"""CPU-only exact empirical structural integration and multinomial direct baselines."""
from pathlib import Path
import os,json,time,ctypes,subprocess,hashlib
import numpy as np,pandas as pd
from scipy import sparse,optimize,special,stats
ROOT=Path(__file__).resolve().parents[1]
CLASS_NAMES=['QUEUE_STAGE_MISS','SERVICE_STAGE_MISS','ON_TIME']

def dump(name,x):
 (ROOT/name).write_text(json.dumps(x,indent=2,default=lambda z:z.item() if isinstance(z,np.generic) else str(z))+'\n')

def load():
 z=dict(np.load(ROOT/'stage_dataset.npz'));mask=z['stage']!=1
 z={k:v[mask] for k,v in z.items()};z['y']=np.select([z['stage']==2,z['stage']==3],[0,1],default=2).astype(np.int8)
 z['index']=np.flatnonzero(mask);return z

def features(d,train,test,state):
 nums=['b30']+(['Q','A'] if state else [])
 raw=np.column_stack([d[k] for k in nums]).astype(float);mu=raw[train].mean(0);sd=raw[train].std(0);sd[sd==0]=1
 def mat(ix):
  n=len(ix);K=d['K'][ix];C=d['C'][ix]
  return sparse.csr_matrix(np.column_stack([np.ones(n),*[K==k for k in range(2,8)],*[C==c for c in range(2,9)],(raw[ix]-mu)/sd]))
 return mat(train),mat(test),dict(numeric=nums,mean=mu.tolist(),sd=sd.tolist())

def fit_direct(d,tr,te,state):
 X,T,scaler=features(d,tr,te,state);y=d['y'][tr];n=len(y);dim=X.shape[1]
 target=np.column_stack([y==0,y==1]).astype(float)
 def fg(beta):
  B=beta.reshape(dim,2);logits=X@B;den=special.logsumexp(np.column_stack([logits,np.zeros(n)]),axis=1)
  ll=den.mean()-np.sum(logits*target)/n+.0005*np.square(B[1:]).sum()
  grad=np.asarray(X.T@(np.exp(logits-den[:,None])-target))/n;grad[1:]+=.001*B[1:]
  return ll,grad.ravel()
 res=optimize.minimize(fg,np.zeros(dim*2),jac=True,method='L-BFGS-B',options=dict(maxiter=1000,gtol=1e-7,ftol=1e-12,maxls=40))
 assert res.success,(res.message,res.fun)
 logits=np.column_stack([T@res.x.reshape(dim,2),np.zeros(len(te))]);p=special.softmax(logits,axis=1)
 return p,dict(scaler=scaler,coefficients=res.x.reshape(dim,2).tolist(),iterations=res.nit,success=bool(res.success),objective=res.fun)

TL=[('KCQA',['K','C','Q','A']),('KCQ',['K','C','Q']),('KCA',['K','C','A']),('KC',['K','C']),('C',['C'])]
SL=[('KCA_start',['K','C','A_start']),('CA_start',['C','A_start']),('KC',['K','C']),('C',['C'])]
def tables(d,tr,levels):
 frame=pd.DataFrame({k:d[k][tr] for k in ['K','C','Q','A','A_start']});out=[]
 for name,keys in levels:
  table={}
  for key,ii in frame.groupby(keys,sort=False).indices.items():
   key=key if isinstance(key,tuple) else (key,);inds=tr[ii];nr=len(np.unique(d['run'][inds]))
   table[tuple(map(int,key))]=(inds,nr)
  out.append(table)
 return out

def select(tabs,levels,values):
 for lev,((name,keys),tab) in enumerate(zip(levels,tabs)):
  key=tuple(int(values[k]) for k in keys);v=tab.get(key)
  if v is not None and len(v[0])>=200 and v[1]>=3:return lev,key,v[0],v[1]
 raise ValueError('No supported empirical fallback')

