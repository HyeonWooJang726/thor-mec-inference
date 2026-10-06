#!/usr/bin/env python3
"""Reproduce the final one-column Campaign 2 Section III figures.

Numeric source: paper/figure_data_section3.csv, read without regeneration.
The preserved plot_fig1.py loader verifies the canonical assignment table and
manifest and the five-run stream summaries. This entry point changes rendering
only; it never invokes an experimental analyzer or writes a source CSV.

Run: python3 -B paper/figures/campaign2/plot_section3_figures.py
Add --replace-generated to explicitly regenerate the four rendered files.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import runpy
import subprocess
import tempfile
from datetime import datetime, timezone

TASK = "CAMPAIGN2_SECTION3_FIGURES_FINALIZE_AND_PUSH"
CAMPAIGN = "block_b_edge_rate_sweep01"
PLACEMENTS = ("CONCENTRATED", "DISPERSED")
COLOR = {"CONCENTRATED": "#355C82", "DISPERSED": "#C17C3C"}
MARKER = {"CONCENTRATED": "o", "DISPERSED": "s"}
LABEL = {"CONCENTRATED": "Concentrated", "DISPERSED": "Dispersed"}
STYLE = {"CONCENTRATED": "-", "DISPERSED": "--"}
RATES = tuple(range(0, 65, 8))
WIDTH, FONT_SIZE, DPI = 3.5, 8.5, 600
FIGURE_HEIGHTS = {1: 4.5, 2: 5.3}
RENDERED = ("fig1_e16.pdf", "fig1_e16.png",
            "fig2_edge_rate_sweep.pdf", "fig2_edge_rate_sweep.png")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def utc():
    return datetime.now(timezone.utc).isoformat()


def load_sweep(root, e16_report):
    source = root / "paper/figure_data_section3.csv"
    previous = json.loads((root / "paper/validation_section3.json").read_text())
    rows = list(csv.DictReader(source.open()))
    rr = [r for r in rows if r["figure"] == "2"]
    require(all(r["campaign"] == CAMPAIGN and int(r["Local_FPS"]) +
                int(r["Edge_FPS"]) == 240 for r in rr), "Sweep campaign/rate mismatch")
    groups = {}
    summaries = [r for r in rr if r["record_type"] == "SUMMARY"]
    expected = {(metric, p, e) for e in RATES for p in
                (("LOCAL_ONLY",) if e == 0 else PLACEMENTS)
                for metric in (("R_min", "Local_assigned_TIR") if e == 0 else
                               ("R_min", "Local_assigned_TIR", "Edge_assigned_TIR"))}
    require(len(summaries) == len(expected), "Missing or duplicate sweep summaries")
    for s in summaries:
        key = (s["metric"], s["placement"], int(s["Edge_FPS"]))
        require(key in expected and key not in groups, "Unexpected sweep summary")
        raw = sorted([r for r in rr if r["record_type"] == "RUN"
                      and (r["metric"], r["placement"], int(r["Edge_FPS"])) == key],
                     key=lambda r: int(r["repeat"]))
        require([int(r["repeat"]) for r in raw] == list(range(1, 6)) and int(s["n"]) == 5,
                "Every condition/metric must include all five repeats")
        ids = [r["run_id"] for r in raw]
        require(len(set(ids)) == 5 and ids == json.loads(s["run_ids"]),
                "Sweep summary run IDs differ from the five observations")
        for r in raw:
            require(float(r["value"]) == int(r["timely_count"]) / int(r["denominator"]),
                    "Canonical ratio does not match its recorded integer count")
        values = [float(r["value"]) for r in raw]
        frozen = [float(s[k]) for k in ("mean", "min", "max")]
        check = [math.fsum(values) / len(values), min(values), max(values)]
        # Precision check only: no outcome threshold or significance test.
        require(all(math.isclose(a, b, rel_tol=0, abs_tol=1e-15)
                    for a, b in zip(frozen, check)), "Sweep summary/run mismatch")
        old = [r for r in previous["all_figure_mean_min_max"] if r["figure"] == 2
               and (r["metric"], r["placement"], r["Edge_FPS"]) == key]
        require(len(old) == 1 and frozen == [old[0][k] for k in ("mean", "min", "max")],
                "Sweep values differ from the existing validation source")
        if key[2] == 16:
            require(ids == e16_report["run_ids"][key[1]],
                    "Figures 1 and 2 use different E16 runs")
        groups[key] = {"mean": frozen[0], "min": frozen[1], "max": frozen[2],
                       "run_ids": ids, "n": len(raw)}
    require(set(groups) == expected, "Incomplete sweep series")
    all_ids = set().union(*(set(g["run_ids"]) for g in groups.values()))
    require(len(all_ids) == 85 and all_ids == set(previous["run_IDs_used"]),
            "The sweep must preserve all 85 measured run IDs")
    require(previous["valid_run_count"] == 85 and previous["invalid_run_count"] == 0
            and previous["nonzero_pair_count"] == 40,
            "Preserved Campaign 2 validation counts differ")
    references = sorted([r for r in rr if r["record_type"] == "REFERENCE"],
                        key=lambda r: int(r["Edge_FPS"]))
    require([int(r["Edge_FPS"]) for r in references] == list(RATES),
            "Arithmetic reference must include each recorded rate")
    reference_values = [float(r["value"]) for r in references]
    require(all(math.isclose(v, 1 - e / 240, rel_tol=0, abs_tol=1e-15)
                for e, v in zip(RATES, reference_values)), "Recorded arithmetic reference mismatch")
    return groups, reference_values, {
        "canonical_source": str(source.relative_to(root)),
        "valid_runs_in_existing_validation": previous["valid_run_count"],
        "invalid_runs_in_existing_validation": previous["invalid_run_count"],
        "nonzero_pairs_in_existing_validation": previous["nonzero_pair_count"],
        "all_measured_run_ids": sorted(all_ids), "summary_count": len(groups),
        "summaries": [{"metric": key[0], "placement": key[1], "Edge_FPS": key[2], **g}
                      for key, g in groups.items()],
        "reference_values": reference_values, "E0_Edge_TIR_undefined": True,
        "E16_runs_shared_with_Figure_1": True,
        "values_match_canonical_CSV_and_validation": True,
        "ANALYZER_SHA_RECORD_NOT_FOUND": previous["ANALYZER_SHA_RECORD_NOT_FOUND"],
    }


def render(matrices, stream_stats, groups, references, output):
    with tempfile.TemporaryDirectory(prefix="section3_final_fonts_") as cache:
        os.environ["MPLCONFIGDIR"] = cache
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib import font_manager
        from matplotlib.colors import ListedColormap
        from matplotlib.lines import Line2D
        from matplotlib.text import Text
        from matplotlib.transforms import Bbox
        import numpy as np

        font_manager.findfont(font_manager.FontProperties(family="STIXGeneral"),
                              fallback_to_default=False)
        plt.rcParams.update({"font.family": "STIXGeneral", "font.size": FONT_SIZE,
            "axes.labelsize": FONT_SIZE, "axes.titlesize": FONT_SIZE,
            "xtick.labelsize": FONT_SIZE, "ytick.labelsize": FONT_SIZE,
            "legend.fontsize": FONT_SIZE, "mathtext.fontset": "stix",
            "pdf.fonttype": 42, "ps.fonttype": 42, "axes.linewidth": .65,
            "xtick.major.size": 2.5, "ytick.major.size": 2.5,
            "xtick.major.width": .65, "ytick.major.width": .65,
            "figure.facecolor": "white", "axes.facecolor": "white",
            "savefig.facecolor": "white", "path.simplify": False})
        drawings, checks, coordinates = {}, {}, []
        range_points, legends = {}, {}

        def clean(ax):
            ax.spines[["top", "right"]].set_visible(False)
            ax.grid(False)
            ax.tick_params(pad=3)

        def series(ax, x, stats, placement, metric, label, connect):
            color = COLOR.get(placement, "#111111")
            marker = MARKER.get(placement, "D")
            style = STYLE.get(placement, "-")
            fill = "white" if metric == "Edge_assigned_TIR" else color
            mean, low, high = np.array(stats).T
            if connect:
                ax.plot(x, mean, color=color, linestyle=style, linewidth=1, zorder=2)
            ax.errorbar(x, mean, yerr=np.vstack([np.maximum(0, mean - low),
                                               np.maximum(0, high - mean)]),
                        fmt="none", ecolor=color, elinewidth=.8,
                        capsize=2, capthick=.8, zorder=2)
            marker_artist, = ax.plot(x, mean, linestyle="None", color=color, marker=marker,
                                    markersize=4.5, markerfacecolor=fill, markeredgewidth=.9,
                                    clip_on=False, zorder=3)
            require(np.array_equal(marker_artist.get_ydata(), mean), "Plotted means changed")
            range_points.setdefault(ax, []).extend(zip(x, low, high))
            coordinates.append({"series": label, "metric": metric,
                                "display_x": list(map(float, x)),
                                "mean": list(map(float, mean)), "min": list(map(float, low)),
                                "max": list(map(float, high)), "connected": connect})
            return Line2D([], [], color=color, marker=marker, markersize=4.5,
                          markerfacecolor=fill, markeredgewidth=.9,
                          linestyle=style if connect else "None", linewidth=1, label=label)

        def sweep_stats(metric, placement):
            return [[groups[metric, placement, e][k] for k in ("mean", "min", "max")]
                    for e in RATES[1:]]

        def one_e0(metric):
            return [[groups[metric, "LOCAL_ONLY", 0][k] for k in ("mean", "min", "max")]]

        fig1 = plt.figure(figsize=(WIDTH, FIGURE_HEIGHTS[1]))
        raster_height = (.79 * WIDTH * 8 / 30) / FIGURE_HEIGHTS[1]
        top = fig1.add_axes([.18, .77, .79, raster_height])
        bottom = fig1.add_axes([.18, .55, .79, raster_height], sharex=top)
        edge = fig1.add_axes([.18, .13, .79, .275])
        for ax, p in zip((top, bottom), PLACEMENTS):
            ax.pcolormesh(np.arange(31) - .5, np.arange(9) - .5, np.array(matrices[p]),
                          cmap=ListedColormap(["#F0F1F2", COLOR[p]]), vmin=0, vmax=1,
                          shading="flat", edgecolors="#D9DCE0", linewidth=.25,
                          rasterized=False, antialiased=False)
            ax.set(xlim=(-.5, 29.5), ylim=(7.5, -.5), yticks=range(8),
                   xticks=[0, 5, 10, 15, 20, 25, 29], ylabel="Stream ID")
            ax.set_aspect("equal", adjustable="box")
            ax.set_title(LABEL[p], color=COLOR[p], pad=4)
            clean(ax)
            ax.tick_params(pad=2)
        top.tick_params(labelbottom=False)
        bottom.set_xlabel("Frame index", labelpad=4)
        handles = []
        for p, offset in zip(PLACEMENTS, (-.14, .14)):
            handles.append(series(edge, np.arange(8) + offset, stream_stats[p],
                                  p, "Edge_assigned_TIR", LABEL[p], False))
        edge.set(xlim=(-.6, 7.6), ylim=(0, 1.02), xticks=range(8),
                 yticks=[0, .25, .5, .75, 1], xlabel="Stream ID", ylabel="Edge-assigned TIR")
        clean(edge)
        legends[edge] = edge.legend(handles=handles, loc="center left",
            bbox_to_anchor=(.005, .34), frameon=False, borderpad=0, borderaxespad=0,
            handlelength=1, handletextpad=.4, labelspacing=.3)
        fig1.text(.575, .445, "(a)", ha="center", va="center")
        fig1.text(.575, .022, "(b)", ha="center", va="center")
        drawings[1] = fig1

        fig2 = plt.figure(figsize=(WIDTH, FIGURE_HEIGHTS[2]))
        worst = fig2.add_axes([.18, .65, .79, .32])
        path = fig2.add_axes([.18, .115, .79, .395])
        for ax in (worst, path):
            clean(ax)
            ax.set(xlim=(-3, 67), xticks=RATES, xlabel="Edge assignment rate (frames/s)")
        worst.set(ylim=(.48, 1.05), yticks=[.5, .6, .7, .8, .9, 1], ylabel="Worst-stream TIR")
        ref, = worst.plot(RATES, references, color="#8A8A8A", linestyle="--",
                          linewidth=1, zorder=1, label="Local-assignment fraction")
        placement_handles = []
        for p, offset in zip(PLACEMENTS, (-.8, .8)):
            placement_handles.append(series(worst, np.array(RATES[1:]) + offset,
                sweep_stats("R_min", p), p, "R_min", LABEL[p], True))
        local = series(worst, [0], one_e0("R_min"), "LOCAL_ONLY", "R_min", "Local-only", False)
        legends[worst] = worst.legend(handles=placement_handles + [local, ref],
            loc="lower right", frameon=False, borderpad=0, borderaxespad=.3,
            handlelength=1.3, handletextpad=.4, labelspacing=.25)
        path.set(ylim=(0, 1.05), yticks=[0, .25, .5, .75, 1], ylabel="Assigned-frame TIR")
        path_handles = []
        for metric, prefix in (("Local_assigned_TIR", "Local"), ("Edge_assigned_TIR", "Edge")):
            for p, offset in zip(PLACEMENTS, (-.8, .8)):
                path_handles.append(series(path, np.array(RATES[1:]) + offset,
                    sweep_stats(metric, p), p, metric, f"{prefix} / {LABEL[p]}", True))
        path_handles.append(series(path, [0], one_e0("Local_assigned_TIR"),
            "LOCAL_ONLY", "Local_assigned_TIR", "Local-only", False))
        legends[path] = path.legend(handles=path_handles, loc="lower right", ncol=2,
            bbox_to_anchor=(1, .01), frameon=False, borderpad=0, borderaxespad=0,
            handlelength=1.1, handletextpad=.35, columnspacing=.75, labelspacing=.28)
        fig2.text(.575, .553, "(a)", ha="center", va="center")
        fig2.text(.575, .022, "(b)", ha="center", va="center")
        drawings[2] = fig2

        for number, fig in drawings.items():
            fig.canvas.draw()
            renderer = fig.canvas.get_renderer()
            clipped = []
            for text in fig.findobj(Text):
                if text.get_visible() and text.get_text():
                    box = text.get_window_extent(renderer)
                    if box.x0 < -1 or box.y0 < -1 or box.x1 > fig.bbox.width + 1 or box.y1 > fig.bbox.height + 1:
                        clipped.append(text.get_text())
                    require(text.get_fontsize() == FONT_SIZE, "Unexpected text size")
            require(not clipped, f"Figure {number} clipped text: {clipped}")
            overlaps = []
            for ax, legend in legends.items():
                if ax.figure is not fig:
                    continue
                box = legend.get_window_extent(renderer)
                radius = 2.6 * fig.dpi / 72
                for x, low, high in range_points[ax]:
                    lo, hi = ax.transData.transform([(x, low), (x, high)])
                    data_box = Bbox.from_extents(lo[0] - radius, lo[1] - radius,
                                                hi[0] + radius, hi[1] + radius)
                    if box.overlaps(data_box):
                        overlaps.append({"x": float(x), "min": float(low), "max": float(high)})
            require(not overlaps, f"Figure {number} legend overlaps data: {overlaps}")
            if number == 1:
                for ax in (top, bottom):
                    box = ax.get_window_extent(renderer)
                    require(math.isclose(box.width / 30, box.height / 8, rel_tol=1e-12),
                            "Raster cells are not square")
            stem = "fig1_e16" if number == 1 else "fig2_edge_rate_sweep"
            bbox = Bbox.from_bounds(0, 0, WIDTH, FIGURE_HEIGHTS[number])
            fig.savefig(output / f"{stem}.pdf", bbox_inches=bbox, pad_inches=0,
                        metadata={"Creator": "plot_section3_figures.py", "CreationDate": None,
                                  "ModDate": None, "Title": f"Campaign 2 Section III figure {number}"})
            fig.savefig(output / f"{stem}.png", bbox_inches=bbox, pad_inches=0, dpi=DPI,
                        metadata={"Software": "plot_section3_figures.py"})
            fonts = subprocess.run(["pdffonts", str(output / f"{stem}.pdf")],
                                   check=True, capture_output=True, text=True).stdout
            require("Type 3" not in fonts, f"Figure {number}: Type 3 font")
            checks[str(number)] = {"size_inches": [WIDTH, FIGURE_HEIGHTS[number]],
                                  "font_family": "STIXGeneral", "font_size_pt": FONT_SIZE,
                                  "PNG_dpi": DPI, "pdffonts": fonts, "Type_3_present": False,
                                  "text_clipping": False, "legend_data_overlap": False,
                                  "vector_PDF": True, "panel_labels_below_axes": True}
            plt.close(fig)
        return {"figures": checks, "plotted_series": coordinates,
                "marker_size_pt": 4.5, "line_width_pt": 1,
                "range_line_width_pt": .8, "cap_size_pt": 2,
                "nonzero_sweep_display_x_offsets": {"Concentrated": -.8, "Dispersed": .8},
                "display_offset_note": "Horizontal separation is presentation only; nominal assigned rates are unchanged.",
                "ranges": "five-run observed min–max, not confidence intervals",
                "connecting_lines": "visual guides between measured points only"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--replace-generated", action="store_true")
    args = parser.parse_args()
    output = Path(__file__).resolve().parent
    root = output.parents[2]
    require((root / ".git").exists() and output == root / "paper/figures/campaign2",
            "Repository/output path mismatch")
    vpath = output / "validation_fig1.json"
    validation = json.loads(vpath.read_text())
    require(validation["section3_finalizations"][-1]["task"] == TASK,
            "Finalization precheck is missing")
    for name in RENDERED:
        p = output / name
        require(not p.is_symlink() and (not p.exists() or args.replace_generated),
                f"Existing output requires --replace-generated: {p}")
    sources = {item["relative_path"]: item["sha256"] for item in validation["input_files"]}
    for name in ("paper/figures/campaign2/figure1_data.csv", "paper/figures/campaign2/plot_fig1.py"):
        sources[name] = sha256(root / name)
    require(all(sha256(root / name) == digest for name, digest in sources.items()),
            "Frozen source changed before generation")
    loader = runpy.run_path(str(output / "plot_fig1.py"))
    matrices, stream_stats, _, e16_report = loader["load_inputs"](root)
    require(e16_report == validation["data_validation"], "Figure 1 scientific values changed")
    groups, reference, sweep_report = load_sweep(root, e16_report)
    rendering = render(matrices, stream_stats, groups, reference, output)
    require(all(sha256(root / name) == digest for name, digest in sources.items()),
            "Source changed during generation")
    revision = validation["section3_finalizations"][-1]
    revision.update({"generated_utc": utc(), "source_sha_before": sources,
                     "source_sha_after": sources, "source_data_unchanged": True,
                     "Figure_1_data_validation": e16_report, "Figure_2_data_validation": sweep_report,
                     "rendering": rendering, "numeric_CSV_created": False,
                     "status": "PENDING_VISUAL_INSPECTION"})
    readme = (
        "Final one-column figures: fig1_e16.pdf/png and fig2_edge_rate_sweep.pdf/png; generate with python3 -B paper/figures/campaign2/plot_section3_figures.py --replace-generated.\n"
        "Canonical numeric CSV: paper/figure_data_section3.csv (unchanged); no duplicate section3 CSV is created.\n"
        "Assignment inputs: Campaign 2 assignment_table.csv and assignment_manifest.json; preserved plot_fig1.py supplies the verified input loader, not the final layout.\n"
        "Figure 1: equal assignment counts, different temporal positions, and stream-wise Edge-assigned timely ratios; all assigned frames, including pre-submission expirations, remain in the denominator.\n"
        "Figure 2: existing five-run means and observed ranges; E0 Edge TIR is undefined, the Local-assignment fraction is arithmetic only, and connecting lines are visual guides. Provenance/checks: validation_fig1.json, section3_finalizations.\n")
    (output / "README_fig1.txt").write_text(readme)
    new_names = (*RENDERED, "plot_section3_figures.py", "README_fig1.txt")
    revision["output_sha256"] = {name: sha256(output / name) for name in new_names}
    validation["output_sha256"].update(revision["output_sha256"])
    validation["status"] = "PENDING_VISUAL_INSPECTION"
    validation["generated_utc"] = utc()
    vpath.write_text(json.dumps(validation, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps({"generation": "PASS", "source_data_unchanged": True,
                      "duplicate_CSV_created": False, "E16_runs_shared": True,
                      "Figure_2_summaries": sweep_report["summary_count"],
                      "rendering": rendering["figures"]}, indent=2))


if __name__ == "__main__":
    main()
