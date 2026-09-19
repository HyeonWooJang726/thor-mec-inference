#!/usr/bin/env python3
"""Replay canonical raw Gate records; no GPU or clock access."""
import argparse
import csv
import gzip
import json
from pathlib import Path
import statistics

import numpy as np


def read_csv(path):
    with gzip.open(path, 'rt', newline='') as source:
        return list(csv.DictReader(source))


def quantiles(values):
    if not values:
        return {key: None for key in ('mean','p50','p95','p99')}
    return dict(zip(('mean','p50','p95','p99'),
                    [float(np.mean(values)), *map(float,np.percentile(values,[50,95,99]))]))


def queue_slope(frames, start_ns, end_ns, left_key='admission_timestamp_ns', right_key='completion_timestamp_ns'):
    """Exact continuous-time OLS slope of the reconstructed step queue.

    Sum each admitted request's waiting indicator integral. Uniform time
    weighting avoids bias from differing numbers of enqueue/start events.
    """
    duration = (end_ns-start_ns)/1e9
    numerator = 0.0
    for row in frames:
        a = max(int(row[left_key]), start_ns)
        b = min(int(row[right_key]), end_ns)
        if b > a:
            left, right = (a-start_ns)/1e9-duration/2, (b-start_ns)/1e9-duration/2
            numerator += (right*right-left*left)/2
    return numerator/(duration**3/12)


