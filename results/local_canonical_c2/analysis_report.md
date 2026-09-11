# Canonical static C2 Local baseline: analysis report

35/35 full-source runs and 252000/252000 frames PASS. Failed runs: 0. Retried runs: 0. C=2 is used as the fixed static runtime configuration for the canonical Local baseline. No dynamic concurrency control was implemented.

All raw JSON/CSV data were independently reread after the campaign: exact IDs, integer-ns timing/decomposition, queue replay, actual natural EOS for all 140 source instances, complete drain, clean joins/NULL shutdown and independent resource ownership PASS. A separate NumPy analysis check rechecked statistics for all 252000 frames and temporal counts for all 27000 selected/context period rows.

B=1, shared canonical engine, two independent workers/contexts/nonblocking submission streams/device I/O/pinned staging sets; async H2D/execute_async_v3/async D2H/own-stream synchronization; no device-wide synchronization or CUDA Graph. Engine hash 9d01cdb2838bb1b9db58c246e6111a5dccee63bb937b673fb48caf43e53bc5ff remained fixed. MAXN, DVFS unlocked and jetson_clocks OFF were verified before and after each run. C counts frame-level outstanding capacity, not K, GPU threads or engine auxiliary streams.

Five run-level statistics per K, arithmetic mean ± sample SD [min,max]. Median and all five values are also in motivation_summary.csv / run_level_variability.csv. Frames from different runs were not pooled for primary statistics. Every startup frame is retained: no warm-up, no exclusions, no drops, no deliberate cooldown. The exact deadline test is local_latency_ns * 30 > 1000000000, a cadence-based candidate deadline, not a final application SLA.

| K | Local mean ms | Local p95 ms | Local p99 ms | Miss % | Queue mean ms | Queue p95 ms | Inference mean ms | Inference p95 ms |
|---|---|---|---|---|---|---|---|---|
| 1 | 21.608 ± 0.279 [21.264, 21.976] | 23.539 ± 0.240 [23.180, 23.807] | 23.896 ± 0.103 [23.747, 24.026] | 0.167 ± 0.000 [0.167, 0.167] | 0.168 ± 0.043 [0.128, 0.229] | 0.243 ± 0.012 [0.232, 0.260] | 11.474 ± 0.251 [11.255, 11.794] | 13.318 ± 0.231 [12.968, 13.542] |
| 2 | 21.758 ± 0.144 [21.527, 21.901] | 23.081 ± 0.104 [22.969, 23.204] | 23.697 ± 0.156 [23.468, 23.907] | 0.294 ± 0.025 [0.278, 0.333] | 0.187 ± 0.032 [0.149, 0.238] | 0.245 ± 0.005 [0.239, 0.251] | 11.017 ± 0.106 [10.873, 11.139] | 12.261 ± 0.162 [12.075, 12.441] |
| 3 | 21.142 ± 0.492 [20.589, 21.564] | 24.339 ± 0.677 [23.568, 25.047] | 25.060 ± 0.681 [24.190, 25.654] | 0.533 ± 0.050 [0.500, 0.611] | 2.707 ± 0.106 [2.536, 2.794] | 8.254 ± 0.365 [7.792, 8.742] | 7.433 ± 0.269 [7.121, 7.666] | 9.409 ± 0.481 [8.844, 9.775] |
| 4 | 23.153 ± 0.648 [22.080, 23.713] | 27.788 ± 0.116 [27.623, 27.896] | 29.387 ± 0.636 [28.690, 29.954] | 0.653 ± 0.168 [0.444, 0.833] | 3.868 ± 0.257 [3.447, 4.077] | 8.365 ± 0.088 [8.284, 8.502] | 8.094 ± 0.154 [7.831, 8.224] | 9.184 ± 0.103 [9.010, 9.268] |
| 5 | 25.721 ± 1.245 [23.611, 26.832] | 32.498 ± 0.642 [32.041, 33.625] | 48.957 ± 19.504 [34.952, 82.303] | 2.351 ± 1.887 [1.278, 5.711] | 5.989 ± 0.791 [4.728, 6.749] | 14.951 ± 0.420 [14.420, 15.379] | 7.712 ± 0.037 [7.666, 7.764] | 9.098 ± 0.046 [9.032, 9.156] |
| 6 | 31.338 ± 0.991 [30.268, 32.766] | 39.165 ± 1.712 [38.088, 42.065] | 173.081 ± 31.650 [142.154, 206.621] | 32.185 ± 0.633 [31.602, 33.185] | 9.731 ± 0.736 [8.878, 10.680] | 16.148 ± 0.134 [16.049, 16.365] | 8.537 ± 0.065 [8.466, 8.616] | 10.101 ± 0.442 [9.782, 10.823] |
| 7 | 138.849 ± 45.411 [88.068, 212.237] | 259.276 ± 7.291 [252.391, 270.643] | 274.016 ± 9.974 [264.453, 290.122] | 77.149 ± 14.408 [60.611, 100.000] | 115.064 ± 44.731 [65.173, 187.405] | 233.560 ± 7.135 [226.798, 243.840] | 9.020 ± 0.262 [8.736, 9.439] | 12.232 ± 0.732 [11.315, 13.334] |

