"""Log-only in-flight calibration analysis using frozen raw-scan definitions."""
import argparse
import csv
import inspect
import json
import math
from pathlib import Path
from config import OUT,ROOT,PLAN,sha,load_plan
from accounting import accounting,classify,rate_summary,staircase,backlog_before
from selection import decide,saturation_status
from integrity import validate_cardinality
import analyze_b1 as b1
from analyze_b1 import summarize_run,overlap_rows,quant,number,read

# The B1/old raw-scan validator hard-coded two instrumentation workers. The
# calibration-only C1 binding creates C contexts and starts C workers.
# Change this OFFLINE cardinality assertion only; all timestamps,
# metric definitions, and GPU/runtime source remain unchanged.
_old = "len(wi)==2 and {int(w['worker_id']) for w in wi}=={0,1}"
_new = "len(wi)==int(c['C']) and {int(w['worker_id']) for w in wi}==set(range(int(c['C'])))"
_source = inspect.getsource(b1.validate_run)
if _source.count(_old) != 1:
    raise RuntimeError('Frozen B1 worker-cardinality validation anchor changed')
_namespace = dict(b1.__dict__)
exec(compile(_source.replace(_old, _new), '<calibration-worker-count-validation-only>', 'exec'), _namespace)
_validate_dynamic_workers = _namespace['validate_run']


def load_run(directory, condition):
    manifest = json.loads((directory/'manifest.json').read_text())
    summary = json.loads((directory/'summary.json').read_text())
    raw = read(directory/'per_frame.csv.gz')
    phase = read(directory/'per_frame_phase_timestamps.csv')
    workers = json.loads((directory/'phase_instrumentation_manifest.json').read_text())
    validity = _validate_dynamic_workers(condition, manifest, summary, raw, phase, workers)
    cardinality = validate_cardinality(condition, manifest, raw, phase, workers)
    validity['cardinality'] = cardinality
    validity['errors'] = sorted(set(validity['errors'] + cardinality['errors']))
    validity['status'] = 'PASS' if not validity['errors'] else 'FAIL'
    return manifest, summary, raw, phase, validity


def active_concurrency_p95(rows, start, end):
    """Time-weighted p95 of executing Local frames over the active 60 seconds."""
    changes = {}
    for row in rows:
        left = number(row, 'inference_start_timestamp_ns')
        right = number(row, 'completion_timestamp_ns')
        if left is None or right is None:
            continue
        left, right = max(start, left), min(end, right)
        if left < right:
            changes[left] = changes.get(left, 0) + 1
            changes[right] = changes.get(right, 0) - 1
    level = 0
    last = start
    durations = {}
    for stamp, delta in sorted(changes.items()):
        durations[level] = durations.get(level, 0) + stamp-last
        level += delta
        last = stamp
    durations[level] = durations.get(level, 0) + end-last
    if level != 0:
        raise RuntimeError('Active concurrency event imbalance')
    cumulative = 0
    for value, duration in sorted(durations.items()):
        cumulative += duration
        if cumulative >= .95*(end-start):
            return value
    raise RuntimeError('Incomplete active concurrency time coverage')


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
    source_count=m.get('last_frame_accounting_counts',{}).get('source_scheduled')
    if source_count!=int(c['K']*30*60):errors.append('physical source count mismatch')
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
    result['mu_cycle']=1000*int(c['C'])/result['full_overlap_service_mean'] if result['full_overlap_service_mean'] else None
    result['classification']=classify(not errors,result['g_B_H'],result['Delta_FPS'])
    result['sustained_completion_FPS']=result['active_completed_FPS']
    result['source_arrival_FPS']=source_count/60 if source_count is not None else None
    result['saturation_status']=saturation_status(
        not errors,result['classification'],result['actual_admitted_FPS'],
        result['active_completed_FPS'])
    result['supply_saturation_evidence']='PASS' if result['saturation_status']=='SATURATED_VALID' else 'NOT_DEMONSTRATED'
    result['C_L']=int(c['C'])
    result['active_concurrency_p95']=active_concurrency_p95(local,t0,t1)
    result['GPU_target_frequency_readback_fraction']=(
        1-gpu if gpu is not None else None)
    result['CPU_pin_before']=json.loads((directory/'CPU_BEFORE_RUN.json').read_text())['status']
    result['CPU_pin_after']=json.loads((directory/'CPU_AFTER_RUN.json').read_text())['status']
    result['raw_scan_integrity_status']='VALID' if not errors else 'INVALID'
    result['saved_integrity_status']=s['integrity_status']
    result['backlog_trajectory_review']='Inspect 1-second B(t); no Delta-vs-OLS hidden-drop warning'
    trace=[dict(run_id=c['run_id'],seconds=i,backlog_before_boundary=backlog_before(sorted(A),sorted(C),t0+i*10**9)) for i in range(61)]
    return result,trace


