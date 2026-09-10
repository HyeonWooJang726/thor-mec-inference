#!/usr/bin/env python3
"""Instrument the canonical local workload; formal runs use the dedicated runner."""

import argparse
import csv
import json
import math
import queue
import hashlib
import subprocess
from datetime import datetime, timezone
from fractions import Fraction
import sys
import threading
import time
from pathlib import Path

import cv2
import gi
import numpy as np

gi.require_version("Gst", "1.0")
gi.require_version("GstVideo", "1.0")
from gi.repository import GLib, Gst, GstVideo  # noqa: E402

from profile_local_e2e import PIPELINE_TEXT, TensorRTRunner, build_pipeline  # noqa: E402
from rtdetr_preprocess import preprocess_bgr  # noqa: E402


from local_latency_breakdown_metrics import (
    QueueAccounting, PER_FRAME_FIELDS, PER_RUN_FIELDS, MOTIVATION_FIELDS, QUEUE_FIELDS,
    frame_rows_ns, validate_timing, queue_metrics, run_summary, aggregate_runs, write_csv,
)

REPO = Path(__file__).resolve().parents[1]
BASELINE = REPO / "results/local_realtime_baseline/capacity_sweep_5rep/b1_sync"
SMOKE_ROOT = REPO / "results/local_latency_breakdown/_smoke"


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--smoke", action="store_true")
    mode.add_argument("--formal", action="store_true")
    parser.add_argument("--k", type=int, required=True, choices=range(1, 8))
    parser.add_argument("--frames-per-stream", type=int)
    parser.add_argument("--run-id")
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    args.fps = 30
    output = Path(args.output_dir).resolve()
    if args.smoke:
        if args.k not in (1, 2, 6) or args.frames_per_stream not in (None, 100):
            parser.error("smoke requires K=1/2/6 and 100 frames per stream")
        if args.run_id not in (None, "smoke01"):
            parser.error("smoke run ID must be smoke01")
        args.frames_per_stream, args.run_id = 100, "smoke01"
        if not output.is_relative_to(SMOKE_ROOT.resolve()) or output == SMOKE_ROOT.resolve():
            parser.error("smoke output must be a new directory strictly below _smoke/")
    else:
        if args.frames_per_stream != 1800 or args.run_id not in {f"run{i:02d}" for i in range(1, 6)}:
            parser.error("formal requires 1800 frames and run01..run05")
        expected = SMOKE_ROOT.parent / f"k{args.k}" / args.run_id
        if output != expected or any(p.is_symlink() for p in (expected, *expected.parents)):
            parser.error("formal output must be the exact nonsymlink kK/runNN path")
    args.output_dir = str(output)
    return args


def audit_inputs():
    reference = json.loads((BASELINE / "k7/run1/summary.json").read_text())["configuration"]
    videos, evidence = reference["videos"], []
    if len(videos) != 7 or len(set(videos)) != 7:
        raise ValueError("formal mapping must contain seven distinct inputs")
    for k in range(1, 8):
        for run in range(1, 6):
            path = BASELINE / f"k{k}/run{run}/summary.json"
            summary = json.loads(path.read_text())
            config = summary["configuration"]
            expected = dict(reference, videos=videos[:k], K=k)
            if config != expected or summary["validation"] != "pass":
                raise ValueError(f"formal configuration inconsistency: {path}")
            console = BASELINE / f"k{k}/run{run}_console.log"
            text = console.read_text()
            if not all(f"stream {i} video path: {v}" in text for i, v in enumerate(videos[:k])):
                raise ValueError(f"formal console mapping inconsistency: {console}")
            evidence.extend(str(p.relative_to(REPO)) for p in (path, console))
    if (reference["fps"], reference["frames_per_stream"], reference["B"], reference["C"]) != (30, 1800, 1, 1):
        raise ValueError("unexpected formal workload")
    video_metadata = []
    for i, video in enumerate(videos):
        probe = json.loads(subprocess.check_output([
            "ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
            "stream=codec_name,width,height,r_frame_rate,avg_frame_rate,nb_frames,duration:format=duration",
            "-of", "json", video], text=True))
        stream = probe["streams"][0]
        if (stream["codec_name"], stream["width"], stream["height"],
                stream["avg_frame_rate"], stream["nb_frames"]) != ("h264", 1920, 1080, "30/1", "1800"):
            raise ValueError(f"unexpected formal input: {video}")
        video_metadata.append({"stream_id": i, "path": video, "exists": Path(video).is_file(),
                               "ffprobe": probe})
    return reference, evidence, video_metadata


