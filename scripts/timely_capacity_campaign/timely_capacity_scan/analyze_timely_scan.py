"""Log-only timely scan. Expired frames remain in the admission denominator."""
import argparse
import json
import statistics
import types
from pathlib import Path
import numpy as np
from timely_config import OUT,ROOT,raw,load_plan,order,decorate,GRIDS
import analyze_b1 as b1
from analyze_scan import write_csv,write_json
from accounting import accounting,backlog_before
from temperature_mapping import temperatures


def run_class(valid,tir):
    if not valid or tir is None:return 'INVALID'
    return 'TIMELY_FEASIBLE' if tir>=.99 else 'TIMELY_CLEAR_FAIL' if tir<.95 else 'TIMELY_BOUNDARY'


def rate_class(rows):
    if len(rows)!=2 or {r['repeat'] for r in rows}!={1,2} or any(r['classification']=='INVALID' for r in rows):return 'INCONCLUSIVE_INVALID'
    if all(r['TIR_admission']>=.99 for r in rows):return 'TIMELY_FEASIBLE'
    if all(r['TIR_admission']<.95 for r in rows):return 'TIMELY_CLEAR_FAIL'
    return 'TIMELY_BOUNDARY'


def validate(c,m,s,frames,ph,wi):
    # Only the expected parameterized frame/deadline schedule differs.
    fn=b1.validate_run
    proxy=types.SimpleNamespace(**dict(b1.cfg.__dict__,decorate=decorate))
    v=types.FunctionType(fn.__code__,dict(fn.__globals__,cfg=proxy))(c,m,s,frames,ph,wi)
    errors=v['errors']
    for key in ('run_id','target_service_FPS','deadline_ms','K','C'):
        if m.get(key)!=c[key]:errors.append('manifest condition mismatch: '+key)
    if m.get('batch_size')!=1 or m.get('source_fps')!=30:errors.append('batch/source config mismatch')
    for r in frames:
        if r.get('phase')!='active':continue
        expected=decorate(dict(stream_id=int(r['stream_id']),frame_id=int(r['frame_id']),logical_arrival_ns=int(r['logical_arrival_ns'])),m['active_start_ns'],c)
        if b1.number(r,'absolute_deadline_ns')!=expected.get('absolute_deadline_ns'):errors.append('deadline identity mismatch')
        if b1.number(r,'admission_timestamp_ns')!=b1.number(r,'logical_arrival_ns'):errors.append('admission timestamp mismatch')
        observed=b1.number(r,'admission_observed_ns')
        if observed is None or not m['active_start_ns']<=observed<m['active_end_ns']:errors.append('source delivery outside active window')
    for key in ('premeasurement_queue_empty','active_phase_completed','drain_completed','cleanup_completed','clean_shutdown','frequency_restore_ok'):
        if m.get(key) is not True:errors.append(key+' incomplete')
    if m.get('child_returncode')!=0 or m.get('supervisor_interrupted_or_timeout'):errors.append('process lifecycle failure')
    if m.get('pruning_enabled') is not True or m.get('deadline_ms')!=c['deadline_ms']:errors.append('pruning/deadline config mismatch')
    if m.get('CPU_pin_child_readback',{}).get('status')!='PASS':errors.append('CPU child pin mismatch')
    if s.get('actual_clock_non_target_fraction')!=0:errors.append('GPU frequency/readback mismatch')
    for flag in ('forced_drop','queue_cap_saturation','queue_overflow','artificial_backpressure','memory_pressure_failure','OOM'):
        if m.get(flag) or s.get(flag):errors.append(flag)
    if m.get('queue_capacity') not in (None,0):errors.append('queue cap')
    return dict(v,status='PASS' if not errors else 'FAIL',errors=sorted(set(errors)))


def cohort_metrics(rows,D,t0,t1):
    n=len(rows);completed=[r for r in rows if b1.number(r,'completion_timestamp_ns') is not None]
    timely=[r for r in completed if b1.number(r,'completion_timestamp_ns')-b1.number(r,'logical_arrival_ns')<=D*10**6]
    expired=[r for r in rows if r['terminal_state']=='EXPIRED_DROP'];late=len(completed)-len(timely)
    T=(t1-t0)/1e9
    return dict(admitted_count=n,timely_count=len(timely),late_completed_count=late,expired_count=len(expired),
        terminal_identity_PASS=n==len(timely)+late+len(expired),actual_admitted_FPS=n/T,
        timely_FPS=len(timely)/T,TIR_admission=len(timely)/n if n else None,
        late_completed_FPS=late/T,expired_FPS=len(expired)/T,
        active_completed_FPS=sum(t0<=b1.number(r,'completion_timestamp_ns')<t1 for r in completed)/T,
        cohort_completed_FPS=len(completed)/T)


