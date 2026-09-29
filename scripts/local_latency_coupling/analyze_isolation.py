#!/usr/bin/env python3
"""Immutable raw replay and paired Local-latency stage accounting; no experiments."""
import argparse
import hashlib
import json
from pathlib import Path
import statistics
import traceback
import types
import numpy as np
from isolation_common import ROOT,OUT,PLAN,load_plan,decorate,sha,proven_analysis as existing
read_csv,flatten,write_csv,finite=existing.read_csv,existing.flatten,existing.write_csv,existing.finite

_ns=dict(existing.original.h.__dict__,decorate=decorate)
exec(compile(existing.adapted_summary_source(),'<isolation-placement-validation-only>','exec'),_ns)
fn=existing.summarize
_summary=types.FunctionType(fn.__code__,dict(fn.__globals__,_replay=_ns['summarize']))


def local_rows(frames):
    result={}
    for r in frames:
        if r.get('phase')=='active' and r.get('placement')=='LOCAL':
            key=(int(r['stream_id']),int(r['frame_id']))
            if key in result:raise ValueError('Duplicate Local frame identity')
            result[key]=r
    return result


def durations_ns(r):
    a,ready,start,end=(int(r[k]) for k in ('logical_arrival_ns','ready_timestamp_ns','inference_start_timestamp_ns','completion_timestamp_ns'))
    if not a<=ready<=start<=end:raise ValueError('Local timestamp order')
    return dict(frontend=ready-a,queue=start-ready,service=end-start,E2E=end-a,pre_service=start-a)


def summarize(manifest,frames,power):
    s=_summary(manifest,frames,power)
    s['experiment']='LOCAL_LATENCY_COUPLING_ISOLATION'
    if s['integrity_status']!='VALID':return s
    rows=local_rows(frames);ds=[durations_ns(r) for _,r in sorted(rows.items())]
    s['local_frame_identity_sha256']=hashlib.sha256(json.dumps(sorted(rows),separators=(',',':')).encode()).hexdigest()
    s['local_pre_service_ms']=existing.original.h.quantiles([d['pre_service']/1e6 for d in ds])
    s['local_frontend_ms']=existing.original.h.quantiles([d['frontend']/1e6 for d in ds])
    s['stage_identity_exact']=all(d['E2E']==d['frontend']+d['queue']+d['service'] for d in ds)
    return s


LATENCY_KEYS=tuple(f'{group}_ms_{q}' for group in ('local_E2E','local_queue') for q in ('p50','p95','p99'))
SERVICE_KEYS=tuple('local_service_ms_'+q for q in ('mean','p50','p95','p99'))
METRICS=LATENCY_KEYS+SERVICE_KEYS+(
    'local_completed_FPS','g_B_L','backlogs_L_active_end_backlog','local_pre_service_ms_p95',
    'local_frontend_ms_p95','rails_VDD_GPU_avg_power_W','rails_VDD_CPU_SOC_MSS_avg_power_W',
    'rails_VIN_avg_power_W','OC3_delta','temperature')+tuple(
    f'{g}_ms_{q}' for g in ('edge_client_pending','edge_send','edge_server_queue','edge_inference') for q in ('mean','p50','p95','p99'))


