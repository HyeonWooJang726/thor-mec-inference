#!/usr/bin/env python3
"""Independent terminal accounting; expired work is never a completion or timely success."""
import argparse
from collections import defaultdict
import csv
import json
import math
from pathlib import Path
import statistics as st
import traceback
from pruning_common import ROOT,OUT,PLAN,sha,load_plan,canonical,canonical_analysis,decorate

existing=canonical_analysis.existing
h=existing.original.h
read_csv,quantiles,flatten,write_csv=h.read_csv,h.quantiles,existing.flatten,existing.write_csv
val=h.val


def summarize(m,frames,power):
    errors=list(m.get('errors',[]))
    s=dict(run_id=m['run_id'],kind=m.get('kind'),repeat=m.get('repeat'),errors=errors,
           hardware_status='PROTECTION_LIMITED' if m.get('OC3_after',0)>m.get('OC3_before',0) else 'CLEAN',
           OC3_before=m.get('OC3_before'),OC3_after=m.get('OC3_after'))
    try:
        t0,t1=m['active_start_ns'],m['active_end_ns'];duration=(t1-t0)/1e9
        if duration!=60:raise ValueError('Active duration is not60s')
        target,D=m['target_service_FPS'],m['deadline_ms']
        source=[r for r in frames if r['phase']=='active']
        rows=[r for r in source if int(r.get('admitted') or 0)==1]
        def check(ok,msg):
            if not ok:errors.append(msg)
        def ordered(r,keys):
            xs=[val(r,k) for k in keys]
            return all(x is not None for x in xs) and xs==sorted(xs)
        check(len(source)==14400 and len(rows)==target*60,'source/admission count')
        for sid in range(8):
            sr=sorted([r for r in source if int(r['stream_id'])==sid],key=lambda r:int(r['frame_id']))
            check([int(r['frame_id']) for r in sr]==list(range(1800)),f'source IDs {sid}')
            pts=[val(r,'source_timestamp_ns') for r in sr]
            check(bool(pts) and all(v is not None and abs(v-(pts[0]+i*10**9//30))<=1 for i,v in enumerate(pts)),f'PTS {sid}')
        for r in source:
            expected=decorate(dict(stream_id=int(r['stream_id']),frame_id=int(r['frame_id']),
                logical_arrival_ns=val(r,'logical_arrival_ns')),t0,target,'B',D)
            for key in ('placement','admitted','absolute_deadline_ns','edge_request_id','edge_release_target_ns'):
                actual=r.get(key)
                if key!='placement':actual=int(actual) if actual not in ('',None) else None
                check(actual==expected.get(key),'placement/deadline identity '+key)
            check(val(r,'admission_timestamp_ns')==val(r,'logical_arrival_ns'),'admission due identity')
            check(ordered(r,('logical_arrival_ns','b_ns','source_pulled_ns','resize_start_ns','resize_end_ns')),'frontend order')
            if not int(r.get('admitted') or 0):
                check(all(val(r,k) is None for k in ('ready_timestamp_ns','completion_timestamp_ns','expired_drop_ns','socket_submission_ns')),'Excluded frame received service')
                continue
            check(ordered(r,('resize_end_ns','payload_ready_ns','ready_timestamp_ns','expiry_check_ns')),'ready/check order')
            expired=r.get('terminal_state')=='EXPIRED_DROP'
            end=val(r,'completion_timestamp_ns');drop=val(r,'expired_drop_ns');stamp=val(r,'expiry_check_ns');deadline=val(r,'absolute_deadline_ns')
            if expired:
                check(drop is not None and stamp==drop and drop>=deadline,'invalid expiration instant')
                check(end is None and all(val(r,k) is None for k in ('inference_start_timestamp_ns','socket_submission_ns','socket_send_complete_ns','response_completion_ns','edge_inference_start_ns')),'expired work was started/completed')
                check(r.get('expired_stage')==('LOCAL_BEFORE_TRT' if r['placement']=='LOCAL' else 'EDGE_BEFORE_SUBMISSION'),'drop stage')
            else:
                check(r.get('terminal_state')=='COMPLETED' and end is not None and drop is None,'missing/multiple terminal states')
                check(stamp is not None and stamp<deadline,'expired waiting work executed')
                if r['placement']=='LOCAL':
                    check(ordered(r,('ready_timestamp_ns','inference_start_timestamp_ns','completion_timestamp_ns')),'Local order')
                    check(stamp==val(r,'inference_start_timestamp_ns'),'Local check/start identity')
                else:
                    check(ordered(r,('payload_ready_ns','socket_submission_ns','socket_send_complete_ns')),'Edge send order')
                    check(ordered(r,('socket_submission_ns','response_completion_ns')),'Thor return order')
                    check(stamp==val(r,'socket_submission_ns') and end==val(r,'response_completion_ns'),'Edge check/completion identity')
                    check(stamp>=val(r,'edge_release_target_ns'),'early eligibility')
                    check(ordered(r,tuple('edge_'+k for k in h.EDGE_KEYS)),'Edge internal order')
                    check(r.get('payload_sha256')==r.get('raw_sha256') and bool(r.get('raw_sha256')),'payload integrity')
        complete=[r for r in rows if val(r,'completion_timestamp_ns') is not None]
        expired=[r for r in rows if r.get('terminal_state')=='EXPIRED_DROP']
        local=[r for r in rows if r['placement']=='LOCAL'];edge=[r for r in rows if r['placement']=='EDGE']
        lc=[r for r in complete if r['placement']=='LOCAL'];ec=[r for r in complete if r['placement']=='EDGE']
        ld=[r for r in expired if r['placement']=='LOCAL'];ed=[r for r in expired if r['placement']=='EDGE']
        check(len(local)==m['local_r']*8*60 and len(edge)==m['edge_r']*8*60,'assignment count')
        check(len(complete)+len(expired)==len(rows),'terminal drain')
        check(m.get('ready_queue_accounting')==dict(enqueue=len(local),start=len(lc),expired=len(ld)),'Local queue terminal accounting')
        check(sorted(val(r,'edge_request_id') for r in edge)==list(range(len(edge))),'Edge assigned IDs')
        ef=m.get('edge_final',{});dropids=sorted(val(r,'edge_request_id') for r in ed)
        check(ef.get('expired_request_ids')==dropids and ef.get('client_expired_before_submission')==len(ed),'Edge END expiry ledger')
        check(ef.get('assigned')==len(edge) and all(ef.get(k)==len(ec) for k in ('received','completed','responses_sent')),'Edge completed counts')
        check(ef.get('integrity_status')=='VALID' and all(ef.get(k) for k in ('drain_completed','cleanup_completed','worker_thread_exited')),'Edge lifecycle')
        check(m.get('edge_threads_exited') and not m.get('edge_path_errors') and not ef.get('errors'),'Edge errors')
        check(not any(ef.get(k) for k in ('drops','duplicates','queue_cap_saturation')),'Edge unexpected drop/cap/duplicate')
        check(not any(m.get(k) for k in ('forced_drop','queue_cap_saturation','queue_overflow')),'unexpected Local drop/cap')
        warm=[r for r in frames if r['phase']=='warmup']
        check(len(warm)==60 and all(val(r,'completion_timestamp_ns') is not None and val(r,'completion_timestamp_ns')<t0 for r in warm),'warmup')
        # B retains completion-only semantics. U subtracts a distinct expired terminal ledger.
        s['backlogs']={};s['unfinished']={}
        for name,rr in [('H',rows),('L',local),('E',edge)]:
            b=h.backlog([dict(logical_arrival_ns=val(r,'logical_arrival_ns'),response_completion_ns=val(r,'completion_timestamp_ns')) for r in rr],t0,t1,30)
            # This is an interval integral to a terminal event, not a fabricated raw completion.
            u=h.backlog([dict(logical_arrival_ns=val(r,'logical_arrival_ns'),response_completion_ns=
                val(r,'expired_drop_ns') if r.get('terminal_state')=='EXPIRED_DROP' else val(r,'completion_timestamp_ns')) for r in rr],t0,t1,30)
            s['backlogs'][name]=b;s['unfinished'][name]=u;s['g_B_'+name]=b['g_B_E'];s['g_U_'+name]=u['g_B_E']
        s.update(backlog_definition='B=assigned-completed (expired remains unserved); U=assigned-completed-expired terminal',
            backlog_after_drain=s['backlogs']['H']['after_drain_backlog'],
            unfinished_after_drain=s['unfinished']['H']['after_drain_backlog'],
            unfinished_at_active_end=s['unfinished']['H']['active_end_backlog'])
        def counts(rr,source_count):
            completed=[r for r in rr if val(r,'completion_timestamp_ns') is not None]
            timely=[r for r in completed if val(r,'completion_timestamp_ns')-val(r,'logical_arrival_ns')<=D*10**6]
            dropped=[r for r in rr if r.get('terminal_state')=='EXPIRED_DROP']
            return dict(source_frames=source_count,admitted_frames=len(rr),expired_dropped_frames=len(dropped),
                executed_frames=sum(val(r,'inference_start_timestamp_ns') is not None if r['placement']=='LOCAL' else val(r,'socket_submission_ns') is not None for r in rr),
                completed_frames=len(completed),timely_completed_frames=len(timely),late_completed_frames=len(completed)-len(timely),
                missing_frames=len(rr)-len(completed)-len(dropped),admitted_FPS=len(rr)/duration,
                raw_completed_FPS=sum(t0<=val(r,'completion_timestamp_ns')<t1 for r in completed)/duration,
                timely_FPS=len(timely)/duration,late_completed_FPS=(len(completed)-len(timely))/duration,
                expired_drop_FPS=len(dropped)/duration,TIR_source=len(timely)/source_count,
                TIR_admission=len(timely)/len(rr) if rr else None)
        s.update(counts(rows,14400));s['per_stream']=[dict(stream_id=k,**counts([r for r in rows if int(r['stream_id'])==k],1800)) for k in range(8)]
        s['paths']={name:counts(rr,14400) for name,rr in [('LOCAL',local),('EDGE',edge)]}
        s['local_assigned_FPS']=len(local)/duration;s['edge_assigned_FPS']=len(edge)/duration
        s['local_active_completed_FPS']=s['paths']['LOCAL']['raw_completed_FPS']
        s['edge_active_completed_FPS']=s['paths']['EDGE']['raw_completed_FPS']
        rates=[r['timely_FPS'] for r in s['per_stream']];tirs=[r['TIR_source'] for r in s['per_stream']]
        s.update(mean_stream_timely_FPS=st.mean(rates),minimum_stream_timely_FPS=min(rates),stream_timely_FPS_SD=st.stdev(rates),
            worst_stream_TIR=min(tirs),mean_stream_TIR=st.mean(tirs),stream_TIR_SD=st.stdev(tirs),
            zero_timely_stream_ids=[r['stream_id'] for r in s['per_stream'] if r['timely_completed_frames']==0])
        for name,rr in [('global',complete),('local',lc),('edge',ec)]:
            s[name+'_E2E_ms']=quantiles([(val(r,'completion_timestamp_ns')-val(r,'logical_arrival_ns'))/1e6 for r in rr])
        for name,rr,a,b in [('local_queue',lc,'ready_timestamp_ns','inference_start_timestamp_ns'),
            ('local_service',lc,'inference_start_timestamp_ns','completion_timestamp_ns'),
            ('local_expired_wait',ld,'ready_timestamp_ns','expired_drop_ns'),
            ('edge_pending',ec,'payload_ready_ns','socket_submission_ns'),('edge_expired_pending',ed,'payload_ready_ns','expired_drop_ns'),
            ('edge_send',ec,'socket_submission_ns','socket_send_complete_ns'),('edge_server_queue',ec,'edge_queue_enter_ns','edge_queue_start_ns'),
            ('edge_inference',ec,'edge_inference_start_ns','edge_inference_end_ns')]:
            s[name+'_ms']=quantiles([(val(r,b)-val(r,a))/1e6 for r in rr])
        s['local_wait_until_disposition_ms']=quantiles([(val(r,'expired_drop_ns') if r.get('terminal_state')=='EXPIRED_DROP' else val(r,'inference_start_timestamp_ns'))/1e6-val(r,'ready_timestamp_ns')/1e6 for r in local])
        overlap=h.edge_runtime.overlap([(val(r,'inference_start_timestamp_ns'),val(r,'completion_timestamp_ns')) for r in lc],t0,t1)
        s.update(active_concurrency_peak=overlap['peak'],active_concurrency_mean=overlap['mean']);check(overlap['peak']<=2,'Local C exceeded')
        for name,key,rr in [('decode_ready','source_pulled_ns',source),('resize_ready','resize_end_ns',source),('payload_ready','payload_ready_ns',rows)]:
            s[name+'_FPS']=sum(t0<=val(r,key)<t1 for r in rr)/duration
        s.update(h.frozen_power(m,power,errors))
        s['rails']=existing.rail_integrals(m,power,s['raw_completed_FPS']*duration)
        vin=s['rails']['VIN'];s['VIN_W']=vin['avg_power_W'];s['VIN_active_energy_J']=vin['active_energy_J']
        s['VIN_J_per_timely_frame']=vin['active_energy_J']/s['timely_completed_frames'] if vin['active_energy_J'] is not None and s['timely_completed_frames'] else None
        s['energy_scope']='active Thor VIN module+carrier input / timely active-admitted cohort; no drain/Edge energy'
        s.update(aggregate_completed_fps=s['raw_completed_FPS'],total_offered_FPS=target,
                 deadline_ms=D,target_service_FPS=target)
    except Exception:errors.append(traceback.format_exc())
    valid=not errors
    s.update(integrity_status='VALID' if valid else 'INVALID',validity='VALID' if valid else 'INVALID',
             pipeline_audit_status='PASS' if valid else 'FAIL',queue_stable=None,
             queue_classification='PRUNING_TERMINAL_ACCOUNTING' if valid else 'INVALID',
             experiment='EXPIRED_WORK_PRUNING')
    return s


def baseline(plan):
    """Use published canonical analysis, renormalize source denominator explicitly."""
    for rel,digest in plan['baseline_sha256'].items():
        if sha(ROOT/rel)!=digest:raise RuntimeError('Baseline changed: '+rel)
    p=ROOT/'results/canonical_timely_service/analysis01'
    with (p/'per_run_deadlines.csv').open() as f:dr=list(csv.DictReader(f))
    with (p/'per_stream_deadlines.csv').open() as f:sr=list(csv.DictReader(f))
    with (p/'per_run_metrics.csv').open() as f:mr={r['run_id']:r for r in csv.DictReader(f)}
    result={}
    for r in dr:
        if r['cell'] not in ('T200-B','T240-B') or int(r['deadline_ms']) not in (100,150):continue
        if r['integrity_status']!='VALID':raise RuntimeError('Invalid baseline')
        streams=sorted([x for x in sr if x['run_id']==r['run_id'] and x['deadline_ms']==r['deadline_ms']],key=lambda x:int(x['stream_id']))
        if [int(x['stream_id']) for x in streams]!=list(range(8)):raise RuntimeError('Baseline stream identities missing/duplicated')
        rates=[float(x['timely_fps'] if 'timely_fps' in x else x['timely_FPS']) for x in streams]
        key=int(r['target_service_FPS']),int(r['deadline_ms']),int(r['repeat'])
        if key in result:raise RuntimeError('Duplicate baseline condition/repeat')
        if abs(sum(rates)-float(r['timely_FPS']))>1e-9:raise RuntimeError('Baseline stream/aggregate mismatch')
        result[key]=dict(
            run_id=r['run_id'],timely_FPS=float(r['timely_FPS']),TIR_source=int(r['on_time_frames'])/14400,
            TIR_admission=float(r['TIR']),minimum_stream_timely_FPS=min(rates),worst_stream_TIR=min(rates)/30,
            late_completed_FPS=float(r['late_FPS']),expired_drop_FPS=0.,
            local_queue_p95_ms=float(mr[r['run_id']]['local_queue_ms_p95']),
            VIN_J_per_timely_frame=float(r['VIN_J_per_timely_frame']) if r['VIN_J_per_timely_frame'] else None,
            stream_timely_FPS=rates)
    if len(result)!=12:raise RuntimeError('Expected12 baseline workload/deadline/repeat cells')
    return result


def verdict(pairs):
    if len(pairs)!=3 or any(r['integrity_status']!='VALID' for r in pairs):return 'INCONCLUSIVE'
    gain=all(r['delta_timely_FPS']>0 for r in pairs)
    regression=any(any(x<0 for x in r['stream_delta_timely_FPS']) for r in pairs)
    if gain and regression:return 'FAIRNESS_REGRESSION'
    if gain and all(r['delta_worst_stream_TIR']>=0 for r in pairs):return 'PRUNING_SUPPORTED'
    if all(r['delta_timely_FPS']<=0 and r['pruning_expired_drop_FPS']>0 and r['delta_late_completed_FPS']<=0 for r in pairs):return 'NO_TIMELY_GAIN'
    return 'INCONCLUSIVE'


def analyze(output):
    if output.exists():raise RuntimeError('No analysis overwrite')
    plan=load_plan();bs=baseline(plan);results=[];pairs=[];before={}
    for c in plan['order']:
        d=OUT/c['run_id']
        for p in d.rglob('*'):
            if p.is_file():before[str(p)]=sha(p)
        try:
            m=json.loads((d/'manifest.json').read_text())
            for key in ('run_id','repeat','target_service_FPS','deadline_ms','local_r','edge_r'):
                if m.get(key)!=c[key]:raise ValueError('Condition mismatch '+key)
            if m.get('execution_manifest_sha256')!=sha(PLAN):raise ValueError('Plan mismatch')
            if m.get('child_returncode')!=0 or m.get('PROCESS_LIFECYCLE')!='PASS' or not all(m.get(k) for k in ('status_finalized','frequency_restore_ok','active_phase_completed','drain_completed','cleanup_completed')):raise ValueError('Lifecycle invalid')
            pre=OUT/'frequency_preflight.json';pf=json.loads(pre.read_text())
            if pf.get('status')!='PASS' or pf.get('plan_sha256')!=sha(PLAN) or m.get('frequency_preflight',{}).get('sha256')!=sha(pre):raise ValueError('Preflight invalid')
            if m.get('pin_readback_Hz',{}).get('min_freq')!=1575000000 or m.get('pin_readback_Hz',{}).get('max_freq')!=1575000000:raise ValueError('Pin mismatch')
            s=summarize(m,read_csv(d/'per_frame.csv.gz'),read_csv(d/'power_trace.csv.gz'))
            saved=json.loads((d/'summary.json').read_text())
            for k in ('integrity_status','admitted_frames','expired_dropped_frames','completed_frames','timely_completed_frames'):
                if saved.get(k)!=s.get(k):raise ValueError('Stored/raw replay mismatch '+k)
        except Exception:s=dict(integrity_status='INVALID',errors=[traceback.format_exc()])
        s.update({k:c[k] for k in ('run_id','cell','repeat','deadline_ms','target_service_FPS','order_index')});results.append(s)
        b=bs[c['target_service_FPS'],c['deadline_ms'],c['repeat']]
        pair=dict(run_id=c['run_id'],cell=c['cell'],repeat=c['repeat'],baseline_run_id=b['run_id'],integrity_status=s['integrity_status'])
        for k in ('timely_FPS','TIR_source','TIR_admission','minimum_stream_timely_FPS','worst_stream_TIR','late_completed_FPS','expired_drop_FPS','VIN_J_per_timely_frame','local_queue_p95_ms'):
            v=s.get(k) if k!='local_queue_p95_ms' else s.get('local_queue_ms',{}).get('p95')
            pair['baseline_'+k]=b[k];pair['pruning_'+k]=v
            pair['delta_'+k]=v-b[k] if s['integrity_status']=='VALID' and v is not None and b[k] is not None else None
        pair['stream_delta_timely_FPS']=[x['timely_FPS']-v for x,v in zip(s.get('per_stream',[]),b['stream_timely_FPS'])]
        pairs.append(pair)
    assert all(sha(Path(p))==h0 for p,h0 in before.items())
    output.mkdir(parents=True,exist_ok=False)
    write_csv(output/'per_run_metrics.csv',[flatten(s) for s in results]);write_csv(output/'baseline_comparison.csv',pairs)
    streams=[dict(run_id=s['run_id'],cell=s['cell'],repeat=s['repeat'],integrity_status=s['integrity_status'],**r) for s in results for r in s.get('per_stream',[])]
    if streams:write_csv(output/'per_stream_metrics.csv',streams)
    stats=[];verdicts=[]
    for cell in sorted({c['cell'] for c in plan['order']}):
        group=[p for p in pairs if p['cell']==cell];verdicts.append(dict(cell=cell,verdict=verdict(group)))
        for key in sorted({k for p in group for k,v in p.items() if isinstance(v,(int,float)) and k!='repeat'}):
            values=[p[key] for p in group if p['integrity_status']=='VALID' and p.get(key) is not None]
            stats.append(dict(cell=cell,metric=key,planned=3,valid_n=len(values),mean=st.mean(values) if values else None,sample_SD=st.stdev(values) if len(values)>1 else None))
    write_csv(output/'condition_summary.csv',stats)
    # Full run metrics, in addition to the explicit baseline/pruning differences.
    write_csv(output/'condition_metrics.csv',canonical_analysis.aggregate(
        [dict(flatten(s),integrity_status=s['integrity_status']) for s in results],['cell']))
    with (output/'replay.json').open('x') as f:json.dump(results,f,indent=2)
    with (output/'pruning_verdict.md').open('x') as f:
        f.write('# Expired-work pruning\n\nHistorical FIFO baseline; repeat-index comparisons are descriptive, not contemporaneous paired trials or significance tests. Source TIR denominator14400, admitted denominator unchanged12000/14400; expired work stays a failure. B=assigned-completed, U=B-expired. No stability claim from pruning-induced U flattening.\n\n')
        for v in verdicts:f.write(f'- {v["cell"]}: {v["verdict"]}\n')
    with (output/'verification.json').open('x') as f:json.dump(dict(preservation='PASS',input_sha256=before,baseline_sha256=plan['baseline_sha256']),f,indent=2)
    print(json.dumps(verdicts,indent=2))


if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,required=True);args=ap.parse_args();analyze(args.output)
