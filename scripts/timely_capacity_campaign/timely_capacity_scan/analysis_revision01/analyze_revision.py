"""Versioned log-only addendum. Frozen runtime, launcher and plan remain intact."""
import argparse
import csv
import inspect
import json
from pathlib import Path
import sys
import types
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent))
import analyze_timely_scan as prior
from timely_config import OUT,ROOT,order,load_plan,sha
from analyze_scan import write_csv,write_json
REVISION=OUT/'analysis_revision01'


def integer_accounting(admitted,timely,late,expired):
    values=(admitted,timely,late,expired)
    if any(type(v) is not int or v<0 for v in values):raise ValueError('Nonnegative exact integer counts required')
    error=admitted-(timely+late+expired)
    return dict(N_admitted=admitted,N_timely=timely,N_late_completed=late,N_expired=expired,
        terminal_accounting_error=error,terminal_accounting_PASS=(error==0),
        TIR_admission=timely/admitted if admitted else None)


def terminal_partition(rows,D):
    timely=late=expired=0;missing=overlap=0;errors=[];ids=[]
    for i,r in enumerate(rows):
        ids.append((r.get('stream_id'),r.get('frame_id')))
        try:
            a=prior.b1.number(r,'logical_arrival_ns');end=prior.b1.number(r,'completion_timestamp_ns')
            drop=prior.b1.number(r,'expired_drop_ns');start=prior.b1.number(r,'inference_start_timestamp_ns')
            check=prior.b1.number(r,'expiry_check_ns');deadline=prior.b1.number(r,'absolute_deadline_ns')
            if a is None:raise ValueError('missing logical arrival')
            good_time=end is not None and end>=a
            yt=good_time and end-a<=D*1_000_000
            yl=good_time and end-a>D*1_000_000
            # Count conflicting completion/expired claims explicitly, not silently
            # prioritizing one: a double claim produces error=-1 as requested.
            yx=r.get('terminal_state')=='EXPIRED_DROP'
            timely+=int(yt);late+=int(yl);expired+=int(yx)
            memberships=int(yt)+int(yl)+int(yx)
            missing+=int(memberships==0);overlap+=int(memberships>1)
            if yt or yl:
                if r.get('terminal_state')!='COMPLETED' or drop is not None or start is None or not a<=start<=end:
                    errors.append(f'row {i}: invalid/conflicting completion terminal state')
            if yx:
                if drop is None or start is not None or end is not None or deadline!=a+D*1_000_000 or drop<deadline or check!=drop:
                    errors.append(f'row {i}: invalid expired-before-execution state')
            if memberships!=1:errors.append(f'row {i}: terminal memberships={memberships}')
        except (ValueError,TypeError) as e:
            errors.append(f'row {i}: {e}')
    duplicates=len(ids)-len(set(ids))
    if duplicates:errors.append('duplicate admitted frame IDs')
    r=integer_accounting(len(rows),timely,late,expired)
    r.update(terminal_partition_PASS=not errors,terminal_partition_errors=errors,
        terminal_unclassified_frames=missing,terminal_overlapping_frames=overlap,terminal_duplicate_IDs=duplicates)
    return r


def cohort_metrics(rows,D,t0,t1):
    old=prior.cohort_metrics(rows,D,t0,t1);p=terminal_partition(rows,D)
    old.update(p)
    old.update(timely_count=p['N_timely'],late_completed_count=p['N_late_completed'],expired_count=p['N_expired'],
        terminal_identity_PASS=p['terminal_accounting_PASS'] and p['terminal_partition_PASS'],
        timely_FPS=p['N_timely']/((t1-t0)/1e9),late_completed_FPS=p['N_late_completed']/((t1-t0)/1e9),expired_FPS=p['N_expired']/((t1-t0)/1e9))
    return old


