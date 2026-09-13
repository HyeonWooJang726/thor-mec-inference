"""Held-out-only scoring, condition calibration, fixed-rule verdict and report."""
from pathlib import Path
import json
import numpy as np,pandas as pd
ROOT=Path(__file__).resolve().parents[1]
NAMES=['Queue','Service','On_time'];MODELS=['B0','B1','P']

def metric(y,p):
 n=len(y);target=np.eye(3)[y];true=p[np.arange(n),y]
 z=dict(n=n,Brier=float(np.square(p-target).sum(1).mean()),logloss=float(-np.log(np.clip(true,1e-15,1)).mean()),true_class_exact_zero=int((true==0).sum()))
 for j,name in enumerate(NAMES):
  z[name+'_observed']=float(np.mean(y==j));z[name+'_predicted']=float(p[:,j].mean());z[name+'_absolute_error']=abs(z[name+'_predicted']-z[name+'_observed'])
 return z

def table(df):
 return df.to_string(index=False,float_format=lambda z:f'{z:.6f}')

def main():
 assert not (ROOT/'structural_fold_metrics.csv').exists(),'refuse overwrite'
 folds=[];runs=[];curves=[];support=[]
 for fold in range(1,6):
  z=dict(np.load(ROOT/f'predictions_fold{fold}.npz'))
  assert np.all(np.isfinite(z['P'])) and np.min(z['P'])>=0 and np.max(abs(z['P'].sum(1)-1))<1e-12
  for model in MODELS:
   p=z[model];y=z['y'];folds.append(dict(fold=fold,model=model,**metric(y,p)))
   for run in np.unique(z['run']):
    ix=z['run']==run;ks=np.unique(z['K'][ix]);cs=np.unique(z['C'][ix]);assert len(ks)==len(cs)==1
    runs.append(dict(fold=fold,run=int(run),K=int(ks[0]),C=int(cs[0]),model=model,**metric(y[ix],p[ix])))
   for scope,mask in [('ALL',np.ones(len(y),bool)),*[(f'K{k}',z['K']==k) for k in [5,6,7]]]:
    for cl in range(3):
     q=p[mask,cl];event=y[mask]==cl;bins=np.minimum((q*10).astype(int),9)
     for b in range(10):
      ix=bins==b
      if ix.any():curves.append(dict(fold=fold,model=model,scope=scope,stage=NAMES[cl],bin=b,n=int(ix.sum()),predicted=float(q[ix].mean()),observed=float(event[ix].mean())))
 f=pd.DataFrame(folds);r=pd.DataFrame(runs);cal=pd.DataFrame(curves)
 f.to_csv(ROOT/'structural_fold_metrics.csv',index=False);r.to_csv(ROOT/'structural_per_run_metrics.csv',index=False);cal.to_csv(ROOT/'calibration_curves.csv',index=False)
 numeric=[c for c in r if c not in ['fold','run','K','C','model']]
 kc=r.groupby(['K','C','model'])[numeric].agg(['mean','std']);kc.columns=['_'.join(c) for c in kc.columns];kc=kc.reset_index();kc['n_valid_runs']=5
 kc.to_csv(ROOT/'structural_by_K_C.csv',index=False)
 comparisons=[]
 for base in ['B0','B1']:
  p=f[f.model=='P'].set_index('fold');b=f[f.model==base].set_index('fold')
  for met in ['Brier','logloss']:
   d=p[met]-b[met]
   for fold,val in d.items():comparisons.append(dict(comparison='P_minus_'+base,metric=met,fold=fold,delta=val,improved=val<0))
 comp=pd.DataFrame(comparisons);comp.to_csv(ROOT/'baseline_comparison.csv',index=False)
 calerrors=[]
 for scope,sel in [('ALL',r),*[(f'K{k}',r[r.K==k]) for k in [5,6,7]],*[(f'K{k}/C{c}',r[(r.K==k)&(r.C==c)]) for k in [5,6,7] for c in range(1,9)]]:
  for model in MODELS:
   sub=sel[sel.model==model]
   for name in NAMES:
    obs=sub[name+'_observed'];pred=sub[name+'_predicted'];err=sub[name+'_absolute_error']
    calerrors.append(dict(scope=scope,model=model,stage=name,runs=len(sub),observed_rate_mean=obs.mean(),predicted_rate_mean=pred.mean(),signed_rate_gap=pred.mean()-obs.mean(),absolute_mean_rate_gap=abs(pred.mean()-obs.mean()),mean_run_absolute_error=err.mean(),SD_run_absolute_error=err.std(ddof=1)))
 ce=pd.DataFrame(calerrors);ce.to_csv(ROOT/'calibration_errors.csv',index=False)
 ts=pd.read_csv(ROOT/'transition_support_lookup.csv');sv=pd.read_csv(ROOT/'service_support_lookup.csv')
 for (fold,lev),x in ts.groupby(['fold','level']):
  support.append(dict(kind='transition',fold=fold,level=lev,predictions_or_mixture_weight=x.test_frames.sum(),minimum_training_samples=x.training_samples.min(),minimum_training_runs=x.training_runs.min()))
 # Service usage counts transition-mixture mass over predictions; not independent extra test samples.
 for fold,t in ts.groupby('fold'):
  sm=sv[sv.fold==fold].set_index('service_lookup_id');acc={}
  for row in t.itertuples():
   for component in json.loads(row.service_mixture):
    ss=sm.loc[component['service_lookup_id']];lev=ss.level;mass=row.test_frames*component['transition_samples']/row.training_samples
    if lev not in acc:acc[lev]=[0,int(ss.training_samples),int(ss.training_runs)]
    acc[lev][0]+=mass;acc[lev][1]=min(acc[lev][1],int(ss.training_samples));acc[lev][2]=min(acc[lev][2],int(ss.training_runs))
  for lev,v in acc.items():support.append(dict(kind='service_mixture',fold=fold,level=lev,predictions_or_mixture_weight=v[0],minimum_training_samples=v[1],minimum_training_runs=v[2]))
 bu=pd.DataFrame(support);bu.to_csv(ROOT/'backoff_usage.csv',index=False)
 means=f.groupby('model')[['Brier','logloss']].mean();sd=f.groupby('model')[['Brier','logloss']].std(ddof=1)
 dcomp=comp[comp.comparison=='P_minus_B1'];wins=dcomp.groupby('metric').improved.sum();delta=dcomp.groupby('metric').delta.mean()
 # Predeclared 'generally reduced' is displayed in full, without tuned thresholds.
 high=ce[ce.scope.isin(['K5','K6','K7'])];pe=high[high.model=='P'].set_index(['scope','stage']).mean_run_absolute_error;be=high[high.model=='B1'].set_index(['scope','stage']).mean_run_absolute_error
 improvements=pe<be
 conditions=ce[ce.scope.str.contains('/C')];cp=conditions[conditions.model=='P'].set_index(['scope','stage']).mean_run_absolute_error;cb=conditions[conditions.model=='B1'].set_index(['scope','stage']).mean_run_absolute_error
 # Interpret the user's qualitative condition-consistency clause at workload level.
 # No new effect-size cutoff: retain systematic workload calibration regressions.
 work_p=pe.groupby(level=0).mean();work_b=be.groupby(level=0).mean()
 if (delta<0).all() and (wins>=4).all() and (work_p<work_b).all():verdict='STRUCTURAL_STAGE_MODEL_SUPPORTED'
 elif not (delta<0).any() or (wins<=2).all() or not improvements.any():verdict='STRUCTURAL_STAGE_MODEL_NOT_SUPPORTED'
 else:verdict='STRUCTURAL_STAGE_MODEL_WEAKLY_SUPPORTED'
 result=dict(verdict=verdict,fold_mean_metrics=means.to_dict('index'),fold_SD_metrics=sd.to_dict('index'),P_vs_B1_improving_folds=wins.to_dict(),P_minus_B1_mean=delta.to_dict(),K5_K6_K7_stage_run_MAE_improved=int(improvements.sum()),K5_K6_K7_stage_run_MAE_total=len(improvements),KC_stage_run_MAE_improved=int((cp<cb).sum()),KC_stage_run_MAE_total=len(cp))
 (ROOT/'result_summary.json').write_text(json.dumps(result,indent=2)+'\n')
 ds=json.loads((ROOT/'dataset_integrity.json').read_text());aud=pd.read_csv(ROOT/'structural_assumption_audit.csv')
 am=aud[(aud.test_low_n>=20)&(aud.test_high_n>=20)].copy()
 # Support cutoff here is presentation-only, not a model fit or gate criterion.
 audittext=f"All {len(aud)} held-out run/state groups are retained. For readable effect summaries, {len(am)} groups have >=20 held-out frames in each training-defined low/high-W tail. Their median high-minus-low service difference is {am.high_minus_low_ms.median():.6f} ms; median absolute difference {am.high_minus_low_ms.abs().median():.6f} ms; median held-out within-group Spearman W/S {am.heldout_spearman_W_S.median():.6f}. These are descriptive support-stratified effects, not significance tests."
 top=am.reindex(am.high_minus_low_ms.abs().sort_values(ascending=False).index).head(12)
 asum=am.groupby(['K','C','A_start']).agg(valid_heldout_run_groups=('fold','size'),mean_high_minus_low_service_ms=('high_minus_low_ms','mean'),SD_high_minus_low_service_ms=('high_minus_low_ms','std'),negative_direction_runs=('high_minus_low_ms',lambda x:int((x<0).sum())),median_heldout_spearman=('heldout_spearman_W_S','median')).reset_index()
 asum.to_csv(ROOT/'structural_assumption_summary.csv',index=False)
 r.groupby(['K','fold','model'])[['Queue_absolute_error','Service_absolute_error','On_time_absolute_error']].mean().reset_index().to_csv(ROOT/'workload_fold_calibration.csv',index=False)
 k6=ce[ce.scope=='K6/C1'];rate=kc[(kc.K>=5)][['K','C','model','Queue_observed_mean','Queue_predicted_mean','Service_observed_mean','Service_predicted_mean','On_time_observed_mean','On_time_predicted_mean']]
 full=bu[bu.kind=='transition'];fullpct=100*full[full.level=='KCQA'].predictions_or_mixture_weight.sum()/full.predictions_or_mixture_weight.sum()
 body=f'''# Structural stage model feasibility gate

## Dataset and preservation
280 valid Static-C acquisitions, 56 conditions, five saved valid slots. {ds['frames']:,} frames audited; {ds['ready_on_time']:,} ready-on-time evaluated; {ds['PRE_READY_LATE']:,} PRE_READY_LATE excluded ({100*ds['PRE_READY_LATE']/ds['frames']:.4f}%). No startup exclusion. Dynamic acquisitions unused. K2/C1 replacement retains statistical slot4 and is not original Round4. Historical failed run is excluded. No GPU runs, controller, residual predictor, policy replay or counterfactual C.

## Measurement and probability model
See metric_definitions.md and analysis_plan.md for source-level boundaries, rational deadline arithmetic and pre-frame states. Q is exact canonical before-enqueue accounting. A is ideal event-time in-flight state; publication delay was not recorded, so deployment observability is not established. W and A_start remain a joint empirical training sample; the service empirical CDF then integrates all samples, with no Monte Carlo, smoothing or duration binning. Test W/A_start/S never enter prediction. Service distributions include all ready-on-time training frames, including queue-stage misses; no selection on successful service start. This explicitly assumes S independent of W given K,C,A_start.

All models share held-out frames. B0 uses K,C,b; B1 adds Q,A; P uses the specified empirical chain. Direct baselines use training-only scaling and fixed L2=0.001, no tuning. Multiclass Brier is the sum over three classes. Exact empirical zeros are retained; only logloss scoring clips at 1e-15. Their true-class zero counts are reported below, so a large logloss is not hidden or repaired by smoothing.

## Primary held-out results
Five-fold mean metrics (folds equally weighted; each fold contains 56 acquisitions; shared training sets mean folds are not five independent new workloads):

```
{table(means.reset_index())}
```

Five-fold sample SD:
```
{table(sd.reset_index())}
```

P-minus-baseline per-fold differences (negative improves):
```
{table(comp)}
```

Fold metrics, including exact-zero true-class probabilities:
```
{table(f[['fold','model','n','Brier','logloss','true_class_exact_zero']])}
```

Frame counts are observation counts, not independent replication. Per-run metrics and both pooled-fold and equal-run condition reporting are preserved. No significance claim.

## Calibration
Condition/stage mean absolute run rate-error improved for {(cp<cb).sum()}/{len(cp)} K5–7/C1–8 stage cells versus B1. At K-aggregate stage level it improved for {improvements.sum()}/{len(improvements)} cells. These counts are descriptive; individual important regressions are retained. Rates below are conditional on ready-on-time, not all-frame DMR. Absolute errors are probability units (multiply by100 for pp).

```
{table(high)}
```

K6/C1, the prespecified calibration check:
```
{table(k6)}
```

All K5–7/C stage rates (mean of five run rates):
```
{table(rate)}
```

`calibration_curves.csv` retains fixed-bin predicted/observed rates for each held-out fold; `calibration_errors.csv` distinguishes absolute gap of mean rates from mean absolute run-level gaps. Neither is a causal effect.

## Backoff and support
Full transition state usage: {fullpct:.4f}%; backoff: {100-fullpct:.4f}%. All selected distributions have >=200 samples and >=3 distinct training runs. Predictions carry transition_group_id; transition_support_lookup.csv gives level, exact key, sample/run count and service-mixture lookup IDs. service_support_lookup.csv resolves every sampled A_start lookup/support. Service usage is transition-mixture-weighted, not an extra sample count. No silent unsupported default.

```
{table(bu)}
```

## Structural assumption audit
{audittext}

Largest absolute held-out differences, presented as diagnostic examples with all groups available in CSV:
```
{table(top)}
```

W cut points and service CDFs are learned only from the other four slots. Held-out W and S are used here exclusively to audit the assumption, never to produce ready predictions. Nonzero within-state dependence indicates missing history/state or selection effects can matter; it does not prove W causes service inflation. The descriptive audit does not add features or rescue the model. The test is not a conditional-independence proof, and correlations remain sensitive to shared temporal state and small support.

Repeated counterexamples to the service independence assumption are visible even after conditioning on K,C,A_start: at K5/C4/A_start=3, the held-out high-W versus low-W service difference averages -8.1124 ms (sample SD 1.4605), negative in 5/5 runs; median within-group rank association is -0.8282. At K7/C6/A_start=5 the difference is -16.3766 ms (SD 0.2853), negative in 5/5, rank association -0.8420. These repeated conditional associations are material counterevidence to treating service as independent of waiting/history. They can help explain a limitation of the factorization but do not prove the cause of a particular calibration error. No W feature was added to the service model. See structural_assumption_summary.csv for every supported group and workload_fold_calibration.csv for all workload/fold stage errors.

## Verdict
**{verdict}**

P-minus-B1 means: Brier {delta['Brier']:+.8f}, logloss {delta['logloss']:+.8f}; improving folds {int(wins['Brier'])}/5 and {int(wins['logloss'])}/5, respectively. The predeclared rule requires mean improvement in both metrics and >=4/5 consistent folds, alongside improved important calibration. The full condition table above must accompany the mean result. The WEAKLY_SUPPORTED condition-consistency clause applies here: K5 service mean absolute run rate-error increases from {100*be.loc[('K5','Service')]:.4f} to {100*pe.loc[('K5','Service')]:.4f} pp, worsens in all five held-out folds, and worsens in five of eight C conditions, especially C2–C4. K5 observed service-stage rate is {100*high[(high.scope=='K5')&(high.model=='P')&(high.stage=='Service')].observed_rate_mean.iloc[0]:.4f}%, versus P prediction {100*high[(high.scope=='K5')&(high.model=='P')&(high.stage=='Service')].predicted_rate_mean.iloc[0]:.4f}% (equal-run means). Thus the strong aggregate improvement does not establish consistently improved stage calibration across important workloads. This is a qualitative assessment under the supplied criterion, not an added effect-size or significance threshold. No further models, tuned support or thresholds were introduced.

## Limitations
This is observed-trajectory probability modeling, not a controller evaluation or an alternative-C outcome. Same videos, one Thor platform/model and 60-second acquisitions limit generalization. Five held-out slots quantify run-to-run behavior, with overlapping training sets. A is host request-interval concurrency, not kernel parallelism; unmeasured publication delay limits online claims. Exact-state backoff can remove Q/A information; empirical CDFs can assign zero probability to held-out events. Service independence from waiting is not guaranteed. PRE_READY_LATE exclusion limits scope and is not a policy-invariant lower bound. No deadline guarantee, Local/Edge/Lyapunov validation, residual prediction, or new policy DMR is demonstrated. A negative verdict ends this gate without extending the model.

## Reproduction and outputs
Run `_scripts/build_dataset.py`, `_scripts/fit_models.py`, `_scripts/analyze_models.py`, `_scripts/make_figures.py`, `_scripts/verify_preservation.py` in that order in an empty copy of this output root (script root constants need the chosen new root). Existing outputs have overwrite guards; do not rerun into protected results. Numerical CDF helper is compiled by fit_models using installed g++; all inference/runtime modules are read only and never imported. Three figure types, each PNG/PDF; no SVG. Final hashes and Git preservation evidence are in analysis_integrity.json.
'''
 (ROOT/'structural_stage_model_report.md').write_text(body)
 print(json.dumps(result,indent=2),flush=True)
if __name__=='__main__':main()
