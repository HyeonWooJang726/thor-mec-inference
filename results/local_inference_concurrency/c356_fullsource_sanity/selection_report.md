# C3/C5/C6 full-source application sanity screening

**PASS: 9/9 full-source runs, 97,200 frames; 0 failed, 0 retried, 0 watchdog. Resource smoke 3/3 PASS, 2,100 frames excluded. No new candidate promoted; retain {2,4}.**

## Scope and evidence strength

C={3,5,6}, K={5,6,7}, one run per cell. Each full-source run uses all 1800 video frames at phase-aligned 30 FPS/stream, 60-second offered duration, no drops, warm-up, sample exclusion or deliberate cooldown. The prescribed order was C3-K5, C5-K5, C6-K5, C6-K6, C5-K6, C3-K6, C3-K7, C5-K7, C6-K7. All accepted frames were drained before cleanup/validation and the next run. This is sanity screening, not a precise formal comparison or final canonical baseline.

New C3/C5/C6 results are **single measured runs**; no between-run SD is defined for them. C2/C4 references are read-only means of **three 60-second full-source runs**. C7 is a **historical mean of two 30-second bounded runs**, with a different workload duration. They are not contemporaneous, not equally reliable, not pooled and not used for significance/population-superiority claims. Reference means, sample SD and min/max are retained in sanity_comparison.csv; new-run SD fields are blank.

## Runtime and integrity

Canonical engine `models/rtdetr_warehouse_v1.0.2.fp16.b1.canonical.engine`, SHA256 `9d01cdb2838bb1b9db58c246e6111a5dccee63bb937b673fb48caf43e53bc5ff`; B1, inputs 1x3x640x640. Same audited Warehouse_027 Camera_0000..Camera_0006 mapping. MAXN, DVFS unlocked, jetson_clocks OFF, CUDA Graph OFF; no engine rebuild or clock changes. Engine/source hashes and environment constraints were verified for every run.

One shared engine, C independent workers/contexts/nonblocking submission streams/device I/O/pinned staging sets. Only the allowed-C guard changed in the pool/ownership modules; resource creation, ContextWorker, arrival/inference workers, front-end acquisition loop and metric implementation are unchanged. Async H2D, execute_async_v3, async D2H and stream-local synchronization remain; no cudaDeviceSynchronize. All configured workers were used and max active equaled C in the observed runs, although equality was not a validation requirement. Host overlap establishes concurrent outstanding requests only; GPU kernel overlap was not directly measured.

59 CPU regression tests passed. The known original test-fixture OUTPUT capture was isolated in memory without modifying its source. Short 100-frame resource smoke requires exact acquisition/completion/cleanup with independently recorded EOS. Full-source 1800-frame runs require **all actual natural EOS**, and cannot substitute sample-budget completion. The original unbounded source pipeline is used; no artificial EOS limiter.

All 54 full-source stream instances observed natural EOS. Every run passed exact arrivals/samples/preprocessed/completed/CSV counts, per-stream IDs 0..1799 once, raw-ns timestamp ordering/decomposition, waiting/active drain, ownership, clean joins and confirmed pipeline NULL. Disk replay verified actual EOS and joins before shutdown. There were zero missing/duplicate frames, negative waiting events, watchdogs or runtime errors. Exact candidate miss condition is local_latency_ns*30 > 1000000000; this is not a final application SLA.

| Smoke | Frames | Workers used | Max active | Service overlap pairs | Integrity |
|---|---:|---:|---:|---:|---|
| C3-K7 | 700 | 3 | 3 | 1318 | PASS |
| C5-K7 | 700 | 5 | 5 | 2550 | PASS |
| C6-K7 | 700 | 6 | 6 | 2769 | PASS |

## New single-run results

All durations are ms, miss is %. No row is an average across repetitions.

| C | K | Local mean | p95 | p99 | Miss % | Queue mean | Queue p95 | Inference mean | Inference p95 |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 3 | 5 | 29.3604 | 38.4518 | 41.2038 | 18.2000 | 3.1500 | 10.2428 | 10.9234 | 13.8948 |
| 5 | 5 | 34.8089 | 36.1208 | 184.4897 | 16.5889 | 0.4520 | 0.7188 | 19.8076 | 23.3153 |
| 6 | 5 | 36.6189 | 36.4021 | 272.4046 | 19.1333 | 0.3648 | 0.8156 | 19.6782 | 23.3369 |
| 3 | 6 | 32.9209 | 39.4856 | 177.3733 | 39.6389 | 7.5622 | 12.7077 | 12.1507 | 14.4517 |
| 5 | 6 | 43.1567 | 41.1589 | 407.8639 | 45.8333 | 3.0322 | 17.1853 | 18.3504 | 24.1153 |
| 6 | 6 | 46.4754 | 40.8474 | 403.2418 | 89.9537 | 0.3400 | 0.9071 | 24.2805 | 27.2823 |
| 3 | 7 | 38.4838 | 54.1674 | 199.6529 | 53.9286 | 12.6402 | 25.3641 | 12.0416 | 14.9615 |
| 5 | 7 | 58.8142 | 245.6528 | 507.6982 | 69.2222 | 5.4597 | 19.0337 | 18.2740 | 24.9613 |
| 6 | 7 | 75.3389 | 406.6161 | 625.5396 | 88.8651 | 3.2876 | 18.5405 | 22.2187 | 27.8291 |

