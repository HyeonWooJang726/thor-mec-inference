#!/usr/bin/env python3
"""D100 A/B paired raw replay, source-normalized timely service as primary."""
import argparse
import hashlib
import inspect
import json
from pathlib import Path
import traceback
from map_common import ROOT,OUT,PLAN,sha,load_plan,proven_analysis as prior_analysis,prior,canonical

read_csv,flatten,write_csv=prior_analysis.read_csv,prior_analysis.flatten,prior_analysis.write_csv
aggregate=prior_analysis.canonical_analysis.aggregate


def summary_source():
    s=inspect.getsource(prior_analysis.summarize);rep=prior.hybrid.replace_once
    s=rep(s,"t0,target,'B',D)","t0,target,m['supply_mode'],D)")
    first="        ef=m.get('edge_final',{});dropids="
    last="        check(not any(m.get(k) for k in ('forced_drop'"
    if s.count(first)!=1 or s.count(last)!=1:raise RuntimeError('Frozen Edge audit changed')
    a,b=s.index(first),s.index(last)
    block=s[a:b]
    guard="        if edge:\n"+''.join('    '+line+'\n' for line in block.splitlines())
    guard+="        else:\n"
    guard+="            check(m.get('edge_usage')=='NOT_USED' and m.get('edge_ready',{}).get('status')=='NOT_USED_NO_CONNECTION','A Edge connection evidence')\n"
    guard+="            check(m.get('edge_final')=={'status':'NOT_USED'} and m.get('edge_threads_exited') and not m.get('edge_path_errors'),'A Edge lifecycle')\n"
    s=s[:a]+guard+s[b:]
    s=rep(s,"experiment='EXPIRED_WORK_PRUNING'","experiment='D100_TIMELY_CAPACITY_MAP'")
    return s


ns=dict(prior_analysis.__dict__)
exec(compile(summary_source(),'<D100-pruning-replay-A-B>','exec'),ns)
_summarize=ns['summarize']


def summarize(m,frames,power):
    s=_summarize(m,frames,power)
    if m.get('deadline_ms')!=100 or m.get('supply_mode') not in ('A','B'):
        s['errors'].append('D100/supply mode mismatch')
        s.update(integrity_status='INVALID',validity='INVALID',pipeline_audit_status='FAIL')
    s['worst_stream_timely_FPS']=s.get('minimum_stream_timely_FPS')
    s['edge_usage']='NOT_USED' if m.get('edge_r')==0 else 'USED'
    # Exact admitted-set identity, including zero-phase due offset, independent of placement.
    cohort=sorted((int(r['stream_id']),int(r['frame_id']),int(r['logical_arrival_ns'])-m['active_start_ns'])
        for r in frames if r.get('phase')=='active' and int(r.get('admitted') or 0))
    s['admitted_identity_sha256']=hashlib.sha256(json.dumps(cohort,separators=(',',':')).encode()).hexdigest()
    return s


COMPARE=('timely_FPS','worst_stream_timely_FPS','TIR_source','worst_stream_TIR','expired_drop_FPS',
    'late_completed_FPS','raw_completed_FPS','local_active_completed_FPS','edge_active_completed_FPS',
    'local_queue_ms_p50','local_queue_ms_p95','local_queue_ms_p99','edge_E2E_ms_p50',
    'edge_E2E_ms_p95','edge_E2E_ms_p99','unfinished_at_active_end','unfinished_after_drain',
    'VIN_J_per_timely_frame','VIN_W','OC3_delta','g_B_L','g_B_E','g_U_H','g_U_L','g_U_E')


def paired(results):
    pairs=[];streams=[]
    for target in (160,200,240):
        for repeat in (1,2,3):
            rr={s['supply_mode']:s for s in results if s['target_service_FPS']==target and s['repeat']==repeat}
            a,b=rr.get('A',{}),rr.get('B',{})
            valid=all(s.get('integrity_status')=='VALID' for s in (a,b))
            same=bool(a.get('admitted_identity_sha256')) and a.get('admitted_identity_sha256')==b.get('admitted_identity_sha256')
            p=dict(target_service_FPS=target,repeat=repeat,A_run_id=a.get('run_id'),B_run_id=b.get('run_id'),
                integrity_status='VALID' if valid and same else 'INVALID',admitted_IDs_identical=same)
            af,bf=flatten(a),flatten(b)
            for k in COMPARE:
                av,bv=af.get(k),bf.get(k)
                p['A_'+k]=av;p['B_'+k]=bv
                p['delta_'+k]=bv-av if p['integrity_status']=='VALID' and av is not None and bv is not None else None
            pairs.append(p)
            sa={r['stream_id']:r for r in a.get('per_stream',[])};sb={r['stream_id']:r for r in b.get('per_stream',[])}
            for sid in range(8):
                entry=dict(target_service_FPS=target,repeat=repeat,stream_id=sid,integrity_status=p['integrity_status'])
                for k in ('admitted_frames','timely_FPS','TIR_source','expired_drop_FPS','late_completed_FPS'):
                    av,bv=sa.get(sid,{}).get(k),sb.get(sid,{}).get(k)
                    entry['A_'+k]=av;entry['B_'+k]=bv
                    entry['delta_'+k]=bv-av if p['integrity_status']=='VALID' and av is not None and bv is not None else None
                streams.append(entry)
    return pairs,streams


