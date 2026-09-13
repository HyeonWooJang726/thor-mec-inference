"""Secondary descriptive aggregates and three fixed-layout figures. No policy fitting."""
from pathlib import Path
import os,tempfile,json,sys
RERENDER_ONLY="--rerender-only" in sys.argv
os.environ.setdefault('MPLCONFIGDIR',tempfile.mkdtemp(prefix='state_history_mpl_'))
import pandas as pd,numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
R=Path(__file__).resolve().parents[1]
def output(name,d):
 p=R/name
 if p.exists():
  if RERENDER_ONLY:return
  raise RuntimeError('refuse overwrite '+str(p))
 d.to_csv(p,index=False,float_format='%.15g')
p=pd.read_csv(R/'phase_level_metrics.csv');w=pd.read_csv(R/'secondary_window_metrics.csv');b=pd.read_csv(R/'boundary_state.csv');e=pd.read_csv(R/'boundary_state_evolution.csv');pairs=pd.read_csv(R/'round_paired_phase_deltas.csv')
# K-cohort means are arrival weighted within each acquisition, then run-level paired.
coh=[]
for keys,g in p.groupby(['acquisition_id','trace','policy','round','K'],sort=False):
 z=dict(zip(['acquisition_id','trace','policy','round','K'],keys));z['arrival_count']=g.arrival_count.sum();z['miss_count']=g.miss_count.sum();z['DMR_percent']=100*z['miss_count']/z['arrival_count']
 for col in ['queue_mean_ms','service_mean_ms','start_lag_mean_ms','front_end_mean_ms','local_mean_ms']:z[col]=np.average(g[col],weights=g.arrival_count)
 coh.append(z)
c=pd.DataFrame(coh);output('K_arrival_cohort_metrics.csv',c)
cp=[]
for keys,g in c.groupby(['trace','K','round']):
 for fix in ['FIXED_C2','FIXED_C4']:
  a=g[g.policy=='K_LOOKUP_C2_C4'].iloc[0];f=g[g.policy==fix].iloc[0];z=dict(trace=keys[0],K=keys[1],round=keys[2],fixed=fix)
  for m in ['DMR_percent','queue_mean_ms','service_mean_ms','local_mean_ms']:z['delta_'+m]=a[m]-f[m]
  cp.append(z)
output('K_cohort_paired_deltas.csv',pd.DataFrame(cp))
# Exact whole-run DMR gap attribution by arrival phase; this is arithmetic, not causation.
g=pairs[pairs.window=='whole_phase'].copy();g['contribution_to_whole_run_DMR_pp']=g['delta_miss_count']*100/11700
output('phase_contribution_to_DMR_gap.csv',g[['trace','round','phase','K','fixed','delta_DMR_percent','delta_miss_count','contribution_to_whole_run_DMR_pp']])
bs=[]
for data,kind in [(b,'boundary_left'),(e,'evolution')]:
 for _,u in data[data.policy=='K_LOOKUP_C2_C4'].iterrows():
  for fix in ['FIXED_C2','FIXED_C4']:
   match=(data.trace==u.trace)&(data['round']==u['round'])&(data.phase==u.phase)&(data.policy==fix)
   if kind=='evolution':match&=data.offset_ms==u.offset_ms
   f=data[match].iloc[0];z=dict(trace=u.trace,round=u['round'],phase=u.phase,K_before=u.K_before,K_after=u.K_after,fixed=fix,sample=kind,offset_ms=u.get('offset_ms',0))
   for m in ['A','ready_queue','unfinished_backlog','generated_unfinished','due_not_generated','unfinished_late_count','unfinished_late_fraction','unfinished_slack_p10_ms','unfinished_slack_median_ms']:
    z[m+'_lookup']=u[m];z[m+'_fixed']=f[m];z['delta_'+m]=u[m]-f[m]
   bs.append(z)
output('boundary_state_paired_deltas.csv',pd.DataFrame(bs))
# Paired same-K initial vs later phase for each policy; no threshold-based selection.
h=[]
for keys,g in p.groupby(['trace','policy','round']):
 for a,z in [(0,2),(1,3)]:
  x=g[g.phase==a].iloc[0];y=g[g.phase==z].iloc[0];row=dict(trace=keys[0],policy=keys[1],round=keys[2],K=x.K,earlier_phase=a,later_phase=z)
  for m in ['DMR_percent','queue_mean_ms','local_p95_ms','time_mean_unfinished_backlog']:
   row[m+'_earlier']=x[m];row[m+'_later']=y[m];row['delta_'+m]=y[m]-x[m]
  h.append(row)
output('trace_order_phase_comparison.csv',pd.DataFrame(h))
# Figures: one example fixed by trace/round/phase, descriptive event states, no smoothing.
D=R/'figures';D.mkdir(exist_ok=True)
plt.rcParams.update({'font.size':9,'axes.labelsize':9,'xtick.labelsize':8,'ytick.labelsize':8,'legend.fontsize':8,'pdf.fonttype':42,'savefig.facecolor':'white'})
colors={'FIXED_C2':'#0072B2','FIXED_C4':'#D55E00','K_LOOKUP_C2_C4':'#009E73'};labels={'FIXED_C2':'Fixed C2','FIXED_C4':'Fixed C4','K_LOOKUP_C2_C4':'K lookup'};styles={'FIXED_C2':('-','o'),'FIXED_C4':('--','s'),'K_LOOKUP_C2_C4':('-.','^')}
def export(fig,name):
 for ext in ['png','pdf']:
  path=D/f'{name}.{ext}';assert RERENDER_ONLY or not path.exists();fig.savefig(path,dpi=300)
 plt.close(fig)
