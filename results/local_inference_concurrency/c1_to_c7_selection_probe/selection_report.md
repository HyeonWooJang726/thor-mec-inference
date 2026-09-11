# TensorRT C=1–7 selection micro-probe

35/35 runs valid; 0 failed; 0 retried. **C=4 is the recommended candidate for subsequent application validation.** Runtime adoption remains conditional on that validation. This campaign does not support finalizing C=2 on the premise that no further throughput gain exists.

## Initial state

HEAD: `a080e4ffbff3de1f43223488dcef31c98bcab5d8`

```text
 M scripts/profile_tcp_throughput.py
?? scripts/analyze_local_concurrency_formal_control.py
?? scripts/local_concurrency_control_metrics.py
?? scripts/local_concurrency_tensorrt.py
?? scripts/local_concurrency_validation.py
?? scripts/profile_edge_realtime.py
?? scripts/profile_local_concurrency_control.py
?? scripts/run_local_concurrency_control.py
?? scripts/run_local_concurrency_formal_control.py
?? scripts/run_local_concurrency_trtexec_probe.py
?? scripts/test_local_concurrency_formal_control.py
?? scripts/test_local_concurrency_validation.py
```

## Environment and fixed command

TensorRT package `10.16.2.10-1+cuda13.2`; actual trtexec banner `[TensorRT v101602] [b10]`. JetPack `7.2.1-b49`, L4T `39.2.1-20260806224157`. Saved installed help confirms `--infStreams=N`: “Instantiate N execution contexts to run inference concurrently (default = 1)”. Package/help stdout, stderr and exits are retained.

Engine: `models/rtdetr_warehouse_v1.0.2.fp16.b1.canonical.engine`

SHA256: `9d01cdb2838bb1b9db58c246e6111a5dccee63bb937b673fb48caf43e53bc5ff`

Input: `results/correctness/Camera_0000_t60_input.bin`

SHA256: `c51c95a17ba7a102b8f898406aedf0385900357a6593fdde55d4668bf6f73e93`

MAXN (mode 0), DVFS unlocked, jetson_clocks OFF, CUDA Graph OFF. CPU/GPU/EMC min < max and unchanged governor/frequency limits are recorded before and after every run. All 70 environment checks pass. No power/clock tuning, model/engine rebuild, random input, batch change, or spin-wait change. First-run power, governor/limits, relevant environment variables and uname match the previous campaign.

C means `trtexec --infStreams=C`: cross-inference execution contexts. It is not video stream count K, CUDA thread count, or TensorRT auxiliary-stream count. The existing engine reports two internal auxiliary streams per context; the engine is unchanged. trtexec host multithreading remains disabled as in the previous probe.

Exact run example (repository cwd):

```sh
/usr/bin/trtexec --loadEngine=models/rtdetr_warehouse_v1.0.2.fp16.b1.canonical.engine --shapes=inputs:1x3x640x640 --loadInputs=inputs:results/correctness/Camera_0000_t60_input.bin --warmUp=2000 --duration=30 --infStreams=4 --exportTimes=results/local_inference_concurrency/c1_to_c7_selection_probe/c4/run01/timing.json
```

All 15 historical commands were audited. The fixed compute arguments match them. Across this campaign only `--infStreams` changes; `--exportTimes` varies only the reporting destination. Shape `inputs:1x3x640x640`, B=1, warm-up 2000 ms, measurement 30 s, transfers enabled. No application runner is imported or executed by the probe.

Rotation: R1 1→2→3→4→5→6→7; R2 2→3→4→5→6→7→1; R3 3→4→5→6→7→1→2; R4 4→5→6→7→1→2→3; R5 5→6→7→1→2→3→4. Deliberate cooldown NONE. Each run exited and its artifacts were validated before the next run started. No failures, retries, or replacement runs occurred.

## Throughput results

Units qps. Each row summarizes five separate run-level throughput values. Sample SD uses n−1. Speedup and incremental gain are ratios of configuration means; C1 has no previous-C incremental gain. No pooling across campaigns.

| C | Mean | Sample SD | Median | Min | Max | Speedup vs C1 | Increment vs previous C (%) |
|---|---|---|---|---|---|---|---|
| 1 | 240.193000 | 2.339980 | 241.702000 | 236.765000 | 241.915000 | 1.000000 | N/A |
| 2 | 240.521600 | 1.795136 | 240.247000 | 238.335000 | 243.102000 | 1.001368 | +0.136807 |
| 3 | 241.290000 | 1.510283 | 240.904000 | 239.898000 | 243.163000 | 1.004567 | +0.319472 |
| 4 | 244.145400 | 2.079348 | 245.100000 | 241.317000 | 246.033000 | 1.016455 | +1.183389 |
| 5 | 243.113800 | 2.006762 | 242.577000 | 241.145000 | 245.311000 | 1.012160 | -0.422535 |
| 6 | 243.864600 | 2.317985 | 245.137000 | 241.178000 | 245.770000 | 1.015286 | +0.308827 |
| 7 | 244.395200 | 1.948250 | 245.347000 | 241.325000 | 246.014000 | 1.017495 | +0.217580 |

