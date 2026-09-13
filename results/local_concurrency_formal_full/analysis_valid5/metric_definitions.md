# Metric definitions audited against frozen implementation

Sources: [Formal runtime metadata](../c1/k2/run01/metadata.json), [runtime](../_campaign/profile_fullsource.py), [raw replay](../_campaign/base_analysis.py), [per-run extension](../_campaign/analyze_run.py), [integer timing/percentiles](../../../scripts/local/local_latency_breakdown_metrics.py), [independent validator](../_campaign/screening_metrics.py). The actual metadata/source definitions, not historical report labels, govern this analysis.

## Configuration and clocks

RT-DETR Warehouse v1.0.2, the recorded FP16 canonical engine, B=1, input 1×3×640×640; first K Warehouse_027 cameras; 30 offered frames/s/stream, 1800 frames/stream, 60-second offered window. MAXN, jetson_clocks OFF, unlocked DVFS; CUDA Graph OFF. One engine and C independent execution contexts, submission streams and private buffer sets. The engine records two TensorRT auxiliary streams per context; these are not C. No warm-up/sample exclusion. No new measurement is performed by this analysis.

Timestamps use `time.perf_counter_ns()` on a monotonic clock. All intervals below are half-open. t0 is the common logical-arrival epoch.

| Timestamp | Actual boundary |
|---|---|
| a | `t0 + (frame_id * 1_000_000_000) // 30`; phase-aligned logical scheduled arrival, not physical capture time |
| b | Front-end worker after arrival dequeue, immediately before pull-sample |
| r | State-lock-protected ready-queue enqueue completion; immediately after unbounded put returns, before counter/event publication |
| s | End of start accounting under state lock, immediately before lock release and `infer()` |
| c | First timestamp after `infer()` returns, host outputs available; before output-name validation |

## Deadline and completion rate

Deadline is **exactly 1/30 second = 33.333… ms after a**. A miss is `(c_ns - a_ns) * 30 > 1_000_000_000` (strict greater-than integer comparison). DMR is `100 * miss_frames / completed_frames`, over all frames including startup and drain. It is a nominal-period deadline, not an externally validated application SLA.

`completed_FPS = completed_frames / ((max(c_ns) - t0_ns) / 1e9)`. Its denominator is **completion elapsed time**, not 60 s and not process wall time. Consequently FPS can slightly exceed 30K because the last scheduled arrival is at 59.966… s and its completion can precede 60 s. `offered_load_fps = 30*K`. Near-offered throughput does not imply deadline satisfaction or mathematical queue stability.

`source_duration=60 s` is the configured offered/source window. `drain_duration=max(0,max(c)-t0-60s)` in seconds. It measures inference completion after the offered-window endpoint; it is not the entire EOS/cleanup interval. `run_wall_time` is parent-observed monotonic child elapsed time, including initialization and shutdown.

## Latency and percentile arithmetic

| Metric | Integer-ns definition |
|---|---|
| Start lag | b − a |
| Front-end | r − b |
| Queue waiting | s − r |
| Service | c − s |
| Local latency | c − a |

Front-end includes pull-sample waiting, map/access, preprocessing, unmap, ready-job preparation and lock/enqueue work; it is not isolated decoder execution time. Service includes input validation, pinned staging copy, async H2D, `execute_async_v3`, async D2H, own-stream synchronization and return. It is not pure GPU kernel latency.

Per frame, local = start lag + front-end + queue + service **exactly in integer ns**. Means inherit this additive identity (apart from floating serialization). Percentiles do not: **P95(X+Y) is generally not P95(X)+P95(Y)**. Component tails are compared separately; local P95/P99 always come from actual local-latency samples.

The frozen percentile function sorts n integer-ns samples and linearly interpolates at index `(n-1)*p/100` using exact rational arithmetic, then converts to ms. Per-condition P95 summaries are **means of the five run-level P95 values**, not pooled P95. The same qualification applies to P99. All figure error bars are sample SD of the five run-level metric values, never frame-level error bars.

## Application concurrency and waiting state

`C` is the application admission cap on independent in-flight frame-level requests. It is not K, B, CUDA threads/cores, auxiliary streams, kernel concurrency or physical GPU parallelism.

