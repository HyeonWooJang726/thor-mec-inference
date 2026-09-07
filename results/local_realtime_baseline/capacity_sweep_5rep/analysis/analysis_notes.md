# Official local capacity sweep: derived analysis

Only the sibling `b1_sync/` official K=1..7, Run=1..5 matrix is included.
35 separate repeated profiler runs; 252,000 frames total. The replicate unit is
the run (five per K); statistical IID is not established. Historical baseline
and long-duration results are excluded. No run or startup frame is excluded.

## Definitions

All latency values are in milliseconds, backlog values in frames. Percentiles
use linear interpolation at sorted index (N-1)*p. Per-K columns summarize five
run-level values: arithmetic mean, median, sample SD (n-1), min, max. No frame-level
confidence intervals are constructed. E2E = completion - scheduled arrival.

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
clipping, or omitted K7 observations is used. 33.33 ms is an arrival cadence.

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
