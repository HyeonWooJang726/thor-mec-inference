#!/usr/bin/env python3
"""Campaign 2 Section III figures from frozen CSVs; never runs an analyzer.

Usage:
  python3 -B plot_section3.py
  python3 -B plot_section3.py --output-dir /path/to/a/new/directory

Only proven generated target files may be replaced with --replace-generated.
Only this campaign's analysis01, paper_evidence01 and assignment artifacts
supply scientific data. Outputs default to the repository paper directory.
"""
import argparse
import csv
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import statistics
import tempfile
from collections import Counter, defaultdict
from datetime import datetime, timezone

CAMPAIGN = "block_b_edge_rate_sweep01"
RATES = tuple(range(0, 65, 8))
PLACEMENTS = ("CONCENTRATED", "DISPERSED")
LABEL = {"CONCENTRATED": "Concentrated", "DISPERSED": "Dispersed"}
COLOR = {"CONCENTRATED": "#355C82", "DISPERSED": "#C17C3C"}
MARKER = {"CONCENTRATED": "o", "DISPERSED": "s"}
OUTPUTS = {
    "fig1_e16.pdf", "fig1_e16.png", "fig2_edge_rate_sweep.pdf",
    "fig2_edge_rate_sweep.png", "figure_data_section3.csv", "captions_section3.tex",
    "validation_section3.json", "plot_section3.py",
}

def require(condition, message):
    if not condition:
        raise RuntimeError(message)

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def read_csv(path):
    with path.open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))

def close(a, b):
    # Verification of floating-point arithmetic only; not an effect threshold.
    return math.isclose(float(a), float(b), rel_tol=0.0, abs_tol=1e-12)

def stats(values):
    require(len(values) == 5, "A condition must retain all five run observations")
    return {"n": len(values), "mean": statistics.mean(values),
            "min": min(values), "max": max(values), "values": values}

