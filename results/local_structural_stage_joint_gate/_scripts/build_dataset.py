"""CPU-only canonical before-state extraction, no runtime imports."""
from pathlib import Path
import hashlib,json,subprocess,sys
import numpy as np
import pandas as pd
REPO=Path('/home/ainet/research/thor-mec-inference')
OUT=Path(__file__).resolve().parents[1]
FORMAL=REPO/'results/local_concurrency_formal_full'
STAGES=['ON_TIME','PRE_READY_LATE','QUEUE_STAGE_MISS','SERVICE_STAGE_MISS']
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1048576),b''):h.update(b)
 return h.hexdigest()
def dump(name,obj):
 (OUT/name).write_text(json.dumps(obj,indent=2,default=lambda x:x.item() if isinstance(x,np.generic) else str(x))+'\n')
def protected():
 data=[]
 for root in [REPO/'results',REPO/'scripts',REPO/'configs',REPO/'AGENTS.md',REPO/'.gitignore']:
  for p in sorted(root.rglob('*')) if root.is_dir() else [root]:
   if p.is_relative_to(OUT):continue
   if p.is_symlink():data.append({'path':str(p.relative_to(REPO)),'symlink':str(p.readlink())})
   elif p.is_file():data.append({'path':str(p.relative_to(REPO)),'size':p.stat().st_size,'sha256':sha(p)})
 dump('protected_inputs_before.json',data)
