"""Three derived figure types, PNG 300dpi and vector PDF; no source edits."""
from pathlib import Path
import os
os.environ.setdefault('MPLCONFIGDIR','/tmp/structural_stage_mpl')
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np,pandas as pd
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'figures'
plt.rcParams.update({'font.size':9,'axes.labelsize':9,'legend.fontsize':8,'xtick.labelsize':8,'ytick.labelsize':8,'pdf.fonttype':42,'font.family':'DejaVu Sans','axes.spines.top':False,'axes.spines.right':False,'lines.linewidth':1.3,'savefig.facecolor':'white'})
COL={'B0':'#777777','B1':'#0072B2','P':'#D55E00'};MARK={'B0':'^','B1':'o','P':'s'}
def save(fig,name):
 for ext in ['png','pdf']:
  p=OUT/f'{name}.{ext}';assert not p.exists();fig.savefig(p,dpi=300,bbox_inches='tight')
 plt.close(fig)
def main():
 cal=pd.read_csv(ROOT/'calibration_curves.csv');kc=pd.read_csv(ROOT/'structural_by_K_C.csv');f=pd.read_csv(ROOT/'structural_fold_metrics.csv')
 fig,axs=plt.subplots(1,3,figsize=(7.1,2.65),layout='constrained')
 for ax,stage in zip(axs,['Queue','Service','On_time']):
  ax.plot([0,1],[0,1],':',color='.55',lw=1)
  for model in ['B0','B1','P']:
   x=cal[(cal.scope=='ALL')&(cal.model==model)&(cal.stage==stage)].groupby('bin')[['predicted','observed']].mean()
   ax.plot(x.predicted,x.observed,color=COL[model],marker=MARK[model],ms=3.5,label=model)
  ax.set(xlim=(0,1),ylim=(0,1),xlabel='Predicted probability',title=stage.replace('_','-'));ax.set_xticks([0,.5,1]);ax.set_yticks([0,.5,1]);ax.grid(alpha=.12)
 axs[0].set_ylabel('Observed proportion');axs[-1].legend(loc='lower right',frameon=False)
 save(fig,'figure01_structural_calibration')
 fig,axs=plt.subplots(3,3,figsize=(7.1,6.1),layout='constrained')
 for row,k in enumerate([5,6,7]):
  for col,stage in enumerate(['Queue','Service','On_time']):
   ax=axs[row,col];x=kc[(kc.K==k)&(kc.model=='B1')].sort_values('C')
   ax.plot(x.C,100*x[stage+'_observed_mean'],color='black',marker='x',ms=4,label='Observed')
   for model in ['B1','P']:
    y=kc[(kc.K==k)&(kc.model==model)].sort_values('C')
    ax.plot(y.C,100*y[stage+'_predicted_mean'],color=COL[model],marker=MARK[model],ms=3,label=model)
   ax.set(xlim=(.7,8.3),ylim=(-2,102),xticks=[1,2,3,4,5,6,7,8],yticks=[0,50,100]);ax.grid(axis='y',alpha=.15)
   if row==0:ax.set_title(stage.replace('_','-'))
   if row==2:ax.set_xlabel('Static cap C')
   if col==0:ax.set_ylabel(f'K={k}\nStage rate (%)')
 axs[0,2].legend(frameon=False,loc='center right',fontsize=7.5)
 save(fig,'figure02_K5_K6_K7_stage_rates')
 fig,axs=plt.subplots(1,2,figsize=(7.1,2.9),layout='constrained')
 for ax,met in zip(axs,['Brier','logloss']):
  for j,m in enumerate(['B0','B1','P']):
   vals=f[f.model==m][met].to_numpy();ax.errorbar(j,vals.mean(),yerr=vals.std(ddof=1),fmt=MARK[m],ms=6,color=COL[m],capsize=4,lw=1.6)
   ax.scatter(j+np.linspace(-.09,.09,5),vals,s=11,color=COL[m],alpha=.55)
  ax.set(xticks=[0,1,2],xticklabels=['B0: coarse','B1: ready state','P: structural'],ylabel='Multiclass '+('Brier score' if met=='Brier' else 'log loss'),xlim=(-.5,2.5));ax.set_ylim(bottom=0);ax.grid(axis='y',alpha=.15)
 save(fig,'figure03_structural_vs_direct_error')
 (OUT/'captions.md').write_text('''# Figure captions

1. **Held-out structural calibration.** Ten fixed equal-width probability bins; each point is the unweighted mean predicted and observed fraction over held-out folds with support in that bin. The diagonal is perfect calibration. B0 is coarse direct, B1 adds ready Q/A, and P is the empirical structural chain. No confidence interval or significance claim is attached; sparse bins remain visible in calibration_curves.csv.

2. **Stage rates by workload and concurrency.** Ready-on-time conditional stage rates, means of five run-level observed/predicted fractions for each K,C. Lines connect measured-grid conditions, not time or dynamic transitions. No error bars are shown here; run-level SD and all observations are in structural_by_K_C.csv and structural_per_run_metrics.csv. These are not all-frame DMR or counterfactual C outcomes.

3. **Structural versus direct probability error.** Points show each held-out fold; larger markers show mean and error bars show sample SD across five held-out folds (not confidence intervals). Folds share training runs and are not independent workloads. Brier is the sum over three classes; logloss clips only scoring probabilities at1e-15 and retains exact-zero counts in CSV. Lower is better.

한국어: 그림1은 stage별 확률 calibration, 그림2는 K5–7/C1–8의 실제 stage 비율과 예측 비율, 그림3은 같은 held-out frame에서 direct/structural 모델의 확률 오차를 비교한다. 이번 결과는 ready 시점의 관측 경로 설명력이며 controller 개선이나 다른 C의 성능을 뜻하지 않는다.
''')
if __name__=='__main__':main()
