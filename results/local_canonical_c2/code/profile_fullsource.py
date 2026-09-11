#!/usr/bin/env python3
"""Canonical fixed C2 full-source Local baseline."""
import argparse
import csv
import math
import queue
import sys
import threading
import time
import json
import hashlib
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[3] / 'scripts'))

from profile_local_latency_breakdown import (
    REPO, audit_inputs, write_json, experiment_metadata as c1_metadata,
    Gst, GstVideo, GLib, cv2, np, build_pipeline as original_build_pipeline, preprocess_bgr,
    QueueAccounting, PER_FRAME_FIELDS, PER_RUN_FIELDS, MOTIVATION_FIELDS, QUEUE_FIELDS,
    frame_rows_ns, validate_timing, queue_metrics, run_summary, aggregate_runs, write_csv,
)
from run_local_concurrency_trtexec_probe import environment as environment_metadata
from screening_tensorrt import ConcurrentTensorRT
from screening_validation import validate_concurrency
from termination_contract import validate_termination

ROOT = REPO / 'results/local_canonical_c2'
CONCURRENCY_FIELDS = ['worker_id', 'context_id', 'a_ns', 'b_ns', 'r_ns', 's_ns', 'c_ns', 'service_start_ns', 'service_completion_ns',
                      'submission_return_ns', 'stream_sync_return_ns']
CONTROL_FRAME_FIELDS = ['C', 'K', 'run_id'] + PER_FRAME_FIELDS + CONCURRENCY_FIELDS + ['start_lag_ns', 'front_end_ns', 'queue_wait_ns', 'inference_ns', 'local_latency_ns', 'start_lag_ms', 'queue_wait_ms', 'local_latency_ms']


def parse_args():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--formal', action='store_true', required=True)
    p.add_argument('--concurrency', type=int, required=True, choices=(2,))
    p.add_argument('--k', type=int, required=True, choices=tuple(range(1,8)))
    p.add_argument('--frames-per-stream', type=int, required=True, choices=(1800,))
    p.add_argument('--run-id', required=True)
    p.add_argument('--output-dir', required=True)
    args = p.parse_args()
    raw = Path(args.output_dir).absolute()
    if any(q.is_symlink() for q in (raw, *raw.parents)):
        p.error('symlink output forbidden')
    out = raw.resolve()
    if args.run_id not in tuple(f'run{i:02d}' for i in range(1,6)):
        p.error('canonical fixes run01..run05')
    expected = ROOT / f'k{args.k}' / args.run_id
    if out != expected:
        p.error(f'exact fresh output required: {expected}')
    args.fps, args.output_dir, args.smoke = 30, str(out), False
    return args


def experiment_metadata(args, reference, evidence, video_metadata, environment, *, formal=False):
    data = c1_metadata(args, reference, evidence, video_metadata, environment, formal=formal)
    data.update({
        'concurrency': args.concurrency, 'planned_formal_K_list': list(range(1,8)),
        'K_list': list(range(1,8)) if formal else [args.k],
        'worker_startup_order': 'pipelines PLAYING -> front-end workers -> C context-owning inference workers -> t0+100ms -> arrival scheduler -> GLib loop',
        'source_preparation': 'one shared engine and C independent contexts/streams/buffer sets created first; same pipeline preparation',
        'warm_up_behavior': 'NONE; all 1800 full-source frames retained; no exclusion',
        'inference_ms_boundary': 's at end of start accounting -> input validation and private pinned staging copy -> async H2D -> execute_async_v3(nondefault per-worker stream) -> async D2H -> cudaStreamSynchronize(own stream) -> host output return -> c; not pure GPU kernel latency',
        'queue_depth_definition': 'N_enqueue-N_inference_start; excludes all 0..C service frames; dequeued job remains waiting until s',
        'gpu_kernel_overlap_directly_measured': False,
        'extra_service_instrumentation': 'host execute return and stream-sync return timestamps; no GPU timing events',
        'control_differences': 'primary comparison: only worker/context/stream/buffer-set count changes with C; identical per-request infer/timing/queue code',
        'EOS_behavior': 'FULL SOURCE: original unbounded file/decode pipeline; all actual natural bus EOS messages and all accepted completions required before successful cleanup; sample budget cannot replace EOS',
        'C1_measurement_sources_modified': False,
    })
    data.update(artifact_class='CANONICAL STATIC C2 FULL-SOURCE LOCAL',
                purpose='final canonical static Local baseline; C2 fixed configuration',
                K_list=[args.k], planned_formal_K_list=list(range(1,8)), run_count_per_K=5,
                offered_duration_s=60, full_source_expected_frames=1800,
                pipeline_termination='original full-source file/decode chain; no identity limiter or synthetic EOS',
                K_level_summary_aggregation='five separate run statistics; mean/sample SD/median/min/max; never pooled frames')
    data.pop('formal_duration_seconds', None)
    data['source_sha256'].update({n: hashlib.sha256((REPO/'scripts'/n).read_bytes()).hexdigest() for n in
        ('profile_local_concurrency_control.py', 'local_concurrency_tensorrt.py', 'local_concurrency_validation.py')})
    return data


