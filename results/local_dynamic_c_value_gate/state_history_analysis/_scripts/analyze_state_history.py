"""Read-only, CPU-only secondary analysis. No controller/predictor or GPU imports."""
from pathlib import Path
import csv,json,hashlib,os,tempfile,subprocess
os.environ.setdefault('MPLCONFIGDIR',tempfile.mkdtemp(prefix='state_history_mpl_'))
import numpy as np
import pandas as pd
OUT=Path(__file__).resolve().parents[1];ROOT=OUT.parent;REC=ROOT/'recovery_001'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def save(name,rows):
 path=OUT/name
 if path.exists():raise RuntimeError('refuse overwrite '+str(path))
 pd.DataFrame(rows).to_csv(path,index=False,float_format='%.15g')
def metric(f):
 d={k:f[k].to_numpy(dtype=np.int64) for k in ['a_ns','b_ns','r_ns','s_ns','c_ns']};lat=d['c_ns']-d['a_ns'];miss=lat*30>10**9
 z=dict(arrival_count=len(f),miss_count=int(miss.sum()),DMR_percent=100*float(miss.mean()))
 for name,start,end in [('local','a_ns','c_ns'),('queue','r_ns','s_ns'),('service','s_ns','c_ns'),('start_lag','a_ns','b_ns'),('front_end','b_ns','r_ns')]:
  v=(d[end]-d[start])/1e6
  for q,x in [('mean',np.mean(v)),('p95',np.percentile(v,95)),('p99',np.percentile(v,99))]:z[name+'_'+q+'_ms']=float(x)
 return z
class Acquisition:
 def __init__(self,row):
  self.row=row;self.directory=ROOT/row['acquisition_id'];self.f=pd.read_csv(self.directory/'per_frame.csv');self.e=pd.read_csv(self.directory/'events.csv',keep_default_na=False)
  self.term=json.loads((self.directory/'termination.json').read_text());self.t0=int(self.term['t0_ns'])
  self.d={k:self.f[k].to_numpy(dtype=np.int64) for k in ['a_ns','actual_generation_ns','b_ns','r_ns','s_ns','c_ns','completion_publication_ns']}
  self.caps=self.e[self.e.kind=='cap_apply'].copy();self.cap_times=self.caps.ns.to_numpy(dtype=np.int64);self.event_times=self.e.ns.to_numpy(dtype=np.int64)
  self.id={k:row[k] for k in ['acquisition_id','round','trace','policy']};self.ks=[6,7,6,7] if row['trace']=='A' else [7,6,7,6]
 def state(self,t,left=False):
  d=self.d;before=lambda x:x<t if left else x<=t;unfinished=before(d['a_ns'])&(~before(d['c_ns']));generated=before(d['actual_generation_ns'])&(~before(d['c_ns']));ready=before(d['r_ns'])&(~before(d['s_ns']));active=before(d['s_ns'])&(~before(d['c_ns']))
  side='left' if left else 'right';ci=np.searchsorted(self.cap_times,t,side=side)-1;ei=np.searchsorted(self.event_times,t,side=side)-1
  assert ci>=0 and ei>=0
  ce=self.caps.iloc[ci];event=self.e.iloc[ei]
  z=dict(sample_ns=int(t),sample_side='LEFT_LIMIT' if left else 'RIGHT_CONTINUOUS',C=int(ce.new_C),A=int(active.sum()),ready_queue=int(ready.sum()),unfinished_backlog=int(unfinished.sum()),generated_unfinished=int(generated.sum()),due_not_generated=int((before(d['a_ns'])&~before(d['actual_generation_ns'])).sum()),online_active_counter=int(event.active_counter),observed_K=int(event.K),latest_event_seq=int(event.seq),latest_event_ns=int(event.ns))
  assert z['unfinished_backlog']==z['generated_unfinished']+z['due_not_generated']
  for prefix,mask in [('unfinished',unfinished),('ready',ready),('generated',generated)]:
   # Exact integer numerator in one-thirtieth ns; quantiles are descriptive ms.
   slack_num=10**9+30*(d['a_ns'][mask]-t);v=slack_num/30000000
   for name,p in [('min',0),('p10',10),('median',50),('p90',90)]:z[prefix+'_slack_'+name+'_ms']=float(np.percentile(v,p)) if len(v) else None
   z[prefix+'_late_count']=int((slack_num<=0).sum());z[prefix+'_late_fraction']=float((slack_num<=0).mean()) if len(v) else None
   for ms in [5,10]:z[prefix+'_urgent_'+str(ms)+'ms_count']=int(((slack_num>0)&(slack_num<=ms*30000000)).sum())
  return z
 def load_window(self,lo,hi):
  a=self.t0+int(lo*1e9);b=self.t0+int(hi*1e9);d=self.d
  z={'calendar_completed_fps':float(((d['c_ns']>=a)&(d['c_ns']<b)).sum())/(hi-lo)}
  for label,start,end in [('ready_queue','r_ns','s_ns'),('unfinished_backlog','a_ns','c_ns'),('generated_unfinished','actual_generation_ns','c_ns'),('A','s_ns','c_ns')]:
   z['time_mean_'+label]=float(np.maximum(0,np.minimum(d[end],b)-np.maximum(d[start],a)).sum())/(b-a)
   times=np.unique(np.r_[a,d[start][(d[start]>=a)&(d[start]<b)],d[end][(d[end]>=a)&(d[end]<b)]])
   counts=np.searchsorted(np.sort(d[start]),times,side='right')-np.searchsorted(np.sort(d[end]),times,side='right');z['peak_'+label]=int(counts.max())
  return z
 def cohort(self,lo,hi):return self.f[(self.f.global_tick>=lo*30)&(self.f.global_tick<hi*30)]

