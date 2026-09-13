"""Only change: retain actual training W,A_start,S triplets; no new features."""
from pathlib import Path
import hashlib,json
import numpy as np,pandas as pd
import frozen_models as fm
ROOT=Path(__file__).resolve().parents[1]
def main():
 assert json.loads((ROOT/'reproduction_check.json').read_text())['status']=='PASS','REPRODUCTION_FAILURE: no joint output permitted'
 assert not (ROOT/'joint_fold1.npz').exists(),'Refuse overwrite/repeat'
 d=fm.load();rows=[];checks=[];max_q_delta=0;total_state_difference=0
 oldsupport=pd.read_csv(ROOT/'old_transition_support_lookup.csv')
 for fold in range(1,6):
  tr=np.flatnonzero(d['slot']!=fold);te=np.flatnonzero(d['slot']==fold);assert not set(d['run'][tr])&set(d['run'][te])
  tab=fm.tables(d,tr,fm.TL);tf=pd.DataFrame({k:d[k][te] for k in ['K','C','Q','A']});groups={}
  for key,pos in tf.groupby(['K','C','Q','A'],sort=True).indices.items():
   lev,tkey,ix,nr=fm.select(tab,fm.TL,dict(zip(['K','C','Q','A'],key)))
   gid=(int(key[0]),int(key[1]),lev,tkey)
   if gid not in groups:groups[gid]=dict(positions=[],indices=ix,nruns=nr)
   groups[gid]['positions'].append(pos)
  p=np.empty((len(te),3));ids=np.empty(len(te),np.int32);old=dict(np.load(ROOT/f'reproduced_fold{fold}.npz'));sup=oldsupport[oldsupport.fold==fold].set_index('transition_group_id')
  for j,(gid,g) in enumerate(groups.items()):
   k,c,lev,key=gid;pos=np.concatenate(g['positions']);ix=g['indices'];nr=g['nruns'];m=len(ix)
   # These three columns are indexed together from the SAME training frames.
   W=d['W'][ix];As=d['A_start'][ix];S=d['S'][ix];assert len(W)==len(As)==len(S)==m
   assert np.all((As>=0)&(As<c)) and np.all(W>=0) and np.all(S>=0)
   bud=d['b30'][te[pos]];w30=np.sort(30*W);total30=np.sort(30*(W+S))
   nw=np.searchsorted(w30,bud,side='right');nt=np.searchsorted(total30,bud,side='right');assert np.all(nt<=nw)
   p[pos]=np.column_stack([(m-nw)/m,(nw-nt)/m,nt/m]);ids[pos]=j
   ref=sup.loc[j];same=ref.level==fm.TL[lev][0] and ref.key==str(key) and ref.training_samples==m and ref.training_runs==nr
   assert same and np.all(old['transition_group_id'][pos]==j)
   if j%50==0:
    for bi in np.unique(bud[np.linspace(0,len(bud)-1,min(3,len(bud)),dtype=int)]):
     expected=np.array([np.mean(30*W>bi),np.mean((30*W<=bi)&(30*(W+S)>bi)),np.mean(30*(W+S)<=bi)])
     at=np.flatnonzero(bud==bi)[0];assert np.array_equal(expected,p[pos[at]])
     checks.append(dict(fold=fold,group=j,b30=int(bi),direct_tuple_classification_matches=True))
   rows.append(dict(fold=fold,transition_group_id=j,K=k,C=c,level=fm.TL[lev][0],key=str(key),training_samples=m,training_runs=nr,test_frames=len(pos),training_index_sha256=hashlib.sha256(ix.astype('<i8').tobytes()).hexdigest(),old_level=ref.level,old_training_samples=int(ref.training_samples),old_training_runs=int(ref.training_runs),old_joint_support_identical=True))
  assert np.all(np.isfinite(p)) and p.min()>=0 and p.max()<=1 and np.max(abs(p.sum(1)-1))<1e-12
  delta=float(np.max(abs(p[:,0]-old['P_old'][:,0])));assert delta<=1e-15;max_q_delta=max(max_q_delta,delta)
  np.savez_compressed(ROOT/f'joint_fold{fold}.npz',index=old['index'],run=old['run'],K=old['K'],C=old['C'],y=old['y'],P_joint=p,transition_group_id=ids)
  print('joint fold PASS',fold,len(te),'max queue probability delta',delta,flush=True)
 pd.DataFrame(rows).to_csv(ROOT/'joint_support_lookup.csv',index=False)
 (ROOT/'joint_numerical_validation.json').write_text(json.dumps(dict(status='PASS',direct_tuple_checks=checks,max_old_joint_queue_probability_difference=max_q_delta,support_or_backoff_differences=total_state_difference,probability_sum='PASS',heldout_run_separation='PASS',test_W_S_A_start_used_in_prediction=False),indent=2)+'\n')
if __name__=='__main__':main()