def main():
 assert not (OUT/'stage_dataset.npz').exists(),'Refuse overwrite'
 startup={cmd:subprocess.check_output(['git',*cmd.split()],cwd=REPO,text=True) for cmd in ['rev-parse HEAD','rev-parse origin/main','status --short']}
 dump('startup_audit.json',{'git':startup,'python':sys.executable,'version':sys.version,'Formal_root':str(FORMAL),'membership':'formal_per_run_summary_valid5.csv statistical_slot','existing_protected_manifest':str(REPO/'results/local_deadline_feasibility_gate/protected_inputs_before.json'),'sklearn':'unavailable in system Python and .venv; no installation; use SciPy logistic','new_GPU_runs':0})
 protected();inputs=[]
 def inp(p,**meta):inputs.append(dict(path=str(p.relative_to(REPO)),size=p.stat().st_size,sha256=sha(p),**meta))
 for p in [FORMAL/'formal_per_run_summary_valid5.csv',FORMAL/'valid5_integrity.json',FORMAL/'campaign_code_hashes.json',FORMAL/'analysis_valid5/metric_definitions.md',FORMAL/'_campaign/profile_fullsource.py',REPO/'scripts/local/local_latency_breakdown_metrics.py']:inp(p,role='membership_or_semantics')
 freeze=json.loads((FORMAL/'campaign_code_hashes.json').read_text())['sha256']
 for p in [FORMAL/'_campaign/profile_fullsource.py',REPO/'scripts/local/local_latency_breakdown_metrics.py']:assert sha(p)==freeze[str(p)]
 df=pd.read_csv(FORMAL/'formal_per_run_summary_valid5.csv')
 assert len(df)==280 and df.source_artifact.nunique()==280 and df.status.eq('PASS').all()
 assert set(zip(df.K,df.C))=={(k,c) for k in range(1,8) for c in range(1,9)}
 assert df.groupby(['K','C']).statistical_slot.apply(lambda x:set(x)==set(range(1,6))).all()
 assert df.groupby('statistical_slot').size().eq(56).all()
 repl=df.query('K==2 and C==1');assert set(repl.run_id)=={'run01','run02','run03','run05','replacement01'}
 rr=repl[repl.run_id=='replacement01'].iloc[0];assert rr.statistical_slot==4 and pd.isna(rr.actual_round_id)
 blocks=[];summaries=[];audit=[];runindex=[]
 for idx,row in df.iterrows():
  base=REPO/row.source_artifact;meta=dict(run_index=int(idx),K=int(row.K),C=int(row.C),valid_slot=int(row.statistical_slot),run_id=row.run_id,acquisition_phase=row.acquisition_phase)
  for fn in ['per_frame.csv','raw_ns.json']:inp(base/fn,**meta)
  x=pd.read_csv(base/'per_frame.csv').sort_values(['stream_id','frame_id']).reset_index(drop=True)
  raw=json.loads((base/'raw_ns.json').read_text());rx=pd.DataFrame(raw['records']).sort_values(['stream_id','frame_id']).reset_index(drop=True)
  assert len(x)==int(row.K)*1800 and not x.duplicated(['stream_id','frame_id']).any()
  assert set(x.stream_id)==set(range(int(row.K))) and all(set(g.frame_id)==set(range(1800)) for _,g in x.groupby('stream_id'))
  assert x.K.eq(row.K).all() and x.C.eq(row.C).all()
  a,b,r,s,c=[x[z+'_ns'].to_numpy(np.int64) for z in ['a','b','r','s','c']]
  for z in ['a_ns','b_ns','r_ns','s_ns','c_ns','inference_queue_depth_before_enqueue']:assert np.array_equal(x[z],rx[z])
  assert np.array_equal(a,int(raw['t0_ns'])+(x.frame_id.to_numpy(np.int64)*1000000000)//30)
  assert np.all((a<=b)&(b<=r)&(r<=s)&(s<=c));assert np.all((b-a)+(r-b)+(s-r)+(c-s)==c-a)
  q=x.inference_queue_depth_before_enqueue.to_numpy(np.int64)
  ids={(int(z.stream_id),int(z.frame_id)):i for i,z in enumerate(x.itertuples())};depth=0;enqueued=set();started=set();last=-1
  for seq,e in enumerate(raw['queue_events']):
   assert e['seq']==seq and e['ns']>=last;last=e['ns'];key=(e['stream_id'],e['frame_id']);i=ids[key]
   if e['kind']=='enqueue':
    assert key not in enqueued and e['ns']==r[i] and depth==q[i];depth+=1;enqueued.add(key)
   elif e['kind']=='start':
    assert key in enqueued and key not in started and e['ns']==s[i];depth-=1;started.add(key)
   else:raise AssertionError('unknown queue event')
   assert depth>=0 and depth==e['depth']
  assert depth==0 and enqueued==started==set(ids)
  # Left-limit interval state, excludes this request at r and s. No future end value enters.
  ss=np.sort(s);cc=np.sort(c)
  A=np.searchsorted(ss,r,side='left')-np.searchsorted(cc,r,side='left')
  As=np.searchsorted(ss,s,side='left')-np.searchsorted(cc,s,side='left')
  assert np.all((A>=0)&(A<=int(row.C))) and np.all((As>=0)&(As<int(row.C)))
  # Verify pre-enqueue count against independent endpoint sweep (lock ordering audited above).
  q2=np.searchsorted(np.sort(r),r,side='left')-np.searchsorted(ss,r,side='left')
  assert np.array_equal(q,q2),'same-ns start/enqueue order needs explicit handling; stop'
  cross_r=int(np.isin(r,cc).sum());cross_s=int(np.isin(s,cc).sum());start_ties=len(s)-len(np.unique(s))
  assert not (cross_r or cross_s or start_ties),'ambiguous same-ns before-state; stop before models'
  br=1000000000-30*(r-a);bs=1000000000-30*(s-a);late=(c-a)*30>1000000000
  stage=np.select([br<0,bs<0,late],[1,2,3],default=0).astype(np.int8)
  assert np.array_equal(stage!=0,x.deadline_miss.astype(bool))
  assert abs(100*np.mean(late)-row.deadline_miss_percent)<1e-8
  block=dict(run=np.full(len(x),idx,np.int16),slot=np.full(len(x),int(row.statistical_slot),np.int8),K=np.full(len(x),row.K,np.int8),C=np.full(len(x),row.C,np.int8),stream_id=x.stream_id.to_numpy(np.int8),frame_id=x.frame_id.to_numpy(np.int16),Q=q.astype(np.int32),A=A.astype(np.int8),A_start=As.astype(np.int8),b30=br,b_start30=bs,W=s-r,S=c-s,stage=stage)
  blocks.append(block)
  z=dict(**meta,total_frames=len(x),ready_on_time=int((stage!=1).sum()),service_start_on_time=int(((stage==0)|(stage==3)).sum()))
  for j,name in enumerate(STAGES):z[name+'_count']=int((stage==j).sum());z[name+'_percent']=100*float(np.mean(stage==j))
  summaries.append(z);runindex.append(dict(**meta,source_artifact=row.source_artifact,actual_round_id=row.actual_round_id))
  # Direct snapshots at deterministic indices, no outcome-dependent sampling.
  for i in np.unique(np.linspace(0,len(x)-1,9,dtype=int)):
   assert A[i]==np.sum((s<r[i])&(c>=r[i])) and As[i]==np.sum((s<s[i])&(c>=s[i]))
  audit.append(dict(**meta,ordering_violations=0,decomposition_violations=0,queue_event_before_state='PASS',A_before_state='PASS',A_start_excludes_target=True,ambiguous_timestamp_ties=0))
  if (idx+1)%40==0:print('validated raw/before-state',idx+1,flush=True)
 arrays={key:np.concatenate([b[key] for b in blocks]) for key in blocks[0]}
 assert len(arrays['stage'])==2016000
 np.savez_compressed(OUT/'stage_dataset.npz',**arrays)
 pd.DataFrame(summaries).to_csv(OUT/'frame_stage_dataset_summary.csv',index=False)
 pd.DataFrame(runindex).to_csv(OUT/'run_index.csv',index=False)
 pd.DataFrame(audit).to_csv(OUT/'before_state_audit.csv',index=False)
 dump('input_manifest.json',dict(inputs=inputs,Static_runs=280,frames=2016000,Dynamic_used=0,replacement='saved statistical slot4; actual round NA',features='before-frame event-time state; observer publication delay not established'))
 dump('dataset_integrity.json',dict(validation='PASS',valid_runs=280,frames=2016000,ready_on_time=int((arrays['stage']!=1).sum()),service_start_on_time=int(np.isin(arrays['stage'],[0,3]).sum()),PRE_READY_LATE=int((arrays['stage']==1).sum()),ordering_violations=0,decomposition_violations=0,before_state_checks='PASS',same_ns_ambiguities=0))
 print('dataset PASS',flush=True)
if __name__=='__main__':main()