def engine():
 so=ROOT/'_scripts/empirical_count.so'
 subprocess.run(['g++','-O3','-std=c++17','-shared','-fPIC',str(ROOT/'_scripts/empirical_count.cpp'),'-o',str(so)],check=True)
 lib=ctypes.CDLL(str(so));fun=lib.pair_count
 arr=np.ctypeslib.ndpointer(dtype=np.int64,ndim=1,flags='C_CONTIGUOUS');uarr=np.ctypeslib.ndpointer(dtype=np.uint64,ndim=1,flags='C_CONTIGUOUS')
 fun.argtypes=[arr,ctypes.c_int64,arr,ctypes.c_int64,arr,ctypes.c_int64,uarr];fun.restype=None
 def count(w,s,b):
  w=np.ascontiguousarray(w,dtype=np.int64);s=np.ascontiguousarray(s,dtype=np.int64);b=np.ascontiguousarray(b,dtype=np.int64)
  ans=np.empty(len(b),np.uint64);fun(w,len(w),s,len(s),b,len(b),ans);return ans
 rng=np.random.default_rng(90213)
 for n,m in [(1,1),(10,7),(31,50)]:
  w=np.sort(rng.integers(0,100,n,dtype=np.int64));s=np.sort(rng.integers(0,100,m,dtype=np.int64));b=np.arange(-2,204,dtype=np.int64)
  assert np.array_equal(count(w,s,b),[(w[:,None]+s<=x).sum() for x in b])
 return count

