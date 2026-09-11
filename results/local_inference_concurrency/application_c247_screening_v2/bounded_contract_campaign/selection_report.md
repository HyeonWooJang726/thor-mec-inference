# Application C2/C4/C7 screening v2: bounded termination contract

**Completion: PASS, 18/18 valid runs and 97,200 exact frames; 0 failed, 0 retried, 0 watchdog. Fixed C recommendation: UNDECIDED (retain C2 and C4 as candidates).**

This fresh campaign lives in `application_c247_screening_v2/bounded_contract_campaign/`. The eight existing blocked/NOT_RUN reports in the parent directory are preserved unchanged. The original incomplete campaign is historical evidence only. Neither its six valid runs nor the nine termination-stress runs are pooled here.

## Termination and root-cause status

The original Camera_0004 missing bus-EOS direct root cause remains **UNKNOWN**. This work separates the explicitly requested bounded contract; it does not establish the historical delivery mechanism. EOS is updated only from a genuine GStreamer bus message. `bounded_complete` is a separate post-cleanup validation state and never writes EOS.

All 27 new actual runs (nine stress plus 18 screening) passed exact samples/IDs, all accepted-frame completion, raw integer timing/decomposition, queue/active drain, source normal return/join, all worker cleanup and actual pipeline NULL confirmation, with no GStreamer/worker/runtime errors or watchdog. The full-source 1800-frame runners remain unchanged and still require actual EOS. The new runner rejects non-900-frame execution.

Bus EOS observation is independent from bounded correctness. Stress: one missing observation, C2-K7-run01 stream3. Screening: four missing observations, listed below. These mean not observed before bounded cleanup; they do not prove the historical missing-EOS mechanism was reproduced.

| Scope | C | K | Run | Missing bus EOS stream IDs | Bounded contract |
|---|---:|---:|---|---|---|
| stress | 2 | 7 | run01 | [3] | PASS |
| screening | 7 | 7 | run01 | [5] | PASS |
| screening | 4 | 7 | run02 | [0] | PASS |
| screening | 4 | 6 | run02 | [5] | PASS |
| screening | 2 | 6 | run02 | [1] | PASS |

See [termination contract](../../bounded_termination_contract_v2/termination_contract.md), [stress report](../../bounded_termination_contract_v2/targeted_stress_report.md), and [diff audit](../../bounded_termination_contract_v2/performance_freeze_audit.json).

## Fixed conditions and integrity

Engine `models/rtdetr_warehouse_v1.0.2.fp16.b1.canonical.engine`, SHA256 `9d01cdb2838bb1b9db58c246e6111a5dccee63bb937b673fb48caf43e53bc5ff`. One shared engine, C independent workers/contexts/nonblocking streams/device I/O and pinned staging sets. All configured workers were used; maximum active inferences equaled configured C in these runs. Host service/submitted-before-sync overlap is evidence of concurrent outstanding inference only. **GPU kernel overlap was not directly measured.**

Actual fixed warehouse video mapping stream0..K-1 to Camera_0000..0006 was checked against historical audited metadata. B1, 30 FPS/stream, phase-aligned arrivals, 900 frames/stream, offered duration 30 seconds, complete drain, no drops/warm-up/exclusion/deliberate cooldown. MAXN, DVFS unlocked, jetson_clocks OFF, CUDA Graph OFF, engine/source hashes unchanged. Wall-clock time includes setup, workload, cleanup and artifact writing; per-run values are preserved separately from the 30-second offered duration.

Run order was the prescribed forward repetition followed by reverse repetition, with each run exited, cleaned up and validated before the next. Integer `a<=b<=r<=s<=c`, exact decomposition and candidate miss condition `(c-a)*30 > 1000000000` were replayed from disk. This 1/30-second candidate deadline is not a final application SLA.

51 CPU tests passed (27 existing Local/concurrency, seven previous EOS evidence, 17 new tests). The known existing test-fixture default-argument issue was isolated in memory without source edits; see regression_report.md. Performance freeze: pipeline construction, arrival, inference and statistics AST identical; entire front-end acquisition loop AST identical; TensorRT/resource validation byte identical. Only source completion/cleanup/validation/diagnostic paths changed. No assertion of identical wall-clock performance under unlocked DVFS is made.

## Primary results: both runs and their mean

All latency values are ms; miss values are %. Every cell is **run01 / run02 / arithmetic mean of the two run statistics**. No frames are pooled. CSV also preserves min/max and sample SD explicitly marked n=2. This is screening, not a final paper baseline; no statistical significance or population superiority is claimed.

