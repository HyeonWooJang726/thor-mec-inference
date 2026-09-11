# C2 versus C4 full-source targeted validation

**PASS: 18/18 targeted runs, 194,400 frames. Both preceding full-source gates passed (18,000 additional frames, excluded). Fixed C: UNDECIDED — CASE C, load-dependent deadline trade-off persists.**

## Scope and execution

Actual complete 60-second/1800-frame Warehouse_027 videos at phase-aligned 30 FPS per stream. C={2,4}, K={5,6,7}, three repetitions, prescribed forward/reverse/third-round order. No warm-up, sample exclusion, frame drops, retries, substitutions or deliberate cooldown. Each accepted frame was drained; each child exited, cleaned up and was independently validated before the next run. This is targeted validation, not the final K1..7 canonical 35-run campaign.

Engine `models/rtdetr_warehouse_v1.0.2.fp16.b1.canonical.engine`, SHA256 `9d01cdb2838bb1b9db58c246e6111a5dccee63bb937b673fb48caf43e53bc5ff`; B1; input shape 1x3x640x640. Historical audited video mapping Camera_0000..Camera_0006 was checked for every active stream. MAXN, DVFS unlocked, jetson_clocks OFF, CUDA Graph OFF, engine and source hashes invariant. TensorRT runtime reports version 10.16.2.10.

C controls only worker/context/nonblocking submission-stream/device-I/O/pinned-staging pool size. Shared engine weights, async H2D, execute_async_v3, async D2H and own-stream synchronization are identical. No per-frame cudaDeviceSynchronize. The fixed engine reports num_aux_streams=2 in both configurations; this is separate from C. All configured workers were used and max active inference was 2/4 respectively. Service/submitted-before-sync host overlap is concurrent outstanding inference evidence; **GPU kernel overlap was not directly measured**.

## Full-source termination and integrity

The original audited full-source decode pipeline is used with no bounded identity limiter. Success requires every natural source EOS observation as well as exact acquisition/completion, IDs, integer timing/decomposition, zero waiting/active drain, successful source/inference/scheduler joins and confirmed NULL shutdown. EOS is never synthesized from counts. On successful runs, lifecycle replay verified actual EOS and worker joins preceded pipeline shutdown.

Gates: C2-K5 and C4-K5 each 9,000 frames, EOS 5/5, all checks PASS. Primary: 18 runs, 194,400 frames (97,200 per C), 108/108 source EOS observations. Including gates: 212,400 frames and 118/118 source EOS observations. Missing EOS, watchdog, GStreamer/worker/runtime errors, nonzero exits, duplicate/missing frames, ordering/decomposition/queue/drain violations: zero. Gate data and all prior campaign data are excluded from primary statistics.

59 regression tests passed; the existing test-fixture captured OUTPUT default was rebound only in memory to its temporary root. Existing code was unchanged. Arrival, front-end acquisition loop, inference worker and metric implementation remain identical to the validated generalized runtime; intentional full-source topology/termination changes are common to C2/C4. See runtime_contract.md, runtime_audit.json and regression.log.

Raw a/b/r/s/c integers remain canonical. Candidate deadline is exactly `(c-a)*30 > 1000000000`, not a final application SLA. Waiting queue is r<=t<s and excludes active inference. All serialized CSV durations were replayed against raw timestamps.

## Three-run statistics

Each cell is **mean ± sample SD [min,max]** of three run-level statistics. Latency values are ms; deadline miss is %. These are not pooled-frame quantiles. ck_summary.csv also preserves run01/run02/run03 and the median of the three run statistics. Sample size is three; no strong statistical significance or population-superiority claim is made.

