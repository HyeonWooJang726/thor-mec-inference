#!/usr/bin/env python3
"""Standalone RTX 5070 Ti offline concurrency characterization. No networking.

Warm up 50 actual requests PER WORKER; measure 30 seconds; two repetitions
for each C=1,2,4,8. Run only when manually deployed and explicitly invoked.
The ContextWorker below is reused from the frozen Local worker, with its two
perf_counter timestamp reads replaced by monotonic_ns for this protocol.
This measures host TensorRT stage including H2D/execute/D2H synchronization,
not CUDA-kernel time. Host interval overlap is not GPU kernel overlap.
"""
import argparse
import csv
import ctypes
import hashlib
import json
import os
from pathlib import Path
import platform
import queue
import signal
import subprocess
import sys
import threading
import time
import traceback
from datetime import datetime, timezone

import numpy as np

trt = None  # Imported only inside the Edge execution path, never for --help.
ENGINE_SHA256 = 'c94050f1969bca2fef9622c14fd9e307277ba26b0630bf5a669a980a8bad75e9'
CACHE_SHA256 = 'df1fcb6f842f6522ffdb743e14ec9bffc5aeac5a1be7954089b1d1ddc4407552'
EXPECTED_SAMPLE_IDS = [0,14,28,41,55,69,83,96,110,124,138,151,165,179,193,206,220,234,248,261,275,289,303,316,330,344,358,371,385,399]
ORDER = [(1,1),(2,1),(4,1),(8,1),(8,2),(4,2),(2,2),(1,2)]
ACTIVE_NS = 30_000_000_000
WARMUP = 50
FIELDS = ['worker_id','request_id','sample_id','phase','service_start_ns',
          'preprocess_end_ns','inference_end_ns','completion_ns','preprocess_ms',
          'inference_ms','response_preparation_ms','service_ms','output_bytes']