| C | K | Local mean | Local p95 | Local p99 | Miss % | Queue mean | Queue p95 | Inference mean | Inference p95 |
|---:|---:|---|---|---|---|---|---|---|---|
| 2 | 5 | 27.1999 / 27.2994 / 27.2497 | 32.3503 / 32.2965 / 32.3234 | 133.2088 / 137.8854 / 135.5471 | 2.5778 / 2.4444 / 2.5111 | 7.2628 / 7.1522 / 7.2075 | 15.4494 / 15.1719 / 15.3107 | 7.7601 / 7.7139 / 7.7370 | 9.1050 / 9.1205 / 9.1127 |
| 2 | 6 | 33.2525 / 34.6105 / 33.9315 | 39.4150 / 58.0459 / 48.7305 | 203.4610 / 225.6725 / 214.5667 | 33.5556 / 34.1667 / 33.8611 | 11.5259 / 12.5694 / 12.0476 | 16.9038 / 33.3319 / 25.1179 | 8.5601 / 8.5784 / 8.5693 | 9.8854 / 9.9762 / 9.9308 |
| 2 | 7 | 126.5258 / 232.3485 / 179.4371 | 262.6009 / 261.5267 / 262.0638 | 275.5344 / 274.4635 / 274.9989 | 74.3968 / 100.0000 / 87.1984 | 102.6687 / 206.6123 / 154.6405 | 238.0970 / 236.7307 / 237.4138 | 8.9756 / 9.4533 / 9.2144 | 11.9824 / 13.6433 / 12.8129 |
| 4 | 5 | 30.8261 / 30.2750 / 30.5505 | 33.7236 / 32.7600 / 33.2418 | 143.2811 / 152.1510 / 147.7160 | 6.0222 / 3.4000 / 4.7111 | 3.5807 / 3.4850 / 3.5329 | 15.1493 / 14.0682 / 14.6088 | 14.2835 / 13.9156 / 14.0996 | 18.2616 / 17.6852 / 17.9734 |
| 4 | 6 | 35.1217 / 39.5613 / 37.3415 | 39.4441 / 41.2747 / 40.3594 | 198.7673 / 319.2020 / 258.9847 | 34.7593 / 35.1111 / 34.9352 | 6.2931 / 7.8941 / 7.0936 | 16.3935 / 17.1986 / 16.7960 | 14.3739 / 14.1847 / 14.2793 | 18.5084 / 18.1600 / 18.3342 |
| 4 | 7 | 44.1284 / 44.2592 / 44.1938 | 131.0859 / 118.7501 / 124.9180 | 249.2086 / 233.5202 / 241.3644 | 47.8730 / 51.1746 / 49.5238 | 12.4044 / 12.6511 / 12.5278 | 79.0059 / 70.0974 / 74.5517 | 14.9599 / 15.2428 / 15.1013 | 18.7856 / 19.1559 / 18.9708 |
| 7 | 5 | 40.9343 / 40.6164 / 40.7753 | 40.8918 / 37.2544 / 39.0731 | 338.2062 / 356.1473 / 347.1768 | 41.3333 / 20.3556 / 30.8444 | 0.5054 / 0.5272 / 0.5163 | 0.8484 / 0.8555 / 0.8519 | 18.4961 / 19.9815 / 19.2388 | 25.2778 / 23.9804 / 24.6291 |
| 7 | 6 | 55.6076 / 61.3760 / 58.4918 | 215.6922 / 281.9818 / 248.8370 | 474.9516 / 527.1114 / 501.0315 | 84.7407 / 80.2593 / 82.5000 | 0.7615 / 0.6340 / 0.6978 | 0.9381 / 1.1744 / 1.0563 | 23.5242 / 22.5932 / 23.0587 | 27.0680 / 27.6748 / 27.3714 |
| 7 | 7 | 109.3932 / 104.2141 / 106.8036 | 512.6140 / 502.9980 / 507.8060 | 626.4295 / 629.0629 / 627.7462 | 96.8095 / 97.0000 / 96.9048 | 0.8632 / 1.3388 / 1.1010 | 1.4152 / 1.5555 / 1.4853 | 26.8385 / 26.9033 / 26.8709 | 32.5333 / 32.5584 / 32.5458 |

## C-pair differences and repetition direction

Δ = tested C minus reference C; negative latency/miss delta favors tested C. Deadline differences are percentage points. Counts show how many of the two repetition-index comparisons favor tested C. These sequential, noncontemporaneous pairs are not a paired randomized trial.