def collect(campaign):
    require(campaign.name == CAMPAIGN, "Only the specified Campaign 2 is accepted")
    files = [
        "analysis01/validity_summary.json", "analysis01/per_run.csv",
        "analysis01/per_stream.csv", "analysis01/per_path.csv",
        "analysis01/paired_comparison.csv", "analysis01/condition_summary.csv",
        "analysis01/paired_summary.csv", "assignment_manifest.json",
        "assignment_table.csv", "paper_evidence01/PAPER_EVIDENCE_MANIFEST.json",
        "paper_evidence01/00_CLOSEOUT_SUMMARY.md",
        "paper_evidence01/02_TEMPORAL_PLACEMENT_SUMMARY.csv",
        "paper_evidence01/02_TEMPORAL_PLACEMENT_SUMMARY.md",
        "paper_evidence01/03_E16_STREAM_BURST_ANALYSIS.csv",
        "paper_evidence01/03_E16_STREAM_BURST_ANALYSIS.md",
    ]
    for name in files:
        require((campaign / name).is_file(), "Missing input: " + name)
    identities = {name: sha(campaign / name) for name in files}
    evidence_manifest = json.loads(
        (campaign / "paper_evidence01/PAPER_EVIDENCE_MANIFEST.json").read_text())
    for name in files:
        if name.startswith("paper_evidence01/"):
            key = name.split("/", 1)[1]
            if key in evidence_manifest["output_sha256"]:
                require(identities[name] == evidence_manifest["output_sha256"][key],
                        "Paper evidence output hash mismatch: " + name)
    validity = json.loads((campaign / files[0]).read_text())
    require({k: validity[k] for k in
             ("planned", "executed", "valid", "invalid", "not_executed")} ==
            dict(planned=85, executed=85, valid=85, invalid=0, not_executed=0),
            "Existing campaign closeout differs from the requested dataset")
    require(validity["status"] == "CAMPAIGN_COMPLETE", "Campaign not complete")
    rows = read_csv(campaign / "analysis01/per_run.csv")
    runs = {r["run_id"]: r for r in rows}
    require(len(runs) == len(rows) == 85, "Missing or duplicate run")
    require(set(runs) == set(validity["run_statuses"]), "Run ledger mismatch")
    for r in rows:
        require(r["campaign"] == CAMPAIGN, "Campaign pooling is forbidden")
        require(r["validity"] == r["integrity_status"] == "VALID",
                "Preserve existing validity; no exclusion is authorized")
        require((r["C_L"], r["C_E"], r["B"]) == ("3", "1", "1"),
                "Wrong runtime")
        require(int(r["source_count"]) == 14400, "Wrong source denominator")
        require(int(r["repeat"]) == int(r["round"]), "Round/repeat mismatch")
        require(float(r["R_min"]) == float(r["worst_stream_TIR"]),
                "R_min alias mismatch")
        require(close(r["R_min"], int(r["min_stream_timely_count"]) / 1800),
                "Worst-stream count mismatch")
        require(close(r["TIR_total"], int(r["total_timely_count"]) / 14400),
                "Overall source denominator mismatch")
        require(int(r["Local_assigned_count"]) == int(r["Local_FPS"]) * 60 and
                int(r["Edge_assigned_count"]) == int(r["Edge_FPS"]) * 60,
                "Assignment count mismatch")
    groups = defaultdict(list)
    for r in rows:
        groups[(int(r["Edge_FPS"]), r["placement"])].append(r)
    expected = {(0, "LOCAL_ONLY")} | {
        (e, p) for e in RATES[1:] for p in PLACEMENTS}
    require(set(groups) == expected, "Wrong measured condition registry")
    for key, group in groups.items():
        group.sort(key=lambda r: int(r["repeat"]))
        require([int(r["repeat"]) for r in group] == list(range(1, 6)),
                "Missing/duplicate repeat: " + str(key))
    pairs = read_csv(campaign / "analysis01/paired_comparison.csv")
    metric_pairs = [r for r in pairs if r["metric"] == "worst_stream_TIR"]
    require(len(metric_pairs) == 40, "Need 40 nonzero same-round pairs")
    require({(int(r["Edge_FPS"]), int(r["round"])) for r in metric_pairs} ==
            {(e, rep) for e in RATES[1:] for rep in range(1, 6)},
            "Nonzero paired comparison coverage mismatch")
    for r in pairs:
        require(r["pair_status"] == "OBSERVED_VALID_PAIR", "Unverified pairing")
        c = runs[r["concentrated_run_id"]]
        d = runs[r["dispersed_run_id"]]
        require(c["round"] == d["round"] == r["round"] and
                c["Edge_FPS"] == d["Edge_FPS"] == r["Edge_FPS"] and
                c["placement"] == "CONCENTRATED" and
                d["placement"] == "DISPERSED", "Pair linkage mismatch")
        metric = "R_min" if r["metric"] == "worst_stream_TIR" else r["metric"]
        require(close(float(d[metric]) - float(c[metric]), r["difference"]),
                "Existing paired value mismatch")
    e16_pairs = [r for r in metric_pairs if r["Edge_FPS"] == "16"]
    require(len(e16_pairs) == 5, "E16 must have exactly five pairs")
    per_stream = read_csv(campaign / "analysis01/per_stream.csv")
    stream_base = {(r["run_id"], int(r["value"])): r for r in per_stream}
    require(len(stream_base) == len(per_stream) == 680, "Stream ledger mismatch")
    paths = read_csv(campaign / "analysis01/per_path.csv")
    path_base = {(r["run_id"], r["value"]): r for r in paths}
    require(len(path_base) == len(paths) == 170, "Path ledger mismatch")
    for r in rows:
        for path, column in [("LOCAL", "Local_assigned_TIR"),
                             ("EDGE", "Edge_assigned_TIR")]:
            p = path_base[(r["run_id"], path)]
            assigned = int(p["admitted"])
            if assigned == 0:
                require(path == "EDGE" and int(r["Edge_FPS"]) == 0 and
                        not r[column] and not p["TIR"], "E0 Edge TIR must be N/A")
            else:
                require(close(r[column], int(p["timely"]) / assigned) and
                        close(p["TIR"], r[column]), "Assigned-frame TIR mismatch")
    e16_data = read_csv(
        campaign / "paper_evidence01/03_E16_STREAM_BURST_ANALYSIS.csv")
    streams = [r for r in e16_data if r["record_type"] == "STREAM"]
    require(len(streams) == 80, "E16 must have 10 runs by 8 streams")
    stream_groups = defaultdict(list)
    for r in streams:
        original = runs[r["run_id"]]
        require(int(original["Edge_FPS"]) == 16 and
                r["placement"] == original["placement"] and
                int(r["repeat"]) == int(original["repeat"]), "Wrong E16 stream row")
        k = int(r["stream_id"])
        require(int(r["Edge_assigned_count"]) == 120 and
                int(r["Local_assigned_count"]) == 1680 and
                int(r["source_count"]) == 1800, "Wrong stream denominator")
        require(sum(int(r["Edge_" + s]) for s in ("timely", "late", "expired")) == 120,
                "Edge timely/late/expired partition mismatch")
        require(sum(int(r["Local_" + s]) for s in ("timely", "late", "expired")) == 1680,
                "Local partition mismatch")
        base = stream_base[(r["run_id"], k)]
        require(int(base["admitted"]) == 1800 and
                int(base["timely"]) == int(r["Edge_timely"]) + int(r["Local_timely"]),
                "Stream timely count mismatch")
        stream_groups[(r["placement"], k)].append(r)
    require(set(stream_groups) ==
            {(p, k) for p in PLACEMENTS for k in range(8)}, "E16 stream coverage")
    for key, group in stream_groups.items():
        group.sort(key=lambda r: int(r["repeat"]))
        require([int(r["repeat"]) for r in group] == list(range(1, 6)),
                "Wrong E16 stream repeat coverage")
    for p in PLACEMENTS:
        for run in groups[(16, p)]:
            ss = [r for r in streams if r["run_id"] == run["run_id"]]
            require(sum(int(r["Edge_timely"]) for r in ss) ==
                    int(run["Edge_timely_count"]), "E16 Edge path count mismatch")
            require(sum(int(r["Edge_expired"]) for r in ss) ==
                    int(run["Edge_EXPIRED_DROP"]), "E16 expiration count mismatch")
    burst_rows = [r for r in e16_data if r["record_type"] == "BURST_FRAME"]
    require(len(burst_rows) == 4800, "Missing concentrated burst records")
    require(all(int(r["logical_burst_rank"]) == int(r["stream_id"]) + 1
                and r["placement"] == "CONCENTRATED" for r in burst_rows),
            "Fixed logical stream/rank mapping not established")
    require({r["run_id"] for r in burst_rows} ==
            {r["run_id"] for r in groups[(16, "CONCENTRATED")]},
            "Logical burst mapping does not cover all five runs")
    assignment = read_csv(campaign / "assignment_table.csv")
    manifest = json.loads((campaign / "assignment_manifest.json").read_text())
    a_groups = defaultdict(list)
    for r in assignment:
        if r["schedule_role"] == "MEASURED":
            a_groups[r["condition"]].append(r)
    pattern = {}
    for condition, ar in a_groups.items():
        e = int(ar[0]["Edge_FPS"])
        internal = ar[0]["placement"]
        p = ("LOCAL_ONLY" if e == 0 else
             {"ALIGNED": "CONCENTRATED", "STAGGERED": "DISPERSED"}[internal])
        require(len(ar) == 240, "Incomplete assignment period")
        cells = {(int(r["stream_id"]), int(r["source_slot"])): r for r in ar}
        require(len(cells) == 240 and set(cells) ==
                {(k, n) for k in range(8) for n in range(30)}, "Wrong assignment cells")
        me = [sum(cells[(k, n)]["assignment"] == "EDGE" for k in range(8))
              for n in range(30)]
        ml = [sum(cells[(k, n)]["assignment"] == "LOCAL" for k in range(8))
              for n in range(30)]
        ec = [sum(cells[(k, n)]["assignment"] == "EDGE" for n in range(30))
              for k in range(8)]
        lc = [sum(cells[(k, n)]["assignment"] == "LOCAL" for n in range(30))
              for k in range(8)]
        require(all(me[n] + ml[n] == 8 for n in range(30)), "Slot partition mismatch")
        require(ec == [e // 8] * 8 and lc == [30 - e // 8] * 8,
                "Wrong per-stream assignment counts")
        require(sum(me) == e and sum(ml) == 240 - e, "Mean split mismatch")
        for (k, n), cell in cells.items():
            require(int(cell["m_E"]) == me[n] and int(cell["m_L"]) == ml[n],
                    "Stored per-slot count mismatch")
            require(int(cell["scheduled_source_offset_ns"]) == n * 1000000000 // 30,
                    "Scheduled input index mismatch")
        ref = manifest[f"L{240-e}{internal}"]
        require(ref["m_E"] == me and ref["m_L"] == ml and
                ref["edge_peak"] == max(me), "Assignment manifest mismatch")
        require(ref["edge_masks"] ==
                [[int(cells[(k, n)]["assignment"] == "EDGE") for n in range(30)]
                 for k in range(8)], "Manifest mask mismatch")
        pattern[(e, p)] = {
            "condition": condition, "Edge_FPS": e, "Local_FPS": 240-e,
            "placement": p, "m_E": me, "m_L": ml, "min_m_E": min(me),
            "max_m_E": max(me), "Edge_per_stream_per_30": ec,
            "Local_per_stream_per_30": lc, "phase_vector": ref["phase_vector"],
        }
    require(set(pattern) == expected, "Wrong measured assignment coverage")
    for e in RATES[1:]:
        c, d = pattern[(e, "CONCENTRATED")], pattern[(e, "DISPERSED")]
        require(c["Edge_per_stream_per_30"] == d["Edge_per_stream_per_30"] and
                c["Local_per_stream_per_30"] == d["Local_per_stream_per_30"],
                "Unequal same-split stream counts")
    summaries = {}
    for (e, p), group in groups.items():
        for metric in ("R_min", "Local_assigned_TIR", "Edge_assigned_TIR"):
            if e == 0 and metric == "Edge_assigned_TIR":
                continue
            summaries[(e, p, metric)] = stats([float(r[metric]) for r in group])
    existing_summary = read_csv(campaign / "analysis01/condition_summary.csv")
    expanded_summary = read_csv(
        campaign / "paper_evidence01/02_TEMPORAL_PLACEMENT_SUMMARY.csv")
    for table in [existing_summary, expanded_summary]:
        for r in table:
            if "record_type" in r and r["record_type"] != "CONDITION_SUMMARY":
                continue
            metric = "R_min" if r["metric"] == "worst_stream_TIR" else r["metric"]
            key = (int(r["Edge_FPS"]), r["placement"], metric)
            if key in summaries:
                for field in ("mean", "min", "max"):
                    require(close(r[field], summaries[key][field]),
                            "Existing summary mismatch: " + str(key))
    e0_completion = []
    for r in groups[(0, "LOCAL_ONLY")]:
        completed = int(r["Local_completed_count"]) + int(r["Edge_completed_count"])
        require(completed == int(r["total_timely_count"]) +
                int(r["late_completion"]), "E0 completion cohort mismatch")
        e0_completion.append({
            "run_id": r["run_id"], "repeat": int(r["repeat"]),
            "active_source_completed_count": completed,
            "active_source_duration_s": 60,
            "cohort_completion_FPS": completed / 60,
            "raw_completion_FPS": float(r["raw_completion_FPS"]),
            "definition": "Active-source eventual completed count, including drain, / 60 s",
        })
    closeout = (campaign / "paper_evidence01/00_CLOSEOUT_SUMMARY.md").read_text()
    analyzer_lines = [
        line for line in closeout.splitlines()
        if re.search(r"analy[sz]e\.py", line, re.I) and
        re.search(r"\b[0-9a-f]{64}\b", line, re.I)
    ]
    return {
        "campaign": campaign, "source_files": files, "identities": identities,
        "rows": rows, "runs": runs, "groups": groups, "e16_pairs": e16_pairs,
        "stream_groups": stream_groups, "summaries": summaries, "pattern": pattern,
        "validity": validity, "e0_completion": e0_completion,
        "analyzer_sha_record": analyzer_lines or "ANALYZER_SHA_RECORD_NOT_FOUND",
        "nonzero_pairs": metric_pairs,
    }

def make_data(data):
    records = []
    common = {"campaign": CAMPAIGN}
    for p in PLACEMENTS:
        for r in data["groups"][(16, p)]:
            records.append(dict(common, figure=1, panel="a", record_type="RUN",
                Edge_FPS=16, Local_FPS=224, placement=p, repeat=int(r["repeat"]),
                run_id=r["run_id"], metric="R_min", value=float(r["R_min"]),
                denominator=1800, timely_count=int(r["min_stream_timely_count"]),
                source="analysis01/per_run.csv;analysis01/paired_comparison.csv"))
        for k in range(8):
            group = data["stream_groups"][(p, k)]
            vals = [int(r["Edge_timely"]) / int(r["Edge_assigned_count"]) for r in group]
            for r, val in zip(group, vals):
                records.append(dict(common, figure=1, panel="b", record_type="RUN",
                    Edge_FPS=16, Local_FPS=224, placement=p, repeat=int(r["repeat"]),
                    stream_id=k, run_id=r["run_id"], metric="Edge_assigned_TIR",
                    value=val, denominator=int(r["Edge_assigned_count"]),
                    timely_count=int(r["Edge_timely"]), expired_count=int(r["Edge_expired"]),
                    late_count=int(r["Edge_late"]),
                    logical_burst_position=(k+1 if p == "CONCENTRATED" else ""),
                    source="paper_evidence01/03_E16_STREAM_BURST_ANALYSIS.csv:STREAM"))
            summary = stats(vals)
            records.append(dict(common, figure=1, panel="b", record_type="SUMMARY",
                Edge_FPS=16, Local_FPS=224, placement=p, stream_id=k,
                metric="Edge_assigned_TIR", denominator=120,
                n=summary["n"], mean=summary["mean"], min=summary["min"], max=summary["max"],
                run_ids=json.dumps([r["run_id"] for r in group]),
                source="paper_evidence01/03_E16_STREAM_BURST_ANALYSIS.csv:STREAM"))
    for (e, p), group in sorted(data["groups"].items()):
        for panel, metrics in [("a", ("R_min",)),
                               ("b", ("Local_assigned_TIR", "Edge_assigned_TIR"))]:
            for metric in metrics:
                if e == 0 and metric == "Edge_assigned_TIR":
                    continue
                for r in group:
                    denom = (1800 if metric == "R_min" else
                             int(r["Local_assigned_count" if metric.startswith("Local")
                                   else "Edge_assigned_count"]))
                    count = int(r["min_stream_timely_count" if metric == "R_min" else
                                  ("Local_timely_count" if metric.startswith("Local")
                                   else "Edge_timely_count")])
                    records.append(dict(common, figure=2, panel=panel, record_type="RUN",
                        Edge_FPS=e, Local_FPS=240-e, placement=p, repeat=int(r["repeat"]),
                        run_id=r["run_id"], metric=metric, value=float(r[metric]),
                        denominator=denom, timely_count=count,
                        source="analysis01/per_run.csv;analysis01/per_path.csv"))
                summary = data["summaries"][(e, p, metric)]
                records.append(dict(common, figure=2, panel=panel, record_type="SUMMARY",
                    Edge_FPS=e, Local_FPS=240-e, placement=p, metric=metric,
                    n=summary["n"], mean=summary["mean"], min=summary["min"],
                    max=summary["max"], run_ids=json.dumps([r["run_id"] for r in group]),
                    source="analysis01/per_run.csv"))
    for e in RATES:
        records.append(dict(common, figure=2, panel="a", record_type="REFERENCE",
            Edge_FPS=e, Local_FPS=240-e, metric="Local-assignment fraction",
            value=1-e/240, source="Arithmetic definition from assigned rates"))
    for (e, p), pattern in sorted(data["pattern"].items()):
        records.append(dict(common, figure=2, panel="caption", record_type="ASSIGNMENT_MAX",
            Edge_FPS=e, Local_FPS=240-e, placement=p, metric="max_n m_E[n]",
            value=pattern["max_m_E"],
            source="assignment_table.csv:schedule_role=MEASURED"))
    return records

def captions(data):
    pattern=data["pattern"]
    rates=", ".join(str(e) for e in RATES[1:])
    concentrated=[pattern[(e,"CONCENTRATED")]["max_m_E"] for e in RATES[1:]]
    dispersed=[pattern[(e,"DISPERSED")]["max_m_E"] for e in RATES[1:]]
    if len(set(concentrated))==1:
        concentrated_text=f"{concentrated[0]} for all nonzero Edge rates"
    else:
        concentrated_text="["+ ", ".join(map(str,concentrated))+f"] at $E={rates}$ FPS"
    dispersed_text="["+ ", ".join(map(str,dispersed))+f"] at $E={rates}$ FPS"
    one=(
        r"Fixed-split comparison at L224/E16 in Campaign 2 "
        r"($C_L=3$, $C_E=1$, TensorRT batch $B=1$). "
        r"Temporally concentrated and temporally dispersed placement have "
        r"identical aggregate assignment counts and identical per-stream "
        r"assignment counts. (a) All five paired worst-stream TIR ($R_{\min}$) "
        r"measurements; each gray line connects the two observations in one "
        r"repeat. (b) Stream-wise timely ratios of Edge-assigned frames for "
        r"both Concentrated and Dispersed. Each run and stream has 120 "
        r"Edge-assigned frames in the denominator, including pre-submission "
        r"expiration; submitted-only counts are not used. Point ranges in "
        r"(b) show means and observed min--max across five runs, not confidence "
        r"intervals, with small horizontal offsets around each stream ID "
        r"for visibility. Concentrated stream IDs 0--7 are fixed to logical "
        r"burst positions 1--8. This is assigned logical order, not network "
        r"transmission or GPU execution rank; a causal position effect is "
        r"not isolated. TIR is bounded in $[0,1]$."
    )
    two=(
        r"Temporal placement across the Campaign 2 Edge-rate sweep. "
        r"(a) Worst-stream TIR. (b) Local- and Edge-path assigned-frame TIR, "
        r"using all frames assigned to each path, including expired frames. "
        r"The common E0 Local-only point is shown once in each panel; "
        r"E0 has no defined Edge-assigned TIR. The Local-assignment fraction "
        r"$1-E/240$ is an arithmetic reference only, not a bound, expected "
        r"TIR, or performance guarantee. Markers and error bars show means "
        r"and observed min--max across five runs, not confidence intervals. "
        r"Connecting lines are visual guides between measured points only; "
        r"they do not estimate unmeasured rates. Figure~\ref{fig:campaign-two-e16} "
        r"and this figure share the same E16 five pairs. Maximum Edge assignments "
        r"per input instant were "+concentrated_text+" for Concentrated, and "+
        dispersed_text+r" for Dispersed; E0 has zero. These are maximum frame "
        r"counts at the same scheduled input index, not GPU concurrency, "
        r"simultaneous transmission, or server concurrency. Assignment "
        r"burstiness is descriptive and does not establish the cause of "
        r"deadline failures."
    )
    # Cross-reference labels cannot be assumed without the root document.
    # Refer to the paired fixed-split figure in prose rather than inventing a label.
    two=two.replace(r"Figure~\ref{fig:campaign-two-e16} and this figure",
                    "The fixed-split figure and this figure")
    return (r"\newcommand{\CampaignTwoFigOneCaption}{"+one+"}\n\n"+
            r"\newcommand{\CampaignTwoFigTwoCaption}{"+two+"}\n")

def render(data, records):
    with tempfile.TemporaryDirectory(prefix="campaign2_paper_matplotlib_") as cache:
        os.environ["MPLCONFIGDIR"] = cache
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib import font_manager
        from matplotlib.lines import Line2D
        from matplotlib.text import Text
        import numpy as np
        from PIL import Image
        font_path = font_manager.findfont(
            font_manager.FontProperties(family="Liberation Sans"), fallback_to_default=False)
        plt.rcParams.update({
            "font.family": "Liberation Sans", "font.size": 9.0,
            "axes.labelsize": 9.5, "axes.titlesize": 10.0,
            "xtick.labelsize": 8.5, "ytick.labelsize": 8.5,
            "legend.fontsize": 8.5, "axes.linewidth": 0.7,
            "xtick.major.width": 0.65, "ytick.major.width": 0.65,
            "xtick.major.size": 3.0, "ytick.major.size": 3.0,
            "pdf.fonttype": 42, "ps.fonttype": 42,
            "figure.facecolor": "white", "axes.facecolor": "white",
            "savefig.facecolor": "white", "path.simplify": False,
        })
        buffers, drawing, artist_points = {}, {}, []
        def style(ax, panel):
            ax.spines["top"].set_visible(False)
            ax.spines["right"].set_visible(False)
            ax.set_axisbelow(True)
            ax.set_title(panel, loc="left", fontweight="bold", pad=8)
        def handle(p, label, path=None):
            edge = path == "Edge"
            face = "white" if edge or p=="DISPERSED" else COLOR[p]
            line = ((0,(4.0,1.8,1.0,1.8)) if p=="CONCENTRATED" else (0,(1.2,1.8))) \
                if edge else ("-" if p=="CONCENTRATED" else "--")
            return Line2D([],[],label=label,color=COLOR[p],marker=MARKER[p],
                          markerfacecolor=face,markeredgewidth=0.9,
                          markersize=5.5 if edge else 4.5,linewidth=1.1,linestyle=line)
        def ranges(ax,x,summaries,p,label=None,path=None,connected=True):
            means=np.array([s["mean"] for s in summaries])
            lower=means-np.array([s["min"] for s in summaries])
            upper=np.array([s["max"] for s in summaries])-means
            edge=path=="Edge"
            linestyle=(((0,(4.0,1.8,1.0,1.8)) if p=="CONCENTRATED" else (0,(1.2,1.8)))
                       if edge else ("-" if p=="CONCENTRATED" else "--"))
            if not connected:linestyle="None"
            color=COLOR.get(p,"#353535")
            face="white" if edge or p=="DISPERSED" else color
            size=5.5 if edge else 4.5
            if p=="LOCAL_ONLY":face=color;size=4.9
            artist=ax.errorbar(x,means,yerr=np.vstack([lower,upper]),
                color=color,ecolor=color,marker=MARKER.get(p,"D"),
                markerfacecolor=face,markeredgecolor=color,markeredgewidth=0.85,
                markersize=size,linestyle=linestyle,linewidth=1.05,
                elinewidth=0.70,capsize=2.0,capthick=0.7,zorder=4 if edge else 3)
            if not connected and p=="DISPERSED":
                for bar in artist.lines[2]:bar.set_linestyle("--")
            require(np.array_equal(artist.lines[0].get_ydata(),means),"Artist mean mismatch")
            artist_points.append({"placement":p,"label":label,"path":path,
                "display_x":list(map(float,x)),"mean":means.tolist(),
                "min":[s["min"] for s in summaries],"max":[s["max"] for s in summaries]})
            return artist
        def finish(fig,name):
            fig.canvas.draw()
            renderer=fig.canvas.get_renderer()
            width,height=fig.canvas.get_width_height()
            outside=[];font_sizes=[]
            for text in fig.findobj(Text):
                if not text.get_visible() or not text.get_text():continue
                font_sizes.append(text.get_fontsize())
                box=text.get_window_extent(renderer)
                if box.x0 < -.5 or box.y0 < -.5 or box.x1 > width+.5 or box.y1 > height+.5:
                    outside.append(text.get_text())
            require(not outside,f"Clipped text in {name}: {outside}")
            require(min(font_sizes)>=8.5,"Font below 8.5 pt")
            for ax in fig.axes:
                legend=ax.get_legend()
                if legend is not None:
                    box=legend.get_window_extent(renderer)
                    require(not box.overlaps(ax.bbox),"Legend overlaps plotted data")
            pdf=io.BytesIO();png=io.BytesIO()
            fig.savefig(pdf,format="pdf",metadata={
                "Title":"","Author":"","Creator":"plot_section3.py",
                "CreationDate":None,"ModDate":None})
            fig.savefig(png,format="png",dpi=600)
            image=Image.open(io.BytesIO(png.getvalue()))
            require(image.size==tuple(round(v*600) for v in fig.get_size_inches()),
                    "Unexpected PNG dimensions")
            require(all(abs(v-600)<.1 for v in image.info["dpi"]),"PNG is not 600 dpi")
            require(pdf.getvalue().startswith(b"%PDF") and b"/Subtype /Image" not in pdf.getvalue(),
                    "PDF is not vector-only")
            drawing[name]={
                "dimensions_inches":fig.get_size_inches().tolist(),
                "PNG_pixels":list(image.size),"PNG_dpi":list(image.info["dpi"]),
                "vector_PDF":True,"minimum_font_size_pt":min(font_sizes),
                "font_family":"Liberation Sans","font_path":font_path,
                "text_inside_canvas":True,"legends_outside_data":True,
                "condition_encoding":"blue circles / orange squares; solid / dashed mean curves",
                "path_encoding":"Local small markers; Edge larger hollow markers and distinct line patterns"}
            buffers[name+".pdf"]=pdf.getvalue();buffers[name+".png"]=png.getvalue()
            plt.close(fig)

        fig,axes=plt.subplots(1,2,figsize=(7.16,3.18))
        fig.subplots_adjust(left=.087,right=.985,bottom=.17,top=.785,wspace=.40)
        a,b=axes
        for ax,panel in zip(axes,("(a)","(b)")):style(ax,panel)
        for repeat in range(1,6):
            c=data["groups"][(16,"CONCENTRATED")][repeat-1]
            d=data["groups"][(16,"DISPERSED")][repeat-1]
            a.plot([repeat,repeat],[float(c["R_min"]),float(d["R_min"])],
                   color="#A9A9A9",linewidth=.80,zorder=1)
        for p in PLACEMENTS:
            values=[float(r["R_min"]) for r in data["groups"][(16,p)]]
            artist,=a.plot(range(1,6),values,linestyle="None",color=COLOR[p],
                          marker=MARKER[p],markersize=5.1,markeredgewidth=.95,
                          markerfacecolor="white" if p=="DISPERSED" else COLOR[p],
                          zorder=4)
            require(list(artist.get_ydata())==values,"Actual paired R_min values changed")
        a.set(xlabel="Repeat",ylabel="Worst-stream TIR",
              xlim=(.6,5.4),ylim=(.85,1.025))
        a.set_xticks(range(1,6));a.set_yticks([.85,.90,.95,1.00])
        for p in PLACEMENTS:
            summaries=[stats([int(r["Edge_timely"])/int(r["Edge_assigned_count"])
                       for r in data["stream_groups"][(p,k)]]) for k in range(8)]
            shift=-.11 if p=="CONCENTRATED" else .11
            ranges(b,[k+shift for k in range(8)],summaries,p,label=LABEL[p],connected=False)
        b.set(xlabel="Stream ID",ylabel="Timely ratio of\nEdge-assigned frames",
              xlim=(-.45,7.45),ylim=(-.04,1.05))
        b.set_xticks(range(8));b.set_yticks([0,.25,.5,.75,1])
        b.grid(axis="y",color="#EBEBEB",linewidth=.45)
        fig.legend(handles=[
            Line2D([],[],color=COLOR[p],marker=MARKER[p],linestyle="None",
                   markerfacecolor="white" if p=="DISPERSED" else COLOR[p],
                   markeredgewidth=.95,markersize=5.0,label=LABEL[p])
            for p in PLACEMENTS],loc="upper center",bbox_to_anchor=(.5,.985),
            frameon=False,ncol=2,columnspacing=2.0,handletextpad=.55)
        finish(fig,"fig1_e16")

        fig,axes=plt.subplots(1,2,figsize=(7.16,3.54))
        fig.subplots_adjust(left=.087,right=.985,bottom=.16,top=.73,wspace=.40)
        a,b=axes
        for ax,panel in zip(axes,("(a)","(b)")):
            style(ax,panel);ax.set_xlim(-2.5,66.5);ax.set_xticks(RATES)
            ax.set_xlabel("Edge assigned rate [FPS]")
        for p in PLACEMENTS:
            ranges(a,RATES[1:],[data["summaries"][(e,p,"R_min")] for e in RATES[1:]],
                   p,label=LABEL[p])
        ranges(a,[0],[data["summaries"][(0,"LOCAL_ONLY","R_min")]],"LOCAL_ONLY",
               label="Local-only",connected=False)
        line,=a.plot(RATES,[1-e/240 for e in RATES],color="#858585",
                     linestyle=":",linewidth=1.20,zorder=2)
        require(list(line.get_ydata())==[1-e/240 for e in RATES],"Reference changed")
        a.set_ylabel("Worst-stream TIR");a.set_ylim(.48,1.03)
        a.set_yticks([.5,.6,.7,.8,.9,1])
        a.grid(axis="y",color="#EBEBEB",linewidth=.45)
        for path,metric in [("Local","Local_assigned_TIR"),("Edge","Edge_assigned_TIR")]:
            for p in PLACEMENTS:
                ranges(b,RATES[1:],[data["summaries"][(e,p,metric)] for e in RATES[1:]],
                       p,label=f"{path} / {LABEL[p]}",path=path)
        ranges(b,[0],[data["summaries"][(0,"LOCAL_ONLY","Local_assigned_TIR")]],
               "LOCAL_ONLY",connected=False)
        b.set_ylabel("Timely ratio of\nassigned frames");b.set_ylim(0,1.055)
        b.set_yticks([0,.25,.5,.75,1])
        b.grid(axis="y",color="#EBEBEB",linewidth=.45)
        common=Line2D([],[],color="#353535",marker="D",linestyle="None",
                      markersize=4.9,label="Local-only")
        ref=Line2D([],[],color="#858585",linestyle=":",linewidth=1.20,
                   label="Local-assignment fraction")
        a.legend(handles=[handle(p,LABEL[p]) for p in PLACEMENTS]+[common,ref],
                 loc="lower center",bbox_to_anchor=(.5,1.115),frameon=False,
                 ncol=2,handlelength=1.45,columnspacing=.8,handletextpad=.4,borderaxespad=0)
        b.legend(handles=[handle(p,f"{path} / {LABEL[p]}",path) for path in ("Local","Edge")
                          for p in PLACEMENTS],
                 loc="lower center",bbox_to_anchor=(.5,1.115),frameon=False,
                 ncol=2,handlelength=1.65,columnspacing=.7,handletextpad=.4,borderaxespad=0)
        finish(fig,"fig2_edge_rate_sweep")
        return buffers,drawing,artist_points

def main(script_text=None, removal_record=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign-dir",type=Path,
        default=Path(__file__).resolve().parent.parent/
                "results/timely_capacity_campaign/v2_2/block_b_edge_rate_sweep01")
    parser.add_argument("--output-dir",type=Path,default=Path(__file__).resolve().parent)
    parser.add_argument("--replace-generated",action="store_true",
        help="Replace only outputs with matching provenance from this generator")
    args=parser.parse_args()
    campaign=args.campaign_dir.resolve();output=args.output_dir.resolve()
    require(not output.is_symlink(),"Output directory must not be a symlink")
    existing=[name for name in OUTPUTS if (output/name).exists() or (output/name).is_symlink()]
    if existing:
        require(args.replace_generated,"Existing target files; no replacement requested")
        vp=output/"validation_section3.json"
        require(vp.is_file() and not vp.is_symlink(),"Missing replacement provenance")
        previous=json.loads(vp.read_text())
        require(previous.get("task")=="CAMPAIGN2_SECTION3_FIGURES02_PUBLISH" and
                previous.get("campaign")==CAMPAIGN,"Unknown target provenance")
        require(set(existing)==OUTPUTS,"Incomplete previous generated output set")
        for name in existing:
            require((output/name).is_file() and not (output/name).is_symlink(),
                    "Unexpected target type")
            if name not in ("validation_section3.json","plot_section3.py"):
                require(sha(output/name)==previous["output_SHA256"].get(name),
                        "Manually edited target; refusing overwrite: "+name)
    original={str(p.relative_to(campaign)):(p.stat().st_size,str(p.stat().st_mtime_ns))
              for p in campaign.rglob("*") if p.is_file()}
    data=collect(campaign);records=make_data(data)
    for r in records:
        if r["figure"]==1:
            if r["panel"]=="a":r["display_x"]=r["repeat"]
            elif r["panel"]=="b":
                r["display_x"]=r["stream_id"]+(-.11 if r["placement"]=="CONCENTRATED" else .11)
        elif r["panel"] in ("a","b"):r["display_x"]=r["Edge_FPS"]
    e16_ids=sorted(r["run_id"] for p in PLACEMENTS for r in data["groups"][(16,p)])
    require(sorted({r["run_id"] for r in records if r.get("run_id") and
                    r["figure"]==1})==e16_ids,"Figure 1 run coverage mismatch")
    require(sorted({r["run_id"] for r in records if r.get("run_id") and
                    r["figure"]==2 and r["Edge_FPS"]==16})==e16_ids,
            "Figures do not share the same five E16 pairs")
    buffers,drawing,artist_points=render(data,records)
    stream=io.StringIO(newline="")
    fields=["campaign","figure","panel","record_type","Edge_FPS","Local_FPS","placement",
            "repeat","stream_id","display_x","run_id","run_ids","metric","value","n",
            "mean","min","max","denominator","timely_count","expired_count","late_count",
            "logical_burst_position","source"]
    writer=csv.DictWriter(stream,fieldnames=fields,lineterminator="\n")
    writer.writeheader();writer.writerows(records)
    buffers["figure_data_section3.csv"]=stream.getvalue().encode()
    buffers["captions_section3.tex"]=captions(data).encode()
    if script_text is None:script_text=Path(__file__).read_text()
    buffers["plot_section3.py"]=script_text.encode()
    require(all(sha(campaign/n)==digest for n,digest in data["identities"].items()),
            "Scientific source content changed")
    current={str(p.relative_to(campaign)):(p.stat().st_size,str(p.stat().st_mtime_ns))
             for p in campaign.rglob("*") if p.is_file()}
    require(current==original,"Existing campaign changed while plotting")
    expected_peaks={8:1,16:1,24:1,32:2,40:2,48:2,56:2,64:4}
    discrepancies=[{"Edge_FPS":e,"reference":expected_peaks[e],
                    "CSV_max_m_E":data["pattern"][(e,"DISPERSED")]["max_m_E"]}
                   for e in RATES[1:]
                   if data["pattern"][(e,"DISPERSED")]["max_m_E"]!=expected_peaks[e]]
    checks={
        "campaign_only_no_pooling":"PASS","valid_runs_85_preserved":"PASS",
        "invalid_runs_zero":"PASS","nonzero_pairs_40":"PASS","E16_five_pairs":"PASS",
        "Fig1a_all_actual_paired_values":"PASS","Fig1b_denominator_all_assigned_120":"PASS",
        "Fig1b_pre_submission_expiration_in_denominator":"PASS",
        "fixed_logical_stream_position_mapping":"PASS","same_E16_pairs_in_both_figures":"PASS",
        "assignment_cell_manifest_consistency":"PASS","means_ranges_match_original_summaries":"PASS",
        "E0_not_duplicated":"PASS","E0_Edge_TIR_undefined":"PASS",
        "no_eta_threshold":"PASS","no_smoothing":"PASS","vector_PDF_and_600dpi_PNG":"PASS",
        "minimum_font_8_5pt":"PASS","no_clipping":"PASS","legends_outside_data":"PASS",
        "source_SHA_unchanged":"PASS","campaign_original_files_unchanged":"PASS",
        "no_new_validity_or_statistical_test":"PASS"}
    validation={
        "task":"CAMPAIGN2_SECTION3_FIGURES02_PUBLISH","campaign":CAMPAIGN,
        "generated_UTC":datetime.now(timezone.utc).isoformat(),
        "source_root":str(campaign),"output_root":str(output),
        "source_files":data["source_files"],"source_SHA256":data["identities"],
        "valid_run_count":85,"invalid_run_count":0,"nonzero_pair_count":40,
        "run_IDs_used":sorted(data["runs"]),"E16_pair_count":5,"E16_pairs":data["e16_pairs"],
        "E16_run_IDs_in_both_figures":e16_ids,
        "E16_Edge_denominator_per_run_per_stream":120,
        "E16_stream_run_count":80,"E16_logical_position_mapping":{str(k):k+1 for k in range(8)},
        "assignment_patterns":list(data["pattern"].values()),
        "max_m_E_by_Edge_rate_and_placement":[
            {"Edge_FPS":p["Edge_FPS"],"placement":p["placement"],"max_m_E":p["max_m_E"]}
            for _,p in sorted(data["pattern"].items())],
        "reference_peak_discrepancies":discrepancies,
        "all_figure_mean_min_max":[r for r in records if r["record_type"]=="SUMMARY"],
        "all_figure_run_values":[r for r in records if r["record_type"]=="RUN"],
        "plotted_artist_values":artist_points,
        "E0_displayed_values":[r for r in records
            if r["record_type"] in ("RUN","SUMMARY") and r["Edge_FPS"]==0],
        "E0_completion_scope_check":data["e0_completion"],
        "range_definition":"Observed min--max of five run observations; not CI or SE",
        "horizontal_offset_note":"Figure 1(b) only: +/-0.11 around stream ID to separate point ranges; all Figure 2 rates are exact",
        "arithmetic_reference":"1 - Edge_FPS/240; not a bound or prediction",
        "hardware_status_counts":dict(Counter(r["hardware_status"] for r in data["rows"])),
        "hardware_note":"PROTECTION_LIMITED preserved; VALID does not imply protection-free hardware",
        "analyze_py_SHA_record_in_closeout":data["analyzer_sha_record"],
        "ANALYZER_SHA_RECORD_NOT_FOUND":isinstance(data["analyzer_sha_record"],str),
        "raw_modified":False,"analysis01_modified":False,"paper_evidence01_modified":False,
        "new_experiment":False,"analyze_py_reexecuted":False,"validity_reclassified":False,
        "authorized_old_figure_removal":removal_record,
        "checks":checks,"rendering_checks":drawing,
        "visual_inspection":{"status":"PENDING_IMAGE_REVIEW"},
        "figure_data_record_counts":dict(Counter(r["record_type"] for r in records)),
        "output_SHA256":{n:hashlib.sha256(value).hexdigest() for n,value in buffers.items()},
        "self_SHA_note":"validation_section3.json omits its own recursive hash",
        "unresolved_items":(["ANALYZER_SHA_RECORD_NOT_FOUND; recorded, not a plotting blocker"]
                            if isinstance(data["analyzer_sha_record"],str) else [])}
    buffers["validation_section3.json"]=(json.dumps(validation,indent=2,
        sort_keys=True,ensure_ascii=False)+"\n").encode()
    require(set(buffers)==OUTPUTS,"Output allowlist mismatch")
    output.mkdir(parents=True,exist_ok=True)
    for name in sorted(buffers):
        with (output/name).open("wb" if name in existing else "xb") as f:f.write(buffers[name])
    require(all(sha(output/n)==digest for n,digest in validation["output_SHA256"].items()),
            "Output SHA mismatch")
    require(all(sha(campaign/n)==digest for n,digest in data["identities"].items()),
            "Source content changed after figure generation")
    for name,(size,mtime) in original.items():
        st=(campaign/name).stat()
        require((st.st_size,str(st.st_mtime_ns))==(size,mtime),"Original campaign file changed")
    print(json.dumps({"status":"GENERATED_DATA_VALIDATED","output":str(output),
        "files":sorted(OUTPUTS),"valid_runs":85,"nonzero_pairs":40,"E16_pairs":5,
        "max_m_E":validation["max_m_E_by_Edge_rate_and_placement"],
        "peak_discrepancies":discrepancies,"rendering":drawing,
        "analyzer_SHA_record":data["analyzer_sha_record"]},ensure_ascii=False))

if __name__=="__main__":
    main()
