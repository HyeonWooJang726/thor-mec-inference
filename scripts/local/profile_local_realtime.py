#!/usr/bin/env python3
"""Validate a phase-aligned 30 FPS local B=1, C=1 workload."""

# Resolve shared experiment modules for direct script and repository-root imports.
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parents[1] / "common"))
from script_paths import configure as _configure, script_path
_configure()


import argparse
import csv
import json
import queue
import statistics
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


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    videos = parser.add_mutually_exclusive_group(required=True)
    videos.add_argument("--video")
    videos.add_argument("--videos", nargs="+")
    parser.add_argument("--engine", required=True)
    parser.add_argument("--fps", type=float, default=30.0)
    parser.add_argument("--frames-per-stream", type=int, required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    if args.fps != 30.0:
        parser.error("--fps must be 30")
    if args.frames_per_stream < 1:
        parser.error("--frames-per-stream must be at least 1")
    return args


def percentile(values, percentile_value):
    return float(np.percentile(np.asarray(values, dtype=np.float64), percentile_value))


CSV_FIELDS = [
    "stream_id", "frame_id", "scheduled_arrival_s", "actual_arrival_enqueue_s",
    "front_end_start_s", "ready_s", "inference_start_s", "completion_s",
    "scheduler_lag_ms", "arrival_queue_wait_ms", "scheduled_to_front_end_ms",
    "front_end_observed_ms", "ready_queue_wait_ms", "inference_ms", "local_e2e_ms",
]


def raw_rows(records):
    rows = []
    for record in sorted(records, key=lambda item: (item["stream_id"], item["frame_id"])):
        row = {name: record[name] for name in CSV_FIELDS[:8]}
        row.update({
            "scheduler_lag_ms": (record["actual_arrival_enqueue_s"] - record["scheduled_arrival_s"]) * 1000.0,
            "arrival_queue_wait_ms": (record["front_end_start_s"] - record["actual_arrival_enqueue_s"]) * 1000.0,
            "scheduled_to_front_end_ms": (record["front_end_start_s"] - record["scheduled_arrival_s"]) * 1000.0,
            "front_end_observed_ms": (record["ready_s"] - record["front_end_start_s"]) * 1000.0,
            "ready_queue_wait_ms": (record["inference_start_s"] - record["ready_s"]) * 1000.0,
            "inference_ms": (record["completion_s"] - record["inference_start_s"]) * 1000.0,
            "local_e2e_ms": (record["completion_s"] - record["scheduled_arrival_s"]) * 1000.0,
        })
        rows.append(row)
    return rows


def reconstruct_backlog(records):
    """Replay raw timestamps, applying arrivals before completions on ties."""
    events = []
    for record in records:
        events.append((record["actual_arrival_enqueue_s"], 0))
        events.append((record["completion_s"], 1))
    backlog = 0
    peak = 0
    at_final_arrival = None
    for _timestamp, event_type in sorted(events):
        if event_type == 0:
            backlog += 1
            peak = max(peak, backlog)
            at_final_arrival = backlog
        else:
            backlog -= 1
    return peak, at_final_arrival, backlog


def write_artifacts(output_dir, args, videos, arrivals, samples, completions, records,
                    peak_backlog, backlog_at_final_arrival, final_backlog, errors):
    rows = raw_rows(records)
    with (output_dir / "per_frame.csv").open("x", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    lags = [row["scheduler_lag_ms"] for row in rows]
    summary = {
        "configuration": {
            "videos": videos, "K": len(videos), "fps": args.fps,
            "frames_per_stream": args.frames_per_stream, "engine": args.engine,
            "B": 1, "C": 1,
        },
        "counts": {
            "arrivals": sum(arrivals), "source_samples_pulled": sum(samples),
            "completions": sum(completions),
        },
        "per_stream_counts": [
            {
                "stream_id": stream_id, "arrivals": arrivals[stream_id],
                "source_samples_pulled": samples[stream_id],
                "completions": completions[stream_id],
            }
            for stream_id in range(len(videos))
        ],
        "scheduler": {
            "lag_mean_ms": statistics.fmean(lags) if lags else None,
            "lag_p95_ms": percentile(lags, 95) if lags else None,
            "lag_max_ms": max(lags) if lags else None,
        },
        "backlog": {
            "peak": peak_backlog, "at_final_arrival": backlog_at_final_arrival,
            "after_drain": final_backlog,
        },
        "errors": errors,
        "validation": "pass" if not errors else "fail",
    }
    with (output_dir / "summary.json").open("x") as handle:
        json.dump(summary, handle, indent=2)
        handle.write("\n")
    return rows


def main():
    args = parse_args()
    videos = [args.video] if args.video is not None else args.videos
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

    def fail(message):
        with state_lock:
            errors.append(message)
        stop_event.set()
        GLib.idle_add(loop.quit)

    def arrival_scheduler():
        try:
            t0 = t0_holder[0]
            for frame_id in range(frames_per_stream):
                target = t0 + frame_id / args.fps
                remaining = target - time.perf_counter()
                if remaining > 0 and stop_event.wait(remaining):
                    return
                if stop_event.is_set():
                    return
                for stream_id in range(streams):
                    with state_lock:
                        actual = time.perf_counter()
                        job = {
                            "stream_id": stream_id,
                            "frame_id": frame_id,
                            "scheduled_arrival_s": target,
                            "actual_arrival_enqueue_s": actual,
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
                job["front_end_start_s"] = time.perf_counter()
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
                job["ready_s"] = time.perf_counter()
                job["tensor"] = tensor
                ready_queue.put(job)
        except Exception as error:
            fail(f"stream {stream_id} front end: {error}")

    def inference_worker():
        try:
            while sum(completions) < total_expected and not stop_event.is_set():
                try:
                    job = ready_queue.get(timeout=0.1)
                except queue.Empty:
                    continue
                job["inference_start_s"] = time.perf_counter()
                outputs = inference.infer(job["tensor"])
                if set(outputs) != {"pred_logits", "pred_boxes"}:
                    raise RuntimeError(f"unexpected TensorRT outputs: {list(outputs)}")
                job["completion_s"] = time.perf_counter()
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
            t0_holder.append(time.perf_counter() + 0.1)
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
    peak_backlog, backlog_at_final_arrival, final_backlog = reconstruct_backlog(records)
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
        if completions[stream_id] != frames_per_stream:
            final_errors.append(
                f"stream {stream_id} completions={completions[stream_id]} expected={frames_per_stream}"
            )
        if actual_ids != expected_ids:
            final_errors.append(f"stream {stream_id}: frame ID sequence mismatch")
    if final_backlog != 0:
        final_errors.append(f"final backlog={final_backlog}, expected=0")
    try:
        artifact_rows = write_artifacts(
            output_dir, args, videos, arrivals, source_samples_pulled, completions,
            records, peak_backlog, backlog_at_final_arrival, final_backlog, final_errors,
        )
    except Exception as error:
        final_errors.append(f"artifact write: {error}")
        artifact_rows = []
    if len(artifact_rows) != len(records):
        final_errors.append(
            f"per-frame artifact rows={len(artifact_rows)} completions={len(records)}"
        )
    if final_errors:
        for error in final_errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1

    scheduler_lag_ms = [
        (record["actual_arrival_enqueue_s"] - record["scheduled_arrival_s"]) * 1000.0
        for record in records
    ]
    arrival_queue_wait_ms = [
        (record["front_end_start_s"] - record["actual_arrival_enqueue_s"]) * 1000.0
        for record in records
    ]
    scheduled_to_front_end_ms = [
        (record["front_end_start_s"] - record["scheduled_arrival_s"]) * 1000.0
        for record in records
    ]
    front_end_observed_ms = [
        (record["ready_s"] - record["front_end_start_s"]) * 1000.0 for record in records
    ]
    ready_queue_wait_ms = [
        (record["inference_start_s"] - record["ready_s"]) * 1000.0 for record in records
    ]
    inference_ms = [
        (record["completion_s"] - record["inference_start_s"]) * 1000.0
        for record in records
    ]
    local_e2e_ms = [
        (record["completion_s"] - record["scheduled_arrival_s"]) * 1000.0
        for record in records
    ]
    final_tick_lags = [
        lag
        for lag, record in zip(scheduler_lag_ms, records)
        if record["frame_id"] == frames_per_stream - 1
    ]

    print(f"streams: {streams}")
    print(f"fps: {args.fps:g}")
    print(f"frames per stream: {frames_per_stream}")
    print(f"offered load [frames/s]: {streams * args.fps:g}")
    print(f"engine: {args.engine}")
    print(f"actual pipeline: {PIPELINE_TEXT}")
    print("arrival synchronization: phase-aligned")
    print("TensorRT batch B: 1")
    print("cross-inference concurrency C: 1")
    print("TensorRT execution contexts: 1")
    print("inference workers: 1")
    print("dynamic batching: no")
    print("frame drop: no")
    for stream_id, video in enumerate(videos):
        print(f"stream {stream_id} video path: {video}")
        print(f"stream {stream_id} arrivals: {arrivals[stream_id]}")
        print(f"stream {stream_id} source samples pulled: {source_samples_pulled[stream_id]}")
        print(f"stream {stream_id} preprocessed: {preprocessed[stream_id]}")
        print(f"stream {stream_id} completions: {completions[stream_id]}")
        print(f"stream {stream_id} frame IDs: 0..{frames_per_stream - 1} exactly once")
    print(f"total arrivals: {sum(arrivals)}")
    print(f"total source samples pulled: {sum(source_samples_pulled)}")
    print(f"total completions: {sum(completions)}")
    print(f"per-frame artifact: {output_dir / 'per_frame.csv'}")
    print(f"summary artifact: {output_dir / 'summary.json'}")
    print(f"scheduler lag mean [ms]: {statistics.fmean(scheduler_lag_ms):.6f}")
    print(f"scheduler lag p95 [ms]: {percentile(scheduler_lag_ms, 95):.6f}")
    print(f"scheduler lag max [ms]: {max(scheduler_lag_ms):.6f}")
    print(f"scheduler final-tick lag max [ms]: {max(final_tick_lags):.6f}")
    print(f"arrival queue wait mean [ms]: {statistics.fmean(arrival_queue_wait_ms):.6f}")
    print(f"scheduled to front end mean [ms]: {statistics.fmean(scheduled_to_front_end_ms):.6f}")
    print(f"front end observed mean [ms]: {statistics.fmean(front_end_observed_ms):.6f}")
    print(f"ready queue wait mean [ms]: {statistics.fmean(ready_queue_wait_ms):.6f}")
    print(f"inference mean [ms]: {statistics.fmean(inference_ms):.6f}")
    print(f"local E2E mean [ms]: {statistics.fmean(local_e2e_ms):.6f}")
    print(f"peak backlog: {peak_backlog}")
    print(f"backlog immediately after final actual arrival: {backlog_at_final_arrival}")
    print(f"final backlog after drain: {final_backlog}")
    print("termination: bounded workload fully drained")
    print(
        f"RESULT streams={streams} arrivals={sum(arrivals)} "
        f"completions={sum(completions)} peak_backlog={peak_backlog} "
        f"final_arrival_backlog={backlog_at_final_arrival} final_backlog={final_backlog}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