| K | Tested vs reference | Miss Δ pp | Miss improved | Local p95 Δ ms | Queue mean Δ ms | Inference mean Δ ms |
|---:|---|---:|---:|---:|---:|---:|
| 5 | C4 vs C2 | +2.2000 | 0/2 | +0.9184 | -3.6746 | +6.3626 |
| 5 | C7 vs C4 | +26.1333 | 0/2 | +5.8313 | -3.0166 | +5.1393 |
| 5 | C7 vs C2 | +28.3333 | 0/2 | +6.7497 | -6.6912 | +11.5018 |
| 6 | C4 vs C2 | +1.0741 | 0/2 | -8.3711 | -4.9541 | +5.7100 |
| 6 | C7 vs C4 | +47.5648 | 0/2 | +208.4776 | -6.3958 | +8.7794 |
| 6 | C7 vs C2 | +48.6389 | 0/2 | +200.1066 | -11.3499 | +14.4894 |
| 7 | C4 vs C2 | -37.6746 | 2/2 | -137.1458 | -142.1127 | +5.8869 |
| 7 | C7 vs C4 | +47.3810 | 0/2 | +382.8880 | -11.4268 | +11.7695 |
| 7 | C7 vs C2 | +9.7063 | 1/2 | +245.7422 | -153.5395 | +17.6564 |

Complete per-repetition deltas for local mean/p95/p99, queue mean/p95 and inference mean/p95 are in c_pair_comparison.csv.

## Selection interpretation

**K5:** C2 has lower miss and local mean/p95/p99 in both repetitions than C4. C4 reduces mean waiting, but inference service rises from 7.7370 to 14.0996 ms and mean miss rises by 2.2000 pp. C7 further reduces waiting but increases mean miss to 30.8444%.

**K6:** C2 miss is lower than C4 in both repetitions (33.8611% versus 34.9352% mean). C4 reduces queue wait, while inference service rises from 8.5693 to 14.2793 ms. Tails are mixed: C4 mean p95 is lower, but p99 is higher on average; per-repetition direction is not uniform. C7 miss reaches 82.5000% despite mean waiting below 1 ms.

**K7:** C4 improves miss, queue wait, local mean/p95/p99 relative to C2 in both repetitions. Miss falls from 87.1984% to 49.5238% (−37.6746 pp), local p95 from 262.0638 to 124.9180 ms, and mean queue wait from 154.6405 to 12.5278 ms. Inference service still rises from 9.2144 to 15.1013 ms. C2 K7 mean miss varies from 74.3968% to 100%; two repetitions are insufficient to characterize its variability reliably.

**C7 versus C4:** C7 worsens miss and local p95/p99 at every tested K in both repetitions. Mean inference service becomes 19.2388 / 23.0587 / 26.8709 ms at K5/K6/K7, while queue means fall to 0.5163 / 0.6978 / 1.1010 ms. The extra queue reduction does not compensate for the longer service and application tails. These are application service intervals, not pure GPU compute times.

**Recommended fixed C: UNDECIDED.** C2 is favored for K5/K6 deadline miss and lower resource/service cost, whereas C4 is favored for K7 deadline/tail/backlog. Selecting one fixed C across K1..7 would require an unstated weighting of those loads or more validation. The n=2 campaign does not justify hiding that trade-off. C7 is not recommended for the next comparison.

**Additional validation: YES, C2 versus C4.** Next task: a targeted 60-second comparison at K5/K6/K7, with the full-source natural-EOS contract retained and an explicit priority for the intended load region. No additional run was automatically performed here.

**TensorRT-only versus application: PARTIAL.** The C4 engine-level throughput advantage corresponds to an application benefit at K7, but it does not consistently improve K5/K6 deadlines. C7 micro-probe throughput does not translate into better application QoS. The probes are separate campaigns and are not pooled. Engine throughput alone does not establish application deadline/queue behavior.

**Canonical 35-run ready: NO.** Termination reliability and screening integrity gates passed, but fixed C remains undecided and the prospective 60-second full-source implementation must retain/validate natural EOS. No K1..7 ×5×60-second campaign or figure was produced. Once a future canonical campaign completes, the requested Figure 1–4 regeneration should use that new final dataset.

## Protected artifacts

PASS: all 2,821 pre-existing protected files retain identical SHA256, size and mtime_ns. Original failed/incomplete screening, previous EOS diagnostics, old Local, formal control, both trtexec probes, smoke and scripts are unchanged. The old v2 placeholder reports are unchanged. No pre-fix pooling, commit, push, reset, clean, engine rebuild, clock changes or unrelated experiment.

Raw run directories, command/stdout/stderr/exit/environment records, lifecycle state and independent validation are preserved.
