# Formal B=1 Real-time Local Baseline

This directory preserves measured formal observations from NVIDIA Jetson AGX
Thor. It contains the initial K=1..7 Run1 sweep and boundary repeats K=6 Run2,
K=6 Run3, and K=7 Run2. All samples, including startup transients and frames
completed after the last arrival, are retained. No run is excluded as an outlier.

## Frozen Implementation

- Profiler implementation source commit:
  `2a5e017bb112cae6cab59dce1b4256844ac8ae67`.
- Initial K1..K7 Run1 result freeze commit:
  `6377190be2fb552693e1db79460fe7f24cba8ee3`.
- Profiler: `scripts/profile_local_realtime.py`, reusing the existing
  `preprocess_bgr`, `build_pipeline`, and `TensorRTRunner` implementations.
- The repeats use the same frozen source implementation according to the
  experiment record. Repository source is unchanged from the source commit;
  these CSV/JSON files do not independently embed a per-run source hash.

Each run has five artifacts under `b1_sync/kK/`: `runR/per_frame.csv`,
`runR/summary.json`, `runR_console.log`, `runR_oc3_before.txt`, and
`runR_oc3_after.txt`.

## Common Configuration

- 30 FPS per stream; 1800 frames per stream.
- Approximately 60 s arrival period; first-to-last actual arrival spans
  approximately 59.9667 s.
- Phase-aligned logical arrivals: `scheduled_arrival = t0 + frame_id / 30.0`,
  with the same global `t0` for every stream.
- B=1, C=1, one TensorRT runner, one TensorRT execution context, and one
  inference worker.
- Dynamic batching disabled; frame drop disabled.
- One front-end worker and one unbounded FIFO arrival queue per stream;
  one shared unbounded ready queue; existing EOS semantics retained.
- Canonical B1 engine:
  `models/rtdetr_warehouse_v1.0.2.fp16.b1.canonical.engine`.
- DVFS enabled; `jetson_clocks` OFF; CUDA Graph OFF; OC protection unchanged.

The DVFS, clock-control, and OC-protection settings above are the declared
experiment configuration. They are not measurements of the changing system
state during execution. The artifacts do not provide time-resolved clock,
thermal, or contention telemetry.

The actual distinct-camera workload covers K<=7, using distinct Warehouse_027
camera videos within each run. These observations do not represent additional
distinct cameras through stream duplication.

**33.33 ms is the arrival cadence, NOT a deadline.** No deadline-miss metric is
defined here.

## Offline Validation and Measurement Conventions

The initial sweep integrity audit passed for all 50,400 rows. The additional
K6 Run2, K6 Run3, and K7 Run2 integrity checks also passed, covering 34,200 rows:

- Exactly `1800*K` rows, with frame IDs 0..1799 exactly once per stream;
  no duplicate or missing frame keys.
- Finite timestamps with
  `scheduled_arrival_s <= actual_arrival_enqueue_s <= front_end_start_s <=
  ready_s <= inference_start_s <= completion_s`.
- All seven derived timing fields exactly reproduce from raw timestamps.
- CSV counts match total and per-stream summary counts.
- Reconstructed backlog matches the summary; final backlog after drain is 0.
- Summary validation is `pass` and errors are empty.

Backlog reconstruction creates an ARRIVAL event at each
`actual_arrival_enqueue_s` and a COMPLETION event at each `completion_s`.
Events are sorted by timestamp, with ARRIVAL before COMPLETION on exact ties.
ARRIVAL adds 1 and COMPLETION subtracts 1. Final-arrival backlog means the value
immediately after applying the last ARRIVAL event, before any tied COMPLETION.

Actual-arrival service rate is:

```text
t_first_actual = min(actual_arrival_enqueue_s)
t_last_actual  = max(actual_arrival_enqueue_s)
completed_by_last_actual = count(completion_s <= t_last_actual)
service_rate_fps = completed_by_last_actual / (t_last_actual - t_first_actual)
```

