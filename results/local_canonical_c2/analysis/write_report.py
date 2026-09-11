from pathlib import Path
import json,csv,statistics,hashlib
D=Path(__file__).resolve().parents[1];A=D/'analysis';data=json.loads((A/'analysis_data.json').read_text());t=json.loads((A/'temporal_analysis.json').read_text())
assert json.loads((D/'formal_integrity_report.json').read_text())['validation']=='PASS'
assert json.loads((A/'derived_integrity_report.json').read_text())['validation']=='PASS'
def cell(r,m):return f"{r[m+'_mean']:.3f} ± {r[m+'_sample_sd']:.3f} [{r[m+'_min']:.3f}, {r[m+'_max']:.3f}]"
metrics=['local_latency_mean_ms','local_latency_p95_ms','local_latency_p99_ms','deadline_miss_pct','queue_wait_mean_ms','queue_wait_p95_ms','inference_mean_ms','inference_p95_ms']
labels=['Local mean ms','Local p95 ms','Local p99 ms','Miss %','Queue mean ms','Queue p95 ms','Inference mean ms','Inference p95 ms']
lines=['# Canonical static C2 Local baseline: analysis report','',
'35/35 full-source runs and 252000/252000 frames PASS. Failed runs: 0. Retried runs: 0. C=2 is used as the fixed static runtime configuration for the canonical Local baseline. No dynamic concurrency control was implemented.','',
'All raw JSON/CSV data were independently reread after the campaign: exact IDs, integer-ns timing/decomposition, queue replay, actual natural EOS for all 140 source instances, complete drain, clean joins/NULL shutdown and independent resource ownership PASS. A separate NumPy analysis check rechecked statistics for all 252000 frames and temporal counts for all 27000 selected/context period rows.','',
'B=1, shared canonical engine, two independent workers/contexts/nonblocking submission streams/device I/O/pinned staging sets; async H2D/execute_async_v3/async D2H/own-stream synchronization; no device-wide synchronization or CUDA Graph. Engine hash 9d01cdb2838bb1b9db58c246e6111a5dccee63bb937b673fb48caf43e53bc5ff remained fixed. MAXN, DVFS unlocked and jetson_clocks OFF were verified before and after each run. C counts frame-level outstanding capacity, not K, GPU threads or engine auxiliary streams.','',
'Five run-level statistics per K, arithmetic mean ± sample SD [min,max]. Median and all five values are also in motivation_summary.csv / run_level_variability.csv. Frames from different runs were not pooled for primary statistics. Every startup frame is retained: no warm-up, no exclusions, no drops, no deliberate cooldown. The exact deadline test is local_latency_ns * 30 > 1000000000, a cadence-based candidate deadline, not a final application SLA.','',
'| K | '+' | '.join(labels)+' |','|'+'---|'*9]
for r in data['summary']:lines.append('| '+str(r['K'])+' | '+' | '.join(cell(r,m) for m in metrics)+' |')
lines += ['', '## Observed transition, selected from new data','',
'K4→K5 is an early tail/miss deterioration; K5→K6 is the primary deadline-QoS transition. K5 miss ranges 1.278–5.711%, while K6 ranges 31.602–33.185%; these observed ranges do not overlap. The mean difference is +29.834 percentage points, and all five repetition-index comparisons increase. Local p95 rises from 32.498 to 39.165 ms (all five increases), and queue mean from 5.989 to 9.731 ms (all five increases). K6 mean latency remains below the candidate deadline, illustrating why mean alone would hide deadline degradation. This selection was made after the new whole-campaign gate, not copied from the old C1 result.','',
'K6→K7 is a second, larger queue/tail transition: queue mean 9.731→115.064 ms; local p95 39.165→259.276 ms; miss 32.185→77.149%. All five corresponding differences increase. K7 miss has SD 14.408 pp and range 60.611–100%; local mean ranges 88.068–212.237 ms. These are five separate runs, not statistical significance or population-superiority claims.','',
'## C2-safe temporal characterization','',
'Figure 3 compares K5/K6; K7 is separately retained as context for the second queue/tail transition. All 1800 periods per run remain included. Ready-time span is max(r)-min(r) among the K frames with the same logical frame ID. Period boundary is t0+floor((j+1)*1e9/30). Prior work means frame IDs ≤j; unfinished work is split into pre-ready, waiting r≤t<s, and active s≤t<c. Ready unfinished inference is waiting+active. Next-first-ready evaluates those prior IDs at the earliest r of the next period (1799 comparisons per run).','',
'| K | Ready span mean ms | Boundary waiting positive % | Boundary active positive % | Prior unfinished at next first-ready % |','|---|---|---|---|---|']
for r in t['summary']:
 lines.append('| '+str(r['K'])+' | '+' | '.join(cell(r,m) for m in ['ready_span_ms_mean','boundary_prior_waiting_positive_pct','boundary_prior_active_positive_pct','next_first_ready_prior_unfinished_positive_pct'])+' |')
