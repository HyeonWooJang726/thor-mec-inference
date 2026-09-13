"""CPU-only descriptive analysis; original artifacts are immutable inputs."""
import csv, hashlib, itertools, json, math, os, statistics as st, subprocess
from collections import Counter, defaultdict
from pathlib import Path

D=Path(__file__).resolve().parents[1]; ROOT=D.parent; REPO=ROOT.parents[1]
METRICS=['deadline_miss_percent','queue_mean_ms','queue_p95_ms','service_mean_ms','service_p95_ms',
 'local_mean_ms','local_p95_ms','local_p99_ms','completed_FPS','observed_max_A','time_weighted_mean_A',
 'fraction_time_A_equals_C','peak_waiting_queue','time_weighted_waiting_queue','waiting_carryover_percent',
 'active_carryover_percent','drain_duration','start_lag_mean_ms','front_end_mean_ms','start_lag_p95_ms',
 'front_end_p95_ms','service_p99_ms','queue_p99_ms','source_duration','run_wall_time',
 'fraction_time_cap_saturated_with_waiting','fraction_time_waiting_without_cap','fraction_time_ready_queue_positive']
DELTA=['queue_mean_ms','queue_p95_ms','service_mean_ms','service_p95_ms','deadline_miss_percent',
 'time_weighted_mean_A','fraction_time_A_equals_C','completed_FPS','local_p95_ms',
 'fraction_time_cap_saturated_with_waiting','start_lag_mean_ms','front_end_mean_ms']
COMPONENTS={'start_lag':('a_ns','b_ns'),'front_end':('b_ns','r_ns'),'queue':('r_ns','s_ns'),
            'service':('s_ns','c_ns'),'local':('a_ns','c_ns')}
def load(p):return json.loads(p.read_text())
def sha(p):
 with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def save(name,value):
 with (D/name).open('x') as f:json.dump(value,f,indent=2,allow_nan=False)
def csvsave(name,rows):
 fields=list(dict.fromkeys(k for r in rows for k in r))
 with (D/name).open('x',newline='') as f:
  w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)
def stats(v):
 return dict(mean=st.mean(v),median=st.median(v),sample_SD=st.stdev(v) if len(v)>1 else None,min=min(v),max=max(v))
def sign(x):return 'increase' if x>1e-12 else 'decrease' if x < -1e-12 else 'equal'
def identity(r):return {k:r[k] for k in ['K','C','run_id','statistical_slot','acquisition_phase','actual_round_id','source_artifact']}
def sweep(records,lo,hi,cap):
 ev=defaultdict(lambda:[0,0])
 for r in records:
  for component,start,end in [(0,r['s_ns'],r['c_ns']),(1,r['r_ns'],r['s_ns'])]:
   a,b=max(start,lo),min(end,hi)
   if a<b:ev[a][component]+=1;ev[b][component]-=1
 A=Q=0;last=lo;duration=defaultdict(int);area=0
 for t,(da,dq) in sorted(ev.items()):
  dt=t-last
  if A==cap:duration['cap']+=dt
  if A==cap and Q>0:duration['blocked']+=dt
  if A<cap and Q>0:duration['uncapped_wait']+=dt
  if Q>0:duration['waiting']+=dt
  area+=A*dt;A+=da;Q+=dq;last=t
  assert 0<=A<=cap and Q>=0
 assert A==Q==0 and last<=hi
 assert duration['blocked']<=duration['cap'] and duration['blocked']+duration['uncapped_wait']==duration['waiting']
 return dict(fraction_time_cap_saturated_with_waiting=duration['blocked']/(hi-lo),
             fraction_time_waiting_without_cap=duration['uncapped_wait']/(hi-lo),
             fraction_time_ready_queue_positive=duration['waiting']/(hi-lo),
             reconstructed_cap_fraction=duration['cap']/(hi-lo),reconstructed_mean_A=area/(hi-lo),
             blocked_duration_ns=duration['blocked'])