def main():
 state=json.loads((REC/'continuation_status.json').read_text());rows=[r for r in state['rows'] if r['stage']=='primary'];assert len(rows)==30 and all(r['status']=='PASS' for r in rows)
 assert len({(r['trace'],r['policy'],r['round']) for r in rows})==30
 protected={str(p):sha(p) for p in ROOT.rglob('*') if p.is_file() and OUT not in p.parents}
 gitstatus=subprocess.check_output(['git','status','--short'],text=True)
 (OUT/'input_hashes.json').write_text(json.dumps(protected,indent=2)+'\n')
 (OUT/'phase_a_commit.json').write_text(json.dumps(dict(HEAD=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),origin_main=subprocess.check_output(['git','rev-parse','origin/main'],text=True).strip(),phase_B_commit_push=False),indent=2))
 phases=[];windows=[];boundaries=[];evolution=[];same=[];trans=[];seconds=[];example=[];checks=[]
 for row in rows:
  x=Acquisition(row);d=x.d;assert len(x.f)==11700 and x.f.request_id.nunique()==11700
  assert json.loads((x.directory/'exit.json').read_text())['exit_code']==0
  assert all(np.all(d[b]>=d[a]) for a,b in [('a_ns','actual_generation_ns'),('actual_generation_ns','b_ns'),('b_ns','r_ns'),('r_ns','s_ns'),('s_ns','c_ns')])
  assert np.array_equal(d['c_ns']-d['a_ns'],(d['b_ns']-d['a_ns'])+(d['r_ns']-d['b_ns'])+(d['s_ns']-d['r_ns'])+(d['c_ns']-d['s_ns']))
  old=json.loads((x.directory/'summary.json').read_text());assert abs(metric(x.f)['DMR_percent']-old['DMR_percent'])<1e-10
  for ph in range(4):
   lo=ph*15;hi=lo+15;t=x.t0+lo*10**9;start=x.state(t,left=True);m=metric(x.cohort(lo,hi));assert m['arrival_count']==x.ks[ph]*450
   p=dict(**x.id,phase=ph,K=x.ks[ph],arrival_start_s=lo,arrival_end_s=hi,**m,**x.load_window(lo,hi));phases.append(p)
   ctarget=2 if row['policy']=='FIXED_C2' else 4 if row['policy']=='FIXED_C4' else 2 if x.ks[ph]==6 else 4
   same.append(dict(**x.id,phase=ph,current_K=x.ks[ph],previous_K=x.ks[ph-1] if ph else None,previous_C=start['C'] if ph else None,current_C_target=ctarget,history='STARTUP' if ph==0 else f'K{x.ks[ph-1]}_TO_K{x.ks[ph]}',**{('start_'+k):v for k,v in start.items()},**{('phase_'+k):v for k,v in m.items()}))
   for name,a,b in [('startup' if ph==0 else 'transition',lo,lo+1),('phase_remainder',lo+1,hi)]:
    windows.append(dict(**x.id,phase=ph,K=x.ks[ph],window=name,arrival_start_s=a,arrival_end_s=b,**metric(x.cohort(a,b)),**x.load_window(a,b)))
   if not ph:continue
   cap=x.caps[x.caps.phase.astype(int)==ph].iloc[0];apply=int(cap.ns)
   common=dict(**x.id,phase=ph,boundary_s=lo,boundary_ns=t,K_before=x.ks[ph-1],K_after=x.ks[ph],C_before=start['C'],C_after=int(cap.new_C),logical_boundary_ns=int(cap.logical_boundary_ns),notification_ns=int(cap.notification_ns),apply_ns=apply,cap_apply_delay_ms=(apply-t)/1e6)
   boundaries.append(dict(**common,**start))
   for off in [1,5,10,20,50,100,500,1000]:evolution.append(dict(**common,offset_ms=off,**x.state(t+off*1000000)))
   # Retain service and publication-counter threshold times separately from exact cap apply.
   oldtrans=pd.read_csv(x.directory/'transition_summary.csv');z=oldtrans[(oldtrans.phase==ph)&(oldtrans.cohort_at_apply=='already_service')].iloc[0]
   after=x.state(apply);first=int(z.first_new_admission_ns);firststate=x.state(first,left=True)
   tr=dict(**common,**{'before_'+k:v for k,v in start.items()},**{'apply_'+k:v for k,v in after.items()},**{'before_first_admission_'+k:v for k,v in firststate.items()})
   for key in ['first_A_service_le_C_ns','first_A_service_lt_C_ns','first_counter_le_C_ns','first_counter_lt_C_ns','first_new_admission_ns']:
    tr[key]=int(z[key]);tr[key+'_delay_from_apply_ms']=(int(z[key])-apply)/1e6
   tr['ready_change_apply_to_first_admission']=firststate['ready_queue']-after['ready_queue'];tr['backlog_change_apply_to_first_admission']=firststate['unfinished_backlog']-after['unfinished_backlog']
   trans.append(tr)
   if row['trace']=='B' and row['round']==1 and ph==1 and row['policy'] in ['FIXED_C4','K_LOOKUP_C2_C4']:
    lo_ns=t-50000000;hi_ns=t+100000000
    times=np.unique(np.r_[lo_ns,hi_ns,x.event_times[(x.event_times>=lo_ns)&(x.event_times<=hi_ns)],*[v[(v>=lo_ns)&(v<=hi_ns)] for v in d.values()]])
    for ti in times:example.append(dict(**x.id,phase=ph,relative_ms=(int(ti)-t)/1e6,**x.state(int(ti))))
  for sec in range(61):seconds.append(dict(**x.id,second=sec,**x.state(x.t0+sec*10**9)))
  final=x.state(int(d['completion_publication_ns'].max())+1);assert final['A']==final['ready_queue']==final['unfinished_backlog']==0
  checks.append(dict(acquisition_id=row['acquisition_id'],requests=11700,validation='PASS',primary_DMR_reproduced=True,final_drain_zero=True))
  print(row['acquisition_id'],'CPU analysis PASS',flush=True)
 save('phase_level_metrics.csv',phases);save('secondary_window_metrics.csv',windows);save('boundary_state.csv',boundaries);save('boundary_state_evolution.csv',evolution);save('same_k_different_state.csv',same)
 save('deadline_pressure_at_boundaries.csv',boundaries);save('k7_to_k6_analysis.csv',[x for x in trans if x['K_before']==7]);save('k6_to_k7_analysis.csv',[x for x in trans if x['K_before']==6]);save('trace_order_analysis.csv',seconds);save('figure01_source_timeline.csv',example)
 # Acquisition-block paired contrasts; lookup minus fixed: positive is lookup worse.
 paired=[]
 for window_name,data in [('whole_phase',phases),('secondary',windows)]:
  for u in data:
   if u['policy']!='K_LOOKUP_C2_C4':continue
   for fixed in ['FIXED_C2','FIXED_C4']:
    f=next(v for v in data if v['trace']==u['trace'] and v['round']==u['round'] and v['phase']==u['phase'] and v['policy']==fixed and v.get('window')==u.get('window'))
    z=dict(trace=u['trace'],round=u['round'],phase=u['phase'],K=u['K'],window=u.get('window',window_name),fixed=fixed,lookup_acquisition=u['acquisition_id'],fixed_acquisition=f['acquisition_id'])
    for key in ['DMR_percent','miss_count','queue_mean_ms','queue_p95_ms','service_mean_ms','service_p95_ms','local_mean_ms','local_p95_ms','start_lag_mean_ms','front_end_mean_ms','time_mean_ready_queue','time_mean_unfinished_backlog','calendar_completed_fps']:
     z[key+'_lookup']=u[key];z[key+'_fixed']=f[key];z['delta_'+key]=u[key]-f[key]
    paired.append(z)
 save('round_paired_phase_deltas.csv',paired)
 frame=pd.DataFrame(paired);agg=[]
 for keys,g in frame.groupby(['trace','phase','K','window','fixed'],sort=False):
  z=dict(zip(['trace','phase','K','window','fixed'],keys));z['n_pairs']=len(g)
  for col in [c for c in frame if c.startswith('delta_')]:
   vals=g[col];z[col+'_mean']=vals.mean();z[col+'_SD']=vals.std(ddof=1);z[col+'_positive_rounds']=int((vals>1e-10).sum());z[col+'_negative_rounds']=int((vals< -1e-10).sum());z[col+'_values']=json.dumps(vals.tolist())
  agg.append(z)
 save('lookup_vs_fixed_phase_comparison.csv',agg)
 # Same-K, same-policy comparisons of phase 0 vs 2 and phase 1 vs 3, paired by trace/round.
 aliases=[]
 for tr in ['A','B']:
  for pa,pb in [(0,2),(1,3)]:
   for rd in range(1,6):
    get=lambda p:next(x for x in same if x['trace']==tr and x['policy']=='K_LOOKUP_C2_C4' and x['round']==rd and x['phase']==p)
    a,b=get(pa),get(pb);z=dict(trace=tr,round=rd,K=a['current_K'],C=a['current_C_target'],phase_a=pa,phase_b=pb,history_a=a['history'],history_b=b['history'])
    for key in ['start_A','start_ready_queue','start_unfinished_backlog','start_unfinished_slack_p10_ms','start_unfinished_slack_median_ms','start_unfinished_late_count','phase_DMR_percent','phase_queue_mean_ms','phase_local_p95_ms']:
     z[key+'_a']=a[key];z[key+'_b']=b[key];z['difference_'+key]=None if a[key] is None or b[key] is None else b[key]-a[key]
    z['candidate']='CURRENT_K_STATE_ALIASING_CANDIDATE';z['qualification']='descriptive paired history contrast; no substantial-effect cutoff or causal proof'
    aliases.append(z)
 save('state_aliasing_candidates.csv',aliases)
 mismatch=[p for p,h in protected.items() if sha(Path(p))!=h];assert not mismatch
 assert subprocess.check_output(['git','status','--short'],text=True)==gitstatus
 integrity=dict(validation='PASS',primary_acquisitions=30,requests=351000,new_GPU_acquisitions=0,phase_rows=len(phases),boundary_rows=len(boundaries),evolution_rows=len(evolution),checks=checks,read_only_input_hash_mismatches=mismatch,experimental_unit='acquisition/run',phase_B_committed=False,phase_B_pushed=False,git_status_unchanged=True)
 (OUT/'analysis_integrity.json').write_text(json.dumps(integrity,indent=2)+'\n')
if __name__=='__main__':main()