def structural(d,tr,te,fold,count):
 tt=tables(d,tr,TL);st=tables(d,tr,SL);groups={};n=len(te)
 tf=pd.DataFrame({k:d[k][te] for k in ['K','C','Q','A']})
 for key,pos in tf.groupby(['K','C','Q','A'],sort=True).indices.items():
  vals=dict(zip(['K','C','Q','A'],key));lev,tkey,ii,nr=select(tt,TL,vals)
  gid=(int(key[0]),int(key[1]),lev,tkey)
  if gid not in groups:groups[gid]=dict(positions=[],indices=ii,nruns=nr)
  groups[gid]['positions'].append(pos)
 service={};srows=[]
 for k in range(1,8):
  for c in range(1,9):
   for a in range(c):
    lev,key,ii,nr=select(st,SL,dict(K=k,C=c,A_start=a))
    vals=np.sort(d['S'][ii]);sid=len(srows)
    service[k,c,a]=(vals,sid);srows.append(dict(fold=fold,service_lookup_id=sid,K=k,C=c,A_start=a,level=SL[lev][0],key=str(key),training_samples=len(ii),training_runs=nr))
 p=np.empty((n,3));tids=np.empty(n,np.int32);trows=[];checks=[];start=time.monotonic()
 for j,(gid,g) in enumerate(groups.items()):
  k,c,lev,key=gid;pos=np.concatenate(g['positions']);ii=g['indices'];W=d['W'][ii];As=d['A_start'][ii];bud=d['b30'][te[pos]]//30
  sw=np.sort(W);nwait=np.searchsorted(sw,bud,side='right');pq=1-nwait/len(ii);po=np.zeros(len(pos));lookup=[]
  for a in np.unique(As):
   w=np.sort(W[As==a]);s,sid=service[k,c,int(a)];counts=count(w,s,bud);po+=counts.astype(float)/len(ii)/len(s)
   lookup.append(dict(A_start=int(a),service_lookup_id=sid,transition_samples=len(w)))
   if j%75==0:
    bx=int(bud[len(bud)//2]);actual=int(count(w,s,np.array([bx],np.int64))[0]);expect=int(np.searchsorted(s,bx-w,side='right').sum())
    assert actual==expect;checks.append(dict(fold=fold,group=j,A_start=int(a),exact_pairs=actual,independent_sum=expect))
  ps=1-pq-po
  assert np.min(ps)>-1e-12 and np.max(ps)<=1+1e-12
  ps=np.maximum(ps,0);po=1-pq-ps
  p[pos]=np.column_stack([pq,ps,po]);tids[pos]=j
  trows.append(dict(fold=fold,transition_group_id=j,K=k,C=c,level=TL[lev][0],key=str(key),training_samples=len(ii),training_runs=g['nruns'],test_frames=len(pos),service_mixture=json.dumps(lookup)))
  if (j+1)%100==0 or j+1==len(groups):print('structural',fold,j+1,'/',len(groups),'seconds',round(time.monotonic()-start,1),flush=True)
 assert np.isfinite(p).all() and p.min()>=-1e-12 and p.max()<=1+1e-12 and np.max(abs(p.sum(1)-1))<1e-12
 return p,tids,trows,srows,checks

def assumption(d,tr,te,fold):
 rows=[];train=pd.DataFrame({k:d[k][tr] for k in ['K','C','A_start']});test=pd.DataFrame({k:d[k][te] for k in ['K','C','A_start']})
 tg=test.groupby(['K','C','A_start']).indices
 for key,pos in train.groupby(['K','C','A_start']).indices.items():
  ix=tr[pos]
  if len(ix)<200 or len(np.unique(d['run'][ix]))<3 or key not in tg:continue
  tx=te[tg[key]];lo,hi=np.quantile(d['W'][ix],[.25,.75]);ss=np.sort(d['S'][ix])
  for run in np.unique(d['run'][tx]):
   jt=tx[d['run'][tx]==run];low=jt[d['W'][jt]<=lo];high=jt[d['W'][jt]>hi]
   corr=stats.spearmanr(d['W'][jt],d['S'][jt]).statistic if len(jt)>2 and np.ptp(d['W'][jt]) and np.ptp(d['S'][jt]) else np.nan
   lmean=d['S'][low].mean()/1e6 if len(low) else np.nan;hmean=d['S'][high].mean()/1e6 if len(high) else np.nan
   rows.append(dict(fold=fold,run=int(run),K=key[0],C=key[1],A_start=key[2],training_n=len(ix),training_runs=len(np.unique(d['run'][ix])),test_n=len(jt),train_W_q25_ns=lo,train_W_q75_ns=hi,test_low_n=len(low),test_high_n=len(high),test_low_service_mean_ms=lmean,test_high_service_mean_ms=hmean,high_minus_low_ms=hmean-lmean,heldout_spearman_W_S=corr,heldout_service_CDF_mean=np.searchsorted(ss,d['S'][jt],side='right').mean()/len(ss)))
 return rows

def main():
 assert not (ROOT/'predictions_fold1.npz').exists(),'Refuse repeat/overwrite'
 d=load();count=engine();fits=[];trows=[];srows=[];checks=[];aud=[]
 for fold in range(1,6):
  tr=np.flatnonzero(d['slot']!=fold);te=np.flatnonzero(d['slot']==fold)
  assert len(np.unique(d['run'][tr]))==224 and len(np.unique(d['run'][te]))==56
  assert not set(d['run'][tr])&set(d['run'][te]);print('fold',fold,'train',len(tr),'test',len(te),flush=True)
  b0,f0=fit_direct(d,tr,te,False);print('B0 fitted',fold,flush=True)
  b1,f1=fit_direct(d,tr,te,True);print('B1 fitted',fold,flush=True)
  pp,ids,tt,ss,ck=structural(d,tr,te,fold,count)
  np.savez_compressed(ROOT/f'predictions_fold{fold}.npz',index=d['index'][te],run=d['run'][te],K=d['K'][te],C=d['C'][te],y=d['y'][te],B0=b0,B1=b1,P=pp,transition_group_id=ids)
  fits.append(dict(fold=fold,training_runs=224,test_runs=56,B0=f0,B1=f1));trows+=tt;srows+=ss;checks+=ck;aud+=assumption(d,tr,te,fold)
  dump('model_fit_records.json',fits)
  pd.DataFrame(trows).to_csv(ROOT/'transition_support_lookup.csv',index=False);pd.DataFrame(srows).to_csv(ROOT/'service_support_lookup.csv',index=False)
  pd.DataFrame(aud).to_csv(ROOT/'structural_assumption_audit.csv',index=False);dump('numerical_validation.json',dict(exact_count_fixtures='PASS',real_query_crosschecks=checks,probabilities='PASS',run_holdout='PASS'))
  print('fold completed',fold,flush=True)
if __name__=='__main__':main()
