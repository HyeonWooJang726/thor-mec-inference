"""CPU-only orchestration tests. Synthetic fixtures are not benchmark results."""

# Resolve shared experiment modules for direct script and repository-root imports.
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parents[1] / "common"))
from script_paths import configure as _configure, script_path
_configure()


import argparse
import ast
import copy
import csv
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import run_local_latency_breakdown_formal as runner
from local_latency_breakdown_metrics import frame_rows_ns, queue_metrics, write_csv, PER_FRAME_FIELDS


class OrchestrationTests(unittest.TestCase):
    def setUp(self):
        self.config = runner.read_json(runner.ORDER)

    def test_complete_observed_order_and_mapping(self):
        plan = runner.build_plan(self.config)
        expected = ([(k, 1) for k in range(1, 8)]
                    + [(k, 2) for k in (2, 3, 4, 5, 6, 7, 1)]
                    + [(k, 3) for k in (3, 4, 5, 6, 7, 1, 2)]
                    + [(k, 4) for k in (4, 5, 6, 7, 1, 2, 3)]
                    + [(k, 5) for k in (5, 6, 7, 1, 2, 3, 4)])
        self.assertEqual([(r["K"], int(r["run_id"][3:])) for r in plan], expected)
        self.assertEqual(sum(r["expected_frames"] for r in plan), 252000)
        for r in plan:
            self.assertEqual(r["videos"], runner.VIDEOS[:r["K"]])
        broken = copy.deepcopy(self.config)
        broken["runs"][0], broken["runs"][1] = broken["runs"][1], broken["runs"][0]
        with self.assertRaises(ValueError):
            runner.build_plan(broken)

    def test_unknown_cooldown_never_creates_outputs(self):
        config = copy.deepcopy(self.config)
        config["cooldown"]["status"] = "UNKNOWN"
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "uncreated"
            with patch.object(runner, "OUTPUT", output), patch.object(runner.subprocess, "run") as child:
                with self.assertRaisesRegex(ValueError, "cooldown UNKNOWN"):
                    runner.execute([], config, [])
                child.assert_not_called()
                self.assertFalse(output.exists())

    def test_explicit_none_does_not_claim_historical_reproduction(self):
        self.assertEqual(runner.cooldown_policy(self.config), [0] * 35)
        self.assertEqual(self.config["cooldown"]["historical_inter_run_cooldown"], "UNKNOWN")
        self.assertEqual(self.config["cooldown"]["protocol_statement"], runner.COOLDOWN_PROTOCOL)
        altered = copy.deepcopy(self.config)
        altered["cooldown"]["sleep_before_run_ns"][1] = 10_000_000_000
        with self.assertRaisesRegex(ValueError, "sleep is prohibited"):
            runner.cooldown_policy(altered)

    def test_collision_and_symlink_rejection_preserves_smoke(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "output"
            (output / "_smoke").mkdir(parents=True)
            sentinel = output / "_smoke/sentinel"
            sentinel.write_text("existing smoke")
            runner.check_empty_formal_root(output)
            for name in ("k1", "per_run_summary.csv", "experiment_metadata.json"):
                collision = output / name
                collision.write_text("existing")
                with self.assertRaisesRegex(ValueError, "collision"):
                    runner.check_empty_formal_root(output)
                self.assertEqual(collision.read_text(), "existing")
                collision.unlink()  # disposable synthetic fixture only
            link = Path(temporary) / "link"
            link.symlink_to(output, target_is_directory=True)
            with self.assertRaises(ValueError):
                runner.check_empty_formal_root(link)
            self.assertEqual(sentinel.read_text(), "existing smoke")

    def test_cli_only_without_gpu_imports(self):
        source = (runner.REPO / "scripts/local/profile_local_latency_breakdown.py").read_text()
        tree = ast.parse(source)
        function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "parse_args")
        scope = {"argparse": argparse, "Path": Path, "REPO": runner.REPO,
                 "SMOKE_ROOT": runner.OUTPUT / "_smoke", "__doc__": "CLI-only test"}
        exec(compile(ast.Module(body=[function], type_ignores=[]), "CLI-only", "exec"), scope)
        for k in range(1, 8):
            argv = ["profile", "--formal", "--k", str(k), "--frames-per-stream", "1800",
                    "--run-id", "run01", "--output-dir", str(runner.OUTPUT / f"k{k}/run01")]
            with patch.object(sys, "argv", argv):
                args = scope["parse_args"]()
                self.assertEqual((args.k, args.frames_per_stream, args.fps), (k, 1800, 30))
        with patch.object(sys, "argv", ["profile", "--smoke", "--k", "2", "--output-dir", str(runner.OUTPUT / "_smoke/new")]):
            self.assertEqual(scope["parse_args"]().frames_per_stream, 100)
        with patch.object(sys, "argv", ["profile", "--formal", "--k", "1", "--frames-per-stream", "100", "--output-dir", str(runner.OUTPUT / "k1/run01")]):
            with self.assertRaises(SystemExit):
                scope["parse_args"]()
        self.assertNotIn("tensorrt", sys.modules)
        self.assertNotIn("profile_local_latency_breakdown", sys.modules)

    def test_measurement_hash_and_dependencies(self):
        # Historical whole-file pins must still reject refactored import paths.
        with self.assertRaisesRegex(ValueError, "validated code version changed"):
            runner.audit_core(self.config)
        config = copy.deepcopy(self.config)
        pins = config["core_compatibility"]["current_source_sha256"]
        config["core_compatibility"]["current_source_sha256"] = {
            name: runner.digest(script_path(name)) for name in pins}
        # Only fixture source-file pins change; the measured block stays pinned.
        runner.audit_core(config)
        self.assertEqual(self.config["core_compatibility"]["measurement_block_sha256"],
                         "6049d16fdbe8d5001d2c4bd3498059e35fc8a49c50927f0bd2cd94b36d8fcc7d")

    def test_child_failure_stops_before_next_run(self):
        config = copy.deepcopy(self.config)
        check_root = runner.check_empty_formal_root
        pins = config["core_compatibility"]["current_source_sha256"]
        config["core_compatibility"]["current_source_sha256"] = {
            name: runner.digest(script_path(name)) for name in pins}
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "synthetic"
            plan = [{"K": 1, "run_id": "run01", "output_path": str(output / "k1/run01")},
                    {"K": 2, "run_id": "run01", "output_path": str(output / "k2/run01")}]
            good = {"host_process_visibility": True, "MAXN": True,
                    "DVFS_not_max_locked": True, "must_clear_before_formal": []}
            with patch.object(runner, "OUTPUT", output), patch.object(runner, "preflight", return_value=good), \
                    patch.object(runner, "check_empty_formal_root", side_effect=lambda: check_root(output)), \
                    patch.object(runner, "check_run_before"), patch.object(runner.subprocess, "run", return_value=subprocess.CompletedProcess([], 17)) as child:
                with self.assertRaisesRegex(ValueError, "child failed"):
                    runner.execute(plan, config, [])
                self.assertEqual(child.call_count, 1)
                self.assertTrue((output / "k1/orchestration_failure.json").is_file())
                self.assertFalse((output / "k2/run01_console.log").exists())
                self.assertFalse((output / "experiment_metadata.json").exists())

    def test_run_validator_and_corruption_rejection(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            records, events = [], []
            for i in range(1800):
                a = 1_000_000_000 + i * 1_000_000_000 // 30
                record = {"stream_id": 0, "frame_id": i, "a_ns": a, "b_ns": a + 1,
                          "r_ns": a + 2, "s_ns": a + 3, "c_ns": a + 4,
                          "actual_arrival_enqueue_ns": a, "inference_queue_depth_before_enqueue": 0}
                records.append(record)
                for kind, ns, depth in (("enqueue", a + 2, 1), ("start", a + 3, 0)):
                    events.append({"seq": len(events), "kind": kind, "ns": ns,
                                   "stream_id": 0, "frame_id": i, "depth": depth})
            q = queue_metrics(events, records, 1800, 1800)
            v = {"artifact_class": "FORMAL / SINGLE RUN", "validation": "PASS", "errors": [],
                 "K": 1, "expected": 1800, "counts": {f: 1800 for f in ("arrivals", "source_samples", "preprocessed", "completions", "per_frame_rows")},
                 "per_stream_counts": [{"stream_id": 0, **{f: 1800 for f in ("arrivals", "source_samples", "preprocessed", "completions")}}],
                 "timestamp_ordering_violations": 0, "decomposition_violations": 0,
                 "max_absolute_decomposition_error_ns": 0, "queue_accounting": "PASS", "queue": q}
            raw = {"t0_ns": 1_000_000_000, "records": records, "queue_events": events}
            runner.write_json(directory / "validation.json", v)
            runner.write_json(directory / "raw_ns.json", raw)
            runner.write_json(directory / "metadata.json", {"artifact_class": "FORMAL", "frames_per_stream": 1800,
                "fps": 30, "batch_size": 1, "concurrency": 1, "engine_sha256": runner.ENGINE_HASH,
                "active_stream_to_video_mapping": runner.VIDEOS[:1]})
            write_csv(directory / "per_frame.csv", PER_FRAME_FIELDS, frame_rows_ns(records, raw["t0_ns"]))
            run = {"K": 1, "run_id": "run01", "videos": runner.VIDEOS[:1], "expected_frames": 1800, "output_path": str(directory)}
            statistic, _ = runner.validate_run(run)
            self.assertEqual(statistic["e2e_mean_ns"], 4)
            path = directory / "validation.json"
            original = path.read_text()
            for field in v["counts"]:
                bad = json.loads(original)
                bad["counts"][field] -= 1
                path.write_text(json.dumps(bad))
                with self.assertRaises(ValueError):
                    runner.validate_run(run)
            path.write_text(original)
            records[0]["frame_id"] = 1
            (directory / "raw_ns.json").write_text(json.dumps(raw))
            with self.assertRaisesRegex(ValueError, "frame IDs"):
                runner.validate_run(run)
            records[0]["frame_id"] = 0
            events[0]["depth"] = -1
            (directory / "raw_ns.json").write_text(json.dumps(raw))
            with self.assertRaises(ValueError):
                runner.validate_run(run)


if __name__ == "__main__":
    unittest.main()
