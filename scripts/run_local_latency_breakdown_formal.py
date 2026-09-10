#!/usr/bin/env python3
"""Fixed formal orchestration. --dry-run and --preflight never import GPU code.

No default execution. --execute requires verified order, the explicit no-sleep
protocol, and a clean
host preflight. Each child invokes the existing profile once in a fresh process.
"""

import argparse
import csv
from datetime import datetime, timezone
from decimal import Decimal
from fractions import Fraction
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys

from local_latency_breakdown_metrics import (
    PER_FRAME_FIELDS, PER_RUN_FIELDS, MOTIVATION_FIELDS, QUEUE_FIELDS,
    aggregate_runs, frame_rows_ns, queue_metrics, run_summary, validate_timing, write_csv,
)

REPO = Path(__file__).resolve().parents[1]
OUTPUT = REPO / "results/local_latency_breakdown"
BASELINE = REPO / "results/local_realtime_baseline/capacity_sweep_5rep/b1_sync"
ORDER = REPO / "configs/local_latency_breakdown_formal_order.json"
ENGINE = REPO / "models/rtdetr_warehouse_v1.0.2.fp16.b1.canonical.engine"
ENGINE_HASH = "9d01cdb2838bb1b9db58c246e6111a5dccee63bb937b673fb48caf43e53bc5ff"
VIDEO_ROOT = Path("/home/ainet/datasets/PhysicalAI-SmartSpaces/MTMC_Tracking_2026/test/Warehouse_027/videos")
VIDEOS = [str(VIDEO_ROOT / f"W027_Camera_{i:04d}.mp4") for i in range(7)]
FIXED = {"K_list": list(range(1, 8)), "runs_per_K": 5, "fps": 30,
         "frames_per_stream": 1800, "B": 1, "C": 1,
         "total_runs": 35, "expected_total_frames": 252000}
COOLDOWN_PROTOCOL = (
    "Historical deliberate cooldown could not be established. "
    "The new latency-breakdown formal protocol therefore uses no "
    "additional deliberate inter-run sleep; the next run starts after "
    "successful completion, cleanup, and validation of the preceding run."
)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(path):
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def read_json(path):
    def reject(value):
        raise ValueError(f"non-finite JSON constant: {value}")
    return json.loads(path.read_text(), parse_constant=reject)


def write_json(path, data):
    def encode(value):
        if isinstance(value, Fraction):
            return {"numerator": value.numerator, "denominator": value.denominator}
        raise TypeError(type(value).__name__)
    with path.open("x") as handle:
        json.dump(data, handle, indent=2, default=encode, allow_nan=False)
        handle.write("\n")


def no_symlinks(path):
    require(not any(p.is_symlink() for p in (path, *path.parents)), f"symlink output prohibited: {path}")


def check_empty_formal_root(root=OUTPUT):
    no_symlinks(root)
    if root.exists():
        require(root.is_dir(), f"output root is not a directory: {root}")
        collisions = [p.name for p in root.iterdir() if p.name != "_smoke"]
        require(not collisions, f"formal output collision; no resume/overwrite: {collisions}")


def audit_mapping():
    evidence = []
    for k in FIXED["K_list"]:
        for n in range(1, 6):
            path = BASELINE / f"k{k}/run{n}/summary.json"
            data = read_json(path)
            expected = {"videos": VIDEOS[:k], "K": k, "fps": 30,
                        "frames_per_stream": 1800,
                        "engine": str(ENGINE.relative_to(REPO)), "B": 1, "C": 1}
            require(data["configuration"] == expected and data["validation"] == "pass",
                    f"baseline configuration/mapping mismatch: {path}")
            console = BASELINE / f"k{k}/run{n}_console.log"
            text = console.read_text()
            require(all(f"stream {i} video path: {v}" in text for i, v in enumerate(VIDEOS[:k])),
                    f"baseline console mapping mismatch: {console}")
            evidence.extend(str(p.relative_to(REPO)) for p in (path, console))
    require(ENGINE.is_file() and ENGINE.stat().st_size > 0, "engine missing/empty")
    require(digest(ENGINE) == ENGINE_HASH, "canonical engine hash mismatch")
    require(all(Path(v).is_file() for v in VIDEOS), "formal input video missing")
    return evidence