lines += ['',
'K6 active carry-over is common at the cadence boundary (98.633%), yet waiting carry-over is much less common (3.156%) and most prior work clears before the next period first becomes ready (only 3.491% still unfinished). Deadline misses therefore must not be equated with a persistently nonempty waiting queue at every period boundary. K7 differs: waiting carry-over is 98.178%, and prior work remains at next first-ready in 71.973% of periods on average. The ready-span difference K5/K6 is small relative to run variation; it alone does not explain the QoS transition.','',
'Actual-time Q(t) and active(t) are exactly integrated, not point-sampled. The original queue time-weighted metric keeps its first-ready-enqueue through last-ready-enqueue window. Separate offered-window metrics integrate [t0,t0+60s); active=0/1/2 percentages use this fixed window and include idle/startup time. Neither is GPU utilization.','',
'| K | Queue peak | Waiting time mean (original window) | Offered active mean | Offered active=2 % |','|---|---|---|---|---|']
for r in data['summary']:lines.append('| '+str(r['K'])+' | '+' | '.join(cell(r,m) for m in ['peak_waiting_queue','time_weighted_waiting_queue','time_weighted_active_offered','active_2_offered_pct'])+' |')
lines += ['',
'All 35 runs used both configured workers and observed max active=2; the fraction at active=2 depends strongly on K (K1 only 0.054% of the offered window, largely startup). Independent contexts, stream pointers and nonoverlapping device/pinned ranges were checked. Host service and submitted-before-sync-return overlaps establish concurrent outstanding requests only; physical GPU kernel overlap was not measured.','',
'Queue depth immediately before enqueue is strongly associated with subsequent queue wait: per-run Pearson ranges K5 0.895–0.951, K6 0.978–0.991, K7 0.978–0.998. This is descriptive, not a causal estimator or scheduler. Small positive handoff waits at depth zero are not evidence of persistent backlog.','',
'K7 does not show uniform monotonic backlog growth: queues are large early and in four runs fall near two time-mean waiting frames later in the workload. Run04 retains substantially more backlog later, but also decreases. After the 60-second offered boundary, K7 residual completion drain is 0.0106–0.0861 s; every accepted frame completes. The evidence supports deadline degradation and long backlog recovery in this startup-inclusive finite workload, not a demonstrated sustained steady-state throughput collapse. No warm-up or frame exclusion is introduced to change that conclusion. Per-run one-second and ten-second traces are retained.','',
'## Service metric and historical comparison','',
'Old C1 period sum(c-s) versus 33.333 ms is NOT reused. In C2, overlapping intervals would double-count wall time. Active event integration is descriptive request occupancy, never GPU wall-clock demand or throughput capacity. Inference service here includes private staging, transfers, host calls and stream-local completion, not pure kernel time. Its dependence on K is not assumed monotonic under unlocked DVFS, and no unmeasured clock-causality claim is made.','',
'Historical results/local_latency_breakdown remains serialized-runtime characterization. The new campaign remains affected by queue/deadline degradation with concurrency-capable submission, while its queue trajectories differ from the historical serialized result. The two implementations differ in pinned memory, transfer and synchronization paths; old C1→new C2 is not an isolated concurrency-effect comparison. No old frame or run is pooled into this campaign. The prior identical-path C1/C2 control is separate supporting evidence.','',
'## Figures and Local phase decision','',
'Four PNG-only figures were generated in analysis/figures after the independent gates and visually inspected. Figure 1: Local QoS scaling and candidate deadline. Figure 2: additive mean per-frame decomposition (K7 uses a separate ms scale). Figure 3: newly selected K5/K6 temporal characterization distinguishing waiting and active. Figure 4: deadline degradation and queue wait versus inference service, with no period service-sum capacity metric. Old figures were not changed. Captions and source paths are in analysis/figure_manifest.json.','',
'Canonical Local baseline complete: YES. Static runtime and campaign artifacts can be frozen: YES, for this documented C2/B1/MAXN/DVFS-unlocked, phase-aligned, full-source, startup-inclusive protocol. This is a fixed baseline choice, not proof of universally best concurrency or a final application SLA. The main Local paper characterization should use this new campaign and accurately distinguish the K5→K6 deadline transition from K6→K7 prolonged queueing. A stronger sustained-throughput-collapse claim is not supported by these finite traces.','',
'Next step: RT-DETR graph split feasibility may proceed as a separate task; no partition work was performed here. Prior C2/C4 studies suggest lower C can reduce per-request contention while higher C can reduce overload queueing; no single tested C dominated every workload. Future C_t∈{2,4} is a possible separate research action, not implemented in this static baseline.','',
'Preservation verification is recorded separately in artifact_integrity_report.json (SHA256, size, mtime_ns for every pre-existing protected file). No commit, push, reset or clean was performed.']
(D/'analysis_report.md').write_text('\n'.join(lines)+'\n')
# Preserve both primary per-run values and a compact human-readable table without averaging frames across runs.
rl=['# Individual run statistics','', '| K | run | '+' | '.join(labels)+' |','|'+'---|'*10]
for r in data['runs']:rl.append('| '+str(r['K'])+' | '+r['run_id']+' | '+' | '.join(f'{r[m]:.6f}' for m in metrics)+' |')
(A/'individual_run_table.md').write_text('\n'.join(rl)+'\n')
# Descriptive ten-second bins; all six bins retained, no primary sample exclusion.
with (A/'temporal_timeline_1s.csv').open() as f:timeline=list(csv.DictReader(f))
bins=[]
for k in [5,6,7]:
 for rep in range(1,6):
  rr=[r for r in timeline if int(r['K'])==k and r['run_id']==f'run{rep:02d}']
  for first in range(0,60,10):
   rows=rr[first:first+10]
   bins.append({'K':k,'run_id':f'run{rep:02d}','actual_start_s':first,'actual_end_s':first+10,'waiting_time_mean':statistics.mean(float(r['waiting_time_mean']) for r in rows),'active_time_mean':statistics.mean(float(r['active_time_mean']) for r in rows)})
with (A/'queue_timeline_10s.csv').open('w',newline='') as f:
 w=csv.DictWriter(f,fieldnames=list(bins[0]));w.writeheader();w.writerows(bins)
print('Wrote analysis report, individual run table and descriptive queue bins')