def main():
 assert not (D/'analysis_integrity.json').exists(),'analysis output already exists; no overwrite'
 # Hashing preserves evidence without re-deriving raw measurement statistics.
 protected={str(p):dict(bytes=p.stat().st_size,sha256=sha(p)) for p in ROOT.rglob('*')
            if p.is_file() and D not in p.parents}
 for p in [REPO/'scripts/profile_tcp_throughput.py',REPO/'scripts/profile_edge_realtime.py',*(REPO/'scripts/partitioning').rglob('*')]:
  if p.is_file():protected[str(p)]=dict(bytes=p.stat().st_size,sha256=sha(p))
 save('protected_inputs_before.json',protected)
 incoming=list(csv.DictReader((ROOT/'formal_per_run_summary_valid5.csv').open()))
 runs=[]
 for x in incoming:
  r=dict(x)
  for k in ['K','C','configured_C','expected_frames','completed_frames','statistical_slot']:r[k]=int(r[k])
  for k in METRICS[:25]:r[k]=float(r[k]);assert math.isfinite(r[k])
  for k in ['actual_round_id','actual_global_run_index']:r[k]=int(r[k]) if r[k] else None
  assert r['K']*1800==r['expected_frames']==r['completed_frames'] and r['C']==r['configured_C']
  assert r['status']=='PASS'
  assert abs(r['local_mean_ms']-sum(r[k+'_mean_ms'] for k in ['start_lag','front_end','queue','service']))<1e-8
  r['offered_load_fps']=30*r['K'];runs.append(r)
 counts=Counter((r['K'],r['C']) for r in runs)
 assert len(runs)==280 and len(counts)==56 and set(counts.values())=={5}
 assert set(counts)==set(itertools.product(range(1,8),range(1,9)))
 assert len({r['source_artifact'] for r in runs})==280
 assert sum(r['completed_frames'] for r in runs)==2016000
 assert {(r['K'],r['C'],r['statistical_slot']) for r in runs}==set(itertools.product(range(1,8),range(1,9),range(1,6)))
 replacements=[r for r in runs if r['acquisition_phase']=='POST_CAMPAIGN_REPLACEMENT']
 assert len(replacements)==1 and (replacements[0]['K'],replacements[0]['C'])==(2,1)
 assert replacements[0]['actual_round_id'] is None and replacements[0]['actual_global_run_index'] is None
 assert {r['run_id'] for r in runs if (r['K'],r['C'])==(2,1)}=={'run01','run02','run03','run05','replacement01'}
 assert not any('c1/k2/run04' in r['source_artifact'] for r in runs)
 canonical=load(ROOT/'valid5_integrity.json');assert canonical['validation']=='PASS'
 state=load(ROOT/'campaign_status.json');assert len(state['PASS_rows'])==279 and state['FAIL_rows']==[220]
 reference=load(ROOT/'c1/k2/run01/metadata.json')
 assert reference['fps']==30 and reference['candidate_deadline_ms']==1000/30
 assert reference['integer_ns_miss_comparison_rule']=='e2e_ns * 30 > 1_000_000_000'
 # Select all five repeats at each K's descriptive minimum and C8, plus specified boundary/anomaly contrasts.
 mean_dmr={(k,c):st.mean(r['deadline_miss_percent'] for r in runs if (r['K'],r['C'])==(k,c)) for k,c in counts}
 best={k:min(range(1,9),key=lambda c:(mean_dmr[k,c],c)) for k in range(1,8)}
 raw_conditions={(k,c) for k in range(1,8) for c in (best[k],8)}|{(4,5),(5,5),(6,6),(7,5),(6,1),(7,1),(7,2),(7,3)}
 save('raw_selection_policy.json',dict(purpose='Only cap+waiting intersection for all runs requiring it; selective deadline components/time patterns',
   selected_conditions=sorted(raw_conditions), rule='all five repeats of each K minimum-mean-DMR condition and C8; K4/C5,K5/C5,K6/C6,K7/C5 boundary contrasts; K6/C1,K7/C1,C2,C3 backlog/variability conditions',
   no_runs_excluded=True,no_primary_frame_statistics_recomputed=True))
 caprows=[];cond=[];timebins=[];access=[]
 for i,r in enumerate(runs):
  out=REPO/r['source_artifact'];check=load(out/'formal_integrity.json')
  assert check['validation']=='PASS' and check['frames']==r['completed_frames']
  assert load(out/'exit.json')['exit_code']==0
  md=load(out/'metadata.json');assert md['fps']==30 and md['batch_size']==1 and md['concurrency']==r['C']
  assert md['active_stream_to_video_mapping']==reference['actual_formal_stream_to_video_mapping'][:r['K']]
  assert md['candidate_deadline_ms']==1000/30
  targeted=(r['K'],r['C']) in raw_conditions
  need_cap=r['fraction_time_A_equals_C']>0
  records=[]
  if need_cap or targeted:
   # Read only needed columns; no predictor, full latency reaggregation, or regenerated raw file.
   with (out/'per_frame.csv').open() as f:
    for x in csv.DictReader(f):
     fields=['r_ns','s_ns','c_ns','a_ns','frame_id','stream_id']+(['b_ns'] if targeted else [])
     records.append({k:int(x[k]) for k in fields})
   assert len(records)==r['completed_frames']
   lo=records[0]['a_ns']-records[0]['frame_id']*1000000000//30;hi=lo+60000000000
   assert all(x['a_ns']==lo+x['frame_id']*1000000000//30 for x in records)
   q=sweep(records,lo,hi,r['C'])
   assert abs(q['reconstructed_cap_fraction']-r['fraction_time_A_equals_C'])<1e-12
   assert abs(q['reconstructed_mean_A']-r['time_weighted_mean_A'])<1e-12
   access.append(dict(**identity(r),columns='r,s,c,a,frame_id,stream_id'+(',b' if targeted else ''),
                      purpose='cap/wait intersection'+('; selected deadline patterns' if targeted else ''),frames_read=len(records)))
  else:
   q=dict(fraction_time_cap_saturated_with_waiting=0.,fraction_time_waiting_without_cap=None,
          fraction_time_ready_queue_positive=None,reconstructed_cap_fraction=0.,blocked_duration_ns=0)
  r.update(q);caprows.append(dict(**identity(r),configured_C=r['C'],fraction_time_A_equals_C=r['fraction_time_A_equals_C'],**q,
                                window='[t0,t0+60s)',method='exact simultaneous half-open intervals' if records else 'A=C duration is exactly zero; intersection is zero'))
  if targeted:
   misses=[x for x in records if (x['c_ns']-x['a_ns'])*30>1000000000]
   assert abs(len(misses)/len(records)*100-r['deadline_miss_percent'])<1e-10
   for label,group in [('miss',misses),('on_time',[x for x in records if (x['c_ns']-x['a_ns'])*30<=1000000000])]:
    d=dict(**identity(r),frame_class=label,frame_count=len(group))
    for name,(a,b) in COMPONENTS.items():d[name+'_mean_ms']=st.mean((x[b]-x[a])/1e6 for x in group) if group else None
    cond.append(d)
   for start,end in [(0,1),(1,5),(5,30),(30,60)]:
    group=[x for x in records if start*30<=x['frame_id']<end*30]
    nmiss=sum((x['c_ns']-x['a_ns'])*30>1000000000 for x in group)
    timebins.append(dict(**identity(r),logical_arrival_start_s=start,logical_arrival_end_s=end,frames=len(group),miss_frames=nmiss,
                         deadline_miss_percent=100*nmiss/len(group),share_of_run_misses=nmiss/len(misses) if misses else None))
  if (i+1)%40==0:print('CPU analysis',i+1,'/280',flush=True)
 csvsave('cap_waiting_per_run.csv',caprows);csvsave('selective_raw_access.csv',access)
 csvsave('deadline_frame_components.csv',cond);csvsave('deadline_miss_time_bins.csv',timebins)
 csvsave('analysis_per_run.csv',runs)
 summaries=[];index={}
 old={(int(x['K']),int(x['C']),x['metric']):x for x in csv.DictReader((ROOT/'formal_kc_aggregate_valid5.csv').open())}
 for k,c in sorted(counts):
  group=[r for r in runs if (r['K'],r['C'])==(k,c)]
  for metric in METRICS:
   values=[r[metric] for r in group if r[metric] is not None]
   a=dict(K=k,C=c,metric=metric,n_valid=len(values),expected_repeats=5,**(stats(values) if values else dict(mean=None,median=None,sample_SD=None,min=None,max=None)))
   a['CV']=a['sample_SD']/abs(a['mean']) if a['mean'] and len(values)>1 else None
   for r in group:a[f'statistical_slot_{r["statistical_slot"]}']=r[metric]
   if (k,c,metric) in old:
    assert all(abs(a[f]-float(old[k,c,metric][f]))<1e-8 for f in ['mean','median','sample_SD','min','max'])
   summaries.append(a);index[k,c,metric]=a
 csvsave('kc_full_summary.csv',summaries)
 paired=[];deltas=[]
 by={(r['K'],r['C'],r['actual_round_id']):r for r in runs if r['acquisition_phase']=='ORIGINAL_CAMPAIGN'}
 for k in range(1,8):
  for c in range(1,8):
   for metric in DELTA:
    pairs=[]
    for round_id in range(1,6):
     a,b=by.get((k,c,round_id)),by.get((k,c+1,round_id))
     delta=b[metric]-a[metric] if a and b else None
     if delta is not None:pairs.append(delta)
     paired.append(dict(K=k,C_low=c,C_high=c+1,original_round_id=round_id,metric=metric,
                         delta=delta,sign=sign(delta) if delta is not None else 'MISSING_ORIGINAL_FAIL',
                         original_low_run=a['source_artifact'] if a else '',original_high_run=b['source_artifact'] if b else '',replacement_used=False))
    a,b=index[k,c,metric],index[k,c+1,metric]
    deltas.append(dict(K=k,C_low=c,C_high=c+1,metric=metric,low_mean=a['mean'],high_mean=b['mean'],
        delta_primary_mean=b['mean']-a['mean'],low_SD=a['sample_SD'],high_SD=b['sample_SD'],paired_n=len(pairs),
        paired_mean=st.mean(pairs),paired_SD=st.stdev(pairs),paired_min=min(pairs),paired_max=max(pairs),
        increased=sum(sign(x)=='increase' for x in pairs),decreased=sum(sign(x)=='decrease' for x in pairs),equal=sum(sign(x)=='equal' for x in pairs),
        missing_original_rounds='4' if (k,c)==(2,1) else '',replacement_used_in_pairing=False))
 csvsave('adjacent_c_deltas.csv',deltas);csvsave('adjacent_c_round_paired_deltas.csv',paired)
 bestrows=[];regret=[];contrasts=[]
 for k in range(1,8):
  rank=sorted(range(1,9),key=lambda c:(index[k,c,'deadline_miss_percent']['mean'],c));first,second=rank[:2]
  a,b=index[k,first,'deadline_miss_percent'],index[k,second,'deadline_miss_percent']
  gap=b['mean']-a['mean'];pairs=[by[k,second,r]['deadline_miss_percent']-by[k,first,r]['deadline_miss_percent'] for r in range(1,6) if (k,second,r) in by and (k,first,r) in by]
  clear=gap>max(a['sample_SD'],b['sample_SD']) and all(x>1e-12 for x in pairs)
  bestrows.append(dict(K=k,best_observed_C=first,mean_DMR=a['mean'],DMR_SD=a['sample_SD'],second_best_C=second,
      second_mean_DMR=b['mean'],gap_pp=gap,paired_n=len(pairs),rounds_favoring_first=sum(x>1e-12 for x in pairs),
      interpretation='consistent separation in these repeats' if clear else 'no clear single winner',
      tie_Cs=','.join(str(c) for c in rank if abs(index[k,c,'deadline_miss_percent']['mean']-a['mean'])<1e-12),
      queue_mean_ms=index[k,first,'queue_mean_ms']['mean'],service_mean_ms=index[k,first,'service_mean_ms']['mean'],
      local_p95_ms=index[k,first,'local_p95_ms']['mean'],mean_A=index[k,first,'time_weighted_mean_A']['mean']))
  for c in range(1,9):regret.append(dict(K=k,C=c,mean_DMR=index[k,c,'deadline_miss_percent']['mean'],best_observed_C=first,
       best_observed_DMR=a['mean'],descriptive_gap_pp=index[k,c,'deadline_miss_percent']['mean']-a['mean'],
       interpretation='post-hoc descriptive gap to hindsight static minimum; not recoverable controller gain'))
  for cl,ch in itertools.combinations(range(1,9),2):
   for metric in ['deadline_miss_percent','queue_mean_ms','service_mean_ms']:
    ds=[by[k,ch,r][metric]-by[k,cl,r][metric] for r in range(1,6) if (k,ch,r) in by and (k,cl,r) in by]
    contrasts.append(dict(K=k,C_low=cl,C_high=ch,metric=metric,paired_n=len(ds),**stats(ds),increased=sum(x>1e-12 for x in ds),decreased=sum(x< -1e-12 for x in ds)))
 csvsave('static_best_observed_c_by_k.csv',bestrows);csvsave('static_c_regret.csv',regret);csvsave('all_static_original_round_contrasts.csv',contrasts)
 fixed=[dict(C=c,equal_K_mean_DMR=st.mean(index[k,c,'deadline_miss_percent']['mean'] for k in range(1,8)),
             equal_K_mean_descriptive_gap_pp=st.mean(x['descriptive_gap_pp'] for x in regret if x['C']==c),
             worst_K_descriptive_gap_pp=max(x['descriptive_gap_pp'] for x in regret if x['C']==c),
             interpretation='equal K weights are exploratory, not deployment probabilities') for c in range(1,9)]
 csvsave('fixed_c_equal_workload_summary.csv',fixed)
 # Original-only time analysis; add a 55-cell complete panel to isolate changing composition.
 drift=[]
 for metric in ['service_mean_ms','queue_mean_ms','local_mean_ms','front_end_mean_ms','start_lag_mean_ms','deadline_miss_percent']:
  complete=[(k,c) for k,c in counts if all((k,c,r) in by for r in range(1,6))]
  center={(k,c):st.mean(by[k,c,r][metric] for r in range(1,6)) for k,c in complete}
  for rd in range(1,6):
   values=[by[k,c,rd][metric] for k,c in complete];dev=[by[k,c,rd][metric]-center[k,c] for k,c in complete]
   drift.append(dict(original_round=rd,metric=metric,common_conditions=55,raw_mean=st.mean(values),cell_centered_mean=st.mean(dev),
                      cell_centered_SD=st.stdev(dev),positive_cells=sum(x>1e-12 for x in dev),negative_cells=sum(x< -1e-12 for x in dev),
                      missing_cell_all_rounds='K2/C1 removed from complete panel; original Round4 FAIL',replacement_used=False))
 csvsave('round_drift_analysis.csv',drift)
 temporal=[]
 for metric in ['service_mean_ms','deadline_miss_percent']:
  oldmeans={(k,c):st.mean(r[metric] for r in runs if (r['K'],r['C'])==(k,c) and r['acquisition_phase']=='ORIGINAL_CAMPAIGN') for k,c in counts}
  xs=[r['actual_global_run_index'] for r in by.values()];ys=[r[metric]-oldmeans[r['K'],r['C']] for r in by.values()]
  xm,ym=st.mean(xs),st.mean(ys);cov=sum((x-xm)*(y-ym) for x,y in zip(xs,ys));xx=sum((x-xm)**2 for x in xs);yy=sum((y-ym)**2 for y in ys)
  temporal.append(dict(metric=metric,n_original_valid=279,slope_per_100_indices=100*cov/xx,correlation=cov/math.sqrt(xx*yy),replacement_used=False))
 csvsave('temporal_order_descriptive.csv',temporal)
 # Optional invalid-exit raw metrics, isolated secondary sensitivity only.
 f=load(ROOT/'c1/k2/run04/raw_ns.json');v=f['records'];lo=f['t0_ns'];hi=lo+60000000000
 summary=load(ROOT/'c1/k2/run04/summary.json')
 fail=dict(queue_mean_ms=summary['queue_wait_mean_ms'],service_mean_ms=summary['inference_mean_ms'],
           deadline_miss_percent=summary['deadline_miss_pct'],local_p95_ms=summary['local_latency_p95_ms'],
           time_weighted_mean_A=sum(max(0,min(hi,x['c_ns'])-max(lo,x['s_ns'])) for x in v)/60000000000)
 sensitivity=[];original=[r for r in runs if (r['K'],r['C'])==(2,1) and r['acquisition_phase']=='ORIGINAL_CAMPAIGN']
 for metric in fail:
  for label,values in [('PRIMARY_VALID5',[r[metric] for r in runs if (r['K'],r['C'])==(2,1)]),
                       ('ORIGINAL_VALID4',[r[metric] for r in original]),
                       ('SECONDARY_ORIGINAL4_PLUS_FAILED_RUN04',[r[metric] for r in original]+[fail[metric]])]:
   sensitivity.append(dict(dataset=label,metric=metric,n=len(values),**stats(values),primary=label=='PRIMARY_VALID5'))
 csvsave('replacement_sensitivity.csv',sensitivity)
 save('analysis_integrity.json',dict(validation='PASS',conditions=56,valid_runs=280,primary_frames=2016000,
      physical_acquisition_runs=281,physical_acquisition_completed_frames=sum(x['completed_frames'] for x in state['rows'])+3600,
      original_campaign=dict(attempted=280,PASS=279,FAIL=1,ABORTED=0),replacement_runs=1,
      duplicates=0,missing_conditions=0,missing_required_metrics=0,K_C_mismatches=0,replacement_in_pairing=False,
      original_K2_C1_round4_missing=True,cap_intersection_runs_processed=len(access),
      cap_zero_runs_with_exact_zero_intersection=280-len(access),selective_deadline_conditions=sorted(raw_conditions),
      selective_deadline_runs=sum((r['K'],r['C']) in raw_conditions for r in runs),
      primary_metrics_match_canonical=True,mean_decomposition='PASS',exact_cap_and_mean_A_crosschecks='PASS',
      GPU_runs=0,source_modified=False,frame_level_statistical_replication=False,
      preservation_validation='PENDING_FINAL_CHECK'))
 print('ANALYSIS TABLES COMPLETE',flush=True)

if __name__=='__main__':main()