## Repetition-index paired direction

| Comparison | Higher C wins | Differences by repetition (qps) |
|---|---|---|
| C2 > C1 | 1/5 | -0.393, -1.455, +6.337, -0.626, -2.220 |
| C3 > C2 | 3/5 | +4.828, -0.332, -3.204, +1.281, +1.269 |
| C4 > C3 | 4/5 | -1.846, +5.776, +6.135, +2.530, +1.682 |
| C5 > C4 | 2/5 | +3.831, -4.303, -3.456, +0.211, -1.441 |
| C6 > C5 | 3/5 | -3.970, +3.749, +3.152, -3.802, +4.625 |
| C7 > C6 | 3/5 | +4.493, -3.812, -2.110, +3.838, +0.244 |

Pairing means the same repetition index in sequential, rotated runs. Runs were not simultaneous and this is not a paired randomized trial. Five observations support descriptive direction and variability, not strong statistical significance claims.

## Reported latency and transfer metrics

Each cell below is the mean of five printed run-level statistics; p95/p99 are means of reported run quantiles, not pooled quantiles. Full mean/sample SD/median/min/max for every printed metric, including enqueue/H2D/D2H percentiles, are retained in `c_summary.csv`. No unreported metric was synthesized.

| C | Latency mean ms | Latency median ms | Latency p95 ms | Latency p99 ms | GPU mean ms | GPU p95 ms | Enqueue mean ms | H2D mean ms | D2H mean ms |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 4.149150 | 4.134570 | 4.323390 | 4.379980 | 4.092202 | 4.249216 | 2.542860 | 0.051719 | 0.005230 |
| 2 | 5.034486 | 5.133398 | 5.352246 | 5.419924 | 4.971320 | 5.291162 | 2.614678 | 0.053862 | 0.009307 |
| 3 | 5.096370 | 5.168458 | 5.375000 | 5.442480 | 5.026486 | 5.303906 | 2.424684 | 0.060223 | 0.009667 |
| 4 | 5.072642 | 5.125976 | 5.330860 | 5.400294 | 5.008226 | 5.271482 | 2.249274 | 0.055248 | 0.009168 |
| 5 | 5.121428 | 5.161132 | 5.399804 | 5.488478 | 5.055098 | 5.335546 | 2.131164 | 0.057017 | 0.009312 |
| 6 | 5.106876 | 5.145704 | 5.388086 | 5.511622 | 5.039192 | 5.321682 | 2.064356 | 0.058191 | 0.009495 |
| 7 | 5.097800 | 5.139746 | 5.367480 | 5.465428 | 5.030704 | 5.300976 | 2.053008 | 0.057911 | 0.009188 |

All 30 C>1 runs emitted this warning, retained verbatim in each stderr log and `warnings.json`:

> * Multiple inference streams are used. Latencies may not be accurate since inferences may run in   parallel. Please use "Throughput" as the performance metric instead.

Aggregate throughput is the primary selection metric. These reported latencies are not precise application inference service times and are not substituted for formal pipeline inference_ms. Clock/spin-wait stability suggestions in the raw warnings were not applied. GPU kernel overlap was not directly measured.

## Saturation and selection

**Saturation observed: YES, as a descriptive plateau; first plausible saturation C: 4.** The entire tested mean-throughput range is narrow (240.193–244.395 qps), so the concurrency benefit is modest. No arbitrary percentage cutoff was used.

C2 vs C1 gives only 0.136807% mean gain and wins 1/5 pairs. C3 vs C2 gives 0.319472% and wins 3/5. In contrast, C4 vs C2 gives 1.506642% and wins 5/5: paired differences 2.931 to 5.444 qps, mean ± sample SD 3.6238 ± 1.0831 qps. C4 vs C3 wins 4/5.

C2 range 238.335–243.102 and C4 range 241.317–246.033 qps overlap; C4 sample SD is 2.079 qps. Thus this is a modest, repeated directional gain, not proof of a universal boundary. In this campaign it is enough to retain C4 as a candidate and reject a premature C2 fixed choice.

| C | Mean difference vs C4 qps | Change vs C4 % | Wins vs C4 |
|---|---|---|---|
| 5 | -1.031600 | -0.422535 | 2/5 |
| 6 | -0.280800 | -0.115013 | 1/5 |
| 7 | +0.249800 | +0.102316 | 3/5 |

