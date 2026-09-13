"""CPU-only publication figures and evidence-linked descriptive report."""
import csv,json,math,os,statistics as st,subprocess
from collections import defaultdict
from pathlib import Path
from analyze import D,ROOT,REPO,sha

def read(name):return list(csv.DictReader((D/name).open()))
def write(name,text):(D/name).write_text(text+'\n')
def csvout(name,rows):
 with (D/name).open('w',newline='') as f:
  w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
S={(int(r['K']),int(r['C']),r['metric']):r for r in read('kc_full_summary.csv')}
R=read('analysis_per_run.csv');AD=read('adjacent_c_deltas.csv');B=read('static_best_observed_c_by_k.csv')
def v(k,c,m):return float(S[k,c,m]['mean'])
def sd(k,c,m):return float(S[k,c,m]['sample_SD'])
def pm(k,c,m,scale=1):return f'{v(k,c,m)*scale:.3f} ± {sd(k,c,m)*scale:.3f}'
def delta(k,c,m):return next(r for r in AD if (int(r['K']),int(r['C_low']),r['metric'])==(k,c,m))
def effect(k,c,m):
 r=delta(k,c,m)
 return f"{float(r['delta_primary_mean']):+.4f} ({r['decreased']}/{r['paired_n']} down, {r['increased']}/{r['paired_n']} up)"
def mdtable(headers,rows):return '\n'.join(['| '+' | '.join(headers)+' |','|'+'|'.join('---' for _ in headers)+'|']+['| '+' | '.join(map(str,r))+' |' for r in rows])
def figsave(fig,name):
 for ext in ['png','pdf','svg']:fig.savefig(D/'figures'/f'{name}.{ext}',dpi=180,bbox_inches='tight')

