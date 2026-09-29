#!/usr/bin/env python3
"""Canonical raw replay and descriptive anchor map; no fitting or interpolation."""
import csv
import json
from pathlib import Path
import statistics
import subprocess

from run_capacity_search import ROOT,OUT,PLAN,INVENTORY,ANCHORS,load_plan,inventory,sha
from analyze_rate_dvfs_gate import read_csv,summarize


def write_csv(path,rows):
    fields=list(dict.fromkeys(k for row in rows for k in row))
    with path.open('w',newline='') as target:
        w=csv.DictWriter(target,fieldnames=fields);w.writeheader()
        for row in rows:w.writerow({k:json.dumps(v,separators=(',',':')) if isinstance(v,(dict,list)) else v for k,v in row.items()})


def mean(rows,key):
    values=[r.get(key) for r in rows]
    return statistics.mean(values) if values and all(isinstance(v,(float,int)) for v in values) else None


def sd(rows,key):
    return statistics.stdev(r[key] for r in rows) if len(rows)>=2 and all(isinstance(r.get(key),(int,float)) for r in rows) else None


def main():
    plan=load_plan();inv=inventory();state=inv.get('campaign_state',{'runs':[],'frequencies':{},'status':'NOT_STARTED'})
    summaries={};mismatches=[]
    for decision in state['runs']:
        d=OUT/decision['run_id']
        if not (d/'summary.json').exists():continue
        m=json.loads((d/'manifest.json').read_text());s=json.loads((d/'summary.json').read_text())
        if s.get('integrity_status')=='VALID':
            raw=summarize(m,read_csv(d/'per_frame.csv.gz'),read_csv(d/'power_trace.csv.gz'))
            for key,value in raw.items():
                if s.get(key)!=value:mismatches.append({'run_id':d.name,'field':key,'stored':s.get(key),'replay':value})
            expected={'K':8,'C':2,'batch_size':1,'CUDA_Graph':False,'requested_freq_MHz':decision['frequency_MHz'],
                      'admission_fps_per_stream':decision['r'],'measurement_seconds':60,'plan_sha256':sha(PLAN),
                      'inputs':plan['inputs'],'child_returncode':0,'frequency_restore_ok':True,'status_finalized':True}
            for key,value in expected.items():
                if m.get(key)!=value:mismatches.append({'run_id':d.name,'field':'manifest.'+key,'stored':m.get(key),'expected':value})
        summaries[d.name]=s
    before=inv['existing_sha256_before'];after={p:sha(ROOT/p) if (ROOT/p).is_file() else None for p in before}
    changed=[p for p in before if before[p]!=after[p]]
    inv['existing_sha256_after']=after;inv['preservation']={'status':'PASS' if not changed else 'FAIL','files':len(before),'changed_paths':changed}
    inv['raw_replay_mismatches']=mismatches
    INVENTORY.write_text(json.dumps(inv,indent=2)+'\n')
    details=[];anchor_map=[]
    for f in ANCHORS:
        fs=state['frequencies'].get(str(f),{})
        stable_r=fs.get('candidate_stable_r');unstable_r=fs.get('candidate_unstable_r')
        endpoints={}
        for role,r in [('stable',stable_r),('unstable',unstable_r)]:
            ids=[x['run_id'] for x in state['runs'] if x['frequency_MHz']==f and x['r']==r] if r is not None else []
            rows=[summaries[i] for i in ids if i in summaries];endpoints[role]=rows
            if r is None:continue
            detail={'frequency_MHz':f,'endpoint_role':role,'admission_r_per_stream':r,'aggregate_admission_FPS':8*r,
                    'planned_attempts':len(ids),'finalized_attempts':len(rows),'run_ids':ids,
                    'integrity_by_repeat':[s.get('integrity_status') for s in rows],
                    'stability_by_repeat':[s.get('queue_classification','INVALID') for s in rows],
                    'frontend_by_repeat':[s.get('supply_status','UNAVAILABLE') for s in rows],
                    'hardware_by_repeat':[s.get('hardware_status','UNAVAILABLE') for s in rows],
                    'OC3_by_repeat':[s.get('OC3_delta') for s in rows],
                    'g_B_by_repeat':[s.get('g_B') for s in rows],
                    'completed_FPS_by_repeat':[s.get('aggregate_completed_fps') for s in rows],
                    'per_stream_by_repeat':[s.get('per_stream') for s in rows]}
            # Means only for three valid runs; no invalid-run omission to rescue a boundary.
            valid=len(rows)==3 and all(s['integrity_status']=='VALID' for s in rows)
            for field in ['aggregate_completed_fps','min_per_stream_completed_fps','mean_per_stream_completed_fps','per_stream_fps_spread',
                          'g_B','source_pending_slope','frontend_pending_slope','frontend_ready_deficit_fraction','avg_power_W',
                          'active_energy_J','energy_per_frame_J','temperature','OC3_delta','actual_freq_mean_MHz','active_concurrency_mean']:
                detail[field+'_mean']=mean(rows,field) if valid else None
                detail[field+'_sd']=sd(rows,field) if valid else None
            details.append(detail)
        allrows=endpoints['stable']+endpoints['unstable']
        expected_count=3*(int(stable_r is not None)+int(unstable_r is not None))
        integrity_ok=(fs.get('status')=='MEASUREMENTS_COMPLETE' and expected_count>0 and len(allrows)==expected_count
                      and all(s['integrity_status']=='VALID' and s.get('PROCESS_LIFECYCLE')=='PASS' and s.get('pipeline_audit_status')=='PASS' for s in allrows))
        consistency=integrity_ok and all(s['queue_stable'] for s in endpoints['stable']) and all(not s['queue_stable'] for s in endpoints['unstable'])
        contaminated=any(s.get('supply_status')=='FRONTEND_LIMITED' for s in allrows)
        status='INCONCLUSIVE'
        if integrity_ok and not mismatches and not changed:
            if contaminated:status='FRONTEND_CONTAMINATED'
            elif consistency:
                status='UPPER_CENSORED' if stable_r==30 and unstable_r is None else 'LOWER_CENSORED' if stable_r is None and unstable_r==1 else 'CONFIRMED' if unstable_r==stable_r+1 else 'INCONCLUSIVE'
        stable_ok=(len(endpoints['stable'])==3 and all(s['integrity_status']=='VALID' and s['queue_stable'] for s in endpoints['stable']))
        unstable_ok=(len(endpoints['unstable'])==3 and all(s['integrity_status']=='VALID' and not s['queue_stable'] for s in endpoints['unstable']))
        sr=endpoints['stable'] if stable_ok else [];ur=endpoints['unstable'] if unstable_ok else []
        row={'frequency_MHz':f,'highest_stable_r_per_stream':stable_r if stable_ok else None,
             'highest_stable_aggregate_admission_FPS':8*stable_r if stable_ok else None,
             'completed_FPS_at_stable_boundary':mean(sr,'aggregate_completed_fps'),'min_stream_FPS':mean(sr,'min_per_stream_completed_fps'),
             'lowest_unstable_r_per_stream':unstable_r if unstable_ok else None,'completed_FPS_at_unstable_point':mean(ur,'aggregate_completed_fps'),
             'g_B_stable':mean(sr,'g_B'),'g_B_unstable':mean(ur,'g_B'),'avg_power_W_at_stable':mean(sr,'avg_power_W'),
             'J_per_frame_at_stable':mean(sr,'energy_per_frame_J'),
             'latency_p95_ms_at_stable':statistics.mean(s['latency_ms']['p95'] for s in sr) if sr else None,
             'OC3_mean':mean(sr,'OC3_delta'),'OC3_mean_scope':'stable boundary, three repetitions',
             'frontend_status':'FRONTEND_LIMITED' if contaminated else 'NORMAL' if allrows and all(s.get('supply_status')=='NORMAL' for s in allrows) else 'UNAVAILABLE',
             'boundary_status':status,'candidate_stable_r':stable_r,'candidate_unstable_r':unstable_r,
             'stable_integrity_by_repeat':[s['integrity_status'] for s in endpoints['stable']],
             'unstable_integrity_by_repeat':[s['integrity_status'] for s in endpoints['unstable']],
             'stable_flags_by_repeat':[s.get('queue_stable') for s in endpoints['stable']],
             'unstable_flags_by_repeat':[s.get('queue_stable') for s in endpoints['unstable']],
             'stable_frontend_by_repeat':[s.get('supply_status') for s in endpoints['stable']],
             'unstable_frontend_by_repeat':[s.get('supply_status') for s in endpoints['unstable']],
             'stable_OC3_by_repeat':[s.get('OC3_delta') for s in endpoints['stable']],
             'unstable_OC3_by_repeat':[s.get('OC3_delta') for s in endpoints['unstable']],
             'stable_completed_FPS_sd':sd(sr,'aggregate_completed_fps'),'stable_power_W_sd':sd(sr,'avg_power_W')}
        anchor_map.append(row)
    write_csv(OUT/'boundary_summary.csv',details or [{'status':'no boundary measurements'}])
    write_csv(OUT/'capacity_anchor_map.csv',anchor_map)
    valid=sum(s['integrity_status']=='VALID' for s in summaries.values())
    observed=[r for r in anchor_map if r['boundary_status']=='CONFIRMED']
    nonmonotonic=[(a['frequency_MHz'],b['frequency_MHz']) for a,b in zip(observed,observed[1:]) if b['highest_stable_r_per_stream']<a['highest_stable_r_per_stream']]
    protection=[f for f in ANCHORS if any(s['requested_freq_MHz']==f and s.get('OC3_delta',0)>0 for s in summaries.values())]
    frontend=[f for f in ANCHORS if any(s['requested_freq_MHz']==f and s.get('supply_status')=='FRONTEND_LIMITED' for s in summaries.values())]
    fmt=lambda v:'N/A' if v is None else f'{v:.4f}' if isinstance(v,float) else str(v)
    lines=['# K8/C2 Local Frequency–Capacity Anchor Characterization','',
           f'Campaign status: {state["status"]}. Adaptively planned {len(state["runs"])}; finalized {len(summaries)}; VALID {valid}; INVALID {len(summaries)-valid}. No extra smoke, automatic retry or unplanned frequency.',
           '', 'Frequency inventory: supported54..1575 MHz step9; default allowed315..1575 MHz, F_raw141 states. Only nine approved anchors measured. No voltage table was measured: these are GPU frequency states, not strict voltage OPPs.',
           '', 'K8/C2, eight distinct fixed videos at logical30 FPS each; common integer r=1..30, TensorRT FP16 B1, unchanged RT-DETR/preprocessing, MAXN fixed. B=logical admitted−completed, g_B canonical final active30s, stable threshold0.5 frames/s with valid/no-drop/no-cap. Warm-up excluded; active60s then drain. OC3 is protection annotation, not invalidity. VDD_GPU energy only active interval; J/frame only stable. Latency p95 uses admitted active-source cohort including drain completions, unchanged canonical scope.',
           '', '1575 MHz alone uses K8 historical r21 stable/r27 unstable for search initialization, never pooled into new endpoint statistics. Other frequencies search independently. Reported highest stable is the adjacent endpoint established by integer binary search and three-repeat confirmation, not exhaustive testing of all admission rates or a proof of monotonic service. r0/r31 are algorithm sentinels, never workloads or measurements.',
           '', 'Boundary values are means of three valid consistent endpoint repetitions. Mixed endpoints stay INCONCLUSIVE; candidate locations and every repeat label are retained in boundary_summary.csv and the map. Any endpoint frontend limitation marks FRONTEND_CONTAMINATED and cannot establish clean inference capacity. An unstable search point away from the final boundary is retained diagnostically and does not automatically invalidate a clean confirmed boundary.',
           '', '| MHz | stable r | stable offered FPS | completed FPS | next unstable r | g_B stable / unstable | frontend | GPU W | J/frame | stable OC3 mean | boundary |',
           '|---:|---:|---:|---:|---:|---|---|---:|---:|---:|---|']
    for x in anchor_map:
        lines.append('| '+' | '.join([str(x['frequency_MHz']),fmt(x['highest_stable_r_per_stream']),fmt(x['highest_stable_aggregate_admission_FPS']),fmt(x['completed_FPS_at_stable_boundary']),fmt(x['lowest_unstable_r_per_stream']),fmt(x['g_B_stable'])+' / '+fmt(x['g_B_unstable']),x['frontend_status'],fmt(x['avg_power_W_at_stable']),fmt(x['J_per_frame_at_stable']),fmt(x['OC3_mean']),x['boundary_status']])+' |')
    lines+=['',f'Confirmed sampled-frequency decreases: {nonmonotonic or "none among confirmed anchors"}. No monotonic constraint, smoothing, interpolation or fitting applied.',
            f'Frequencies with any FRONTEND_LIMITED run (including non-boundary search): {frontend}.',
            f'Frequencies with any PROTECTION_LIMITED run: {protection}.',
            '', 'Interpretation: this is finite-duration Local end-to-end sustainable-capacity evidence at discrete offered workloads. Protection and concurrent decode/preprocessing resource sharing remain system behavior. Do not claim a GPU-only capacity, exact theoretical boundary or extrapolate between anchors. Boundary powers occur at different offered loads and cannot establish equal-service energy efficiency.',
            '', 'Repeat diagnostics:']
    for row in details:
        lines.append('- '+json.dumps({k:row[k] for k in ['frequency_MHz','endpoint_role','admission_r_per_stream','run_ids','integrity_by_repeat','stability_by_repeat','frontend_by_repeat','OC3_by_repeat','g_B_by_repeat','completed_FPS_by_repeat']}))
    lines+=['',f'Raw replay mismatches: {json.dumps(mismatches)}.',f'Existing artifact preservation: {inv["preservation"]}.',
            '', 'Invalid runs retained: '+json.dumps([{'run_id':s['run_id'],'errors':s.get('errors',[])} for s in summaries.values() if s['integrity_status']!='VALID']),
            '', 'Next-stage frequency refinement is a recommendation only; no extra frequency runs, equal-service comparison, longer confirmation, F_eff selection or controller implementation is included. Review inconclusive/contaminated anchors first; among clean confirmed neighbors report their discrete admission change without estimating an intermediate capacity.']
    for a,b in zip(anchor_map,anchor_map[1:]):
        if a['boundary_status']==b['boundary_status']=='CONFIRMED':
            lines.append(f'- Candidate refinement interval {a["frequency_MHz"]}..{b["frequency_MHz"]} MHz: observed stable offered rates {a["highest_stable_aggregate_admission_FPS"]} -> {b["highest_stable_aggregate_admission_FPS"]} FPS; intermediate capacity unmeasured.')
    (OUT/'gate_verdict.md').write_text('\n'.join(lines)+'\n')
    (OUT/'final_git_status.txt').write_text(subprocess.check_output(['git','status','--short','--branch'],cwd=ROOT,text=True))
    print(json.dumps({'planned':len(state['runs']),'completed':len(summaries),'valid':valid,'raw_replay_mismatches':len(mismatches),'preservation':inv['preservation'],'boundaries':[(r['frequency_MHz'],r['candidate_stable_r'],r['candidate_unstable_r'],r['boundary_status']) for r in anchor_map]}))
    return 1 if changed or mismatches else 0


if __name__=='__main__':raise SystemExit(main())
