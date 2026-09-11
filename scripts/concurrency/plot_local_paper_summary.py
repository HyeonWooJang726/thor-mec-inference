#!/usr/bin/env python3
"""Two paper figures from immutable Local artifacts; no benchmark invocation.

Reuses the canonical plotting source's rcParams, palette and errorbar styling.
A separate entrypoint is needed because that historical script writes four
fixed canonical figures and has no cross-campaign data-selection interface.
Only the matched C2/C4 full-source campaign is used for the concurrency figure.
"""

import argparse
import ast
import collections
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import statistics
import tempfile

os.environ["MPLCONFIGDIR"] = tempfile.mkdtemp(prefix="thor-paper-mpl-")
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
CANONICAL = ROOT / "results/local_canonical_c2"
CONCURRENCY = ROOT / "results/local_inference_concurrency"
TARGETED = CONCURRENCY / "c2_vs_c4_fullsource_validation"
STYLE_SOURCE = CANONICAL / "analysis/plot_figures.py"
METRICS = ["deadline_miss_pct", "queue_wait_mean_ms", "inference_mean_ms"]


def read_csv(path):
    with path.open() as stream:
        return list(csv.DictReader(stream))


def write_csv(path, rows):
    with path.open("x", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def dump(path, value):
    with path.open("x") as stream:
        json.dump(value, stream, indent=2)
        stream.write("\n")


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def inherited_style():
    """Read literals only; do not import or execute the old artifact script."""
    tree = ast.parse(STYLE_SOURCE.read_text())
    palette, rc = {}, None
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if ast.unparse(node.func) == "plt.rcParams.update":
                rc = ast.literal_eval(node.args[0])
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            name = node.targets[0]
            if isinstance(name, ast.Name) and name.id in {"blue", "red", "green", "orange"}:
                palette[name.id] = ast.literal_eval(node.value)
    assert rc and set(palette) == {"blue", "red", "green", "orange"}
    return rc, palette


def audit_coverage():
    specs = [
        (CANONICAL, "formal_plan.json", "formal_integrity_report.json", "canonical formal", True),
        (CONCURRENCY / "formal_control", "formal_plan.json", "formal_integrity_report.json", "C1/C2 formal control; separate campaign", False),
        (TARGETED, "run_plan.json", "fullsource_integrity_report.json", "matched full-source targeted validation", True),
        (CONCURRENCY / "c356_fullsource_sanity", "run_plan.json", "integrity_report.json", "full-source sanity; n=1", False),
        (CONCURRENCY / "application_c247_screening_v2/bounded_contract_campaign", "screening_plan.json", "screening_integrity_report.json", "30-second bounded screening; n=2", False),
        (CONCURRENCY / "application_c247_screening", "screening_plan.json", "screening_integrity_report.json", "failed/incomplete historical screening", False),
        (CONCURRENCY / "application_c247_screening_v2", "screening_plan.json", "screening_integrity_report.json", "blocked plan; no observations at this root", False),
    ]
    coverage = []
    for base, plan_name, integrity_name, kind, used in specs:
        plan = json.loads((base / plan_name).read_text())
        integrity = json.loads((base / integrity_name).read_text())
        rows = read_csv(base / "per_run_summary.csv")
        cells = collections.Counter((int(r["C"]), int(r["K"])) for r in rows)
        coverage.append({
            "root": str(base.relative_to(ROOT)), "classification": kind,
            "selected": used, "summary_csv_rows_including_plan_placeholders": len(rows),
            "summary_cells": [{"C": c, "K": k, "rows": n} for (c, k), n in sorted(cells.items())],
            "integrity_status": integrity.get("validation", integrity.get("status")),
            "valid_runs": integrity.get("valid_runs", integrity.get("completed_valid_runs")),
            "plan_metadata": {k: v for k, v in plan.items() if not isinstance(v, (dict, list))},
            "source_plan": plan_name, "source_integrity": integrity_name,
        })
    micro = CONCURRENCY / "c1_to_c7_selection_probe/run_summary.csv"
    rows = read_csv(micro)
    coverage.append({"root": str(micro.parent.relative_to(ROOT)), "classification": "TensorRT-only micro-probe; no application K/deadline data",
                     "selected": False, "C_counts": dict(collections.Counter(r["C"] for r in rows)), "runs": len(rows)})
    return coverage


def replay(base, plan_name, integrity_name, figure):
    """Recompute only plotted metrics from integer timestamps, per run first."""
    plan = json.loads((base / plan_name).read_text())
    integrity = json.loads((base / integrity_name).read_text())
    assert integrity["validation"] == "PASS"
    assert plan["fps"] == 30 and plan["frames_per_stream"] == 1800
    assert plan["offered_duration_s"] == 60 and plan["batch"] == 1
    assert "natural full-source" in plan["source_termination"]
    summary = read_csv(base / "per_run_summary.csv")
    assert len(summary) == plan["expected_runs"]
    planned = {(int(r["C"]), int(r["K"]), f"run{int(r['rep']):02d}") for r in plan["runs"]}
    observed = {(int(r["C"]), int(r["K"]), r["run_id"]) for r in summary}
    assert planned == observed and len(observed) == len(summary)
    rows, validation = [], []
    for stored in summary:
        c, k, run_id = int(stored["C"]), int(stored["K"]), stored["run_id"]
        run_dir = base / f"k{k}" / run_id if base == CANONICAL else base / f"c{c}" / f"k{k}" / run_id
        raw = run_dir / "per_frame.csv"
        seen, count, miss, queue_ns, service_ns = set(), 0, 0, 0, 0
        with raw.open() as stream:
            for frame in csv.DictReader(stream):
                a, b, r, s, end = [int(frame[key]) for key in ("a_ns", "b_ns", "r_ns", "s_ns", "c_ns")]
                assert a <= b <= r <= s <= end
                assert end-a == (b-a)+(r-b)+(s-r)+(end-s)
                assert int(frame["queue_wait_ns"]) == s-r
                assert int(frame["inference_ns"]) == end-s
                assert int(frame["local_latency_ns"]) == end-a
                missed = (end-a)*30 > 1_000_000_000
                assert int(frame["deadline_miss"]) == int(missed)
                assert int(frame["C"]) == c and int(frame["K"]) == k and frame["run_id"] == run_id
                identity = (int(frame["stream_id"]), int(frame["frame_id"]))
                assert identity not in seen
                seen.add(identity)
                count += 1
                miss += int(missed)
                queue_ns += s-r
                service_ns += end-s
        assert seen == {(stream, frame) for stream in range(k) for frame in range(1800)}
        assert count == int(stored["frames"]) == k*1800
        metrics = {"deadline_miss_pct": miss/count*100,
                   "queue_wait_mean_ms": queue_ns/count/1e6,
                   "inference_mean_ms": service_ns/count/1e6}
        for metric, value in metrics.items():
            assert math.isclose(value, float(stored[metric]), rel_tol=1e-12, abs_tol=1e-10), (raw, metric)
        rows.append({"figure": figure, "C": c, "K": k, "run_id": run_id,
                     "frames": count, **metrics, "source_raw": str(raw.relative_to(ROOT))})
        validation.append({"C": c, "K": k, "run_id": run_id, "frames": count,
                           "ids_timestamps_decomposition_miss": "PASS", "plotted_summary_metrics_match": "PASS",
                           "raw_sha256": digest(raw)})
    assert sum(r["frames"] for r in rows) == plan["expected_frames"]
    return rows, validation, plan


def aggregate(rows):
    result = []
    for figure, c, k in sorted({(r["figure"], r["C"], r["K"]) for r in rows}):
        cell = [r for r in rows if (r["figure"], r["C"], r["K"]) == (figure, c, k)]
        for metric in METRICS:
            values = [r[metric] for r in cell]
            result.append({"figure": figure, "C": c, "K": k, "metric": metric,
                           "n_runs": len(values), "mean": statistics.mean(values),
                           "sample_sd": statistics.stdev(values), "min": min(values), "max": max(values)})
    return result


def render(out, rows, rc, colors):
    plt.rcParams.update(rc)
    plt.rcParams.update({"figure.facecolor": "white", "axes.facecolor": "white",
                         "grid.alpha": .12, "pdf.fonttype": 42, "ps.fonttype": 42})
    queue_color, service_color = colors["red"], colors["green"]
    figures = []

    def values(figure, c_values, k_values, metric):
        cells = [next(r for r in rows if (r["figure"], r["C"], r["K"], r["metric"]) ==
                      (figure, c, k, metric)) for c, k in zip(c_values, k_values)]
        return np.array([r["mean"] for r in cells]), np.array([r["sample_sd"] for r in cells])

    def errorbar(ax, x, mean, sd, label, color, marker):
        return ax.errorbar(x, mean, yerr=sd, label=label, color=color,
                           marker=marker, capsize=3, lw=1.5, markersize=6)

    def layout(fig, axes):
        fig.subplots_adjust(left=.08, right=.98, bottom=.27, top=.83, wspace=.3)
        for ax in axes:
            ax.grid(axis="x", visible=False)
            ax.tick_params(labelsize=10)

    def save(fig, axes, filename, description):
        fig.canvas.draw()
        renderer = fig.canvas.get_renderer()
        boxes = []
        for ax in axes:
            boxes.extend([ax.title.get_window_extent(renderer), ax.xaxis.label.get_window_extent(renderer),
                          ax.yaxis.label.get_window_extent(renderer)])
        legends = [legend for legend in fig.legends]
        boxes.extend(legend.get_window_extent(renderer) for legend in legends)
        canvas = fig.bbox
        assert all(canvas.contains(bb.x0, bb.y0) and canvas.contains(bb.x1, bb.y1) for bb in boxes)
        for legend in legends:
            bb = legend.get_window_extent(renderer)
            assert not any(bb.overlaps(ax.get_window_extent(renderer)) or
                           bb.overlaps(ax.xaxis.label.get_window_extent(renderer)) for ax in axes)
        for fmt in ("png", "pdf"):
            fig.savefig(out / f"{filename}.{fmt}", dpi=300, facecolor="white")
        figures.append({"name": filename, "description": description,
                        "figsize_inches": list(fig.get_size_inches()), "dpi_png": 300,
                        "layout_bounds_checks": "PASS", "axes": [
                            {"title": ax.get_title(), "xlabel": ax.get_xlabel(), "ylabel": ax.get_ylabel(),
                             "xscale": ax.get_xscale(), "yscale": ax.get_yscale(),
                             "xlim": list(ax.get_xlim()), "ylim": list(ax.get_ylim())} for ax in axes]})
        plt.close(fig)

    ks = list(range(1, 8))
    fig, axes = plt.subplots(1, 2, figsize=(10.8, 4.2))
    mean, sd = values(1, [2]*7, ks, "deadline_miss_pct")
    errorbar(axes[0], ks, mean, sd, "Candidate deadline misses", queue_color, "o")
    axes[0].set_ylabel("Candidate deadline misses (%)")
    axes[0].set_ylim(-3, 100)
    axes[0].set_title("Deadline degradation\nunder increasing load", fontsize=11)
    for metric, label, color, marker in [
            ("queue_wait_mean_ms", "Inference queue wait", queue_color, "o"),
            ("inference_mean_ms", "Inference service", service_color, "s")]:
        mean, sd = values(1, [2]*7, ks, metric)
        assert np.all(mean-sd > 0), "Cannot show a nonpositive arithmetic SD endpoint on log scale"
        errorbar(axes[1], ks, mean, sd, label, color, marker)
    axes[1].set_yscale("log")
    axes[1].set_ylabel("Mean per-frame duration (ms, log scale)")
    axes[1].set_title("Queueing–service trade-off", fontsize=11)
    for ax in axes:
        ax.set_xlabel("Video streams K")
        ax.set_xticks(ks)
        ax.set_xlim(.7, 7.3)
        ax.axvspan(5, 6, color="0.5", alpha=.08, linewidth=0, zorder=0)
    handles, labels = axes[1].get_legend_handles_labels()
    fig.legend(handles, labels, loc="lower center", bbox_to_anchor=(.5, .025),
               ncol=2, frameon=False, fontsize=10)
    layout(fig, axes)
    save(fig, axes, "final_deadline_knee", "Canonical C=2 only; n=5 per K; arithmetic run means and sample SD; neutral shading K5–K6.")

    cs = [2, 4]
    fig, axes = plt.subplots(1, 2, figsize=(10.8, 4.2))
    upper = []
    for k, color, marker in [(5, colors["blue"], "o"), (6, colors["orange"], "s"), (7, "#666666", "^")]:
        mean, sd = values(2, cs, [k]*2, "deadline_miss_pct")
        errorbar(axes[0], cs, mean, sd, f"K={k}", color, marker)
        upper.extend(mean+sd)
        best = int(np.argmin(mean))
        axes[0].scatter([cs[best]], [mean[best]], marker="*", s=110, color=color,
                        edgecolor="black", linewidth=.6, zorder=5, clip_on=False)
    axes[0].set_ylabel("Candidate deadline misses (%)")
    axes[0].set_ylim(0, max(100, math.ceil(max(upper)/10)*10))
    axes[0].set_title("Workload-dependent best concurrency", fontsize=11)
    handles, labels = axes[0].get_legend_handles_labels()
    handles.append(Line2D([], [], color="black", linestyle="none", marker="*", markersize=10))
    labels.append("Lowest observed mean")
    fig.legend(handles, labels, loc="lower center", bbox_to_anchor=(.30, .015),
               ncol=2, frameon=False, fontsize=9)
    for metric, label, color, marker in [
            ("queue_wait_mean_ms", "Inference queue wait", queue_color, "o"),
            ("inference_mean_ms", "Inference service", service_color, "s")]:
        mean, sd = values(2, cs, [6]*2, metric)
        errorbar(axes[1], cs, mean, sd, label, color, marker)
    axes[1].set_ylabel("Mean duration (ms)")
    axes[1].set_ylim(bottom=0)
    axes[1].set_title("Queueing–service trade-off\nacross concurrency", fontsize=11)
    axes[1].text(.03, .95, "K=6", transform=axes[1].transAxes, ha="left", va="top", fontsize=10)
    handles, labels = axes[1].get_legend_handles_labels()
    fig.legend(handles, labels, loc="lower center", bbox_to_anchor=(.76, .015),
               ncol=1, frameon=False, fontsize=10)
    for ax in axes:
        ax.set_xlabel("Inference concurrency C")
        ax.set_xticks(cs)
        ax.set_xlim(1.8, 4.2)
    layout(fig, axes)
    save(fig, axes, "final_concurrency_tradeoff", "Matched 60-second C2/C4 targeted campaign only; n=3 per (C,K). Stars: lowest observed mean among C={2,4}; no claim about untested C. Lines connect measured configurations, not interpolated observations. Unclipped arithmetic SD can extend beyond 100%.")
    return figures


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "results/figures")
    args = parser.parse_args()
    out = args.output.resolve()
    if out.exists() and any(out.iterdir()):
        raise SystemExit("Refusing to overwrite existing figures or artifacts; use a new output directory")
    out.mkdir(parents=True, exist_ok=True)
    coverage = audit_coverage()
    dump(out / "artifact_coverage_audit.json", coverage)
    first, v1, p1 = replay(CANONICAL, "formal_plan.json", "formal_integrity_report.json", 1)
    second, v2, p2 = replay(TARGETED, "run_plan.json", "fullsource_integrity_report.json", 2)
    for key in ["fps", "frames_per_stream", "offered_duration_s", "batch", "engine_sha256",
                "power", "DVFS", "jetson_clocks", "CUDA_Graph", "warmup", "sample_exclusion", "drop", "candidate_deadline", "source_termination"]:
        assert p1[key] == p2[key], key
    run_rows = first + second
    grouped = aggregate(run_rows)
    assert len(first) == 35 and len(second) == 18
    assert all(r["n_runs"] == (5 if r["figure"] == 1 else 3) for r in grouped)
    write_csv(out / "figure_run_statistics.csv", run_rows)
    write_csv(out / "figure_aggregates.csv", grouped)
    rc, colors = inherited_style()
    figures = render(out, grouped, rc, colors)
    dump(out / "figure_manifest.json", {"validation": "PASS", "figures": figures,
                                        "style_source": str(STYLE_SOURCE.relative_to(ROOT)),
                                        "style_source_sha256": digest(STYLE_SOURCE), "inherited_rcParams": rc,
                                        "inherited_palette": colors, "script_sha256": digest(Path(__file__)),
                                        "source_summary_sha256": {str((base / 'per_run_summary.csv').relative_to(ROOT)): digest(base / 'per_run_summary.csv') for base in [CANONICAL, TARGETED]},
                                        "output_sha256": {p.name: digest(p) for p in out.iterdir() if p.suffix in {".png", ".pdf"}}})
    dump(out / "replay_validation.json", {"validation": "PASS", "canonical_runs": len(first),
                                         "canonical_frames": sum(r["frames"] for r in first),
                                         "targeted_runs": len(second), "targeted_frames": sum(r["frames"] for r in second),
                                         "benchmark_executed": False, "raw_modified": False,
                                         "error_bars": "sample standard deviation of run-level statistics; ddof=1; not SEM or CI",
                                         "runs": v1+v2})
    def mean(fig, c, k, metric):
        return next(r["mean"] for r in grouped if (r["figure"], r["C"], r["K"], r["metric"]) == (fig, c, k, metric))
    m = lambda k, metric: mean(1, 2, k, metric)
    table = "\n".join(f"| {k} | {mean(2,2,k,'deadline_miss_pct'):.4f} | {mean(2,4,k,'deadline_miss_pct'):.4f} |"
                       for k in (5, 6, 7))
    (out / "figure_report.md").write_text(f"""# Two Local/concurrency paper figures

## Audit and cohort selection

Figure 1 reads `results/local_canonical_c2/per_run_summary.csv`, the formal plan and PASS integrity report, and independently replays every selected raw `k*/run*/per_frame.csv`. B=1, C=2, K=1–7; five runs per K, 60 seconds, full-source natural EOS, phase-aligned 30 FPS, 1800 frames/stream; 35 runs / 252,000 frames.

Figure 2 uses only `results/local_inference_concurrency/c2_vs_c4_fullsource_validation/`: its per_run_summary.csv, run_plan.json, fullsource_integrity_report.json and c*/k*/run*/per_frame.csv. C={{2,4}}, K={{5,6,7}}, three runs per cell; 18 runs / 194,400 frames. The same engine, input mapping, full-source workload, transfers, timing and termination definitions apply within this campaign; C changes only the concurrency resource count. Its two gate runs are excluded. This is matched targeted validation, not the canonical 35-run dataset. Canonical C2 and targeted C2 are not pooled.

Other coverage, excluded from these figures: formal C1/C2 control (K5–7, n=5; separate campaign); full-source C3/C5/C6 sanity (K5–7, n=1); C2/C4/C7 bounded 30-second screening (K5–7, n=2); engine-only C1–7 trtexec (n=5, no application deadlines). The completed bounded campaign is at `application_c247_screening_v2/bounded_contract_campaign/`; the parent root is a blocked NOT_RUN record. Original screening is incomplete (6 valid, 1 failed, 11 not run), so planned CSV rows must not be treated as observations. Smoke, stress and termination gates are excluded. No single matched full-source repeated C1–7 cohort exists; C7 is only a shorter bounded application reference. No missing combination is estimated or interpolated. Full audited coverage and original plan fields are in artifact_coverage_audit.json.

## Metrics and uncertainty

Candidate deadline: exactly 1/30 second (33.333333… ms), using `(c_ns-a_ns)*30 > 1000000000`. It is a cadence-based candidate, not an application SLA. Queue waiting is application-level inference-ready waiting `s-r`; active service is excluded. Inference service is `c-s`, including host-side execution/submission, transfers and stream-local completion, not pure GPU kernel time. Integer raw timestamps are the source of truth.

Each run's miss percentage and arithmetic per-frame means are recomputed independently and agree with its source summary within absolute 1e-10 / relative 1e-12 tolerance. Group points are arithmetic means of five (Figure 1) or three (Figure 2) run statistics. Error bars are sample SD (ddof=1), not SEM or confidence intervals. No pooling or exclusions; individual run values, min/max and SD are retained in the two CSVs. Figure 1's log axis shows arithmetic mean±SD in milliseconds, without a log-space aggregation. Figure 2's descriptive SD whisker can extend above 100%; it is not a probability interval and is not clipped.

## Figure 1 caption

**Deadline knee and queueing growth.** Canonical static Local runtime B=1, C=2. Left: candidate deadline misses as load increases. Right: application inference queue wait and host-visible inference service, on a logarithmic duration axis. Points and error bars show mean and sample SD across five 60-second full-source runs. Neutral shading marks K5–K6. Queue waiting grows at the same load transition as deadline degradation; this observational decomposition does not by itself prove exclusive causation. Service duration is not monotonic across all K.

K5→K6: miss {m(5,'deadline_miss_pct'):.4f}%→{m(6,'deadline_miss_pct'):.4f}%; queue {m(5,'queue_wait_mean_ms'):.4f}→{m(6,'queue_wait_mean_ms'):.4f} ms; service {m(5,'inference_mean_ms'):.4f}→{m(6,'inference_mean_ms'):.4f} ms. Absolute queue increase {m(6,'queue_wait_mean_ms')-m(5,'queue_wait_mean_ms'):.4f} ms exceeds service increase {m(6,'inference_mean_ms')-m(5,'inference_mean_ms'):.4f} ms. K7 miss reaches {m(7,'deadline_miss_pct'):.4f}% with {m(7,'queue_wait_mean_ms'):.4f} ms mean queue wait.

## Figure 2 caption

**Concurrency trade-off.** Only the matched 60-second full-source C={{2,4}} targeted campaign is shown. Left: candidate deadline misses at K5/K6/K7; stars mark the lowest observed mean among these two configurations for each workload. Connecting segments are guides between measured settings, not measurements of intermediate C. Right: at K6, higher concurrency reduces waiting while increasing host-visible inference service duration. Points and error bars summarize three runs per cell. No statistical-significance or globally best-concurrency claim is made; engine throughput screening and application QoS are separate evidence.

| K | C2 miss (%) | C4 miss (%) |
|---|---:|---:|
{table}

K6 queue: {mean(2,2,6,'queue_wait_mean_ms'):.4f}→{mean(2,4,6,'queue_wait_mean_ms'):.4f} ms. Service: {mean(2,2,6,'inference_mean_ms'):.4f}→{mean(2,4,6,'inference_mean_ms'):.4f} ms. This is consistent with increased per-request contention under concurrent execution; pure GPU contention and physical kernel overlap were not directly isolated/measured. Lower observed miss occurs at C2 for K5/K6 and C4 for K7; neither tested configuration dominates all three workloads.

## Reproduction and preservation

`python3 -B scripts/concurrency/plot_local_paper_summary.py --output <new-empty-directory>`

The new entrypoint reuses the historical canonical source's DejaVu Sans rcParams, metric colors, markers and errorbar style without importing/executing or changing that source. It writes PNG (300 dpi) and vector PDF; all existing figures and raw artifacts remain untouched. No benchmark, commit or push. See artifact_integrity_report.json for the independent pre/post file checks performed for this task.
""")
    print(json.dumps({"validation": "PASS", "canonical_runs": len(first), "targeted_runs": len(second),
                      "frames_replayed": sum(r["frames"] for r in run_rows), "output": str(out)}, indent=2))


if __name__ == "__main__":
    main()