def build_plan(config):
    require(config["order_status"] == "VERIFIED", "formal run order UNKNOWN; refusing execution")
    entries = config["runs"]
    keys = [(r["K"], r["run_id"]) for r in entries]
    require(len(keys) == 35 and set(keys) == {(k, f"run{n:02d}") for k in range(1, 8) for n in range(1, 6)},
            "plan must contain exactly K=1..7 x run01..run05")
    require(entries == sorted(entries, key=lambda r: Decimal(r["first_scheduled_arrival_s"])),
            "plan order differs from baseline arrival chronology")
    require(entries == sorted(entries, key=lambda r: r["before_mtime_ns"]),
            "baseline wall-clock and raw arrival orders disagree")
    for previous, current in zip(entries, entries[1:]):
        require(Decimal(previous["last_completion_s"]) < Decimal(current["first_scheduled_arrival_s"]),
                "baseline order overlaps or is ambiguous")
        require(previous["exit_mtime_ns"] < current["before_mtime_ns"], "baseline artifact order ambiguous")
    plan = [{"K": r["K"], "run_id": r["run_id"], "videos": VIDEOS[:r["K"]],
             "expected_frames": r["K"] * 1800,
             "output_path": str(OUTPUT / f'k{r["K"]}' / r["run_id"])} for r in entries]
    require(sum(r["expected_frames"] for r in plan) == 252000, "plan frame total mismatch")
    return plan


def audit_order_sources(config):
    for entry in config["runs"]:
        path = REPO / entry["source_per_frame"]
        expected = BASELINE / f'k{entry["K"]}/run{int(entry["run_id"][3:])}/per_frame.csv'
        require(path == expected, "unexpected order evidence source")
        require(digest(path) == entry["source_sha256"], f"order evidence changed: {path}")
        with path.open(newline="") as handle:
            raw = list(csv.DictReader(handle))
        require(min(Decimal(r["scheduled_arrival_s"]) for r in raw) == Decimal(entry["first_scheduled_arrival_s"]),
                "baseline arrival evidence mismatch")
        require(max(Decimal(r["completion_s"]) for r in raw) == Decimal(entry["last_completion_s"]),
                "baseline completion evidence mismatch")
        prefix = expected.parent.parent / expected.parent.name
        require(Path(str(prefix) + "_oc3_before.txt").stat().st_mtime_ns == entry["before_mtime_ns"],
                "baseline before timestamp changed")
        require(Path(str(prefix) + "_exit_code.txt").stat().st_mtime_ns == entry["exit_mtime_ns"],
                "baseline exit timestamp changed")


def audit_core(config):
    compatibility = config["core_compatibility"]
    for name, expected in compatibility["current_source_sha256"].items():
        require(digest(REPO / "scripts" / name) == expected, f"validated code version changed: {name}")
    source = (REPO / "scripts/profile_local_latency_breakdown.py").read_text()
    block = source[source.index("    loop = GLib.MainLoop()"):source.index("    # Preserve raw ns evidence separately;")]
    require(hashlib.sha256(block.encode()).hexdigest() == compatibility["measurement_block_sha256"],
            "smoke-validated measurement block changed; smoke revalidation required")


def cooldown_policy(config):
    policy = config["cooldown"]
    require(policy["status"] == "EXPLICIT_CURRENT_PROTOCOL", "current protocol cooldown UNKNOWN or not explicitly specified")
    require(policy["historical_inter_run_cooldown"] == "UNKNOWN"
            and policy["current_formal_deliberate_inter_run_cooldown"] == "NONE",
            "protocol must distinguish historical UNKNOWN from current NONE")
    waits = policy["sleep_before_run_ns"]
    require(isinstance(waits, list) and len(waits) == 35
            and all(type(n) is int and n == 0 for n in waits), "additional deliberate sleep is prohibited")
    require(policy["protocol_statement"] == COOLDOWN_PROTOCOL, "cooldown protocol statement mismatch")
    require(isinstance(policy.get("evidence"), str) and policy["evidence"].strip(), "cooldown evidence required")
    return waits


