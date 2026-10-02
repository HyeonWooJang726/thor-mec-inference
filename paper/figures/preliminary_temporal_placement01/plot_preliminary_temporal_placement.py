#!/usr/bin/env python3
"""Plot existing L224/E16 measurements without importing experiment runtimes.

Usage: python3 -B plot_preliminary_temporal_placement.py --output-dir FRESH_DIR
The script can also populate its own otherwise empty output directory once.
All scientific inputs are read-only. Existing output artifacts are never replaced.
"""
import argparse
from collections import Counter
import csv
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import statistics
import subprocess
import tempfile


STEM = "preliminary_temporal_placement"
WIDTH, HEIGHT = 7.16, 3.95
MIN_FONT = 8.5
FONT = "Liberation Sans"
COLORS = {"ALIGNED": "#00679A", "STAGGERED": "#C86B39"}
MARKERS = {"ALIGNED": "o", "STAGGERED": "s"}
LABELS = {
    "ALIGNED": "Temporally concentrated placement",
    "STAGGERED": "Temporally dispersed placement",
}
CAMPAIGNS = {
    "grid03_mini01": (3, 24, "GRID03_MINI_PREREGISTRATION.md", "grid03_mini_verdict.json"),
    "block_b_confirmation03": (5, 25, "CONFIRMATION03_PREREGISTRATION.md", "confirmation03_verdict.json"),
}
SCOPE_DESCRIPTIONS = {
    1: "Identical mean split and per-stream assignment counts",
    2: "Exactly three Grid03-mini pairs in panel (b)",
    3: "Exactly five Confirmation03 pairs in panel (c)",
    4: "Campaigns remain separate; no pooled samples or means",
    5: "Every plotted repeat and paired difference matches canonical CSV",
    6: "Both measured runtimes verified as C_L=3, C_E=1, B=1",
    7: "No Configuration B label in the figure",
    8: "No eta threshold or reference line",
    9: "No causal queue/GPU explanation in the figure",
    10: "No universal optimality claim",
    11: "Concentrated/dispersed are controlled placement conditions",
    12: "Every valid L224/E16 repetition is visible",
}


def require(condition, message):
    if not condition:
        raise ValueError("Figure validation failed: " + message)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def near(a, b):
    # Cross-file floating-point roundoff only; not a scientific decision threshold.
    return math.isclose(float(a), float(b), rel_tol=1e-12, abs_tol=1e-12)


def read_csv(path):
    with path.open(newline="") as stream:
        return list(csv.DictReader(stream))


def git(root, *args):
    return subprocess.check_output(
        ["git", "--no-optional-locks", "-C", str(root), *args], text=True
    ).strip()


def find_root():
    for parent in Path(__file__).resolve().parents:
        if (parent / ".git").exists() and (parent / "results").is_dir():
            return parent
    raise ValueError("Use --repo-root to specify the canonical repository")


def inventory(bases):
    result = []
    for base in bases:
        for path in sorted(base.rglob("*")):
            if path.is_file():
                stat = path.stat()
                result.append((str(path), stat.st_size, stat.st_mtime_ns))
    return result


def digest_inventory(items):
    return hashlib.sha256(json.dumps(items, separators=(",", ":")).encode()).hexdigest()


