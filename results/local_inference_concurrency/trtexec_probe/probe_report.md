# Canonical TensorRT cross-inference probe

All 15 measured runs completed with exit 0 and trtexec PASSED. Five runs/configuration. No application formal benchmark was executed.

## Audited harness and conditions

- TensorRT banner: v101602 b10; installed libnvinfer10/python3-libnvinfer: 10.16.2.10-1+cuda13.2. JetPack 7.2.1-b49, CUDA 13.2, Thor.
- `/usr/bin/trtexec --version` was actually invoked: exit 1, Model missing or format not recognized; it prints the version banner but is not a successful version-only CLI. Host stdout/stderr retained under ../audit/host_version.*. The first sandbox attempt failed device access and is also preserved.
- `/usr/bin/trtexec --help` exits 0 and explicitly says `--infStreams=N` instantiates N execution contexts for concurrent inference. CLI selection is based on installed help, not TensorRT 11.
- Engine: `models/rtdetr_warehouse_v1.0.2.fp16.b1.canonical.engine` (SHA256 9d01cdb2838bb1b9db58c246e6111a5dccee63bb937b673fb48caf43e53bc5ff).
- Actual existing warehouse input: `results/correctness/Camera_0000_t60_input.bin`, 4,915,200 bytes, SHA256 c51c95a17ba7a102b8f898406aedf0385900357a6593fdde55d4668bf6f73e93. No random/new input was generated.
- Prior command/protocol evidence: `results/power_calibration/rtdetr_b1_maxn_run1.log:26` and `results/cross_inference_profiling/rtdetr_b1_c1_maxn_run1.log:18`. The correctness README identifies the original frame as Warehouse_000 / Camera_0000. The video application workload is separately Warehouse_027; these are not conflated.
- Historical profiling used the noncanonical b1.engine (SHA256 b17925533fd9b4387083f85d035cd233a3bb553917047a3d6d4786a01ab003fe), which differs from the requested canonical engine. Historical numbers are not merged into this new probe.
- Shape inputs:1x3x640x640, B=1, warmUp=2000 ms, duration=30 seconds (trtexec minimum measured walltime), MAXN ID 0, DVFS unlocked, jetson_clocks OFF as evidenced by CPU/GPU/EMC min<max. No clock/power modifications.
- CUDA Graph OFF, SpinWait OFF, data transfers enabled; no extra streams/thread/auxiliary options. Defaults are retained.
- `--exportTimes` is the only additional reporting-only flag. It preserves actual trtexec per-inference timings, separated from the 2-second warm-up (first measured samples start at about 2000 ms); it does not change duration/warmup.
- Rotation: rep01 1→2→4; rep02 2→4→1; rep03 4→1→2; rep04 1→2→4; rep05 2→4→1. No deliberate cooldown. Each previous process and artifact write completed before the next run.
- Every run has command JSON/text, separate stdout/stderr, exit.json, environment before/after, raw timing.json and parsed metrics.json. Optional unreadable thermal sensors are explicitly unavailable. A pre-measurement thermal-read failure is retained in ../trtexec_probe_preflight_failed_01; no inference run had started there.

Historical command (exact):

```
/usr/bin/trtexec --loadEngine=models/rtdetr_warehouse_v1.0.2.fp16.b1.engine --shapes=inputs:1x3x640x640 --loadInputs=inputs:results/correctness/Camera_0000_t60_input.bin --warmUp=2000 --duration=30
```

New command pattern (each exact expanded command is in its run directory):

```
/usr/bin/trtexec --loadEngine=models/rtdetr_warehouse_v1.0.2.fp16.b1.canonical.engine --shapes=inputs:1x3x640x640 --loadInputs=inputs:results/correctness/Camera_0000_t60_input.bin --warmUp=2000 --duration=30 --infStreams=C --exportTimes=results/local_inference_concurrency/trtexec_probe/repRR_infStreamsC/timing.json
```

## Five-run statistics

Each entry is mean ± sample SD [minimum, maximum]. Percentiles are the arithmetic mean of five reported run percentiles, never pooled-frame percentiles. Only metrics actually printed by this installed trtexec are parsed. Full statistics for reported min/max/mean/median/p90/p95/p99 of each latency category are in concurrency_summary.csv.