def budget_metrics(rows,D):
    executed=[r for r in rows if b1.number(r,'inference_start_timestamp_ns') is not None and b1.number(r,'completion_timestamp_ns') is not None]
    budget=[D-(b1.number(r,'inference_start_timestamp_ns')-b1.number(r,'logical_arrival_ns'))/1e6 for r in executed]
    service=[(b1.number(r,'completion_timestamp_ns')-b1.number(r,'inference_start_timestamp_ns'))/1e6 for r in executed]
    return dict(budget_n=len(budget),**{f'budget_p{p}':float(np.percentile(budget,p)) if budget else None for p in (5,25,50,75,95)},
        budget_le_zero_fraction=sum(v<=0 for v in budget)/len(budget) if budget else None,
        budget_less_than_measured_service_fraction=sum(b<s for b,s in zip(budget,service))/len(budget) if budget else None,
        budget_population='executed active-admitted frames including drain; expired has no service-start budget')


def analyze_run(d,c):
    m=json.loads((d/'manifest.json').read_text());s=json.loads((d/'summary.json').read_text())
    frames=b1.read(d/'per_frame.csv.gz');ph=b1.read(d/'per_frame_phase_timestamps.csv');wi=json.loads((d/'phase_instrumentation_manifest.json').read_text())
    valid=validate(c,m,s,frames,ph,wi);errors=valid['errors']
    for name in ('CPU_BEFORE_RUN.json','CPU_AFTER_RUN.json'):
        if json.loads((d/name).read_text())['status']!='PASS':errors.append(name+' failed')
    residency=json.loads((d/'CPU_TIME_IN_STATE_DELTA.json').read_text())
    if not residency or any(r.get('status')!='PASS' or (r.get('frequency_kHz')!=2601000 and r.get('delta_counter_units',0)>0) for r in residency):errors.append('CPU frequency residency invalid')
    t0,t1=m['active_start_ns'],m['active_end_ns']
    rows=[r for r in frames if r.get('phase')=='active' and r.get('placement')=='LOCAL']
    counts=cohort_metrics(rows,c['deadline_ms'],t0,t1)
    if counts['actual_admitted_FPS']!=c['target_service_FPS'] or not counts['terminal_identity_PASS']:errors.append('admission/terminal identity failure')
    base,_,_=b1.summarize_run(c,m,s,frames,ph);ov=b1.overlap_rows(ph,c['run_id']);full=[r for r in ov if r['overlap_group']=='full-overlap']
    r=dict(run_id=c['run_id'],deadline_ms=c['deadline_ms'],offered_FPS=c['target_service_FPS'],repeat=c['repeat'],**counts,**budget_metrics(rows,c['deadline_ms']))
    for stem,key in (('service','existing_service_duration_ms'),('GPU_span','gpu_exec_duration_ms'),('host_residual','host_wakeup_delay_ms')):
        for p in ('mean','p50','p95'):r[stem+'_'+p]=base[key+'_'+p]
        q=b1.quant([x[key] for x in full])
        for p in ('mean','p50','p95'):r['full_overlap_'+stem+'_'+p]=q[p]
    waits=[(b1.number(x,'inference_start_timestamp_ns')-b1.number(x,'ready_timestamp_ns'))/1e6 for x in rows if b1.number(x,'inference_start_timestamp_ns') is not None]
    for k,v in b1.quant(waits).items():r['queue_'+k]=v
    disposition=[((b1.number(x,'expired_drop_ns') if x['terminal_state']=='EXPIRED_DROP' else b1.number(x,'inference_start_timestamp_ns'))-b1.number(x,'ready_timestamp_ns'))/1e6 for x in rows]
    for k,v in b1.quant(disposition).items():r['queue_to_disposition_'+k]=v
    A=[b1.number(x,'logical_arrival_ns') for x in rows];C=[b1.number(x,'completion_timestamp_ns') for x in rows if b1.number(x,'completion_timestamp_ns') is not None]
    X=[b1.number(x,'expired_drop_ns') for x in rows if x['terminal_state']=='EXPIRED_DROP']
    B=accounting(A,C,t0,t1);U=accounting(A,C+X,t0,t1)
    r.update(B_active_end=B['B_active_end'],max_backlog=B['max_backlog'],g_B_H=B['g_B_H'],
        U_active_end=U['B_active_end'],U_after_drain=U['after_drain_backlog'],max_unfinished=U['max_backlog'],
        backlog_definition='Legacy B=admitted-completed includes expired unserved; actual U=admitted-completed-expired. Neither is timely gate.',
        active_concurrency_mean=base['active_concurrency_mean'],full_overlap_sample_count=len(full),
        full_overlap_sample_fraction=len(full)/len(ov) if ov else None,OC3_delta=base['OC3_delta'],
        actual_GPU_frequency_MHz=base['actual_GPU_frequency_MHz'],frequency_restore_ok=base['frequency_restore_ok'],
        CPU_time_in_state_delta=residency,integrity_status='VALID' if not errors else 'INVALID',validity_errors=sorted(set(errors)))
    r.update(temperatures(d,m,b1.read(d/'power_trace.csv.gz')))
    r['classification']=run_class(not errors,r['TIR_admission'])
    trace=[dict(run_id=c['run_id'],seconds=i,B=backlog_before(sorted(A),sorted(C),t0+i*10**9),U=backlog_before(sorted(A),sorted(C+X),t0+i*10**9)) for i in range(61)]
    return r,trace


