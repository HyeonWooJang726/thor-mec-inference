"""All-five-fold reproduction barrier; no P-joint generation here."""
from pathlib import Path
import hashlib,json,sys
import numpy as np,pandas as pd
import frozen_models as fm
ROOT=Path(__file__).resolve().parents[1];REPO=ROOT.parents[1];OLD=REPO/'results/local_structural_stage_model_gate'
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1048576),b''):h.update(b)
 return h.hexdigest()
def dump(obj):
 (ROOT/'reproduction_check.json').write_text(json.dumps(obj,indent=2,default=lambda x:x.item() if isinstance(x,np.generic) else str(x))+'\n')
def score(y,p):
 return dict(Brier=float(((p-np.eye(3)[y])**2).sum(1).mean()),logloss=float(-np.log(np.clip(p[np.arange(len(y)),y],1e-15,1)).mean()))
def main():
 assert not (ROOT/'reproduction_check.json').exists(),'Refuse overwrite'
 report=dict(status='RUNNING',reference_commit='d965452619af7ea103f8b5f4b421fa608a8d8f6e',probability_atol=1e-10,probability_rtol=1e-10,metric_atol=1e-10,folds=[])
 dump(report)
 try:
  x=dict(np.load(ROOT/'stage_dataset.npz'));old=dict(np.load(OLD/'stage_dataset.npz'))
  assert x.keys()==old.keys() and all(np.array_equal(x[k],old[k]) for k in x),'dataset array mismatch'
  assert len(x['stage'])==2016000 and np.sum(x['stage']!=1)==1973897 and np.sum(x['stage']==1)==42103
  report['dataset_arrays_identical']=True;report['dataset_fields_compared']=list(x);del x,old
  manifest=json.loads((ROOT/'input_manifest.json').read_text());prior=json.loads((OLD/'input_manifest.json').read_text())
  pm={e['path']:e for e in prior['inputs']}
  assert all(e['path'] in pm and e['sha256']==pm[e['path']]['sha256'] and e['size']==pm[e['path']]['size'] for e in manifest['inputs'])
  prevfiles=['analysis_plan.md','metric_definitions.md','structural_stage_model_report.md','input_manifest.json','analysis_integrity.json','stage_dataset.npz','run_index.csv','structural_fold_metrics.csv','transition_support_lookup.csv','service_support_lookup.csv','model_fit_records.json',*[f'predictions_fold{i}.npz' for i in range(1,6)],'_scripts/fit_models.py','_scripts/build_dataset.py','_scripts/empirical_count.cpp']
  for fn in prevfiles:
   p=OLD/fn;manifest['inputs'].append(dict(path=str(p.relative_to(REPO)),size=p.stat().st_size,sha256=sha(p),role='previous_frozen_structural_reference'))
  (ROOT/'input_manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
  report['prior_canonical_input_hashes_match']=True
  d=fm.load();count=fm.engine();savedmetrics=pd.read_csv(OLD/'structural_fold_metrics.csv');records=[];trows=[];srows=[];numerical=[]
  for fold in range(1,6):
   tr=np.flatnonzero(d['slot']!=fold);te=np.flatnonzero(d['slot']==fold)
   assert len(np.unique(d['run'][tr]))==224 and len(np.unique(d['run'][te]))==56 and not set(d['run'][tr])&set(d['run'][te])
   baseline,fit=fm.fit_direct(d,tr,te,True);print('B1 fit complete',fold,flush=True)
   p,ids,ts,ss,checks=fm.structural(d,tr,te,fold,count)
   prev=dict(np.load(OLD/f'predictions_fold{fold}.npz'));expected=dict(index=d['index'][te],run=d['run'][te],K=d['K'][te],C=d['C'][te],y=d['y'][te],transition_group_id=ids)
   assert all(np.array_equal(prev[k],v) for k,v in expected.items())
   item=dict(fold=fold,training_runs=224,test_runs=56,test_frames=len(te),identity_match=True)
   for name,prob,col in [('B1',baseline,'B1'),('P-old',p,'P')]:
    measured=score(expected['y'],prob);ref=savedmetrics[(savedmetrics.fold==fold)&(savedmetrics.model==col)].iloc[0]
    delta=float(np.max(abs(prob-prev[col])));assert np.allclose(prob,prev[col],atol=1e-10,rtol=1e-10),(name,fold,delta)
    assert all(abs(measured[m]-ref[m])<=1e-10 for m in ['Brier','logloss'])
    item[name]=dict(**measured,max_probability_abs_difference=delta,Brier_abs_difference=abs(measured['Brier']-ref.Brier),logloss_abs_difference=abs(measured['logloss']-ref.logloss),reproduced=True)
   np.savez_compressed(ROOT/f'reproduced_fold{fold}.npz',**expected,B1=baseline,P_old=p)
   records.append(dict(fold=fold,B1=fit));trows+=ts;srows+=ss;numerical+=checks
   report['folds'].append(item);dump(report);print('reproduction PASS fold',fold,flush=True)
  pd.DataFrame(trows).to_csv(ROOT/'old_transition_support_lookup.csv',index=False);pd.DataFrame(srows).to_csv(ROOT/'old_service_support_lookup.csv',index=False)
  # Exact table ordering and all scalar support selections must reproduce, too.
  pd.testing.assert_frame_equal(pd.read_csv(ROOT/'old_transition_support_lookup.csv'),pd.read_csv(OLD/'transition_support_lookup.csv'))
  pd.testing.assert_frame_equal(pd.read_csv(ROOT/'old_service_support_lookup.csv'),pd.read_csv(OLD/'service_support_lookup.csv'))
  report.update(status='PASS',B1_reproduced=True,P_old_reproduced=True,training_and_test_population_identical=True,backoff_tables_identical=True,means={m:{metric:float(np.mean([f[m][metric] for f in report['folds']])) for metric in ['Brier','logloss']} for m in ['B1','P-old']})
  (ROOT/'reproduced_model_fits.json').write_text(json.dumps(records,indent=2)+'\n');(ROOT/'old_numerical_validation.json').write_text(json.dumps(numerical,indent=2)+'\n');dump(report)
  print('ALL REPRODUCTION PASS',json.dumps(report['means']),flush=True)
 except Exception as e:
  report.update(status='REPRODUCTION_FAILURE',reason=repr(e),P_joint_generated=False);dump(report);raise
if __name__=='__main__':main()