class ContextWorker:
    def __init__(self, engine, worker_id):
        self.worker_id, self.owner_thread = worker_id, None
        self.cuda = ctypes.CDLL('libcudart.so')  # CDLL releases the GIL during CUDA waits.
        ptr = ctypes.c_void_p
        for name, types in {
            'cudaSetDevice': [ctypes.c_int],
            'cudaMalloc': [ctypes.POINTER(ptr), ctypes.c_size_t], 'cudaFree': [ptr],
            'cudaHostAlloc': [ctypes.POINTER(ptr), ctypes.c_size_t, ctypes.c_uint], 'cudaFreeHost': [ptr],
            'cudaStreamCreateWithFlags': [ctypes.POINTER(ptr), ctypes.c_uint],
            'cudaStreamDestroy': [ptr], 'cudaStreamSynchronize': [ptr],
            'cudaMemcpyAsync': [ptr, ptr, ctypes.c_size_t, ctypes.c_int, ptr],
        }.items():
            fn = getattr(self.cuda, name)
            fn.argtypes, fn.restype = types, ctypes.c_int
        self.device, self.host_ptrs, self.host, self.sizes = {}, {}, {}, {}
        self.stream = ptr()
        self.context = None
        try:
            self.check(self.cuda.cudaSetDevice(0), 'cudaSetDevice')
            self.context = engine.create_execution_context()
            if self.context is None:
                raise RuntimeError('execution context creation failed')
            self.check(self.cuda.cudaStreamCreateWithFlags(ctypes.byref(self.stream), 1), 'cudaStreamCreateWithFlags(nonblocking)')
            self.names = [engine.get_tensor_name(i) for i in range(engine.num_io_tensors)]
            shapes = {n: tuple(engine.get_tensor_shape(n)) for n in self.names}
            if shapes != {'inputs': (1, 3, 640, 640), 'pred_logits': (1, 300, 7), 'pred_boxes': (1, 300, 4)}:
                raise RuntimeError(f'unexpected engine shapes: {shapes}')
            for name in self.names:
                dtype = np.dtype(trt.nptype(engine.get_tensor_dtype(name)))
                if dtype != np.float32:
                    raise RuntimeError('FP32 I/O required')
                size = int(np.prod(shapes[name]))*dtype.itemsize
                self.sizes[name] = size
                device, host = ptr(), ptr()
                self.check(self.cuda.cudaMalloc(ctypes.byref(device), size), 'cudaMalloc')
                self.device[name] = device
                self.check(self.cuda.cudaHostAlloc(ctypes.byref(host), size, 0), 'cudaHostAlloc')
                self.host_ptrs[name] = host
                storage = (ctypes.c_float*(size//4)).from_address(host.value)
                self.host[name] = np.ctypeslib.as_array(storage).reshape(shapes[name])
                if not self.context.set_tensor_address(name, device.value):
                    raise RuntimeError(f'set_tensor_address: {name}')
            self.outputs = {n: self.host[n] for n in self.names if n != 'inputs'}
        except Exception:
            self.close()
            raise

    @staticmethod
    def check(status, operation):
        if status:
            raise RuntimeError(f'{operation}: CUDA error {status}')

    def resources(self):
        return {'worker_id': self.worker_id, 'context_object_id': id(self.context),
                'cuda_stream_pointer': self.stream.value,
                'device_buffers': {n: p.value for n, p in self.device.items()},
                'pinned_host_buffers': {n: p.value for n, p in self.host_ptrs.items()},
                'buffer_bytes': self.sizes}

    def bind_thread(self):
        ident = threading.get_ident()
        if self.owner_thread is not None and self.owner_thread != ident:
            raise RuntimeError('context cannot be shared by worker threads')
        self.check(self.cuda.cudaSetDevice(0), 'worker cudaSetDevice')
        self.owner_thread = ident

    def infer(self, tensor):
        if self.owner_thread != threading.get_ident():
            raise RuntimeError('context called by a non-owner thread')
        if tensor.dtype != np.float32 or tensor.shape != (1, 3, 640, 640) or not tensor.flags.c_contiguous:
            raise RuntimeError('unexpected input tensor')
        np.copyto(self.host['inputs'], tensor)
        self.check(self.cuda.cudaMemcpyAsync(self.device['inputs'], self.host_ptrs['inputs'],
                   self.sizes['inputs'], 1, self.stream), 'H2D cudaMemcpyAsync')
        if not self.context.execute_async_v3(stream_handle=self.stream.value):
            raise RuntimeError('execute_async_v3 failed')
        self.submission_return_ns = time.monotonic_ns()
        for name in self.outputs:
            self.check(self.cuda.cudaMemcpyAsync(self.host_ptrs[name], self.device[name], self.sizes[name],
                       2, self.stream), f'{name} D2H cudaMemcpyAsync')
        self.check(self.cuda.cudaStreamSynchronize(self.stream), 'cudaStreamSynchronize')
        self.stream_sync_return_ns = time.monotonic_ns()
        return self.outputs

    def close(self):
        if self.stream.value:
            self.check(self.cuda.cudaStreamSynchronize(self.stream), 'cleanup stream sync')
        self.context = None
        self.host.clear()
        if hasattr(self, 'outputs'):
            self.outputs.clear()
        for p in self.device.values():
            self.check(self.cuda.cudaFree(p), 'cudaFree')
        self.device.clear()
        for p in self.host_ptrs.values():
            self.check(self.cuda.cudaFreeHost(p), 'cudaFreeHost')
        self.host_ptrs.clear()
        if self.stream.value:
            self.check(self.cuda.cudaStreamDestroy(self.stream), 'cudaStreamDestroy')
            self.stream = ctypes.c_void_p()


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1048576), b''):
            h.update(block)
    return h.hexdigest()


def save_json(path, value):
    with Path(path).open('x') as f:
        json.dump(value, f, indent=2, allow_nan=False)
        f.write('\n')