def classify(rows,paired):
    """Conservative predeclared directional evidence, not a significance test.

    Increased queue is not proof service slowdown cannot cause queueing. The
    automatic supported label therefore additionally requires no increase in the
    measured service mean/p50/p95/p99 in each round. Otherwise unresolved.
    No posthoc similarity margin; exact matching summaries are the only automatic
    sufficient NOT_SUPPORTED case. Other apparent similarities remain inconclusive.
    """
    if len(rows)!=6 or any(r.get('integrity_status')!='VALID' for r in rows):return 'INCONCLUSIVE'
    if {(r['repeat'],r['supply_mode']) for r in rows}!={(i,m) for i in (1,2,3) for m in ('A','B')}:return 'INCONCLUSIVE'
    if any(not r.get('stage_identity_exact') for r in rows) or len(paired)!=3 or any(not p.get('identity_match') for p in paired):return 'INCONCLUSIVE'
    deltas=[]
    for repeat in (1,2,3):
        a=next(r for r in rows if r['repeat']==repeat and r['supply_mode']=='A')
        b=next(r for r in rows if r['repeat']==repeat and r['supply_mode']=='B')
        keys=LATENCY_KEYS+SERVICE_KEYS+('local_pre_service_ms_p95',)
        if any(not finite(x.get(k)) for x in (a,b) for k in keys):return 'INCONCLUSIVE'
        deltas.append({k:b[k]-a[k] for k in keys})
    if all(d[k]==0 for d in deltas for k in LATENCY_KEYS):return 'LATENCY_COUPLING_NOT_SUPPORTED'
    rising=all(d[k]>0 for d in deltas for k in LATENCY_KEYS+('local_pre_service_ms_p95',))
    service_not_slower=all(d[k]<=0 for d in deltas for k in SERVICE_KEYS)
    if rising and service_not_slower:return 'LATENCY_COUPLING_SUPPORTED'
    return 'INCONCLUSIVE'


def paired_decomposition(a,b,repeat):
    aa,bb=local_rows(a),local_rows(b)
    if set(aa)!=set(bb) or len(aa)!=11040:raise ValueError('Matched Local frame IDs/count differ')
    deltas={k:[] for k in ('frontend','queue','service','E2E','pre_service')}
    for key in sorted(aa):
        da,db=durations_ns(aa[key]),durations_ns(bb[key])
        dd={k:db[k]-da[k] for k in da}
        if dd['E2E']!=dd['frontend']+dd['queue']+dd['service']:raise ValueError('Stage accounting corruption')
        for k in deltas:deltas[k].append(dd[k]/1e6)
    return dict(repeat=repeat,identity_match=True,matched_frames=len(aa),
        **{f'mean_B_minus_A_{k}_ms':statistics.mean(v) for k,v in deltas.items()},
        stage_identity_exact=True,
        interpretation='Paired integer-ns duration identity; mean deltas additive, percentiles NOT additive; no service-counterfactual causal model')