def enforce_validity(row):
    r=dict(row);arith=r.get('terminal_accounting_PASS') is True;partition=r.get('terminal_partition_PASS') is True
    valid=arith and partition and r.get('integrity_status')=='VALID' and r.get('classification')!='INVALID'
    r['diagnostic_TIR_admission']=r.get('TIR_admission')
    r['TIR_admission_valid']=valid
    if not valid:
        r['classification']='INVALID';r['integrity_status']='INVALID';r['TIR_admission']=None
        errors=list(r.get('validity_errors',[]))
        if not arith:errors.append('exact integer terminal accounting identity FAIL')
        if not partition:errors.append('mutually exclusive/exhaustive terminal partition FAIL')
        r['validity_errors']=sorted(set(errors));r['cause_review_required']=True
    else:r['cause_review_required']=False
    return r


def analyze_run(d,c):
    # Clone the old analysis function's namespace; its module is never mutated.
    fn=prior.analyze_run
    bound=types.FunctionType(fn.__code__,dict(fn.__globals__,cohort_metrics=cohort_metrics))
    try:r,trace=bound(d,c)
    except Exception as e:
        r=dict(run_id=c['run_id'],deadline_ms=c['deadline_ms'],offered_FPS=c['target_service_FPS'],repeat=c['repeat'],
            classification='INVALID',integrity_status='INVALID',validity_errors=[repr(e)])
        trace=[]
        try:
            frames=prior.b1.read(d/'per_frame.csv.gz')
            rows=[x for x in frames if x.get('phase')=='active' and int(x.get('admitted') or 0)==1]
            r.update(terminal_partition(rows,c['deadline_ms']))
        except Exception as error:r['validity_errors'].append('terminal replay unavailable: '+repr(error))
    for key in ('N_admitted','N_timely','N_late_completed','N_expired','terminal_accounting_error','terminal_accounting_PASS','terminal_partition_PASS'):
        r.setdefault(key,None)  # Missing artifact is N/A, never synthesized zero.
    return enforce_validity(r),trace


EXPECTATIONS=(
 (100,216,'M1_BUDGET','Raw OFF near rho≈1 motivates possible strong queue-budget consumption; service-start remaining budget may approach deadline boundary.',None),
 (100,216,'M1_LATE_GT_EXPIRED','Late-completed count may exceed expired count.','composition'),
 (100,208,'M2_TIR99','TIR_admission may be >=0.99.','tir'),
 (67,200,'M3_TIR99','TIR_admission may be >=0.99.','tir'),
 (67,208,'M4_TRANSITION','May lie in deadline-feasible boundary or transition region.','boundary'))


def mechanism_checks(rows,reviews=None):
    """Pure diagnostic sink. Its outputs are NEVER read by validity/classification."""
    reviews=reviews or {};result=[]
    for D,rate,eid,text,kind in EXPECTATIONS:
        rr=[r for r in rows if r['deadline_ms']==D and r['offered_FPS']==rate]
        if kind=='boundary':groups=[rr]
        else:groups=[[r] for r in rr] or [[]]
        for group in groups:
            r=group[0] if len(group)==1 else {};rid=r.get('run_id','RATE_LEVEL')
            ok=bool(group) and all(x.get('classification')!='INVALID' and x.get('TIR_admission_valid') is True for x in group)
            matched='UNRESOLVED';notes='Not acceptance, not classification, not a grid rule.'
            observed={k:r.get(k) for k in ('queue_p50','queue_p95','queue_p99','budget_p5','budget_p25','budget_p50','budget_p75','budget_p95','budget_less_than_measured_service_fraction','N_late_completed','N_expired','TIR_admission')}
            if not ok:notes+=' Missing/invalid evidence; no expectation test.'
            elif kind=='tir':matched='MATCHED' if r['TIR_admission']>=.99 else 'NOT_MATCHED'
            elif kind=='composition':matched='MATCHED' if r['N_late_completed']>r['N_expired'] else 'NOT_MATCHED'
            elif kind=='boundary':
                status=prior.rate_class(group);observed={'rate_classification':status,'TIRs':[x['TIR_admission'] for x in group]}
                matched='UNRESOLVED' if status=='INCONCLUSIVE_INVALID' else 'MATCHED' if status=='TIMELY_BOUNDARY' else 'NOT_MATCHED'
                notes+=' Operational diagnostic: original two-repeat TIMELY_BOUNDARY category; no new transition threshold.'
            else:
                notes+=' Qualitative "near deadline" has no registered numeric cutoff; manual interpretation required, no invented threshold.'
                review=reviews.get((eid,rid))
                if review and review.get('matched') in ('MATCHED','NOT_MATCHED'):
                    matched=review['matched'];notes+=' Manual descriptive review: '+review.get('notes','')
            if matched=='NOT_MATCHED':
                notes+=' prediction failed. Keep verdict/grid unchanged.'
                if rate==216 and D==100:notes+=' Pruning ON queue regulation behavior remains a follow-up interpretation topic.'
            result.append(dict(deadline_ms=D,offered_FPS=rate,run_id=rid,repeat=r.get('repeat'),expectation_id=eid,
                expectation_text=text,expected_mechanism=text,observed_value=json.dumps(observed,sort_keys=True),
                observed_mechanism=json.dumps(observed,sort_keys=True),matched=matched,
                interpretation_needed=matched!='MATCHED',notes=notes,verdict_effect='NONE'))
    return result