def figures():
 os.environ['MPLCONFIGDIR']=str(D/'_scripts/matplotlib_cache')
 import matplotlib
 matplotlib.use('Agg')
 import matplotlib.pyplot as plt
 import numpy as np
 plt.rcParams.update({'font.size':10,'axes.titlesize':11,'svg.fonttype':'none','pdf.fonttype':42})
 (D/'figures').mkdir(exist_ok=True)
 cs=list(range(1,9));colors=plt.get_cmap('tab10').colors
 captions=[]
 def curves(ax,metric,ks=range(1,8),scale=1,symlog=False):
  for k in ks:ax.errorbar(cs,[scale*v(k,c,metric) for c in cs],yerr=[scale*sd(k,c,metric) for c in cs],marker='o',ms=4,capsize=3,color=colors[k-1],label=f'K={k}')
  ax.set_xticks(cs);ax.set_xlabel('Application in-flight cap C');ax.grid(alpha=.2)
  if symlog:
   ax.set_yscale('symlog',linthresh=0.1 if scale==100 else 1)
   ax.set_ylim(bottom=0)
  ax.legend(fontsize=8,ncol=2)
 def finish(fig,name,caption):
  figsave(fig,name);plt.close(fig);captions.append((name,caption))
 fig,axs=plt.subplots(1,2,figsize=(12,4.5),layout='constrained')
 curves(axs[0],'deadline_miss_percent');curves(axs[1],'deadline_miss_percent',range(1,5))
 for ax in axs:ax.set_ylabel('Deadline miss ratio (%)')
 axs[0].set_title('All K');axs[1].set_title('Low/moderate K detail — all frames retained')
 finish(fig,'figure01_dmr','DMR vs C; all frames including startup and drain. Points: means of five run DMRs; error bars: run-level sample SD. K2/C1 includes the post-campaign replacement. Low-K panel is an axis/detail view, not data exclusion.')
 for number,name,metrics,labels in [(2,'queue',['queue_mean_ms','queue_p95_ms'],['Queue mean (ms)','Mean of run-level queue P95s (ms)']),
                                    (3,'service',['service_mean_ms','service_p95_ms'],['Service mean (ms)','Mean of run-level service P95s (ms)']),
                                    (9,'local_tails',['local_p95_ms','local_p99_ms'],['Mean of run-level local P95s (ms)','Mean of run-level local P99s (ms)'])]:
  fig,axs=plt.subplots(1,2,figsize=(12,4.5),layout='constrained')
  for ax,metric,label in zip(axs,metrics,labels):curves(ax,metric,symlog=name!='service');ax.set_ylabel(label)
  finish(fig,f'figure{number:02d}_{name}',f'{name.title()} vs C. Points are five-run means; error bars are run-level sample SD. Percentile panels show mean of run-level P95 values (or P99), not pooled percentiles. '+('Queue/local axes use symlog with 1 ms linear threshold for display only.' if name!='service' else 'Service is host-observed request service, not isolated kernels.'))
 fig,ax=plt.subplots(figsize=(7,4.7),layout='constrained');curves(ax,'time_weighted_mean_A');ax.set_ylabel('Time-weighted mean in-flight A(t)')
 finish(fig,'figure04_mean_A','Five-run mean A with run-level sample SD, window [t0,t0+60s). A counts host-observed in-flight requests; not GPU utilization or kernel parallelism. Mean A shares an interval-area accounting identity with service duration.')
 fig,axs=plt.subplots(1,2,figsize=(12,4.5),layout='constrained')
 curves(axs[0],'fraction_time_A_equals_C',scale=100);curves(axs[1],'fraction_time_cap_saturated_with_waiting',scale=100,symlog=True)
 axs[0].set_ylabel('Time at A=C (%)');axs[1].set_ylabel('Time at A=C and Q>0 (%) — symlog')
 axs[0].set_title('Cap-saturated state');axs[1].set_title('Saturation coincident with waiting')
 finish(fig,'figure05_cap_and_waiting','Cap saturation and exact cap-saturated-with-waiting state fractions over [t0,t0+60s). Means ± run-level sample SD. The right axis uses a 0.1 percentage-point symlog display threshold. A=C with Q=0 is not queued admission blocking. Neither metric is device utilization.')
 fig,axs=plt.subplots(2,4,figsize=(16,8),layout='constrained');components=['start_lag','front_end','queue','service']
 for k,ax in zip(range(1,8),axs.flat):
  bottom=np.zeros(8)
  for i,m in enumerate(components):
   y=np.array([v(k,c,m+'_mean_ms') for c in cs]);ax.bar(cs,y,bottom=bottom,label=m,color=colors[i]);bottom+=y
  # Total uncertainty is SD of actual run local means, never sum of component SDs.
  ax.errorbar(cs,bottom,yerr=[sd(k,c,'local_mean_ms') for c in cs],fmt='none',ecolor='black',capsize=2)
  ax.axhline(1000/30,color='black',ls=':',lw=1);ax.set(title=f'K={k}',xlabel='C',ylabel='Mean local components (ms)',xticks=cs)
  if k==7:ax.set_yscale('symlog',linthresh=30);ax.set_title('K=7 (symlog; non-proportional heights)')
  ax.set_ylim(bottom=0)
 axs.flat[-1].axis('off');handles,labels=axs.flat[0].get_legend_handles_labels();axs.flat[-1].legend(handles,labels,loc='center')
 finish(fig,'figure06_mean_decomposition','Stacked equal-run mean components; total error bars are sample SD of actual run local means. Dotted line: nominal 33.333… ms deadline. Component P95s are not added. K7 uses symlog to retain C1 and all other cells; nonlinear bar heights are not proportional shares.')
 fig,ax=plt.subplots(figsize=(8,5),layout='constrained');curves(ax,'completed_FPS')
 for k in range(1,8):ax.axhline(30*k,color=colors[k-1],ls='--',lw=.8,alpha=.6)
 ax.set_ylabel('Completed FPS (completion elapsed denominator)')
 finish(fig,'figure07_completed_vs_offered','Completed FPS means ± run-level sample SD. Matching dashed lines are offered 30K FPS. Slight excess over offered rate follows the denominator definition, not throughput beyond source pacing. Near-offered FPS can coexist with high DMR.')
 regret=read('static_c_regret.csv');lookup={(int(r['K']),int(r['C'])):float(r['descriptive_gap_pp']) for r in regret}
 fig,ax=plt.subplots(figsize=(10,5),layout='constrained');matrix=np.array([[lookup[k,c] for c in cs] for k in range(1,8)])
 im=ax.imshow(matrix,aspect='auto',cmap='magma_r')
 for i in range(7):
  for j in range(8):ax.text(j,i,f'{matrix[i,j]:.2f}',ha='center',va='center',fontsize=8,color='white' if matrix[i,j]>40 else 'black')
 ax.set(xticks=range(8),xticklabels=cs,yticks=range(7),yticklabels=[f'K={k}' for k in range(1,8)],xlabel='Static C',title='Post-hoc gap to each K’s best-observed mean DMR')
 fig.colorbar(im,ax=ax,label='Descriptive DMR gap (percentage points)')
 finish(fig,'figure08_static_regret','Post-hoc gaps between five-run mean DMR and the minimum selected from the same C grid. This descriptive heatmap has no uncertainty interval for the selected minimum. It is not an online-policy evaluation or achievable Dynamic-C gain.')
 write('figures/captions.md','Nonnegative symlog axes start at zero; any below-zero portion of mean ± SD is outside the display. SD bars describe variation, not feasible-value or confidence bounds.\n\n'+'\n\n'.join(f'## {n}\n\n{c}' for n,c in captions))