def command_result(argv):
    if shutil.which(argv[0]) is None:
        return {"command": argv, "status": "unavailable", "output": "command not installed"}
    result = subprocess.run(argv, capture_output=True, text=True, timeout=15)
    return {"command": argv, "returncode": result.returncode,
            "output": (result.stdout + result.stderr).strip()}


def preflight():
    """Read-only host inventory. Never kills a process or adjusts power/clocks."""
    ps = command_result(["ps", "-eo", "pid,ppid,comm,pcpu,pmem,etime,args", "--sort=-pcpu"])
    init = Path("/proc/1/comm").read_text().strip()
    visible = init in ("systemd", "init")
    rows, blockers, review = [], [], []
    for line in ps.get("output", "").splitlines()[1:]:
        parts = line.split(None, 6)
        if len(parts) != 7:
            continue
        pid, ppid, comm, cpu, mem, elapsed, args = parts
        if int(pid) == os.getpid() or "run_local_latency_breakdown_formal.py" in args:
            continue
        row = dict(pid=int(pid), ppid=int(ppid), command=comm, cpu_pct=cpu,
                   memory_pct=mem, elapsed=elapsed, args=args)
        if any(token in args.lower() for token in ("profile_", "trtexec", "gst-launch", "ffmpeg", "update-manager", "jetsonpowergui")) or comm.startswith("codex"):
            blockers.append(row)
        elif "python" in comm or comm in ("tmux", "screen", "gnome-software", "update-notifier"):
            review.append(row)
        if int(ppid) != 2 and not args.startswith("["):
            rows.append(row)
    power = command_result(["nvpmodel", "-q"])
    clocks = {}
    cpu_root = Path("/sys/devices/system/cpu/cpufreq")
    for pattern in ("policy*/scaling_governor", "policy*/scaling_min_freq", "policy*/scaling_max_freq"):
        for p in cpu_root.glob(pattern):
            clocks[str(p)] = p.read_text().strip()
    for name in ("governor", "min_freq", "max_freq"):
        for p in Path("/sys/class/devfreq").glob("*/" + name):
            clocks[str(p)] = p.read_text().strip()
    checks = []
    for directory, low, high in [(cpu_root / "policy0", "scaling_min_freq", "scaling_max_freq"),
                                 (Path("/sys/class/devfreq/gpu-gpc-0"), "min_freq", "max_freq"),
                                 (Path("/sys/class/devfreq/bwmgr"), "min_freq", "max_freq")]:
        checks.append(str(directory / low) in clocks and str(directory / high) in clocks
                      and int(clocks[str(directory / low)]) < int(clocks[str(directory / high)]))
    return {"recorded_at": datetime.now(timezone.utc).isoformat(),
            "host_process_visibility": visible, "pid1": init, "power": power,
            "MAXN": "NV Power Mode: MAXN" in power.get("output", ""),
            "clock_sysfs": clocks, "DVFS_not_max_locked": all(checks),
            "jetson_clocks_invoked": False, "processes": rows,
            "must_clear_before_formal": blockers, "review_nonessential_processes": review,
            "system_load": command_result(["uptime"]),
            "tmux_sessions": command_result(["tmux", "list-sessions"]),
            "screen_sessions": command_result(["screen", "-ls"])}


def require_preflight(check):
    require(check["host_process_visibility"], "host process visibility unavailable (sandbox); run preflight on host")
    require(check["MAXN"] and check["DVFS_not_max_locked"], "MAXN / nonlocked clock preflight failed")
    require(not check["must_clear_before_formal"], "competing processes present; inspect --preflight; no process is killed automatically")