def remaining_preprocess(raw):
    # Byte-for-byte canonical RAW640 tail; no resize on the Edge.
    if len(raw) != 691200:
        raise ValueError('expected 691200-byte RAW640')
    bgr = np.frombuffer(raw, np.uint8).reshape(360, 640, 3)
    padded = np.zeros((640, 640, 3), np.uint8)
    padded[:360] = bgr
    rgb = np.ascontiguousarray(padded[..., ::-1])
    normalized = rgb.astype(np.float32) / np.float32(255.0)
    return np.ascontiguousarray(normalized.transpose(2, 0, 1)[None])


def load_cache(path):
    if sha(path) != CACHE_SHA256:
        raise RuntimeError('cached Warehouse artifact SHA256 mismatch')
    with np.load(path, allow_pickle=False) as archive:
        raw = archive['raw640']
        ids = archive['sample_ids'].tolist()
        if raw.dtype != np.uint8 or raw.shape != (30, 360, 640, 3) or ids != EXPECTED_SAMPLE_IDS:
            raise RuntimeError('unexpected frozen RAW640 sample identities or shape')
        # Hash was verified previously on Thor. Do not repeat its semantic test.
        return [a.tobytes(order='C') for a in raw], ids


def nsmi():
    cmd = ['nvidia-smi', '-i', '0', '--query-gpu=name,driver_version,utilization.gpu,power.draw,temperature.gpu',
           '--format=csv,noheader,nounits']
    stamp = time.monotonic_ns()
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        return dict(timestamp_ns=stamp, command=cmd, returncode=p.returncode,
                    stdout=p.stdout.strip(), stderr=p.stderr.strip())
    except (OSError, subprocess.TimeoutExpired) as e:
        return dict(timestamp_ns=stamp, command=cmd, unavailable=str(e))


def validate_edge(args):
    if platform.machine().lower() not in ('x86_64', 'amd64'):
        raise RuntimeError('Edge-only profiler: refusing non-x86_64 host (including Thor)')
    if sha(args.engine) != ENGINE_SHA256:
        raise RuntimeError('RTX engine SHA256 mismatch; no engine rebuild or substitution allowed')
    gpu = nsmi()
    if gpu.get('returncode') != 0 or 'RTX 5070 Ti' not in gpu.get('stdout', ''):
        raise RuntimeError('RTX 5070 Ti visibility not verified: ' + json.dumps(gpu))
    return gpu


def percentiles(values):
    if not values:
        return {k: None for k in ('mean', 'p50', 'p95', 'p99')}
    return dict(mean=float(np.mean(values)),
                **{f'p{p}': float(np.percentile(values, p)) for p in (50, 95, 99)})


def overlap(intervals, start, end):
    """Exact integral of host in-service intervals, clipped to active window."""
    events = {}
    for a, b in intervals:
        a, b = max(a, start), min(b, end)
        if a < b:
            events[a] = events.get(a, 0) + 1
            events[b] = events.get(b, 0) - 1
    n = peak = area = 0
    previous = start
    for stamp, delta in sorted(events.items()):
        area += n * (stamp - previous)
        n += delta
        if n < 0:
            raise RuntimeError('negative host in-service accounting')
        peak = max(peak, n)
        previous = stamp
    if n:
        raise RuntimeError('unfinished clipped host interval accounting')
    return {'peak': peak, 'mean': area / (end - start)}