| C | K | Local mean | Local p95 | Local p99 | Deadline miss % | Queue mean | Queue p95 | Inference mean | Inference p95 |
|---:|---:|---|---|---|---|---|---|---|---|
| 2 | 5 | 26.4139 ± 0.2049 [26.2865,26.6503] | 32.2002 ± 0.0527 [32.1621,32.2603] | 79.6054 ± 19.2286 [66.7219,101.7076] | 1.6111 ± 0.0778 [1.5556,1.7000] | 6.7369 ± 0.0775 [6.6871,6.8261] | 15.2442 ± 0.1085 [15.1733,15.3691] | 7.7066 ± 0.0177 [7.6869,7.7211] | 9.0661 ± 0.0359 [9.0408,9.1072] |
| 2 | 6 | 30.9123 ± 1.4156 [29.5202,32.3502] | 38.9931 ± 1.6355 [37.9254,40.8760] | 157.3571 ± 40.2503 [114.5973,194.5101] | 32.2901 ± 0.5720 [31.6296,32.6204] | 9.3662 ± 0.6881 [8.6052,9.9446] | 16.1172 ± 0.1070 [16.0385,16.2391] | 8.5566 ± 0.0574 [8.5191,8.6227] | 10.0564 ± 0.5188 [9.7498,10.6554] |
| 2 | 7 | 163.6664 ± 89.8081 [62.5720,234.2246] | 259.2254 ± 12.1039 [248.2010,272.1774] | 280.7943 ± 12.6955 [266.8552,291.6948] | 84.5079 ± 26.8330 [53.5238,100.0000] | 139.3322 ± 88.2705 [40.1437,209.2469] | 231.9823 ± 12.9851 [219.9294,245.7327] | 9.1581 ± 0.4777 [8.6067,9.4484] | 12.4822 ± 1.5874 [10.6601,13.5655] |
| 4 | 5 | 29.9855 ± 0.7221 [29.4813,30.8127] | 33.3460 ± 0.2017 [33.2120,33.5780] | 65.6199 ± 47.7580 [37.9942,120.7660] | 4.9148 ± 0.6046 [4.5222,5.6111] | 3.3963 ± 0.2801 [3.1779,3.7121] | 15.0204 ± 0.2721 [14.8387,15.3332] | 14.2796 ± 0.0754 [14.2278,14.3660] | 18.2881 ± 0.0851 [18.2008,18.3707] |
| 4 | 6 | 33.5718 ± 0.2370 [33.3082,33.7671] | 38.9019 ± 0.0786 [38.8289,38.9850] | 155.3651 ± 14.7555 [140.3338,169.8284] | 33.7006 ± 0.1767 [33.5000,33.8333] | 5.1513 ± 0.5820 [4.7896,5.8227] | 15.6259 ± 0.2012 [15.4150,15.8159] | 14.2606 ± 0.0651 [14.1856,14.3013] | 18.3734 ± 0.0630 [18.3101,18.4361] |
| 4 | 7 | 41.2866 ± 1.9477 [39.0380,42.4456] | 71.9133 ± 22.1556 [46.8964,89.0571] | 238.0379 ± 34.2214 [199.5975,265.1864] | 47.3836 ± 0.6910 [46.5873,47.8254] | 10.5433 ± 1.7831 [8.6432,12.1803] | 36.2734 ± 17.2448 [16.7034,49.2430] | 15.2889 ± 0.0271 [15.2601,15.3139] | 19.0888 ± 0.0759 [19.0012,19.1359] |

## Individual run statistics — none excluded