def verdict(pairs):
    if len(pairs)!=3 or any(p['integrity_status']!='VALID' for p in pairs):return 'INCONCLUSIVE'
    d=[(p['delta_timely_FPS'],p['delta_worst_stream_timely_FPS']) for p in pairs]
    if all(a>0 and w>0 for a,w in d):return 'HYBRID_TIMELY_CAPACITY_GAIN'
    if all(a<0 and w<0 for a,w in d):return 'LOCAL_BETTER'
    if all(a<=0 and w<=0 for a,w in d):return 'NO_EDGE_TIMELY_GAIN'
    return 'INCONCLUSIVE'


def verify_lifecycle(m,c):
    for k in ('run_id','repeat','cell','supply_mode','target_service_FPS','deadline_ms','local_r','edge_r'):
        if m.get(k)!=c[k]:raise ValueError('Condition mismatch '+k)
    if m.get('requested_freq_MHz')!=1575 or m.get('execution_manifest_sha256')!=sha(PLAN):raise ValueError('Plan/frequency provenance')
    if m.get('child_returncode')!=0 or m.get('PROCESS_LIFECYCLE')!='PASS':raise ValueError('Process exit')
    if not all(m.get(k) for k in ('status_finalized','frequency_restore_ok','active_phase_completed','drain_completed','cleanup_started','cleanup_completed')):raise ValueError('Lifecycle/drain/restore')
    pre=OUT/'frequency_preflight.json';pf=json.loads(pre.read_text())
    if pf.get('status')!='PASS' or pf.get('plan_sha256')!=sha(PLAN) or m.get('frequency_preflight',{}).get('sha256')!=sha(pre):raise ValueError('Preflight')
    if (m.get('pin_readback_Hz',{}).get('min_freq'),m.get('pin_readback_Hz',{}).get('max_freq'))!=(1575000000,1575000000):raise ValueError('Pin readback')


def analyze(output):
    if output.exists():raise RuntimeError('New analysis directory required')
    plan=load_plan();before={str(PLAN):sha(PLAN)};results=[]
    for c in plan['order']:
        d=OUT/c['run_id']
        before.update({str(p):sha(p) for p in d.rglob('*') if p.is_file()})
        try:
            m=json.loads((d/'manifest.json').read_text());verify_lifecycle(m,c)
            s=summarize(m,read_csv(d/'per_frame.csv.gz'),read_csv(d/'power_trace.csv.gz'))
            saved=json.loads((d/'summary.json').read_text())
            for key in ('integrity_status','source_frames','admitted_frames','expired_dropped_frames','completed_frames','timely_completed_frames','admitted_identity_sha256'):
                if saved.get(key)!=s.get(key):raise ValueError('Stored/raw replay mismatch '+key)
        except Exception:s=dict(integrity_status='INVALID',errors=[traceback.format_exc()])
        s.update({k:c[k] for k in ('run_id','cell','repeat','supply_mode','deadline_ms','target_service_FPS','order_index')});results.append(s)
    pairs,stream_pairs=paired(results)
    if not all(sha(Path(p))==digest for p,digest in before.items()):raise RuntimeError('Inputs changed during replay')
    output.mkdir(parents=True,exist_ok=False)
    flat=[flatten(s) for s in results]
    streams=[dict(run_id=s['run_id'],cell=s['cell'],repeat=s['repeat'],integrity_status=s['integrity_status'],**r)
        for s in results for r in s.get('per_stream',[])]
    write_csv(output/'per_run_metrics.csv',flat)
    if streams:write_csv(output/'per_stream_metrics.csv',streams)
    write_csv(output/'paired_comparison.csv',pairs);write_csv(output/'paired_stream_comparison.csv',stream_pairs)
    write_csv(output/'condition_metrics.csv',aggregate(flat,['cell']))
    if streams:write_csv(output/'condition_stream_metrics.csv',aggregate(streams,['cell','stream_id']))
    write_csv(output/'paired_summary.csv',aggregate(pairs,['target_service_FPS']))
    verdicts=[dict(target_service_FPS=t,verdict=verdict([p for p in pairs if p['target_service_FPS']==t])) for t in (160,200,240)]
    with (output/'replay.json').open('x') as f:json.dump(results,f,indent=2)
    with (output/'gate_verdict.md').open('x') as f:
        f.write('# D100 timely capacity-source map\n\nSame-campaign paired repeats, all paths use identical waiting-only pruning. Primary: per-stream/worst-stream timelyFPS and source-normalized worst-streamTIR. Source denominator14400/1800; expired remains failure. Drain completions included. B=assigned-completed; U=B-expired, no raw stability claim from pruning. VIN energy excludes Edge/drain. No significance claim or arbitrary timely-good threshold.\n\n')
        for v in verdicts:f.write(f'- S{v["target_service_FPS"]}: {v["verdict"]}\n')
        f.write('\nPer-stream A/B differences, every repeat, invalids and ties remain visible in the CSVs. Local sufficiency at160 is quantified by timely shortfall, not a new PASS threshold. Historical FIFO/pruning runs are not pooled.\n')
    with (output/'verification.json').open('x') as f:json.dump(dict(preservation='PASS',input_sha256=before,
        planned=18,valid=sum(s['integrity_status']=='VALID' for s in results),paired_admission_ID_audit=[dict(target=p['target_service_FPS'],repeat=p['repeat'],identical=p['admitted_IDs_identical']) for p in pairs]),f,indent=2)
    print(json.dumps(verdicts,indent=2))


if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,required=True);a=ap.parse_args();analyze(a.output)