def analyze_rows(records, c, start, end):
    active = [r for r in records if r['phase'] == 'measurement'
              and start <= r['completion_ns'] < end]
    measurement = [r for r in records if r['phase'] == 'measurement']
    warmup = [r for r in records if r['phase'] == 'warmup']
    if len({r['request_id'] for r in records}) != len(records):
        raise RuntimeError('duplicate request IDs')
    if any(sum(r['worker_id'] == w for r in warmup) != WARMUP for w in range(c)):
        raise RuntimeError('warmup count mismatch')
    for r in records:
        if not (r['service_start_ns'] <= r['preprocess_end_ns'] <= r['inference_end_ns'] <= r['completion_ns']):
            raise RuntimeError('timestamp order corruption')
    if any(not start <= r['service_start_ns'] < end for r in measurement):
        raise RuntimeError('service admitted outside active interval')
    host = overlap([(r['service_start_ns'], r['completion_ns']) for r in measurement], start, end)
    if host['peak'] > c:
        raise RuntimeError('configured C exceeded')
    return dict(completed_active=len(active), started_active=len(measurement),
                completed_after_active=len(measurement) - len(active),
                completed_FPS=len(active) / 30,
                per_worker_completed_FPS={str(w): sum(r['worker_id'] == w for r in active) / 30 for w in range(c)},
                warmup_inferences=len(warmup), host_in_service_concurrency=host,
                latency_ms={k: percentiles([r[k] for r in active]) for k in
                            ('preprocess_ms', 'inference_ms', 'response_preparation_ms', 'service_ms')})


