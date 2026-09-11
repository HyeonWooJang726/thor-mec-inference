# Local inference concurrency formal control

Primary comparison: **new control C=1 vs new control C=2**, using identical request, transfer, timing and queue code.
Completed: 30/30 valid runs, 324,000 frames; 162,000 per C. No failed run was excluded or replaced.

## Conditions and interpretation boundaries

- Canonical RT-DETR B=1 engine, same audited W027 Camera_0000..0006 cumulative K mapping, 30 FPS phase-aligned logical arrivals, 1800 frames/stream, 60-second offered workload; drain included as needed.
- MAXN, DVFS unlocked, jetson_clocks OFF (readable CPU/GPU/EMC min<max), CUDA Graph OFF. No power/clock/model/engine changes. Environment before/after is retained for every run.
- No warm-up or sample exclusion, matching the frozen application workload. The old trtexec warm-up belongs to a separate harness.
- Both C values use private pinned staging, asynchronous H2D, execute_async_v3 on nonblocking worker streams, asynchronous D2H and stream-local synchronization. No cudaDeviceSynchronize is called by this inference path.
- Only concurrency-dependent worker/context/stream/buffer-set counts differ: one vs two. The engine reports two within-inference auxiliary streams per context, unchanged; cuda_stream_count refers to explicit submission streams.
- a/b/r/s/c are raw integer ns. c is host-output availability after stream synchronization. Waiting queue is ready-but-not-started N_enqueue−N_start, excluding all active requests.
- Queue peak covers the whole run through drain; time-weighted waiting queue integrates first to last ready enqueue, identical to the old metric definition.
- Candidate deadline is exactly 1/30 second: e2e_ns*30>1,000,000,000. This is not a final application SLA.
- Specified five rounds interleave C and K; deliberate cooldown NONE. Exact order/commands are in formal_plan.json. Each next run starts only after previous exit, cleanup and artifact validation.
- Paired means matching run indices, not simultaneous execution or a paired randomized trial. Five pairs support descriptive direction/variability, not strong statistical significance claims.
- Host service and submitted-unsynchronized interval overlap establish concurrent submission/outstanding inference only. GPU kernel overlap was not directly measured.

## Run-level aggregation

Every configuration cell below is the arithmetic mean ± sample SD [min, max] of five run-level statistics. Per-run quantiles use exact linear interpolation of integer ns; no pooling across runs. Full values: per_run_summary.csv and formal_summary.csv.

| C | K | Local mean ms | Local median ms | Local p95 ms | Local p99 ms | Miss % | Queue wait mean ms | Inference mean ms |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 5 | 26.588797 ± 0.975255 [25.956345, 28.310251] | 24.611833 ± 0.560445 [24.314906, 25.611493] | 35.792459 ± 2.046116 [34.811572, 39.451521] | 116.442573 ± 14.826399 [101.054640, 139.233283] | 13.975556 ± 3.334976 [11.133333, 19.311111] | 9.530695 ± 0.188839 [9.292513, 9.761685] | 4.837695 ± 0.156400 [4.737588, 5.112985] |
| 1 | 6 | 81.681730 ± 56.579155 [40.519240, 168.287618] | 65.842208 ± 74.901938 [28.942985, 199.438924] | 195.452730 ± 40.968821 [147.280644, 243.190562] | 253.193261 ± 14.193373 [238.123763, 275.873525] | 53.055556 ± 21.864937 [36.666667, 86.212963] | 63.076410 ± 55.685033 [22.634962, 148.224841] | 5.216710 ± 0.109325 [5.119236, 5.380383] |
| 1 | 7 | 5002.334505 ± 354.048325 [4651.179967, 5596.304487] | 5159.686145 ± 400.503574 [4710.710659, 5807.594609] | 8335.646568 ± 455.675705 [7908.621198, 9110.990977] | 8419.830033 ± 453.551444 [7994.579602, 9192.769875] | 100.000000 ± 0.000000 [100.000000, 100.000000] | 4982.414996 ± 353.811124 [4631.457995, 5575.985291] | 5.353857 ± 0.032292 [5.324170, 5.408670] |
| 2 | 5 | 25.983327 ± 0.429924 [25.453442, 26.500644] | 26.862501 ± 0.076207 [26.750245, 26.931052] | 32.177275 ± 0.041631 [32.135981, 32.230064] | 53.217928 ± 25.094537 [33.311803, 86.900914] | 1.326667 ± 0.220493 [1.000000, 1.533333] | 6.459744 ± 0.323827 [6.068810, 6.867305] | 7.693725 ± 0.008298 [7.682653, 7.704910] |
| 2 | 6 | 30.924454 ± 0.651612 [30.143695, 31.736819] | 28.136404 ± 0.077361 [28.025405, 28.214125] | 38.071997 ± 0.122533 [37.908244, 38.216307] | 167.406646 ± 28.888749 [137.731048, 204.610886] | 32.661111 ± 0.346301 [32.287037, 33.083333] | 9.662193 ± 0.468223 [9.088756, 10.268002] | 8.545962 ± 0.024082 [8.520761, 8.580789] |
| 2 | 7 | 115.574804 ± 62.024594 [52.408663, 186.758947] | 115.778645 ± 80.058377 [35.233113, 205.142685] | 232.592492 ± 30.677763 [188.051562, 258.456805] | 283.799592 ± 9.769890 [270.463664, 294.100300] | 74.634921 ± 21.856271 [51.388889, 95.849206] | 91.840800 ± 61.019772 [29.936202, 162.189654] | 8.964942 ± 0.393398 [8.540945, 9.347196] |

