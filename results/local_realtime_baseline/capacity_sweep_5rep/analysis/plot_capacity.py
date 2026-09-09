#!/usr/bin/env python3
"""Offline aggregation of the fixed official 35-run matrix; never runs a profiler.

Run with .venv/bin/python. All outputs are exclusive-create; existing files abort.
The sibling b1_sync tree is opened read-only. No historical inputs are discovered.
"""
from __future__ import annotations

import csv
import hashlib
import json
import math
import os
from pathlib import Path
import re
import statistics as st
import sys
import tempfile

OUT = Path(__file__).resolve().parent
RAW = OUT.parent / "b1_sync"
OUTPUTS = ["per_run_summary.csv", "per_k_summary.csv", "per_k_summary_full.csv", "local_capacity_main.pdf",
           "local_capacity_main.png", "analysis_notes.md", "analysis_provenance.json"]
DEADLINE_MS = 1000.0 / 30.0
VIDEO_BASE = "/home/ainet/datasets/PhysicalAI-SmartSpaces/MTMC_Tracking_2026/test/Warehouse_027/videos"
ENGINE = "models/rtdetr_warehouse_v1.0.2.fp16.b1.canonical.engine"
TS = ["scheduled_arrival_s", "actual_arrival_enqueue_s", "front_end_start_s",
      "ready_s", "inference_start_s", "completion_s"]
DERIVED = {"scheduler_lag_ms": (1, 0), "arrival_queue_wait_ms": (2, 1),
           "scheduled_to_front_end_ms": (2, 0), "front_end_observed_ms": (3, 2),
           "ready_queue_wait_ms": (4, 3), "inference_ms": (5, 4),
           "local_e2e_ms": (5, 0)}


def require(ok, message):
    if not ok:
        raise ValueError(message)