def environment_metadata():
    power = subprocess.check_output(["nvpmodel", "-q"], text=True).strip()
    if "NV Power Mode: MAXN" not in power:
        raise ValueError(f"MAXN required, observed: {power}")
    paths = list(Path("/sys/devices/system/cpu/cpufreq").glob("policy*/scaling_governor"))
    paths += list(Path("/sys/devices/system/cpu/cpufreq").glob("policy*/scaling_*_freq"))
    for name in ("governor", "min_freq", "max_freq"):
        paths += list(Path("/sys/class/devfreq").glob("*/" + name))
    clocks = {str(p): p.read_text().strip() for p in paths if p.is_file()}
    return {"Thor_hardware": Path("/proc/device-tree/model").read_text().strip("\0"),
            "power_mode": power,
            "jetson_clocks_state": "not enabled by this task; read-only sysfs DVFS evidence attached; --show requires root and was not escalated",
            "clock_sysfs": clocks}


def experiment_metadata(args, reference, evidence, video_metadata, environment, *, formal=False):
    """Metadata builder supports a later formal caller, without writing artifacts."""
    return {
        "artifact_class": "FORMAL" if formal else "SMOKE / NON-FORMAL",
        "purpose": "latency breakdown" if formal else "instrumentation correctness only; no performance interpretation",
        "git_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO, text=True).strip(),
        "experiment_date": datetime.now(timezone.utc).isoformat(),
        **environment,
        "model": "RT-DETR Warehouse v1.0.2", "engine_path": args.engine,
        "engine_sha256": hashlib.sha256(Path(args.engine).read_bytes()).hexdigest(),
        "batch_size": 1, "concurrency": 1, "fps": 30,
        "frames_per_stream": args.frames_per_stream,
        "formal_frames_per_stream": reference["frames_per_stream"],
        "formal_duration_seconds": 60,
        "candidate_deadline_ms": 1000.0 / 30.0,
        "candidate_deadline_exact_definition": "1/30 second",
        "integer_ns_miss_comparison_rule": "e2e_ns * 30 > 1_000_000_000",
        "candidate_deadline_purpose": "comparison with prior Local formal; not final application SLA",
        "K_list": list(range(1, 8)) if formal else [args.k],
        "planned_formal_K_list": list(range(1, 8)),
        "run_count_per_K": 5 if formal else 1,
        "actual_formal_stream_to_video_mapping": reference["videos"],
        "active_stream_to_video_mapping": reference["videos"][:args.k],
        "mapping_source_evidence": evidence, "videos": video_metadata,
        "GStreamer_pipeline": PIPELINE_TEXT,
        "appsink": {"sync": False, "emit_signals": False, "max_buffers": 1, "drop": False},
        "preprocessing_identity": "rtdetr_preprocess.preprocess_bgr: INTER_LINEAR 640x360; top-left zero pad 640x640; BGR->RGB; FP32 /255; contiguous NCHW 1x3x640x640; cv2 threads=1",
        "warm_up_behavior": "none in canonical profile_local_realtime.py; no warm-up added, no samples excluded",
        "source_preparation": "TensorRTRunner constructed first; pipelines built in stream order, then all set PLAYING; no seek, pre-pull, or wait for preroll",
        "worker_startup_order": "pipeline PLAYING in stream order -> all front-end workers -> one inference worker -> t0=perf_counter_ns()+100000000 -> arrival scheduler -> GLib loop",
        "arrival_definition": "phase-aligned logical scheduled job arrivals at 30 FPS per stream; not camera capture or decoder timestamps",
        "arrival_integer_representation": "a_ns=t0_ns+(frame_id*1000000000)//30; floor each absolute rational offset (<1ns quantization), no accumulated rounded period; wait API alone converts remaining ns to seconds",
        "queue_capacity_semantics": "unbounded queue.Queue(maxsize=0) for each arrival queue and one FIFO ready queue; no drops, no batching; appsink max-buffers=1/drop=false unchanged",
        "EOS_behavior": "bounded jobs; EOS noted; missing pull-sample fails; all completions required; pipeline NULL and thread join after drain; full-source EOS not required for bounded smoke",
        "clock_source": vars(time.get_clock_info("perf_counter")),
        "integer_ns_timing_method": "same underlying performance-counter clock semantics, integer-nanosecond API used for measurement",
        "timing_API": "time.perf_counter_ns() (canonical time.perf_counter())",
        "a_j": "30 FPS logical scheduled job-arrival time",
        "b_j": "front-end worker after arrival get, immediately before pull-sample",
        "r_j": "state_lock-protected ready-queue enqueue completion boundary: sample perf_counter_ns immediately after unbounded put returns, before enqueue counter/event publication",
        "s_j": "after ready dequeue, under state_lock at end of start accounting, immediately before lock release and TensorRTRunner.infer call",
        "c_j": "first perf_counter_ns after infer returns, before output-name validation; host outputs available",
        "front_end_ms_boundary": "pull-sample wait/access; caps validation; buffer map; ndarray view; preprocess_bgr; unmap; ready job preparation; accounting lock acquisition; unbounded queue insertion through r; async decode service is not isolated",
        "inference_ms_boundary": "TensorRT inference-worker service time: input validation, synchronous input H2D, execute_async_v3(stream=0), cudaDeviceSynchronize, synchronous output D2H, Python return; includes tiny s lock-release/call overhead; not pure GPU kernel latency",
        "queue_depth_definition": "N_enqueue-N_inference_start immediately before this enqueue; excludes self and service, includes dequeued job until s",
        "queue_event_accounting_method": "same state_lock for put/r/N_enqueue/event and N_inference_start/s/event; get outside lock; infer outside lock; Q_inf(t)=#{j:r_j<=t<s_j}; no Queue.qsize",
        "queue_event_sequence_rule": "zero-based strictly increasing sequence assigned in state_lock; replay sequence without timestamp sorting, including equal timestamps",
        "queue_time_weighted_integration_interval": "first ready enqueue r through last ready enqueue r; integer frame-ns area / integer ns interval; T=0 rejected",
        "queue_peak_definition": "maximum event-state waiting depth over entire run through drain",
        "queue_at_last_enqueue_definition": "waiting depth immediately after final ready enqueue event in lock sequence",
        "K_level_summary_aggregation": "each metric is arithmetic mean of exactly five run-level statistics (including run percentiles and miss percentages); no pooled frames; queue metrics also mean of five independent run metrics",
        "smoke_summary_aggregation": "one actual run per K; run_count=1; never represented as five repeats",
        "statistics_arithmetic": "integer ns differences/validation/integration; exact rational means and linear percentile interpolation in ns; ms conversion only at CSV serialization",
        "source_sha256": {n: hashlib.sha256((REPO / "scripts" / n).read_bytes()).hexdigest()
                          for n in ("profile_local_realtime.py", "profile_local_e2e.py", "rtdetr_preprocess.py", "profile_local_latency_breakdown.py", "local_latency_breakdown_metrics.py")},
    }