## Observed transition, selected from new data

K4→K5 is an early tail/miss deterioration; K5→K6 is the primary deadline-QoS transition. K5 miss ranges 1.278–5.711%, while K6 ranges 31.602–33.185%; these observed ranges do not overlap. The mean difference is +29.834 percentage points, and all five repetition-index comparisons increase. Local p95 rises from 32.498 to 39.165 ms (all five increases), and queue mean from 5.989 to 9.731 ms (all five increases). K6 mean latency remains below the candidate deadline, illustrating why mean alone would hide deadline degradation. This selection was made after the new whole-campaign gate, not copied from the old C1 result.

K6→K7 is a second, larger queue/tail transition: queue mean 9.731→115.064 ms; local p95 39.165→259.276 ms; miss 32.185→77.149%. All five corresponding differences increase. K7 miss has SD 14.408 pp and range 60.611–100%; local mean ranges 88.068–212.237 ms. These are five separate runs, not statistical significance or population-superiority claims.

## C2-safe temporal characterization

Figure 3 compares K5/K6; K7 is separately retained as context for the second queue/tail transition. All 1800 periods per run remain included. Ready-time span is max(r)-min(r) among the K frames with the same logical frame ID. Period boundary is t0+floor((j+1)*1e9/30). Prior work means frame IDs ≤j; unfinished work is split into pre-ready, waiting r≤t<s, and active s≤t<c. Ready unfinished inference is waiting+active. Next-first-ready evaluates those prior IDs at the earliest r of the next period (1799 comparisons per run).

| K | Ready span mean ms | Boundary waiting positive % | Boundary active positive % | Prior unfinished at next first-ready % |
|---|---|---|---|---|
| 5 | 3.530 ± 1.239 [2.553, 5.304] | 0.811 ± 0.174 [0.667, 1.111] | 7.411 ± 9.346 [2.556, 24.111] | 1.001 ± 0.171 [0.778, 1.223] |
| 6 | 3.922 ± 0.508 [3.409, 4.758] | 3.156 ± 2.041 [1.944, 6.778] | 98.633 ± 1.543 [96.000, 99.667] | 3.491 ± 2.231 [2.168, 7.449] |
| 7 | 5.257 ± 0.170 [5.044, 5.511] | 98.178 ± 1.089 [96.889, 99.833] | 99.756 ± 0.075 [99.667, 99.833] | 71.973 ± 17.319 [53.585, 100.000] |

K6 active carry-over is common at the cadence boundary (98.633%), yet waiting carry-over is much less common (3.156%) and most prior work clears before the next period first becomes ready (only 3.491% still unfinished). Deadline misses therefore must not be equated with a persistently nonempty waiting queue at every period boundary. K7 differs: waiting carry-over is 98.178%, and prior work remains at next first-ready in 71.973% of periods on average. The ready-span difference K5/K6 is small relative to run variation; it alone does not explain the QoS transition.

Actual-time Q(t) and active(t) are exactly integrated, not point-sampled. The original queue time-weighted metric keeps its first-ready-enqueue through last-ready-enqueue window. Separate offered-window metrics integrate [t0,t0+60s); active=0/1/2 percentages use this fixed window and include idle/startup time. Neither is GPU utilization.