`A(t)=sum_j 1[s_j <= t < c_j]`. `observed_max_A` spans the whole run including drain. Primary mean A and fraction A=C integrate over `[t0,t0+60s)`. They are not GPU utilization. A>1 demonstrates overlapping host-observed request intervals, not an equal number of physically simultaneous kernels.

`Q(t)=sum_j 1[r_j <= t < s_j]`: canonical inference-ready waiting accounting. A dequeued request remains accounted as waiting until s. It is not a direct `Queue.qsize()` sample.

The new metric is

`fraction_time_cap_saturated_with_waiting = (1/60s) * integral_[t0,t0+60s) 1[A(t)=C and Q(t)>0] dt`.

This is an exact **cap-saturated-and-waiting state fraction**, an operational admission-blocked-state proxy using the canonical ready accounting. It does not by itself prove why a request waited, actual online publication/receipt times, or device utilization. Fraction A=C alone is cap saturation, including A=C with Q=0. We group all same-ns event deltas before integrating the next interval, so coincident completions/starts do not create spurious duration. The reconstructed A integral and cap fraction are cross-checked against saved canonical values.

Only columns r,s,c,a,frame ID and stream ID are read to calculate the new state intersection; b is additionally read for selected deadline-component diagnostics. Runs with exactly zero cap-saturated duration have exactly zero intersection and need no raw read solely for this metric. Auxiliary waiting-without-cap/any-wait fractions have unavailable entries where a raw read was unnecessary; their n_valid is explicit. The required cap-with-waiting metric has five values for every condition.

Mean A and service time are not independent evidence: the exact interval identity is `integral A(t) dt = sum of service-interval lengths clipped to that window`. With negligible boundary effects and fixed completed rate, mean A is approximately completion rate × mean service duration. A correlation between these two summaries alone therefore cannot establish that higher A caused longer service. Comparisons here are system responses to the configured C intervention at each K, with this accounting dependence acknowledged.

**0≤A≤C is an invariant of these fixed-C runs only.** A future non-preemptive decrease C_old→C_new can temporarily leave A>C_new while existing requests finish and new admission is restricted. No dynamic transition or GPU-internal kernel/resource contention was measured here.

## Backlog windows

`peak_waiting_queue` is peak canonical waiting depth over the whole run through drain. `time_weighted_waiting_queue` uses the canonical **first ready enqueue r through last ready enqueue r** interval; it does not share the fixed 60-second denominator of the new state fractions.

Waiting/active carryover percentages count the 1800 period-end boundaries `t0+floor((frame_id+1)*1e9/30)` where prior IDs (≤ that frame ID) remain waiting/active. Future IDs are not counted. The final boundary is included. A low final drain does not imply low earlier backlog or low miss ratio.

## Experimental unit, primary dataset and temporal pairing

The unit is one run. Five repeats reuse the same video content and quantify run-to-run system variability. They are not five independent workloads; 2,016,000 frames are not 2,016,000 independent statistical replicates. Each condition uses equal-run mean, median, sample SD (n−1 denominator), min, max and retained individual values. No significance tests, frame-level CIs, outlier removal, or causal resource attribution are used.

Primary valid5 has 279 original PASS runs plus replacement01. Physical acquisitions also retain the invalid-exit original run04: 281 acquisitions and 2,019,600 completed frames versus 280 primary runs and 2,016,000 primary frames. Original status remains 279 PASS/1 FAIL.

Original-round pairing uses only original PASS rows. K2/C1 Round 4 is missing; its C1→C2 comparisons have four pairs. Replacement statistical slot 4 is never an actual round/global-index label. The 55-cell complete temporal panel excludes K2/C1 from **all** rounds only for that explicitly labeled secondary panel. The original 279-row drift CSV remains unchanged.

Best-observed C and regret are post-hoc descriptive comparisons on this same dataset. Equal-K weighting is exploratory, not a deployment distribution. Neither gives an achievable online-controller improvement estimate. 'No clear single winner' is a cautious descriptive flag when the nearest mean gap does not exceed the larger of the two run SDs or does not favor the mean-minimizer in every available original-round pair; it is not a significance/equivalence test.