def render():
 shapes={1:('irregular','Very low absolute DMR; minimum C4 not separated from C3; selected C4/C8 misses entirely in first second. Not a sustained U-shaped service regime.'),
  2:('irregular','C2/C3/C4 mean tie; C1-to-C2 DMR direction splits 2/4 each way, followed by repeat-consistent high-C tail increase. Low-C minimum is unresolved.'),
  3:('interior minimum / U-shaped','Broad interior low-C basin at C2 with local reversals; C1→2 DMR falls 5/5 and C2→8 rises in all original pairs. C2 versus C4 not a clear winner.'),
  4:('interior minimum / U-shaped','Shallow interior mean minimum C4, then a high-C tail step; C4→5 DMR rises 5/5 although mean service falls. Not a strictly monotone arm.'),
  5:('interior minimum / U-shaped','C1→2 DMR falls 5/5, C2→3 rises 5/5; later small reversals and large run variability. C2’s gap to C3 is smaller than C3 run SD.'),
  6:('irregular','Two low-C troughs: C2→3 rises 5/5, C3→4 falls 5/5, then large high-C penalty. Interior global mean minimum C2; not a simple U.'),
  7:('interior minimum / U-shaped','DMR falls through C4 and rises strongly C4→7; C7→8 falls modestly in 5/5. Interior minimum is robust in these repeats, arms are not strictly monotone.')}
 csvout('dmr_shape_by_k.csv',[dict(K=k,shape=x[0],qualification=x[1],mean_DMR_C1_to_C8=json.dumps([v(k,c,'deadline_miss_percent') for c in range(1,9)]),
   classification_method='descriptive exact mean curve plus original-round directions; no numerical plateau/equivalence threshold') for k,x in shapes.items()])
 regions={1:'low load; occupancy/throughput plateau across the tested grid; selected-condition misses are startup-localized',
  2:'low/moderate load; C1→2 changes ready waiting/service, then mean A plateaus; selected-condition misses are startup-localized',
  3:'moderate load; queue response through C3; low DMR with high-C tail changes, no sustained ready backlog during this window',
  4:'moderate load with tail-sensitive boundary; C>=5 affects rare long tails, most sampled-condition misses occur in first second',
  5:'deadline-sensitive boundary; C choices span ~2–20% DMR despite near-offered completion rate',
  6:'deadline overload; C1 has persistent ready backlog and large run variability; higher C restores near-offered rate but does not ensure deadlines',
  7:'severe deadline overload; C1 also exhibits throughput/backlog overload; C>=2 nearly tracks offered rate yet DMR remains high'}
 bands={1:(1,8),2:(2,8),3:(3,8),4:(4,8),5:(5,8),6:(6,8),7:(7,8)}
 workload=[]
 for k,(lo,hi) in bands.items():
  workload.append(dict(K=k,region=regions[k],descriptive_mean_A_band_C=f'{lo}..{hi}',
     band_mean_A_min=min(v(k,c,'time_weighted_mean_A') for c in range(lo,hi+1)),band_mean_A_max=max(v(k,c,'time_weighted_mean_A') for c in range(lo,hi+1)),
     plateau_interpretation='descriptive diminishing-response band, not threshold-tested equivalence or all-metric plateau',
     mean_DMR_min=min(v(k,c,'deadline_miss_percent') for c in range(1,9)),mean_DMR_max=max(v(k,c,'deadline_miss_percent') for c in range(1,9))))
 csvout('workload_regions.csv',workload)
 # Explicit early/late evidence distinguishes sustained service growth from local exceptions.
 qsh=[]
 for k in range(1,8):
  early=2 if k==1 else (1 if k in (2,3,5,6,7) else 3)
  late={1:7,2:2,3:3,4:4,5:5,6:6,7:7}[k]
  qsh.append(dict(K=k,H1_queue_reduction='CONFIRMED',H2_concurrent_service_increase='NOT_CONFIRMED' if k==1 else 'CONFIRMED',
      H3_service_after_diminishing_queue_relief={1:'NOT_CONFIRMED',4:'NOT_CONFIRMED',7:'PARTIALLY_CONFIRMED'}.get(k,'CONFIRMED'),
      early_C_pair=f'{early}->{early+1}',early_delta_queue=effect(k,early,'queue_mean_ms'),early_delta_service=effect(k,early,'service_mean_ms'),
      late_C_pair=f'{late}->{late+1}',late_delta_queue=effect(k,late,'queue_mean_ms'),late_delta_service=effect(k,late,'service_mean_ms'),
      qualification='K1 queue difference is only 0.068 ms; no sustained service response' if k==1 else 'Late service response is local, not a claim that service increases at every higher C'))
 csvout('queue_service_hypotheses_by_k.csv',qsh)
 candidates=[]
 for k,cl,ch,kind in [(2,1,2,'low/moderate'),(5,2,5,'deadline boundary'),(6,2,6,'deadline overload bridge'),(7,4,7,'high/severe deadline overload')]:
  support='; '.join(f'{m}: {v(k,cl,m):.4f}->{v(k,ch,m):.4f}' for m in ['queue_mean_ms','service_mean_ms','time_weighted_mean_A','deadline_miss_percent','fraction_time_cap_saturated_with_waiting'])
  for direction in ['increase','decrease']:
   candidates.append(dict(K=k,C_low=cl,C_high=ch,transition_direction=f'{cl}->{ch}' if direction=='increase' else f'{ch}->{cl}',
       workload_type=kind,supporting_metrics=support,rationale='Measure already-running service response and queue/latency transient across observed static regimes; '+('test non-preemptive decrease with possible transient A>C_new' if direction=='decrease' else 'test extra admission and its service/transient cost')))
 csvout('dynamic_transition_candidates.csv',candidates)
 # Secondary historical comparison is never merged into primary samples.
 hp=REPO/'results/local_concurrency_low_mid_range_discovery/combined_k1_k7_c1_c8_summary.csv'
 hist=[]
 for r in csv.DictReader(hp.open()):
  assert r['status']=='PASS';k,c=int(r['K']),int(r['C'])
  for m in ['deadline_miss_percent','queue_mean_ms','service_mean_ms','time_weighted_mean_A']:
   hist.append(dict(K=k,C=c,metric=m,historical_campaign=r['source_campaign'],historical_single_value=float(r[m]),
       formal_valid5_mean=v(k,c,m),formal_valid5_SD=sd(k,c,m),difference_formal_minus_historical=v(k,c,m)-float(r[m]),pooled=False))
 csvout('historical_secondary_comparison.csv',hist)
 write('historical_secondary_comparison.md',f'''# Secondary historical check (never pooled)

The historical 56-point CSV combines distinct one-run discovery campaigns. Formal valid5 is the sole primary evidence.

K5/C8 historical DMR was 56.333%; Formal is {pm(5,8,'deadline_miss_percent')}%. That large historical penalty is **not reproduced in magnitude**. Same-campaign K5 C7→8 has a +2.493 pp mean difference but increases in only 3/5 pairs.

Historical K6 C7→8 DMR rose 88.537→93.157%; Formal instead falls {v(6,7,'deadline_miss_percent'):.3f}→{v(6,8,'deadline_miss_percent'):.3f}% in 5/5 original pairs. K7 C7→8 also falls modestly in all five Formal pairs. Neither endpoint implies a new higher-occupancy regime or a hardware maximum.

Broad queue reduction/service inflation and the K5 low-C versus K7 C4 basin are reproduced; historical magnitudes and every adjacent direction are not. Source SHA256: {sha(hp)}.
''')
 drift=read('round_drift_analysis.csv');temp=read('temporal_order_descriptive.csv')
 dt=mdtable(['Round','Service cell-centered ms','DMR cell-centered pp'],[[r, next(f"{float(x['cell_centered_mean']):+.5f}" for x in drift if x['original_round']==str(r) and x['metric']=='service_mean_ms'),next(f"{float(x['cell_centered_mean']):+.5f}" for x in drift if x['original_round']==str(r) and x['metric']=='deadline_miss_percent')] for r in range(1,6)])
 drift_text=f'''# Original-only temporal / round analysis

Original `campaign_drift_summary.csv` remains the initial 279-valid-row reference (56 cells in R1/2/3/5, 55 in R4). Replacement is never inserted. `round_drift_analysis.csv` additionally uses the **same 55 complete cells** in all five rounds, excluding K2/C1 across all rounds only in this clearly labeled secondary panel. Center each cell on its original five-round mean, then average its round deviation.

{dt}

Service shows no sustained monotone drift: centered round means span -0.06348 to +0.02370 ms. The original-row cell-centered service slope is {float(temp[0]['slope_per_100_indices']):+.5f} ms per 100 global indices (correlation {float(temp[0]['correlation']):.4f}). These are descriptive, not independent-sample trend tests.

DMR has visible round bias: common-panel R5−R1 = -1.77709 pp. However the median within-cell R5−R1 is only -0.02778 pp. K7/C2 contributes -40.746 pp and K6/C1 -26.028 pp to the unaveraged sum (-97.740 pp): together about 68.3% of the panel change. Thus a few sensitive conditions strongly affect the global average; this is not uniform system-wide improvement. The DMR order slope is {float(temp[1]['slope_per_100_indices']):+.4f} pp per 100 indices, correlation {float(temp[1]['correlation']):.4f}.

K6/C1 original-round DMR values are 63.954, 100.000, 77.991, 36.139, 37.926%; K7/C2 values are 100.000, 79.460, 84.016, 91.167, 59.254%. All remain included. No outlier deletion or drift correction is applied.

Balanced rounds avoid placing each C in its own campaign epoch and permit same-round contrasts. They reduce one source of temporal confounding, but five rounds cannot establish that all temporal confounding is absent. Temperature/resource causes were not identified here. Verdict on a meaningful **system-wide temporal drift mechanism: UNCLEAR**; observed DMR round variability/bias: YES; sustained service drift: not observed. The opposite K6/K7 C2-versus-C4 DMR directions survive all five within-round comparisons.
'''
 write('round_drift_analysis.md',drift_text)
 sens=read('replacement_sensitivity.csv')
 sensitivity=mdtable(['Metric','Primary valid5 mean','Original valid4 mean','Original4 + invalid-exit run04 mean'],[[m,*[f"{float(next(x['mean'] for x in sens if x['metric']==m and x['dataset']==label)):.6f}" for label in ['PRIMARY_VALID5','ORIGINAL_VALID4','SECONDARY_ORIGINAL4_PLUS_FAILED_RUN04']]] for m in ['queue_mean_ms','service_mean_ms','deadline_miss_percent','local_p95_ms','time_weighted_mean_A']])
 write('replacement_sensitivity.md',f'''# K2/C1 replacement sensitivity — secondary only

{sensitivity}

The invalid-exit run04 remains FAIL and is excluded from all primary analysis. The optional final column uses its retained raw/summary values only as an explicitly abnormal-exit secondary check, not as a valid replicate. No original artifact was modified. Primary versus original valid4 changes queue mean by +0.000863 ms, service by -0.010896 ms, DMR by +0.002778 pp, local run-P95 mean by -0.058868 ms and mean A by -0.000654. This does not materially change the K2/C1 characterization relative to the multi-ms C1→2 queue/service response or the unresolved low-C DMR ranking.

Replacement handling does not materially alter the K2/C1 characterization. This is a descriptive assessment, not a formal equivalence test. It remains a later acquisition, never a Round4 pair. Full n, sample SD, min and max are retained in replacement_sensitivity.csv.
''')
 hyp=[('H1','CONFIRMED','Queue response differs with K: K1 C1→2 +0.0389 ms (4/5 up), K2 −2.8916 ms (4/4 down), K7 −5073.2284 ms (5/5 down).'),
      ('H2','CONFIRMED','Service increases at some higher C: K5 C4→5 +5.7248 ms and K7 C6→7 +5.3554 ms, both 5/5 up. It does not rise at every adjacent step.'),
      ('H3','CONFIRMED','Same region: K5 C4→5 queue −2.2821 ms and service +5.7248 ms, both consistent in 5/5; K7 C4→5 queue −5.7090 and service +3.0746 ms, 5/5.'),
      ('H4','CONFIRMED','Non-monotonic DMR accompanies component changes: K5 C1→2 −11.0422 pp then C2→3 +1.5489 pp, each 5/5; K7 C3→4 −11.4841 then C4→5 +21.2778 pp, each 5/5. No causal attribution to queue/service alone.'),
      ('H5','CONFIRMED','C2→4 DMR rises +1.8019 pp at K6 (5/5), but falls −35.3889 pp at K7 (5/5).'),
      ('H6','NOT_CONFIRMED','No single fixed C dominates every K in measured DMR. C4 has the lowest exploratory equal-K mean, but C2 is lower at K6 in every round. Adequacy to an unspecified deployment/SLA is not established.'),
      ('H7','CONFIRMED','Opposite repeat-consistent static preferences and distinct queue/service/blocked-state regimes motivate testing adaptation. Static data do not measure achievable online improvement or transition cost.')]
 csvout('research_hypotheses.csv',[dict(hypothesis=h,verdict=v,evidence=e) for h,v,e in hyp])
 notes={1:'Mean A is 0.339–0.350 over C1..8 and FPS stays about 30.006. The 0.133–0.300% DMR variation is small in absolute terms; all misses in selected C4 and C8 runs occur in the first logical second. Their local P95s remain around 23.2–23.5 ms. This does not support a sustained high-C service penalty at K1. No clear winner between C4 and C3.',
  2:'C1→2 removes 2.892 ms mean ready waiting but increases mean service by 5.025 ms (both 4/4 original pairs). Local mean increases 19.558→21.671 ms while mean run-level local P95 decreases 23.629→23.088 ms: mean and tail need not move together. C>=2 mean A is 0.660–0.677. C2/C3/C4 tie in mean DMR. Selected C2/C8 misses are all in the first second; high-C DMR is not evidence of sustained ready backlog.',
  3:'C1→3 reduces queue 4.319→0.255 ms and increases service 4.746→11.555 ms. Mean A reaches about 1.04 at C3 and stays in 1.040–1.090 thereafter. C2 has the lowest mean DMR (0.463%) but its 0.052 pp gap to C4 is smaller than run variability. High C does not uniformly improve deadlines or tails.',
  4:'C1→4 reduces queue 6.885→0.287 ms and increases service 4.729→15.680 ms. At C4→5 queue still decreases in all five rounds and DMR rises in all five, but mean service actually falls 0.661 ms with mixed directions. Start lag rises 0.708→2.217 ms and front-end 10.518→11.361 ms. Mean run-level local P99 jumps 30.170→86.598 ms; 94.3% of C5 misses occur in the first second. This is a counterexample to attributing every DMR rise to service inflation.',
  5:'A deadline-sensitive regime appears despite approximately 150 completed FPS throughout. C1→2 DMR drops 13.189→2.147%; C2→5 queue falls 6.317→0.482 ms while service rises 7.708→19.694 ms and DMR rises to 13.773%. At C5→6 service adds 0.295 ms in 5/5 rounds after most queue relief. C5..8 mean A occupies a narrow 2.944–2.998 band, but start lag and DMR have not equivalently plateaued. C2 is mean-minimizing, yet C3 variability makes a precise single-winner claim cautious.',
  6:'All configurations have substantial deadline misses (32.296–89.550%). C1 has mean queue 82.236±62.341 ms and waiting carryover 95.244%; its run DMR spans 36.139–100%. C2→6 reduces queue 9.428→0.379 ms, increases service 8.543→23.942 ms and DMR 32.296→86.831%. Start lag also increases 0.946→8.695 ms. C6..8 mean A is 4.309–4.372; C6→7 service still grows consistently, but C7→8 does not show consistent mean-service inflation. C2 and C4 are distinct low-C basins, with C2 lower in all five DMR pairs.',
  7:'C1 is throughput/backlog overload: 184.053 completed FPS against 210 offered, mean queue 5188.484 ms and mean drain 8.459 s. C2..8 nearly recover offered throughput, but even C4 mean DMR is 47.390%. C4→7 reduces queue 11.356→0.780 ms while service grows 15.237→28.019 ms and DMR 47.390→97.262%. Start lag simultaneously rises 2.245→27.266 ms. C7→8 mean A declines 5.883→5.823 and service 28.019→27.735 ms; DMR improves modestly in every round, while local tail variability remains substantial. C8 is an endpoint, not a measured hardware limit.'}
 text=['# 1. Dataset Integrity','',
  'Primary integrity PASS: 56 K,C conditions, exactly five valid measurements each, 280 primary runs and 2,016,000 primary frames. Original campaign remains 279 PASS/1 FAIL (global index 220, K2/C1/run04, exit −11); replacement01 is a later PASS. Physical acquisitions retain 281 runs and 2,019,600 completed frames. No duplicates, missing required metric, identity mismatch or selective run exclusion. Other than the predefined invalid process exit, every valid run remains included.',
  'Canonical primary metrics were checked against formal_kc_aggregate_valid5.csv. New cap-with-waiting state fractions use a narrow timestamp sweep, not regeneration of all original latency metrics. 265 per-frame files were read for required state intersections and/or selective diagnostics; 15 zero-cap cases need no raw read. Detailed deadline diagnostics cover 22 specified conditions × all five runs (110 runs), recorded in raw_selection_policy.json. The original failed run is read only for optional secondary sensitivity.',
  '', '# 2. Metric Definitions','',
  'See metric_definitions.md for source paths and exact boundaries. Deadline: (c−a)*30 > 1,000,000,000, exactly 1/30 s after logical scheduled arrival. FPS: completed frames divided by (last c−t0), not 60 seconds or process wall time. Queue=s−r, service=c−s, local=c−a; mean local adds start lag (b−a), front-end (r−b), queue and service. Mean decomposition holds for all runs.',
  'Each table value is an equal-run mean ± sample SD (n=5), unless explicitly identified otherwise. Run-level P95/P99 columns are means of five run-level percentiles, not pooled percentiles. Component percentiles are not added. Error bars in figures use run-level SD, not frame-level replication.',
  '', '# 3. Concurrency Definition','',
  'C is the application cap on in-flight frame-level requests, not video count, batch size, CUDA core/thread count, auxiliary streams or kernel-level parallelism. A(t) counts started requests not yet completed. 0≤A≤C is the invariant of these static-C runs only. A future non-preemptive decrease may temporarily produce A>C_new while existing requests finish.',
  'A=C is cap saturation. The separately reconstructed A=C AND Q>0 fraction identifies saturation coincident with canonical ready waiting; A=C with Q=0 is not queued blocking. Neither quantity is GPU utilization. GPU kernels, SM occupancy, bandwidth and resource contention were not directly profiled. Mean A also shares an interval-area identity with service duration, so their correlation alone is not independent causal evidence.',
  '', '# 4. Overall Results','',
  'The Formal data support workload-dependent static responses and motivate controlled adaptation research. They do not demonstrate an online Dynamic-C gain. The strongest evidence is not a post-hoc minimum alone: C2→4 worsens DMR at K6 in every round and improves it at K7 in every round. Low-load DMR differences often reflect rare initial frames; high-load misses persist through the measurement window.',
  'Important contrary evidence: service does not monotonically rise at every high-C step; K4 C4→5 DMR rises despite a lower mean service, and K7 C7→8 service and DMR both fall slightly. Historical K5/C8’s 56.333% DMR is not reproduced: Formal gives 19.698±4.161%. Primary claims use Formal only; see historical_secondary_comparison.md.',
  '', '# 5. Workload-Dependent Behavior','']
 for k in range(1,8):
  text += [f'## K{k}', '',regions[k]+'.', '',notes[k],'',
   mdtable(['C','DMR %','Queue mean ms','Queue run-P95 mean ms','Service mean ms','Service run-P95 mean ms','Local run-P95 mean ms','Local run-P99 mean ms','Completed FPS'],
    [[c,*[pm(k,c,m) for m in ['deadline_miss_percent','queue_mean_ms','queue_p95_ms','service_mean_ms','service_p95_ms','local_p95_ms','local_p99_ms','completed_FPS']]] for c in range(1,9)]),'',
   mdtable(['C','Observed max A range','Mean A','A=C time %','A=C & Q>0 time %','Peak Q','Time-weighted Q','Waiting carryover %','Active carryover %','Drain s'],
    [[c,f"{float(S[k,c,'observed_max_A']['min']):g}–{float(S[k,c,'observed_max_A']['max']):g}",pm(k,c,'time_weighted_mean_A'),pm(k,c,'fraction_time_A_equals_C',100),pm(k,c,'fraction_time_cap_saturated_with_waiting',100),*[pm(k,c,m) for m in ['peak_waiting_queue','time_weighted_waiting_queue','waiting_carryover_percent','active_carryover_percent','drain_duration']]] for c in range(1,9)]),'',
   mdtable(['C','Start-lag mean ms','Front-end mean ms','Local mean ms'],[[c,*[pm(k,c,m) for m in ['start_lag_mean_ms','front_end_mean_ms','local_mean_ms']]] for c in range(1,9)]),'',
   f"Descriptive mean-A diminishing-response band C{bands[k][0]}..{bands[k][1]}: {next(x['band_mean_A_min'] for x in workload if x['K']==k):.3f}–{next(x['band_mean_A_max'] for x in workload if x['K']==k):.3f}. This is a metric-specific observed band, not a preselected threshold or proof that DMR/tails plateau.",'']
 text += ['# 6. Queue and Service Behavior','',
  'Below, H1 asks whether a queue-reduction interval exists, H2 whether service inflation co-occurs locally, and H3 whether further service growth remains after queue relief diminishes. These local tests are separate from the research-level H1–H7 in section 14. “CONFIRMED” is descriptive repeat evidence, not a statistical significance statement.', '',
  mdtable(['K','Local H1','Local H2','Local H3','Early queue Δ / paired direction','Early service Δ / paired direction'],[[q['K'],q['H1_queue_reduction'],q['H2_concurrent_service_increase'],q['H3_service_after_diminishing_queue_relief'],q['early_C_pair']+': '+q['early_delta_queue'],q['early_delta_service']] for q in qsh]),'',
  'K1’s repeat-consistent C2→3 queue decrease is only 0.068 ms and does not establish a sustained service trade-off. Late examples: K3 C3→4 queue −0.024 ms versus service +0.414 ms (5/5 service increases); K5 C5→6 queue −0.094 ms versus service +0.295 ms (5/5 service increases). K6 C6→7 has no further queue reduction (+0.084 ms) yet service +0.352 ms in 5/5. K4 high-C service directions are mixed. K7 C6→7 still increases service strongly, but after C7 the C8 step reduces mean service in 4/5; local H3 is only partially confirmed.',
  '', '# 7. Deadline Performance','',mdtable(['K','Mean-curve shape','Qualification'],[[k,*shapes[k]] for k in shapes]),'',
  'Shapes are descriptive, not an automatic threshold-based plateau/equivalence test. Several curves have an interior basin plus smaller reversals; no claim of a strictly smooth U is made. K6 is explicitly irregular because its C2→3 rise and C3→4 fall both repeat in 5/5 rounds.',
  'Queue-down/DMR-up intervals are preserved in adjacent_c_deltas.csv. Strong examples: K5 C2→3, K6 C2→3 and C5→6, K7 C4→5 and C5→6 each have queue decrease and DMR increase in all five original-round pairs. K4 C4→5 also has both signs in 5/5, despite mean service falling. These changes are accompanied by start-lag/front-end/tail changes and are not assigned to a single cause.',
  '', '# 8. Actual In-Flight Concurrency and Admission Saturation','',
  f"K1/C1: cap saturation {100*v(1,1,'fraction_time_A_equals_C'):.3f}% versus cap-with-waiting {100*v(1,1,'fraction_time_cap_saturated_with_waiting'):.3f}%. K2/C2: {100*v(2,2,'fraction_time_A_equals_C'):.3f}% versus {100*v(2,2,'fraction_time_cap_saturated_with_waiting'):.3f}%. K7/C7: {100*v(7,7,'fraction_time_A_equals_C'):.3f}% versus {100*v(7,7,'fraction_time_cap_saturated_with_waiting'):.3f}%. Conflating cap saturation with waiting would materially mischaracterize these states.",
  f"At K7/C8 the corresponding fractions are {100*v(7,8,'fraction_time_A_equals_C'):.3f}% and {100*v(7,8,'fraction_time_cap_saturated_with_waiting'):.3f}%, yet DMR is {v(7,8,'deadline_miss_percent'):.3f}%. Admission-cap relief alone therefore is not a proxy for deadline success. This does not identify GPU-internal bottlenecks.",
  '', '# 9. Latency Decomposition','',
  'At K7 C4→8, queue mean falls 11.356→0.487 ms, while start lag rises 2.245→29.991 ms, front-end 13.121→14.896 ms, service 15.237→27.735 ms and local mean 41.959→73.108 ms. Mean run-level local P95 rises 70.901→352.354 ms. Thus queue/service alone omit an important pre-ready contribution. At K6 C2→8, start lag increases 0.946→9.114 ms while service increases 8.543→24.292 ms and queue falls 9.428→0.362 ms.',
  'Selected deadline-conditioned results are in deadline_frame_components.csv. Each conditional mean is calculated within a run, then compared with equal weight across runs; aggregate frame counts describe the traces, not independent statistical samples. At K7/C8, missed-frame mean components averaged across runs are start lag 31.036, front-end 15.055, queue 0.499, service 28.121 ms. At K7/C4 they are 4.079, 14.667, 23.523, 14.363 ms. Multiple components differ; no kernel-contention cause is established.',
  'Temporal exceedance is essential: all 12 K1/C4 misses and 25 K1/C8 misses across five runs occur in the first logical second; likewise all 53 K2/C2 and 103 K2/C8 misses. At K4/C5 94.29% occur in that second. In contrast, only 1.73% of K7/C8 misses occur there, so its high DMR is not a startup-only phenomenon. These diagnostics do not remove any startup sample or recompute a “steady-state primary” result. High-C start-lag tails are observed, but their underlying cause is not proven.',
  '', '# 10. Static-C Descriptive Analysis','',
  mdtable(['K','Best-observed C','Mean DMR % ± SD','Second C','Gap pp','Pairs favoring first','Interpretation'],[[r['K'],r['tie_Cs'],f"{float(r['mean_DMR']):.4f} ± {float(r['DMR_SD']):.4f}",r['second_best_C'],f"{float(r['gap_pp']):.4f}",r['rounds_favoring_first']+'/'+r['paired_n'],r['interpretation']] for r in B]),'',
  '“Best-observed static C within the measured C=1..8 grid” is selected using this same dataset. The regret table quantifies the gap to that configuration in hindsight; it is not an online-policy score. K1–K5 have no clear single winner under the conservative descriptive gap/direction flag; K5 nevertheless favors C2 over C3 in all five pairs, with large variation in effect size.',
  'Exploratory equal-K mean DMR is minimized at C4: 12.7853%. The hindsight per-K minima average 11.8979%, a descriptive gap of 0.8874 pp. Equal K weights are not deployment frequencies and this gap is not a predicted Dynamic-C benefit. A fixed C4 is a sensible comparator for future tests, not a universally dominant configuration or an established adequate setting for an unspecified SLA.',
  '', '# 11. Run-to-Run / Round-Paired Consistency','',
  'Adjacent tables retain every original-round difference, including explicit MISSING_ORIGINAL_FAIL entries at K2/C1→2 Round4 for each metric. That comparison has four pairs; all others have five. Replacement appears in primary means only. Queue and service effects are highly consistent in the main low-to-mid C transitions at K2–K7; small high-C steps and low-load DMR are often mixed.',
  'The central non-adjacent contrast is C2→4: K6 DMR +1.8019 pp, paired range +0.8519 to +3.6944, 5/5 increases; K7 −35.3889 pp, paired range −52.1508 to −11.7222, 5/5 decreases. This supports workload dependence without needing a selected best-C claim.',
  'Variability is retained: K5/C3 DMR=[2.9222,10.3778,1.5889,1.7222,1.8667]%; K6/C1=[63.9537,100,77.9907,36.1389,37.9259]%; K7/C2=[100,79.4603,84.0159,91.1667,59.2540]%. These are valid runs, not grounds for exclusion. kc_full_summary.csv includes sample SD, min/max, CV (undefined at zero mean) and all five values. Near-zero DMR CV is unstable and is not used to rank configurations.',
  '', '# 12. Temporal Drift','',dt,'',
  'The balanced 55-cell original-only panel shows no sustained service drift but visible DMR round bias concentrated in sensitive conditions. Meaningful system-wide drift attribution is UNCLEAR; balance reduces temporal confounding but does not prove its absence. See round_drift_analysis.md for slopes, per-cell contributions and the original 279-row reference. No drift correction or replacement insertion is performed.',
  '', '# 13. Replacement Sensitivity','',sensitivity,'',
  'Primary valid5 versus original valid4 changes K2/C1 DMR by +0.002778 pp and mean run-level local P95 by −0.058868 ms. The secondary invalid-exit comparison is similarly close. Replacement handling does not materially alter the K2/C1 characterization; it is not a formal equivalence test. The failed run remains excluded from primary and round analyses.',
  '', '# 14. Research Hypotheses','',mdtable(['Hypothesis','Verdict','Numerical / repeated evidence'],hyp),'',
  '# 15. Implications for Dynamic-C Control','',
  'SUPPORTED as research motivation: configuration effects depend on workload, repeat-consistent static preferences conflict, and low ready waiting can coexist with poor deadline performance. A future policy must consider more than ready-queue length or cap occupancy. The data do not establish its state estimator, decision rule, switch timing, achievable miss reduction or cost. Residual predictors, shadow replay and online scheduling are outside this analysis.',
  'Static endpoints do not reveal how already-running requests respond when C changes. Non-preemptive decreases can leave A>C_new temporarily. A transition may incur service/queue/start-lag transients that erase a hindsight static gap. Those must be measured before any superiority claim.',
  '', '# 16. Next Transition Experiments','',
  mdtable(['K','Workload','C_low ↔ C_high','Static DMR %','Static queue ms','Static service ms'],[[k,kind,f'{cl} ↔ {ch}',f"{v(k,cl,'deadline_miss_percent'):.3f} ↔ {v(k,ch,'deadline_miss_percent'):.3f}",f"{v(k,cl,'queue_mean_ms'):.3f} ↔ {v(k,ch,'queue_mean_ms'):.3f}",f"{v(k,cl,'service_mean_ms'):.3f} ↔ {v(k,ch,'service_mean_ms'):.3f}"] for k,cl,ch,kind in [(2,1,2,'low/moderate'),(5,2,5,'boundary'),(6,2,6,'deadline overload bridge'),(7,4,7,'high/severe deadline overload')]]),'',
  'These eight directional candidates are proposals only, not executed. K2 spans a real queue/service change before its occupancy plateau; K5 spans the sensitive deadline boundary; K7 spans sharply different service/start-lag/deadline behavior; K6 isolates a large high-C deadline penalty while throughput remains near offered. Measure already-running inference service response, ready-queue response, pre-ready latency, transient deadline misses, and non-preemptive decrease. Preserve both directions; do not fabricate completion times from static traces.',
  '', '# 17. Limitations','']
 limitations=['Same video content repeated; run is the experimental unit, not frames or independent workload samples.',
  'One Jetson AGX Thor platform and RT-DETR Warehouse workload; MAXN with natural/unlocked DVFS, not fixed device frequency.',
  'C=1..8 is the tested range, not hardware maximum; C and A are application-level in-flight quantities.',
  'A<=C is a static-C invariant only; a future non-preemptive decrease can temporarily give A>C.',
  'A=C alone does not prove queued admission blocking; the new metric requires simultaneous Q>0 and uses host accounting boundaries, not measured observer publication delays.',
  'A(t) is not kernel-level parallelism or utilization; GPU internal kernel/resource contention was not directly profiled.',
  'Mean A and service share an interval-area identity; association alone does not establish a direction of causation.',
  'Run-level P95/P99 averaging is not pooled percentile calculation; component P95s are not additive.',
  '60-second offered window with startup and drain retained; no theoretical queue-stability proof or stationarity claim.',
  'Replacement is post-campaign; original K2/C1 Round4 remains missing in temporal/paired analysis.',
  'Five repeats can expose variability but cannot exclude temporal confounding. Some means/tails are highly variable; no valid outlier was removed.',
  'Historical video content hashes were not recorded for the replacement audit; path and ffprobe identity matched, historical content-hash continuity remains UNKNOWN.',
  'Best-observed C and regret are post-hoc descriptive quantities with selection bias; equal-K weighting is not a deployment distribution.',
  'Dynamic-C gain, transition cost and online decision accuracy are not demonstrated by static characterization.',
  'The retained stale pilot/non-formal validator strings are documented legacy labels; raw/frozen artifacts were not rewritten.']
 text += ['- '+x for x in limitations]
 text += ['', '**Final verdict: FORMAL_CHARACTERIZATION_SUPPORTS_DYNAMIC_C_MOTIVATION**', '',
          'This verdict motivates controlled transition research only. No new GPU measurement, replacement, Dynamic-C/Edge run, source modification, commit or push was performed.']
 write('formal_static_concurrency_analysis.md','\n\n'.join(text))
 figures()
 # Final immutable-input audit follows all derived writes.
 before=json.loads((D/'protected_inputs_before.json').read_text())
 bad=[p for p,h in before.items() if not Path(p).is_file() or Path(p).stat().st_size!=h['bytes'] or sha(Path(p))!=h['sha256']]
 assert not bad,bad
 integrity=json.loads((D/'analysis_integrity.json').read_text())
 integrity.update(preservation_validation='PASS',protected_files_checked=len(before),hash_mismatches=bad,
                  figures=sorted(p.name for p in (D/'figures').glob('*.pdf')),
                  git_status=subprocess.check_output(['git','status','--short'],cwd=REPO,text=True).strip(),
                  verdict='FORMAL_CHARACTERIZATION_SUPPORTS_DYNAMIC_C_MOTIVATION')
 (D/'analysis_integrity.json').write_text(json.dumps(integrity,indent=2)+'\n')
 print('REPORT / FIGURES / PRESERVATION PASS',flush=True)

if __name__=='__main__':render()