| K | Queue peak | Waiting time mean (original window) | Offered active mean | Offered active=2 % |
|---|---|---|---|---|
| 1 | 1.000 ± 0.000 [1.000, 1.000] | 0.005 ± 0.001 [0.004, 0.007] | 0.344 ± 0.008 [0.338, 0.354] | 0.054 ± 0.004 [0.049, 0.058] |
| 2 | 5.000 ± 1.225 [3.000, 6.000] | 0.011 ± 0.002 [0.009, 0.014] | 0.661 ± 0.006 [0.652, 0.668] | 31.445 ± 0.441 [30.804, 31.806] |
| 3 | 12.000 ± 1.414 [11.000, 14.000] | 0.244 ± 0.010 [0.229, 0.252] | 0.669 ± 0.024 [0.641, 0.690] | 25.935 ± 1.066 [24.730, 26.939] |
| 4 | 17.200 ± 3.564 [11.000, 20.000] | 0.465 ± 0.031 [0.414, 0.491] | 0.971 ± 0.018 [0.940, 0.987] | 45.350 ± 2.101 [41.716, 46.965] |
| 5 | 26.600 ± 4.037 [21.000, 32.000] | 0.900 ± 0.119 [0.711, 1.015] | 1.157 ± 0.006 [1.150, 1.165] | 50.500 ± 0.644 [49.388, 50.962] |
| 6 | 43.000 ± 6.364 [37.000, 51.000] | 1.757 ± 0.134 [1.603, 1.929] | 1.536 ± 0.012 [1.524, 1.551] | 72.765 ± 0.974 [72.028, 74.026] |
| 7 | 56.800 ± 2.387 [54.000, 60.000] | 24.225 ± 9.404 [13.719, 39.427] | 1.893 ± 0.054 [1.834, 1.980] | 90.904 ± 4.563 [85.832, 98.169] |

All 35 runs used both configured workers and observed max active=2; the fraction at active=2 depends strongly on K (K1 only 0.054% of the offered window, largely startup). Independent contexts, stream pointers and nonoverlapping device/pinned ranges were checked. Host service and submitted-before-sync-return overlaps establish concurrent outstanding requests only; physical GPU kernel overlap was not measured.

Queue depth immediately before enqueue is strongly associated with subsequent queue wait: per-run Pearson ranges K5 0.895–0.951, K6 0.978–0.991, K7 0.978–0.998. This is descriptive, not a causal estimator or scheduler. Small positive handoff waits at depth zero are not evidence of persistent backlog.

K7 does not show uniform monotonic backlog growth: queues are large early and in four runs fall near two time-mean waiting frames later in the workload. Run04 retains substantially more backlog later, but also decreases. After the 60-second offered boundary, K7 residual completion drain is 0.0106–0.0861 s; every accepted frame completes. The evidence supports deadline degradation and long backlog recovery in this startup-inclusive finite workload, not a demonstrated sustained steady-state throughput collapse. No warm-up or frame exclusion is introduced to change that conclusion. Per-run one-second and ten-second traces are retained.

## Service metric and historical comparison

Old C1 period sum(c-s) versus 33.333 ms is NOT reused. In C2, overlapping intervals would double-count wall time. Active event integration is descriptive request occupancy, never GPU wall-clock demand or throughput capacity. Inference service here includes private staging, transfers, host calls and stream-local completion, not pure kernel time. Its dependence on K is not assumed monotonic under unlocked DVFS, and no unmeasured clock-causality claim is made.

Historical results/local_latency_breakdown remains serialized-runtime characterization. The new campaign remains affected by queue/deadline degradation with concurrency-capable submission, while its queue trajectories differ from the historical serialized result. The two implementations differ in pinned memory, transfer and synchronization paths; old C1→new C2 is not an isolated concurrency-effect comparison. No old frame or run is pooled into this campaign. The prior identical-path C1/C2 control is separate supporting evidence.

## Figures and Local phase decision

Four PNG-only figures were generated in analysis/figures after the independent gates and visually inspected. Figure 1: Local QoS scaling and candidate deadline. Figure 2: additive mean per-frame decomposition (K7 uses a separate ms scale). Figure 3: newly selected K5/K6 temporal characterization distinguishing waiting and active. Figure 4: deadline degradation and queue wait versus inference service, with no period service-sum capacity metric. Old figures were not changed. Captions and source paths are in analysis/figure_manifest.json.

Canonical Local baseline complete: YES. Static runtime and campaign artifacts can be frozen: YES, for this documented C2/B1/MAXN/DVFS-unlocked, phase-aligned, full-source, startup-inclusive protocol. This is a fixed baseline choice, not proof of universally best concurrency or a final application SLA. The main Local paper characterization should use this new campaign and accurately distinguish the K5→K6 deadline transition from K6→K7 prolonged queueing. A stronger sustained-throughput-collapse claim is not supported by these finite traces.

Next step: RT-DETR graph split feasibility may proceed as a separate task; no partition work was performed here. Prior C2/C4 studies suggest lower C can reduce per-request contention while higher C can reduce overload queueing; no single tested C dominated every workload. Future C_t∈{2,4} is a possible separate research action, not implemented in this static baseline.

Preservation verification is recorded separately in artifact_integrity_report.json (SHA256, size, mtime_ns for every pre-existing protected file). No commit, push, reset or clean was performed.