def analyze(output):
    if output.exists():raise RuntimeError('Refuse analysis overwrite')
    plan=load_plan();before={str(PLAN):sha(PLAN)};rows=[];frames_by_run={};errors=[]
    for c in plan['order']:
        d=OUT/c['run_id'];s={}
        try:
            for p in d.rglob('*'):
                if p.is_file():before[str(p)]=sha(p)
            m=json.loads((d/'manifest.json').read_text())
            for key,value in (('run_id',c['run_id']),('repeat',c['repeat']),('supply_mode',c['supply_mode']),('local_r',23),('edge_r',c['edge_r']),('target_service_FPS',c['target_service_FPS']),('requested_freq_MHz',1413)):
                if m.get(key)!=value:raise ValueError('Frozen condition mismatch: '+key)
            if m.get('execution_manifest_sha256')!=sha(PLAN) or m.get('inputs')!=plan['inputs']:raise ValueError('Plan/source mapping mismatch')
            frames=read_csv(d/'per_frame.csv.gz');power=read_csv(d/'power_trace.csv.gz')
            s=summarize(m,frames,power)
            if m.get('child_returncode')!=0 or m.get('PROCESS_LIFECYCLE')!='PASS' or any(m.get(k) is not True for k in ('status_finalized','frequency_restore_ok','active_phase_completed','drain_completed','cleanup_started','cleanup_completed')):raise ValueError('Process/lifecycle/restore failure')
            pre=OUT/'frequency_preflight.json';before[str(pre)]=sha(pre);record=json.loads(pre.read_text())
            if record.get('status')!='PASS' or record.get('plan_sha256')!=sha(PLAN) or m.get('frequency_preflight',{}).get('sha256')!=sha(pre):raise ValueError('Preflight provenance mismatch')
            pin=m.get('pin_readback_Hz',{})
            if (pin.get('min_freq'),pin.get('max_freq'))!=(1413000000,1413000000):raise ValueError('Pin readback mismatch')
            for k in ('child_returncode','frequency_restore_ok','PROCESS_LIFECYCLE','status_finalized'):s[k]=m[k]
            frames_by_run[c['repeat'],c['supply_mode']]=frames
        except Exception:
            error=traceback.format_exc();errors.append(dict(run_id=c['run_id'],error=error))
            s.update(run_id=c['run_id'],integrity_status='INVALID',queue_stable=False,errors=s.get('errors',[])+[error])
        s.update(cell=c['cell'],repeat=c['repeat'],supply_mode=c['supply_mode'],order_index=c['order_index'])
        rows.append(s)
    paired=[]
    for repeat in (1,2,3):
        try:paired.append(paired_decomposition(frames_by_run[repeat,'A'],frames_by_run[repeat,'B'],repeat))
        except Exception:paired.append(dict(repeat=repeat,identity_match=False,error=traceback.format_exc()))
    flat=[flatten(s) for s in rows];verdict=classify(flat,paired);differences=[]
    for repeat in (1,2,3):
        a=next(r for r in flat if r['repeat']==repeat and r['supply_mode']=='A')
        b=next(r for r in flat if r['repeat']==repeat and r['supply_mode']=='B')
        for k in METRICS:
            good=a['integrity_status']==b['integrity_status']=='VALID' and finite(a.get(k)) and finite(b.get(k))
            differences.append(dict(repeat=repeat,metric=k,A=a.get(k),B=b.get(k),B_minus_A=b[k]-a[k] if good else None))
    output.mkdir(parents=True,exist_ok=False)
    for name,data in [('per_run_metrics.csv',flat),('condition_summary.csv',existing.aggregate(flat)),('paired_differences.csv',differences),('matched_stage_decomposition.csv',paired)]:write_csv(output/name,data)
    with (output/'replay.json').open('x') as f:json.dump(rows,f,indent=2)
    with (output/'latency_verdict.md').open('x') as f:
        f.write('# Local-latency isolation pilot\n\n'+verdict+'\n\n')
        f.write('Six planned IDs are retained, with per-run values and mean/sample SD(ddof=1). All Local frame IDs are frozen B200 identities, at1413MHz and184FPS; only Edge0/16 changes. Common decode/resize240FPS. A has no network. No historical observations are pooled.\n\n')
        f.write('Latency population: active-logical frames including drain; Local and Edge E2E use Thor clock; server durations use Edge clock. No percentile sums/differences are interpreted as additive stage decomposition. Paired identical Local frames obey E2E=frontend+queue+service exactly in integer ns; only mean stage deltas are additive.\n\n')
        f.write('SUPPORTED requires 3/3 positive B−A Local E2E and queue p50/p95/p99 and pre-service p95, with no service mean/p50/p95/p99 increase in any round. If service also slows, queueing amplification cannot be excluded, so INCONCLUSIVE. This is directional descriptive evidence, not statistical significance or identification of CPU/memory/network/GPU mechanism.\n\n')
        f.write('No numerical similarity tolerance was supplied or fitted. Exact zero differences in all Local E2E/queue quantiles in3/3 are a sufficient NOT_SUPPORTED case; otherwise small/mixed differences are INCONCLUSIVE, not proof of equivalence. Review effect magnitudes, repeat variability, order, OC3 and temperature together. VIN is Thor module+carrier input only; rails are never summed.\n\n')
        f.write('| Run | Integrity | Local FPS | Local p95 E2E ms | Local p95 queue ms | Local p95 service ms | g_B,L | OC3 | GPU temperature C |\n|---|---|---:|---:|---:|---:|---:|---:|---:|\n')
        for r in flat:f.write('| '+' | '.join(str(r.get(k,'N/A')) for k in ('run_id','integrity_status','local_completed_FPS','local_E2E_ms_p95','local_queue_ms_p95','local_service_ms_p95','g_B_L','OC3_delta','temperature'))+' |\n')
    assert all(Path(p).is_file() and sha(p)==digest for p,digest in before.items()),'Input preservation failure'
    with (output/'verification.json').open('x') as f:json.dump(dict(verdict=verdict,input_sha256=before,preservation='PASS',errors=errors),f,indent=2)
    print(verdict)

if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--output',type=Path,required=True)
    analyze(ap.parse_args().output)