No completion exactly ties the last actual arrival in the compared runs, so
`completed_by_last_actual + final_arrival_backlog = total arrivals` holds.
Post-arrival drain completions are excluded from this service rate.

Trajectory time zero is the first actual arrival. Backlog means integrate the
piecewise-constant backlog over elapsed time. Slopes are ordinary least-squares
regressions of full 1-second time-weighted bin means against bin center times;
`[10,59)` uses bins 10..58. The final partial bin is excluded from regression.
Full-period means include the initial transient. Latency statistics include all
completed frames, including drain; percentiles use linear interpolation.

## Initial K=1..7 Sweep

- K=1..5: no sustained backlog growth observed in Run1.
- K=6 Run1: observed stable after startup.
- K=7 Run1: clear overload.

The initial observed boundary was between offered loads of 180 fps and 210 fps,
but was not yet repeatability-confirmed. This was an observation over the tested
arrival windows, not an established long-duration sustainable capacity.

## K=6 Repeatability

Offered load is 180 fps. Latencies below are in ms; backlog is in frames.

| Run | Service rate [fps] | Ready wait mean | Local E2E mean | Front-end mean | Inference mean | Peak backlog | Final-arrival backlog | Classification |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| [Run1](b1_sync/k6/run1/summary.json) | 179.983273 | 19.163 | 36.482 | 11.553 | 4.830 | 50 | 7 | Observed stable after startup |
| [Run2](b1_sync/k6/run2/summary.json) | 179.983163 | 17.255 | 34.582 | 11.623 | 4.891 | 41 | 7 | Observed stable after startup |
| [Run3](b1_sync/k6/run3/summary.json) | 179.449614 | 180.704 | 201.161 | 13.954 | 5.470 | 49 | 39 | Near-critical / marginal |

Run1 and Run2 return to low backlog after approximately 5 s. Their `[10,59)`
time-weighted backlog means are 4.820 and 4.885 frames, respectively. Run3 does
not reproduce that low-backlog state.

| Run | Full arrival-period backlog mean | `[10,59)` slope [frames/s] | R-squared | `[30,59)` slope [frames/s] | R-squared |
|---|---:|---:|---:|---:|---:|
| Run1 | 6.544 | -0.000479 | 0.015813 | -0.000868 | 0.013975 |
| Run2 | 6.202 | -0.000420 | 0.008090 | -0.000874 | 0.015186 |
| Run3 | 36.135 | +0.120375 | 0.199064 | +0.173166 | 0.200575 |

## K=6 Run3 Observation

### Confirmed observations

- Artifact integrity PASS; all 10,800 frames completed without frame loss.
- Normal bounded-workload termination under the existing EOS semantics: no
  early-EOS error was reported, and the console records
  `termination: bounded workload fully drained`. Full-video EOS timing is not
  independently recorded by these artifacts.
- Final drain succeeded; final backlog is 0. The OC3 before/after files both
  contain 0 (0 -> 0).
- The source implementation is the same frozen implementation described above.
- No evidence of sustained scheduler drift: Run3's consecutive 10-second
  actual-arrival-bin mean scheduler lags are 0.168, 0.147, 0.159, 0.143, 0.136,
  and 0.147 ms. Overall mean/p95/max are 0.150/0.160/8.846 ms, and final-tick
  maximum lag is 0.121 ms. Isolated lag spikes are retained.
- Front-end mean increased from 11.553/11.623 ms in Run1/2 to 13.954 ms;
  inference mean increased from 4.830/4.891 ms to 5.470 ms.
- Ready queue wait increased substantially and a high backlog plateau formed.
  The full arrival-period time-weighted backlog mean is 36.135 frames.

### Trajectory and interpretation

Run3's consecutive interval time-weighted backlog means are 27.179, 35.348,
37.716, 35.851, 40.900, and 39.830 frames for 0-10, 10-20, 20-30, 30-40,
40-50, and 50-final-arrival seconds. The trajectory contains accumulation,
partial recovery, and a high late plateau; it is not near-linear growth across
the whole arrival period.