## Primary C2−C1 comparison

| K | Miss difference pp | Queue mean difference ms | Queue p95 difference ms | Local mean difference ms | Local p95 difference ms | Local p99 difference ms | Inference mean difference ms | Inference p95 difference ms | Peak queue difference |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 5 | -12.648889 | -3.070951 | -1.516618 | -0.605470 | -3.615184 | -63.224645 | 2.856030 | 3.240439 | -5.200000 |
| 6 | -20.394444 | -53.414216 | -156.057549 | -50.757276 | -157.380732 | -85.786615 | 3.329251 | 2.062710 | -4.800000 |
| 7 | -25.365079 | -4890.574196 | -8112.008708 | -4886.759700 | -8103.054076 | -8136.030441 | 3.611085 | 3.512488 | -1711.000000 |

Negative differences indicate lower C2 values. Deadline misses use percentage-point differences. Relative changes are provided only for positive local-latency/inference-service denominators; no relative miss or queue percentage is used.

## Paired direction

| K | C2 lower miss | C2 lower queue wait | C2 lower local latency |
|---:|---:|---:|---:|
| 5 | 5/5 | 5/5 | 3/5 |
| 6 | 5/5 | 5/5 | 5/5 |
| 7 | 5/5 | 5/5 | 5/5 |

| K | Run | Miss C2−C1 pp | Queue wait C2−C1 ms | Local mean C2−C1 ms |
|---:|---|---:|---:|---:|
| 5 | run01 | -17.977778 | -3.077010 | -2.522395 |
| 5 | run02 | -14.122222 | -3.480013 | -0.614320 |
| 5 | run03 | -10.600000 | -2.738366 | 0.387023 |
| 5 | run04 | -9.888889 | -3.274625 | -0.409008 |
| 5 | run05 | -10.655556 | -2.784740 | 0.131348 |
| 6 | run01 | -6.000000 | -19.092183 | -15.742987 |
| 6 | run02 | -32.324074 | -82.367050 | -80.165402 |
| 6 | run03 | -4.175926 | -12.366960 | -8.782421 |
| 6 | run04 | -53.925926 | -139.136084 | -138.143924 |
| 6 | run05 | -5.546296 | -14.108805 | -10.951649 |
| 7 | run01 | -20.119048 | -4877.015257 | -4872.652105 |
| 7 | run02 | -48.611111 | -4595.859662 | -4592.957710 |
| 7 | run03 | -48.039683 | -4842.200854 | -4839.523306 |
| 7 | run04 | -5.904762 | -5413.795636 | -5409.545540 |
| 7 | run05 | -4.150794 | -4723.999571 | -4719.119840 |

## Old C1 vs new control C1: sensitivity reference

The following values are read from the actual frozen CSV/run validations. This is a historical implementation-sensitivity comparison, not the primary concurrency comparison. It changes transfer/synchronization implementation and was measured at a different time; it cannot isolate which internal change caused a difference. Never use old C1→new C2 as a concurrency effect.

