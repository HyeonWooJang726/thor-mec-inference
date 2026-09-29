#!/usr/bin/env python3
"""Read-only replay of historical evidence plus isolated profiles; no fitted capacity."""
import csv
import gzip
import importlib.util
import json
import math
from pathlib import Path
import statistics as st
import subprocess
import sys

from profile_isolated import ROOT,OUT,FREQS,sha,plan,write
spec=importlib.util.spec_from_file_location('canonical_capacity_replay',ROOT/'scripts/rate_dvfs_gate/analyze_rate_dvfs_gate.py')
canonical=importlib.util.module_from_spec(spec);spec.loader.exec_module(canonical)

def read(p):
    opener=gzip.open if str(p).endswith('.gz') else open
    with opener(p,'rt',newline='') as f:return list(csv.DictReader(f))

def csv_out(name,rows):
    fields=list(dict.fromkeys(k for x in rows for k in x))
    with (OUT/name).open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader()
        w.writerows({k:json.dumps(v,separators=(',',':')) if isinstance(v,(dict,list)) else v for k,v in x.items()} for x in rows)

def avg(rows,key):return st.mean(x[key] for x in rows)
def getstat(rows,key,sub):return st.mean(x[key][sub] for x in rows)
def mean_sd(v):return {'mean':st.mean(v),'sample_sd':st.stdev(v) if len(v)>1 else None}
def close(a,b):return math.isclose(a,b,rel_tol=1e-12,abs_tol=1e-12)
def label(pred,stable):return ('TRUE_FEASIBLE' if stable else 'FALSE_FEASIBLE') if pred else ('FALSE_INFEASIBLE' if stable else 'TRUE_INFEASIBLE')
def fmt(v):return 'N/A' if v is None else f'{v:.3f}' if isinstance(v,float) else str(v)