| C | K | Run | Local mean | p95 | p99 | Miss % | Queue mean | Queue p95 | Inference mean | Inference p95 |
|---:|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 2 | 5 | run01 | 26.6503 | 32.1782 | 101.7076 | 1.7000 | 6.8261 | 15.1733 | 7.6869 | 9.0408 |
| 2 | 5 | run02 | 26.3048 | 32.1621 | 70.3867 | 1.5556 | 6.6871 | 15.1901 | 7.7117 | 9.1072 |
| 2 | 5 | run03 | 26.2865 | 32.2603 | 66.7219 | 1.5778 | 6.6973 | 15.3691 | 7.7211 | 9.0504 |
| 4 | 5 | run01 | 30.8127 | 33.5780 | 120.7660 | 5.6111 | 3.7121 | 15.3332 | 14.3660 | 18.3707 |
| 4 | 5 | run02 | 29.4813 | 33.2120 | 37.9942 | 4.5222 | 3.1779 | 14.8893 | 14.2278 | 18.2008 |
| 4 | 5 | run03 | 29.6624 | 33.2480 | 38.0994 | 4.6111 | 3.2988 | 14.8387 | 14.2449 | 18.2928 |
| 2 | 6 | run01 | 32.3502 | 40.8760 | 194.5101 | 32.6204 | 9.9446 | 16.0385 | 8.6227 | 10.6554 |
| 2 | 6 | run02 | 29.5202 | 37.9254 | 114.5973 | 31.6296 | 8.6052 | 16.0741 | 8.5191 | 9.7641 |
| 2 | 6 | run03 | 30.8664 | 38.1779 | 162.9638 | 32.6204 | 9.5486 | 16.2391 | 8.5281 | 9.7498 |
| 4 | 6 | run01 | 33.3082 | 38.8917 | 140.3338 | 33.8333 | 4.8417 | 15.6466 | 14.3013 | 18.3739 |
| 4 | 6 | run02 | 33.6403 | 38.9850 | 155.9333 | 33.5000 | 5.8227 | 15.8159 | 14.2951 | 18.4361 |
| 4 | 6 | run03 | 33.7671 | 38.8289 | 169.8284 | 33.7685 | 4.7896 | 15.4150 | 14.1856 | 18.3101 |
| 2 | 7 | run01 | 62.5720 | 248.2010 | 266.8552 | 53.5238 | 40.1437 | 219.9294 | 8.6067 | 10.6601 |
| 2 | 7 | run02 | 234.2246 | 272.1774 | 283.8330 | 100.0000 | 209.2469 | 245.7327 | 9.4484 | 13.2211 |
| 2 | 7 | run03 | 194.2027 | 257.2978 | 291.6948 | 100.0000 | 168.6059 | 230.2847 | 9.4191 | 13.5655 |
| 4 | 7 | run01 | 42.3764 | 79.7865 | 265.1864 | 47.7381 | 10.8064 | 42.8739 | 15.2925 | 19.1292 |
| 4 | 7 | run02 | 42.4456 | 89.0571 | 249.3296 | 47.8254 | 12.1803 | 49.2430 | 15.3139 | 19.1359 |
| 4 | 7 | run03 | 39.0380 | 46.8964 | 199.5975 | 46.5873 | 8.6432 | 16.7034 | 15.2601 | 19.0012 |

## Paired direction and mean differences

Δ = C4 minus C2. Miss delta is percentage points; all other deltas are ms. Repetition-index pairing is descriptive; the runs were sequential and are not a paired randomized trial. Full per-pair deltas are in paired_comparison.csv.

| K | Miss Δ pp | Local mean Δ | p95 Δ | p99 Δ | Queue mean Δ | Queue p95 Δ | Inference mean Δ | Inference p95 Δ | C4 improved miss / p95 / queue mean |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| 5 | +3.3037 | +3.5716 | +1.1458 | -13.9855 | -3.3406 | -0.2238 | +6.5730 | +9.2220 | 0/3 / 0/3 / 3/3 |
| 6 | +1.4105 | +2.6595 | -0.0912 | -1.9919 | -4.2148 | -0.4914 | +5.7040 | +8.3169 | 0/3 / 1/3 / 3/3 |
| 7 | -37.1243 | -122.3798 | -187.3121 | -42.7565 | -128.7889 | -195.7089 | +6.1308 | +6.6065 | 3/3 / 3/3 / 3/3 |

## K-specific findings

**K5:** C2 has lower deadline miss, local mean and p95 in all three pairs. C4 raises mean miss from 1.6111% to 4.9148% (+3.3037 pp), mean service from 7.7066 to 14.2796 ms, and mean local p95 from 32.2002 to 33.3460 ms. Mean waiting falls from 6.7369 to 3.3963 ms. Local p99 is mixed: C4 improves two of three pairs and has lower mean p99, but much greater observed p99 variation (38.0–120.8 ms). A better p99 mean does not erase consistently worse miss/p95.