def sha(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def snapshot():
    return {str(p.relative_to(RAW)): sha(p) for p in sorted(RAW.rglob("*")) if p.is_file()}


def percentile(values, p):
    a = sorted(values)
    x = (len(a) - 1) * p
    lo, hi = math.floor(x), math.ceil(x)
    return a[lo] + (a[hi] - a[lo]) * (x - lo)


def read_run(k, run, deadline_counts=None):
    folder = RAW / f"k{k}"
    stem = f"run{run}"
    paths = [folder / stem / f for f in ("per_frame.csv", "summary.json")]
    paths += [folder / f"{stem}_{s}" for s in
              ("console.log", "exit_code.txt", "oc3_before.txt", "oc3_after.txt")]
    require(all(p.is_file() and p.stat().st_size for p in paths), f"{k}/{run}: artifacts")
    summary = json.loads(paths[1].read_text())
    require(paths[3].read_text().strip() == "0", f"{k}/{run}: exit")
    before, after = [p.read_text().strip() for p in paths[4:]]
    require(re.fullmatch(r"[0-9]+", before) and re.fullmatch(r"[0-9]+", after)
            and int(before) == int(after), f"{k}/{run}: OC3")
    console = paths[2].read_text()
    require("termination: bounded workload fully drained" in console, "drain marker")
    require(not re.search(r"\b(fatal|error|traceback)\b|(?:early|premature)\s+EOS",
                          console, re.I), f"{k}/{run}: console error")
    require(summary["validation"] == "pass" and summary["errors"] == [], "validation")
    config = dict(K=k, fps=30, frames_per_stream=1800, B=1, C=1, engine=ENGINE,
                  videos=[f"{VIDEO_BASE}/W027_Camera_{i:04d}.mp4" for i in range(k)])
    for key, value in config.items():
        require(summary["configuration"][key] == value, f"configuration: {key}")
    counts = ("arrivals", "source_samples_pulled", "completions")
    require(all(summary["counts"][key] == k * 1800 for key in counts), "total counts")
    streams = summary["per_stream_counts"]
    require(len(streams) == k and {s["stream_id"] for s in streams} == set(range(k)), "streams")
    require(all(s[key] == 1800 for s in streams for key in counts), "stream counts")
    with paths[0].open(newline="") as f:
        rows = list(csv.DictReader(f))
    require(len(rows) == k * 1800, "row count")
    keys = [(int(r["stream_id"]), int(r["frame_id"])) for r in rows]
    require(len(set(keys)) == len(keys) and set(keys) ==
            {(s, n) for s in range(k) for n in range(1800)}, "logical IDs")
    t0 = float(rows[keys.index((0, 0))][TS[0]])
    values = {key: [] for key in DERIVED}
    events = []
    for row in rows:
        times = [float(row[key]) for key in TS]
        require(all(math.isfinite(x) for x in times), "nonfinite timestamp")
        require(all(a <= b for a, b in zip(times, times[1:])), "timestamp ordering")
        require(times[0] == t0 + int(row["frame_id"]) / 30.0, "schedule / common t0")
        for key, (end, start) in DERIVED.items():
            value = (times[end] - times[start]) * 1000
            require(float(row[key]) == value, f"derived mismatch: {key}")
            values[key].append(value)
        events.extend(((times[1], 0), (times[5], 1)))
    events.sort()  # ARRIVAL (0) before COMPLETION (1) at equal timestamps.
    first = min(t for t, kind in events if kind == 0)
    last = max(t for t, kind in events if kind == 0)
    backlog = peak = at_final = 0
    prev = first
    areas = []
    for t, kind in events:
        # Integrate the piecewise-constant pre-event state only inside [first,last].
        if prev < last:
            areas.append(backlog * (min(t, last) - prev))
        backlog += 1 if kind == 0 else -1
        require(backlog >= 0, "negative backlog")
        peak = max(peak, backlog)
        if kind == 0:
            at_final = backlog
        prev = t
    reconstructed = dict(peak=peak, at_final_arrival=at_final, after_drain=backlog)
    require(all(summary["backlog"][key] == val for key, val in reconstructed.items()),
            "summary backlog")
    require(backlog == 0 and last > first, "final drain / arrival window")
    e2e, ready = values["local_e2e_ms"], values["ready_queue_wait_ms"]
    if deadline_counts is not None:
        deadline_counts[k, run] = (sum(value > DEADLINE_MS for value in e2e), len(e2e))
    result = dict(K=k, Run=run, offered_load_fps=30*k, rows=len(rows),
                  e2e_mean_ms=st.mean(e2e), e2e_median_ms=percentile(e2e, .5),
                  e2e_p95_ms=percentile(e2e, .95), ready_wait_mean_ms=st.mean(ready),
                  ready_wait_p95_ms=percentile(ready, .95),
                  front_end_mean_ms=st.mean(values["front_end_observed_ms"]),
                  inference_mean_ms=st.mean(values["inference_ms"]),
                  peak_backlog=peak, final_arrival_backlog=at_final, final_backlog=backlog,
                  time_weighted_backlog=math.fsum(areas)/(last-first))
    return result


def compact_summary(aggregates, deadline_counts):
    records = []
    for a in aggregates:
        counts = [deadline_counts[a["K"], run] for run in range(1, 6)]
        misses, frames = map(sum, zip(*counts))
        record = dict(K=a["K"], offered_load_fps=a["offered_load_fps"],
                      run_count=a["run_count"], deadline_ms=DEADLINE_MS,
                      deadline_miss_pct=100 * misses / frames)
        for metric in ("e2e_mean_ms", "e2e_p95_ms", "ready_wait_mean_ms",
                       "front_end_mean_ms", "inference_mean_ms"):
            record[metric] = a[metric + "_mean"]
        for metric in ("peak_backlog_mean", "final_arrival_backlog_mean",
                       "time_weighted_backlog_mean"):
            record[metric] = a[metric]
        records.append(record)
    return records


def write_csv(name, records):
    with (OUT / name).open("x", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(records[0]))
        writer.writeheader()
        writer.writerows(records)


def plot(runs, aggregates):
    # Keep font caches outside the source tree and derived publication outputs.
    with tempfile.TemporaryDirectory(prefix="capacity-mpl-") as cache:
        os.environ["MPLCONFIGDIR"] = cache
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.lines import Line2D
        from matplotlib.ticker import ScalarFormatter, NullFormatter
        plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 9,
                             "axes.labelsize": 10, "pdf.fonttype": 42,
                             "ps.fonttype": 42, "axes.spines.top": False,
                             "axes.spines.right": False})
        fig, axes = plt.subplots(1, 2, figsize=(7.2, 3.35))
        panels = [("e2e_mean_ms", "Local E2E latency [ms]", "#0072B2", [20, 50, 100, 500, 1000, 5000]),
                  ("time_weighted_backlog", "Time-weighted backlog [frames]", "#D55E00", [.5, 1, 5, 10, 50, 100, 500, 1000])]
        for idx, (ax, (metric, label, color, ticks)) in enumerate(zip(axes, panels)):
            for k in range(1, 8):
                group = [r for r in runs if r["K"] == k]
                y = [r[metric] for r in group]
                require(all(v > 0 for v in y), "log plot requires positive data; no offset allowed")
                # Fixed display offsets only; true offered load is exactly 30*K.
                ax.scatter([30*k + dx for dx in (-4, -2, 0, 2, 4)], y,
                           s=22, facecolors="none", edgecolors=color, linewidths=1, zorder=4)
                a = aggregates[k-1]
                mean, sd = a[metric+"_mean"], a[metric+"_sample_sd"]
                require(mean-sd > 0, "SD extends outside log domain")
                ax.errorbar(30*k, mean, yerr=sd, fmt="D", color="black", ms=4,
                            capsize=3, elinewidth=1, zorder=5)
            ax.set_yscale("log")
            ax.set_yticks(ticks)
            ax.yaxis.set_major_formatter(ScalarFormatter())
            ax.yaxis.set_minor_formatter(NullFormatter())
            ax.set_xlim(20, 220)
            ax.set_xticks(list(range(30, 211, 30)))
            ax.set_xlabel("Offered load [frames/s]")
            ax.set_ylabel(label)
            ax.grid(axis="y", which="major", color="0.88", linewidth=.6)
            ax.set_axisbelow(True)
            top = ax.secondary_xaxis("top", functions=(lambda x: x/30, lambda x: x*30))
            top.set_xticks(list(range(1, 8)))
            top.set_xlabel("Concurrent streams, K")
        axes[0].set_ylim(15, 7500)
        axes[1].set_ylim(.4, 1600)
        handles = [Line2D([], [], marker="o", color="0.35", markerfacecolor="none",
                          linestyle="none", markersize=5, label="Individual run (n = 5 per K)"),
                   Line2D([], [], marker="D", color="black", markersize=4,
                          label="Mean ± sample SD across runs")]
        fig.legend(handles=handles, loc="lower center", ncol=2, frameon=False, fontsize=8)
        fig.subplots_adjust(left=.09, right=.985, bottom=.22, top=.78, wspace=.34)
        for extension in ("pdf", "png"):
            with (OUT / f"local_capacity_main.{extension}").open("xb") as f:
                fig.savefig(f, format=extension, dpi=400, bbox_inches="tight", pad_inches=.06)
        plt.close(fig)
        return matplotlib.__version__