def summarize(manifest, frames, power):
    errors = list(manifest.get('errors', []))
    active = [r for r in frames if r['phase']=='active']
    admitted = [r for r in active if int(r.get('admitted') or 0)]
    finished = [r for r in admitted if r.get('completion_timestamp_ns')]
    t0, t1 = manifest.get('active_start_ns'), manifest.get('active_end_ns')
    summary = {'protocol_version':2,'run_id':manifest['run_id'], 'kind':manifest['kind'],'repeat':manifest.get('repeat'),
               'K':manifest['K'],'C':manifest['C'], 'freq_state':manifest['freq_state'],
               'requested_freq_MHz':manifest['requested_freq_MHz'],
               'admission_fps_per_stream':manifest['admission_fps_per_stream'],
               'source_frames':len(active),'admitted_frames':len(admitted),
               'completed_frames_including_drain':len(finished),
               'errors':errors, 'provenance':'measured',
               'power_scope':'GPU rail VDD_GPU (tegrastats instantaneous channel)',
               'protocol_amendment':'UNIFIED_BACKLOG_B',
               'queue_definition':'B(t) = logical admitted count - inference completion count',
               'hardware_status':'PROTECTION_LIMITED' if manifest.get('OC3_after',0)>manifest.get('OC3_before',0) else 'CLEAN',
               'OC3_delta':manifest.get('OC3_after',0)-manifest.get('OC3_before',0)}
    if t0 is None or t1 is None:
        errors.append('active interval unavailable')
        summary.update(validity='INVALID',integrity_status='INVALID',queue_stable=False,pipeline_audit_status='INCONCLUSIVE')
        return summary
    duration = (t1-t0)/1e9
    active_finished = [r for r in finished if t0 <= int(r['completion_timestamp_ns']) < t1]
    expected = int(duration*30)
    per_stream=[]
    for stream in range(manifest['K']):
        rows=[r for r in active if int(r['stream_id'])==stream]
        if sorted(int(r['frame_id']) for r in rows) != list(range(expected)):
            errors.append(f'stream {stream}: source identity/count mismatch')
        acc=0
        for row in sorted(rows,key=lambda r:int(r['frame_id'])):
            acc += manifest['admission_fps_per_stream']
            decision = acc >=30
            if decision: acc-=30
            if row.get('admitted') in ('',None) or bool(int(row['admitted'])) != decision:
                errors.append(f'stream {stream}: deterministic admission mismatch')
                break
        selected=[r for r in admitted if int(r['stream_id'])==stream]
        complete=[r for r in active_finished if int(r['stream_id'])==stream]
        rate=len(complete)/duration
        per_stream.append({'stream_id':stream,'source_frames':len(rows),
                           'admitted_frames':len(selected),'completed_active':len(complete),
                           'R_k':rate,'eta_k':rate/30})
    if len(finished)!=len(admitted): errors.append('admitted/completed drain accounting mismatch')
    if manifest.get('warmup_inferences_per_worker'):
        warm=[r for r in frames if r['phase']=='warmup']
        if len(warm)!=manifest['C']*manifest['warmup_inferences_per_worker'] or any(not r.get('completion_timestamp_ns') for r in warm):
            errors.append('warm-up accounting mismatch')
    if manifest.get('clean_shutdown') is False:
        errors.append('unclean shutdown')
    for row in admitted:
        names=('logical_arrival_ns','admission_timestamp_ns','b_ns','source_pulled_ns','ready_timestamp_ns',
               'inference_start_timestamp_ns','completion_timestamp_ns')
        if any(row.get(n) in (None,'') for n in names):
            errors.append('missing admitted-frame timestamps'); break
        stamps=[int(row[n]) for n in names]
        if stamps!=sorted(stamps):
            errors.append('frame timestamp ordering mismatch'); break
        if not t0 <= stamps[1] < t1:
            errors.append('admission outside active interval'); break
    for row in active:
        names=('logical_arrival_ns','admission_timestamp_ns','b_ns','source_pulled_ns')
        if all(row.get(n) not in ('',None) for n in names):
            timestamps=[int(row[n]) for n in names]
            if timestamps!=sorted(timestamps):errors.append('decode/admission timing corruption')
        if not int(row.get('admitted') or 0) and any(row.get(n) not in (None,'') for n in
             ('enqueue_timestamp_ns','inference_start_timestamp_ns','completion_timestamp_ns')):
            errors.append('skipped frame entered inference queue'); break
        if not row.get('source_timestamp_ns') or not row.get('source_pulled_ns'):
            # PTS zero is represented as integer 0 or string '0', both valid.
            if row.get('source_timestamp_ns') not in (0,'0') or not row.get('source_pulled_ns'):
                errors.append('source frame decode record missing'); break
    for stream in range(manifest['K']):
        pts=[int(r['source_timestamp_ns']) for r in sorted(active,key=lambda r:int(r['frame_id']))
             if int(r['stream_id'])==stream and r.get('source_timestamp_ns') not in ('',None)]
        if any(b<=a for a,b in zip(pts,pts[1:])): errors.append(f'stream {stream}: source PTS identity not increasing')
        if pts and any(abs(p-(pts[0]+i*10**9//30))>1 for i,p in enumerate(pts)):
            errors.append(f'stream {stream}: source PTS cadence/hidden-drop mismatch')
        timeline=[int(r['logical_arrival_ns']) for r in sorted(active,key=lambda r:int(r['frame_id'])) if int(r['stream_id'])==stream]
        if timeline!=[t0+i*10**9//30 for i in range(expected)]:errors.append(f'stream {stream}: source pacing mismatch')
    if manifest.get('queue_overflow') or manifest.get('forced_drop') or manifest.get('queue_cap_saturation'):
        errors.append('queue overflow/drop/cap saturation')
    summary.update(aggregate_admitted_fps=len(admitted)/duration,
                   aggregate_completed_fps=len(active_finished)/duration,
                   completed_active_frames=len(active_finished),
                   min_per_stream_completed_fps=min(p['R_k'] for p in per_stream),
                   mean_per_stream_completed_fps=statistics.mean(p['R_k'] for p in per_stream),
                   per_stream=per_stream,measurement_seconds=duration)
    if len(finished)==len(admitted) and all(r.get('inference_start_timestamp_ns') for r in admitted):
        slope_start=t1-int(min(30,duration/2)*1e9)
        summary['g_B']=queue_slope(admitted,slope_start,t1)
        events=[]
        for row in admitted:
            events.extend([(int(row['admission_timestamp_ns']),1),(int(row['completion_timestamp_ns']),-1)])
        depth=0; peak=0; end_queue=0
        for stamp,delta in sorted(events):
            depth+=delta
            if depth<0: errors.append('negative reconstructed system backlog B')
            peak=max(peak,depth)
            if stamp<t1: end_queue=depth
        if depth: errors.append('nonzero B after drain')
        summary.update(backlog_peak=peak,backlog_at_active_end=end_queue,backlog_after_drain=depth,
                       queue_wait_ms=quantiles([(int(r['inference_start_timestamp_ns'])-int(r['ready_timestamp_ns']))/1e6 for r in finished]),
                       service_ms=quantiles([(int(r['completion_timestamp_ns'])-int(r['inference_start_timestamp_ns']))/1e6 for r in finished]),
                       latency_ms=quantiles([(int(r['completion_timestamp_ns'])-int(r['logical_arrival_ns']))/1e6 for r in finished]))
    else:
        summary.update(g_B=None)
    try:
        ordered=sorted(power,key=lambda r:int(r['timestamp_ns']))
        stamps=np.array([(int(r['timestamp_ns'])-t0)/1e9 for r in ordered])
        watts=np.array([float(r['measured_power_W']) for r in ordered])
        if len(stamps)<2 or stamps[0]>0 or stamps[-1]<duration or np.any(np.diff(stamps)<=0):
            raise ValueError('power trace does not bracket active interval or is nonmonotonic')
        inside=(stamps>0)&(stamps<duration)
        xs=np.concatenate(([0.],stamps[inside],[duration]))
        ys=np.concatenate(([np.interp(0,stamps,watts)],watts[inside],[np.interp(duration,stamps,watts)]))
        if np.max(np.diff(xs))>.5 or not np.isfinite(ys).all() or np.any(ys<0):
            raise ValueError('power trace gap >0.5 s or invalid measured power')
        energy=float(np.trapz(ys,xs))
        active_power=[r for r in ordered if t0<=int(r['timestamp_ns'])<=t1]
        actual=[float(r['actual_gpu_freq_MHz']) for r in active_power if float(r['actual_gpu_freq_MHz'])>0]
        if not actual: errors.append('FREQUENCY_READBACK_UNAVAILABLE')
        for sec in range(int(duration)):
            if not any(t0+sec*10**9<=int(r['timestamp_ns'])<t0+(sec+1)*10**9 and float(r['actual_gpu_freq_MHz'])>0 for r in active_power):
                errors.append(f'active frequency readback missing in second {sec}')
        if any(int(r['min_freq_Hz'])!=manifest['requested_freq_MHz']*10**6 or
               int(r['max_freq_Hz'])!=manifest['requested_freq_MHz']*10**6 for r in active_power):
            errors.append('requested range not maintained')
        counts=[int(r['OC3_count']) for r in ordered]
        delta=manifest.get('OC3_after',max(counts))-manifest.get('OC3_before',min(counts))
        if delta<0 or any(b<a for a,b in zip(counts,counts[1:])):errors.append('OC3 counter regressed')
        summary.update(avg_power_W=energy/duration,active_energy_J=energy,
                       actual_freq_mean_MHz=statistics.mean(actual) if actual else None,
                       actual_freq_mean_scope='nonzero active-interval observations',
                       temperature=statistics.mean(float(r['temperature_C']) for r in active_power),
                       OC3_delta=delta,hardware_status='PROTECTION_LIMITED' if delta>0 else 'CLEAN',
                       actual_clock_non_target_fraction=sum(f!=manifest['requested_freq_MHz'] for f in actual)/len(actual) if actual else None)
    except (ValueError,KeyError,TypeError) as error:
        errors.append(f'measurement trace: {error}')
    # Stage occupancy is diagnostic only; B is the single primary backlog.
    pipeline_failures=[]
    if finished and len(finished)==len(admitted) and all(r.get('ready_timestamp_ns') and r.get('admission_timestamp_ns') for r in admitted):
        ready_active=[r for r in admitted if t0<=int(r['ready_timestamp_ns'])<t1]
        admitted_active=[r for r in admitted if t0<=int(r['admission_timestamp_ns'])<t1]
        summary.update(source_fps=len(active)/duration,aggregate_ready_fps=len(ready_active)/duration,
                       aggregate_admitted_fps=len(admitted_active)/duration)
        window=t1-int(min(30,duration/2)*1e9)
        front_slopes=[queue_slope([r for r in admitted if int(r['stream_id'])==i],window,t1,'admission_timestamp_ns','ready_timestamp_ns') for i in range(manifest['K'])]
        source_slopes=[queue_slope([r for r in active if int(r['stream_id'])==i and r.get('source_pulled_ns')],window,t1,'logical_arrival_ns','source_pulled_ns') for i in range(manifest['K'])]
        gap=max(0,len(admitted_active)-len(ready_active))/max(1,len(admitted_active))
        bottleneck=(gap>.01 and (sum(front_slopes)>.5 or max(front_slopes)>.2)) or sum(source_slopes)>.5 or max(source_slopes)>.2
        summary.update(frontend_ready_deficit_fraction=gap,frontend_pending_slope=sum(front_slopes),
                       source_pending_slope=sum(source_slopes),frontend_bottleneck=bottleneck,
                       supply_status='FRONTEND_LIMITED' if bottleneck else 'NORMAL',
                       source_to_decode_ms=quantiles([(int(r['source_pulled_ns'])-int(r['logical_arrival_ns']))/1e6 for r in active if r.get('source_pulled_ns')]))
        decoded_active=sum(t0<=int(r['source_pulled_ns'])<t1 for r in active if r.get('source_pulled_ns'))
        started_active=sum(t0<=int(r['inference_start_timestamp_ns'])<t1 for r in admitted if r.get('inference_start_timestamp_ns'))
        summary['stage_diagnostics_at_active_end']={
            'scheduled':len(active),'decoded':decoded_active,'admitted':len(admitted_active),
            'ready':len(ready_active),'started':started_active,'completed':len(active_finished),
            'scheduled_minus_decoded':len(active)-decoded_active,
            'admitted_minus_ready':len(admitted_active)-len(ready_active),
            'ready_minus_started':len(ready_active)-started_active,
            'started_minus_completed':started_active-len(active_finished)}
        service_events=[];area=0.;depth=0;peak=0;previous=t0
        for row in finished:
            start,end=max(t0,int(row['inference_start_timestamp_ns'])),min(t1,int(row['completion_timestamp_ns']))
            if end>start:service_events.extend([(start,1),(end,-1)])
        for stamp,delta in sorted(service_events):
            area+=depth*(stamp-previous)/1e9;depth+=delta;peak=max(peak,depth);previous=stamp
            if depth<0:pipeline_failures.append('negative active concurrency')
        summary.update(active_concurrency_peak=peak,active_concurrency_mean=area/duration,
                       concurrency_scope='host service intervals, not a claim of GPU kernel overlap')
        if peak>manifest['C'] or (len(finished)>100 and manifest['C']>1 and peak<=1):
            pipeline_failures.append('CONCURRENCY_ENFORCEMENT_FAIL')
    if manifest.get('premeasurement_queue_empty') is not True:
        errors.append('premeasurement queue not verified empty')
    summary['pipeline_failures']=pipeline_failures
    summary['validity']='VALID' if not errors else 'INVALID'
    summary['integrity_status']=summary['validity']
    summary['pipeline_audit_status']='FAIL' if pipeline_failures else 'INCONCLUSIVE' if errors else 'PASS'
    summary['supply_status']=summary.get('supply_status','UNAVAILABLE')
    summary['queue_stable']=bool(not errors and summary['g_B'] is not None and summary['g_B']<=.5)
    summary['backlog_stable']=summary['queue_stable']
    summary['queue_classification']=('INVALID' if errors else 'QUEUE_STABLE' if summary['queue_stable'] else 'UNSTABLE')
    summary['energy_per_frame_J']=(summary['active_energy_J']/len(active_finished)
                                  if summary['queue_stable'] and active_finished else None)
    return summary


FIELDS=['protocol_version','K','C','freq_state','requested_freq_MHz','actual_freq_mean_MHz',
        'admission_fps_per_stream','source_fps','aggregate_admitted_fps','aggregate_ready_fps',
        'aggregate_completed_fps','min_per_stream_completed_fps','mean_per_stream_completed_fps',
        'g_B','backlog_at_active_end','backlog_peak','queue_stable','avg_power_W',
        'median_power_W','active_energy_J','energy_per_frame_J','temperature','OC3_delta',
        'integrity_status','hardware_status','supply_status','active_concurrency_peak','active_concurrency_mean',
        'frontend_ready_deficit_fraction','frontend_pending_slope','source_pending_slope','pipeline_audit_status']


def write_csv(path,fields,rows):
    with path.open('w',newline='') as target:
        writer=csv.DictWriter(target,fieldnames=fields,extrasaction='ignore')
        writer.writeheader();writer.writerows(rows)


def evaluate(cells,groups,pipeline_status,complete):
    stable=lambda x:x['queue_stable']=='QUEUE_STABLE'
    unstable=lambda x:x['queue_stable']=='UNSTABLE'
    clear=lambda xs:all(x['integrity_status']=='VALID' and x['queue_stable'] in ('QUEUE_STABLE','UNSTABLE') for x in xs)
    primary=[x for x in cells if x['K']==7]
    evidence={'ADMISSION_GATE':[],'FREQUENCY_CAPACITY_GATE':[],'ENERGY_OPPORTUNITY_GATE':[]}
    boundaries={}
    for freq in ('LOW','MID','HIGH'):
        subset=[x for x in primary if x['freq_state']==freq]
        good=[x for x in subset if stable(x)]
        boundaries[freq]=max((x['admission_fps_per_stream'] for x in good),default=None)
        if clear(subset) and good:
            transition=any(a['admission_fps_per_stream']<b['admission_fps_per_stream'] and stable(a) and unstable(b) for a in subset for b in subset)
            maximum=max(x['aggregate_completed_fps'] for x in subset)
            best=max(x['aggregate_completed_fps'] for x in good)
            if transition and best>=.95*maximum:
                evidence['ADMISSION_GATE'].append({'frequency':freq,'best_stable_fps':best,'max_observed_fps':maximum,'ratio':best/maximum})
    boundary_known=all(boundaries[f] is not None and clear([x for x in primary if x['freq_state']==f]) for f in ('LOW','HIGH'))
    if boundary_known and boundaries['HIGH']-boundaries['LOW']>=3:
        evidence['FREQUENCY_CAPACITY_GATE'].append({'r_star':boundaries,'HIGH_minus_LOW':boundaries['HIGH']-boundaries['LOW']})
    comparisons=[]
    for low in cells:
        for high in cells:
            if (low['K'],low['C'],low['admission_fps_per_stream'])!=(high['K'],high['C'],high['admission_fps_per_stream']):continue
            if low['requested_freq_MHz']>=high['requested_freq_MHz'] or not stable(low) or not stable(high):continue
            lk=(low['K'],low['C'],low['freq_state'],low['admission_fps_per_stream'])
            hk=(high['K'],high['C'],high['freq_state'],high['admission_fps_per_stream'])
            lrep={x['repeat']:x for x in groups[lk] if x['integrity_status']=='VALID'}
            hrep={x['repeat']:x for x in groups[hk] if x['integrity_status']=='VALID'}
            matched=sorted(lrep.keys() & hrep.keys())
            pairs=[(lrep[i],hrep[i]) for i in matched]
            throughput_difference=abs(low['aggregate_completed_fps']-high['aggregate_completed_fps'])/high['aggregate_completed_fps']
            power_ratio=low['median_power_W']/high['median_power_W']
            consistent=len(pairs)>=2 and all(a['avg_power_W']<b['avg_power_W'] and abs(a['aggregate_completed_fps']-b['aggregate_completed_fps'])/b['aggregate_completed_fps']<=.02 for a,b in pairs)
            item={'K':low['K'],'r':low['admission_fps_per_stream'],'lower':low['freq_state'],'higher':high['freq_state'],
                  'throughput_difference_fraction':throughput_difference,'median_power_ratio':power_ratio,
                  'matched_repeats':matched,'consistent':consistent,
                  'energy_per_frame_same_direction':all(a['energy_per_frame_J']<b['energy_per_frame_J'] for a,b in pairs) if pairs else None}
            comparisons.append(item)
            if throughput_difference<=.02 and power_ratio<=.9 and consistent:evidence['ENERGY_OPPORTUNITY_GATE'].append(item)
    verdicts={'PIPELINE_AUDIT':pipeline_status}
    for gate in evidence:
        enough=clear(primary) if gate=='ADMISSION_GATE' else boundary_known if gate=='FREQUENCY_CAPACITY_GATE' else clear(cells)
        verdicts[gate]='PASS' if evidence[gate] else 'FAIL' if complete and enough else 'INCONCLUSIVE'
    final='RATE_DVFS_GATE_PASS' if complete and all(v=='PASS' for v in verdicts.values()) else ', '.join(k+'_FAIL' for k,v in verdicts.items() if v=='FAIL') or 'INCONCLUSIVE'
    return verdicts,final,evidence,boundaries,comparisons


def aggregate(root, execution_plan=None):
    plantext=(root/'EXPERIMENT_PLAN_V2.md').read_text()
    section=plantext.split('## Protocol Amendment — Unified Backlog B(t)\n',1)[1]
    plan=json.loads(section.split('```json\n',1)[1].split('\n```',1)[0])
    if execution_plan:
        plan=json.loads(execution_plan.read_text())
    allowed={x['run_id'] for x in plan['smoke']+plan['order']}
    def output(name):
        return root/(name.replace('.', '_recovery.',1) if execution_plan else name)
    summaries=[];historical=[]
    for directory in sorted(root.glob('RDVG_*')):
        if not (directory/'manifest.json').exists():continue
        manifest=json.loads((directory/'manifest.json').read_text())
        if manifest.get('protocol_amendment')!='UNIFIED_BACKLOG_B' or directory.name not in allowed:
            # Preserve every V1 run byte-for-byte. Exclusion exists only in the V2 index.
            old=json.loads((directory/'summary.json').read_text())
            old.update(protocol_version=manifest.get('protocol_version',1),integrity_status=old.get('validity','INVALID'),
                       hardware_status='PROTECTION_LIMITED' if manifest.get('OC3_after',0)>manifest.get('OC3_before',0) else 'CLEAN',
                       exclusion_reason='OLD_PROTOCOL_ABORT_ON_SOURCE_LAG' if directory.name=='RDVG_V2_20260919_P02' else 'PROTOCOL_V1_ABORT_ON_OC3' if manifest.get('protocol_version',1)==1 and manifest['kind']=='primary' else 'PRE_UNIFIED_BACKLOG_PROTOCOL')
            historical.append(old);continue
        if not (directory/'summary.json').exists():continue
        summary=summarize(manifest,read_csv(directory/'per_frame.csv.gz'),read_csv(directory/'power_trace.csv.gz'))
        # Replay verification is read-only for run-level artifacts.
        saved=json.loads((directory/'summary.json').read_text())
        if saved.get('status_finalized'):
            for key,value in summary.items():
                if key=='pipeline_audit_status':continue
                # Supervisor errors are appended after measurement analysis; a
                # replay encounters them before deriving the same raw errors.
                if key=='errors' and sorted(saved.get(key,[]))==sorted(value):continue
                if saved.get(key)!=value:raise RuntimeError(f'raw replay differs: {directory.name} {key}')
            if saved['child_returncode']!=manifest['child_returncode']:raise RuntimeError('child exit record mismatch')
            summary=saved
        elif summary!=saved:raise RuntimeError('raw replay differs from preserved summary: '+directory.name)
        outcome=plan.get('process_outcome_annotations',{}).get(directory.name)
        if outcome:
            # The historical pre-exit artifacts remain immutable. Final indexing
            # incorporates the explicitly recorded supervisor observation.
            summary=dict(summary,errors=list(summary['errors']))
            summary['process_outcome_annotation']=outcome
            if outcome['nonzero_exit_observed']:
                summary.update(integrity_status='INVALID',validity='INVALID',queue_stable=False,
                               queue_classification='INVALID',energy_per_frame_J=None,
                               pipeline_audit_status='FAIL')
                summary['errors'].append(outcome['reason'])
        summaries.append(summary)
    write_csv(output('aggregate_summary.csv'),['run_id','kind','repeat','exclusion_reason']+FIELDS+['queue_classification','child_returncode','child_exit_signal','PIPELINE_SEMANTICS','PROCESS_LIFECYCLE'],historical+summaries)
    groups={}
    for condition in plan['order']:
        key=(condition['K'],condition['C'],condition['frequency'],condition['r'])
        groups.setdefault(key,[])
    for s in summaries:
        if s['kind'] not in ('primary','sanity'):continue
        key=(s['K'],s['C'],s['freq_state'],s['admission_fps_per_stream'])
        groups[key].append(s)
    cells=[]
    for (k,c,f,r),runs in sorted(groups.items()):
        valid=[s for s in runs if s['integrity_status']=='VALID']
        usable=len(valid)>=2
        cell=dict(protocol_version=2,K=k,C=c,freq_state=f,admission_fps_per_stream=r,
                  requested_freq_MHz={'LOW':945,'MID':1260,'HIGH':1575}[f],
                  attempted_repetitions=len(runs),valid_repetitions=len(valid),invalid_repetitions=len(runs)-len(valid))
        flags=[s['queue_stable'] for s in valid]
        cell['integrity_status']='VALID' if usable else 'INCONCLUSIVE'
        cell['queue_stable']=('QUEUE_STABLE' if all(flags) else 'UNSTABLE' if not any(flags) else 'MIXED') if usable else 'INCONCLUSIVE'
        cell['clean_runs']=sum(s['hardware_status']=='CLEAN' for s in valid)
        cell['protection_limited_runs']=sum(s['hardware_status']=='PROTECTION_LIMITED' for s in valid)
        cell['OC3_occurrence_rate']=cell['protection_limited_runs']/len(valid) if valid else None
        cell['hardware_status']='PROTECTION_LIMITED' if cell['protection_limited_runs'] else 'CLEAN' if valid else 'UNMEASURED'
        cell['frontend_limited_runs']=sum(s.get('supply_status')=='FRONTEND_LIMITED' for s in valid)
        cell['supply_status']='FRONTEND_LIMITED' if cell['frontend_limited_runs'] else 'NORMAL' if valid else 'UNMEASURED'
        cell['per_stream_completed_fps']=json.dumps([statistics.mean(s['per_stream'][i]['R_k'] for s in valid) for i in range(k)]) if usable else None
        cell['pipeline_audit_status']='FAIL' if any(s.get('pipeline_audit_status')=='FAIL' for s in runs) else 'PASS' if usable and all(s.get('pipeline_audit_status')=='PASS' for s in valid) else 'INCONCLUSIVE'
        for field in FIELDS:
            if field in cell:continue
            vals=[s.get(field) for s in valid]
            cell[field]=statistics.mean(vals) if usable and vals and all(isinstance(v,(int,float)) for v in vals) else None
        cell['median_power_W']=statistics.median(s['avg_power_W'] for s in valid) if usable else None
        cells.append(cell)
    extra=['attempted_repetitions','valid_repetitions','invalid_repetitions','clean_runs','protection_limited_runs','OC3_occurrence_rate','frontend_limited_runs','per_stream_completed_fps']
    write_csv(output('operating_map.csv'),FIELDS+extra,cells)
    experiment=[s for s in summaries if s['kind'] in ('primary','sanity')]
    complete=len(experiment)==45
    pipeline='FAIL' if any(s.get('pipeline_audit_status')=='FAIL' for s in summaries) else 'PASS' if summaries and all(s.get('pipeline_audit_status')=='PASS' for s in summaries if s['integrity_status']=='VALID') and all(x['pipeline_audit_status']=='PASS' for x in cells) else 'INCONCLUSIVE'
    verdicts,final,evidence,boundaries,comparisons=evaluate(cells,groups,pipeline,complete)
    lines=['# Rate/DVFS Gate V2 verdict','',f'Final: **{final}**','',
           'Prior runs are historical, untouched and excluded. V2 P02 exclusion_reason=OLD_PROTOCOL_ABORT_ON_SOURCE_LAG. Original plans/code/root reports are preserved in pre_backlog_amendment_snapshot.tar.gz.',
           '', '| Gate | Verdict |','|---|---|']+[f'| {k} | {v} |' for k,v in verdicts.items()]
    lines+=['','B(t)=logical admitted count minus inference completion count. Logical source and admission use the 30-FPS frame index, independent of decoder progress. Admission→completion includes every unfinished stage. Source/decode/ready lag is diagnostic only, not an abort or invalidation. Primary stability uses only g_B<=0.5 frames/s in the final active 30 s, with no cap/drop and valid integrity.',
            '',f'Observed r_star (FPS/stream): {boundaries}. None means no stable tested point; no extrapolation below the grid.',
            '','Condition means below use integrity-valid repetitions; at least two required, all valid repeats must agree on stability. Median power is the median of per-run active average power. OC3 does not exclude a valid repetition.',
            '','| K | MHz | r | completed FPS | min stream FPS | g_B | state | avg GPU W | J/frame | clean/protected | frontend-limited | valid/attempted |',
            '|---:|---:|---:|---:|---:|---:|---|---:|---:|---|---:|---|']
    def fmt(x):return 'unavailable' if x is None else f'{x:.3f}'
    for x in cells:
        lines.append(f"| {x['K']} | {x['requested_freq_MHz']} | {x['admission_fps_per_stream']} | {fmt(x['aggregate_completed_fps'])} | {fmt(x['min_per_stream_completed_fps'])} | {fmt(x['g_B'])} | {x['queue_stable']} | {fmt(x['avg_power_W'])} | {fmt(x['energy_per_frame_J'])} | {x['clean_runs']}/{x['protection_limited_runs']} | {x['frontend_limited_runs']} | {x['valid_repetitions']}/{x['attempted_repetitions']} |")
    for gate,items in evidence.items():
        lines+=['',gate+' witnesses:']+(['- '+json.dumps(x) for x in items] or ['- None.'])
    lines+=['','All same-service energy comparisons (including nonqualifying pairs):']+['- '+json.dumps(x) for x in comparisons]
    invalid=[s for s in summaries if s['integrity_status']!='VALID']
    lines+=['','Invalid V2 runs (preserved; no retries):']+(['- '+s['run_id']+': '+'; '.join(s['errors']) for s in invalid] or ['- None.'])
    lines+=['',f'Planned campaign observed: primary {sum(s["kind"]=="primary" for s in summaries)}/36; K6 sanity {sum(s["kind"]=="sanity" for s in summaries)}/9.',
            f'Integrity-valid campaign runs: {sum(s["integrity_status"]=="VALID" for s in experiment)}; PROTECTION_LIMITED valid runs: {sum(s["integrity_status"]=="VALID" and s["hardware_status"]=="PROTECTION_LIMITED" for s in experiment)}.',
            'Power scope: measured GPU rail VDD_GPU. Energy is active-interval only; J/frame only for stable runs. Actual frequency means exclude recorded idle zeros; non-target clocks are retained, not invalidated due to OC3.',
            'No energy fitting/controller or additional workloads. MAXN fixed; default GPC range restored after each run. See per-run manifests for exact restoration and errors.']
    lines+=['','Interpretation: these are complete Local SYSTEM capacities. FRONTEND_LIMITED conditions are SYSTEM_CAPACITY_LIMITED_BY_FRONTEND, not GPU-only capacity measurements. A frequency-dependent stable boundary supports SYSTEM_CAPACITY_GPU_SENSITIVE without locating its bottleneck solely inside TensorRT.']
    output('gate_verdict.md').write_text('\n'.join(lines)+'\n')
    return verdicts


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[2]/'results/rate_dvfs_gate')
    parser.add_argument('--execution-plan',type=Path)
    args=parser.parse_args()
    print(json.dumps(aggregate(args.root,args.execution_plan)))