| Metric | infStreams=1 | infStreams=2 | infStreams=4 |
|---|---:|---:|---:|
| Throughput (qps) | 240.953000 ± 2.444601 [237.831000, 242.755000] | 244.517600 ± 0.872440 [243.643000, 245.823000] | 243.597600 ± 0.856113 [242.094000, 244.177000] |
| Latency mean (ms) | 4.132968 ± 0.044794 [4.099900, 4.193810] | 4.955112 ± 0.011548 [4.937670, 4.968430] | 5.103160 ± 0.015577 [5.084230, 5.127340] |
| Latency median (ms) | 4.117676 ± 0.046937 [4.082030, 4.181640] | 5.058206 ± 0.011991 [5.041020, 5.074220] | 5.163182 ± 0.012650 [5.147460, 5.180660] |
| Latency p95 (ms) | 4.302344 ± 0.035353 [4.277340, 4.355470] | 5.271972 ± 0.016857 [5.250980, 5.290040] | 5.349998 ± 0.027182 [5.314450, 5.390620] |
| Latency p99 (ms) | 4.347166 ± 0.044941 [4.308590, 4.413570] | 5.337596 ± 0.021163 [5.318360, 5.365230] | 5.412304 ± 0.034954 [5.373050, 5.468750] |
| Enqueue mean (ms) | 2.542890 ± 0.036748 [2.514660, 2.607340] | 2.589352 ± 0.008592 [2.579820, 2.600870] | 2.255800 ± 0.015667 [2.229580, 2.269830] |
| H2D mean (ms) | 0.048983 ± 0.002912 [0.046248, 0.053842] | 0.052547 ± 0.001474 [0.051215, 0.054458] | 0.054623 ± 0.001572 [0.052857, 0.055997] |
| GPU compute mean (ms) | 4.078866 ± 0.042922 [4.047050, 4.134780] | 4.893820 ± 0.013245 [4.873870, 4.908640] | 5.039282 ± 0.014408 [5.022930, 5.062040] |
| GPU compute p95 (ms) | 4.228810 ± 0.035350 [4.201660, 4.282230] | 5.211180 ± 0.019965 [5.185790, 5.232420] | 5.291798 ± 0.024405 [5.259770, 5.328120] |
| D2H mean (ms) | 0.005117 ± 0.000086 [0.005027, 0.005232] | 0.008744 ± 0.000630 [0.008133, 0.009448] | 0.009250 ± 0.000462 [0.008442, 0.009571] |
| Paired-repetition throughput ratio | 1.000000 ± 0.000000 [1.000000, 1.000000] | 1.014881 ± 0.011304 [1.004540, 1.029543] | 1.011070 ± 0.012055 [0.997376, 1.026267] |
| Paired concurrency reference | 1.000000 ± 0.000000 [1.000000, 1.000000] | 0.507440 ± 0.005652 [0.502270, 0.514772] | 0.252767 ± 0.003014 [0.249344, 0.256567] |

Ratio of configuration throughput means (C1/C2/C4): 1.000000, 1.014794, 1.010976.

Reference throughput(C)/(C × throughput(1)), using configuration means: 1.000000, 0.507397, 0.252744. This is only a concurrency reference, not GPU utilization or theoretical efficiency. CSV speedup/reference mean/SD/min/max use within-repetition ratios; separately named ratio-of-configuration-means columns remove denominator ambiguity.

## Interpretation

**A — C2 aggregate throughput:** observed increase YES; practical benefit WEAK. Mean is +3.5646 qps (+1.4794%). C1 SD is 2.4446 qps and range 237.831–242.755; C2 SD is 0.8724 and range 243.643–245.823. All five within-repetition ratios exceed one (1.00454–1.02954). Direction is consistent, but magnitude is small and comparable with C1 run variation; no arbitrary significance threshold or inferential p-value is applied.

**B — reported latency inflation: YES, with the CLI accuracy limitation below.** Mean per-inference latency is 4.132968→4.955112 ms (+19.8923%); p95 is 4.302344→5.271972 ms (+22.5372%). The mean-latency SDs are only 0.044794 and 0.011548 ms. GPU compute mean/p95 also inflate; the latency effect is much larger than observed run variation.

**C — C4 additional throughput benefit over C2: NO observed benefit.** Mean throughput decreases 0.9200 qps (−0.3763%), with overlapping run ranges and similar SDs (~0.86–0.87 qps). It does not establish a large throughput penalty, but mean latency rises again to 5.103160 ms (2.99% above C2) and p95 to 5.349998 ms. Extra concurrency increases observed latency/contended service without measurable additional aggregate throughput in this harness; a specific hardware contention mechanism was not directly measured.

These results compare only infStreams 1/2/4 inside the same trtexec harness. They must not be equated numerically with frozen application inference_ms, whose service boundary includes different host/copy/synchronization work. The probe does not decide whether K6 application deadline queueing persists. That requires the future C2 formal control. Host service/submission overlap in smoke is not a direct measurement of GPU kernel overlap.

## Installed CLI warnings and interpretation limit

All ten infStreams=2/4 runs explicitly warn that multi-stream latencies may be
inaccurate when inferences run in parallel and recommend Throughput as the
performance metric. Those runs also report unstable GPU compute time and suggest
clock locking or SpinWait. Full warnings are preserved in each stderr.log and in
warnings.json. Neither suggested setting was enabled: the fixed historical
DVFS-unlocked / SpinWait-OFF protocol was maintained.

Therefore latency inflation above means **inflation of the metrics reported by
this harness**, with the CLI's multi-stream accuracy caveat. It is not an accurate,
unqualified measurement of intrinsic per-request GPU service or kernel contention.
Throughput is the primary probe decision metric. No GPU capacity ceiling or actual
kernel-overlap conclusion is inferred from the small throughput gain. C=2 application
formal remains necessary regardless of these harness results.