| C | K | Peak waiting queue | Time-weighted waiting queue | Workers used | Max active | Service overlap pairs | Service overlap ms |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 3 | 5 | 23 | 0.473200 | 3 | 3 | 12637 | 35129.8271 |
| 5 | 5 | 20 | 0.068188 | 5 | 5 | 18176 | 38703.4793 |
| 6 | 5 | 16 | 0.055039 | 6 | 6 | 18247 | 38659.1210 |
| 3 | 6 | 44 | 1.365479 | 3 | 3 | 16337 | 44451.2367 |
| 5 | 6 | 21 | 0.550302 | 5 | 5 | 25644 | 42107.7674 |
| 6 | 6 | 15 | 0.061716 | 6 | 6 | 27420 | 48224.9929 |
| 3 | 7 | 46 | 2.662014 | 3 | 3 | 20489 | 49779.8791 |
| 5 | 7 | 33 | 1.156091 | 5 | 5 | 35564 | 53766.2360 |
| 6 | 7 | 38 | 0.697260 | 6 | 6 | 38682 | 51639.7779 |

## Overall application trend with heterogeneous references

| K | C | Source | n | Offered seconds | Miss % | Local p95 | Local p99 | Queue mean | Inference mean |
|---:|---:|---|---:|---:|---:|---:|---:|---:|---:|
| 5 | 2 | FULL_SOURCE_REFERENCE_3_RUN_MEAN | 3 | 60 | 1.6111 | 32.2002 | 79.6054 | 6.7369 | 7.7066 |
| 5 | 3 | NEW_FULL_SOURCE_SINGLE_RUN | 1 | 60 | 18.2000 | 38.4518 | 41.2038 | 3.1500 | 10.9234 |
| 5 | 4 | FULL_SOURCE_REFERENCE_3_RUN_MEAN | 3 | 60 | 4.9148 | 33.3460 | 65.6199 | 3.3963 | 14.2796 |
| 5 | 5 | NEW_FULL_SOURCE_SINGLE_RUN | 1 | 60 | 16.5889 | 36.1208 | 184.4897 | 0.4520 | 19.8076 |
| 5 | 6 | NEW_FULL_SOURCE_SINGLE_RUN | 1 | 60 | 19.1333 | 36.4021 | 272.4046 | 0.3648 | 19.6782 |
| 5 | 7 | BOUNDED_HISTORICAL_2_RUN_MEAN | 2 | 30 | 30.8444 | 39.0731 | 347.1768 | 0.5163 | 19.2388 |
| 6 | 2 | FULL_SOURCE_REFERENCE_3_RUN_MEAN | 3 | 60 | 32.2901 | 38.9931 | 157.3571 | 9.3662 | 8.5566 |
| 6 | 3 | NEW_FULL_SOURCE_SINGLE_RUN | 1 | 60 | 39.6389 | 39.4856 | 177.3733 | 7.5622 | 12.1507 |
| 6 | 4 | FULL_SOURCE_REFERENCE_3_RUN_MEAN | 3 | 60 | 33.7006 | 38.9019 | 155.3651 | 5.1513 | 14.2606 |
| 6 | 5 | NEW_FULL_SOURCE_SINGLE_RUN | 1 | 60 | 45.8333 | 41.1589 | 407.8639 | 3.0322 | 18.3504 |
| 6 | 6 | NEW_FULL_SOURCE_SINGLE_RUN | 1 | 60 | 89.9537 | 40.8474 | 403.2418 | 0.3400 | 24.2805 |
| 6 | 7 | BOUNDED_HISTORICAL_2_RUN_MEAN | 2 | 30 | 82.5000 | 248.8370 | 501.0315 | 0.6978 | 23.0587 |
| 7 | 2 | FULL_SOURCE_REFERENCE_3_RUN_MEAN | 3 | 60 | 84.5079 | 259.2254 | 280.7943 | 139.3322 | 9.1581 |
| 7 | 3 | NEW_FULL_SOURCE_SINGLE_RUN | 1 | 60 | 53.9286 | 54.1674 | 199.6529 | 12.6402 | 12.0416 |
| 7 | 4 | FULL_SOURCE_REFERENCE_3_RUN_MEAN | 3 | 60 | 47.3836 | 71.9133 | 238.0379 | 10.5433 | 15.2889 |
| 7 | 5 | NEW_FULL_SOURCE_SINGLE_RUN | 1 | 60 | 69.2222 | 245.6528 | 507.6982 | 5.4597 | 18.2740 |
| 7 | 6 | NEW_FULL_SOURCE_SINGLE_RUN | 1 | 60 | 88.8651 | 406.6161 | 625.5396 | 3.2876 | 22.2187 |
| 7 | 7 | BOUNDED_HISTORICAL_2_RUN_MEAN | 2 | 30 | 96.9048 | 507.8060 | 627.7462 | 1.1010 | 26.8709 |

