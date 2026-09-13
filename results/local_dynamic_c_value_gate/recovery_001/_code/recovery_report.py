"""Frozen post-campaign aggregation and predeclared engineering verdict."""
import os,tempfile,statistics
os.environ.setdefault('MPLCONFIGDIR',tempfile.mkdtemp(prefix='dynamic_value_fig_'))
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from core import *
from recovery_analysis import numbers

def aggregate(output_root=None, artifact_root=None):
 global ROOT
 ROOT=Path(output_root) if output_root else ROOT
 artifact_root=Path(artifact_root) if artifact_root else ROOT
 state=json.loads((ROOT/'continuation_status.json').read_text());passed=[r for r in state['rows'] if r['status']=='PASS' and r['stage']=='primary'];runs=[];windows=[];trans=[];seconds=[]
 for r in passed:
  d=artifact_root/r['acquisition_id'];runs.append(json.loads((d/'summary.json').read_text()));windows+=numbers(d/'window_summary.csv');trans+=numbers(d/'transition_summary.csv');seconds+=numbers(d/'state_seconds.csv')
 csvout(ROOT/'per_run_summary.csv',runs,fields=None if runs else ['acquisition_id','status'])
 csvout(ROOT/'per_window_summary.csv',windows,fields=None if windows else ['acquisition_id','window'])
 csvout(ROOT/'transition_summary.csv',trans,fields=None if trans else ['acquisition_id','phase'])
 complete=len(passed)==30 and state['campaign_status']=='COMPLETED'
 summaries=[];comparisons=[];window_pairs=[]
 for tr in ['A','B']:
  for policy in POLICIES:
   g=[r for r in runs if r['trace']==tr and r['policy']==policy]
   z=dict(trace=tr,policy=policy,n=len(g))
   for metric in ['DMR_percent','local_mean_ms','local_p95_ms','local_p99_ms','queue_mean_ms','queue_p95_ms','service_mean_ms','service_p95_ms','front_end_mean_ms','front_end_p95_ms','start_lag_mean_ms','start_lag_p95_ms','drain_duration','completed_FPS','observed_max_A','peak_generated_backlog','peak_due_not_generated','peak_ready_waiting','time_weighted_mean_A','fraction_A_eq_C','fraction_A_gt_C','fraction_A_ge_C_and_waiting']:
    v=[r[metric] for r in g];z[metric+'_mean']=statistics.mean(v) if v else None;z[metric+'_SD']=statistics.stdev(v) if len(v)>1 else None
   summaries.append(z)
  for fixed in ['FIXED_C2','FIXED_C4']:
   pairs=[]
   for rd in range(1,6):
    f=next((r for r in runs if r['trace']==tr and r['policy']==fixed and r['round']==rd),None);d=next((r for r in runs if r['trace']==tr and r['policy']=='K_LOOKUP_C2_C4' and r['round']==rd),None)
    if f and d:pairs.append(f['DMR_percent']-d['DMR_percent'])
   f=next(r for r in summaries if r['trace']==tr and r['policy']==fixed);d=next(r for r in summaries if r['trace']==tr and r['policy']=='K_LOOKUP_C2_C4')
   mean=statistics.mean(pairs) if pairs else None
   comparisons.append(dict(trace=tr,fixed=fixed,n_pairs=len(pairs),mean_improvement_pp=mean,sample_SD=statistics.stdev(pairs) if len(pairs)>1 else None,improving_rounds=sum(v>0 for v in pairs),mean_at_least_1pp=mean>=1 if mean is not None else None,relative_reduction_percent=100*(f['DMR_percent_mean']-d['DMR_percent_mean'])/f['DMR_percent_mean'] if f['DMR_percent_mean'] else None,paired_values=json.dumps(pairs)))
   for phase in range(4):
    for window in ['startup' if phase==0 else 'transition','phase_remainder']:
     diffs=[]
     for rd in range(1,6):
      find=lambda policy:next((r for r in windows if r['trace']==tr and r['policy']==policy and r['round']==rd and r['phase']==phase and r['window']==window),None)
      f,d=find(fixed),find('K_LOOKUP_C2_C4')
      if f and d:diffs.append(float(f['DMR_percent'])-float(d['DMR_percent']))
     window_pairs.append(dict(trace=tr,fixed=fixed,phase=phase,window=window,n_pairs=len(diffs),mean_improvement_pp=statistics.mean(diffs) if diffs else None,sample_SD=statistics.stdev(diffs) if len(diffs)>1 else None,improving_rounds=sum(v>0 for v in diffs),paired_values=json.dumps(diffs)))
 csvout(ROOT/'policy_summary.csv',summaries);csvout(ROOT/'paired_comparison.csv',comparisons);csvout(ROOT/'window_paired_comparison.csv',window_pairs)
 if not complete:verdict='INCONCLUSIVE_VALIDITY'
 elif all(x['mean_improvement_pp']>=.5 and x['improving_rounds']>=4 for x in comparisons):verdict='PROMISING_FOR_NEXT_STAGE'
 elif any(all(x['mean_improvement_pp']>0 for x in comparisons if x['trace']==tr) for tr in ['A','B']):verdict='SMALL_OR_INCONSISTENT_GAIN'
 else:verdict='NO_OBSERVED_ADVANTAGE_IN_TESTED_TRACES'
 counts={stage:{s:sum(r['stage']==stage and r['status']==s for r in state['rows']) for s in ['PASS','FAIL','ABORTED','UNATTEMPTED']} for stage in ['smoke','primary']}
 save(ROOT/'integrity.json',dict(campaign_status=state['campaign_status'],counts=counts,primary_valid_frames=sum(r['completed_frames'] for r in runs),primary_expected_frames=351000,verdict=verdict,automatic_retries=0,unattempted_preserved=True))
 lines=['# Limited Local Dynamic-C value gate',f'\nVerdict: **{verdict}**. Campaign: {state["campaign_status"]}.',
 '\nThis is a limited pilot in two measured traces, not a final controller or general proof of Dynamic-C superiority. Positive Δ=fixed−lookup means fewer misses under lookup. The engineering gate is predeclared 0.5 pp and ≥4/5 improving rounds for both contrasts in both traces; 1 pp and relative reduction are secondary only.',
 '\n| Trace | Policy | n | DMR mean ± sample SD (%) | Local run-P95 mean ± sample SD (ms) | Drain mean (s) | Integrity |','|---|---|---:|---:|---:|---:|---|']
 def fmt(v):return 'N/A' if v is None else f'{v:.4f}'
 for r in summaries:lines.append(f"| {r['trace']} | {r['policy']} | {r['n']} | {fmt(r['DMR_percent_mean'])} ± {fmt(r['DMR_percent_SD'])} | {fmt(r['local_p95_ms_mean'])} ± {fmt(r['local_p95_ms_SD'])} | {fmt(r['drain_duration_mean'])} | {'PASS' if r['n']==5 else 'INCOMPLETE'} |")
 lines+=['\n| Trace | Fixed comparator | Δ mean ± SD (pp) | Improving rounds | Relative reduction (%) | Mean ≥1 pp |','|---|---|---:|---:|---:|---|']
 for r in comparisons:lines.append(f"| {r['trace']} | {r['fixed']} | {fmt(r['mean_improvement_pp'])} ± {fmt(r['sample_SD'])} | {r['improving_rounds']}/{r['n_pairs']} | {fmt(r['relative_reduction_percent'])} | {r['mean_at_least_1pp']} |")
 lines+=['\n## Transition windows', '1 s is a predeclared reporting window, not measured settling time. Negative fixed−lookup differences below mean additional lookup misses in that arrival window; they are not isolated causal switching costs. Workload changes, carried backlog, service and front-end/start-lag response can coexist. Cohorts retain their logical arrival phase/deadline. Original static metrics are not substituted as dynamic comparators.']
 for r in window_pairs:
  if r['window']=='transition':lines.append(f"- {r['trace']} phase {r['phase']} vs {r['fixed']}: Δ={fmt(r['mean_improvement_pp'])} pp, positive {r['improving_rounds']}/{r['n_pairs']}.")
 lines+=['\n## Measurement and limitations',
 'All policies use one shared engine, P=4 independent execution contexts/streams/buffers and four owning workers; Formal used a context/worker count equal to C. Frozen TensorRT infer, preprocessing and input pipeline code are reused unchanged. New cap admission and event logging are identical across all three policies. Warm-up=0 and deliberate cooldown=0 inherit Formal; startup frames are retained. Internal watchdog=300 s from trace setup; parent timeout=420 s from process start. All scheduled samples must complete; actual natural EOS is recorded separately from trace-budget termination.',
 'A_service is reconstructed from [s,c), online active counter decrements at completion publication. Actual c is never available to the controller before that notification. Dynamic non-preemptive cap decreases can produce A>C; no new admission occurs while the counter is ≥C. Cap equality alone is not waiting or GPU utilization. Occupancy denominators are the offered [t0,t0+60s) window. Backlog includes every generated but uncompleted request; due-but-not-generated is separate. Transition CSV retains active/request cohort distinctions and separate times for A≤C, A<C and first new admission; it also retains counter-based versions.',
 'Run is the repeated unit; same video content is reused. Mean run-P95s are not pooled P95s; component P95s are not additive. Same-round pairing matches execution blocks, not identical process state. Equal-time K6/K7 windows have 6:7 frame weighting. Static S(C) is a descriptive baseline-selection score, not a forecast or performance bound. Only tested fixed baselines {C2,C4} are compared. High absolute DMR is reported even if improvement exists; neither stream capacity nor long-term queue stability is established.',
 'Environment snapshots before/after each acquisition preserve temperatures, clock ranges/current frequencies and host process lists. These between-run readings do not identify causal thermal/clock effects inside a phase; no new hot-path profiler was used. No future trace information enters Controller.notify(current_K).',
 '\n## Next-stage interpretation',
 'If PROMISING, retain current-K lookup as a baseline and consider a simple queue/deadline-slack controller next. Otherwise defer assuming Dynamic-C is the core contribution; limited weak results do not refute every Dynamic-C policy. Local/Edge placement, joint C_L/C_E and complex methods are outside this experiment. No follow-up experiment is launched.',
 '\n## Acquisition accounting',json.dumps(counts),f'Primary valid frames: {sum(r["completed_frames"] for r in runs)} / 351000. Smoke is never included in primary.',
 '\n## Preservation', 'Figure relocation manifest/reference audit are in this root. The 28 static figure/caption files moved to analysis_valid5/figures/supporting_static with unchanged SHA256. Representative figures retain revision_002 main and revision_001 heatmap. Frozen Formal/raw/campaign and unrelated scripts are untouched. No automatic commit/push.']
 if state.get('halt_reason'):lines+=['\n## HALT',state['halt_reason']]
 if complete:
  plt.rcParams.update({'font.size':9,'pdf.fonttype':42});dest=ROOT/'figures';dest.mkdir()
  colors=['#0072B2','#D55E00','#009E73'];fig,axs=plt.subplots(1,2,figsize=(7.1,3.1),layout='constrained')
  for ax,tr in zip(axs,['A','B']):
   g=[r for r in summaries if r['trace']==tr];ax.bar(range(3),[r['DMR_percent_mean'] for r in g],yerr=[r['DMR_percent_SD'] for r in g],color=colors,capsize=3)
   ax.set(xticks=range(3),xticklabels=['C2','C4','K lookup'],ylabel='Deadline miss rate (%)',title=f'Trace {tr}',ylim=(0,100))
  for ext in ['png','pdf']:fig.savefig(dest/f'figure01_policy_DMR.{ext}',dpi=300)
  plt.close(fig)
  fig,axs=plt.subplots(3,2,figsize=(7.1,7),layout='constrained')
  for col,tr in enumerate(['A','B']):
   for policy,color,style in zip(POLICIES,colors,['-','--','-.']):
    x=list(range(61));sel=[r for r in seconds if r['trace']==tr and r['policy']==policy]
    for i,metric in enumerate(['A_service','generated_backlog','DMR_percent']):
     xs=x if i<2 else x[:-1];means=[statistics.mean(float(r[metric]) for r in sel if r['second']==s and r[metric]!='') for s in xs]
     axs[i,col].plot(xs,means,label=policy,color=color,ls=style,lw=1)
    if policy=='K_LOOKUP_C2_C4':axs[0,col].step(x,[int(next(r['C'] for r in sel if r['second']==s)) for s in x],where='post',color='black',lw=.8,label='lookup cap')
   for i in range(3):
    ax=axs[i,col];ax.set(xlabel='Time / arrival window start (s)',ylabel=['In-flight requests','Generated backlog','Arrival-bin DMR (%)'][i],title=f'Trace {tr}' if i==0 else '')
    for b in [15,30,45]:ax.axvline(b,color='.8',lw=.7)
   axs[2,col].set_ylim(0,100)
  axs[0,0].legend(fontsize=6)
  for ext in ['png','pdf']:fig.savefig(dest/f'figure02_state_deadlines.{ext}',dpi=300)
  plt.close(fig)
  lines+=['\n## Figures','Figure 1: DMR means and run-level sample SD (n=5). Figure 2: same-time state samples and 1-second arrival-bin DMR, means over five runs; boundaries are at 15/30/45 s. Backlog is generated requests minus actual completions. A and cap are application states, not GPU utilization.']
 (ROOT/'analysis_report.md').write_text('\n'.join(lines)+'\n')
 print(verdict,flush=True)
if __name__=='__main__':aggregate()
