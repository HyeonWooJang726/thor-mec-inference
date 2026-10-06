#!/usr/bin/env python3
"""Reproduce the one-column Campaign 2 E16 placement figure (redesign 06).

Only ../figure_data_section3.csv supplies observations and stream summaries.
No experimental analyzer, hardware, transport, or upstream dataset is invoked.
The Edge ratio denominator is all assigned frames, including pre-submission
expirations. Ranges are observed extrema across five runs, not confidence
intervals. Horizontal offsets separate identical observations; y is never
jittered. Larger, black-outlined filled markers show the placement means.

Run: python3 -B paper/figures/plot_fig1.py
Use --replace-generated to regenerate these two rendered outputs explicitly.
Validation is printed to stdout; the frozen CSV is never written.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import os
from pathlib import Path
import subprocess
import tempfile


CAMPAIGN = "block_b_edge_rate_sweep01"
PLACEMENTS = ("CONCENTRATED", "DISPERSED")
LABEL = {"CONCENTRATED": "Concentrated", "DISPERSED": "Dispersed"}
COLOR = {"CONCENTRATED": "#355C82", "DISPERSED": "#C17C3C"}
MARKER = {"CONCENTRATED": "o", "DISPERSED": "s"}
WIDTH, HEIGHT, DPI, FONT_SIZE = 3.5, 4.4, 600, 8.5


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_data(path):
    rows = list(csv.DictReader(io.StringIO(path.read_text(encoding="utf-8"))))
    selected = [r for r in rows if r["figure"] == "1"]
    require(selected, "No Figure 1 rows in the frozen CSV")
    require(all(r["campaign"] == CAMPAIGN and r["Edge_FPS"] == "16"
                and r["Local_FPS"] == "224" for r in selected),
            "Figure 1 must contain only Campaign 2 L224/E16")
    paired = [r for r in selected if r["panel"] == "a"]
    require(len(paired) == 10 and all(r["record_type"] == "RUN"
                and r["metric"] == "R_min" for r in paired),
            "Panel (a) must contain exactly ten run-level R_min records")
    runs = {}
    for placement in PLACEMENTS:
        rr = sorted([r for r in paired if r["placement"] == placement],
                    key=lambda r: int(r["repeat"]))
        require([int(r["repeat"]) for r in rr] == list(range(1, 6)),
                f"Missing or duplicated paired repeats: {placement}")
        require(len({r["run_id"] for r in rr}) == 5,
                f"Duplicate run IDs: {placement}")
        for r in rr:
            require(int(r["denominator"]) == 1800, "R_min source denominator")
            require(float(r["value"]) == int(r["timely_count"]) /
                    int(r["denominator"]), "R_min count/ratio mismatch")
            require("paired_comparison.csv" in r["source"],
                    "The frozen figure data does not establish pairing")
        runs[placement] = rr
    require(len({r["run_id"] for r in paired}) == 10,
            "Placement run IDs are not distinct")

    stream_rows = [r for r in selected if r["panel"] == "b"]
    raw_stream = [r for r in stream_rows if r["record_type"] == "RUN"]
    summaries = [r for r in stream_rows if r["record_type"] == "SUMMARY"]
    require(len(raw_stream) == 80 and len(summaries) == 16,
            "Panel (b) must contain 80 stream/run records and 16 summaries")
    require(all(r["metric"] == "Edge_assigned_TIR" for r in stream_rows),
            "Unexpected panel (b) metric")
    stream_stats = {placement: [] for placement in PLACEMENTS}
    checked_rows = []
    for placement in PLACEMENTS:
        for stream in range(8):
            ss = [r for r in summaries if r["placement"] == placement
                  and int(r["stream_id"]) == stream]
            require(len(ss) == 1, "Missing or duplicated stream summary")
            s = ss[0]
            rr = sorted([r for r in raw_stream if r["placement"] == placement
                         and int(r["stream_id"]) == stream],
                        key=lambda r: int(r["repeat"]))
            require([int(r["repeat"]) for r in rr] == list(range(1, 6)),
                    "Missing or duplicated stream repeat")
            require([r["run_id"] for r in rr] ==
                    [r["run_id"] for r in runs[placement]],
                    "Stream and whole-stream observations use different runs")
            require(json.loads(s["run_ids"]) == [r["run_id"] for r in rr],
                    "Stream-summary provenance mismatch")
            require(int(s["n"]) == 5 and int(s["denominator"]) == 120,
                    "Stream summary must use five runs and 120 assigned frames")
            values = []
            for r in rr:
                denom = int(r["denominator"])
                timely = int(r["timely_count"])
                expired = int(r["expired_count"])
                late = int(r["late_count"])
                require(denom == 120, "Edge-assigned denominator is not 120")
                require(min(timely, expired, late) >= 0 and
                        timely + expired + late == denom,
                        "Edge terminal counts do not partition the assigned cohort")
                require(float(r["value"]) == timely / denom,
                        "Stream Edge-assigned ratio/count mismatch")
                values.append(float(r["value"]))
            calculated = (math.fsum(values) / len(values), min(values), max(values))
            frozen = tuple(float(s[k]) for k in ("mean", "min", "max"))
            require(all(math.isclose(a, b, rel_tol=0, abs_tol=1e-15)
                        for a, b in zip(calculated, frozen)),
                    "Frozen stream mean/min/max does not match its five runs")
            # Plot the existing frozen summary, not a replacement summary.
            stream_stats[placement].append(frozen)
            checked_rows.append({"placement": placement, "stream_id": stream,
                                 "mean": frozen[0], "min": frozen[1],
                                 "max": frozen[2], "denominator": 120})
    zero_rows = [r for r in raw_stream if r["placement"] == "CONCENTRATED"
                 and int(r["stream_id"]) in (5, 6, 7)]
    zero_condition = len(zero_rows) == 15 and all(
        int(r["timely_count"]) == 0 and float(r["value"]) == 0 for r in zero_rows)
    values = {p: [float(r["value"]) for r in runs[p]] for p in PLACEMENTS}
    differences = [d - c for c, d in zip(values["CONCENTRATED"],
                                        values["DISPERSED"])]
    report = {
        "campaign": CAMPAIGN, "data_source": str(path),
        "paired_repeat_count": 5,
        "run_ids": {p: [r["run_id"] for r in runs[p]] for p in PLACEMENTS},
        "paired_R_min": values, "paired_differences": differences,
        "means": {p: math.fsum(v) / len(v) for p, v in values.items()},
        "mean_gain_pp": math.fsum(differences) / len(differences) * 100,
        "stream_mean_min_max": checked_rows,
        "stream_5_7_concentrated_all_five_zero": zero_condition,
        "edge_denominator_all_assigned_frames": 120,
        "pre_submission_expirations_in_denominator": True,
        "stream_summary_check": "PASS", "paired_value_check": "PASS",
    }
    return values, stream_stats, report


def render(values, stream_stats, report, output_dir):
    with tempfile.TemporaryDirectory(prefix="fig1_redesign06_fonts_") as cache:
        os.environ["MPLCONFIGDIR"] = cache
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib import font_manager
        from matplotlib.lines import Line2D
        from matplotlib.transforms import Bbox
        import numpy as np

        font_manager.findfont(font_manager.FontProperties(family="STIXGeneral"),
                              fallback_to_default=False)
        plt.rcParams.update({
            "font.family": "STIXGeneral", "font.size": FONT_SIZE,
            "axes.labelsize": FONT_SIZE, "xtick.labelsize": FONT_SIZE,
            "ytick.labelsize": FONT_SIZE, "legend.fontsize": FONT_SIZE,
            "mathtext.fontset": "stix", "pdf.fonttype": 42, "ps.fonttype": 42,
            "figure.facecolor": "white", "axes.facecolor": "white",
            "savefig.facecolor": "white", "axes.linewidth": .65,
            "xtick.major.size": 2.5, "ytick.major.size": 2.5,
            "xtick.major.width": .65, "ytick.major.width": .65,
            "path.simplify": False,
        })
        fig = plt.figure(figsize=(WIDTH, HEIGHT))
        a = fig.add_axes([.18, .61, .79, .34])
        b = fig.add_axes([.18, .14, .79, .34])
        for ax in (a, b):
            ax.spines[["top", "right"]].set_visible(False)
            ax.grid(False)
            ax.tick_params(pad=3)

        # Deterministic horizontal offsets reveal coincident paired values.
        # These offsets are presentation only, not another experimental variable.
        offsets = np.linspace(-.22, .02, len(values["CONCENTRATED"]))
        for offset, c, d in zip(offsets, values["CONCENTRATED"], values["DISPERSED"]):
            a.plot([offset, 1 + offset], [c, d], color="#A5A5A5",
                   linewidth=.55, zorder=1)
        for category, placement in enumerate(PLACEMENTS):
            a.plot(category + offsets, values[placement], linestyle="None",
                   marker=MARKER[placement], markersize=3.6,
                   color=COLOR[placement], markerfacecolor=COLOR[placement],
                   markeredgewidth=.4, zorder=3)
            # Keep the larger mean separate from the complete five-run cluster.
            a.plot(category + .23, report["means"][placement], linestyle="None",
                   marker=MARKER[placement], markersize=6,
                   markerfacecolor=COLOR[placement], markeredgecolor="#222222",
                   markeredgewidth=.65, zorder=4)
        a.set(xlim=(-.4, 1.43), ylim=(.90, 1.01),
              xticks=[0, 1], xticklabels=[LABEL[p] for p in PLACEMENTS],
              yticks=[.90, .95, 1.00], xlabel="Placement", ylabel="Worst-stream TIR")
        a.text(.5, .15, f'Mean gain: +{report["mean_gain_pp"]:.1f} pp',
               ha="center", va="center", transform=a.transAxes)

        streams = np.arange(8)
        x_positions = {"CONCENTRATED": streams - .12,
                       "DISPERSED": streams + .12}
        for stream in streams:
            b.plot([x_positions[p][stream] for p in PLACEMENTS],
                   [stream_stats[p][stream][0] for p in PLACEMENTS],
                   color="#B0B0B0", linewidth=.55, zorder=1)
        for placement in PLACEMENTS:
            stats = np.array(stream_stats[placement])
            means, lows, highs = stats.T
            b.errorbar(x_positions[placement], means,
                       yerr=np.vstack([means - lows, highs - means]),
                       fmt="none", ecolor=COLOR[placement],
                       elinewidth=.8, capsize=2, capthick=.8, zorder=2)
            b.plot(x_positions[placement], means, linestyle="None",
                   marker=MARKER[placement], markersize=4.5,
                   markerfacecolor="white", markeredgecolor=COLOR[placement],
                   markeredgewidth=.9, zorder=3, clip_on=False)
        b.set(xlim=(-.55, 7.55), ylim=(0, 1.045), xticks=streams,
              yticks=[0, .25, .5, .75, 1], xlabel="Stream ID",
              ylabel="Edge-assigned TIR")
        handles = [Line2D([], [], linestyle="None", color=COLOR[p],
                          marker=MARKER[p], markersize=4.5,
                          markerfacecolor="white", markeredgewidth=.9,
                          label=LABEL[p]) for p in PLACEMENTS]
        b.legend(handles=handles, loc="center left", bbox_to_anchor=(.005, .32),
                 frameon=False, borderaxespad=0, handletextpad=.45,
                 labelspacing=.35)
        if report["stream_5_7_concentrated_all_five_zero"]:
            # A concise bracket marks the checked zero-outcome streams only.
            b.plot([4.88, 4.88, 6.88, 6.88], [.075, .105, .105, .075],
                   color="#555555", linewidth=.6, zorder=2)
            b.text(5.88, .15, "No timely Edge results", ha="center", va="bottom",
                   bbox={"facecolor": "white", "edgecolor": "none", "pad": .2})
        for ax, label in ((a, "(a)"), (b, "(b)")):
            ax.text(.5, -.25, label, transform=ax.transAxes,
                    ha="center", va="top", clip_on=False)

        # Validate all text against the full 3.5 x 4.4-inch export canvas.
        fig.canvas.draw()
        renderer = fig.canvas.get_renderer()
        from matplotlib.text import Text
        clipped = []
        for item in fig.findobj(Text):
            if item.get_visible() and item.get_text():
                box = item.get_window_extent(renderer)
                if (box.x0 < -1 or box.y0 < -1 or
                        box.x1 > fig.bbox.width + 1 or box.y1 > fig.bbox.height + 1):
                    clipped.append(item.get_text())
                require(item.get_fontsize() == FONT_SIZE, "Unexpected text font size")
        require(not clipped, f"Clipped text: {clipped}")
        a_bbox = a.get_window_extent(renderer)
        require(a_bbox.x0 < a_bbox.x1, "Invalid placement axis bounds")
        # The lower full-ratio bound remains zero; zero markers are not clipped.
        require(b.get_ylim()[0] == 0, "Panel (b) lower bound must include zero")
        require(len(a.lines) == 9, "Unexpected paired-line/marker count")
        require(len(a.get_legend_handles_labels()[0]) == 0,
                "Panel (a) must not contain legend entries")

        # Including the full canvas in tight bbox preserves exact physical size.
        bbox = Bbox.from_bounds(0, 0, WIDTH, HEIGHT)
        fig.savefig(output_dir / "fig1.pdf", bbox_inches=bbox, pad_inches=0,
                    metadata={"Title": "E16 temporal-placement measurement",
                              "Creator": "plot_fig1.py", "CreationDate": None,
                              "ModDate": None})
        fig.savefig(output_dir / "fig1.png", dpi=DPI, bbox_inches=bbox, pad_inches=0,
                    metadata={"Software": "plot_fig1.py"})
        plt.close(fig)
        report.update({"figure_width_in": WIDTH, "figure_height_in": HEIGHT,
                       "font_family": "STIXGeneral", "font_size_pt": FONT_SIZE,
                       "png_dpi": DPI, "text_clipping_check": "PASS",
                       "paired_lines": 5, "mean_marker_offset": .23,
                       "data_y_jitter": False,
                       "ranges": "observed min–max across five runs"})


def main():
    script_dir = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path,
                        default=script_dir.parent / "figure_data_section3.csv")
    parser.add_argument("--output-dir", type=Path, default=script_dir)
    parser.add_argument("--replace-generated", action="store_true")
    args = parser.parse_args()
    require(not args.data.is_symlink(), "Do not use a symlink as frozen input")
    data = args.data.resolve(strict=True)
    output = args.output_dir.resolve(strict=True)
    require(output.is_dir(), "Output directory must already exist")
    for name in ("fig1.pdf", "fig1.png"):
        target = output / name
        require(not target.is_symlink(), f"Output is a symlink: {target}")
        require(not target.exists() or args.replace_generated,
                f"Existing output: {target}; explicit --replace-generated required")
    before = sha256(data)
    values, stream_stats, report = verify_data(data)
    print("stream_id,conc_mean,conc_min,conc_max,disp_mean,disp_min,disp_max")
    for stream in range(8):
        print(",".join([str(stream)] +
                       [repr(v) for p in PLACEMENTS for v in stream_stats[p][stream]]))
    render(values, stream_stats, report, output)
    fonts = subprocess.run(["pdffonts", str(output / "fig1.pdf")],
                           check=True, text=True, capture_output=True).stdout
    require("Type 3" not in fonts, "PDF contains Type 3 font")
    after = sha256(data)
    require(before == after, "FIGURE_DATA_MODIFIED=YES")
    report.update({"figure_data_sha_before": before, "figure_data_sha_after": after,
                   "figure_data_unchanged": True, "pdffonts": fonts,
                   "Type_3_present": False,
                   "output_sha256": {n: sha256(output / n)
                                     for n in ("fig1.pdf", "fig1.png")}})
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
