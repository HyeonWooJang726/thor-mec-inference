"""Log-only scan analysis. New output directory required; never changes run artifacts."""
import argparse
import csv
import json
import math
from pathlib import Path
from config import OUT,ROOT,load_plan
from accounting import accounting,classify,rate_summary,staircase,backlog_before
from analyze_b1 import load_run,summarize_run,overlap_rows,quant,number,read


def write_json(path,data):
    with path.open('x') as f:json.dump(data,f,indent=2,allow_nan=False)


def write_csv(path,rows):
    keys=list(dict.fromkeys(k for r in rows for k in r))
    with path.open('x',newline='') as f:
        w=csv.DictWriter(f,fieldnames=keys);w.writeheader();w.writerows(rows)


def analyze_run(directory,c,require_scan_controls=True):
    m,s,raw,ph,valid=load_run(directory,c)
    errors=list(valid['errors']);t0,t1=m['active_start_ns'],m['active_end_ns']
    local=[r for r in raw if r.get('phase')=='active' and r.get('placement')=='LOCAL']
    A=[number(r,'logical_arrival_ns') for r in local]
    C=[number(r,'completion_timestamp_ns') for r in local if number(r,'completion_timestamp_ns') is not None]
    data=accounting(A,C,t0,t1)
    for r in local:
        if number(r,'admission_timestamp_ns')!=number(r,'logical_arrival_ns'):errors.append('admission/source logical timestamp mismatch')
        if number(r,'completion_timestamp_ns') is not None and number(r,'completion_timestamp_ns')<number(r,'logical_arrival_ns'):errors.append('completion before admission')
    for field in ('premeasurement_queue_empty','active_phase_completed','drain_completed','cleanup_completed','clean_shutdown','frequency_restore_ok'):
        if m.get(field) is not True:errors.append(field+' not PASS')
    if m.get('child_returncode')!=0 or m.get('supervisor_interrupted_or_timeout'):errors.append('unexpected/incomplete process exit')
    if m.get('pruning_enabled') is not False:errors.append('pruning must be OFF')
    for flag in ('forced_drop','queue_cap_saturation','queue_overflow','artificial_backpressure','memory_pressure_failure','OOM'):
        if m.get(flag) or s.get(flag):errors.append(flag)
    if m.get('queue_capacity') not in (None,0):errors.append('bounded Local ready queue')
    if data['actual_admitted_FPS']!=c['target_service_FPS']:errors.append('target vs actual logical admissions mismatch')
    if data['after_drain_backlog']!=0 or data['min_backlog']<0 or data['B_active_start']!=0:errors.append('cohort backlog accounting failure')
    enqueued=[number(r,'ready_timestamp_ns') for r in local if number(r,'ready_timestamp_ns') is not None]
    observed=[number(r,'admission_observed_ns') for r in local if number(r,'admission_observed_ns') is not None]
    # Logical admissions remain canonical. Observed scheduler delivery is separate.
    if len(observed)!=len(A) or any(not(t0<=x<t1) for x in observed):errors.append('source admission not delivered during active window')
    if len(enqueued)!=len(A):errors.append('missing Local enqueue')
    if any(r.get('terminal_state')!='COMPLETED' for r in local):errors.append('drop/expiry/unfinished work in OFF scan')
    aq=m.get('ready_queue_accounting',{})
    if aq.get('enqueue')!=len(A) or aq.get('start')!=len(A) or aq.get('expired')!=0:errors.append('ready queue counters inconsistent')
    if m.get('CPU_pin_child_readback',{}).get('status')!='PASS':errors.append('CPU child pin failed')
    if require_scan_controls:
        for name in ('CPU_BEFORE_RUN.json','CPU_AFTER_RUN.json'):
            if json.loads((directory/name).read_text()).get('status')!='PASS':errors.append(name+' failed')
        residency=json.loads((directory/'CPU_TIME_IN_STATE_DELTA.json').read_text())
        if not residency or any(r.get('status')!='PASS' for r in residency):errors.append('CPU residency unavailable')
        if any(r.get('frequency_kHz')!=2601000 and r.get('delta_counter_units',0)>0 for r in residency):errors.append('CPU frequency residency outside pin')
    gpu=s.get('actual_clock_non_target_fraction')
    if gpu is None or gpu!=0:errors.append('GPU actual readback missing/mismatch')
    base,_,_=summarize_run(c,m,s,raw,ph)
    overlap=overlap_rows(ph,c['run_id']);full=[r for r in overlap if r['overlap_group']=='full-overlap']
    q=quant([(number(r,'inference_start_timestamp_ns')-number(r,'ready_timestamp_ns'))/1e6 for r in local if number(r,'inference_start_timestamp_ns') is not None])
    result=dict(base,**data,target_offered_FPS=c['target_service_FPS'],repeat=c['repeat'],
        actual_enqueued_FPS=sum(t0<=x<t1 for x in enqueued)/60,
        cohort_enqueued_FPS=len(enqueued)/60,observed_admitted_FPS=sum(t0<=x<t1 for x in observed)/60,
        delivered_admission_lateness_ms=quant([(number(r,'admission_observed_ns')-number(r,'logical_arrival_ns'))/1e6 for r in local if number(r,'admission_observed_ns') is not None]),
        ready_queue_capacity=None,queue_full_blocking='IMPOSSIBLE_BY_UNBOUNDED_QUEUE_SOURCE',
        uninstrumented_lock_wait='No direct producer put duration; no claim of zero mutex wait',
        full_overlap_sample_count=len(full),validity_errors=sorted(set(errors)))
    for key,val in q.items():result['queue_'+key+'_ms']=val
    for stem,key in [('service','existing_service_duration_ms'),('GPU_span','gpu_exec_duration_ms'),('host_residual','host_wakeup_delay_ms')]:
        result[stem+'_mean']=base[key+'_mean'];result[stem+'_p95']=base[key+'_p95']
        fs=quant([r[key] for r in full]);result['full_overlap_'+stem+'_mean']=fs['mean']
    result['mu_cycle']=2000/result['full_overlap_service_mean'] if result['full_overlap_service_mean'] else None
    result['classification']=classify(not errors,result['g_B_H'],result['Delta_FPS'])
    result['raw_scan_integrity_status']='VALID' if not errors else 'INVALID'
    result['saved_integrity_status']=s['integrity_status']
    result['backlog_trajectory_review']='Inspect 1-second B(t); no Delta-vs-OLS hidden-drop warning'
    trace=[dict(run_id=c['run_id'],seconds=i,backlog_before_boundary=backlog_before(sorted(A),sorted(C),t0+i*10**9)) for i in range(61)]
    return result,trace


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,required=True);a=ap.parse_args()
    plan=load_plan();a.output.mkdir(parents=True,exist_ok=False);rows=[];trace=[]
    for c in plan['order']:
        try:r,b=analyze_run(OUT/c['run_id'],c);trace+=b
        except Exception as e:r=dict(run_id=c['run_id'],repeat=c['repeat'],target_offered_FPS=c['target_service_FPS'],classification='INVALID',validity_errors=[repr(e)])
        rows.append(r)
    rates,boundary=rate_summary(rows)
    write_csv(a.output/'per_run_capacity.csv',rows);write_csv(a.output/'per_rate_capacity.csv',rates)
    write_csv(a.output/'backlog_1s.csv',trace);write_json(a.output/'boundary_summary.json',boundary)
    keys=('run_id','target_offered_FPS','classification','full_overlap_service_mean','mu_cycle','active_completed_FPS','g_B_H','OC3_delta','full_overlap_sample_count','full_overlap_GPU_span_mean','full_overlap_host_residual_mean')
    write_csv(a.output/'saturation_diagnostic.csv',[{k:r.get(k) for k in keys} for r in rows])
    write_json(a.output/'analysis.json',dict(runs=rows,boundary=boundary,
        limitation='Canonical-aligned Local operating boundary; not GPU-only capacity. OLS residual is diagnostic, endpoint conservation is exact. Invalid runs excluded, cohort FPS is not a sustainability gate.'))
    return 0


if __name__=='__main__':raise SystemExit(main())