C5–C7 have overlapping ranges and sample SDs near 2 qps. Their adjacent gains alternate in direction, with only 2/5, 3/5, and 3/5 wins. C7 has the highest mean, but exceeds C4 by only 0.2498 qps (0.102316%) and wins 3/5 direct pairs. No consistent additional benefit beyond C4 is established. C4 is the smallest plausible plateau candidate under these tested conditions. This is CASE B for the selection rule; no high-C infeasibility occurred.

## Previous probe sensitivity comparison

| C | Old mean ± SD qps | New mean ± SD qps | New−old qps | Change % |
|---|---|---|---|---|
| 1 | 240.953000 ± 2.444601 | 240.193000 ± 2.339980 | -0.760000 | -0.315414 |
| 2 | 244.517600 ± 0.872440 | 240.521600 ± 1.795136 | -3.996000 | -1.634238 |
| 4 | 243.597600 ± 0.856113 | 244.145400 ± 2.079348 | +0.547800 | +0.224879 |

**Trend reproduced: PARTIAL.** The narrow aggregate throughput range is reproduced, but the prior C2 advantage and lack of C4 improvement over C2 are not. Old C2 exceeds every new C2 run (old min 243.643 > new max 243.102 qps). The prior C2 mean gain vs C1 was about 1.479%; now it is 0.137%. Old C4 was below old C2; new C4 exceeds new C2 in all five indexed pairs. Same recorded fixed settings do not eliminate time-dependent DVFS/thermal/system variability; this comparison does not establish the cause of the campaign difference. The campaigns are never pooled.

## Application validation and next step

**Recommended fixed-C candidate: 4, conditional on application validation. Additional application C validation: YES (C4). Immediate K1–7 × 5 canonical application formal readiness: NO.** Current application CLI accepts only C1/C2 and formal K5/K6/K7; current concurrency validation also supports only C1/C2. The completed 30-run C1/C2 control cannot validate a C4 application path.

Next task should prepare the same application code path for four independent contexts, submission streams, private device buffers and pinned staging sets, then run short integrity and sufficiently loaded concurrent-submission validation. Extend the workload/output guard for a fresh K1–7 campaign and make low-load validation distinguish available context count from actually demanded overlap. Only after that passes should the separately authorized 35-run canonical application campaign begin. No such implementation change, smoke, or application formal run was performed here.

This micro-probe answers only engine-level aggregate throughput behavior under additional cross-inference outstanding work. It makes no claims about application deadlines, queue wait, video capacity, or physical kernel overlap. Existing new-C1/new-C2 formal results remain separate evidence.

## Artifact integrity

| Protected root | Files | SHA256 / size / mtime_ns unchanged |
|---|---|---|
| results/local_latency_breakdown | 445 | YES |
| results/local_inference_concurrency/trtexec_probe | 143 | YES |
| results/local_inference_concurrency/smoke | 31 | YES |
| results/local_inference_concurrency/formal_control | 749 | YES |

All 1,829 pre-existing protected files are unchanged, including the additional baseline, prior preparation artifacts and scripts. No files were added outside the new output root. `protected_manifest_before.json` and `protected_manifest_after.json` retain hashes, sizes and nanosecond mtimes. `raw_artifact_manifest.json` protects every new per-run artifact. `integrity_report.json` records 35/35 run/order/command/metric checks, 70 environment checks, source invariance, and preservation results.

Outputs: `run_summary.csv`, `c_summary.csv`, `paired_direction.csv`, `paired_run_details.csv`, `c2_reference_comparison.csv`, `previous_probe_comparison.csv`, `selection.json`, `integrity_report.json`; complete raw commands/logs/exits/environments/timings/validations in `c1`…`c7/run01`…`run05`. New execution and aggregation code are confined to this output root: `run_probe.py`, `analyze_probe.py`.

## Final git status

```text
 M scripts/profile_tcp_throughput.py
?? scripts/analyze_local_concurrency_formal_control.py
?? scripts/local_concurrency_control_metrics.py
?? scripts/local_concurrency_tensorrt.py
?? scripts/local_concurrency_validation.py
?? scripts/profile_edge_realtime.py
?? scripts/profile_local_concurrency_control.py
?? scripts/run_local_concurrency_control.py
?? scripts/run_local_concurrency_formal_control.py
?? scripts/run_local_concurrency_trtexec_probe.py
?? scripts/test_local_concurrency_formal_control.py
?? scripts/test_local_concurrency_validation.py
```

Commit/push/reset/clean/staging: NO. Figures: NONE. Application workloads: NONE. The original C1 formal, prior trtexec probe/smoke, and 30-run C1/C2 application formal were not rerun or changed.
