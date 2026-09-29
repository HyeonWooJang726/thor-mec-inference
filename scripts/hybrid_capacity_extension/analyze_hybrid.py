#!/usr/bin/env python3
"""Hybrid raw replay. Same active/final-window OLS and frozen power validation."""
import argparse
import ast
import csv
import gzip
import inspect
import json
from pathlib import Path
import re
import statistics
import sys

import numpy as np
from hybrid_common import ROOT,OUT,decorate,load_plan,edge_runtime
sys.path.insert(0,str(ROOT/'scripts/rate_dvfs_gate'))
import analyze_rate_dvfs_gate as local_analysis
from formal_analyzer import backlog
from edge_link import EDGE_KEYS

read_csv=local_analysis.read_csv
quantiles=local_analysis.quantiles


def frozen_power(manifest,power,errors):
    """Extract the unchanged canonical power/frequency/OC3 validation block.

    No Hybrid frame projection is fed to the old admission/concurrency checks.
    """
    tree=ast.parse(inspect.getsource(local_analysis.summarize))
    blocks=[n for n in tree.body[0].body if isinstance(n,ast.Try)
            and 'power trace does not bracket' in ast.unparse(n)]
    if len(blocks)!=1:raise RuntimeError('canonical power block shape changed')
    t0,t1=manifest['active_start_ns'],manifest['active_end_ns']
    ns=dict(local_analysis.__dict__,manifest=manifest,power=power,errors=errors,
            t0=t0,t1=t1,duration=(t1-t0)/1e9,summary={})
    exec(compile(ast.fix_missing_locations(ast.Module(body=blocks,type_ignores=[])),
                 '<unchanged-canonical-power-block>','exec'),ns)
    return ns['summary']


def val(row,key):
    x=row.get(key)
    return int(x) if x not in ('',None) else None


