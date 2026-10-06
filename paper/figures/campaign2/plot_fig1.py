#!/usr/bin/env python3
"""Render only Campaign 2 Figure 1 from preserved assignment and figure inputs.

Run from any directory: python3 -B paper/figures/campaign2/plot_fig1.py
Use --replace-generated for an explicit layout rerender. This script neither
deletes obsolete outputs nor runs an experimental analyzer. Input data are
never written. Stream coordinates use the existing frozen means/min/max;
the five run records are used only to verify those summaries and denominators.
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
from datetime import datetime, timezone

TASK = "CAMPAIGN2_SECTION3_FIGURE1_CLEANUP_AND_PUBLISH"
CAMPAIGN = "block_b_edge_rate_sweep01"
CAMPAIGN_PATH = Path("results/timely_capacity_campaign/v2_2") / CAMPAIGN
PLACEMENTS = ("CONCENTRATED", "DISPERSED")
INTERNAL = {"CONCENTRATED": "ALIGNED", "DISPERSED": "STAGGERED"}
LABEL = {"CONCENTRATED": "Concentrated", "DISPERSED": "Dispersed"}
COLOR = {"CONCENTRATED": "#355C82", "DISPERSED": "#C17C3C"}
MARKER = {"CONCENTRATED": "o", "DISPERSED": "s"}
WIDTH, HEIGHT, FONT_SIZE, DPI = 7.16, 3.5, 8.5, 600
OUTPUT_NAMES = ("fig1_e16.pdf", "fig1_e16.png", "figure1_data.csv",
                "plot_fig1.py", "validation_fig1.json", "README_fig1.txt")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def utc():
    return datetime.now(timezone.utc).isoformat()


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_inputs(root):
    source = root / "paper/figure_data_section3.csv"
    previous = json.loads((root / "paper/validation_section3.json").read_text())
    table = root / CAMPAIGN_PATH / "assignment_table.csv"
    manifest_file = root / CAMPAIGN_PATH / "assignment_manifest.json"
    manifest = json.loads(manifest_file.read_text())
    require(previous["campaign"] == CAMPAIGN, "Validation source campaign mismatch")
    require(sha256(source) == previous["plot_revisions"][-1]["figure_data_sha_after"],
            "Frozen figure CSV SHA differs from the preserved validation")
    for path in (table, manifest_file):
        require(sha256(path) == previous["source_SHA256"][path.name],
                f"Assignment source SHA mismatch: {path}")
    data_rows, matrices, assignments = [], {}, {}
    table_rows = list(enumerate(csv.DictReader(table.open()), start=2))
    for placement in PLACEMENTS:
        rr = [(line, r) for line, r in table_rows if r["schedule_role"] == "MEASURED"
              and r["Local_FPS"] == "224" and r["Edge_FPS"] == "16"
              and r["placement"] == INTERNAL[placement]]
        require(len(rr) == 240, "Assignment raster must contain 240 cells")
        cells = {(int(r["stream_id"]), int(r["source_slot"])): r for _, r in rr}
        require(set(cells) == {(k, n) for k in range(8) for n in range(30)},
                "Missing or duplicate assignment cells")
        matrix = [[int(cells[k, n]["assignment"] == "EDGE")
                   for n in range(30)] for k in range(8)]
        local_matrix = [[int(cells[k, n]["assignment"] == "LOCAL")
                         for n in range(30)] for k in range(8)]
        m = manifest["L224" + INTERNAL[placement]]
        require(matrix == m["edge_masks"] and local_matrix == m["local_masks"],
                "Assignment table and manifest differ cell-by-cell")
        edge_counts = [sum(row) for row in matrix]
        local_counts = [sum(row) for row in local_matrix]
        require(edge_counts == [2] * 8 and local_counts == [28] * 8,
                "Per-stream 28 Local / 2 Edge assignment invariant failed")
        phases = [int(cells[k, 0]["phase"]) for k in range(8)]
        m_e = [sum(matrix[k][n] for k in range(8)) for n in range(30)]
        m_l = [sum(local_matrix[k][n] for k in range(8)) for n in range(30)]
        require(phases == m["phase_vector"] and m_e == m["m_E"] and m_l == m["m_L"],
                "Assignment phases or per-index totals differ from manifest")
        for _, r in rr:
            n, k = int(r["source_slot"]), int(r["stream_id"])
            require(int(r["m_E"]) == m_e[n] and int(r["m_L"]) == m_l[n]
                    and int(r["phase"]) == phases[k] and m_e[n] + m_l[n] == 8,
                    "Assignment table slot metadata mismatch")
        old = [a for a in previous["assignment_patterns"]
               if a["Edge_FPS"] == 16 and a["placement"] == placement]
        require(len(old) == 1 and old[0]["phase_vector"] == phases
                and old[0]["m_E"] == m_e and old[0]["m_L"] == m_l,
                "Assignment source and preserved figure validation disagree")
        matrices[placement] = matrix
        assignments[placement] = {"Local_total": sum(local_counts),
                                 "Edge_total": sum(edge_counts),
                                 "Local_per_stream": local_counts,
                                 "Edge_per_stream": edge_counts,
                                 "phase_vector": phases, "m_E": m_e, "m_L": m_l,
                                 "table_manifest_cell_match": True}
        for line, r in sorted(rr, key=lambda item:
                              (int(item[1]["stream_id"]), int(item[1]["source_slot"]))):
            data_rows.append({"record_type": "ASSIGNMENT_CELL", "panel": "a",
                              "campaign": CAMPAIGN, "placement": placement,
                              "stream_id": r["stream_id"], "frame_index": r["source_slot"],
                              "phase": r["phase"], "assignment": r["assignment"],
                              "Local_FPS": r["Local_FPS"], "Edge_FPS": r["Edge_FPS"],
                              "m_E": r["m_E"], "m_L": r["m_L"],
                              "source_path": str(table.relative_to(root)),
                              "source_row": line, "source_sha256": sha256(table)})
    require(assignments[PLACEMENTS[0]]["Local_per_stream"] ==
            assignments[PLACEMENTS[1]]["Local_per_stream"] and
            assignments[PLACEMENTS[0]]["Edge_per_stream"] ==
            assignments[PLACEMENTS[1]]["Edge_per_stream"], "Placement count mismatch")

    rows = list(enumerate(csv.DictReader(source.open()), start=2))
    selected = [(line, r) for line, r in rows if r["figure"] == "1" and r["panel"] == "b"]
    require(len(selected) == 96 and all(r["campaign"] == CAMPAIGN
            and r["Edge_FPS"] == "16" and r["Local_FPS"] == "224"
            and r["metric"] == "Edge_assigned_TIR" for _, r in selected),
            "Stream source must contain only Campaign 2 E16 data")
    stats, checked = {p: [] for p in PLACEMENTS}, []
    ids = {p: [] for p in PLACEMENTS}
    denom = previous["E16_Edge_denominator_per_run_per_stream"]
    for placement in PLACEMENTS:
        for stream in range(8):
            rr = sorted([r for _, r in selected if r["record_type"] == "RUN"
                         and r["placement"] == placement and int(r["stream_id"]) == stream],
                        key=lambda r: int(r["repeat"]))
            ss = [r for _, r in selected if r["record_type"] == "SUMMARY"
                  and r["placement"] == placement and int(r["stream_id"]) == stream]
            require(len(ss) == 1 and [int(r["repeat"]) for r in rr] == list(range(1, 6)),
                    "Missing or duplicate stream run/summary")
            s = ss[0]
            run_ids = [r["run_id"] for r in rr]
            require(len(set(run_ids)) == 5 and json.loads(s["run_ids"]) == run_ids,
                    "Stream summary run provenance mismatch")
            if stream == 0:
                ids[placement] = run_ids
            require(run_ids == ids[placement], "Different runs across streams")
            require(int(s["n"]) == 5 and int(s["denominator"]) == denom,
                    "Summary denominator or repeat count mismatch")
            values = []
            for r in rr:
                counts = [int(r[k]) for k in ("timely_count", "expired_count", "late_count")]
                require(int(r["denominator"]) == denom and min(counts) >= 0
                        and sum(counts) == denom, "Assigned cohort accounting mismatch")
                require(float(r["value"]) == counts[0] / denom,
                        "Edge-assigned timely ratio/count mismatch")
                values.append(float(r["value"]))
            frozen = [float(s[k]) for k in ("mean", "min", "max")]
            derived = [math.fsum(values) / len(values), min(values), max(values)]
            require(all(math.isclose(a, b, rel_tol=0, abs_tol=1e-15)
                        for a, b in zip(frozen, derived)), "Frozen summary/run mismatch")
            old = [r for r in previous["all_figure_mean_min_max"]
                   if r["figure"] == 1 and r["panel"] == "b"
                   and r["placement"] == placement and r["stream_id"] == stream]
            require(len(old) == 1 and frozen == [old[0][k] for k in ("mean", "min", "max")],
                    "Frozen figure data and validation summary mismatch")
            stats[placement].append(frozen)
            checked.append({"placement": placement, "stream_id": stream,
                            "mean": frozen[0], "min": frozen[1], "max": frozen[2],
                            "denominator": denom, "n": len(rr), "run_ids": run_ids})
    require(set(ids[PLACEMENTS[0]]).isdisjoint(ids[PLACEMENTS[1]]), "Repeated placement run IDs")
    require(set(sum(ids.values(), [])) == set(previous["E16_run_IDs_in_both_figures"]),
            "Run IDs differ from preserved Figure 1 validation")
    for line, r in selected:
        d = {k: r[k] for k in ("record_type", "panel", "campaign", "placement", "stream_id",
                              "Local_FPS", "Edge_FPS", "repeat", "run_id", "run_ids", "metric",
                              "value", "n", "mean", "min", "max", "denominator", "timely_count",
                              "expired_count", "late_count")}
        d.update({"source_path": str(source.relative_to(root)), "source_row": line,
                  "source_sha256": sha256(source), "original_source": r["source"]})
        data_rows.append(d)
    report = {"assignment_patterns": assignments, "stream_mean_min_max": checked,
              "run_ids": ids, "measured_runs_per_placement": 5,
              "Edge_assigned_denominator_per_stream_run": denom,
              "pre_submission_expirations_already_in_denominator": True,
              "denominator_is_submitted_only": False,
              "ranges": "observed min–max across five measured runs",
              "existing_valid_run_count": previous["valid_run_count"],
              "existing_nonzero_pair_count": previous["nonzero_pair_count"],
              "ANALYZER_SHA_RECORD_NOT_FOUND": previous["ANALYZER_SHA_RECORD_NOT_FOUND"]}
    return matrices, stats, data_rows, report


def render(matrices, stats, output):
    with tempfile.TemporaryDirectory(prefix="campaign2_fig1_cleanup_fonts_") as cache:
        os.environ["MPLCONFIGDIR"] = cache
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib import font_manager
        from matplotlib.colors import ListedColormap
        from matplotlib.lines import Line2D
        from matplotlib.patches import Patch
        from matplotlib.legend_handler import HandlerTuple
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
        fig = plt.figure(figsize=(WIDTH, HEIGHT))
        top = fig.add_axes([.065, .57, .37, .28])
        bottom = fig.add_axes([.065, .20, .37, .28], sharex=top)
        outcome = fig.add_axes([.55, .20, .42, .65])
        for ax, placement in zip((top, bottom), PLACEMENTS):
            ax.pcolormesh(np.arange(31) - .5, np.arange(9) - .5,
                          np.array(matrices[placement]),
                          cmap=ListedColormap(["#F0F1F2", COLOR[placement]]),
                          vmin=0, vmax=1, shading="flat", edgecolors="none",
                          rasterized=False, antialiased=False)
            ax.set(xlim=(-.5, 29.5), ylim=(7.5, -.5), yticks=range(8),
                   xticks=[0, 5, 10, 15, 20, 25, 29], ylabel="Stream ID")
            ax.set_title(LABEL[placement], color=COLOR[placement], pad=5)
            ax.tick_params(pad=2)
            ax.spines[["top", "right"]].set_visible(False)
            ax.grid(False)
        top.tick_params(labelbottom=False)
        bottom.set_xlabel("Frame index", labelpad=4)
        edge_handle = tuple(Patch(facecolor=COLOR[p], edgecolor="none") for p in PLACEMENTS)
        fig.legend([Patch(facecolor="#F0F1F2", edgecolor="#B0B0B0", linewidth=.4), edge_handle],
                   ["Local", "Edge"], handler_map={tuple: HandlerTuple(ndivide=None, pad=.1)},
                   loc="upper center", bbox_to_anchor=(.25, .985), ncol=2,
                   frameon=False, handlelength=1.6, columnspacing=1.1,
                   handletextpad=.45, borderaxespad=0)
        for placement, offset in zip(PLACEMENTS, (-.14, .14)):
            mean, low, high = np.array(stats[placement]).T
            x = np.arange(8) + offset
            outcome.errorbar(x, mean, yerr=np.vstack([mean - low, high - mean]),
                             fmt="none", ecolor=COLOR[placement],
                             elinewidth=.8, capsize=2, capthick=.8, zorder=2)
            outcome.plot(x, mean, linestyle="None", marker=MARKER[placement],
                         markersize=4.5, markerfacecolor="white",
                         markeredgecolor=COLOR[placement], markeredgewidth=.9, zorder=3)
        outcome.set(xlim=(-.6, 7.6), ylim=(-.025, 1.045), xticks=range(8),
                    yticks=[0, .25, .5, .75, 1], xlabel="Stream ID",
                    ylabel="Timely ratio of Edge-assigned frames")
        outcome.spines[["top", "right"]].set_visible(False)
        outcome.grid(False)
        handles = [Line2D([], [], color=COLOR[p], marker=MARKER[p],
                          markerfacecolor="white", markeredgewidth=.9,
                          markersize=4.5, linestyle="None", label=LABEL[p]) for p in PLACEMENTS]
        outcome.legend(handles=handles, loc="center left", bbox_to_anchor=(.005, .33),
                       frameon=False, borderaxespad=0, handletextpad=.5, labelspacing=.35)
        for x, label in ((.25, "(a)"), (.76, "(b)")):
            fig.text(x, .035, label, ha="center", va="center")
        fig.canvas.draw()
        renderer = fig.canvas.get_renderer()
        clipped = []
        for text in fig.findobj(Text):
            if text.get_visible() and text.get_text():
                box = text.get_window_extent(renderer)
                if box.x0 < -1 or box.y0 < -1 or box.x1 > fig.bbox.width + 1 or box.y1 > fig.bbox.height + 1:
                    clipped.append(text.get_text())
                require(text.get_fontsize() == FONT_SIZE, "Unexpected font size")
        require(not clipped, f"Clipped labels: {clipped}")
        bbox = Bbox.from_bounds(0, 0, WIDTH, HEIGHT)
        fig.savefig(output / "fig1_e16.pdf", bbox_inches=bbox, pad_inches=0,
                    metadata={"Title": "E16 temporal assignment and stream-wise timely service",
                              "Creator": "plot_fig1.py", "CreationDate": None, "ModDate": None})
        fig.savefig(output / "fig1_e16.png", bbox_inches=bbox, pad_inches=0, dpi=DPI,
                    metadata={"Software": "plot_fig1.py"})
        plt.close(fig)
    fonts = subprocess.run(["pdffonts", str(output / "fig1_e16.pdf")],
                           check=True, capture_output=True, text=True).stdout
    require("Type 3" not in fonts, "Type 3 PDF font is forbidden")
    return {"figure_size_inches": {"width": WIDTH, "height": HEIGHT},
            "png_dpi": DPI, "font": {"family": "STIXGeneral", "size_pt": FONT_SIZE,
            "pdf_fonttype": 42, "ps_fonttype": 42, "pdffonts": fonts, "Type_3_present": False},
            "text_clipping_check": "PASS", "vector_assignment_cells": True,
            "outcome_connecting_lines": False, "range_line_width_pt": .8,
            "marker_size_pt": 4.5, "range_cap_size_pt": 2}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--replace-generated", action="store_true")
    args = parser.parse_args()
    output = Path(__file__).resolve().parent
    root = output.parents[2]
    require((root / ".git").exists() and output == root / "paper/figures/campaign2",
            "Repository/output path mismatch")
    vpath = output / "validation_fig1.json"
    require(not vpath.is_symlink(), "Validation output must not be a symlink")
    validation = json.loads(vpath.read_text())
    require(validation["task"] == TASK, "Existing validation belongs to another task")
    for name in ("fig1_e16.pdf", "fig1_e16.png", "figure1_data.csv", "README_fig1.txt"):
        p = output / name
        require(not p.is_symlink() and (not p.exists() or args.replace_generated),
                f"Existing output requires explicit --replace-generated: {p}")
    before = {item["relative_path"]: sha256(root / item["relative_path"])
              for item in validation["input_files"]}
    require(all(before[item["relative_path"]] == item["sha256"]
                for item in validation["input_files"]), "Input changed since deletion precheck")
    matrices, stats, data_rows, report = load_inputs(root)
    print("stream_id,conc_mean,conc_min,conc_max,disp_mean,disp_min,disp_max")
    for k in range(8):
        print(",".join([str(k)] + [repr(v) for p in PLACEMENTS for v in stats[p][k]]))
    fields = ["record_type", "panel", "campaign", "placement", "stream_id", "frame_index",
              "phase", "assignment", "Local_FPS", "Edge_FPS", "m_E", "m_L", "repeat", "run_id",
              "run_ids", "metric", "value", "n", "mean", "min", "max", "denominator",
              "timely_count", "expired_count", "late_count", "source_path", "source_row",
              "source_sha256", "original_source"]
    buf = io.StringIO(newline="")
    writer = csv.DictWriter(buf, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    writer.writerows(data_rows)
    data_path = output / "figure1_data.csv"
    if data_path.exists():
        require(data_path.read_text() == buf.getvalue(), "Generated data would change: stopped")
    else:
        data_path.write_text(buf.getvalue())
    validation["rendering"] = render(matrices, stats, output)
    validation["data_validation"] = report
    after = {name: sha256(root / name) for name in before}
    require(before == after, "Source data modified")
    validation.update({"input_sha_after": after, "input_files_unchanged": True,
                       "generated_utc": utc(), "plot_generation_status": "PASS",
                       "visual_inspection": "PENDING", "status": "PENDING_FINAL_INSPECTION",
                       "source_data_modified": False, "analysis01_modified": False,
                       "paper_evidence01_modified": False, "analyze_reexecuted": False,
                       "new_experiment": False})
    validation["short_caption"] = (
        "Temporal placement at L224/E16. (a) Both placements assign 28 Local and 2 Edge "
        "frames per stream per 30 frame indices; only temporal positions differ. "
        "(b) Stream-wise Edge-assigned timely ratios: means and observed min–max across "
        "five runs. Denominators include pre-submission expirations. "
        "This is descriptive preliminary evidence, not an algorithm comparison.")
    readme = (
        "Inputs: assignment_table.csv, assignment_manifest.json, paper/figure_data_section3.csv, paper/validation_section3.json (exact paths/SHA in validation_fig1.json).\n"
        "Outputs: fig1_e16.pdf/png, figure1_data.csv, plot_fig1.py, validation_fig1.json, README_fig1.txt; regenerate with python3 -B paper/figures/campaign2/plot_fig1.py --replace-generated.\n"
        "Deleted obsolete Figure 1 outputs: see deleted_files_precheck/deleted_files in validation_fig1.json; Figure 2 and shared sources retained.\n"
        "Interpretation: identical aggregate and per-stream counts, different temporal assignment positions, different observed stream-wise timely service; no causal or algorithm claim.\n"
        "Metric: all Edge-assigned frames remain in the denominator, including pre-submission expiration; means and observed ranges use five measured runs.\n")
    (output / "README_fig1.txt").write_text(readme)
    validation["generated_files"] = [str((output / n).relative_to(root)) for n in OUTPUT_NAMES]
    validation["output_sha256"] = {n: sha256(output / n) for n in OUTPUT_NAMES
                                   if n != "validation_fig1.json"}
    validation["validation_self_sha_note"] = "Self SHA omitted to avoid a recursive manifest."
    vpath.write_text(json.dumps(validation, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps({"plot_generation_status": "PASS", "input_files_unchanged": True,
                      "assignment_patterns": report["assignment_patterns"],
                      "rendering": validation["rendering"]}, indent=2))


if __name__ == "__main__":
    main()
