"""CPU-only raw-capacity accounting; no runtime/device dependencies.

Half-open count windows [a,b); B_at_boundary is the left limit B(b-).
OLS integrates the right-continuous event staircase in [a,b), not event samples.
"""
from bisect import bisect_left
from collections import defaultdict
import math


def backlog_before(arrivals, completions, t):
    return bisect_left(arrivals,t)-bisect_left(completions,t)


def staircase(arrivals,completions,a,b):
    changes=defaultdict(int)
    for timestamps,sign in ((arrivals,1),(completions,-1)):
        for t in timestamps[bisect_left(timestamps,a):bisect_left(timestamps,b)]:
            changes[t]+=sign
    level=backlog_before(arrivals,completions,a);last=a;segments=[]
    for t,d in sorted(changes.items()):
        if t>last:segments.append((last,t,level))
        level+=d;last=t
    if last<b:segments.append((last,b,level))
    return segments


def continuous_ols(segments,a,b):
    duration=(b-a)/1e9
    if duration<=0:raise ValueError('Nonpositive regression window')
    numerator=0.0
    for left,right,value in segments:
        x,y=(left-a)/1e9,(right-a)/1e9
        numerator+=value*((y*y-x*x)/2-duration*(y-x)/2)
    return numerator/(duration**3/12)


def classify(valid,g,delta):
    if not valid or not all(math.isfinite(x) for x in (g,delta)):return 'INVALID'
    if g<=0.1 and delta<=0.5:return 'STABLE'
    if g>0.5 and delta>0.5:return 'UNSUSTAINABLE'
    return 'BOUNDARY'


def accounting(arrivals,completions,t0,t1):
    """Inputs are ACTUAL recorded source-logical admissions and Local completions.

    No fabricated missing timestamps. Drain completions retained for cohort
    accounting, excluded from ALL active/last30 counts. No inferred drop warning
    from either Delta-vs-slope or endpoint-rate-vs-OLS residual.
    """
    if t1-t0!=60_000_000_000:raise ValueError('Expected complete 60-second active window')
    A,C=sorted(map(int,arrivals)),sorted(map(int,completions));a=t1-30_000_000_000;b=t1
    T=(t1-t0)/1e9;W=(b-a)/1e9
    nA=bisect_left(A,t1)-bisect_left(A,t0);nC=bisect_left(C,t1)-bisect_left(C,t0)
    nAL=bisect_left(A,b)-bisect_left(A,a);nCL=bisect_left(C,b)-bisect_left(C,a)
    b0=backlog_before(A,C,t0);ba=backlog_before(A,C,a);be=backlog_before(A,C,b)
    whole=staircase(A,C,t0,t1);last=staircase(A,C,a,b)
    g=continuous_ols(last,a,b);delta=(nA-nC)/T;rate=(nAL-nCL)/W
    exact=(nAL-nCL)-(be-ba)
    return dict(active_start_ns=t0,active_end_ns=t1,active_seconds=T,
        last30_start_ns=a,last30_end_ns=b,last30_seconds=W,
        admitted_count_active=nA,completed_count_active=nC,
        actual_admitted_FPS=nA/T,active_completed_FPS=nC/T,
        cohort_completed_FPS=len(C)/T,Delta_FPS=delta,
        admitted_count_last30=nAL,completed_count_last30=nCL,
        admitted_rate_last30=nAL/W,completed_rate_last30=nCL/W,
        rate_deficit_last30=rate,g_B_H=g,queue_conservation_error=rate-g,
        B_active_start=b0,B_at_30s=ba,B_active_end=be,
        B_active_end_div_60=be/60,
        delta_level_identity_error=delta-(be-b0)/T,
        endpoint_conservation_error_frames=exact,
        after_drain_backlog=len(A)-len(C),
        max_backlog=max([b0,be]+[z for x,y,z in whole]),
        min_backlog=min([b0,be]+[z for x,y,z in whole]),
        diagnostic_only=True,hidden_drop_warning=False,
        conservation_review='Endpoint identity checked separately; OLS residual is descriptive, not a failure or causal attribution')


def rate_summary(rows):
    result=[]
    for rate in sorted({r['target_offered_FPS'] for r in rows}):
        selected=[r for r in rows if r['target_offered_FPS']==rate]
        by={r['repeat']:r for r in selected}
        classes=[by.get(i,{}).get('classification','MISSING') for i in (1,2)]
        status=('OBSERVED_STABLE' if classes==['STABLE']*2 else
                'OBSERVED_UNSUSTAINABLE' if classes==['UNSUSTAINABLE']*2 else 'BOUNDARY_OR_UNSTABLE')
        valid=[r for r in selected if r['classification'] not in ('INVALID','MISSING')]
        out=dict(offered_FPS=rate,R1_classification=classes[0],R2_classification=classes[1],
                 rate_classification=status,valid_repeat_count=len(valid),excluded_invalid_or_missing=2-len(valid))
        for key in ('active_completed_FPS','Delta_FPS','g_B_H','B_active_end'):
            out['mean_'+key]=sum(r[key] for r in valid)/len(valid) if valid else None
        result.append(out)
    stable=[r['offered_FPS'] for r in result if r['rate_classification']=='OBSERVED_STABLE']
    unstable=[r['offered_FPS'] for r in result if r['rate_classification']=='OBSERVED_UNSUSTAINABLE']
    low=max(stable,default=None);high=min(unstable,default=None)
    if low==240:description='No raw sustainable boundary observed within the real K8 x 30 FPS workload range'
    elif low is not None and high is not None and low<high:description=f'{low} < boundary < {high} FPS (observed bracket, not an exact capacity)'
    else:description='Unresolved bracket; missing evidence or non-monotone classifications'
    return result,dict(highest_2of2_STABLE=low,lowest_2of2_UNSUSTAINABLE=high,
        boundary_or_unstable_rates=[r['offered_FPS'] for r in result if r['rate_classification']=='BOUNDARY_OR_UNSTABLE'],
        observed_boundary_bracket=description)