def summarize(manifest,frames,power):
    errors=list(manifest.get('errors',[]))
    rows=[r for r in frames if r['phase']=='active']
    summary=dict(run_id=manifest['run_id'],kind=manifest['kind'],repeat=manifest.get('repeat'),
         K=8,C_L=2,C_E=1,source_frames=len(rows),admitted_frames=len(rows),errors=errors,
         hardware_status='PROTECTION_LIMITED' if manifest.get('OC3_after',0)>manifest.get('OC3_before',0) else 'CLEAN',
         OC3_before=manifest.get('OC3_before'),OC3_after=manifest.get('OC3_after'))
    t0,t1=manifest.get('active_start_ns'),manifest.get('active_end_ns')
    if t0 is None or t1 is None:
        return dict(summary,integrity_status='INVALID',validity='INVALID',pipeline_audit_status='INCONCLUSIVE',
                    queue_stable=False,backlog_stable=False,queue_classification='INVALID')
    duration=(t1-t0)/1e9
    def bad(message):errors.append(message)
    def ordered(r,keys):
        values=[val(r,k) for k in keys]
        return all(v is not None for v in values) and values==sorted(values)
    groups={path:[r for r in rows if r.get('placement')==path] for path in ('LOCAL','EDGE')}
    finished=[r for r in rows if val(r,'completion_timestamp_ns') is not None]
    def active(items,key):return [r for r in items if val(r,key) is not None and t0<=val(r,key)<t1]
    completed=active(rows,'completion_timestamp_ns')
    placement_good=True
    per_stream=[]
    for sid in range(8):
        rs=sorted([r for r in rows if int(r['stream_id'])==sid],key=lambda r:int(r['frame_id']))
        if [int(r['frame_id']) for r in rs]!=list(range(int(duration*30))):bad(f'source identity/count {sid}')
        pts=[val(r,'source_timestamp_ns') for r in rs]
        if any(v is None for v in pts) or (pts and any(abs(v-(pts[0]+i*10**9//30))>1 for i,v in enumerate(pts))):
            bad(f'decode PTS/drop corruption {sid}')
        for r in rs:
            expected=decorate(dict(stream_id=sid,frame_id=int(r['frame_id']),logical_arrival_ns=val(r,'logical_arrival_ns')),t0)
            if r.get('placement')!=expected['placement'] or int(r.get('admitted') or 0)!=1:
                bad('placement/admission corruption');placement_good=False
            if expected['placement']=='EDGE' and any(val(r,k)!=expected[k] for k in ('edge_request_id','edge_release_target_ns')):
                bad('Edge schedule/identity corruption');placement_good=False
            if val(r,'logical_arrival_ns')!=t0+int(r['frame_id'])*10**9//30:bad('logical source pacing corruption')
        assigned={p:sum(r.get('placement')==p for r in rs) for p in groups}
        if assigned!={'LOCAL':int(duration*25),'EDGE':int(duration*5)}:
            bad(f'placement count {sid}');placement_good=False
        entry=dict(stream_id=sid,source_frames=len(rs),local_assigned=assigned['LOCAL'],edge_assigned=assigned['EDGE'])
        for path in groups:
            rr=[r for r in rs if r.get('placement')==path]
            entry[path.lower()+'_completed_including_drain']=sum(val(r,'completion_timestamp_ns') is not None for r in rr)
            entry[path.lower()+'_completed_active']=len(active(rr,'completion_timestamp_ns'))
        entry['R_k']=(entry['local_completed_active']+entry['edge_completed_active'])/duration
        entry['terminal_placement_gap']=len(rs)-sum(assigned.values())
        per_stream.append(entry)
    common=('logical_arrival_ns','admission_timestamp_ns','b_ns','source_pulled_ns','resize_start_ns',
            'resize_end_ns','payload_ready_ns','ready_timestamp_ns')
    for r in rows:
        if not ordered(r,common):bad('frontend timestamp/order missing')
        if r.get('placement')=='LOCAL':
            if not ordered(r,('ready_timestamp_ns','inference_start_timestamp_ns','completion_timestamp_ns')):bad('Local timestamps')
        else:
            if not ordered(r,('payload_ready_ns','socket_submission_ns','socket_send_complete_ns')):bad('Edge submission timestamps')
            if not ordered(r,('socket_submission_ns','response_completion_ns')):bad('Edge E2E timestamps')
            if not ordered(r,tuple('edge_'+k for k in EDGE_KEYS)):bad('Edge internal timestamp order')
            if val(r,'completion_timestamp_ns')!=val(r,'response_completion_ns'):bad('Edge completion identity')
            if r.get('payload_sha256')!=r.get('raw_sha256') or not r.get('raw_sha256'):bad('Edge payload hash')
            if val(r,'socket_submission_ns') is not None and val(r,'socket_submission_ns')<val(r,'edge_release_target_ns'):bad('early Edge release')
    if len(finished)!=len(rows) or len(rows)!=int(duration*240):bad('global drain/count mismatch')
    erows=groups['EDGE'];lrows=groups['LOCAL'];expected_edge=int(duration*40)
    if sorted(val(r,'edge_request_id') for r in erows if val(r,'edge_request_id') is not None)!=list(range(expected_edge)):bad('Edge IDs')
    ef=manifest.get('edge_final',{})
    if any(ef.get(k)!=expected_edge for k in ('received','completed','responses_sent')):bad('Edge final count')
    if (ef.get('integrity_status')!='VALID' or not all(ef.get(k) for k in ('drain_completed','cleanup_completed','worker_thread_exited'))
            or ef.get('errors') or not manifest.get('edge_threads_exited') or manifest.get('edge_path_errors')):bad('Edge lifecycle')
    if ef.get('drops') or ef.get('duplicates') or ef.get('queue_cap_saturation'):bad('Edge drop/cap/duplicate')
    if manifest.get('forced_drop') or manifest.get('queue_cap_saturation') or manifest.get('queue_overflow'):bad('Local drop/cap')
    q=manifest.get('ready_queue_accounting',{})
    if q.get('enqueue')!=int(duration*200) or q.get('start')!=int(duration*200):bad('Local ready queue count')
    warm=[r for r in frames if r['phase']=='warmup']
    if len(warm)!=60 or any(not val(r,'completion_timestamp_ns') for r in warm):bad('Local warmup count')
    if warm and any(val(r,'completion_timestamp_ns')>=t0 for r in warm if val(r,'completion_timestamp_ns')):bad('Local warmup overlap')
    metrics={}
    for name,rr in [('H',rows),('L',lrows),('E',erows)]:
        projected=[dict(logical_arrival_ns=val(r,'logical_arrival_ns'),
                        response_completion_ns=val(r,'completion_timestamp_ns')) for r in rr]
        try: b=backlog(projected,t0,t1,min(30,duration/2))
        except (ValueError,TypeError):bad('backlog timestamp corruption');b=dict(g_B_E=None,peak_backlog=None,active_end_backlog=None,after_drain_backlog=None)
        metrics[name]=b
        summary['g_B_'+name]=b['g_B_E']
    summary.update(backlogs=metrics,g_B=summary['g_B_H'],backlog_peak=metrics['H']['peak_backlog'],
         backlog_at_active_end=metrics['H']['active_end_backlog'],backlog_after_drain=metrics['H']['after_drain_backlog'],
         total_offered_FPS=len(rows)/duration,local_assigned_FPS=len(lrows)/duration,edge_assigned_FPS=len(erows)/duration,
         local_assigned_frames=len(lrows),edge_assigned_frames=len(erows),
         local_completed_including_drain=sum(val(r,'completion_timestamp_ns') is not None for r in lrows),
         edge_completed_including_drain=sum(val(r,'completion_timestamp_ns') is not None for r in erows),
         total_completed_active_frames=len(completed),
         aggregate_completed_fps=len(completed)/duration,total_completed_FPS=len(completed)/duration,
         local_completed_FPS=len(active(lrows,'completion_timestamp_ns'))/duration,
         edge_completed_FPS=len(active(erows,'completion_timestamp_ns'))/duration,
         completion_offered_ratio=len(completed)/max(1,len(rows)),completed_frames_including_drain=len(finished),
         per_stream=per_stream,placement_accounting_correct=placement_good,
         decode_ready_FPS=len(active(rows,'source_pulled_ns'))/duration,
         resize_ready_FPS=len(active(rows,'resize_end_ns'))/duration,
         payload_ready_FPS=len(active(rows,'payload_ready_ns'))/duration,
         local_ready_FPS=len(active(lrows,'ready_timestamp_ns'))/duration,
         edge_submitted_FPS=len(active(erows,'socket_send_complete_ns'))/duration)
    for name,rr in [('global',rows),('local',lrows),('edge',erows)]:
        summary[name+'_E2E_ms']=quantiles([(val(r,'completion_timestamp_ns')-val(r,'logical_arrival_ns'))/1e6
                               for r in rr if val(r,'completion_timestamp_ns') is not None])
    summary['latency_ms']=summary['global_E2E_ms']
    summary['latency_population']='all completed active-logical frames including drain; host clocks never subtracted across hosts'
    for name,rr,a,b in [('local_queue',lrows,'ready_timestamp_ns','inference_start_timestamp_ns'),
                        ('local_service',lrows,'inference_start_timestamp_ns','completion_timestamp_ns'),
                        ('edge_client_pending',erows,'payload_ready_ns','socket_submission_ns'),
                        ('edge_send',erows,'socket_submission_ns','socket_send_complete_ns'),
                        ('edge_server_queue',erows,'edge_queue_enter_ns','edge_queue_start_ns')]:
        summary[name+'_ms']=quantiles([(val(r,b)-val(r,a))/1e6 for r in rr if val(r,a) is not None and val(r,b) is not None])
    try:
        intervals=[(val(r,'inference_start_timestamp_ns'),val(r,'completion_timestamp_ns')) for r in lrows]
        overlap=edge_runtime.overlap(intervals,t0,t1)
        summary.update(active_concurrency_peak=overlap['peak'],active_concurrency_mean=overlap['mean'])
        if overlap['peak']>2:bad('Local C=2 exceeded')
    except (TypeError,ValueError,RuntimeError):bad('Local concurrency trace missing/corrupt')
    # Reuse original source/ready diagnostic criteria; under-delivery alone is not INVALID.
    if all(val(r,'ready_timestamp_ns') and val(r,'source_pulled_ns') for r in rows):
        left=t1-int(min(30,duration/2)*1e9)
        slopes={}
        for name,key in [('source','source_pulled_ns'),('frontend','ready_timestamp_ns')]:
            slopes[name]=[local_analysis.queue_slope([r for r in rows if int(r['stream_id'])==sid],left,t1,'logical_arrival_ns',key) for sid in range(8)]
        deficit=max(0,len(rows)-len(active(rows,'ready_timestamp_ns')))/max(1,len(rows))
        limited=(deficit>.01 and (sum(slopes['frontend'])>.5 or max(slopes['frontend'])>.2)) or sum(slopes['source'])>.5 or max(slopes['source'])>.2
        summary.update(frontend_ready_deficit_fraction=deficit,source_pending_slope=sum(slopes['source']),
                       frontend_pending_slope=sum(slopes['frontend']),supply_status='FRONTEND_LIMITED' if limited else 'NORMAL')
    else:summary['supply_status']='UNKNOWN'
    summary.update(frozen_power(manifest,power,errors))
    rails={}
    for r in power:
        if t0<=int(r['timestamp_ns'])<t1:
            for name,mw in re.findall(r'\b([A-Z][A-Z0-9_]*) (\d+)mW/',r.get('raw_tegrastats','')):
                rails.setdefault(name,[]).append(int(mw)/1000)
    summary['available_rail_power_W_diagnostic']={name:statistics.mean(v) for name,v in rails.items()}
    summary['power_scope']='VDD_GPU; other available named rails are diagnostics, not asserted total-device energy'
    valid=not errors
    stable=valid and summary['g_B_H'] is not None and summary['g_B_H']<=.5 and summary['backlog_after_drain']==0
    summary.update(integrity_status='VALID' if valid else 'INVALID',validity='VALID' if valid else 'INVALID',
       pipeline_audit_status='PASS' if valid else 'FAIL',queue_stable=stable,backlog_stable=stable,
       queue_classification='STABLE' if stable else 'UNSTABLE' if valid else 'INVALID',
       bottleneck_classification='NONE_OBSERVED' if stable else 'MIXED/UNRESOLVED',
       energy_per_frame_J=None,energy_note='No hybrid energy-superiority claim; capacity is primary.')
    return summary


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--output',required=True)
    args=ap.parse_args();out=Path(args.output);out.mkdir(parents=True,exist_ok=False)
    plan=load_plan();results=[]
    for c in plan['smoke']+plan['order']:
        d=OUT/c['run_id']
        if not (d/'summary.json').exists():continue
        m=json.loads((d/'manifest.json').read_text())
        s=summarize(m,read_csv(d/'per_frame.csv.gz'),read_csv(d/'power_trace.csv.gz'))
        if m.get('child_returncode')!=0 or m.get('PROCESS_LIFECYCLE')!='PASS' or not m.get('frequency_restore_ok'):
            s.update(integrity_status='INVALID',queue_stable=False,backlog_stable=False,queue_classification='INVALID')
        results.append(s)
    smoke=[s for s in results if s['kind']=='smoke'];primary=[s for s in results if s['kind']!='smoke']
    verdict='INCONCLUSIVE'
    if len(smoke)==1 and smoke[0]['integrity_status']=='VALID':
        if len(primary)==3 and all(s['integrity_status']=='VALID' and s['queue_stable'] and s['placement_accounting_correct'] and s['total_offered_FPS']==240 for s in primary):
            verdict='HYBRID_FULL_SERVICE_SUSTAINABLE'
        elif sum(s['integrity_status']=='VALID' and not s['queue_stable'] for s in primary)>=2:
            verdict='HYBRID_FULL_SERVICE_NOT_SUSTAINABLE'
    from hybrid_common import wire
    wire.save(out/'hybrid_replay.json',results)
    wire.save(out/'verdict.json',dict(verdict=verdict,primary_runs=len(primary)))
    baseline=[]
    for rid in plan['baseline_local240_run_ids']:
        s=json.loads((ROOT/'results/k8_workload_gate'/rid/'summary.json').read_text())
        baseline.append(dict(run_id=rid,completion_FPS=s['aggregate_completed_fps'],g_B=s['g_B'],
           active_end_backlog=s['backlog_at_active_end'],after_drain=s['backlog_after_drain'],
           p95_ms=s['latency_ms']['p95'],p99_ms=s['latency_ms']['p99'],frontend=s['supply_status']))
    wire.save(out/'historical_local240_comparison.json',dict(baseline=baseline,
       protocol_difference='Historical Local-only has synchronous source pacing unchanged here; hybrid introduces staggered Edge eligibility, shared resize then split, extra network/result-return path; latency populations include drain in both. No rerun.'))
    comparison=[]
    for b in baseline:
        comparison.append(dict(configuration='HISTORICAL_LOCAL_ONLY',run_id=b['run_id'],offered_FPS=240,
           local_assigned_FPS=240,edge_assigned_FPS=0,completed_FPS=b['completion_FPS'],g_B=b['g_B'],
           active_end_backlog=b['active_end_backlog'],after_drain_backlog=b['after_drain'],
           p95_ms=b['p95_ms'],p99_ms=b['p99_ms'],frontend_status=b['frontend']))
    for s in primary:
        comparison.append(dict(configuration='HYBRID',run_id=s['run_id'],offered_FPS=s.get('total_offered_FPS'),
           local_assigned_FPS=s.get('local_assigned_FPS'),edge_assigned_FPS=s.get('edge_assigned_FPS'),
           completed_FPS=s.get('aggregate_completed_fps'),g_B=s.get('g_B_H'),
           active_end_backlog=s.get('backlog_at_active_end'),after_drain_backlog=s.get('backlog_after_drain'),
           p95_ms=s.get('latency_ms',{}).get('p95'),p99_ms=s.get('latency_ms',{}).get('p99'),frontend_status=s.get('supply_status')))
    with (out/'local_vs_hybrid.csv').open('x',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=list(comparison[0]));writer.writeheader();writer.writerows(comparison)
    print(verdict)


if __name__=='__main__':main()