**K6:** C2 has lower deadline miss and local mean in all three pairs. C4 mean miss is higher by 1.4105 pp despite a 4.2148-ms reduction in mean queue wait; mean service rises by 5.7040 ms. Average p95 differs by only −0.0912 ms and average p99 by −1.9919 ms, but C4 improves each tail in only one of three pairs. These mean tail differences do not show repeatable C4 tail improvement.

K6 miss values: C2 32.6204 / 31.6296 / 32.6204%, SD 0.5720 pp, range 31.6296–32.6204%; C4 33.8333 / 33.5000 / 33.7685%, SD 0.1767 pp, range 33.5000–33.8333%. Tail variation remains visible: C2 p99 194.5101 / 114.5973 / 162.9638 ms (SD 40.2503), C4 p99 140.3338 / 155.9333 / 169.8284 ms (SD 14.7555). No run was excluded or repeated. Narrow observed miss ranges in these three runs are not a population-level variability guarantee.

**K7:** C4 improves deadline miss, local mean/p95/p99 and queue mean/p95 in all three pairs. Mean miss drops from 84.5079% to 47.3836% (−37.1243 pp), p95 from 259.2254 to 71.9133 ms, and mean waiting from 139.3322 to 10.5433 ms. Mean inference service increases from 9.1581 to 15.2889 ms. C2 miss is highly variable across runs: 53.5238 / 100 / 100%, SD 26.8330 pp. C4 miss is 47.7381 / 47.8254 / 46.5873%, SD 0.6910 pp; its p95 still varies from 46.8964 to 89.0571 ms. Both configurations retain substantial K7 candidate-deadline misses. Finite-run drain success alone does not establish indefinitely sustainable operation.

## Fixed concurrency decision

**CASE C — UNDECIDED.** The load-dependent trade-off persists in full-source validation: C2 favors K5/K6 deadline miss and lower resource/service cost; C4 favors K7 deadlines, tails and queueing. C4 is not selected merely because its queue is smaller or K7 backlog is reduced. C2 is not selected by ignoring the repeated K7 benefit. The workload weighting and acceptable deadline-miss degradation across loads have not been specified; choosing one C from these conflicting objectives would impose an unstated preference.

Conditional candidates: retain C2 when K5/K6 deadline QoS and lower resource cost take priority; retain C4 when supporting K7 with substantially reduced degradation justifies the observed K5/K6 miss cost. The next decision should state the intended operating load range and acceptable miss budget before commissioning the final campaign. Repeating runs without that decision rule need not resolve this trade-off. No additional experiment was automatically run.

**Canonical 35-run ready: NO.** The full-source runtime/termination gate is valid, but a single fixed C is not selected. Accordingly no canonical_runtime_configuration.md or selected-C candidate configuration was created. The current executable is deliberately restricted to the approved K5/K6/K7 targeted matrix; the future K1..7 canonical runner must be prepared separately while retaining natural EOS. No final 35-run was executed.

## Relationship to earlier campaigns

The trtexec C1..7 probe is engine-only aggregate throughput context, not an application deadline measurement. Its C4/C7 throughput behavior is not used to override these QoS measurements. The 30-second application campaign showed the same qualitative load trade-off: C2 lower K5/K6 miss, C4 lower K7 miss. This 60-second campaign independently confirms that direction in all three pairs for each K, with different absolute values and observed variability. Neither campaign, old C1/C2 control, nor either gate is pooled with this primary dataset. C7 was not rerun.

## Artifact protection and limits

PASS: all 3,601 pre-existing protected artifacts retain identical SHA256, size and mtime_ns; no missing/changed files or unexpected additions outside the new root. Old Local, formal C1/C2 control, trtexec probes, failed screening, screening v2, bounded contract v2, EOS diagnostics and unrelated scripts remain unchanged. See artifact_integrity_report.json and before/after manifests.

All raw per-frame records, exact commands, stdout/stderr, exits, environments, resource ownership, lifecycle and independent checks are retained. No Figure was generated. Figure 1–4 should be regenerated from the future completed canonical 35-run dataset. No graph/network/server/scheduler experiment, engine rebuild, batch/clock/CUDA Graph change, commit, push, reset or clean was performed.
