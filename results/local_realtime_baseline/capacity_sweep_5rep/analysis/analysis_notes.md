# Official local capacity sweep: derived analysis

Only the sibling `b1_sync/` official K=1..7, Run=1..5 matrix is included.
35 separate repeated profiler runs; 252,000 frames total. The replicate unit is
the run (five per K); statistical IID is not established. Historical baseline
and long-duration results are excluded. No run or startup frame is excluded.

## Definitions

All latency values are in milliseconds, backlog values in frames. Percentiles
use linear interpolation at sorted index (N-1)*p. Local E2E in milliseconds is
`(completion_s - scheduled_arrival_s) * 1000`.
No frame-level confidence intervals are constructed.

`per_run_summary.csv` preserves all 35 individual repeated-run results with
the existing run-level schema and calculation definitions unchanged.

`per_k_summary.csv` is a compact human-readable summary with exactly 13 columns,
in this order: `K`, `offered_load_fps`, `run_count`, `deadline_ms`,
`deadline_miss_pct`, `e2e_mean_ms`, `e2e_p95_ms`, `ready_wait_mean_ms`,
`front_end_mean_ms`, `inference_mean_ms`, `peak_backlog_mean`,
`final_arrival_backlog_mean`, `time_weighted_backlog_mean`.
Offered load is 30*K and run_count is five. Each representative latency/time/
backlog value is the arithmetic mean of five run-level values; in particular,
e2e_p95_ms averages the five run-level p95 values. SD, median, min, max and
final_backlog aggregates are omitted. All 35 runs drain to final_backlog=0;
final-arrival backlog is retained because it measures pending work at the last
actual arrival. Run-to-run variability remains available in per_run_summary.csv.
`per_k_summary_full.csv` preserves the original detailed K-level aggregates:
arithmetic mean, median, sample SD (n-1), min and max for each run-level metric.

The analysis evaluates a candidate 33.333-ms E2E deadline, equal in duration
to the 30-FPS arrival interval. `deadline_ms = 1000.0 / 30.0`, or
33.333333333333336 ms. Arrival cadence and an application SLA are conceptually
distinct; this candidate is not a universally required deadline for 30 FPS.
`deadline_miss_pct = 100 * total_deadline_misses / total_frames` pools all frames
of the five official runs at each K. A miss means `local_e2e_ms > deadline_ms`;
equality is not a miss. Equal frame counts across the five runs make this equal
to the arithmetic mean of their individual miss percentages.

Backlog events use actual_arrival_enqueue_s (+1) and completion_s (-1), with
ARRIVAL before COMPLETION on exact ties. Final-arrival backlog is measured
immediately after the last ARRIVAL event, before any tied COMPLETION event.
Time-weighted backlog is the piecewise-constant backlog integral divided by
the duration from first to last actual arrival. Drain after that endpoint is
excluded from this time average, but all completed jobs are used for latency.

## Main figure caption

Local capacity characterization with B=1, C=1, 30 frames/s per stream,
phase-aligned logical arrivals and 1,800 frames per stream. Each K has five
separate repeated runs. (a) Mean local E2E latency per run. (b) Time-weighted
backlog during the actual-arrival period per run. Open circles show all five
run values; black diamonds and error bars show the arithmetic mean and sample
standard deviation across runs, not a confidence interval. Horizontal offsets
of -4,-2,0,2,4 frames/s separate Run1..Run5 visually; true load is 30*K for all
five points in each group. Both y axes are logarithmic. All plotted values and
mean-minus-SD bounds are strictly positive: no zero replacement, epsilon offset,
clipping, or omitted K7 observations is used. Error bars remain five-run sample
SD (n-1), computed from the detailed aggregates independently of the compact CSV.

## Interpretation and scope

K1-K5: observed bounded / underloaded over this protocol.
K6: observed bounded over these five 60-second runs, with variable queueing
tails; a near-capacity/marginal operating point. Long-term sustainability is
not established by this dataset. K7: persistent overload reproduced in 5/5
runs in the preceding full audit, with service deficit and positive backlog
slope. The observed transition lies between 180 and 210 frames/s under this
protocol. No physical cause of K6 variability is inferred. All integrity-PASS
runs are retained regardless of latency or backlog magnitude.

## Reproduction

Use the repository's existing `.venv/bin/python` (Matplotlib 3.11.1) to run
`plot_capacity.py`. The script refuses to overwrite any derived output. To
reproduce separately, copy the script to a new sibling directory of `b1_sync`
and invoke it there. It reads only that fixed sibling input matrix, validates
it before publishing, and records SHA256 hashes of all 210 inputs. No profiler,
CUDA, TensorRT, GStreamer, or video decode code is imported or executed.
