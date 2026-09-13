"""Predeclared held-out comparisons and verdict, no model fitting or tuning."""
from pathlib import Path
import json
import numpy as np,pandas as pd
ROOT=Path(__file__).resolve().parents[1]
NAMES=['Queue','Service','On_time'];MODELS=['B1','P-old','P-joint']
def score(y,p):
 n=len(y);target=np.eye(3)[y];true=p[np.arange(n),y]
 z=dict(n=n,Brier=float(((p-target)**2).sum(1).mean()),logloss=float(-np.log(np.clip(true,1e-15,1)).mean()),true_class_exact_zero=int((true==0).sum()))
 for j,name in enumerate(NAMES):
  z[name+'_observed']=float((y==j).mean());z[name+'_predicted']=float(p[:,j].mean());z[name+'_absolute_error']=abs(z[name+'_predicted']-z[name+'_observed'])
 return z

def table(x):return x.to_string(index=False,float_format=lambda v:f'{v:.6f}')
def main():
 assert json.loads((ROOT/'reproduction_check.json').read_text())['status']=='PASS'
 assert not (ROOT/'fold_metrics.csv').exists(),'Refuse overwrite'
 fs=[];rs=[]
 for fold in range(1,6):
  old=dict(np.load(ROOT/f'reproduced_fold{fold}.npz'));joint=dict(np.load(ROOT/f'joint_fold{fold}.npz'))
  assert all(np.array_equal(old[k],joint[k]) for k in ['index','run','K','C','y','transition_group_id'])
  for name,p in [('B1',old['B1']),('P-old',old['P_old']),('P-joint',joint['P_joint'])]:
   fs.append(dict(fold=fold,model=name,**score(old['y'],p)))
   for run in np.unique(old['run']):
    ix=old['run']==run;rs.append(dict(fold=fold,run=int(run),K=int(old['K'][ix][0]),C=int(old['C'][ix][0]),model=name,**score(old['y'][ix],p[ix])))
 f=pd.DataFrame(fs);r=pd.DataFrame(rs);f.to_csv(ROOT/'fold_metrics.csv',index=False);r.to_csv(ROOT/'per_run_metrics.csv',index=False)
 summary=f.groupby('model')[['Brier','logloss']].agg(['mean','std']);summary.columns=['_'.join(c) for c in summary.columns];summary=summary.reindex(MODELS).reset_index();summary.to_csv(ROOT/'model_metric_summary.csv',index=False)
 old=f[f.model=='P-old'].set_index('fold');joint=f[f.model=='P-joint'].set_index('fold');paired=[]
 for fold in range(1,6):
  for m in ['Brier','logloss']:
   diff=joint.loc[fold,m]-old.loc[fold,m];paired.append(dict(fold=fold,metric=m,old_value=old.loc[fold,m],joint_value=joint.loc[fold,m],delta_joint_minus_old=diff,improved=diff<0))
 pair=pd.DataFrame(paired);pair.to_csv(ROOT/'paired_model_comparison.csv',index=False)
 cal=[]
 scopes=[('ALL',None,None),*[(f'K{k}',k,None) for k in range(1,8)],*[(f'K{k}/C{c}',k,c) for k in [5,6,7] for c in range(1,9)]]
 for scope,k,c in scopes:
  sub=r if k is None else r[r.K==k]
  if c is not None:sub=sub[sub.C==c]
  for model in MODELS:
   m=sub[sub.model==model]
   for stage in NAMES:
    obs=m[stage+'_observed'];pred=m[stage+'_predicted'];errs=m[stage+'_absolute_error']
    cal.append(dict(scope=scope,K=k,C=c,model=model,stage=stage,n_runs=len(m),n_frames=int(m.n.sum()),observed_rate=obs.mean(),observed_run_SD=obs.std(ddof=1),predicted_rate=pred.mean(),predicted_run_SD=pred.std(ddof=1),signed_error=pred.mean()-obs.mean(),absolute_error=abs(pred.mean()-obs.mean()),mean_run_absolute_error=errs.mean(),run_absolute_error_SD=errs.std(ddof=1)))
 ce=pd.DataFrame(cal);ce[ce.C.isna()].to_csv(ROOT/'calibration_by_K.csv',index=False);ce[ce.C.notna()].to_csv(ROOT/'calibration_by_K_C.csv',index=False)
 key=ce[((ce.scope=='K5')&(ce.stage=='Service'))|((ce.scope=='K6/C1')&(ce.stage=='Queue'))];key.to_csv(ROOT/'key_condition_comparison.csv',index=False)
 s=pd.read_csv(ROOT/'joint_support_lookup.csv');usage=[]
 for fold in [0,1,2,3,4,5]:
  t=s if fold==0 else s[s.fold==fold];total=t.test_frames.sum()
  for level in ['KCQA','KCQ','KCA','KC','C']:
   v=t[t.level==level];weights=v.test_frames
   usage.append(dict(fold=fold,level=level,test_frames=int(weights.sum()),usage_percent=100*weights.sum()/total,lookup_groups=len(v),training_samples_min=v.training_samples.min(),training_samples_weighted_mean=np.average(v.training_samples,weights=weights) if len(v) else np.nan,training_samples_max=v.training_samples.max(),training_runs_min=v.training_runs.min(),training_runs_max=v.training_runs.max(),old_joint_backoff_differences=int((~v.old_joint_support_identical).sum())))
 usage=pd.DataFrame(usage);usage.to_csv(ROOT/'backoff_usage.csv',index=False)
 pm=pair.groupby('metric').delta_joint_minus_old.mean();wins=pair.groupby('metric').improved.sum()
 ko=key[(key.scope=='K5')&(key.model=='P-old')].iloc[0];kj=key[(key.scope=='K5')&(key.model=='P-joint')].iloc[0]
 cells=ce[(ce.K==5)&(ce.C.notna())&(ce.stage=='Service')];co=cells[cells.model=='P-old'].set_index('C');cj=cells[cells.model=='P-joint'].set_index('C')
 cellwins=int((cj.absolute_error<co.absolute_error).sum());cellwins_run=int((cj.mean_run_absolute_error<co.mean_run_absolute_error).sum());qj=key[(key.scope=='K6/C1')&(key.model=='P-joint')].iloc[0]
 criteria=dict(Brier_mean_improved=bool(pm['Brier']<0),logloss_mean_improved=bool(pm['logloss']<0),Brier_at_least_4_of_5=bool(wins['Brier']>=4),logloss_at_least_4_of_5=bool(wins['logloss']>=4),K5_service_mean_run_error_reduced=bool(kj.mean_run_absolute_error<ko.mean_run_absolute_error),K5_service_absolute_error_cells_at_least_5=cellwins>=5,K6_C1_queue_absolute_error_at_most_5pp=bool(qj.absolute_error<=.05))
 if not criteria['Brier_mean_improved'] or not criteria['logloss_mean_improved'] or (wins<=2).any() or not criteria['K5_service_mean_run_error_reduced']:verdict='JOINT_STAGE_MODEL_NOT_SUPPORTED'
 elif all(criteria.values()):verdict='JOINT_STAGE_MODEL_SUPPORTED'
 else:verdict='JOINT_STAGE_MODEL_WEAKLY_SUPPORTED'
 result=dict(verdict=verdict,criteria=criteria,mean_metrics=summary.to_dict('records'),paired_mean_delta=pm.to_dict(),improving_folds=wins.to_dict(),K5_service_old_error_pp=100*ko.mean_run_absolute_error,K5_service_joint_error_pp=100*kj.mean_run_absolute_error,K5_service_improved_cells_absolute_mean_error=cellwins,K5_service_improved_cells_mean_run_absolute_error=cellwins_run,K6_C1_queue_joint_error_pp=100*qj.absolute_error,full_state_usage_percent=float(usage[(usage.fold==0)&(usage.level=='KCQA')].usage_percent.iloc[0]))
 (ROOT/'result_summary.json').write_text(json.dumps(result,indent=2)+'\n')
 repro=json.loads((ROOT/'reproduction_check.json').read_text());nv=json.loads((ROOT/'joint_numerical_validation.json').read_text())
 txt=f'''# Joint structural stage model feasibility gate

## Scope and dataset
This gate changes only the old probability factorization, retaining observed training-frame (W,A_start,S) triplets under the same ready-state lookup. No additional feature, model family, smoothing, tuning, GPU acquisition, controller, action or policy replay. All old files remain read-only.

The previous dataset arrays were independently rebuilt from canonical raw and matched exactly: 280 valid runs, K1–7/C1–8, 2,016,000 frames; 1,973,897 ready-on-time evaluated; 42,103 PRE_READY_LATE excluded. Both training and test populations follow the same eligibility rule, including queue-stage-late service observations in training. No startup/outlier removal. K2/C1 replacement remains saved statistical slot4; failed historical run04 is excluded. Slot4 is not original temporal Round4. Dynamic acquisitions are unused.

## B1/P-old reproduction barrier
Reference commit d965452619af7ea103f8b5f4b421fa608a8d8f6e matches startup HEAD and origin/main. Previous extraction/fit/empirical counting code was copied byte-for-byte and compared with that commit. B1 was refitted with original train-only scaling, categorical encoding, L2=0.001 and optimizer settings; P-old distributions were rebuilt. We did not substitute prior predictions for the new computation. Every eligible frame ID, label, backoff ID, support table and probability was checked against the prior files. All five reproduction folds passed before P-joint predictions were generated. Tolerance was frozen at probability atol=rtol=1e-10 and metric absolute difference1e-10. See reproduction_check.json for actual differences and hashes in input_manifest.json.

Reproduced means:
```
{json.dumps(repro['means'],indent=2)}
```

## Same state, joint outcomes
At ready, input is K,C,Q,A,b30 only. Q is before target enqueue; A is target-excluded in-flight state immediately before ready. W=s-r, S=c-s and A_start are retained together by training row identity. Test W,S,A_start never condition a prediction. P-old uses empirical W/A_start then an independent conditional service CDF; P-joint uses actual paired W+S from each selected training row. No different-C outcome is computed.

Exact rational deadline: b30=1e9-30*(r-a). Queue count uses 30W>b30; Service uses 30W<=b30<30(W+S); On-time uses 30(W+S)<=b30. Sorting integer30W and integer30(W+S) gives exact CDF counts without a rounded deadline. Direct tuple classifications cross-check deterministic queries. Class order is Queue, Service, On-time; probabilities sum to1.

Transition support/backoff remains KCQA -> KCQ -> KCA -> KC -> C, >=200 samples AND >=3 distinct training runs. Every selected training index set is hashed and its support/backoff linked to each held-out prediction. Old/joint backoff discrepancies: {nv['support_or_backoff_differences']}. Maximum old/joint queue probability difference: {nv['max_old_joint_queue_probability_difference']:.3g}. The unchanged W marginal means Queue risk is algebraically preserved: K6/C1 success retention is expected, not a newly discovered queue-model improvement.

## Held-out metrics
Five held-out slots; each uses224 training and56 test runs, no shared run within a fold. Brier sums three squared class-probability errors. Logloss retains exact empirical zeros and clips only scoring probabilities to1e-15. No smoothing is introduced. Metrics are pooled over eligible frames within a fold, then reported as equally weighted fold mean and sample SD. Runs, not frames, are experimental units; folds have overlapping training data and are not independent workload draws.

```
{table(summary)}
```

All fold values:
```
{table(f)}
```

Paired P-joint minus P-old (negative improves):
```
{table(pair)}
```

## Calibration, including required conditions
Calibration rates are equal-run mean observed/predicted fractions, conditional on ready-on-time. Signed error is predicted minus observed, absolute error is its absolute value; mean run absolute error averages the absolute within-run gaps. CSVs distinguish these and include sample SD. Rates are probability units; multiply by100 for percentage points. These are not all-frame DMR.

K5 Service mean run absolute error: {100*ko.mean_run_absolute_error:.6f} pp -> {100*kj.mean_run_absolute_error:.6f} pp. K5/C Service absolute mean-rate error improves in {cellwins}/8 cells; the mean-run-absolute counterpart improves in {cellwins_run}/8. The primary cell-count interpretation was frozen in analysis_plan.md before results.

Required key conditions:
```
{table(key)}
```

All K5/C service cells retained:
```
{table(cells)}
```

Overall/K5/K6/K7 calibration:
```
{table(ce[ce.scope.isin(['ALL','K5','K6','K7'])])}
```

All K5–7/C1–8 class rates and errors are in calibration_by_K_C.csv; no favorable-cell-only reporting. Full per-run metrics remain available for each comparison.

Remaining K5 bias is not eliminated: the P-joint Service predicted mean is {100*kj.predicted_rate:.4f}% versus observed {100*kj.observed_rate:.4f}%. Its mean run absolute error is {100*kj.mean_run_absolute_error:.4f} pp, compared with B1 {100*key[(key.scope=='K5')&(key.model=='B1')].mean_run_absolute_error.iloc[0]:.4f} pp. Passing this gate therefore supports improvement over P-old under the supplied criteria; it does not establish perfect calibration or superiority in every individual condition.

## Support and backoff
```
{table(usage[usage.fold==0])}
```

Full-state usage is {result['full_state_usage_percent']:.6f}%; remaining usage follows the original backoff. No test labels or test W/S/A_start select support. joint_support_lookup.csv records training sample/run counts, training-index hashes and old comparisons; prediction files carry the lookup ID. A_start remains in the source tuple and is not a new target feature.

## Predeclared verdict
**{verdict}**

```
{json.dumps(criteria,indent=2)}
```

Improving folds: Brier {int(wins['Brier'])}/5, logloss {int(wins['logloss'])}/5. Mean differences: Brier {pm['Brier']:+.8f}, logloss {pm['logloss']:+.8f}. Criteria are exactly those supplied before analysis: both mean metrics improve, each >=4/5, K5 mean-run Service error reduces, >=5/8 K5 Service cells improve, K6/C1 Queue error<=5pp. NOT_SUPPORTED takes precedence if either mean does not improve, either metric improves in<=2 folds or K5 mean-run Service error does not decrease. No post-result rule changes.

## Interpretation and limitations
This ablation asks whether retaining the observed W/S association improves the probability model. It does not establish that the old independence assumption uniquely caused all errors; besides W/S coupling, the triplet keeps all observed associations between ready state and service within each selected support group, whereas the old service pool marginalized some of them. This is the requested single replacement of the factorized distribution, not an added observed feature.

Any support is confined to held-out acquisitions of this same static grid, video content, model and Thor platform. Empirical probabilities may still be poorly calibrated in sparse regimes. Publication/receipt delay was not recorded: A is ideal event-time state, not validated observer receipt state. A is application in-flight count, not GPU kernel parallelism. PRE_READY_LATE exclusion limits scope and does not prove an immutable policy lower bound. No residual-time prediction, deadline guarantee, alternative-C outcome, scheduler improvement, Local/Edge or Lyapunov validity is demonstrated. No additional model or history feature was tried to improve the verdict.

## Reproduction and files
In a new output directory containing these script copies: build_dataset.py -> reproduce_old.py -> fit_joint.py -> analyze_joint.py -> make_figures.py -> verify_integrity.py. Root derives from the script location. Existing-output guards prevent reruns/overwrites. `frozen_models.py` is an unchanged reference module; do not execute its original main entrypoint (it would run the prior gate, including B0). Only the listed reproduction wrapper invokes B1 and P-old. Code hashes, input hashes and numerical checks preserve provenance. Three PNG/PDF figure types only. analysis_integrity.json records final preservation and Git state; commit/push is NO.
'''
 (ROOT/'joint_stage_model_report.md').write_text(txt)
 print(json.dumps(result,indent=2),flush=True)
if __name__=='__main__':main()
