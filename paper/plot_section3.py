#!/usr/bin/env python3
"""REV03 restyling of Campaign 2 Section III figures from an immutable figure CSV.

Usage: python3 -B paper/plot_section3.py --replace-generated

The production entry point reads only figure_data_section3.csv and existing
validation_section3.json. Legacy collect/make_data extraction functions below
are preserved verbatim for provenance; REV03 never calls them. No upstream
raw, analysis01, or paper_evidence01 data are used to recompute coordinates.
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

def captions_from_frozen():
    """Restyle captions without changing the recorded scientific quantities."""
    one = (
        r"Fixed-split comparison at L224/E16 in Campaign 2 "
        r"($C_L=3$, $C_E=1$, TensorRT batch $B=1$). Temporally concentrated "
        r"and temporally dispersed placement have identical aggregate "
        r"Local--Edge assignment counts and identical per-stream assignment counts. "
        r"(a) Five paired worst-stream TIR observations; gray segments connect "
        r"observations from the same repeat and are not trend lines. "
        r"(b) Stream-wise Edge-assigned timely ratios for both Concentrated "
        r"and Dispersed. Each stream and run has 120 Edge-assigned frames "
        r"in the denominator, including pre-submission expirations; expired "
        r"frames are not added again, and submitted-only counts are not used. "
        r"Point ranges in (b) show means and observed min--max across five runs, "
        r"not confidence intervals, with horizontal offsets of $\mp0.15$ around "
        r"stream IDs for visibility. Filled markers denote whole-stream or "
        r"Local-assigned ratios, whereas open markers denote Edge-assigned ratios. "
        r"Concentrated stream IDs 0--7 are fixed to logical burst positions 1--8; "
        r"these are not network submission or GPU execution ranks, and a causal "
        r"position effect is not isolated. TIR is bounded in $[0,1]$."
    )
    two = (
        r"Temporal placement across the Campaign 2 Edge-rate sweep. "
        r"(a) Worst-stream TIR. (b) Path-wise timely ratios of all Local- or "
        r"Edge-assigned frames, including expired frames. The common E0 "
        r"Local-only observation is shown once in each panel; its Edge-assigned "
        r"TIR is undefined. Markers and error bars show means and observed "
        r"min--max across five runs, not confidence intervals. Filled markers "
        r"denote whole-stream or Local-assigned ratios, whereas open markers "
        r"denote Edge-assigned ratios. Nonzero Concentrated and Dispersed points "
        r"are offset by $-0.6$ and $+0.6$ frames/s for visibility. The "
        r"Local-assignment fraction $1-\lambda_E/240$ is an arithmetic reference "
        r"only, not a bound, expected TIR, or guarantee. Connecting lines are "
        r"visual guides between measured operating points only, not interpolation "
        r"or estimates of unmeasured rates. Figure 1 and Figure 2 share the same "
        r"E16 five pairs. Concentrated has a maximum of 8 Edge assignments per "
        r"common scheduled input index at every nonzero Edge rate. Dispersed "
        r"has maximum 1 at E8--E24, 2 at E32--E56, and 4 at E64; E0 has zero. "
        r"These maxima are descriptive assignment properties, not GPU concurrency, "
        r"simultaneous transmission counts, server concurrency, or a causal "
        r"explanation of deadline failures."
    )
    return (r"\newcommand{\CampaignTwoFigOneCaption}{" + one + "}\n\n" +
            r"\newcommand{\CampaignTwoFigTwoCaption}{" + two + "}\n")


def frozen_csv_records(output, previous):
    """Read REV01 CSV. Never call collect/make_data or write a data CSV."""
    path = output / "figure_data_section3.csv"
    require(path.is_file() and not path.is_symlink(), "Missing regular figure CSV")
    require(sha(path) == previous["output_SHA256"]["figure_data_section3.csv"],
            "FIGURE_DATA_MODIFIED=YES")
    rows = read_csv(path)
    require(len(rows) == 432, "Frozen CSV row count differs from REV01")
    require(all(r["campaign"] == CAMPAIGN for r in rows), "Campaign pooling forbidden")
    numbers = {"figure", "Edge_FPS", "Local_FPS", "repeat", "stream_id", "n",
               "denominator", "timely_count", "expired_count", "late_count",
               "logical_burst_position"}
    reals = {"display_x", "value", "mean", "min", "max"}
    records = []
    for row in rows:
        r = dict(row)
        for key in numbers:
            if r[key] != "":
                r[key] = int(r[key])
        for key in reals:
            if r[key] != "":
                r[key] = float(r[key])
        records.append(r)
    runs = [r for r in records if r["record_type"] == "RUN"]
    summaries = [r for r in records if r["record_type"] == "SUMMARY"]
    require(len(runs) == 340 and len(summaries) == 66, "Frozen record coverage mismatch")
    # Compare coordinates and summaries with REV01, without reaggregating samples.
    for kind, key in [("RUN", "all_figure_run_values"),
                      ("SUMMARY", "all_figure_mean_min_max")]:
        current = [r for r in records if r["record_type"] == kind]
        original = previous[key]
        require(len(current) == len(original), "REV01 record count mismatch")
        for actual, expected in zip(current, original):
            for name, value in expected.items():
                require(actual[name] == value, "Frozen coordinate mismatch: " + name)
    ids = {r["run_id"] for r in runs}
    require(len(ids) == previous["valid_run_count"] == 85 and
            previous["invalid_run_count"] == 0, "REV01 run coverage mismatch")
    require(ids == set(previous["run_IDs_used"]), "REV01 run IDs mismatch")
    fig1a = [r for r in runs if (r["figure"], r["panel"]) == (1, "a")]
    require(len(fig1a) == 10 and
            {(r["repeat"], r["placement"]) for r in fig1a} ==
            {(rep, p) for rep in range(1, 6) for p in PLACEMENTS},
            "E16 five-pair coverage mismatch")
    require(previous["nonzero_pair_count"] == 40 and
            previous["E16_pair_count"] == 5, "REV01 pairing provenance mismatch")
    pairs = previous["E16_pairs"]
    require(len(pairs) == 5, "Missing E16 pairing provenance")
    for pair in pairs:
        rep = int(pair["round"])
        for p, column in [("CONCENTRATED", "concentrated_run_id"),
                          ("DISPERSED", "dispersed_run_id")]:
            require(next(r["run_id"] for r in fig1a if
                         r["repeat"] == rep and r["placement"] == p) == pair[column],
                    "Frozen E16 pairing differs")
    e16_fig2 = [r for r in runs if r["figure"] == 2 and r["Edge_FPS"] == 16]
    require({r["run_id"] for r in e16_fig2} == {r["run_id"] for r in fig1a},
            "Figures must share the same E16 five pairs")
    stream_runs = [r for r in runs if (r["figure"], r["panel"]) == (1, "b")]
    require(len(stream_runs) == 80 and
            all(r["denominator"] == 120 for r in stream_runs),
            "Fig1b denominator must include all 120 assignments")
    for r in stream_runs:
        require(r["timely_count"] + r["expired_count"] + r["late_count"] == 120,
                "Frozen stream terminal partition mismatch")
        require(close(r["value"], r["timely_count"] / 120),
                "Frozen assigned-frame ratio mismatch")
        if r["placement"] == "CONCENTRATED":
            require(r["logical_burst_position"] == r["stream_id"] + 1,
                    "Frozen logical position mapping mismatch")
    require(not any(r["Edge_FPS"] == 0 and r["metric"] == "Edge_assigned_TIR"
                    for r in records), "E0 Edge TIR is undefined")
    peaks = [dict(Edge_FPS=r["Edge_FPS"], placement=r["placement"],
                  max_m_E=int(r["value"])) for r in records
             if r["record_type"] == "ASSIGNMENT_MAX"]
    require(peaks == previous["max_m_E_by_Edge_rate_and_placement"],
            "Frozen assignment maxima differ from REV01")
    expected_dis = dict(zip(RATES[1:], [1, 1, 1, 2, 2, 2, 2, 4]))
    for p in peaks:
        expected = (0 if p["Edge_FPS"] == 0 else
                    8 if p["placement"] == "CONCENTRATED" else
                    expected_dis[p["Edge_FPS"]])
        require(p["max_m_E"] == expected, "Caption maximum differs from REV01")
    return records


def render_frozen(records):
    """Plot raw values or existing summaries directly; no numeric aggregation."""
    with tempfile.TemporaryDirectory(prefix="campaign2_rev03_matplotlib_") as cache:
        os.environ["MPLCONFIGDIR"] = cache
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib import font_manager
        from matplotlib.lines import Line2D
        from matplotlib.text import Text
        from matplotlib.transforms import Bbox
        import numpy as np
        from PIL import Image

        selected_font = "STIXGeneral"
        font_path = font_manager.findfont(
            font_manager.FontProperties(family=selected_font), fallback_to_default=False)
        plt.rcParams.update({
            "font.family": selected_font, "font.size": 8,
            "mathtext.fontset": "stix", "axes.labelsize": 8, "axes.titlesize": 8,
            "xtick.labelsize": 8, "ytick.labelsize": 8, "legend.fontsize": 8,
            "axes.linewidth": .65, "xtick.major.width": .65, "ytick.major.width": .65,
            "xtick.major.size": 2.5, "ytick.major.size": 2.5,
            "pdf.fonttype": 42, "ps.fonttype": 42,
            "figure.facecolor": "white", "axes.facecolor": "white",
            "savefig.facecolor": "white", "path.simplify": False,
            "lines.linewidth": 1, "lines.markersize": 4.5,
        })
        buffers, drawings, coordinates = {}, {}, []
        range_items = {}
        raw_items = {}

        def subset(figure, panel, kind, **filters):
            group = [r for r in records if r["figure"] == figure and
                     r["panel"] == panel and r["record_type"] == kind and
                     all(r[key] == value for key, value in filters.items())]
            return sorted(group, key=lambda r: (r["Edge_FPS"],
                          r["stream_id"] if r["stream_id"] != "" else -1,
                          r["repeat"] if r["repeat"] != "" else -1))

        def style(ax, panel):
            ax.spines["top"].set_visible(False)
            ax.spines["right"].set_visible(False)
            ax.grid(False)
            ax.set_axisbelow(True)
            ax.text(.5, -.22, panel, transform=ax.transAxes, ha="center", va="top",
                    fontsize=8, fontweight="normal", clip_on=False)

        def handle(p, label, edge=False, connected=True):
            color = COLOR.get(p, "#111111")
            marker = MARKER.get(p, "D")
            return Line2D([], [], color=color, marker=marker, markersize=4.5,
                          markerfacecolor="white" if edge else color,
                          markeredgewidth=.8, linewidth=1,
                          linestyle=("-" if p == "CONCENTRATED" else "--")
                                    if connected else "None", label=label)

        def point_range(ax, rows, x, p, figure, panel, edge=False, connected=False):
            require(rows, "Missing frozen point range")
            means = np.array([r["mean"] for r in rows])
            minima = np.array([r["min"] for r in rows])
            maxima = np.array([r["max"] for r in rows])
            require(all(r["n"] == 5 for r in rows), "Need five observed runs")
            color = COLOR.get(p, "#111111")
            marker = MARKER.get(p, "D")
            ax.errorbar(x, means, yerr=np.vstack([means-minima, maxima-means]),
                        fmt="none", ecolor=color, elinewidth=.8, capsize=2,
                        capthick=.8, zorder=2)
            if connected:
                ax.plot(x, means, color=color, linewidth=1,
                        linestyle="-" if p == "CONCENTRATED" else "--", zorder=2)
            artist, = ax.plot(x, means, color=color, marker=marker, markersize=4.5,
                             markeredgecolor=color, markeredgewidth=.8,
                             markerfacecolor="white" if edge else color,
                             linestyle="None", zorder=3)
            require(np.array_equal(artist.get_ydata(), means), "Mean coordinates changed")
            coordinates.append({"figure":figure, "panel":panel, "placement":p,
                "metric":rows[0]["metric"], "display_x":list(map(float, x)),
                "mean":means.tolist(), "min":minima.tolist(), "max":maxima.tolist(),
                "marker_fill":"open" if edge else "filled",
                "line_style":("-" if p=="CONCENTRATED" else "--") if connected else "None"})
            range_items.setdefault(ax, []).extend(zip(x, means, minima, maxima))
            return artist

        def finish(fig, name):
            fig.canvas.draw()
            renderer = fig.canvas.get_renderer()
            canvas_box = fig.bbox
            text_sizes = []
            for text in fig.findobj(Text):
                if not text.get_visible() or not text.get_text():
                    continue
                text_sizes.append(text.get_fontsize())
                box = text.get_window_extent(renderer)
                require(box.x0 >= canvas_box.x0-.5 and box.y0 >= canvas_box.y0-.5 and
                        box.x1 <= canvas_box.x1+.5 and box.y1 <= canvas_box.y1+.5,
                        "Text outside figure: " + text.get_text())
            require(set(text_sizes) == {8.0}, "All typography must be 8 pt")
            legend_records = []
            for ax in fig.axes:
                for getter in (ax.get_xticklabels, ax.get_yticklabels):
                    labels = [t for t in getter() if t.get_visible() and t.get_text()]
                    boxes = [t.get_window_extent(renderer) for t in labels]
                    require(not any(a.overlaps(b) for a,b in zip(boxes,boxes[1:])),
                            "Adjacent tick labels overlap")
                legend = ax.get_legend()
                if legend is None:
                    continue
                box = legend.get_window_extent(renderer)
                require(ax.bbox.contains(box.x0, box.y0) and
                        ax.bbox.contains(box.x1, box.y1), "Legend outside panel")
                for x, mean, low, high in range_items.get(ax, []):
                    p1 = ax.transData.transform((x, low))
                    p2 = ax.transData.transform((x, high))
                    stem = Bbox.from_extents(p1[0]-3, p1[1]-3, p2[0]+3, p2[1]+3)
                    require(not stem.overlaps(box),
                            f"Legend obscures observed range in {ax.get_ylabel()}: "
                            f"x={x}, min={low}, max={high}; legend={box.bounds}")
                for x,y in raw_items.get(ax,[]):
                    px,py = ax.transData.transform((x,y))
                    require(not box.contains(px,py), "Legend obscures raw point")
                legend_records.append({"labels":[t.get_text() for t in legend.get_texts()],
                    "inside_axes":True, "observed_points_and_ranges_unobscured":True})
            pdf, png = io.BytesIO(), io.BytesIO()
            # Include the full white canvas in tight bounding-box computation so
            # exported two-column dimensions remain exactly 7.16 x 2.8 inches.
            save_options = dict(bbox_inches="tight", pad_inches=0,
                                bbox_extra_artists=(fig.patch,))
            fig.savefig(pdf, format="pdf", metadata={
                "Title":"", "Author":"", "Creator":"plot_section3.py REV03",
                "CreationDate":None, "ModDate":None}, **save_options)
            fig.savefig(png, format="png", dpi=600, **save_options)
            im = Image.open(io.BytesIO(png.getvalue()))
            require(im.size == (4296,1680), "Exported size differs from 7.16 x 2.8 in")
            require(all(abs(v-600)<.1 for v in im.info["dpi"]), "PNG must be 600 dpi")
            require(b"/Subtype /Image" not in pdf.getvalue(), "PDF has raster image")
            drawings[name] = {
                "width_inches":7.16, "height_inches":2.8, "PNG_pixels":list(im.size),
                "PNG_dpi":list(im.info["dpi"]), "vector_PDF":True,
                "selected_font":selected_font, "font_path":font_path,
                "requested_font_size_pt":8, "observed_text_sizes_pt":sorted(set(text_sizes)),
                "text_inside_canvas":True, "tick_overlap":False,
                "legends":legend_records, "bbox_inches":"tight",
                "full_canvas_in_tight_bbox":True}
            buffers[name+".pdf"] = pdf.getvalue()
            buffers[name+".png"] = png.getvalue()
            plt.close(fig)

        fig, (a,b) = plt.subplots(1,2,figsize=(7.16,2.8))
        fig.subplots_adjust(left=.075, right=.987, bottom=.23, top=.95, wspace=.38)
        for ax,panel in [(a,"(a)"),(b,"(b)")]:
            style(ax,panel)
        c = subset(1,"a","RUN",placement="CONCENTRATED")
        d = subset(1,"a","RUN",placement="DISPERSED")
        for cr,dr in zip(c,d):
            require(cr["repeat"] == dr["repeat"], "Pair repeat mismatch")
            a.plot([cr["repeat"],dr["repeat"]], [cr["value"],dr["value"]],
                   color="#A5A5A5",linewidth=.65,zorder=1)
        for p in PLACEMENTS:
            rows = c if p=="CONCENTRATED" else d
            x,y = [r["repeat"] for r in rows],[r["value"] for r in rows]
            artist, = a.plot(x,y,linestyle="None",color=COLOR[p],marker=MARKER[p],
                            markerfacecolor=COLOR[p],markeredgewidth=.8,
                            markersize=4.5,zorder=3)
            require(list(artist.get_ydata()) == y, "Paired measured values changed")
            coordinates.append({"figure":1,"panel":"a","placement":p,"metric":"R_min",
                "display_x":x,"value":y,"run_ids":[r["run_id"] for r in rows],
                "marker_fill":"filled","line_style":"None"})
            raw_items.setdefault(a,[]).extend(zip(x,y))
        a.set(xlabel="Repeat",ylabel="Worst-stream TIR",xlim=(.6,5.4),ylim=(.90,1.01))
        a.set_xticks(range(1,6));a.set_yticks([.90,.95,1])
        from matplotlib.ticker import FormatStrFormatter
        a.yaxis.set_major_formatter(FormatStrFormatter("%.2f"))
        for p in PLACEMENTS:
            rows = subset(1,"b","SUMMARY",placement=p)
            shift = -.15 if p=="CONCENTRATED" else .15
            point_range(b,rows,[r["stream_id"]+shift for r in rows],p,1,"b",edge=True)
        b.set(xlabel="Stream ID",ylabel="Timely ratio of Edge-assigned frames",
              xlim=(-.5,7.5),ylim=(-.04,1.05))
        b.set_xticks(range(8));b.set_yticks([0,.25,.5,.75,1])
        b.legend(handles=[handle(p,LABEL[p],edge=True,connected=False) for p in PLACEMENTS],
                 loc="center left",bbox_to_anchor=(.01,.47),frameon=False,
                 handlelength=1,handletextpad=.45,borderaxespad=.2,labelspacing=.35)
        finish(fig,"fig1_e16")

        fig,(a,b) = plt.subplots(1,2,figsize=(7.16,2.8))
        fig.subplots_adjust(left=.075, right=.987, bottom=.23, top=.95, wspace=.38)
        for ax,panel in [(a,"(a)"),(b,"(b)")]:
            style(ax,panel)
            ax.set(xlabel="Edge assignment rate (frames/s)",xlim=(-3,67))
            ax.set_xticks(RATES)
        refs = subset(2,"a","REFERENCE")
        a.plot([r["Edge_FPS"] for r in refs],[r["value"] for r in refs],
               color="#555555",linestyle="--",linewidth=1,zorder=1)
        for p in PLACEMENTS:
            rows = subset(2,"a","SUMMARY",placement=p)
            shift = -.6 if p=="CONCENTRATED" else .6
            point_range(a,rows,[r["Edge_FPS"]+shift for r in rows],p,2,"a",
                        connected=(p=="DISPERSED"))
        point_range(a,subset(2,"a","SUMMARY",placement="LOCAL_ONLY"),[0],
                    "LOCAL_ONLY",2,"a")
        a.set(ylabel="Worst-stream TIR",ylim=(.49,1.04))
        a.set_yticks([.5,.6,.7,.8,.9,1])
        reference_handle = Line2D([],[],color="#555555",linestyle="--",linewidth=1,
            label=r"Local-assignment fraction $1-\lambda_E/240$")
        a.legend(handles=[handle("CONCENTRATED","Concentrated",connected=False),
            handle("DISPERSED","Dispersed"),handle("LOCAL_ONLY","Local-only",connected=False),
            reference_handle],loc="lower right",frameon=False,handlelength=1.4,
            handletextpad=.45,borderaxespad=.35,labelspacing=.35)
        for path,metric in [("Local","Local_assigned_TIR"),("Edge","Edge_assigned_TIR")]:
            for p in PLACEMENTS:
                rows = subset(2,"b","SUMMARY",placement=p,metric=metric)
                shift = -.6 if p=="CONCENTRATED" else .6
                point_range(b,rows,[r["Edge_FPS"]+shift for r in rows],p,2,"b",
                            edge=(path=="Edge"),connected=True)
        point_range(b,subset(2,"b","SUMMARY",placement="LOCAL_ONLY"),[0],
                    "LOCAL_ONLY",2,"b")
        b.set(ylabel="Timely ratio of assigned frames",ylim=(-.015,1.065))
        b.set_yticks([0,.25,.5,.75,1])
        b.legend(handles=[handle(p,f"{path} / {LABEL[p]}",edge=(path=="Edge"))
                          for path in ("Local","Edge") for p in PLACEMENTS]+[
                          handle("LOCAL_ONLY","Local-only",connected=False)],
                 loc="lower right",frameon=False,handlelength=1.5,
                 handletextpad=.45,borderaxespad=.15,labelspacing=.12)
        finish(fig,"fig2_edge_rate_sweep")
        return buffers,drawings,coordinates


def main():
    """REV03 entry point: frozen figure CSV only, no upstream data extraction."""
    import shutil
    import subprocess
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--replace-generated",action="store_true",
                        help="Replace validated rendered figures and captions only")
    args = parser.parse_args()
    require(args.replace_generated,"Explicit --replace-generated is required")
    output = Path(__file__).absolute().parent
    expected = Path("/home/ainet/research/thor-mec-rate-dvfs-gate/paper")
    require(output == expected and output.resolve() == expected and
            not output.is_symlink(), "FIGURE_DIRECTORY_MISMATCH")
    vp = output / "validation_section3.json"
    previous = json.loads(vp.read_text())
    require(previous["output_root"] == str(expected), "FIGURE_DIRECTORY_MISMATCH")
    require(previous["campaign"] == CAMPAIGN, "Wrong figure campaign")
    require(shutil.which("pdffonts"), "pdffonts is unavailable")
    records = frozen_csv_records(output,previous)
    before = sha(output/"figure_data_section3.csv")
    rendered = ["fig1_e16.pdf","fig1_e16.png",
                "fig2_edge_rate_sweep.pdf","fig2_edge_rate_sweep.png"]
    revisions = previous.setdefault("plot_revisions",[])
    current = next((r for r in revisions if r["plot_revision"]==3),None)
    pending = current is not None and current["status"] == "PRE_RENDER"
    reference_hashes = (previous["output_SHA256"] if current is None else
                        current.get("output_SHA256", previous["output_SHA256"]))
    for name in rendered+["captions_section3.tex"]:
        p = output/name
        if pending and name in rendered and not p.exists():
            continue
        require(p.is_file() and not p.is_symlink(), "Missing/unexpected output: "+name)
        require(sha(p)==reference_hashes[name],
                "Output differs from recorded provenance: "+name)
    if current is None:
        deleted = []
        for name in rendered:
            p=output/name;st=p.stat()
            deleted.append({"path":str(p.resolve()),"SHA256":sha(p),
                            "size":st.st_size,"mtime_ns":st.st_mtime_ns,
                            "mtime_UTC":datetime.fromtimestamp(st.st_mtime,
                                          timezone.utc).isoformat()})
        current = {
            "plot_revision":3,
            "task":"CAMPAIGN2_SECTION3_FIGURES03_RESTYLE_AND_PUBLISH",
            "revision_started_UTC":datetime.now(timezone.utc).isoformat(),
            "figure_data_sha_before":before,
            "deleted_previous_outputs":deleted,
            "REV01_validation_sha_before":sha(vp),
            "REV01_provenance_preserved":True,
            "numeric_source_of_truth":str(output/"figure_data_section3.csv"),
            "upstream_data_read_for_coordinates":False,
            "data_extraction_functions_used":False,
            "status":"PRE_RENDER"}
        revisions.append(current)
    else:
        require(current["figure_data_sha_before"]==before,"FIGURE_DATA_MODIFIED=YES")
    current["status"]="PRE_RENDER"
    # Record original hashes/metadata before removing exactly the four render files.
    previous["plot_revision"]=3
    vp.write_text(json.dumps(previous,indent=2,sort_keys=True,ensure_ascii=False)+"\n")
    for name in rendered:
        if (output/name).exists():
            (output/name).unlink()
    buffers,drawings,coordinates = render_frozen(records)
    buffers["captions_section3.tex"]=captions_from_frozen().encode()
    for name,value in buffers.items():
        (output/name).write_bytes(value)
    font_reports = {}
    for name in ["fig1_e16","fig2_edge_rate_sweep"]:
        command = ["pdffonts",str(output/(name+".pdf"))]
        result = subprocess.run(command,capture_output=True,text=True,check=True)
        lines=result.stdout.splitlines()
        fonts=lines[2:]
        require(fonts and all("Type 3" not in line for line in fonts),
                "PDF_FONT_VALIDATION=FAIL")
        font_reports[name]={"command":command,"stdout":result.stdout,
                           "stderr":result.stderr,"embedded_font_rows":fonts,
                           "Type_3_present":False,"status":"PASS"}
    after = sha(output/"figure_data_section3.csv")
    require(before==after,"FIGURE_DATA_MODIFIED=YES")
    current.update({
        "status":"RENDERED_PENDING_VISUAL_INSPECTION",
        "generated_UTC":datetime.now(timezone.utc).isoformat(),
        "figure_data_sha_after":after,"figure_data_unchanged":True,
        "rendering_checks":drawings,
        "font":{"selected_font":"STIXGeneral","requested_size_pt":8,
                "pdf_fonttype":42,"ps_fonttype":42,
                "embedded_fonts":font_reports,"Type_3_present":False},
        "pdffonts_result":font_reports,"PDF_FONT_VALIDATION":"PASS",
        "style":{"main_line_width_pt":1,"marker_size_pt":4.5,
                 "errorbar_width_pt":.8,"cap_size_pt":2,
                 "paired_gray_line_width_pt":.65,
                 "panel_label_location":"below each x-axis label, centered",
                 "legend_locations":{"fig1a":"NONE","fig1b":"inside center left",
                     "fig2a":"inside lower right","fig2b":"inside lower right"},
                 "Fig1b_x_offsets":{"CONCENTRATED":-.15,"DISPERSED":.15},
                 "Fig2_nonzero_x_offsets":{"CONCENTRATED":-.6,"DISPERSED":.6},
                 "reference_zorder":1,"errorbar_zorder":2,"marker_zorder":3,
                 "Fig2a_Concentrated_connecting_line":False,
                 "Fig2a_Dispersed_connecting_line":"dashed visual guide",
                 "marker_fill":"filled whole-stream/Local; open Edge"},
        "data_validation":{"valid_runs":previous["valid_run_count"],
            "invalid_runs":previous["invalid_run_count"],
            "nonzero_pairs":previous["nonzero_pair_count"],
            "E16_five_pair_IDs":previous["E16_pairs"],
            "Fig1b_denominator":120,"Fig1b_stream_run_count":80,
            "E0_values":previous["E0_displayed_values"],
            "all_figure_mean_min_max":previous["all_figure_mean_min_max"],
            "assignment_max_m_E":previous["max_m_E_by_Edge_rate_and_placement"],
            "figure_data_rows":len(records),
            "original_values_and_summary_coordinates_match_REV01":True,
            "CSV_display_x_preserved":
                "REV01 CSV display_x unchanged; REV03 display offsets recorded separately"},
        "plotted_artist_values":coordinates,
        "visual_inspection":{"status":"PENDING_IMAGE_REVIEW"},
        "ANALYZER_SHA_RECORD_NOT_FOUND":previous["ANALYZER_SHA_RECORD_NOT_FOUND"],
        "output_SHA256":{name:sha(output/name) for name in rendered+
                        ["captions_section3.tex","plot_section3.py"]}})
    vp.write_text(json.dumps(previous,indent=2,sort_keys=True,ensure_ascii=False)+"\n")
    print(json.dumps({"status":current["status"],"output":str(output),
        "figure_data_sha_before":before,"figure_data_sha_after":after,
        "PDF_FONT_VALIDATION":"PASS","rendering":drawings},ensure_ascii=False))


if __name__ == "__main__":
    main()