f=pd.read_csv(R/'figure01_source_timeline.csv');fig,axs=plt.subplots(4,1,figsize=(7.1,6.0),sharex=True,layout='constrained')
for ax,metric,label in zip(axs,['C','A','ready_queue','unfinished_backlog'],['Applied cap C','In-flight A','Ready queue','Logical unfinished']):
 for pol in ['FIXED_C4','K_LOOKUP_C2_C4']:
  g=f[f.policy==pol];ax.step(g.relative_ms,g[metric],where='post',color=colors[pol],ls=styles[pol][0],label=labels[pol],lw=1.1)
 ax.axvline(0,color='.5',lw=.7);ax.set_ylabel(label);ax.set_ylim(bottom=0);ax.spines[['top','right']].set_visible(False)
axs[0].legend(ncol=2);axs[-1].set_xlabel('Time relative to logical K7-to-K6 boundary (ms)');axs[-1].set_xlim(-50,100);export(fig,'figure01_decrease_timeline')
# Within each acquisition, average its boundaries in each direction first. Then mean/SD across 10 runs.
b['direction']=np.where(b.K_before==7,'K7 to K6','K6 to K7');cols=['unfinished_backlog','unfinished_late_fraction','unfinished_slack_p10_ms','unfinished_slack_median_ms'];unit=b.groupby(['acquisition_id','trace','policy','round','direction'])[cols].mean().reset_index();output('figure02_run_level_boundary_data.csv',unit)
fig,axs=plt.subplots(4,2,figsize=(7.1,7.0),layout='constrained')
for j,direction in enumerate(['K7 to K6','K6 to K7']):
 for i,(metric,label) in enumerate(zip(cols,['Logical unfinished','Late unfinished (%)','Slack P10 (ms)','Slack median (ms)'])):
  ax=axs[i,j]
  for x,pol in enumerate(colors):
   vals=unit[(unit.direction==direction)&(unit.policy==pol)][metric].dropna()*(100 if i==1 else 1)
   ax.errorbar(x,vals.mean(),yerr=vals.std(ddof=1),fmt=styles[pol][1],color=colors[pol],capsize=3,ms=5)
  ax.set_xticks(range(3),['C2','C4','Lookup']);ax.set_ylabel(label);ax.spines[['top','right']].set_visible(False)
  if i==0:ax.set_title(direction);ax.set_ylim(bottom=0)
  if i==1:ax.set_ylim(0,105)
  if i>=2:ax.axhline(0,color='.8',lw=.7)
# Shared row scales avoid magnifying sub-nanosecond rounding into visual pressure.
for i in [0,2,3]:
 limits=[ax.get_ylim() for ax in axs[i]];lo=min(x[0] for x in limits);hi=max(x[1] for x in limits)
 for ax in axs[i]:ax.set_ylim(lo,hi)
export(fig,'figure02_boundary_pressure')
fig,axs=plt.subplots(1,2,figsize=(7.1,3.3),layout='constrained')
for ax,tr in zip(axs,['A','B']):
 for pol in colors:
  g=p[(p.trace==tr)&(p.policy==pol)].groupby('phase').DMR_percent.agg(['mean','std'])
  ls,m=styles[pol];ax.errorbar(range(4),g['mean'],yerr=g['std'],color=colors[pol],marker=m,ls=ls,capsize=3,label=labels[pol],lw=1.2,ms=4)
 ks=[6,7,6,7] if tr=='A' else [7,6,7,6];ax.set_xticks(range(4),[f'{15*i}–{15*(i+1)}\nK{k}' for i,k in enumerate(ks)]);ax.set(xlabel='Arrival phase (s)',ylabel='Deadline miss rate (%)',ylim=(0,105),title=f'Trace {tr}');ax.spines[['top','right']].set_visible(False)
axs[0].legend(loc='upper right');export(fig,'figure03_phase_DMR')
(D/'captions.md').write_text('''# Secondary descriptive figures

All inputs are the 30 measured primary acquisitions; no smoke or synthetic fixture enters these figures. No new GPU work or policy fitting. C/A are application request states, not GPU utilization.

1. **K7-to-K6 timeline:** Trace B, round 1, boundary 15 s was selected by identifier, not outcome. Exact right-continuous states at raw timestamp change points are plotted for lookup and fixed C4. Vertical line is the logical boundary; cap changes use actual apply timestamps. Logical unfinished includes due-but-not-generated requests. This is a comparison between separate processes, not a frame-level causal counterfactual.
2. **Boundary pressure:** Left-limit states at 15/30/45 s. Within-acquisition boundaries of the same direction are averaged first; error bars show sample SD across 10 acquisitions per policy/direction (five repetitions for each trace), not independent transition/frame errors. Phase-specific results remain in CSVs. Late fraction alone is degenerate at these tick-aligned boundaries: unfinished requests commonly have slack −2/3 ns from integer arrival rounding. Interpret slack magnitude and queue/count jointly; −2/3 ns is not a large accumulated deadline debt.
3. **Phase DMR:** Arrival-cohort DMR for the four 15-s phases, mean ± sample SD of five runs. Completion in a later phase retains the original arrival cohort. Startup is included. Connections join measured phase summaries, not a causal transition effect. Phase source samples and initialization/history differ; no independent workload sampling or significance is claimed.
''')
print('Three figures and secondary descriptive aggregates written.')