NOTES = """# Official local capacity sweep: derived analysis

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
"""


def main():
    require(not any((OUT / name).exists() or (OUT / name).is_symlink() for name in OUTPUTS),
            "derived output collision: no overwrite")
    before = snapshot()
    require(len(before) == 210, "expected exactly 210 official input files")
    deadline_counts = {}
    runs = [read_run(k, r, deadline_counts) for k in range(1, 8) for r in range(1, 6)]
    require(sum(r["rows"] for r in runs) == 252000, "total rows")
    metrics = list(runs[0])[4:]
    aggregates = []
    for k in range(1, 8):
        a = dict(K=k, offered_load_fps=30*k, run_count=5)
        for metric in metrics:
            values = [r[metric] for r in runs if r["K"] == k]
            for suffix, func in [("mean", st.mean), ("median", st.median),
                                 ("sample_sd", st.stdev), ("min", min), ("max", max)]:
                a[f"{metric}_{suffix}"] = func(values)
        aggregates.append(a)
    require(snapshot() == before, "raw changed during reading")
    write_csv("per_run_summary.csv", runs)
    write_csv("per_k_summary.csv", compact_summary(aggregates, deadline_counts))
    write_csv("per_k_summary_full.csv", aggregates)
    mpl_version = plot(runs, aggregates)
    (OUT / "analysis_notes.md").open("x").write(NOTES)
    require(snapshot() == before, "raw changed during output generation")
    provenance = dict(input_root=str(RAW), runs_used=35, rows_used=252000,
                      included_runs=[f"k{r['K']}/run{r['Run']}" for r in runs],
                      python=sys.version, matplotlib=mpl_version, raw_sha256=before,
                      raw_hashes_unchanged=True, script_sha256=sha(Path(__file__)),
                      outputs_sha256={name: sha(OUT/name) for name in OUTPUTS[:-1]},
                      validation="35/35 PASS; exact derived, schedule, ID, count and backlog checks")
    with (OUT / "analysis_provenance.json").open("x") as f:
        json.dump(provenance, f, indent=2)
        f.write("\n")
    print("PASS: 35 runs, 252000 rows; raw SHA256 unchanged 210/210")
    for a in aggregates:
        print(f"K={a['K']} E2E={a['e2e_mean_ms_mean']:.6f} ± "
              f"{a['e2e_mean_ms_sample_sd']:.6f} ms; TW backlog="
              f"{a['time_weighted_backlog_mean']:.6f} ± "
              f"{a['time_weighted_backlog_sample_sd']:.6f}")


if __name__ == "__main__":
    main()