## K-specific interpretation

**K5:** New miss rates are C3 18.2000%, C5 16.5889%, C6 19.1333%; historical full-source C2/C4 means are 1.6111%/4.9148%. C3 has lower p99 than those reference means, but its p95 and deadline miss are worse. C5/C6 mean waiting is below 0.5 ms while service means approach 20 ms and deadline miss remains high. C7 historical 30-second miss is 30.8444%; it is context only, not a matched full-source comparison.

**K6:** C3 39.6389%, C5 45.8333%, C6 89.9537% miss versus C2/C4 means 32.2901%/33.7006%. None shows a deadline advantage over the retained references. C5/C6 p99 reaches 407.8639/403.2418 ms despite reduced mean waiting. C6 has 24.2805-ms mean service and 0.3400-ms mean waiting; this is the high-service-cost/deadline-degradation direction associated with C7 historical screening, whose 30-second miss mean is 82.5000%. The durations differ, so a numerical superiority claim against C7 is unwarranted.

**K7:** C3 53.9286%, C5 69.2222%, C6 88.8651% miss versus C2/C4 means 84.5079%/47.3836%. C3 substantially reduces backlog relative to the C2 mean, but does not match C4 deadline QoS. C3 local mean/p95/p99 (38.4838/54.1674/199.6529 ms) are below C4 reference means (41.2866/71.9133/238.0379 ms); its p95/p99 remain within the C4 three-run ranges (46.8964–89.0571 and 199.5975–265.1864 ms). This single observation is not evidence of repeatable C3 tail superiority. C5/C6 further reduce mean waiting but worsen deadlines and local tails relative to C4. C7 historical 30-second miss is 96.9048%; do not interpret its absolute difference as a matched 60-second effect.

## Missed-candidate decision

**C3 promoted: NO.** Mean inference service lies between the C2/C4 reference means, but the desired C2-like K5/K6 deadline behavior was not observed. Relative to C4 reference, miss rises by 13.2852 / 5.9383 / 6.5450 pp at K5/K6/K7. Its favorable single-run K7 tails and lower service cost are preserved in the report, but do not establish a better fixed-concurrency compromise under the specified deadline-first priority.

**C5 promoted: NO.** Relative to C4, mean waiting decreases at all K, but miss rises by 11.6741 / 12.1327 / 21.8386 pp and p95/p99 are higher at every K. No extra queue benefit translated into better deadline/tail QoS in this sanity sample.

**C6 promoted: NO.** Relative to C4, miss rises by 14.2185 / 56.2531 / 41.4815 pp and tails worsen. Mean service is higher by 5.3986 / 10.0199 / 6.9299 ms. The observed behavior supports the contention-cost concern, without assigning a GPU-kernel-level root cause.

**Remaining candidate set: {2,4}.** This is CASE A at sanity-screening strength, with the n=1 uncertainty explicitly retained. It is not a population-level exclusion of C3/C5/C6. No overlooked candidate shows sufficient deadline-first evidence to displace or expand the existing set. No additional experiment was automatically executed.

**Canonical C decision ready: NO.** The new application-level sanity gaps are filled, but the existing C2 advantage at K5/K6 versus C4 advantage at K7 remains. Choosing one fixed C still requires the intended operating load range and acceptable deadline-miss trade-off. **Canonical 35-run ready: NO; C remains undecided.**

Application candidate coverage now includes prior C1/C2 full-source control, C2/C4 full-source targeted validation, new C3/C5/C6 full-source single-run sanity, and historical C7 bounded application screening. This does not mean all C1..7 received equal-duration/equal-repetition full-source validation. C1/C2/C4/C7 were not rerun in this task.

## Protection and outputs

PASS: all 4,188 pre-existing protected files retain identical SHA256, size and mtime_ns. Old Local, formal control, both micro-probes, failed/successful screening, bounded contract, EOS diagnostics, C2/C4 full-source results and unrelated scripts are unchanged. New raw logs, commands, exits, environments, resource/lifecycle evidence and CSV replay remain under this root.

No figures, final 35-run, model/engine rebuild, batch/clock/CUDA Graph change, graph partition, network/server/scheduler experiment, commit, push, reset or clean.