def verify_revision():
    manifest=json.loads((REVISION/'source_sha256.json').read_text())
    for name,h in manifest.items():
        if sha(ROOT/name)!=h:raise RuntimeError('Analysis revision changed: '+name)


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,required=True)
    ap.add_argument('--mechanism-reviews',type=Path,help='Optional descriptive M1_BUDGET review CSV; no verdict effect')
    a=ap.parse_args();prior.require_restore();load_plan();verify_revision()
    a.output.mkdir(parents=True,exist_ok=False);rows=[];trace=[]
    for c in order():
        r,t=analyze_run(OUT/c['run_id'],c);rows.append(r);trace+=t
    rates,boundary=prior.summaries(rows);decomp=[]
    for r in rows:
        if r['deadline_ms']==100 and r['offered_FPS'] in (224,240):
            for label,key in [('timely','N_timely'),('late-completed','N_late_completed'),('expired','N_expired')]:
                n=r.get(key);den=r.get('N_admitted')
                decomp.append(dict(run_id=r['run_id'],state=label,count=n,FPS=n/60 if n is not None else None,
                    fraction_of_admitted=n/den if den else None,valid=r['classification']!='INVALID'))
    ref=prior.b1.read(OUT/'raw_reference.csv')
    comparison=[dict(raw_rate=x['offered_FPS'],raw_classification=x['rate_classification'],raw_mean_active_completed=x['mean_active_completed_FPS'],deadline=D,**boundary[f'D{D}']) for x in ref for D in prior.GRIDS]
    reviews={}
    if a.mechanism_reviews:
        records=prior.b1.read(a.mechanism_reviews);reviews={(x['expectation_id'],x['run_id']):x for x in records}
        if len(reviews)!=len(records):raise ValueError('Duplicate mechanism review keys')
    checks=mechanism_checks(rows,reviews)
    for name,rr in [('per_run_timely.csv',rows),('per_rate_timely.csv',rates),('late_expired_decomposition.csv',decomp),('raw_vs_deadline_boundary.csv',comparison),('backlog_trace.csv',trace),('mechanism_expectation_check.csv',checks)]:write_csv(a.output/name,rr)
    write_json(a.output/'deadline_boundary_summary.json',boundary)
    write_json(a.output/'analysis.json',dict(runs=rows,boundaries=boundary,mechanism_expectations_verdict_effect='NONE'))
    write_json(a.output/'analysis_provenance.json',dict(revision_sources=json.loads((REVISION/'source_sha256.json').read_text()),
        original_plan_sha256=sha(OUT/'plan.json'),mechanism_reviews_sha256=sha(a.mechanism_reviews) if a.mechanism_reviews else None))


if __name__=='__main__':main()