def write_json(path, data):
    def encode(value):
        if isinstance(value, Fraction):
            return {"numerator": value.numerator, "denominator": value.denominator}
        raise TypeError(type(value).__name__)
    with path.open("x") as handle:
        json.dump(data, handle, indent=2, default=encode, allow_nan=False)
        handle.write("\n")


def main():
    args = parse_args()
    reference, evidence, video_metadata = audit_inputs()
    videos = reference["videos"][:args.k]
    args.engine = str(REPO / reference["engine"])
    environment = environment_metadata()
    streams = len(videos)
    frames_per_stream = args.frames_per_stream
    total_expected = streams * frames_per_stream
    output_dir = Path(args.output_dir)

    engine_path = Path(args.engine)
    if not engine_path.is_file() or engine_path.stat().st_size == 0:
        print(f"ERROR: invalid engine file: {engine_path}", file=sys.stderr)
        return 1
    for video in videos:
        if not Path(video).is_file():
            print(f"ERROR: video not found: {video}", file=sys.stderr)
            return 1
    if output_dir.exists():
        print(f"ERROR: output directory already exists: {output_dir}", file=sys.stderr)
        return 1
    try:
        output_dir.mkdir(parents=True)
    except Exception as error:
        print(f"ERROR: failed to create output directory: {error}", file=sys.stderr)
        return 1

    # CLI/output adaptation only: the measurement block below is unchanged.
    def artifact(name):
        return output_dir / (name if args.smoke else name.removeprefix("smoke_"))

    write_json(artifact("smoke_metadata.json"), experiment_metadata(
        args, reference, evidence, video_metadata, environment, formal=not args.smoke))
    Gst.init(None)
    cv2.setNumThreads(1)
    pipelines = []
    sinks = []
    inference = None
    try:
        inference = TensorRTRunner(args.engine)
        for video in videos:
            pipeline, _converter, sink = build_pipeline(video)
            pipelines.append(pipeline)
            sinks.append(sink)
    except Exception as error:
        for pipeline in pipelines:
            try:
                pipeline.set_state(Gst.State.NULL)
            except Exception:
                pass
        if inference is not None:
            try:
                inference.close()
            except Exception:
                pass
        write_json(artifact("smoke_failure.json"), {"stage": "setup", "error": str(error)})
        print(f"ERROR setup: {error}", file=sys.stderr)
        return 1

    loop = GLib.MainLoop()
    arrival_queues = [queue.Queue() for _ in range(streams)]
    ready_queue = queue.Queue()
    stop_event = threading.Event()
    state_lock = threading.Lock()
    errors = []
    arrivals = [0] * streams
    source_samples_pulled = [0] * streams
    preprocessed = [0] * streams
    completions = [0] * streams
    eos = [False] * streams
    records = []
    t0_holder = []
    accounting = QueueAccounting()

    def fail(message):
        with state_lock:
            errors.append(message)
        stop_event.set()
        GLib.idle_add(loop.quit)

    def arrival_scheduler():
        try:
            t0 = t0_holder[0]
            for frame_id in range(frames_per_stream):
                target = t0 + (frame_id * 1_000_000_000) // 30
                remaining = target - time.perf_counter_ns()
                if remaining > 0 and stop_event.wait(remaining / 1_000_000_000):
                    return
                if stop_event.is_set():
                    return
                for stream_id in range(streams):
                    with state_lock:
                        actual = time.perf_counter_ns()
                        job = {
                            "stream_id": stream_id,
                            "frame_id": frame_id,
                            "a_ns": target,
                            "actual_arrival_enqueue_ns": actual,
                        }
                        arrival_queues[stream_id].put(job)
                        arrivals[stream_id] += 1
        except Exception as error:
            fail(f"arrival scheduler: {error}")

    def front_end_worker(stream_id):
        sink = sinks[stream_id]
        try:
            for _ in range(frames_per_stream):
                while not stop_event.is_set():
                    try:
                        job = arrival_queues[stream_id].get(timeout=0.1)
                        break
                    except queue.Empty:
                        continue
                else:
                    return
                job["b_ns"] = time.perf_counter_ns()
                sample = sink.emit("pull-sample")
                if sample is None:
                    with state_lock:
                        source_eos = eos[stream_id]
                    if source_eos:
                        raise RuntimeError(
                            f"stream {stream_id}: unexpected early EOS after "
                            f"{source_samples_pulled[stream_id]} source samples"
                        )
                    raise RuntimeError(
                        f"stream {stream_id}: appsink returned no sample before workload completion"
                    )
                info = GstVideo.VideoInfo.new_from_caps(sample.get_caps())
                if info.width != 1920 or info.height != 1080 or info.finfo.name != "BGR":
                    raise RuntimeError(
                        f"stream {stream_id}: unexpected frame caps: "
                        f"{info.width}x{info.height} {info.finfo.name}"
                    )
                buffer = sample.get_buffer()
                ok, mapping = buffer.map(Gst.MapFlags.READ)
                if not ok:
                    raise RuntimeError(f"stream {stream_id}: GstBuffer map failed")
                source_samples_pulled[stream_id] += 1
                try:
                    frame = np.ndarray(
                        (1080, 1920, 3),
                        dtype=np.uint8,
                        buffer=mapping.data,
                        strides=(info.stride[0], 3, 1),
                    )
                    tensor = preprocess_bgr(frame)
                finally:
                    buffer.unmap(mapping)
                preprocessed[stream_id] += 1
                job["tensor"] = tensor
                with state_lock:
                    accounting.enqueue(ready_queue, job, time.perf_counter_ns)
        except Exception as error:
            fail(f"stream {stream_id} front end: {error}")

    def inference_worker():
        try:
            while sum(completions) < total_expected and not stop_event.is_set():
                try:
                    job = ready_queue.get(timeout=0.1)
                except queue.Empty:
                    continue
                with state_lock:
                    accounting.start(job, time.perf_counter_ns)
                outputs = inference.infer(job["tensor"])
                job["c_ns"] = time.perf_counter_ns()
                if set(outputs) != {"pred_logits", "pred_boxes"}:
                    raise RuntimeError(f"unexpected TensorRT outputs: {list(outputs)}")
                del job["tensor"]
                stream_id = job["stream_id"]
                with state_lock:
                    completions[stream_id] += 1
                    records.append(job)
                    complete = sum(completions) == total_expected
                if complete:
                    GLib.idle_add(loop.quit)
        except Exception as error:
            fail(f"inference worker: {error}")

    def on_message(_bus, message, stream_id):
        if message.type == Gst.MessageType.ERROR:
            error, debug = message.parse_error()
            fail(f"stream {stream_id} GStreamer: {error}; debug={debug or 'unavailable'}")
        elif message.type == Gst.MessageType.EOS:
            with state_lock:
                eos[stream_id] = True

    for stream_id, pipeline in enumerate(pipelines):
        bus = pipeline.get_bus()
        bus.add_signal_watch()
        bus.connect("message", on_message, stream_id)

    front_threads = [
        threading.Thread(target=front_end_worker, args=(stream_id,), name=f"realtime-front-{stream_id}")
        for stream_id in range(streams)
    ]
    inference_thread = threading.Thread(target=inference_worker, name="realtime-inference")
    scheduler_thread = threading.Thread(target=arrival_scheduler, name="realtime-arrivals")

    started_threads = []
    try:
        for stream_id, pipeline in enumerate(pipelines):
            if pipeline.set_state(Gst.State.PLAYING) == Gst.StateChangeReturn.FAILURE:
                errors.append(f"stream {stream_id}: failed to enter PLAYING state")
                break
        if not errors:
            for thread in front_threads:
                thread.start()
                started_threads.append(thread)
            inference_thread.start()
            started_threads.append(inference_thread)
            t0_holder.append(time.perf_counter_ns() + 100_000_000)
            scheduler_thread.start()
            started_threads.append(scheduler_thread)
            loop.run()
    except Exception as error:
        errors.append(f"runtime: {error}")
    finally:
        stop_event.set()
        for stream_id, pipeline in enumerate(pipelines):
            try:
                if pipeline.set_state(Gst.State.NULL) == Gst.StateChangeReturn.FAILURE:
                    errors.append(f"cleanup stream {stream_id}: failed to enter NULL state")
            except Exception as error:
                errors.append(f"cleanup stream {stream_id} pipeline: {error}")
        for thread in started_threads:
            try:
                thread.join()
            except Exception as error:
                errors.append(f"cleanup thread {thread.name}: {error}")
        try:
            inference.close()
        except Exception as error:
            errors.append(f"cleanup TensorRTRunner: {error}")

    with state_lock:
        final_errors = list(errors)
    for stream_id in range(streams):
        expected_ids = list(range(frames_per_stream))
        actual_ids = sorted(
            record["frame_id"] for record in records if record["stream_id"] == stream_id
        )
        if arrivals[stream_id] != frames_per_stream:
            final_errors.append(
                f"stream {stream_id} arrivals={arrivals[stream_id]} expected={frames_per_stream}"
            )
        if source_samples_pulled[stream_id] != frames_per_stream:
            final_errors.append(
                f"stream {stream_id} source samples={source_samples_pulled[stream_id]} "
                f"expected={frames_per_stream}"
            )
        if preprocessed[stream_id] != frames_per_stream:
            final_errors.append(f"stream {stream_id}: preprocessing count mismatch")
        if completions[stream_id] != frames_per_stream:
            final_errors.append(
                f"stream {stream_id} completions={completions[stream_id]} expected={frames_per_stream}"
            )
        if actual_ids != expected_ids:
            final_errors.append(f"stream {stream_id}: frame ID sequence mismatch")
    timing = validate_timing(records)
    if any(timing.values()):
        final_errors.append(f"raw-ns timing validation: {timing}")
    qmetrics = {}
    try:
        qmetrics = queue_metrics(accounting.events, records, accounting.n_enqueue, accounting.n_start)
    except Exception as error:
        final_errors.append(f"queue validation: {error}")
    rows = frame_rows_ns(records, t0_holder[0]) if t0_holder else []
    if len(rows) != total_expected:
        final_errors.append(f"per-frame rows={len(rows)}, expected={total_expected}")
    positive_depth = sum(r["inference_queue_depth_before_enqueue"] > 0 for r in rows)
    positive_wait = sum(r["inference_queue_wait_ns"] > 0 for r in rows)
    if streams == 6 and (not positive_depth or not positive_wait):
        final_errors.append("K6 did not exercise positive queue depth/wait")
    # Preserve raw ns evidence separately; never extend the exact per-frame CSV.
    write_json(artifact("smoke_raw_ns.json"), {"t0_ns": t0_holder[0] if t0_holder else None,
               "records": records, "queue_events": accounting.events})
    write_csv(output_dir / "per_frame.csv", PER_FRAME_FIELDS, rows)
    with (output_dir / "per_frame.csv").open(newline="") as handle:
        saved = csv.DictReader(handle)
        saved_rows = list(saved)
        if saved.fieldnames != PER_FRAME_FIELDS or len(saved_rows) != total_expected:
            final_errors.append("serialized CSV schema/row mismatch")
        if any(not math.isfinite(float(row[field])) or float(row[field]) < 0
               for row in saved_rows for field in PER_FRAME_FIELDS):
            final_errors.append("serialized CSV has non-finite/negative values")
    if not final_errors:
        run = run_summary(rows, streams, args.run_id)
        motivation, queues = aggregate_runs([run], [dict(qmetrics, K=streams, run_id=args.run_id)], formal=False)
        write_csv(artifact("smoke_per_run_summary.csv"), PER_RUN_FIELDS, [run])
        write_csv(artifact("smoke_motivation_summary.csv"), MOTIVATION_FIELDS, motivation)
        write_csv(artifact("smoke_inference_queue_summary.csv"), QUEUE_FIELDS, queues)
    validation = {
        "artifact_class": "SMOKE / NON-FORMAL" if args.smoke else "FORMAL / SINGLE RUN", "K": streams, "expected": total_expected,
        "counts": {"arrivals": sum(arrivals), "source_samples": sum(source_samples_pulled),
                   "preprocessed": sum(preprocessed), "completions": sum(completions), "per_frame_rows": len(rows)},
        "per_stream_counts": [{"stream_id": i, "arrivals": arrivals[i],
            "source_samples": source_samples_pulled[i], "preprocessed": preprocessed[i],
            "completions": completions[i]} for i in range(streams)],
        "frame_ID_range": f"0..{frames_per_stream - 1} exactly once per stream",
        **timing, "queue": qmetrics, "queue_depth_positive_frames": positive_depth,
        "queue_wait_positive_frames": positive_wait,
        "queue_accounting": "PASS" if qmetrics else "FAIL",
        "errors": final_errors, "validation": "PASS" if not final_errors else "FAIL",
        "performance_interpretation": "NONE" if args.smoke else "formal latency breakdown",
    }
    write_json(artifact("smoke_validation.json"), validation)
    print(json.dumps(validation, default=str))
    return 1 if final_errors else 0


if __name__ == "__main__":
    sys.exit(main())