def summaries(rows):
    rates=[];boundaries={}
    for D,grid in GRIDS.items():
        for rate in grid:
            rr=[r for r in rows if r['deadline_ms']==D and r['offered_FPS']==rate];by={r['repeat']:r for r in rr}
            x=dict(deadline=D,offered_FPS=rate,rate_classification=rate_class(rr))
            for rep in (1,2):
                r=by.get(rep,{});x[f'R{rep}_TIR']=r.get('TIR_admission');x[f'R{rep}_classification']=r.get('classification','MISSING')
            good=[r for r in rr if r['classification']!='INVALID']
            for key in ('TIR_admission','timely_FPS','expired_FPS','late_completed_FPS'):
                vals=[r[key] for r in good]
                for stat,value in (('mean',statistics.mean(vals) if vals else None),('sample_SD',statistics.stdev(vals) if len(vals)>1 else None),('min',min(vals) if vals else None),('max',max(vals) if vals else None)):x[key+'_'+stat]=value
            rates.append(x)
        rr=[r for r in rates if r['deadline']==D];lo=max([r['offered_FPS'] for r in rr if r['rate_classification']=='TIMELY_FEASIBLE'],default=None);hi=min([r['offered_FPS'] for r in rr if r['rate_classification']=='TIMELY_CLEAR_FAIL'],default=None)
        boundaries[f'D{D}']=dict(highest_2of2_TIMELY_FEASIBLE=lo,lowest_2of2_TIMELY_CLEAR_FAIL=hi,
            TIMELY_BOUNDARY_rates=[r['offered_FPS'] for r in rr if r['rate_classification']=='TIMELY_BOUNDARY'],
            invalid_or_missing_rates=[r['offered_FPS'] for r in rr if r['rate_classification']=='INCONCLUSIVE_INVALID'],
            observed_bracket=f'{lo} to {hi} FPS' if lo is not None and hi is not None and lo<hi else 'OPEN_OR_UNRESOLVED; no interpolation or forced raw/timely gap')
    return rates,boundaries


def require_restore():
    p=OUT/'CPU_RESTORE_READBACK.json'
    if not p.exists():raise RuntimeError('User CPU restore PASS required BEFORE analyzer')
    r=json.loads(p.read_text())
    if r.get('status')!='PASS' or r.get('mode')!='restored':raise RuntimeError('CPU restore not PASS')
    from run_scan import cpu
    reference=json.loads((OUT/'CPU_STATE_BEFORE.json').read_text())
    if cpu.original.validate(r['snapshot'],reference,'restored')['status']!='PASS':raise RuntimeError('Restore snapshot mismatch')
    ends=[json.loads(p.read_text()).get('child_exit_monotonic_ns',0) for p in OUT.glob('V22_TIMELY_*/manifest.json')]
    if ends and r['snapshot']['monotonic_ns']<max(ends):raise RuntimeError('Restore predates campaign exit')


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,required=True);a=ap.parse_args()
    require_restore();load_plan();a.output.mkdir(parents=True,exist_ok=False);rows=[];trace=[]
    for c in order():
        try:r,t=analyze_run(OUT/c['run_id'],c);trace+=t
        except Exception as e:r=dict(run_id=c['run_id'],deadline_ms=c['deadline_ms'],offered_FPS=c['target_service_FPS'],repeat=c['repeat'],classification='INVALID',validity_errors=[repr(e)])
        rows.append(r)
    rates,boundary=summaries(rows);decomp=[]
    for r in rows:
        if r['deadline_ms']==100 and r['offered_FPS'] in (224,240):
            for label,key in (('timely','timely'),('late-completed','late_completed'),('expired','expired')):
                n=r.get(key+'_count');den=r.get('admitted_count')
                decomp.append(dict(run_id=r['run_id'],offered_FPS=r['offered_FPS'],repeat=r['repeat'],state=label,count=n,FPS=n/60 if n is not None else None,fraction_of_admitted=n/den if den else None,valid=r['classification']!='INVALID'))
    ref=b1.read(OUT/'raw_reference.csv');comparison=[dict(raw_rate=x['offered_FPS'],raw_classification=x['rate_classification'],raw_mean_active_completed=x['mean_active_completed_FPS'],deadline=D,**boundary[f'D{D}']) for x in ref for D in GRIDS]
    for name,rr in [('per_run_timely.csv',rows),('per_rate_timely.csv',rates),('late_expired_decomposition.csv',decomp),('raw_vs_deadline_boundary.csv',comparison),('backlog_trace.csv',trace)]:write_csv(a.output/name,rr)
    write_json(a.output/'deadline_boundary_summary.json',boundary);write_json(a.output/'analysis.json',dict(runs=rows,boundaries=boundary))


if __name__=='__main__':main()
