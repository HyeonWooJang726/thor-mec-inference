#!/usr/bin/env python3
"""Selected observed transition only; half-open waiting and active events for C2."""
from pathlib import Path
import json,argparse,statistics,sys
from collections import defaultdict
from analyze import D,gate,write_csv,stats
from event_analysis import temporal_periods,occupancy,pearson

def percentile(v,p):
    v=sorted(v);pos=(len(v)-1)*p/100;i=int(pos);f=pos-i
    return v[i]*(1-f)+v[min(i+1,len(v)-1)]*f

def main():
    p=argparse.ArgumentParser();p.add_argument('--pair',nargs=2,type=int,required=True);p.add_argument('--reason',required=True);p.add_argument('--context-k',type=int);a=p.parse_args()
    gate();assert json.loads((D/'analysis/analysis_validation.json').read_text())['validation']=='PASS'
    assert a.pair[1]==a.pair[0]+1 and 1<=a.pair[0]<7
    periods=[];runs=[];timeline=[];association=[]
    analysis_ks=sorted(set(a.pair+([a.context_k] if a.context_k else [])))
    for k in analysis_ks:
      for rep in range(1,6):
        runid=f'run{rep:02d}';raw=json.loads((D/f'k{k}'/runid/'raw_ns.json').read_text());rec=raw['records'];t0=raw['t0_ns']
        pr=temporal_periods(rec,t0)
        assert len(pr)==1800
        periods.extend({'K':k,'run_id':runid,**r} for r in pr)
        out={'K':k,'run_id':runid,'periods':1800}
        for m in ['ready_span_ms','first_ready_lag_ms','boundary_prior_unfinished','boundary_prior_pre_ready','boundary_prior_ready_unfinished','boundary_prior_waiting','boundary_prior_active','next_first_ready_prior_unfinished','next_first_ready_prior_pre_ready','next_first_ready_prior_ready_unfinished','next_first_ready_prior_waiting','next_first_ready_prior_active']:
            v=[r[m] for r in pr if r[m] is not None]
            out[m+'_mean']=statistics.mean(v);out[m+'_p95']=percentile(v,95)
            if m not in ['ready_span_ms','first_ready_lag_ms']:out[m+'_positive_pct']=100*sum(x>0 for x in v)/len(v)
        runs.append(out)
        q=[(r['r_ns'],r['s_ns']) for r in rec];active=[(r['s_ns'],r['c_ns']) for r in rec]
        # Actual-time integration (not sampled depth and not service sums per logical period).
        for sec in range(60):
            lo=t0+sec*1_000_000_000;hi=lo+1_000_000_000
            _,qm=occupancy(q,lo,hi);_,am=occupancy(active,lo,hi,2)
            pg=pr[sec*30:(sec+1)*30]
            timeline.append({'K':k,'run_id':runid,'second':sec,'waiting_time_mean':qm,'active_time_mean':am,
              'logical_frame_deadline_miss_pct':statistics.mean(r['deadline_miss_pct'] for r in pg),
              'boundary_prior_waiting_mean':statistics.mean(r['boundary_prior_waiting'] for r in pg),
              'boundary_prior_active_mean':statistics.mean(r['boundary_prior_active'] for r in pg)})
        groups=defaultdict(list)
        for r in rec:groups[r['inference_queue_depth_before_enqueue']].append(r)
        for depth,rows in sorted(groups.items()):
            waits=[(r['s_ns']-r['r_ns'])/1e6 for r in rows]
            association.append({'K':k,'run_id':runid,'pre_enqueue_depth':depth,'frames':len(rows),
             'queue_wait_mean_ms':statistics.mean(waits),'queue_wait_p95_ms':percentile(waits,95),
             'deadline_miss_pct':100*sum((r['c_ns']-r['a_ns'])*30>1_000_000_000 for r in rows)/len(rows)})
    write_csv(D/'analysis/temporal_periods.csv',periods);write_csv(D/'analysis/temporal_per_run.csv',runs)
    write_csv(D/'analysis/temporal_timeline_1s.csv',timeline);write_csv(D/'analysis/queue_depth_wait_association.csv',association)
    summary=[]
    for k in analysis_ks:
        row={'K':k,'n_runs':5}
        for m in runs[0]:
            if m in ('K','run_id','periods'):continue
            row.update({m+'_'+s:v for s,v in stats([r[m] for r in runs if r['K']==k]).items()})
        summary.append(row)
    write_csv(D/'analysis/temporal_summary.csv',summary)
    result={'validation':'PASS','selected_transition_pair':a.pair,'selection_reason':a.reason,'secondary_context_K':a.context_k,'runs':runs,'summary':summary,
       'periods_per_run':1800,'next_first_ready_comparisons_per_run':1799,
       'boundary':'t0 + floor((frame_id+1)*1e9/30); prior work has frame_id <= current period',
       'next_first_ready':'min ready timestamp among next logical frame IDs; counts all unfinished earlier frame IDs, split pre-ready/waiting/active',
       'queue_definition':'r <= t < s; excludes active s <= t < c; active <=2',
       'ready_span':'max(r)-min(r) among K frames with same logical frame ID',
       'time_bins':'actual-time exact Q and active integrals over 1-second bins in [t0,t0+60s); deadline bins use logical frame IDs, explicitly distinct',
       'startup':'included; no sample exclusions','period_service_sum_used':False,'GPU_kernel_overlap_measured':False}
    with (D/'analysis/temporal_analysis.json').open('x') as f:json.dump(result,f,indent=2)
    print('Temporal analysis PASS',a.pair)
if __name__=='__main__':main()