The `[40,59)` slope is -0.078167 frames/s with low R-squared (0.074087).
Completion throughput during `[50, final-arrival]` is 180.602 fps. Thus a
final-arrival backlog of 39 does not by itself establish sustained overload.
The positive earlier-window slopes are retained in the table above; the late
plateau does not establish long-duration stationarity either.

Classification: **near-critical / marginal**, not sustained linear overload.
Run3 is a valid formal observation, not a correctness failure, and is retained
without outlier removal.

Interpretation: the observed K6 workload at 180 fps operates near local service
capacity. Relatively small processing-rate changes can be amplified into large
queueing changes near this operating point. This interpretation is consistent
with the measured stage durations and backlog, but does not identify the cause
of the processing-time increase or establish an exact service-capacity value.

## Root-Cause Status

**Root cause of the Run3 processing-time increase: UNKNOWN / NOT IDENTIFIED.**

The root cause of the K=6 Run3 processing-time increase has not been identified.
System-state causes were not instrumented in these runs.

DVFS state, thermal throttling, background system activity, CPU contention,
memory contention, GPU clock variation, decoder contention, and other
system-state explanations are hypotheses only. Do not attribute the behavior
to thermal/DVFS/background load/etc. without additional measurements.
OC3 remaining 0 does not identify or rule out those unmeasured causes.

## K=7 Repeatability

Offered load is 210 fps. Both runs pass integrity and drain to backlog 0, but
both show clear overload while arrivals continue.

| Run | Service rate [fps] | Peak backlog | Final-arrival backlog | Ready wait mean/p95/p99 [ms] | Local E2E mean/p95/p99 [ms] |
|---|---:|---:|---:|---|---|
| [Run1](b1_sync/k7/run1/summary.json) | 185.986617 | 1447 | 1447 | 3909.037 / 6721.555 / 6831.366 | 3928.497 / 6740.580 / 6848.861 |
| [Run2](b1_sync/k7/run2/summary.json) | 184.686039 | 1525 | 1525 | 4194.661 / 7088.772 / 7209.238 | 4213.896 / 7107.981 / 7227.004 |

| Run | `[10,59)` slope [frames/s] | R-squared | `[30,59)` slope [frames/s] | R-squared |
|---|---:|---:|---:|---:|
| Run1 | +23.123075 | 0.999159 | +24.051687 | 0.999117 |
| Run2 | +24.690160 | 0.999707 | +24.449049 | 0.998823 |

All consecutive full 1-second backlog-bin means strictly increase in both
runs. Selected bins show the trajectory (time-weighted mean frames):

| Bin [s] | Run1 | Run2 |
|---|---:|---:|
| 0-1 | 67.865 | 57.811 |
| 10-11 | 308.208 | 315.122 |
| 20-21 | 532.586 | 570.313 |
| 30-31 | 743.332 | 809.044 |
| 40-41 | 987.973 | 1066.724 |
| 50-51 | 1225.564 | 1310.630 |
| 58-59 | 1413.096 | 1490.525 |
| 59-final-arrival | 1435.369 | 1513.380 |

Overload is reproduced: service rate is below 210 fps, arrival-period backlog
grows persistently, a large backlog remains at the last arrival, and ready
queue waits reach seconds. This classification follows the trajectory and
service deficit, not latency magnitude alone. Eventual drain is separate from
real-time sustainability; K7 is not a measurement of a final capacity value.

## Current Interpretation

- K7: clear overload observed in Run1 and Run2.
- K6: not reproducibly low-backlog stable across Run1-3.
- K6: best described as near-critical / marginal across these observations.
- 180 fps is not yet established as repeatably sustainable capacity.
- Long-duration K6 characterization is the next priority, with repeats to
  distinguish recovery, a persistent plateau, and renewed growth.

Correctness PASS, eventual drain, stability within the observed window, and
long-duration sustainability are distinct claims. These observations preserve
the uncertainty about K6 and the unidentified cause of Run3's processing-time
increase. This documentation and artifact freeze introduced no source change,
new experiment, raw-artifact edit, or sample exclusion.