def assemble_outputs(rows):
    """Shared final-analyzer input validation and aggregation for real/synthetic paths."""
    decision=decide(rows)
    supply=[dict(run_id=r['run_id'],C_L=r['C_L'],repeat=r['repeat'],
        supply_class=r.get('saturation_status'),raw_scan_classification=r.get('classification'),
        source_arrival_FPS=r.get('source_arrival_FPS'),
        active_completion_FPS=r.get('active_completed_FPS'),
        g_B_H=r.get('g_B_H'),Delta_FPS=r.get('Delta_FPS'),
        integrity_status=r.get('raw_scan_integrity_status')) for r in rows]
    by={(r['C_L'],r['repeat']):r for r in rows}
    summary=[dict(C_L=cc,R1_run_id=by[cc,1]['run_id'],R2_run_id=by[cc,2]['run_id'],
        R1_supply_class=by[cc,1].get('saturation_status'),
        R2_supply_class=by[cc,2].get('saturation_status'),
        R1_active_completion_FPS=by[cc,1].get('active_completed_FPS'),
        R2_active_completion_FPS=by[cc,2].get('active_completed_FPS'),
        mean_active_completion_FPS=(decision.get('r_C') or {}).get(cc),
        combined_supply_class=(decision.get('per_C_supply_class') or {}).get(cc))
        for cc in (1,2,3,4)]
    figure=[]
    for row in rows:
        figure.append(dict(C_L=row['C_L'],repeat=row['repeat'],
            supply_class=row.get('saturation_status'),
            active_completion_FPS=row.get('active_completed_FPS'),
            queue_wait_p50_ms=row.get('queue_p50_ms'),
            queue_wait_p95_ms=row.get('queue_p95_ms'),
            service_mean_ms=row.get('existing_service_duration_ms_mean'),
            service_p95_ms=row.get('existing_service_duration_ms_p95'),
            GPU_stream_span_mean_ms=row.get('gpu_exec_duration_ms_mean'),
            GPU_stream_span_p95_ms=row.get('gpu_exec_duration_ms_p95'),
            host_residual_mean_ms=row.get('host_wakeup_delay_ms_mean'),
            host_residual_p95_ms=row.get('host_wakeup_delay_ms_p95'),
            active_concurrency_mean=row.get('active_concurrency_mean'),
            active_concurrency_p95=row.get('active_concurrency_p95'),
            OC3_delta=row.get('OC3_delta')))
    validity=dict(status='PASS' if all(r.get('raw_scan_integrity_status')=='VALID' for r in rows) else 'INCOMPLETE_OR_INVALID',
        invalid_or_missing_run_ids=[r['run_id'] for r in rows if r.get('raw_scan_integrity_status')!='VALID'],
        valid_run_count=sum(r.get('raw_scan_integrity_status')=='VALID' for r in rows),expected_run_count=8)
    return decision,supply,summary,figure,validity


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,required=True);a=ap.parse_args()
    plan=load_plan()
    restore=json.loads((OUT/'CPU_RESTORE_READBACK.json').read_text())
    if restore.get('status')!='PASS' or restore.get('mode')!='restored':
        raise RuntimeError('CPU restore PASS required before calibration analysis')
    a.output.mkdir(parents=True,exist_ok=False);rows=[];trace=[]
    for c in plan['order']:
        try:r,b=analyze_run(OUT/c['run_id'],c);trace+=b
        except Exception as e:r=dict(run_id=c['run_id'],C_L=c['C'],repeat=c['repeat'],
            target_offered_FPS=c['target_service_FPS'],raw_scan_integrity_status='INVALID',
            saturation_status='INVALID',supply_saturation_evidence='NOT_DEMONSTRATED',
            classification='INVALID',validity_errors=[repr(e)])
        rows.append(r)
    decision,supply,summary,figure,validity=assemble_outputs(rows)
    write_csv(a.output/'per_run.csv',rows)
    write_csv(a.output/'backlog_1s.csv',trace)
    write_csv(a.output/'supply_classification.csv',supply)
    write_csv(a.output/'per_C_summary.csv',summary)
    write_csv(a.output/'fig_local_concurrency_calibration.csv',figure)
    write_json(a.output/'c2_justification.json',decision)
    write_json(a.output/'validity_summary.json',dict(validity,CPU_restore_status=restore['status']))
    write_json(a.output/'provenance.json',dict(plan_sha256=sha(PLAN),
        frozen_worker_sha256=plan['frozen_worker_sha256'],
        calibration_worker_sha256=plan['calibration_worker_sha256'],
        source='new calibration runs only',
        completion_FPS='active completions divided by exactly 60 s; drain excluded',
        saturation='Raw UNSUSTAINABLE is SATURATED_VALID; STABLE near 240 is SOURCE_LIMITED; BOUNDARY is AMBIGUOUS. Higher-C observed throughput can reject C2 even when source-limited, but cannot justify C2.',
        GPU_span_and_host_residual='unchanged V2.2 phase instrumentation',
        previous_Confirmation02_reclassification=False))
    return 0


if __name__=='__main__':raise SystemExit(main())