def run_child(args):
    global trt
    import tensorrt as imported_trt
    trt = imported_trt
    out = Path(args.output)
    payloads, sample_ids = load_cache(args.cache)
    before_gpu = validate_edge(args)
    logger = trt.Logger(trt.Logger.ERROR)
    trt.init_libnvinfer_plugins(logger, '')
    runtime = trt.Runtime(logger)  # Keep alive until every execution context is destroyed.
    engine = runtime.deserialize_cuda_engine(Path(args.engine).read_bytes())
    if engine is None:
        raise RuntimeError('TensorRT engine deserialization failed')
    workers, threads, records = [], [], [[] for _ in range(args.c)]
    errors = queue.Queue()
    stop, release, telemetry_stop = threading.Event(), threading.Event(), threading.Event()
    ready = [threading.Event() for _ in range(args.c)]
    window = {}
    interrupted = []
    telemetry = []

    def interrupt(signum, _frame):
        interrupted.append(signum)
        stop.set()
        release.set()

    signal.signal(signal.SIGTERM, interrupt)
    signal.signal(signal.SIGINT, interrupt)

    def take_request(worker, seq, phase, writer):
        wid = worker.worker_id
        index = (seq * args.c + wid) % len(payloads)
        a = time.monotonic_ns()
        if phase == 'measurement' and a >= window['end']:
            return False
        tensor = remaining_preprocess(payloads[index])
        b = time.monotonic_ns()
        outputs = worker.infer(tensor)
        d = time.monotonic_ns()
        if not all(np.isfinite(x).all() for x in outputs.values()):
            raise RuntimeError('non-finite TensorRT output')
        response = outputs['pred_logits'].tobytes(order='C') + outputs['pred_boxes'].tobytes(order='C')
        if len(response) != 13200:
            raise RuntimeError('output shape/bytes corruption')
        e = time.monotonic_ns()
        row = dict(worker_id=wid, request_id=f'{wid}:{seq}', sample_id=sample_ids[index], phase=phase,
                   service_start_ns=a, preprocess_end_ns=b, inference_end_ns=d, completion_ns=e,
                   preprocess_ms=(b-a)/1e6, inference_ms=(d-b)/1e6,
                   response_preparation_ms=(e-d)/1e6, service_ms=(e-a)/1e6, output_bytes=len(response))
        records[wid].append(row)
        writer.writerow(row)  # Private per-worker log, outside the service interval.
        return True

    def workload(worker):
        wid = worker.worker_id
        try:
            worker.bind_thread()
            with (out / f'worker_{wid}.csv').open('x', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=FIELDS)
                writer.writeheader()
                for seq in range(WARMUP):
                    if stop.is_set():
                        return
                    take_request(worker, seq, 'warmup', writer)
                f.flush()
                ready[wid].set()
                release.wait()
                if stop.is_set():
                    return
                delay = (window['start'] - time.monotonic_ns()) / 1e9
                if delay > 0:
                    stop.wait(delay)
                seq = WARMUP
                while not stop.is_set():
                    if not take_request(worker, seq, 'measurement', writer):
                        break
                    seq += 1
                    if seq % 32 == 0:
                        f.flush()
        except BaseException:
            errors.put({'worker_id': wid, 'traceback': traceback.format_exc()})
            stop.set()
        finally:
            ready[wid].set()

    def monitor():
        while not telemetry_stop.is_set():
            telemetry.append(nsmi())
            telemetry_stop.wait(1)

    clean = False
    try:
        for w in range(args.c):
            workers.append(ContextWorker(engine, w))
        resources = [w.resources() for w in workers]
        for key in ('context_object_id', 'cuda_stream_pointer'):
            if len({r[key] for r in resources}) != args.c:
                raise RuntimeError('context/stream alias')
        for key in ('device_buffers', 'pinned_host_buffers'):
            pointers = [p for r in resources for p in r[key].values()]
            if len(set(pointers)) != len(pointers):
                raise RuntimeError('private buffer alias')
        save_json(out / 'manifest.json', dict(C_E=args.c, repeat=args.repeat, warmup_per_worker=WARMUP,
                  active_seconds=30, cache_sha256=CACHE_SHA256, engine_sha256=ENGINE_SHA256,
                  cached_samples=len(payloads), sample_ids=sample_ids, resources=resources,
                  engine_aux_streams=engine.num_aux_streams, TensorRT=trt.__version__,
                  python=platform.python_version(), numpy=np.__version__,
                  color_conversion='numpy_channel_reverse_BGR_to_RGB', opencv_required=False,
                  hostname=platform.node(), platform=platform.platform(),
                  executable=sys.executable, gpu_before=before_gpu,
                  B=1, CUDA_Graph=False, dynamic_batching=False, system_changes='NONE',
                  time_source='time.monotonic_ns', measurement_kind='offline saturated worker loops',
                  inference_definition='host H2D + TensorRT execute_async_v3 + D2H + stream synchronize',
                  service_definition='preprocess + inference stage + finite check + output byte serialization',
                  host_concurrency_definition='overlap of host service intervals, not GPU kernels',
                  latency_scope='requests completed inside active window; warmup and residual drain retained separately',
                  logging='private per-worker CSV outside service interval; its overhead is included in completed throughput'))
        for worker in workers:
            t = threading.Thread(target=workload, args=(worker,), name=f'worker-{worker.worker_id}')
            threads.append(t)
            t.start()
        for event in ready:
            event.wait()
        if stop.is_set():
            raise RuntimeError('worker warmup failed or interrupted')
        window['start'] = time.monotonic_ns() + 200_000_000
        window['end'] = window['start'] + ACTIVE_NS
        save_json(out / 'active_window.json', window)
        monitor_thread = threading.Thread(target=monitor, daemon=True)
        monitor_thread.start()
        release.set()
        for t in threads:
            t.join()
        telemetry_stop.set()
        monitor_thread.join(timeout=6)
        if stop.is_set():
            raise RuntimeError('worker failed or interrupted during measurement')
        clean = True
    except BaseException:
        errors.put({'stage': 'main', 'traceback': traceback.format_exc()})
    finally:
        stop.set()
        release.set()
        telemetry_stop.set()
        for t in threads:
            t.join()
        for worker in workers:
            try:
                worker.close()
            except BaseException:
                clean = False
                errors.put({'stage': 'cleanup', 'traceback': traceback.format_exc()})
        workers.clear()
        engine = None
        runtime = None
    error_list = []
    while not errors.empty():
        error_list.append(errors.get())
    flat = [r for group in records for r in group]
    metrics = {}
    if clean and not error_list and not interrupted:
        try:
            metrics = analyze_rows(flat, args.c, window['start'], window['end'])
        except BaseException:
            error_list.append({'stage': 'accounting', 'traceback': traceback.format_exc()})
    valid = clean and not error_list and not interrupted and bool(metrics)
    save_json(out / 'gpu_diagnostic.json', dict(samples=telemetry, after=nsmi(),
              scope='optional nvidia-smi utilization/power diagnostics; no resource configuration changes'))
    save_json(out / 'summary.json', dict(integrity_status='VALID' if valid else 'INVALID',
              clean_shutdown=clean, errors=error_list, signals=interrupted, **metrics))
    return 0 if valid else 1


