# Local latency breakdown formal orchestration

This prepares execution; no formal benchmark was run during implementation.

From the repository root, print the 35 planned runs without importing GStreamer,
OpenCV or TensorRT, initializing a GPU, or creating any result directories:

```bash
/usr/bin/python3 -B scripts/local/run_local_latency_breakdown_formal.py --dry-run
```

Inspect processes, load, MAXN and readable DVFS controls on the **host**:

```bash
/usr/bin/python3 -B scripts/local/run_local_latency_breakdown_formal.py --preflight
```

This command never stops processes or changes clocks. A sandbox PID namespace
cannot provide the required host process inventory. Inspect nonessential Python
processes and tmux/screen experiments as well as the explicitly reported blockers.
Do not stop NVIDIA system services merely because they use Python.

## Fixed configuration and order

The runner fixes K=1..7, five runs/K, 30 FPS/stream, 1800 frames/stream, B=C=1,
and the canonical RT-DETR engine. The total is 35 runs and 252,000 frames.
Each run launches the existing profile in a fresh Python process. No warm-up,
source preparation, scheduler, pipeline, inference service, or queue change is
introduced by the runner.

`configs/local_latency_breakdown_formal_order.json` records the actual baseline
order. Raw scheduled-arrival timestamps, oc3-before file mtimes and exit-code
file mtimes agree. It is the following observed sequence:

| Repetition | K sequence |
|---|---|
| run01 | 1, 2, 3, 4, 5, 6, 7 |
| run02 | 2, 3, 4, 5, 6, 7, 1 |
| run03 | 3, 4, 5, 6, 7, 1, 2 |
| run04 | 4, 5, 6, 7, 1, 2, 3 |
| run05 | 5, 6, 7, 1, 2, 3, 4 |

The configuration pins the evidence hashes and source versions. Mapping is also
checked against all 35 baseline summaries and console logs. The seven actual
videos remain Warehouse_027 Camera_0000 through Camera_0006, cumulatively by K.

## Explicit current cooldown protocol

Historical deliberate cooldown: **UNKNOWN**.
Current formal deliberate inter-run cooldown: **NONE**.

Historical deliberate cooldown could not be established. The new latency-breakdown formal protocol therefore uses no additional deliberate inter-run sleep; the next run starts after successful completion, cleanup, and validation of the preceding run.

This is an explicit protocol decision by the experiment owner on 2026-09-10,
not a claim to reproduce historical cooldown. Observed wall-clock gaps do not
establish deliberate sleep, and no 10/30/60-second delay or temperature gate is
inferred from them. The runner prohibits nonzero deliberate waits and does not
call sleep. Each preceding child finishes pipeline/thread/TensorRT cleanup and
exits; artifact validation must succeed before the next planned run's preflight
and setup begin. The verified rotation order is unchanged, so each repetition
starts with a different K rather than fixing a time position to one K.

Before actual execution, finish this Codex session and review nonessential host
processes (Jetson Power GUI, update-manager, gnome-software, update-notifier,
user Python workloads, profile_*, trtexec, gst-launch, ffmpeg). Do not stop an
NVIDIA system service merely because it uses Python. No processes are stopped
by the runner.

Run from the repository root, in a host terminal after cleanup:

```bash
/usr/bin/python3 -B scripts/local/run_local_latency_breakdown_formal.py --preflight
```

Only after inspecting that preflight, the single formal command is:

```bash
/usr/bin/python3 -B scripts/local/run_local_latency_breakdown_formal.py --execute
```

The formal command is documentation only in this final pre-run task: it is not
executed by Codex. Actual execution independently repeats its preflight and
collision checks.

## Output and validation

The only formal root is `results/local_latency_breakdown/`; its existing
`_smoke/` subtree is ignored and preserved. Any other existing root entry is a
collision. Existing runs are never resumed, retried or overwritten. Symlink
output paths are rejected; directory/file creation is exclusive.

Formal runs write `kK/runNN/per_frame.csv` with exactly the existing ten columns.
Additional run-local raw-ns, validation and metadata evidence supports the
orchestrator's post-run checks. Run logs live under each `kK/`; orchestration
preflight/failure evidence lives under `k1/`.

Every run must pass total and per-stream arrival/sample/preprocessed/completion
counts, exact IDs 0..1799, raw timing ordering/decomposition, phase alignment,
single-service nonoverlap, event sequence/depth/counters, queue integral and
drain checks. The CSV is compared against raw-ns records and exact deadline
decisions. Any child exit or validation failure stops before the next run.

Only after all 35 pass are the root summaries (exact 14/15/5-column schemas) and
`experiment_metadata.json` generated. K metrics are arithmetic means of five
run statistics, including percentiles, miss percentages and queue metrics;
frames/events are never pooled across repetitions.

## Scope of profile changes

The profile's existing smoke arguments retain their defaults and restrictions.
The added `--formal` mode permits only 1800 frames, K=1..7, run01..run05 and the
exact formal output path. Output filenames, artifact classification and run IDs
are adapted to formal mode. The measurement block, including its timing and
queue validations, is byte-for-byte identical to the smoke-tested version.
TensorRT/pipeline preparation differs only in the setup failure artifact path.
The metrics and existing test files are unchanged.

The complete before/after diff and preservation records for this preparation
are in `logs/local_latency_orchestration_20260910T160911/`.

CPU-only tests (synthetic fixtures and mocked child execution, no inference):

```bash
/usr/bin/python3 -B scripts/local/test_local_latency_breakdown_formal.py -v
/usr/bin/python3 -B scripts/local/test_local_latency_breakdown.py -v
```