def replay_inflight(p):
    ext=p.get('external_inflight')
    if not ext:return {'status':'UNAVAILABLE'}
    repo=Path(ext['repository']);base=Path(ext['root'])
    assert all(sha(path)==h for path,h in ext['files_sha256_before'].items())
    selection=json.loads((base/'combined_manifest.json').read_text())
    stored=json.loads((base/'analysis.json').read_text());config=json.loads((base/'config.json').read_text())
    assert selection['primary_oc_filter'] is False
    assert json.loads((base/'validation.json').read_text())['validation']=='PASS'
    assert [x['run_id'] for x in selection['runs']]==[f'run{i:02d}' for i in range(1,13)]
    metrics={str(o):[] for o in [0.0,.25,.5,.75]};perrun=[];total_rows=0;total_pairs=0
    for item in selection['runs']:
        d=repo/item['path'];assert sha(d/'raw.csv')==item['raw_sha256']
        assert sha(d/'artifact_hashes.json')==item['artifact_sha256']
        hashes=json.loads((d/'artifact_hashes.json').read_text())['sha256']
        for n in ['raw.csv','analysis.json','config.json','request_counts.json']:
            assert sha(d/n)==hashes[n]
        rows=read(d/'raw.csv');a=json.loads((d/'analysis.json').read_text());total_rows+=len(rows)
        assert len(rows)==512 and len(a['pairs'])==256
        index={(int(x['pair_id']),x['condition']):x for x in rows};assert len(index)==len(rows)
        observed={str(o):[] for o in [0.0,.25,.5,.75]}
        for pair in a['pairs']:
            sid=pair['pair_id'];s=index[sid,'serial'];o=index[sid,'overlap'];offset=float(o['offset_fraction']);total_pairs+=1
            keys=['A_input_sha256','B_input_sha256','engine_sha256','A_resource_id','B_resource_id','A_worker_id','B_worker_id','planned_offset_ns','offset_fraction','randomized_order']
            assert all(s[k]==o[k] and s[k]!='' for k in keys)
            assert s['engine_sha256']==p['engine']['sha256']
            assert s['A_input_sha256']==s['B_input_sha256']==config['core']['matrix']['A_input']['sha256']
            for row in [s,o]:
                assert row['complete']=='true'
                assert int(row['A_service_ns'])==int(row['A_completion_ns'])-int(row['A_start_ns'])
                assert int(row['B_service_ns'])==int(row['B_completion_ns'])-int(row['B_start_ns'])
                for who in ['A','B']:assert row[who+'_request_success']==row[who+'_execute_success']=='true'
            eligible=offset!=.75 and s['validity']==o['validity']=='VALID'
            assert eligible==pair['eligible']
            if eligible:
                assert float(s['realized_overlap_ns'])==0 and int(s['B_start_ns'])>=int(s['A_completion_ns'])
                assert int(o['A_completion_ns'])>int(o['B_start_ns']) and o['a_complete_at_action']=='false'
                assert float(o['cuda_service_overlap_ns'])>0 and float(o['cuda_execution_envelope_overlap_ns'])>0
                assert 0<=int(o['actual_offset_ns'])-int(o['planned_offset_ns'])<=int(o['timing_tolerance_ns'])
            delta=int(o['A_service_ns'])-int(s['A_service_ns']);actual=int(o['actual_offset_ns'])
            planned=max(0,int(o['A_completion_ns'])-int(o['reference_ns'])-int(o['planned_offset_ns']))-max(0,int(s['A_completion_ns'])-int(s['reference_ns'])-int(s['planned_offset_ns']))
            aligned=max(0,int(o['A_completion_ns'])-int(o['reference_ns'])-actual)-max(0,int(s['A_completion_ns'])-int(s['reference_ns'])-actual)
            ratio=int(o['A_service_ns'])/int(s['A_service_ns'])
            assert delta==pair['Delta_S_A_ns'] and planned==pair['Delta_R_A_planned_ns'] and aligned==pair['Delta_R_A_actual_aligned_ns']
            assert close(ratio,pair['relative_slowdown_ratio'])
            if eligible or offset==.75:observed[str(offset)].append([delta,planned,aligned,ratio-1,delta/a['S0_ns'],float(delta>0)])
        for offset,values in observed.items():
            means=[st.mean(x[j] for x in values) for j in range(6)];metrics[offset].append(means)
            idx=int(item['run_id'][-2:])-1
            assert len(values)==stored['by_offset'][offset]['n_per_run'][idx]
            assert all(close(x,y) for x,y in zip(means,stored['by_offset'][offset]['run_means'][idx]))
            perrun.append({'run_id':item['run_id'],'offset_fraction':float(offset),'pairs':len(values),'Delta_S_A_ms':means[0]/1e6,'relative_slowdown':means[3],'positive_fraction':means[5]})
    result=[]
    for offset,values in metrics.items():
        means=[st.mean(x[j] for x in values) for j in range(6)]
        for j,k in enumerate(['Delta_S_A_ns','Delta_R_A_planned_ns','Delta_R_A_actual_aligned_ns','relative_slowdown','Delta_S_over_S0','positive_fraction']):
            assert close(means[j],stored['by_offset'][offset]['equal_run_means'][k])
        result.append({'offset_fraction':float(offset),'Delta_S_A_ms':means[0]/1e6,'relative_slowdown':means[3],
                       'positive_run_means':sum(x[0]>0 for x in values),'runs':len(values),
                       'pairs':sum(x['pairs'] for x in perrun if x['offset_fraction']==float(offset)),
                       'role':'primary predeclared offset' if offset=='0.5' else 'late diagnostic only' if offset=='0.75' else 'secondary offset'})
    assert all(sha(path)==h for path,h in ext['files_sha256_before'].items())
    return {'status':'RAW_ARITHMETIC_AND_AGGREGATION_REPLAY_PASS','source_root':str(base),'source_rows':total_rows,'paired_trials':total_pairs,
            'complete_selected_runs':12,'external_files_preserved':len(ext['files_sha256_before']),
            'environment':'MAXN; DVFS unlocked315..1575 MHz; not an anchor baseline','engine_sha256':p['engine']['sha256'],
            'input':'fixed Warehouse000 Camera0000 real preprocessed tensor, differs from K8 videos',
            'scope':'historical pair eligibility and post-treatment selection retained; no new p-value/bootstrap, kernel overlap or practical scheduler claim; OC not filtered',
            'offset_results':result,'per_run_results':perrun,'historical_oc_diagnostics':json.loads((base/'oc_diagnostics.json').read_text())}