def selection(results):
    by_c = {c: [r for r in results if r['C_E'] == c] for c in (1, 2, 4, 8)}
    eligible = [c for c, rows in by_c.items() if len(rows) == 2 and
                all(r['integrity_status'] == 'VALID' and r['completed_FPS'] >= 40 for r in rows)]
    if eligible:
        choice = min(eligible)
        # Missing lower-C evidence prevents claiming a smallest sufficient C.
        if any(len(by_c[c]) != 2 or any(r['integrity_status'] != 'VALID' for r in by_c[c])
               for c in by_c if c < choice):
            return dict(status='INCONCLUSIVE', PRIMARY_EDGE_CONCURRENCY=None,
                        reason='lower-C integrity evidence incomplete', qualifying_C=eligible)
        return dict(status='PRIMARY_EDGE_CONCURRENCY_SELECTED', PRIMARY_EDGE_CONCURRENCY=choice,
                    per_repeat_margin_FPS=[r['completed_FPS'] - 40 for r in by_c[choice]],
                    qualifying_C=eligible, note='No extra safety margin applied; inspect the reported absolute margin.')
    complete = all(len(rows) == 2 and all(r['integrity_status'] == 'VALID' for r in rows) for rows in by_c.values())
    if complete and all(r['completed_FPS'] < 40 for r in results):
        return dict(status='EDGE_RUNTIME_CAPACITY_INSUFFICIENT', PRIMARY_EDGE_CONCURRENCY=None)
    return dict(status='INCONCLUSIVE', PRIMARY_EDGE_CONCURRENCY=None,
                reason='mixed repeats at 40 FPS or incomplete integrity evidence; no C confirmed sufficient twice')