def check_run_before(run):
    require(FIXED["fps"] == 30 and FIXED["frames_per_stream"] == 1800
            and FIXED["B"] == FIXED["C"] == 1, "fixed configuration altered")
    k = run["K"]
    path = Path(run["output_path"])
    require(path == OUTPUT / f"k{k}" / run["run_id"], "unexpected output path")
    no_symlinks(path)
    require(not path.exists(), f"run output collision: {path}")
    require(run["videos"] == VIDEOS[:k] and run["expected_frames"] == k * 1800,
            "run configuration/mapping mismatch")
    audit_mapping()


def validate_run(run):
    """Revalidate raw events and exact CSV, not just a child's PASS string."""
    directory = Path(run["output_path"])
    v = read_json(directory / "validation.json")
    require(v["artifact_class"] == "FORMAL / SINGLE RUN" and v["validation"] == "PASS"
            and not v["errors"] and v["K"] == run["K"], "child validation failed")
    expected = run["expected_frames"]
    require(v["expected"] == expected, "expected frame count mismatch")
    for field in ("arrivals", "source_samples", "preprocessed", "completions", "per_frame_rows"):
        require(v["counts"][field] == expected, f"{field} mismatch")
    counts = v["per_stream_counts"]
    require([c["stream_id"] for c in counts] == list(range(run["K"])), "per-stream counts IDs mismatch")
    require(all(c[f] == 1800 for c in counts for f in ("arrivals", "source_samples", "preprocessed", "completions")),
            "per-stream count mismatch")
    raw = read_json(directory / "raw_ns.json")
    records, events = raw["records"], raw["queue_events"]
    require(len(records) == expected, "raw frame count mismatch")
    for stream in range(run["K"]):
        require(sorted(r["frame_id"] for r in records if r["stream_id"] == stream) == list(range(1800)),
                "frame IDs are not exactly 0..1799 per stream")
    timing = validate_timing(records)
    require(not any(timing.values()) and all(v[name] == 0 for name in timing), "raw timing validation failed")
    for r in records:
        require(r["a_ns"] == raw["t0_ns"] + r["frame_id"] * 1_000_000_000 // 30,
                "phase-aligned scheduled arrival mismatch")
        require(r["a_ns"] <= r["actual_arrival_enqueue_ns"] <= r["b_ns"], "arrival enqueue ordering mismatch")
    require(all(a["c_ns"] <= b["s_ns"] for a, b in zip(records, records[1:])), "single inference service overlap")
    require(v["queue_accounting"] == "PASS" and v["queue"]["waiting_after_drain"] == 0,
            "queue accounting/drain failed")
    q = queue_metrics(events, records, v["queue"]["N_enqueue"], v["queue"]["N_inference_start"])
    for key, value in q.items():
        saved = v["queue"][key]
        if isinstance(saved, dict):
            saved = Fraction(saved["numerator"], saved["denominator"])
        require(value == saved, f"queue metric mismatch: {key}")
    rows = frame_rows_ns(records, raw["t0_ns"])
    with (directory / "per_frame.csv").open(newline="") as handle:
        reader = csv.DictReader(handle)
        require(reader.fieldnames == PER_FRAME_FIELDS, "per-frame CSV schema mismatch")
        saved = list(reader)
    require(len(saved) == expected, "per-frame CSV row count mismatch")
    for row, original in zip(saved, rows):
        for field in PER_FRAME_FIELDS:
            value = float(row[field])
            require(math.isfinite(value) and value >= 0, "non-finite/negative CSV value")
            expected_value = float(Fraction(original[field[:-3] + "_ns"], 1_000_000)) if field.endswith("_ms") else original[field]
            require(value == expected_value, f"CSV/raw discrepancy: {field}")
    meta = read_json(directory / "metadata.json")
    require(meta["artifact_class"] == "FORMAL" and meta["frames_per_stream"] == 1800
            and meta["fps"] == 30 and meta["batch_size"] == meta["concurrency"] == 1
            and meta["engine_sha256"] == ENGINE_HASH
            and meta["active_stream_to_video_mapping"] == run["videos"], "run metadata mismatch")
    return run_summary(rows, run["K"], run["run_id"]), dict(q, K=run["K"], run_id=run["run_id"])