| K | Metric | Old C1 mean | New C1 mean | New−old | Unit |
|---:|---|---:|---:|---:|---|
| 5 | local_latency_mean_ms | 25.730043 | 26.588797 | 0.858754 | ms |
| 5 | local_latency_p95_ms | 33.822362 | 35.792459 | 1.970097 | ms |
| 5 | local_latency_p99_ms | 104.084341 | 116.442573 | 12.358232 | ms |
| 5 | deadline_miss_pct | 4.906667 | 13.975556 | 9.068889 | percentage points |
| 5 | start_lag_mean_ms | 0.967965 | 0.897097 | -0.070867 | ms |
| 5 | front_end_mean_ms | 11.162738 | 11.323309 | 0.160571 | ms |
| 5 | queue_wait_mean_ms | 8.975442 | 9.530695 | 0.555253 | ms |
| 5 | queue_wait_p95_ms | 16.237647 | 16.709000 | 0.471352 | ms |
| 5 | inference_mean_ms | 4.623897 | 4.837695 | 0.213798 | ms |
| 5 | inference_p95_ms | 5.083022 | 5.805787 | 0.722765 | ms |
| 5 | peak_waiting_queue | 33.600000 | 33.400000 | -0.200000 | frames |
| 5 | time_weighted_waiting_queue | 1.349739 | 1.432908 | 0.083169 | frames |
| 6 | local_latency_mean_ms | 43.620811 | 81.681730 | 38.060920 | ms |
| 6 | local_latency_p95_ms | 109.433303 | 195.452730 | 86.019427 | ms |
| 6 | local_latency_p99_ms | 221.504810 | 253.193261 | 31.688451 | ms |
| 6 | deadline_miss_pct | 35.048148 | 53.055556 | 18.007407 | percentage points |
| 6 | start_lag_mean_ms | 1.022426 | 1.059501 | 0.037075 | ms |
| 6 | front_end_mean_ms | 11.917329 | 12.329110 | 0.411781 | ms |
| 6 | queue_wait_mean_ms | 25.777952 | 63.076410 | 37.298457 | ms |
| 6 | queue_wait_p95_ms | 87.654159 | 172.290271 | 84.636112 | ms |
| 6 | inference_mean_ms | 4.903103 | 5.216710 | 0.313607 | ms |
| 6 | inference_p95_ms | 6.775114 | 7.739450 | 0.964336 | ms |
| 6 | peak_waiting_queue | 44.600000 | 47.400000 | 2.800000 | frames |
| 6 | time_weighted_waiting_queue | 4.652781 | 11.386668 | 6.733887 | frames |
| 7 | local_latency_mean_ms | 4294.063545 | 5002.334505 | 708.270960 | ms |
| 7 | local_latency_p95_ms | 7213.383529 | 8335.646568 | 1122.263039 | ms |
| 7 | local_latency_p99_ms | 7337.789498 | 8419.830033 | 1082.040534 | ms |
| 7 | deadline_miss_pct | 100.000000 | 100.000000 | 0.000000 | percentage points |
| 7 | start_lag_mean_ms | 0.989373 | 1.097032 | 0.107658 | ms |
| 7 | front_end_mean_ms | 13.446460 | 13.468620 | 0.022160 | ms |
| 7 | queue_wait_mean_ms | 4274.372474 | 4982.414996 | 708.042523 | ms |
| 7 | queue_wait_p95_ms | 7194.645764 | 8316.802916 | 1122.157153 | ms |
| 7 | inference_mean_ms | 5.255238 | 5.353857 | 0.098619 | ms |
| 7 | inference_p95_ms | 8.581680 | 8.468056 | -0.113624 | ms |
| 7 | peak_waiting_queue | 1546.400000 | 1771.800000 | 225.400000 | frames |
| 7 | time_weighted_waiting_queue | 813.012745 | 929.828783 | 116.816037 | frames |

## Prior trtexec context (separate harness)

infStreams=1: 240.953000 qps, infStreams=2: 244.517600 qps, infStreams=4: 243.597600 qps.
That probe showed a weak C2 throughput gain and no additional C4 gain. The installed trtexec warned that multi-stream latencies may be inaccurate and recommended throughput. Those values are not equated with application inference service and did not predetermine the application result.

## Integrity

Every run passed exact arrivals/samples/preprocessing/completions/CSV counts, stream IDs 0..1799 exactly once, phase alignment, a≤b≤r≤s≤c, exact ns decomposition, CSV/raw equality, queue event replay/integral, normal source EOS, waiting=0/active=0 after drain, resource ownership and concurrency bounds. Independent post-run replay rechecked all 30 runs. See formal_integrity_report.json and analysis_revalidation.json.



## Research finding: MIXED (CASE A supported + CASE D sensitivity)

