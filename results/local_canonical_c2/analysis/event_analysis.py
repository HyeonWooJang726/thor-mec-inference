"""C2-safe CPU analysis of half-open host intervals. No GPU capacity inference."""
from collections import defaultdict
from bisect import bisect_right
from statistics import mean

def occupancy(intervals,lo,hi,capacity=None):
    """Exact duration by count in [lo,hi); touching endpoints do not overlap."""
    assert lo < hi
    events=defaultdict(int)
    for a,b in intervals:
        assert a<=b
        a,b=max(lo,a),min(hi,b)
        if a<b:events[a]+=1;events[b]-=1
    duration=defaultdict(int);active=0;previous=lo
    for t,delta in sorted(events.items()):
        duration[active]+=t-previous;active+=delta;previous=t
        assert active>=0 and (capacity is None or active<=capacity)
    duration[active]+=hi-previous
    assert active==0 and sum(duration.values())==hi-lo
    area=sum(n*ns for n,ns in duration.items())
    assert area==sum(max(0,min(hi,b)-max(lo,a)) for a,b in intervals)
    return dict(duration),area/(hi-lo)

def at_times(intervals,times):
    starts=sorted(a for a,b in intervals if a<b);ends=sorted(b for a,b in intervals if a<b)
    return [bisect_right(starts,t)-bisect_right(ends,t) for t in times]

def temporal_periods(records,t0,frames=1800):
    """One row per logical period, including startup and the last offered boundary.
    Prior work at next-first-ready includes all earlier frame IDs, even those not yet ready.
    Distinguish pre-ready, waiting, active from all unfinished prior frames.
    """
    groups=defaultdict(list)
    for r in records:groups[r['frame_id']].append(r)
    ready=[min(r['r_ns'] for r in groups[j]) for j in range(frames)]
    rows=[]
    # Updating sorted event endpoints keeps count queries O(log n); no per-period O(n) scans.
    import bisect
    prior_r=[];prior_s=[];prior_c=[]
    for j in range(frames):
        g=groups[j];boundary=t0+((j+1)*1_000_000_000)//30
        for r in g:
            bisect.insort(prior_r,r['r_ns']);bisect.insort(prior_s,r['s_ns']);bisect.insort(prior_c,r['c_ns'])
        def state(t):
            nr=bisect_right(prior_r,t);ns=bisect_right(prior_s,t);nc=bisect_right(prior_c,t)
            out={'pre_ready':len(prior_r)-nr,'waiting':nr-ns,'active':ns-nc,'unfinished':len(prior_r)-nc}
            assert min(out.values())>=0 and out['active']<=2
            assert out['unfinished']==out['pre_ready']+out['waiting']+out['active']
            out['ready_unfinished']=out['waiting']+out['active']
            return out
        end=state(boundary)
        out={'frame_id':j,'scheduled_s':j/30,'ready_span_ms':(max(r['r_ns'] for r in g)-min(r['r_ns'] for r in g))/1e6,
             'first_ready_lag_ms':(ready[j]-(t0+(j*1_000_000_000)//30))/1e6,
             'deadline_miss_pct':100*sum((r['c_ns']-r['a_ns'])*30>1_000_000_000 for r in g)/len(g),
             **{'boundary_prior_'+k:v for k,v in end.items()}}
        if j+1<frames:out.update({'next_first_ready_prior_'+k:v for k,v in state(ready[j+1]).items()})
        else:out.update({'next_first_ready_prior_'+k:None for k in end})
        rows.append(out)
    return rows

def pearson(x,y):
    mx,my=mean(x),mean(y);xx=sum((v-mx)**2 for v in x);yy=sum((v-my)**2 for v in y)
    if xx==0 or yy==0:return None
    return sum((a-mx)*(b-my) for a,b in zip(x,y))/(xx*yy)**.5