def main():
    p=plan();checks=[];profiles={};all_profile=[]
    # Baseline means cannot be silently salvaged from fewer repetitions.
    for f in FREQS:
        rr=[]
        for decision in [x for x in p['profiling_order'] if x['frequency_MHz']==f]:
            d=OUT/decision['run_id'];m=json.loads((d/'manifest.json').read_text());s=json.loads((d/'summary.json').read_text())
            assert m['child_returncode']==0 and s['integrity_status']=='VALID' and m['frequency_restore_ok']
            assert m['C']==1 and m['batch_size']==1 and not m['CUDA_Graph'] and m['engine']==p['engine']
            assert m['input_inventory_sha256']==p.get('frozen_inventory_sha256',sha(OUT/'INPUT_INVENTORY.md'))
            raw=read(d/'latency_samples.csv.gz');act=[x for x in raw if x['phase']=='measurement'];warm=[x for x in raw if x['phase']=='warmup']
            assert len(act)==s['measurement_count'] and len(warm)==s['warmup_count'] and len(warm)>=100
            assert (int(warm[-1]['completion_ns'])-int(warm[0]['start_ns']))/1e9>=5
            assert all(int(x['completion_ns'])>int(x['start_ns']) for x in raw)
            assert all(int(a['completion_ns'])<=int(b['start_ns']) for a,b in zip(raw,raw[1:]))
            values=[(int(x['completion_ns'])-int(x['start_ns']))/1e6 for x in act]
            assert all(close(v,float(x['service_ms'])) for v,x in zip(values,act))
            replay=canonical.quantiles(values)
            assert all(close(replay[k],s['service_ms'][k]) for k in replay)
            elapsed=(m['measurement_end_ns']-m['measurement_start_ns'])/1e9
            assert elapsed>=10 and close(elapsed,s['elapsed_seconds'])
            assert close(len(act)/elapsed,s['measured_C1_inference_only_throughput'])
            pp=[x for x in read(d/'power_trace.csv.gz') if m['measurement_start_ns']<=int(x['timestamp_ns'])<=m['measurement_end_ns']]
            assert pp and all(int(x['min_freq_Hz'])==int(x['max_freq_Hz'])==f*1000000 for x in pp)
            assert close(st.mean(float(x['actual_freq_MHz']) for x in pp),s['actual_freq_mean_MHz'])
            rr.append(s);all_profile.append(s)
        assert len(rr)==3
        t=avg([{'t':x['service_ms']['mean']} for x in rr],'t')
        profiles[f]={'frequency_MHz':f,'T_iso_mean_ms':t,'T_iso_run_means_ms':[x['service_ms']['mean'] for x in rr],
                     'T_iso_sample_SD_ms':st.stdev(x['service_ms']['mean'] for x in rr),
                     'A_ISO':1000/t,'B_NAIVE_C2':2000/t,
                     'A_ISO_by_repeat':[1000/x['service_ms']['mean'] for x in rr],
                     'B_NAIVE_C2_by_repeat':[2000/x['service_ms']['mean'] for x in rr],
                     'C1_measured_throughput_diagnostic':avg(rr,'measured_C1_inference_only_throughput'),
                     'C2_inference_only_strong_baseline':'UNAVAILABLE','profile_run_ids':[x['run_id'] for x in rr],
                     'profile_OC3_by_repeat':[x['OC3_delta'] for x in rr],'profile_actual_frequency_by_repeat':[x['actual_freq_mean_MHz'] for x in rr],
                     'profile_hardware_by_repeat':[x['hardware_status'] for x in rr],
                     'empirical_hardware_status':'PROTECTION_LIMITED' if f==1575 else 'CLEAN'}
    # Exact canonical summary replay, with old files never written.
    cap=ROOT/'results/local_capacity_characterization';inventory=json.loads((cap/'frequency_inventory.json').read_text())
    groups={};summaries={}
    for x in inventory['campaign_state']['runs']:
        d=cap/x['run_id'];m=json.loads((d/'manifest.json').read_text());s=json.loads((d/'summary.json').read_text())
        replay=canonical.summarize(m,canonical.read_csv(d/'per_frame.csv.gz'),canonical.read_csv(d/'power_trace.csv.gz'))
        bad=[k for k,v in replay.items() if s.get(k)!=v]
        if bad:raise RuntimeError('canonical replay mismatch '+d.name+' '+str(bad))
        assert s['integrity_status']=='VALID' and m['child_returncode']==0 and s['frequency_restore_ok']
        groups.setdefault((x['frequency_MHz'],x['r']),[]).append(s);summaries[d.name]=s
    boundaries=[];endkeys=set();models=[]
    for anchor in read(cap/'capacity_anchor_map.csv'):
        f=int(anchor['frequency_MHz']);rs=int(anchor['highest_stable_r_per_stream']);ru=int(anchor['lowest_unstable_r_per_stream'])
        sr=groups[f,rs];ur=groups[f,ru]
        assert len(sr)==len(ur)==3 and all(x['queue_stable'] for x in sr) and all(not x['queue_stable'] for x in ur)
        clean=f in FREQS
        if clean:assert anchor['boundary_status']=='CONFIRMED' and all(x['supply_status']=='NORMAL' for x in sr+ur)
        row={'frequency_MHz':f,'primary_included':clean,'exclusion_reason':'' if clean else 'FRONTEND_CONTAMINATED',
             'confirmed_stable_offered_FPS':8*rs,'confirmed_unstable_offered_FPS':8*ru,
             'boundary_status':anchor['boundary_status'],'empirical_hardware_status':'PROTECTION_LIMITED' if f==1575 else 'CLEAN',
             'stable_run_ids':[x['run_id'] for x in sr],'unstable_run_ids':[x['run_id'] for x in ur],
             'stable_g_B_by_repeat':[x['g_B'] for x in sr],'unstable_g_B_by_repeat':[x['g_B'] for x in ur],
             'stable_frontend_by_repeat':[x['supply_status'] for x in sr],'unstable_frontend_by_repeat':[x['supply_status'] for x in ur],
             'stable_OC3_by_repeat':[x['OC3_delta'] for x in sr],'unstable_OC3_by_repeat':[x['OC3_delta'] for x in ur]}
        boundaries.append(row)
        if clean:
            endkeys.update([(f,rs),(f,ru)]);models.append({**profiles[f],'confirmed_stable_offered_FPS':8*rs,'confirmed_unstable_offered_FPS':8*ru})
    cases=[]
    for (f,r),ss in sorted(groups.items()):
        if f not in FREQS:continue
        assert len(set(x['queue_stable'] for x in ss))==1 and all(x['supply_status']=='NORMAL' for x in ss)
        stable=ss[0]['queue_stable'];demand=8*r
        for model in ['A_ISO','B_NAIVE_C2']:
            pp=profiles[f];pred=demand<=pp[model];outcome=label(pred,stable)
            cases.append({'model':model,'frequency_MHz':f,'demand_FPS':demand,'r_per_stream':r,'primary_endpoint':(f,r) in endkeys,
                          'predicted_capacity_FPS':pp[model],'model_prediction':'PREDICTED_FEASIBLE' if pred else 'PREDICTED_INFEASIBLE',
                          'observation':'OBSERVED_STABLE' if stable else 'OBSERVED_UNSTABLE','decision':outcome,
                          'decisions_by_profile_repeat':[label(demand<=v,stable) for v in pp[model+'_by_repeat']],
                          'observed_repeats':len(ss),'empirical_run_ids':[x['run_id'] for x in ss],
                          'g_B_mean':avg(ss,'g_B'),'g_B_by_repeat':[x['g_B'] for x in ss],
                          'active_end_backlog_mean':avg(ss,'backlog_at_active_end'),'active_end_backlog_by_repeat':[x['backlog_at_active_end'] for x in ss],
                          'completed_FPS_mean':avg(ss,'aggregate_completed_fps'),'completed_FPS_by_repeat':[x['aggregate_completed_fps'] for x in ss],
                          'queue_wait_mean_ms':getstat(ss,'queue_wait_ms','mean'),'queue_wait_p95_ms':getstat(ss,'queue_wait_ms','p95'),
                          'queue_wait_by_repeat':[x['queue_wait_ms'] for x in ss],
                          'service_mean_ms':getstat(ss,'service_ms','mean'),'frontend_by_repeat':[x['supply_status'] for x in ss],
                          'hardware_by_repeat':[x['hardware_status'] for x in ss],'empirical_hardware_status':'PROTECTION_LIMITED' if f==1575 else 'CLEAN',
                          'OC3_by_repeat':[x['OC3_delta'] for x in ss]})
    confusion=[]
    for model in ['A_ISO','B_NAIVE_C2']:
        for scope in ['PRIMARY_ENDPOINT_CONDITIONS','PRIMARY_ENDPOINT_RUNS','SECONDARY_ALL_OBSERVED_CONDITIONS']:
            selected=[x for x in cases if x['model']==model and (x['primary_endpoint'] or scope.startswith('SECONDARY'))]
            for outcome in ['FALSE_FEASIBLE','FALSE_INFEASIBLE','TRUE_FEASIBLE','TRUE_INFEASIBLE']:
                cc=[x for x in selected if x['decision']==outcome]
                confusion.append({'model':model,'scope':scope,'decision':outcome,'count':sum(x['observed_repeats'] if scope.endswith('_RUNS') else 1 for x in cc),
                                  'total':sum(x['observed_repeats'] if scope.endswith('_RUNS') else 1 for x in selected),
                                  'workloads_FPS':sorted(set(x['demand_FPS'] for x in cc)),'frequency_MHz':sorted(set(x['frequency_MHz'] for x in cc)),
                                  'condition_keys':[[x['frequency_MHz'],x['demand_FPS']] for x in cc],
                                  'protected_frequency_MHz':1575,'note':'1575 empirical observations PROTECTION_LIMITED; conditions equally weighted; repeated frames are not independent experiments'})
    # Selection is evaluated on all endpoint demands without interpolating capacity.
    cleanb=[x for x in boundaries if x['primary_included']];demands=sorted({x[k] for x in cleanb for k in ['confirmed_stable_offered_FPS','confirmed_unstable_offered_FPS']})
    fmap=[]
    for demand in demands:
        empirical=next((x['frequency_MHz'] for x in cleanb if x['confirmed_stable_offered_FPS']>=demand),None)
        for model in ['A_ISO','B_NAIVE_C2']:
            selected=next((f for f in FREQS if profiles[f][model]>=demand),None)
            ss=groups.get((selected,demand//8),[]) if selected else []
            ee=groups.get((empirical,demand//8),[]) if empirical else []
            row={'model':model,'demand_FPS':demand,'model_lowest_frequency_MHz':selected,'empirical_map_lowest_frequency_MHz':empirical,
                 'decision':'FREQUENCY_DECISION_MISMATCH' if selected!=empirical else 'MATCH',
                 'within_confirmed_map_demand_coverage':empirical is not None,
                 'model_selected_frequency_by_profile_repeat':[next((f for f in FREQS if profiles[f][model+'_by_repeat'][rep]>=demand),None) for rep in range(3)],
                 'empirical_scope':'lowest confirmed-stable demand envelope; exact equal-demand measurement separately flagged',
                 'empirical_none_reason':'NO_CONFIRMED_FEASIBLE_ANCHOR' if empirical is None else '',
                 'model_selected_direct_run_ids':[x['run_id'] for x in ss],'empirical_selected_direct_run_ids':[x['run_id'] for x in ee],
                 'model_selected_direct_stability':[x['queue_classification'] for x in ss],
                 'empirical_selected_direct_stability':[x['queue_classification'] for x in ee],
                 'model_selected_direct_g_B':[x['g_B'] for x in ss],'model_selected_direct_end_backlog':[x['backlog_at_active_end'] for x in ss],
                 'model_selected_hardware':'PROTECTION_LIMITED' if selected==1575 else 'CLEAN' if selected else 'N/A',
                 'empirical_selected_hardware':'PROTECTION_LIMITED' if empirical==1575 else 'CLEAN' if empirical else 'N/A',
                 'actual_equal_workload_power_comparison_available':bool(ss and ee and selected!=empirical)}
            if ss and ee and selected!=empirical:
                row.update(model_selected_power_W=avg(ss,'avg_power_W'),empirical_selected_power_W=avg(ee,'avg_power_W'),
                           power_difference_model_minus_empirical_W=avg(ss,'avg_power_W')-avg(ee,'avg_power_W'),
                           model_active_energy_J=avg(ss,'active_energy_J'),empirical_active_energy_J=avg(ee,'active_energy_J'),
                           power_comparison_note='observed same offered workload; inspect stability/completed service; unstable energy is not equal-service efficiency',
                           model_completed_FPS=avg(ss,'aggregate_completed_fps'),empirical_completed_FPS=avg(ee,'aggregate_completed_fps'))
            fmap.append(row)
    # Mechanistic supporting evidence: canonical static C experiment, not absent A-in-flight-B.
    support=[];robust=ROOT/'results/c_robustness_gate'
    cg={}
    for d in sorted(robust.glob('CRG_*')):
        m=json.loads((d/'manifest.json').read_text());s=json.loads((d/'summary.json').read_text())
        if m.get('kind')!='primary':continue
        raw=read(d/'per_frame.csv.gz')
        vals=[(int(x['completion_timestamp_ns'])-int(x['inference_start_timestamp_ns']))/1e6 for x in raw if x['phase']=='active' and x['admitted']=='1']
        re=canonical.quantiles(vals)
        assert all(close(re[k],s['service_ms'][k]) for k in re)
        cg.setdefault((m['operating_point'],m['C']),[]).append(s)
    for (point,c),ss in sorted(cg.items()):
        support.append({'operating_point':point,'K':ss[0]['K'],'frequency_MHz':ss[0]['requested_freq_MHz'],'r':ss[0]['admission_fps_per_stream'],'C':c,
                        'service_mean_ms':getstat(ss,'service_ms','mean'),'service_run_means':[x['service_ms']['mean'] for x in ss],
                        'completed_FPS_mean':avg(ss,'aggregate_completed_fps'),'hardware_by_repeat':[x['hardware_status'] for x in ss],
                        'raw_replay':'PASS','interpretation':'static C association, not controlled A-in-flight-B and not causal GPU-kernel proof'})
    # Service distributions of amended RDVG, explicitly separate from current score.
    rdvg=[]
    for d in sorted((ROOT/'results/rate_dvfs_gate').glob('RDVG_B_20260919_*')):
        if not (d.name.rsplit('_',1)[-1].startswith(('P','S')) and d.name.rsplit('_',1)[-1][1:].isdigit()):continue
        m=json.loads((d/'manifest.json').read_text());s=json.loads((d/'summary.json').read_text());raw=read(d/'per_frame.csv.gz')
        vals=[(int(x['completion_timestamp_ns'])-int(x['inference_start_timestamp_ns']))/1e6 for x in raw if x['phase']=='active' and x['admitted']=='1']
        re=canonical.quantiles(vals);assert all(close(re[k],s['service_ms'][k]) for k in re)
        rdvg.append({'run_id':d.name,'K':s['K'],'C':s['C'],'frequency_MHz':s['requested_freq_MHz'],'r':s['admission_fps_per_stream'],'service_ms':s['service_ms'],'supply_status':s['supply_status'],'hardware_status':s['hardware_status']})
    assert len(rdvg)==45
    changed=[k for k,v in p['existing_sha256_before'].items() if not (ROOT/k).is_file() or sha(ROOT/k)!=v]
    assert not changed,'existing artifact changed '+str(changed)
    # Recheck all frozen execution sources and model/video.
    assert all(sha(ROOT/k)==v for k,v in p['execution_hashes'].items())
    for key in ['input','engine']:assert sha(p[key]['path'])==p[key]['sha256']
    inflight=replay_inflight(p)
    verification={'canonical_raw_replay_runs':len(summaries),'isolated_raw_replay_runs':len(all_profile),'c_robustness_service_replay_runs':27,
                  'rate_dvfs_service_replay_runs':len(rdvg),'mismatches':[],'existing_files_sha256_checked':len(p['existing_sha256_before']),'changed_paths':changed,
                  'static_C_support':support,'rate_dvfs_loaded_service_diagnostics':rdvg,
                  'A_in_flight_B':inflight,'new_profile_input_tensor_hashes':sorted({json.loads((OUT/x['run_id']/'manifest.json').read_text())['input_tensor_sha256'] for x in all_profile})}
    write(OUT/'verification.json',verification)
    csv_out('model_predictions.csv',models);csv_out('empirical_boundaries.csv',boundaries);csv_out('decision_cases.csv',cases)
    csv_out('decision_confusion.csv',confusion);csv_out('frequency_decision_map.csv',fmap)
    primary=[x for x in cases if x['primary_endpoint']]
    lines=['# Local Capacity-Model Validity Gate','',
           'Existing fixed-frequency isolated data were insufficient. Added only21 C1 isolated profiles (7 anchors ×3); no full pipeline or capacity rerun. All existing artifacts unchanged. The optional matched C2 inference-only saturation model is UNAVAILABLE. Measured C1 closed-loop throughput is a same-profile diagnostic, not an independent strong C2 baseline.',
           '', '## Prediction and empirical observations',
           'Values use equal-weight means of three isolated run mean service times. Ground truth remains two confirmed offered-workload observations, not an exact capacity. A=1000/T_iso_ms; B=2000/T_iso_ms with naive independent linear scaling. T_iso includes host staging/copies/inference/synchronization; excludes frontend and queue.1575 MHz empirical results are PROTECTION_LIMITED.315/477 are excluded from every primary model score and selection candidate set, retained in empirical_boundaries.csv.',
           '', '| MHz | stable offered / next unstable FPS | T_iso ms ± sample SD | A FPS | B FPS | measured C1 FPS (diagnostic) | isolated OC3 repeats | empirical hardware |',
           '|---:|---|---|---:|---:|---:|---|---|']
    for x in models:lines.append('| '+' | '.join([str(x['frequency_MHz']),f"{x['confirmed_stable_offered_FPS']} / {x['confirmed_unstable_offered_FPS']}",f"{x['T_iso_mean_ms']:.6f} ± {x['T_iso_sample_SD_ms']:.6f}",fmt(x['A_ISO']),fmt(x['B_NAIVE_C2']),fmt(x['C1_measured_throughput_diagnostic']),str(x['profile_OC3_by_repeat']),x['empirical_hardware_status']])+' |')
    lines+=['','## Raw decision confusion','Primary unit:14 equally weighted endpoint conditions; each has3/3 consistent empirical runs. Repeat counts42 are descriptive replication, not independent frame-level tests. No percentage/significance threshold. Feasible iff offered demand <= model capacity.','', '| Model | FALSE_FEASIBLE | FALSE_INFEASIBLE | TRUE_FEASIBLE | TRUE_INFEASIBLE |','|---|---:|---:|---:|---:|']
    for model in ['A_ISO','B_NAIVE_C2']:
        cc=[x for x in confusion if x['model']==model and x['scope']=='PRIMARY_ENDPOINT_CONDITIONS']
        lines.append('| '+model+' | '+' | '.join(str(x['count']) for x in cc)+' |')
    lines+=['','All primary and secondary cases, workload/frequency sets and run IDs are in decision_cases.csv and decision_confusion.csv. Secondary search points are not silently pooled into the primary score.','', '## Every primary endpoint mismatch','', '| Model | MHz | offered FPS | outcome | g_B mean | active-end backlog mean | completed FPS | queue wait mean / p95 ms | frontend | hardware |','|---|---:|---:|---|---:|---:|---:|---|---|---|']
    for x in primary:
        if x['decision'].startswith('FALSE'):
            lines.append('| '+' | '.join([x['model'],str(x['frequency_MHz']),str(x['demand_FPS']),x['decision'],fmt(x['g_B_mean']),fmt(x['active_end_backlog_mean']),fmt(x['completed_FPS_mean']),fmt(x['queue_wait_mean_ms'])+' / '+fmt(x['queue_wait_p95_ms']),'NORMAL',x['empirical_hardware_status']])+' |')
    uncertain=[{k:x[k] for k in ['model','frequency_MHz','demand_FPS','decision','decisions_by_profile_repeat']} for x in cases if len(set(x['decisions_by_profile_repeat']))>1]
    lines+=['','Baseline-repeat sensitivity (every decision changing across the three profile estimates):',json.dumps(uncertain),
            '', '## Frequency decisions',
            'Demand set: union of primary endpoint workloads. Empirical choice uses the confirmed stable-demand envelope, not an interpolated capacity. Exact equal-workload observations are separately identified. A map-supported lower demand is not relabeled as a directly acquired experiment. No confirmed feasible anchor above200 FPS in this evidence; this is not a theorem that all higher demand is impossible.',
            '', '| Demand FPS | model | selected MHz | empirical-map MHz | decision | direct selected-cell stability | selected-cell g_B | selected-cell hardware |','|---:|---|---:|---:|---|---|---|---|']
    for x in fmap:
        lines.append('| '+' | '.join([str(x['demand_FPS']),x['model'],fmt(x['model_lowest_frequency_MHz']),fmt(x['empirical_map_lowest_frequency_MHz']),x['decision'],str(x['model_selected_direct_stability']),str(x['model_selected_direct_g_B']),x['model_selected_hardware']])+' |')
    for model in ['A_ISO','B_NAIVE_C2']:
        allm=[x for x in fmap if x['model']==model];covered=[x for x in allm if x['within_confirmed_map_demand_coverage']]
        lines.append(f"\n{model}: {sum(x['decision']=='FREQUENCY_DECISION_MISMATCH' for x in allm)}/{len(allm)} mismatches across all endpoint demands; {sum(x['decision']=='FREQUENCY_DECISION_MISMATCH' for x in covered)}/{len(covered)} within confirmed map demand coverage.208 FPS has no confirmed-feasible anchor, retained separately. Per-profile-repeat frequency selections are in frequency_decision_map.csv.")
    lines+=['','Exact equal-workload power comparisons (all available mismatches; no estimates):']
    for x in fmap:
        if x['actual_equal_workload_power_comparison_available']:
            lines.append('- '+json.dumps({k:x[k] for k in ['model','demand_FPS','model_lowest_frequency_MHz','empirical_map_lowest_frequency_MHz','model_selected_power_W','empirical_selected_power_W','power_difference_model_minus_empirical_W','model_completed_FPS','empirical_completed_FPS','model_selected_direct_stability','empirical_selected_direct_stability','model_selected_hardware','empirical_selected_hardware']}))
    if not any(x['actual_equal_workload_power_comparison_available'] for x in fmap):lines.append('None; no power/energy consequence estimated.')
    lines+=['','## Service-interference supporting evidence',
            'A-in-flight-B was located in the separate existing main worktree and read without modification. Its frozen combined12-run selection, paired raw service arithmetic, eligibility, engine/input identity and equal-run aggregation were revalidated. This is MAXN/DVFS-unlocked, fixed Warehouse000 input, a different host service boundary (no per-request pinned staging copy), and supporting mechanism only; never pooled into anchor models. Post-treatment eligibility caveats and late-offset diagnostic status remain. No new statistical test, kernel overlap or scheduler-benefit claim. Additional27 C-robustness raw service distributions were replayed with same-operating-point C contrasts. Historical unlocked trtexec summary/report are contextual only; reported multi-stream latency carried an accuracy warning.',
            '', '| Point | MHz | C | service mean ms | completed FPS | hardware repeats |','|---|---:|---:|---:|---:|---|']
    for x in support:lines.append('| '+' | '.join([x['operating_point'],str(x['frequency_MHz']),str(x['C']),fmt(x['service_mean_ms']),fmt(x['completed_FPS_mean']),str(x['hardware_by_repeat'])])+' |')
    lines+=['','In-flight replay: '+json.dumps({k:v for k,v in inflight.items() if k not in ['per_run_results','historical_oc_diagnostics']}),
            '', 'These static C associations additionally support the possibility that isolated service and linear scaling do not transfer. They do not identify a GPU-kernel contention mechanism.45 amended Rate-DVFS service distributions were also replayed (verification.json), kept separate by K/C/frequency/r and never used as isolated samples.',
            '', '## Integrity and scope',json.dumps({k:v for k,v in verification.items() if k not in ['static_C_support','rate_dvfs_loaded_service_diagnostics','A_in_flight_B']}),
            '', 'The baseline repeatedly uses the first real W027 frame with the same engine/preprocessing; the empirical workload uses eight varying videos. No content-dependent or low-load-pacing generalization is established. The three10s profiles do not establish long-duration stationarity. Measurements include actual clock/protection behavior, which can differ between isolated and continuous multi-stream load. The optional matched C2 inference-only saturation baseline is missing; these results do not refute such an unmeasured strong baseline.',
            '', '## Descriptive verdict']
    review=p.get('reviewed_conclusion')
    if review:
        for name,h in review['derived_sha256'].items():assert sha(OUT/name)==h,'reviewed result changed: '+name
        lines.extend([review['verdict'],'',review['interpretation']])
    else:lines.append('PENDING_REVIEW — inspect complete confusion, repeat sensitivity and direct frequency-choice evidence before selecting the user-defined category. No automated threshold or fitted model is introduced.')
    (OUT/'model_gap_verdict.md').write_text('\n'.join(lines)+'\n')
    print(json.dumps({'raw_replay':'PASS','preserved_files':len(p['existing_sha256_before']),
                      'primary_confusion':[x for x in confusion if x['scope']=='PRIMARY_ENDPOINT_CONDITIONS'],
                      'frequency_mismatch_counts':{m:sum(x['model']==m and x['decision']=='FREQUENCY_DECISION_MISMATCH' for x in fmap) for m in ['A_ISO','B_NAIVE_C2']},
                      'frequency_demands':len(demands),'repeat_sensitive_cases':uncertain},indent=2))

if __name__=='__main__':main()
