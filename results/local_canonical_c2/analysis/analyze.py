#!/usr/bin/env python3
"""Post-gate run-level canonical analysis. No cross-run frame pooling."""
from pathlib import Path
import sys,json,csv,statistics,hashlib
D=Path(__file__).resolve().parents[1];R=D.parents[1]
sys.path[:0]=[str(D/'code'),str(R/'scripts')]
from screening_metrics import validate_run
from local_latency_breakdown_metrics import percentile_ns
from event_analysis import occupancy,pearson

def write_csv(path,rows):
    rows=list(rows)
    with path.open('x',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(dict.fromkeys(k for row in rows for k in row)));w.writeheader();w.writerows(rows)
def stats(v):
    return dict(mean=statistics.mean(v),sample_sd=statistics.stdev(v),median=statistics.median(v),min=min(v),max=max(v))
def gate():
    g=json.loads((D/'formal_integrity_report.json').read_text())
    assert g['validation']=='PASS' and g['valid_runs']==35 and g['frames']==252000
    for p,h in g['raw_source_sha256'].items():assert hashlib.sha256((D/p).read_bytes()).hexdigest()==h,p
    return g

def main():
    gate();runs=[]
    for k in range(1,8):
      for rep in range(1,6):
        runid=f'run{rep:02d}';out=D/f'k{k}'/runid
        r=json.loads((out/'summary.json').read_text());raw=json.loads((out/'raw_ns.json').read_text())
        rec=raw['records'];t0=raw['t0_ns'];v=json.loads((out/'validation.json').read_text())
        for label,a,b,ps in [('start_lag','a_ns','b_ns',[95]),('front_end','b_ns','r_ns',[95]),
                             ('queue_wait','r_ns','s_ns',[99]),('inference','s_ns','c_ns',[99])]:
            values=[x[b]-x[a] for x in rec]
            for p in ps:r[f'{label}_p{p}_ms']=float(percentile_ns(values,p))/1e6
        active,avg=occupancy([(x['s_ns'],x['c_ns']) for x in rec],t0,t0+60_000_000_000,2)
        r['time_weighted_active_offered']=avg
        for n in range(3):r[f'active_{n}_offered_pct']=100*active.get(n,0)/60_000_000_000
        qdur,qavg=occupancy([(x['r_ns'],x['s_ns']) for x in rec],t0,t0+60_000_000_000)
        r['time_weighted_waiting_offered']=qavg
        r['waiting_positive_offered_pct']=100*(1-qdur.get(0,0)/60_000_000_000)
        r['workers_actually_used']=v['concurrency']['workers_actually_used']
        r['submitted_overlap_time_ms']=v['concurrency']['submitted_not_yet_synchronized_intervals']['service_interval_overlap_time_ms']
        r['completion_elapsed_s']=v['completion_elapsed_s'];r['drain_after_offered_end_s']=v['drain_after_offered_end_s']
        r['wall_clock_duration_s']=v['wall_clock_duration_s']
        depth=[x['inference_queue_depth_before_enqueue'] for x in rec];wait=[(x['s_ns']-x['r_ns'])/1e6 for x in rec]
        r['queue_depth_wait_pearson']=pearson(depth,wait)
        assert abs(sum(r[x+'_mean_ms'] for x in ['start_lag','front_end','queue_wait','inference'])-r['local_latency_mean_ms'])<1e-9
        assert abs(sum(r[f'active_{n}_offered_pct'] for n in range(3))-100)<1e-10
        runs.append(r)
    write_csv(D/'per_run_summary.csv',runs)
    metrics=[key for key in runs[0] if key not in ('C','K','run_id','frames')]
    summary=[];long=[]
    for k in range(1,8):
        row={'C':2,'K':k,'n_runs':5,'frames_per_run':k*1800}
        for m in metrics:
            vals=[r[m] for r in runs if r['K']==k]
            if any(v is None for v in vals):continue
            st=stats(vals)
            row.update({f'{m}_{s}':v for s,v in st.items()})
            long.append({'C':2,'K':k,'metric':m,'n_runs':5,**st,**{f'run{i:02d}':v for i,v in enumerate(vals,1)}})
        summary.append(row)
    write_csv(D/'motivation_summary.csv',summary);write_csv(D/'run_level_variability.csv',long)
    queue_keys=['C','K','run_id','peak_waiting_queue','time_weighted_waiting_queue','time_weighted_waiting_offered',
       'waiting_positive_offered_pct','queue_wait_mean_ms','queue_wait_p95_ms','queue_wait_p99_ms','max_active_inferences',
       'time_weighted_active_offered','active_0_offered_pct','active_1_offered_pct','active_2_offered_pct','service_overlap_pair_count','service_overlap_time_ms','queue_depth_wait_pearson']
    write_csv(D/'inference_queue_summary.csv',({k:r[k] for k in queue_keys} for r in runs))
    decomp=[]
    for r in runs:
        d={k:r[k] for k in ['C','K','run_id','local_latency_mean_ms','start_lag_mean_ms','front_end_mean_ms','queue_wait_mean_ms','inference_mean_ms']}
        for comp in ['start_lag','front_end','queue_wait','inference']:d[comp+'_share_pct']=100*r[comp+'_mean_ms']/r['local_latency_mean_ms']
        decomp.append(d)
    write_csv(D/'latency_decomposition.csv',decomp)
    knees=[]
    for a,b in zip(summary,summary[1:]):
        row={'from_K':a['K'],'to_K':b['K'],'n_runs_per_K':5}
        for m in ['deadline_miss_pct','local_latency_p95_ms','local_latency_p99_ms','queue_wait_mean_ms','queue_wait_p95_ms','peak_waiting_queue','time_weighted_waiting_queue']:
            row[m+'_delta_mean']=b[m+'_mean']-a[m+'_mean']
            row[m+'_lower_min']=a[m+'_min'];row[m+'_lower_max']=a[m+'_max']
            row[m+'_upper_min']=b[m+'_min'];row[m+'_upper_max']=b[m+'_max']
            paired=[next(r[m] for r in runs if r['K']==b['K'] and r['run_id']==f'run{i:02d}')-next(r[m] for r in runs if r['K']==a['K'] and r['run_id']==f'run{i:02d}') for i in range(1,6)]
            row[m+'_increases_by_rep']=sum(v>0 for v in paired)
        knees.append(row)
    write_csv(D/'deadline_knee_analysis.csv',knees)
    data={'runs':runs,'summary':summary,'adjacent_K_changes':knees,'frame_pooling_primary':False,
      'active_window':'[t0,t0+60s); exact interval event replay, active=0/1/2 fractions include startup',
      'waiting_legacy_window':'first ready enqueue through last ready enqueue; retained original definition',
      'waiting_offered_window':'[t0,t0+60s); separately reported, not substituted for original',
      'period_service_sum_used':False,'GPU_kernel_overlap_measured':False}
    with (D/'analysis/analysis_data.json').open('x') as f:json.dump(data,f,indent=2)
    with (D/'analysis/analysis_validation.json').open('x') as f:json.dump({'validation':'PASS','runs':35,'frames':252000,'run_level_aggregation':True,'mean_decomposition':True,'active_fraction_sum':True,'independent_event_area_identity':True},f,indent=2)
    print('Analysis PASS: 35 separate run statistics, 7 five-run summaries; temporal pair must be selected from data.')
if __name__=='__main__':main()
