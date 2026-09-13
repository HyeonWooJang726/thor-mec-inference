"""Only three PNG/PDF figure types from held-out derived CSVs."""
from pathlib import Path
import os
os.environ.setdefault('MPLCONFIGDIR','/tmp/structural_joint_mpl')
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import pandas as pd,numpy as np
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'figures'
plt.rcParams.update({'font.family':'DejaVu Sans','font.size':9,'axes.labelsize':9,'legend.fontsize':8,'xtick.labelsize':8,'ytick.labelsize':8,'pdf.fonttype':42,'axes.spines.top':False,'axes.spines.right':False,'savefig.facecolor':'white','lines.linewidth':1.4})
MODELS=['B1','P-old','P-joint'];COL={'B1':'#777777','P-old':'#D55E00','P-joint':'#0072B2'};MARK={'B1':'^','P-old':'s','P-joint':'o'}
def save(fig,name):
 for ext in ['png','pdf']:
  p=OUT/f'{name}.{ext}';assert not p.exists(),'Refuse figure overwrite';fig.savefig(p,dpi=300,bbox_inches='tight')
 plt.close(fig)
def main():
 f=pd.read_csv(ROOT/'fold_metrics.csv');kc=pd.read_csv(ROOT/'calibration_by_K_C.csv');key=pd.read_csv(ROOT/'key_condition_comparison.csv')
 fig,axs=plt.subplots(1,2,figsize=(7.1,2.8),layout='constrained')
 for ax,met in zip(axs,['Brier','logloss']):
  for j,m in enumerate(MODELS):
   v=f[f.model==m][met].to_numpy();ax.errorbar(j,v.mean(),yerr=v.std(ddof=1),fmt=MARK[m],ms=6,color=COL[m],capsize=4)
   ax.scatter(j+np.linspace(-.09,.09,5),v,s=12,color=COL[m],alpha=.6)
  ax.set(xticks=range(3),xticklabels=MODELS,xlim=(-.45,2.45),ylabel='Multiclass '+('Brier score' if met=='Brier' else 'log loss'));ax.set_ylim(bottom=0);ax.grid(axis='y',alpha=.15)
 save(fig,'figure01_old_vs_joint_metrics')
 fig,axs=plt.subplots(1,2,figsize=(7.1,3.0),layout='constrained');k=kc[(kc.K==5)&(kc.stage=='Service')]
 obs=k[k.model=='P-old'].sort_values('C');axs[0].plot(obs.C,100*obs.observed_rate,color='black',marker='x',ms=5,label='Observed')
 for m in MODELS:
  x=k[k.model==m].sort_values('C');axs[0].plot(x.C,100*x.predicted_rate,color=COL[m],marker=MARK[m],ms=4,label=m)
  axs[1].plot(x.C,100*x.absolute_error,color=COL[m],marker=MARK[m],ms=4,label=m)
 for ax in axs:ax.set(xlabel='Static concurrency cap C',xticks=range(1,9),xlim=(.7,8.3));ax.set_ylim(bottom=0);ax.grid(axis='y',alpha=.15)
 axs[0].set_ylabel('K5 Service-stage rate (%)');axs[1].set_ylabel('Absolute mean-rate error (pp)');axs[0].legend(frameon=False,fontsize=7.5,loc='upper left')
 save(fig,'figure02_K5_service_calibration')
 fig,axs=plt.subplots(1,2,figsize=(7.1,3.0),layout='constrained')
 for ax,scope,stage in [(axs[0],'K5','Service'),(axs[1],'K6/C1','Queue')]:
  z=key[(key.scope==scope)&(key.stage==stage)];observed=z.iloc[0].observed_rate*100
  ax.axhline(observed,color='black',ls='--',lw=1,label='Observed mean')
  for j,m in enumerate(MODELS):
   row=z[z.model==m].iloc[0];ax.errorbar(j,row.predicted_rate*100,yerr=row.predicted_run_SD*100,fmt=MARK[m],ms=6,color=COL[m],capsize=4)
  ax.set(xticks=range(3),xticklabels=MODELS,xlim=(-.5,2.5),ylabel='Stage rate (%)',title=f'{scope}: {stage}');ax.set_ylim(bottom=0);ax.grid(axis='y',alpha=.15)
 axs[0].legend(frameon=False,fontsize=8,loc='lower right')
 save(fig,'figure03_key_condition_calibration')
 (OUT/'captions.md').write_text('''# Captions

1. **Held-out model error.** Five-fold means with sample SD error bars and individual fold points, on identical ready-on-time frames. Brier sums squared errors across three classes; logloss uses the previous1e-15 scoring clip, not smoothed predictions. Folds share training data; error bars are not confidence intervals or frame-level uncertainty.

2. **K5 Service-stage calibration across C.** Left: observed and predicted fractions, equal-weighted means of five run rates per condition. Right: absolute difference between the two mean rates, in percentage points. All eight C cells retained; these are separate static acquisitions. No error bars are plotted here; run SD and mean run absolute error are retained separately in CSV. Calibration is conditional on ready-on-time, not all-frame DMR.

3. **Prespecified calibration checks.** Predicted run-rate means with sample SD error bars and the observed mean reference. K5 aggregates40 runs across C; K6/C1 contains five runs. The K5 SD includes C-condition variation and must not be read as uncertainty of five repeats at one C. P-joint preserves P-old Queue risk algebraically because transition lookup and the W marginal do not change; overlap in the right panel is expected. The guardrail concerns absolute mean-rate error<=5pp.

한국어: 기존 factorized 분포와 같은 training frame의 joint triplet 분포를 비교한 offline 결과다. 전체 예측 오차, K5 service calibration 및 기존 K6/C1 Queue 성공 보존을 보여준다. GPU 실험, 다른 C의 counterfactual 성능 또는 controller 이득을 의미하지 않는다.
''')
if __name__=='__main__':main()