The same-path primary comparison supports persistence of deadline degradation with
C=2. At K6, C2 has **32.661111% misses** (sample SD 0.346301 pp, run range
32.287037–33.083333%) and **9.662193 ms mean waiting** (SD 0.468223 ms).
Local p95 is 38.071997 ms, above the candidate 1/30-second deadline. This occurs
with two independent execution contexts and nonblocking streams, and observed
concurrent submitted requests in every run. Thus a single inference worker alone
does not explain away the observed K6 deadline phenomenon in this configuration.
This is evidence about this phase-aligned B=1 application workload on Thor, not
an intrinsic or universal GPU problem.

Concurrency nevertheless changes the magnitude substantially. At K6, misses fall
53.055556→32.661111% (−20.394444 pp), queue mean 63.076410→9.662193 ms,
and local mean 81.681730→30.924454 ms. At K7, local mean falls
5002.334505→115.574804 ms and queue mean 4982.414996→91.840800 ms, while
74.634921% misses remain (run range 51.388889–95.849206%). The K7 multi-second
backlog of C1 cannot be presented as insensitive to concurrency. A clean rightward
shift eliminating the K6 deadline knee is not demonstrated by these tested loads.

Per-request host inference service **increases** with C2: means at K5/K6/K7 are
4.837695→7.693725, 5.216710→8.545962, and 5.353857→8.964942 ms. Lower waiting
and longer overlapping service coexist. Service intervals are measured at the
host/application boundary, not isolated kernel times. Actual GPU kernel overlap
was not directly measured.

All K values show lower C2 miss and queue mean in 5/5 run-index pairs. K5 local
mean improves in 3/5 pairs, whereas K6/K7 improve in 5/5. Effect size varies:
C1-K6 local mean has SD 56.579155 ms and range 40.519240–168.287618 ms; its
larger values occur in rounds 2 and 4 (C2-before-C1 for that K). This is a descriptive
order association from only five repetitions, not evidence of a causal carryover
mechanism. The prescribed ordering and no-cooldown protocol were preserved.
No outlier was excluded and no statistical-significance claim is made.

The historical old-C1 reference is not implementation-equivalent in these results.
At K5, mean local latency changes only +0.858754 ms, but misses increase
4.906667→13.975556% (+9.068889 pp), p95 +1.970097 ms, queue mean +0.555253 ms,
and inference mean +0.213798 ms. At K6, local mean is +38.060920 ms, p95
+86.019427 ms, misses +18.007407 pp, queue mean +37.298457 ms and inference
mean +0.313607 ms; the new-run variance is also much larger. At K7, local mean
and queue mean rise by about 708 ms while misses remain 100%, and inference
mean changes +0.098619 ms. These are measured sensitivity differences across
implementation and historical measurement time; this study does not isolate
which transfer/synchronization change caused them. Old C1→new C2 must not be
used as the concurrency effect.

**Local motivation verdict: 조건부 수정 필요.** Retain the scoped observation that
candidate-deadline degradation persists under this C2 execution configuration.
Use the same-path C1/C2 comparison for concurrency claims, explicitly acknowledge
the large K7 backlog improvement and old/new C1 sensitivity, and constrain claims
to the tested workload, hardware, transfer/synchronization path and C values.
The data do not support an intrinsic GPU limitation claim or measured physical
kernel overlap.

**Next step: YES, RT-DETR graph split feasibility may be investigated next.**
The requested concurrency control and integrity gate are complete. First align
motivation wording with this scoped result; a later feasibility study still needs
to establish whether partitioning/offloading is feasible and beneficial. No graph
split, server/network/MEC experiment, scheduler change, rebuild, new figure, commit
or push was performed in this task.

## Preservation and reproducibility

The initial 955-file manifest includes all historical result artifacts and sources.
All **930 existing result files** are unchanged in SHA256, size and mtime_ns:
445 local_latency_breakdown files, 275 local_realtime_baseline files, and 210 prior
local_inference_concurrency artifacts (including probe and smoke). No result file
was added to or removed from the protected historical sets. Both unrelated local
files are unchanged. Four authorized concurrency source files were generalized,
with original bytes and mtimes archived in formal_control_preparation/source_before.
Previous smoke metadata hashes match those archived pre-edit sources.

The formal_integrity_report.json global checks confirm 30/30 runs, 324,000 frames,
zero ordering/decomposition/duplicate/missing/negative-queue violations, normal EOS,
queue/active drain, source hashes matching the four passing generalized smokes,
identical engine hashes and K-specific video mappings, and MAXN/unlocked-DVFS
before and after all runs. Actual command/exit timestamps confirm the specified
order and that the preceding independent artifact validation finished before the
next launch. Formal execution spans 2026-09-11 03:20:20–03:52:49 UTC.