def load_validate(root):
    """Read complete campaign coverage, then select exactly the requested split."""
    hashes, selected, schedule, hardware, pair_values = {}, {}, {}, {}, {}

    def read(path):
        require(path.is_file(), f"missing input: {path}")
        hashes[str(path.relative_to(root))] = sha(path)
        return path.read_text()

    for campaign, (repeats, planned_count, prereg, verdict_file) in CAMPAIGNS.items():
        base = root / "results/timely_capacity_campaign/v2_2" / campaign
        names = [
            "plan.json", "plan.sha256", "session_plan.json", "runtime_manifest.json",
            "assignment_manifest.json", "assignment_table.csv", "source_sha256.json",
            prereg, "ANALYSIS_SPECIFICATION.md", "analysis01/per_run.csv",
            "analysis01/paired_comparison.csv", "analysis01/per_stream.csv",
            "analysis01/per_path.csv", "analysis01/validity_summary.json",
            "analysis01/" + verdict_file,
        ]
        contents = {name: read(base / name) for name in names}
        plan = json.loads(contents["plan.json"])
        session = json.loads(contents["session_plan.json"])
        runtime = json.loads(contents["runtime_manifest.json"])["runtime"]
        validity = json.loads(contents["analysis01/validity_summary.json"])
        require(contents["plan.sha256"].split()[0] == sha(base / "plan.json"), "plan hash")
        for name in names:
            if name in plan["artifact_sha256"]:
                require(sha(base / name) == plan["artifact_sha256"][name], f"frozen artifact {name}")
        for values in [runtime, plan["runtime"]]:
            for key, expected in {
                "C_L": 3, "C_E": 1, "B": 1, "K": 8, "source_FPS_per_stream": 30,
                "deadline_ms": 100, "active_seconds": 60, "repeats": repeats,
            }.items():
                require(values[key] == expected, f"{campaign}: runtime {key}")
            require(values["pruning"] is True, "expired-frame dropping must remain ON")
            require(values["source_phase_ns"] == [0] * 8, "logical source phase unchanged")
        require("Paired" in contents[prereg] and "same" in contents[prereg], "preregistered pairing")

        runs = read_csv(base / "analysis01/per_run.csv")
        require(len(runs) == planned_count, f"{campaign}: complete measured coverage")
        require(len({row["run_id"] for row in runs}) == planned_count, "unique run identities")
        measured = [entry for entry in plan["order"] if int(entry["repeat"]) != 0]
        require({row["run_id"] for row in runs} == {row["run_id"] for row in measured}, "plan run IDs")
        require(session["order"] == plan["order"], "session order binding")
        require(validity["planned"] == planned_count, "validity planned count")
        require(validity.get("valid_count", validity.get("valid")) == planned_count,
                "all planned measured runs valid")
        require(not validity["errors"], "validity errors")
        by_run, summaries = {}, {}
        for row in runs:
            require(row["integrity_status"] == "VALID", "do not hide invalid measured runs")
            require([int(row[key]) for key in ("C_L", "C_E", "B")] == [3, 1, 1], "run runtime")
            summary = json.loads(read(base / row["run_id"] / "summary.json"))
            require(summary["integrity_status"] == "VALID", "actual run validity")
            require(summary["run_id"] == row["run_id"], "actual run identity")
            by_run[row["run_id"]] = row
            summaries[row["run_id"]] = summary
        hardware[campaign] = dict(Counter(s["hardware_status"] for s in summaries.values()))
        require(hardware[campaign] == {"PROTECTION_LIMITED": planned_count}, "hardware flag provenance")
        l224 = [row for row in runs if int(row["rate_local"]) == 224]
        keys = [(int(row["round"]), row["pattern"]) for row in l224]
        require(len(keys) == 2 * repeats and len(set(keys)) == len(keys), "L224 repeat coverage")
        require(set(keys) == {(n, p) for n in range(1, repeats + 1) for p in LABELS}, "L224 pairs")
        selected[campaign] = {key: row for key, row in zip(keys, l224)}
        streams = read_csv(base / "analysis01/per_stream.csv")
        paths = read_csv(base / "analysis01/per_path.csv")
        for row in l224:
            require(int(row["rate_edge"]) == 16, "L224/E16 split")
            summary = summaries[row["run_id"]]
            require(summary["source_frames"] == 14400, "active source count")
            ss = [item for item in streams if item["run_id"] == row["run_id"]]
            pp = [item for item in paths if item["run_id"] == row["run_id"]]
            require(len(ss) == 8 and {int(s["value"]) for s in ss} == set(range(8)), "all eight streams")
            require(len(pp) == 2 and {p["value"] for p in pp} == {"LOCAL", "EDGE"}, "both paths")
            for s in ss:
                require(int(s["admitted"]) == 1800, "source denominator")
                require(sum(int(s[k]) for k in ("timely", "late", "expired")) == 1800, "terminal partition")
                require(near(s["TIR"], int(s["timely"]) / 1800), "stream TIR")
            require(float(row["worst_stream_TIR"]) == min(float(s["TIR"]) for s in ss), "R_min")
            require(near(row["total_timely_FPS"], sum(int(s["timely"]) for s in ss) / 60), "timely FPS")
            require(near(row["worst_stream_TIR"], summary["worst_stream_TIR"]), "summary R_min")
            require(near(row["total_timely_FPS"], summary["timely_FPS"]), "summary timely FPS")
            for path in pp:
                prefix = "Local" if path["value"] == "LOCAL" else "Edge"
                require(near(row[prefix + "_timely_FPS"], path["timely_FPS"]), "path timely FPS")
            require(near(row["total_timely_FPS"], float(row["Local_timely_FPS"]) + float(row["Edge_timely_FPS"])),
                    "Local + Edge = Total")

        pairs = read_csv(base / "analysis01/paired_comparison.csv")
        pair_values[campaign] = {}
        for metric in ("worst_stream_TIR", "total_timely_FPS"):
            candidates = [p for p in pairs if p["metric"] == metric and
                          (p.get("rate_local") == "224" if repeats == 3 else p.get("comparison") == "P1")]
            require(len(candidates) == 1, "unique paired comparison")
            pair = candidates[0]
            if repeats == 5:
                require(pair["subtraction"] == "A-B", "confirmation P1 subtraction")
            values = []
            for n in range(1, repeats + 1):
                a, b = selected[campaign][n, "ALIGNED"], selected[campaign][n, "STAGGERED"]
                delta = float(pair[f"R{n}"])
                require(near(delta, float(b[metric]) - float(a[metric])), "paired difference consistency")
                require(delta > 0, "factual positive-pair annotation must match data")
                values.append(pair[f"R{n}"])
            pair_values[campaign][metric] = values

        manifest = json.loads(contents["assignment_manifest.json"])
        table = read_csv(base / "assignment_table.csv")
        schedule[campaign] = {}
        for pattern in LABELS:
            subset = [row for row in table if int(row["Local_FPS"]) == 224 and
                      (row.get("placement") == pattern if repeats == 3 else
                       row.get("condition") == ("B" if pattern == "ALIGNED" else "A"))]
            require(len(subset) == 240, "schedule cardinality")
            identity = [(int(row["stream_id"]), int(row["source_slot"])) for row in subset]
            require(len(set(identity)) == 240 and set(identity) == {(k, n) for k in range(8) for n in range(30)},
                    "exact schedule identities")
            m = manifest["L224" + pattern]
            cells, offsets = [[0] * 30 for _ in range(8)], [[0] * 30 for _ in range(8)]
            for row in subset:
                k, n = int(row["stream_id"]), int(row["source_slot"])
                require(row["assignment"] in ("LOCAL", "EDGE"), "assignment label")
                require(int(row["phase"]) == m["phase_vector"][k], "assignment phase")
                require(int(row["Edge_FPS"]) == 16, "schedule Edge rate")
                cells[k][n] = int(row["assignment"] == "EDGE")
                offsets[k][n] = int(row["scheduled_source_offset_ns"])
                require(offsets[k][n] == n * 10**9 // 30, "scheduled source time")
            me = [sum(cells[k][n] for k in range(8)) for n in range(30)]
            ml = [8 - v for v in me]
            require(cells == m["edge_masks"], "manifest/table cell match")
            require([[1 - v for v in row] for row in cells] == m["local_masks"], "Local mask match")
            require(me == m["m_E"] and ml == m["m_L"], "per-slot assignment loads")
            require([sum(row) for row in cells] == [2] * 8, "per-stream Edge count")
            require(sum(me) == 16 and sum(ml) == 224, "same one-second mean split")
            require(max(me) == (8 if pattern == "ALIGNED" else 1), "Edge assignment peak")
            require(m["phase_vector"] == ([0] * 8 if pattern == "ALIGNED" else [0, 2, 4, 6, 8, 9, 11, 13]),
                    "verified phase vectors")
            require(all(int(row["m_E"]) == me[int(row["source_slot"])] and
                        int(row["m_L"]) == ml[int(row["source_slot"])] for row in subset), "table loads")
            schedule[campaign][pattern] = dict(cells=cells, offsets=offsets, me=me, ml=ml,
                                                phase=m["phase_vector"])
        require(schedule[campaign]["ALIGNED"]["offsets"] == schedule[campaign]["STAGGERED"]["offsets"],
                "placement does not alter source timestamps")
    require(schedule["grid03_mini01"] == schedule["block_b_confirmation03"], "confirmation inherits exact schedule")
    return selected, schedule, hardware, pair_values, hashes


def draw_figure(selected, schedule):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import ListedColormap
    from matplotlib import font_manager
    from matplotlib.text import Text
    import numpy as np

    font_path = font_manager.findfont(font_manager.FontProperties(family=FONT), fallback_to_default=False)
    plt.rcParams.update({
        "font.family": FONT, "font.size": 9, "axes.labelsize": MIN_FONT,
        "axes.titlesize": 9.5, "xtick.labelsize": MIN_FONT, "ytick.labelsize": MIN_FONT,
        "axes.linewidth": 0.65, "xtick.major.width": 0.65, "ytick.major.width": 0.65,
        "xtick.major.size": 2.5, "ytick.major.size": 2.5,
        "pdf.fonttype": 42, "ps.fonttype": 42, "svg.fonttype": "none",
        "svg.hashsalt": "preliminary-temporal-placement-l224e16-v1",
        "figure.facecolor": "white", "axes.facecolor": "white",
    })
    fig = plt.figure(figsize=(WIDTH, HEIGHT), dpi=100)
    texts = []

    def text(x, y, value, **kwargs):
        item = fig.text(x, y, value, fontsize=kwargs.pop("fontsize", 9), **kwargs)
        texts.append(item)
        return item

    for label, x, title, subtitle in [
        ("(a)", 0.020, "Controlled assignment", "structure"),
        ("(b)", 0.426, "Preliminary screening", "Grid03-mini (3 repeats)"),
        ("(c)", 0.726, "Independent confirmation", "Confirmation03 (5 repeats)"),
    ]:
        text(x, 0.954, label, fontweight="bold", fontsize=9.5)
        text(x + 0.041, 0.954, title, fontsize=9.5)
        text(x + 0.041, 0.911, subtitle, fontsize=MIN_FONT)

    # Each QuadMesh cell is vector geometry, not an embedded raster image.
    cmap = ListedColormap(["#EEF0F2", COLORS["STAGGERED"]])
    for pattern, bottom, heading_y in [("ALIGNED", 0.592, 0.823), ("STAGGERED", 0.282, 0.513)]:
        ax = fig.add_axes([0.070, bottom, 0.280, 0.205])
        text(0.070, heading_y, LABELS[pattern], fontsize=MIN_FONT)
        cells = schedule["grid03_mini01"][pattern]["cells"]
        ax.pcolormesh(np.arange(31), np.arange(9), np.array(cells), cmap=cmap,
                      vmin=0, vmax=1, shading="flat", edgecolors="white", linewidth=0.22,
                      antialiased=False, rasterized=False)
        ax.set(xlim=(0, 30), ylim=(8, 0))
        ax.set_yticks(np.arange(8) + 0.5, [str(k) for k in range(8)])
        ax.set_xticks([n + 0.5 for n in [0, 5, 10, 15, 20, 25, 29]],
                      [str(n) for n in [0, 5, 10, 15, 20, 25, 29]])
        ax.set_ylabel("Stream", labelpad=3)
        ax.tick_params(axis="y", length=0, pad=2)
        ax.tick_params(axis="x", pad=2)
        if pattern == "STAGGERED":
            ax.set_xlabel("Source slot n", labelpad=3)
    from matplotlib.patches import Rectangle
    for x, name, color in [(0.095, "Local", "#EEF0F2"), (0.217, "Edge", COLORS["STAGGERED"])]:
        fig.add_artist(Rectangle((x, 0.159), 0.022, 0.025, transform=fig.transFigure,
                                 facecolor=color, edgecolor="#777777", linewidth=0.5))
        text(x + 0.029, 0.160, name, fontsize=MIN_FONT)
    text(0.070, 0.073, "Same L224/E16 split;\n28 L + 2 E per stream", fontsize=9,
         linespacing=1.3)

    plotted = {}
    for campaign, left in [("grid03_mini01", 0.459), ("block_b_confirmation03", 0.759)]:
        repeats = CAMPAIGNS[campaign][0]
        ax = fig.add_axes([left, 0.245, 0.218, 0.552])
        ax.set(xlim=(-0.38, 1.46), ylim=(0.90, 1.005))
        ax.set_xticks([0, 1], ["Concentrated", "Dispersed"])
        ax.set_yticks([0.90, 0.925, 0.95, 0.975, 1.0], ["0.900", "0.925", "0.950", "0.975", "1.000"])
        ax.tick_params(axis="both", pad=3)
        ax.spines[["top", "right"]].set_visible(False)
        ax.set_axisbelow(True)
        ax.grid(axis="y", color="#E5E5E5", linewidth=0.45)
        if campaign == "grid03_mini01":
            ax.set_ylabel("Worst-stream timely inference ratio, R_min", labelpad=5)
        offsets = np.linspace(-0.14, 0.14, repeats)
        plotted[campaign] = {"pairs": [], "means": {}}
        for repeat, offset in enumerate(offsets, 1):
            values = [float(selected[campaign][repeat, pattern]["worst_stream_TIR"]) for pattern in LABELS]
            xs = [float(offset), 1 + float(offset)]
            line, = ax.plot(xs, values, color="#949494", linewidth=0.65, zorder=2)
            for index, pattern in enumerate(LABELS):
                ax.plot(xs[index], values[index], marker=MARKERS[pattern], markersize=3.7,
                        color=COLORS[pattern], markeredgecolor=COLORS[pattern], markeredgewidth=0.5,
                        linestyle="none", zorder=3)
            plotted[campaign]["pairs"].append({"repeat": repeat, "x": xs, "R_min": values})
            require(list(line.get_ydata()) == values, "exact plotted pair ordinates")
        for index, pattern in enumerate(LABELS):
            values = [float(selected[campaign][n, pattern]["worst_stream_TIR"]) for n in range(1, repeats + 1)]
            mean = statistics.mean(values)
            # Separate x position ensures the mean never covers an observed repeat.
            x = index + 0.28
            mean_artist, = ax.plot(x, mean, marker=MARKERS[pattern], markersize=7,
                                  markerfacecolor="none", markeredgecolor=COLORS[pattern],
                                  markeredgewidth=1.3, linestyle="none", zorder=4)
            require(float(mean_artist.get_ydata()[0]) == mean, "exact mean ordinate")
            plotted[campaign]["means"][pattern] = {"x": x, "R_min": mean}
        text(left + 0.109, 0.846, "Filled: repeats; open: mean", fontsize=MIN_FONT, ha="center")
        text(left + 0.109, 0.090, f"{repeats}/{repeats} paired differences > 0", fontsize=MIN_FONT, ha="center")

    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    bounds = fig.bbox
    font_sizes = []
    for item in fig.findobj(match=Text):
        if not item.get_visible() or not item.get_text():
            continue
        font_sizes.append(item.get_fontsize())
        box = item.get_window_extent(renderer)
        require(box.x0 >= bounds.x0 and box.y0 >= bounds.y0 and
                box.x1 <= bounds.x1 and box.y1 <= bounds.y1,
                "text outside fixed figure bounds: " + item.get_text())
    require(min(font_sizes) >= MIN_FONT, "minimum final font size")
    visible_text = "\n".join(item.get_text() for item in fig.findobj(match=Text)
                             if item.get_visible() and item.get_text())
    for forbidden in ["ALIGNED", "STAGGERED", "Configuration B", "eta", "η", "optimal",
                      "algorithm", "policy", "scheme", "queue", "GPU", "causes"]:
        require(forbidden not in visible_text, "out-of-scope display wording: " + forbidden)
    require([len(plotted[c]["pairs"]) for c in CAMPAIGNS] == [3, 5], "separate pair counts")
    return fig, plotted, {"font_path": font_path, "font_sha256": sha(Path(font_path)),
                          "min_font_pt": min(font_sizes), "max_font_pt": max(font_sizes),
                          "matplotlib_version": matplotlib.__version__, "numpy_version": np.__version__,
                          "visible_text": visible_text}


def write_data(output, selected, plotted, pairs):
    fields = ["campaign", "record_type", "repeat", "placement", "run_id", "R_min",
              "total_timely_FPS", "Local_timely_FPS", "Edge_timely_FPS", "plot_x",
              "paired_delta_R_min", "paired_delta_total_timely_FPS"]
    data = output / (STEM + "_data.csv")
    with data.open("x", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for campaign in CAMPAIGNS:
            for pair in plotted[campaign]["pairs"]:
                n = pair["repeat"]
                for index, pattern in enumerate(LABELS):
                    row = selected[campaign][n, pattern]
                    writer.writerow(dict(campaign=campaign, record_type="observed_repeat", repeat=n,
                                         placement=LABELS[pattern], run_id=row["run_id"],
                                         R_min=row["worst_stream_TIR"], total_timely_FPS=row["total_timely_FPS"],
                                         Local_timely_FPS=row["Local_timely_FPS"], Edge_timely_FPS=row["Edge_timely_FPS"],
                                         plot_x=pair["x"][index],
                                         paired_delta_R_min=pairs[campaign]["worst_stream_TIR"][n - 1],
                                         paired_delta_total_timely_FPS=pairs[campaign]["total_timely_FPS"][n - 1]))
            for pattern in LABELS:
                rows = [selected[campaign][n, pattern] for n in range(1, CAMPAIGNS[campaign][0] + 1)]
                writer.writerow(dict(campaign=campaign, record_type="condition_mean", repeat="",
                                     placement=LABELS[pattern], run_id="", R_min=plotted[campaign]["means"][pattern]["R_min"],
                                     total_timely_FPS=statistics.mean(float(r["total_timely_FPS"]) for r in rows),
                                     Local_timely_FPS=statistics.mean(float(r["Local_timely_FPS"]) for r in rows),
                                     Edge_timely_FPS=statistics.mean(float(r["Edge_timely_FPS"]) for r in rows),
                                     plot_x=plotted[campaign]["means"][pattern]["x"]))
    exported = read_csv(data)
    observed = [r for r in exported if r["record_type"] == "observed_repeat"]
    require(len(observed) == 16 and len(exported) == 20, "16 observations plus four separate campaign means")
    reverse = {v: k for k, v in LABELS.items()}
    for row in observed:
        original = selected[row["campaign"]][int(row["repeat"]), reverse[row["placement"]]]
        require(row["R_min"] == original["worst_stream_TIR"] and
                row["total_timely_FPS"] == original["total_timely_FPS"], "export preserves canonical value strings")


def write_provenance(output, root, hashes, selected, hardware, pairs, rendering, before, after):
    timestamp = datetime.now(timezone.utc).isoformat()
    lines = [
        "Preliminary Measurement temporal-placement figure provenance",
        f"generation_timestamp_utc: {timestamp}", f"repository: {root}",
        f"git_branch: {git(root, 'branch', '--show-current')}", f"git_HEAD: {git(root, 'rev-parse', 'HEAD')}",
        "runtime: C_L=3; C_E=1; TensorRT B=1; K=8; F=30 FPS/stream; aggregate=240 FPS; D=100 ms; active=60 s; expiry ON",
        "split: Local 224 FPS / Edge 16 FPS; per-stream 28 Local + 2 Edge per 30 source slots",
        "logical source phase: common_zero_offset; original physical capture synchronization: UNVERIFIED",
        "panel_a: exact assignment-time structure; not socket arrivals or GPU execution",
        "panel_b: Grid03-mini, three independent measured repeats per condition; same-repeat pairing",
        "panel_c: separately preregistered Confirmation03, five measured repeats per condition; same-round P1 A-B",
        "No cross-campaign pooling. No existing scientific verdict reclassified.",
        "hardware_status for all measured runs: " + json.dumps(hardware, sort_keys=True),
        "PROTECTION_LIMITED is retained as recorded. VALID does not mean absence of protection events.",
        f"dimensions_inches: {WIDTH} x {HEIGHT}", "PNG_dpi: 600",
        f"font: {FONT}; minimum={rendering['min_font_pt']} pt; maximum={rendering['max_font_pt']} pt",
        f"font_file_used_not_copied: {rendering['font_path']}", f"font_SHA256: {rendering['font_sha256']}",
        f"matplotlib: {rendering['matplotlib_version']}; numpy: {rendering['numpy_version']}",
        "R_min axis limits: [0.90, 1.005]; the metric is bounded in [0,1]. No eta line.",
        "Pair points: filled blue circles / orange squares. Means: larger open markers with the same condition encodings.",
        "Horizontal offsets separate coincident observations and the mean; only y coordinates encode measured R_min.",
        "No error bars or confidence intervals. Pair lines only connect preregistered repeat identities.",
        "scientific_inputs_SHA256_before_after: PASS",
        "no_experimental_result_modified: YES",
        "existing_paper_figures_unchanged: YES",
        f"preserved_file_inventory_count: {len(before)}",
        f"preserved_inventory_SHA256_before: {digest_inventory(before)}",
        f"preserved_inventory_SHA256_after: {digest_inventory(after)}",
        "", "SCIENTIFIC SCOPE CHECKS",
    ]
    for n, description in SCOPE_DESCRIPTIONS.items():
        lines.append(f"{n:02d} PASS: {description}")
    lines.extend(["", "CANONICAL INPUT SHA-256 (relative to repository)"])
    lines.extend(f"{value}  {path}" for path, value in sorted(hashes.items()))
    lines.extend(["", "PAIRED DIFFERENCES (source CSV strings, dispersed minus concentrated)"])
    for campaign in CAMPAIGNS:
        lines.append(campaign + ": " + json.dumps(pairs[campaign], sort_keys=True))
    lines.extend(["", "OPTIONAL SUPPLEMENTARY TIMELY-FPS TABLE (not plotted on the main axes)",
                  "campaign | placement | n | repeats | mean | min | max"])
    for campaign in CAMPAIGNS:
        for pattern in LABELS:
            values = [float(selected[campaign][n, pattern]["total_timely_FPS"])
                      for n in range(1, CAMPAIGNS[campaign][0] + 1)]
            lines.append(f"{campaign} | {LABELS[pattern]} | {len(values)} | {values} | "
                         f"{statistics.mean(values)} | {min(values)} | {max(values)}")
    lines.extend([
        "", "PROPOSED PAPER CAPTION",
        "Temporal placement at a fixed L224/E16 mean split. (a) Exact controlled assignment schedules for eight "
        "30-FPS streams: each stream receives 28 Local and two Edge assignments per 30 source slots. "
        "Temporally concentrated placement aligns Edge assignments across streams, whereas temporally dispersed "
        "placement shifts assignment phases without changing the logical source schedule or assignment counts. "
        "The schedules represent assignment-time structure, not simultaneous transmission or GPU execution. "
        "(b) Worst-stream timely inference ratio R_min in Grid03-mini, with three preregistered pairs. "
        "(c) The independently preregistered Confirmation03 comparison, with five pairs. Filled points are "
        "individual measured runs, gray lines connect the same repeat, and larger open markers show each "
        "condition's mean within its own campaign. Small horizontal offsets separate coincident observations. "
        "R_min is bounded in [0,1]; both measurement panels use the same restricted vertical range. "
        "The measured runtime is C_L=3, C_E=1, B=1, with a 100-ms deadline and expired-frame dropping enabled. "
        "The direction of the L224/E16 difference is reproduced in all five confirmation pairs. "
        "This comparison does not establish universal optimality or a causal mechanism.",
        "", "OUTPUT SHA-256 (provenance file excluded to avoid self-reference)",
    ])
    for path in sorted(output.iterdir()):
        if path.is_file():
            lines.append(f"{sha(path)}  {path.name}")
    (output / (STEM + "_provenance.txt")).write_text("\n".join(lines) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    root = (args.repo_root or find_root()).resolve()
    script = Path(__file__).resolve()
    output = (args.output_dir or script.parent).resolve()
    source_bases = [root / "results/timely_capacity_campaign/v2_2" / c for c in CAMPAIGNS]
    protected = source_bases + [root / "paper/figures/grid03_mini", root / "final_study_v1"]
    require(not any(output == p or output.is_relative_to(p) for p in protected), "output overlaps protected inputs")
    if output.exists():
        require(output.is_dir() and list(output.iterdir()) == [script] and script.parent == output,
                "output must be fresh (only this generator may already exist)")
    before = inventory(protected)
    selected, schedule, hardware, pairs, hashes = load_validate(root)
    with tempfile.TemporaryDirectory(prefix="preliminary-figure-mpl-") as mpl_dir:
        os.environ["MPLCONFIGDIR"] = mpl_dir
        fig, plotted, rendering = draw_figure(selected, schedule)
        if not output.exists():
            output.mkdir(parents=True, exist_ok=False)
        destination_script = output / script.name
        if destination_script != script:
            shutil.copyfile(script, destination_script)
        epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
        fig.savefig(output / (STEM + ".pdf"), format="pdf", metadata={
            "Title": "Preliminary temporal-placement measurements", "Creator": script.name,
            "CreationDate": epoch, "ModDate": epoch,
        })
        fig.savefig(output / (STEM + ".svg"), format="svg", metadata={"Date": None, "Creator": script.name})
        fig.savefig(output / (STEM + ".png"), format="png", dpi=600)
        write_data(output, selected, plotted, pairs)
        from PIL import Image
        from xml.etree import ElementTree
        with Image.open(output / (STEM + ".png")) as image:
            require(image.size == (round(WIDTH * 600), round(HEIGHT * 600)), "600-dpi PNG dimensions")
            require(all(abs(value - 600) < 0.1 for value in image.info["dpi"]), "PNG resolution")
        svg = ElementTree.parse(output / (STEM + ".svg")).getroot()
        require(not list(svg.iter("{http://www.w3.org/2000/svg}image")), "SVG must contain vector schedules")
        require((output / (STEM + ".pdf")).read_bytes().startswith(b"%PDF"), "PDF output")
        after = inventory(protected)
        require(before == after, "protected file inventory/mtime changed")
        require(all(sha(root / p) == h for p, h in hashes.items()), "canonical input hash changed")
        write_provenance(output, root, hashes, selected, hardware, pairs, rendering, before, after)
    print(f"OUTPUT_DIRECTORY: {output}")
    print(f"DIMENSIONS: {WIDTH} x {HEIGHT} in; PNG 600 dpi")
    print(f"FONT: {FONT}; {rendering['min_font_pt']}--{rendering['max_font_pt']} pt")
    print("PLOTTED_REPETITIONS: Grid03-mini=3 pairs; Confirmation03=5 pairs")
    print(f"SOURCE_SHA_CHECKS: PASS ({len(hashes)} inputs; frozen plan/artifact hashes verified)")
    for number, description in SCOPE_DESCRIPTIONS.items():
        print(f"SCOPE_CHECK_{number:02d}: PASS -- {description}")
    print("EXISTING_EXPERIMENTS_AND_PAPER_FIGURES: UNCHANGED")


if __name__ == "__main__":
    main()