def build_pipeline(video, frames):
    if frames != 1800:
        raise ValueError('only the audited complete 1800-frame source is supported')
    return original_build_pipeline(video)


def main():
    process_entry_ns = time.perf_counter_ns()
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

    # Isolated control fork; C=1 files remain read-only. C=2 changes documented below.
    def artifact(name):
        return output_dir / name.removeprefix("smoke_")

    write_json(artifact("smoke_metadata.json"), experiment_metadata(
        args, reference, evidence, video_metadata, environment, formal=False))
    Gst.init(None)
    cv2.setNumThreads(1)
    pipelines = []
    sinks = []
    inference = None
    try:
        inference = ConcurrentTensorRT(args.engine, args.concurrency)
        write_json(output_dir / "resources.json", inference.resources)
        resource_metadata = inference.resources
        for video in videos:
            pipeline, _converter, sink = build_pipeline(video, frames_per_stream)
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
    source_loop_normal = [False] * streams
    source_worker_exception = [None] * streams
    gst_errors = [[] for _ in range(streams)]
    shutdown_requested = [False] * streams
    shutdown_NULL = [False] * streams
    lifecycle = []
    joined = {}
    watchdog_triggered = False
    records = []
    t0_holder = []
    accounting = QueueAccounting()

    def fail(message):
        with state_lock:
            errors.append(message)
        stop_event.set()
        GLib.idle_add(loop.quit)

    def maybe_finish():
        with state_lock:
            complete = sum(completions) == total_expected
            sources_done = all(source_loop_normal) and all(eos)
        if complete and sources_done:
            loop.quit()
        return False

    def watchdog():
        nonlocal watchdog_triggered
        watchdog_triggered = True
        fail('run watchdog expired before natural full-source EOS/accepted-frame drain')
        return False

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
            source_worker_exception[stream_id] = str(error)
            fail(f"stream {stream_id} front end: {error}")
        else:
            with state_lock:
                source_loop_normal[stream_id] = True
                lifecycle.append({'event': 'full_source_acquisition_loop_normal_return', 'stream_id': stream_id, 'ns': time.perf_counter_ns()})
            GLib.idle_add(maybe_finish)

    def inference_worker(worker_id):
        try:
            context_worker = inference.workers[worker_id]
            context_worker.bind_thread()
            while sum(completions) < total_expected and not stop_event.is_set():
                try:
                    job = ready_queue.get(timeout=0.1)
                except queue.Empty:
                    continue
                job["worker_id"] = worker_id
                job["context_id"] = worker_id
                with state_lock:
                    accounting.start(job, time.perf_counter_ns)
                outputs = context_worker.infer(job["tensor"])
                job["c_ns"] = time.perf_counter_ns()
                job["service_start_ns"] = job["s_ns"]
                job["service_completion_ns"] = job["c_ns"]
                job["submission_return_ns"] = context_worker.submission_return_ns
                job["stream_sync_return_ns"] = context_worker.stream_sync_return_ns
                if set(outputs) != {"pred_logits", "pred_boxes"}:
                    raise RuntimeError(f"unexpected TensorRT outputs: {list(outputs)}")
                del job["tensor"]
                stream_id = job["stream_id"]
                with state_lock:
                    completions[stream_id] += 1
                    records.append(job)
                    complete = sum(completions) == total_expected
                if complete:
                    GLib.idle_add(maybe_finish)
        except Exception as error:
            fail(f"inference worker: {error}")

    def on_message(_bus, message, stream_id):
        if message.type == Gst.MessageType.ERROR:
            error, debug = message.parse_error()
            gst_errors[stream_id].append(str(error))
            fail(f"stream {stream_id} GStreamer: {error}; debug={debug or 'unavailable'}")
        elif message.type == Gst.MessageType.EOS:
            with state_lock:
                eos[stream_id] = True
                lifecycle.append({'event': 'bus_EOS_observed', 'stream_id': stream_id, 'ns': time.perf_counter_ns()})
            maybe_finish()

    for stream_id, pipeline in enumerate(pipelines):
        bus = pipeline.get_bus()
        bus.add_signal_watch()
        bus.connect("message", on_message, stream_id)

    front_threads = [
        threading.Thread(target=front_end_worker, args=(stream_id,), name=f"realtime-front-{stream_id}")
        for stream_id in range(streams)
    ]
    inference_threads = [threading.Thread(target=inference_worker, args=(i,), name=f"concurrent-inference-{i}") for i in range(args.concurrency)]
    scheduler_thread = threading.Thread(target=arrival_scheduler, name="realtime-arrivals")

    def join_started_workers():
        for thread in started_threads:
            try:
                thread.join(timeout=5)
                joined[thread.name] = not thread.is_alive()
                lifecycle.append({'event': 'worker_join', 'worker': thread.name,
                    'joined': joined[thread.name], 'ns': time.perf_counter_ns()})
                if not joined[thread.name]:
                    errors.append(f"cleanup thread {thread.name}: join timeout")
            except Exception as error:
                errors.append(f"cleanup thread {thread.name}: {error}")

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
            for thread in inference_threads:
                thread.start()
                started_threads.append(thread)
            t0_holder.append(time.perf_counter_ns() + 100_000_000)
            scheduler_thread.start()
            started_threads.append(scheduler_thread)
            GLib.timeout_add_seconds(300, watchdog)
            loop.run()
    except Exception as error:
        errors.append(f"runtime: {error}")
    finally:
        stop_event.set()
        clean_full_source_exit = not errors and all(eos) and all(source_loop_normal) and sum(completions) == total_expected
        if clean_full_source_exit:
            join_started_workers()
        # Drain already queued genuine bus messages; do not wait for or synthesize EOS.
        for stream_id, pipeline in enumerate(pipelines):
            bus = pipeline.get_bus()
            while True:
                message = bus.pop_filtered(Gst.MessageType.ERROR | Gst.MessageType.EOS)
                if message is None:
                    break
                on_message(bus, message, stream_id)
        for stream_id, pipeline in enumerate(pipelines):
            try:
                result = pipeline.set_state(Gst.State.NULL)
                shutdown_requested[stream_id] = result != Gst.StateChangeReturn.FAILURE
                status, current, pending = pipeline.get_state(5 * Gst.SECOND)
                shutdown_NULL[stream_id] = (status != Gst.StateChangeReturn.FAILURE and current == Gst.State.NULL)
                lifecycle.append({'event': 'pipeline_shutdown', 'stream_id': stream_id,
                    'request_result': str(result), 'state_result': str(status), 'state': str(current),
                    'pending': str(pending), 'ns': time.perf_counter_ns()})
                if not shutdown_requested[stream_id] or not shutdown_NULL[stream_id]:
                    errors.append(f"cleanup stream {stream_id}: failed to confirm NULL state")
            except Exception as error:
                errors.append(f"cleanup stream {stream_id} pipeline: {error}")
        if not clean_full_source_exit:
            join_started_workers()
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
    concurrency_metrics = {}
    try:
        concurrency_metrics = validate_concurrency(records, resource_metadata, args.concurrency)
    except Exception as error:
        final_errors.append(f"concurrency validation: {error}")
    qmetrics = {}
    try:
        qmetrics = queue_metrics(accounting.events, records, accounting.n_enqueue, accounting.n_start)
    except Exception as error:
        final_errors.append(f"queue validation: {error}")
    rows = frame_rows_ns(records, t0_holder[0]) if t0_holder else []
    if len(rows) != total_expected:
        final_errors.append(f"per-frame rows={len(rows)}, expected={total_expected}")
    termination_evidence = {
        'mode': 'full_source', 'frames_per_stream': frames_per_stream, 'streams': streams,
        'per_stream': [{'source_samples_pulled': source_samples_pulled[i],
            'frame_ids': sorted(r['frame_id'] for r in records if r['stream_id'] == i),
            'source_loop_normal_return': source_loop_normal[i],
            'source_joined': joined.get(front_threads[i].name, False),
            'pipeline_shutdown_requested': shutdown_requested[i], 'pipeline_NULL_confirmed': shutdown_NULL[i],
            'worker_exception': source_worker_exception[i], 'gstreamer_errors': gst_errors[i],
            'eos_observed': eos[i]} for i in range(streams)],
        'counts': {'arrivals': sum(arrivals), 'samples': sum(source_samples_pulled),
            'preprocessed': sum(preprocessed), 'completed': sum(completions), 'per_frame_rows': len(rows)},
        'timing': timing, 'waiting_after_drain': qmetrics.get('waiting_after_drain'),
        'active_after_drain': concurrency_metrics.get('active_after_drain'),
        'negative_waiting_depth_events': sum(e['depth'] < 0 for e in accounting.events),
        'all_workers_joined': len(joined) == streams + args.concurrency + 1 and all(joined.values()),
        'watchdog_triggered': watchdog_triggered, 'runtime_errors': list(final_errors)}
    termination = validate_termination(termination_evidence)
    final_errors.extend(termination['errors'])
    write_json(output_dir / 'termination_evidence.json', termination_evidence)
    write_json(output_dir / 'lifecycle.json', lifecycle)
    positive_depth = sum(r["inference_queue_depth_before_enqueue"] > 0 for r in rows)
    positive_wait = sum(r["inference_queue_wait_ns"] > 0 for r in rows)
    # Preserve both canonical metric columns and explicit concurrency evidence.
    write_json(artifact("smoke_raw_ns.json"), {"t0_ns": t0_holder[0] if t0_holder else None,
               "records": records, "queue_events": accounting.events})
    by_id = {(r['stream_id'], r['frame_id']): r for r in records}
    for row in rows:
        raw = by_id[(row['stream_id'], row['frame_id'])]
        row.update({key: raw[key] for key in CONCURRENCY_FIELDS})
        row.update(C=args.concurrency, K=streams, run_id=args.run_id, start_lag_ns=row['frame_start_lag_ns'], queue_wait_ns=row['inference_queue_wait_ns'], local_latency_ns=row['e2e_ns'])
    write_csv(output_dir / "per_frame.csv", CONTROL_FRAME_FIELDS, rows)
    with (output_dir / "per_frame.csv").open(newline="") as handle:
        saved = csv.DictReader(handle)
        saved_rows = list(saved)
        if saved.fieldnames != CONTROL_FRAME_FIELDS or len(saved_rows) != total_expected:
            final_errors.append("serialized CSV schema/row mismatch")
        if any(not math.isfinite(float(row[field])) or float(row[field]) < 0
               for row in saved_rows for field in CONTROL_FRAME_FIELDS if field != "run_id"):
            final_errors.append("serialized CSV has non-finite/negative values")
    if not final_errors:
        run = run_summary(rows, streams, args.run_id)
        motivation, queues = aggregate_runs([run], [dict(qmetrics, K=streams, run_id=args.run_id)], formal=False)
        write_csv(artifact("smoke_per_run_summary.csv"), PER_RUN_FIELDS, [run])
        write_csv(artifact("smoke_motivation_summary.csv"), MOTIVATION_FIELDS, motivation)
        write_csv(artifact("smoke_inference_queue_summary.csv"), QUEUE_FIELDS, queues)
    if not final_errors:
        write_json(output_dir / "run_summary.json", {"metrics_ns": run, "queue": qmetrics, **concurrency_metrics})
    validation = {
        "artifact_class": "CANONICAL STATIC C2 FULL-SOURCE LOCAL", "K": streams, "C": args.concurrency, "expected": total_expected,
        "source_EOS": eos, "EOS_validation": "PASS" if all(eos) else "FAIL",
        "termination": termination, "bounded_complete": termination["bounded_complete"],
        "counts": {"arrivals": sum(arrivals), "source_samples": sum(source_samples_pulled),
                   "preprocessed": sum(preprocessed), "completions": sum(completions), "per_frame_rows": len(rows)},
        "per_stream_counts": [{"stream_id": i, "arrivals": arrivals[i],
            "source_samples": source_samples_pulled[i], "preprocessed": preprocessed[i],
            "completions": completions[i]} for i in range(streams)],
        "frame_ID_range": f"0..{frames_per_stream - 1} exactly once per stream",
        **timing, "concurrency": concurrency_metrics, "resources": resource_metadata,
        "negative_waiting_depth_events": sum(e["depth"] < 0 for e in accounting.events),
        "queue": qmetrics, "queue_depth_positive_frames": positive_depth,
        "queue_wait_positive_frames": positive_wait,
        "queue_accounting": "PASS" if qmetrics else "FAIL",
        "errors": final_errors, "validation": "PASS" if not final_errors else "FAIL",
        "performance_interpretation": "Canonical C2 Local baseline; five run-level statistics per K",
    }
    workload_completion_ns = max((r['c_ns'] for r in records), default=0)
    offered_end_ns = t0_holder[0] + frames_per_stream * 1_000_000_000 // 30 if t0_holder else 0
    validation.update(offered_duration_s=frames_per_stream/30,
                      offered_end_ns=offered_end_ns,
                      completion_elapsed_s=(workload_completion_ns-t0_holder[0])/1e9 if t0_holder else None,
                      drain_after_offered_end_s=max(0, workload_completion_ns-offered_end_ns)/1e9,
                      wall_clock_duration_s=(time.perf_counter_ns()-process_entry_ns)/1e9)
    write_json(artifact("smoke_validation.json"), validation)
    if not final_errors:
        from screening_metrics import summarize_records
        write_json(output_dir / "summary.json", summarize_records(
            records, qmetrics, concurrency_metrics, args.concurrency, streams, args.run_id))
    print(json.dumps(validation, default=str))
    return 1 if final_errors else 0


if __name__ == "__main__":
    sys.exit(main())