def supervise(args):
    # No measurement runs until all local input/GPU identity checks pass on Edge.
    out = Path(args.output).resolve()
    out.mkdir(parents=True, exist_ok=False)
    try:
        gpu = validate_edge(args)
        payloads, ids = load_cache(args.cache)
        import tensorrt
        dependencies = dict(TensorRT=tensorrt.__version__, numpy=np.__version__)
    except BaseException:
        save_json(out / 'preflight_failure.json', {'traceback': traceback.format_exc()})
        return 1
    save_json(out / 'campaign_manifest.json', dict(script_sha256=sha(__file__),
              engine_path=str(Path(args.engine).resolve()), engine_sha256=ENGINE_SHA256,
              cache_path=str(Path(args.cache).resolve()), cache_sha256=CACHE_SHA256,
              cached_sample_count=len(payloads), sample_ids=ids,
              dependencies=dependencies,
              color_conversion='numpy_channel_reverse_BGR_to_RGB', opencv_required=False,
              source_scope='30 existing deterministic Warehouse frames, subset of the previous 400; no synthetic input',
              frozen_order=ORDER, warmup_per_worker=WARMUP, active_seconds=30,
              repeat_count=2, gpu_preflight=gpu, formal_future_port=5000,
              selection='smallest C with both integrity-valid completed FPS >= 40; no added margin',
              watchdog_seconds=300, watchdog_note='administrative process-hang safeguard, not a throughput threshold',
              no_network=True, no_automatic_retry=True))
    results = []
    interrupted = False
    for c, repetition in ORDER:
        directory = out / f'C{c}_R{repetition}'
        directory.mkdir()
        cmd = [sys.executable, '-B', str(Path(__file__).resolve()), '--child', '--c', str(c),
               '--repeat', str(repetition), '--engine', str(Path(args.engine).resolve()),
               '--cache', str(Path(args.cache).resolve()), '--output', str(directory)]
        start = datetime.now(timezone.utc).isoformat()
        timed_out = False
        with (directory / 'stderr.log').open('x') as log:
            child = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT)
            try:
                rc = child.wait(timeout=300)
            except (subprocess.TimeoutExpired, KeyboardInterrupt) as exc:
                timed_out = isinstance(exc, subprocess.TimeoutExpired)
                interrupted = not timed_out
                child.terminate()
                try:
                    rc = child.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    child.kill()
                    rc = child.wait()
        summary = {}
        if (directory / 'summary.json').exists():
            try:
                summary = json.loads((directory / 'summary.json').read_text())
            except (ValueError, OSError):
                pass
        valid = rc == 0 and not timed_out and not interrupted and summary.get('integrity_status') == 'VALID' and summary.get('clean_shutdown') is True
        process = dict(child_pid=child.pid, child_returncode=rc,
                       child_exit_signal=signal.Signals(-rc).name if rc < 0 else None,
                       start_time=start, exit_time=datetime.now(timezone.utc).isoformat(),
                       watchdog_timeout=timed_out, interrupted=interrupted,
                       summary_written=bool(summary), final_integrity_status='VALID' if valid else 'INVALID')
        save_json(directory / 'process_status.json', process)
        row = dict(C_E=c, repeat=repetition, integrity_status=process['final_integrity_status'],
                   completed_FPS=summary.get('completed_FPS'),
                   worker_completed_FPS=summary.get('per_worker_completed_FPS'),
                   host_in_service_peak=summary.get('host_in_service_concurrency', {}).get('peak'),
                   host_in_service_mean=summary.get('host_in_service_concurrency', {}).get('mean'),
                   clean_shutdown=summary.get('clean_shutdown', False), child_returncode=rc,
                   errors=summary.get('errors', ['missing summary']), output_directory=directory.name)
        for metric, values in summary.get('latency_ms', {}).items():
            row.update({f'{metric}_{key}': value for key, value in values.items()})
        results.append(row)
        print(json.dumps(row), flush=True)
        if interrupted:
            break
    columns = sorted(set().union(*(r.keys() for r in results)))
    with (out / 'edge_concurrency_summary.csv').open('x', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        for row in results:
            writer.writerow({k: json.dumps(v) if isinstance(v, (dict, list)) else v for k, v in row.items()})
    verdict = selection(results)
    save_json(out / 'selection.json', verdict)
    with (out / 'edge_concurrency_verdict.md').open('x') as f:
        f.write('# Offline Edge concurrency\n\n' + json.dumps(verdict, indent=2) + '\n\n'
                'Host service-interval concurrency is not GPU kernel concurrency. '
                'Inference timing includes H2D, TensorRT launch, D2H, and stream synchronization. '
                'Raw warmup/measurement rows and residual completions are retained. '
                'This offline result alone does not establish network-path 40-FPS feasibility.\n')
    save_json(out / 'output_hashes.json', {str(p.relative_to(out)): sha(p) for p in sorted(out.rglob('*')) if p.is_file()})
    print(json.dumps(verdict), flush=True)
    return 0 if len(results) == 8 and all(r['integrity_status'] == 'VALID' for r in results) else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--execute', action='store_true', help='Run eight offline measurements on RTX 5070 Ti Edge only')
    mode.add_argument('--child', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--engine', required=True, help='Existing RTX-specific B1 FP16 engine; frozen SHA256 is checked')
    parser.add_argument('--cache', required=True, help='Existing semantic_raw640_30.npz; frozen SHA256 is checked')
    parser.add_argument('--output', required=True, help='NEW Edge result directory; existing path is never overwritten')
    parser.add_argument('--c', type=int, choices=(1, 2, 4, 8), help=argparse.SUPPRESS)
    parser.add_argument('--repeat', type=int, choices=(1, 2), help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.child and (args.c is None or args.repeat is None):
        parser.error('child needs C/repeat')
    return run_child(args) if args.child else supervise(args)


if __name__ == '__main__':
    raise SystemExit(main())