def execute(plan, config, mapping_evidence):
    waits = cooldown_policy(config)  # Validate the explicit protocol before output mkdir.
    check_empty_formal_root()
    initial = preflight()
    require_preflight(initial)
    # Existing _smoke is allowed; exclusive k-directory claims serialize runners.
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "k1").mkdir(exist_ok=False)
    for k in range(2, 8):
        (OUTPUT / f"k{k}").mkdir(exist_ok=False)
    runs, queues, completed = [], [], []
    try:
        write_json(OUTPUT / "k1/orchestration_preflight.json", initial)
        for index, run in enumerate(plan):
            audit_core(config)
            check_run_before(run)
            environment = preflight()
            require_preflight(environment)
            path = Path(run["output_path"])
            command = [sys.executable, "-B", str(REPO / "scripts/profile_local_latency_breakdown.py"),
                       "--formal", "--k", str(run["K"]), "--run-id", run["run_id"],
                       "--frames-per-stream", "1800", "--output-dir", str(path)]
            with (path.parent / f'{run["run_id"]}_console.log').open("x") as log:
                child = subprocess.run(command, cwd=REPO, stdout=log, stderr=subprocess.STDOUT)
            write_json(path.parent / f'{run["run_id"]}_execution.json',
                       {"command": command, "returncode": child.returncode,
                        "preflight": environment, "deliberate_sleep_ns": waits[index]})
            require(child.returncode == 0, f'child failed: K={run["K"]} {run["run_id"]}, exit={child.returncode}')
            statistic, q = validate_run(run)
            runs.append(statistic)
            queues.append(q)
            completed.append({"K": run["K"], "run_id": run["run_id"]})
        motivations, queue_rows = aggregate_runs(runs, queues, formal=True)
        write_csv(OUTPUT / "per_run_summary.csv", PER_RUN_FIELDS, runs)
        write_csv(OUTPUT / "motivation_summary.csv", MOTIVATION_FIELDS, motivations)
        write_csv(OUTPUT / "inference_queue_summary.csv", QUEUE_FIELDS, queue_rows)
        metadata = read_json(Path(plan[0]["output_path"]) / "metadata.json")
        metadata.update({"artifact_class": "FORMAL", "status": "COMPLETE", "configuration": FIXED,
                         "K_list": FIXED["K_list"], "run_count_per_K": 5,
                         "active_stream_to_video_mapping": VIDEOS,
                         "mapping_source_evidence": mapping_evidence,
                         "actual_run_order": completed, "run_order_audit": config,
                         "cooldown_policy": config["cooldown"], "initial_preflight": initial,
                         "historical_inter_run_cooldown": "UNKNOWN",
                         "current_formal_deliberate_inter_run_cooldown": "NONE",
                         "inter_run_cooldown_protocol": COOLDOWN_PROTOCOL,
                         "completed_at": datetime.now(timezone.utc).isoformat(),
                         "smoke_summary_aggregation": "not applicable to this formal result",
                         "orchestration_sha256": digest(Path(__file__))})
        write_json(OUTPUT / "experiment_metadata.json", metadata)
    except BaseException as error:
        write_json(OUTPUT / "k1/orchestration_failure.json", {"status": "FAILED", "error": repr(error),
                   "completed_runs": completed, "policy": "stop immediately; preserve all artifacts; no automatic retry/resume"})
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--preflight", action="store_true")
    mode.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    try:
        if args.preflight:
            print(json.dumps(preflight(), indent=2))
            return 0
        config = read_json(ORDER)
        plan = build_plan(config)
        check_empty_formal_root()
        audit_core(config)
        evidence = audit_mapping()
        audit_order_sources(config)
        if args.dry_run:
            for run in plan:
                print(json.dumps(run))
            return 0
        execute(plan, config, evidence)
        return 0
    except (ValueError, OSError, KeyError, subprocess.SubprocessError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
