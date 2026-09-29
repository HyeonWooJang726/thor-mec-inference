#!/usr/bin/env python3
"""Explicitly launched RTX 5070 Ti RAW640 server; C=1, port 5000 only."""
import argparse
import csv
import hashlib
from pathlib import Path
import queue
import socket
import threading
import time
import traceback

import formal_protocol as p


class Backend:
    """All CUDA resource creation/use/destruction belongs to one worker thread."""
    def __init__(self, args):
        self.worker = None
        self.runtime = self.engine = None
        self.h = p.load_runtime_helpers()
        self.gpu = self.h.validate_edge(args)
        self.payloads, self.ids = self.h.load_cache(args.cache)
        import tensorrt as trt
        self.h.trt = trt
        self.trt_version = trt.__version__
        self.logger = trt.Logger(trt.Logger.ERROR)
        trt.init_libnvinfer_plugins(self.logger, '')
        self.runtime = trt.Runtime(self.logger)
        self.engine = self.runtime.deserialize_cuda_engine(Path(args.engine).read_bytes())
        if self.engine is None:
            raise RuntimeError('engine deserialize failed')
        self.worker = self.h.ContextWorker(self.engine, 0)
        self.worker.bind_thread()

    def process(self, raw):
        stamps = {'preprocess_start_ns': time.monotonic_ns()}
        tensor = self.h.remaining_preprocess(raw)
        stamps['preprocess_end_ns'] = time.monotonic_ns()
        stamps['inference_start_ns'] = time.monotonic_ns()
        outputs = self.worker.infer(tensor)
        stamps['inference_end_ns'] = time.monotonic_ns()
        data = p.encode_outputs(outputs)  # Copy private output buffers before next request.
        stamps['response_ready_ns'] = time.monotonic_ns()
        return stamps, data

    def info(self):
        return dict(TensorRT=self.trt_version, gpu_before=self.gpu,
                    resources=self.worker.resources(), engine_aux_streams=self.engine.num_aux_streams,
                    engine_sha256=self.h.ENGINE_SHA256, cache_sha256=self.h.CACHE_SHA256,
                    color_conversion='numpy_channel_reverse_BGR_to_RGB', opencv_required=False,
                    C_E=1, B=1, CUDA_Graph=False, dynamic_batching=False,
                    inference_definition='host H2D + execute_async_v3 + D2H + stream synchronization')

    def close(self):
        if self.worker is not None:
            self.worker.close()
            self.worker = None
        self.engine = None
        self.runtime = None


def serve_session(conn, output, expected, backend_factory):
    """Receive and inference paths are separate; FIFO has no finite cap/drop policy.

    backend_factory is injectable only for CPU protocol tests; CLI always uses Backend.
    FINAL is sent only after worker cleanup and persisted server accounting.
    """
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    incoming = queue.Queue()  # Unbounded; bounded experiment request count validated below.
    stop = threading.Event()
    ready = threading.Event()
    errors, rows, warmup = [], [], []
    shared = dict(received=0, completed=0, responses_sent=0, duplicates=0,
                  queue_peak_observed=0, queue_cap_saturation=False, drops=0,
                  cleanup_started=False, cleanup_completed=False, end_received=False)
    thread = None

    def fail():
        errors.append(traceback.format_exc())
        stop.set()
        try:
            conn.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass

    try:
        kind, _, hello, _ = p.recv_message(conn)
        for key, value in expected.items():
            if hello.get(key) != value:
                raise ValueError(f'HELLO {key} does not match frozen session order')
        helpers = p.load_runtime_helpers()
        if kind != p.HELLO or hello.get('cache_sha256') != helpers.CACHE_SHA256:
            raise ValueError('invalid HELLO/cache')
        count = hello['rate'] * hello['seconds']
        p.save(output / 'manifest.json', dict(client_hello=hello, expected=expected,
                    provenance=p.provenance(), queue_policy='unbounded FIFO; no cap/drop',
                    system_changes='NONE', clock='Edge time.monotonic_ns'))

        def worker():
            backend = None
            try:
                backend = backend_factory()
                for i in range(50):
                    stamps, _ = backend.process(backend.payloads[i % len(backend.payloads)])
                    warmup.append(dict(warmup_index=i, **stamps))
                shared['backend'] = backend.info()
                shared['warmup_inferences'] = len(warmup)
                ready.set()
                while not stop.is_set():
                    try:
                        entry = incoming.get(timeout=0.2)
                    except queue.Empty:
                        continue
                    if entry is None:
                        break
                    rid, raw, stamp = entry
                    stamp['queue_start_ns'] = time.monotonic_ns()
                    timing, payload = backend.process(raw)
                    stamp.update(timing)
                    stamp['raw_sha256'] = hashlib.sha256(raw).hexdigest()
                    shared['completed'] += 1
                    row = stamp
                    p.send_message(conn, p.RESPONSE, rid, stamp, payload)
                    row['response_send_complete_ns'] = time.monotonic_ns()
                    shared['responses_sent'] += 1
            except BaseException:
                fail()
            finally:
                shared['cleanup_started'] = True
                try:
                    if backend is not None:
                        backend.close()
                    shared['cleanup_completed'] = backend is not None
                except BaseException:
                    fail()
                ready.set()

        thread = threading.Thread(target=worker, name='edge-inference-C1')
        thread.start()
        ready.wait()
        if errors:
            raise RuntimeError('worker preflight/warmup failed')
        p.send_message(conn, p.READY, metadata=dict(backend=shared['backend'], warmup_inferences=50,
                                                  run_id=hello['run_id'], queue_cap=None))
        seen = set()
        while not stop.is_set():
            kind, rid, meta, raw = p.recv_message(conn)
            received_ns = time.monotonic_ns()
            if kind == p.END:
                if meta.get('submitted') != count or len(seen) != count:
                    raise ValueError('END accounting mismatch')
                shared['end_received'] = True
                incoming.put(None)
                break
            if kind != p.REQUEST or not 0 <= rid < count:
                raise ValueError('unexpected request kind/id')
            if rid in seen:
                shared['duplicates'] += 1
                raise ValueError('duplicate request')
            seen.add(rid)
            shared['received'] += 1
            stamp = dict(request_id=rid, receive_complete_ns=received_ns,
                         queue_enter_ns=time.monotonic_ns())
            rows.append(stamp)  # Preserve received-but-unfinished requests on worker failure.
            incoming.put((rid, raw, stamp))
            shared['queue_peak_observed'] = max(shared['queue_peak_observed'], incoming.qsize())
    except BaseException:
        fail()
    finally:
        if errors:
            stop.set()
        incoming.put(None)
        if thread is not None:
            thread.join()  # Natural drain; no timeout that silently drops admitted requests.
        for name, data in [('requests.csv', rows), ('warmup.csv', warmup)]:
            with (output / name).open('x', newline='') as f:
                if data:
                    fields = sorted({key for row in data for key in row})
                    writer = csv.DictWriter(f, fieldnames=fields)
                    writer.writeheader()
                    writer.writerows(data)
        valid = (not errors and shared['cleanup_completed'] and shared['end_received']
                 and shared['received'] == shared['completed'] == shared['responses_sent'])
        summary = dict(**shared, errors=errors, integrity_status='VALID' if valid else 'INVALID',
                       drain_completed=valid, worker_thread_exited=thread is None or not thread.is_alive())
        p.save(output / 'summary.json', summary)
        (output / 'stderr.log').write_text('\n'.join(errors))
    if summary['integrity_status'] == 'VALID':
        p.send_message(conn, p.FINAL, metadata=summary)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', choices=['smoke', 'campaign'], required=True)
    parser.add_argument('--engine', required=True)
    parser.add_argument('--cache', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--host', default='0.0.0.0')
    args = parser.parse_args()
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=False)
    try:
        helpers = p.load_runtime_helpers()
        gpu = helpers.validate_edge(args)
        helpers.load_cache(args.cache)
        order = [(0, 8)] if args.mode == 'smoke' else p.ORDER
        p.save(out / 'campaign_manifest.json', dict(mode=args.mode, order=order, port=p.PORT,
                  gpu_preflight=gpu, provenance=p.provenance(), engine_path=str(Path(args.engine).resolve()),
                  cache_path=str(Path(args.cache).resolve()), warmup_per_session=50,
                  C_E=1, B=1, CUDA_Graph=False, dynamic_batching=False))
        results = []
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.bind((args.host, p.PORT))
            listener.listen(1)
            print(f'LISTENING {args.host}:{p.PORT}; mode={args.mode}', flush=True)
            for index, (repeat, rate) in enumerate(order):
                expected = dict(mode=args.mode, repeat=repeat, rate=rate,
                                seconds=10 if args.mode == 'smoke' else 60,
                                run_id=f'{args.mode}_{index+1:02d}')
                with listener.accept()[0] as conn:
                    # Administrative broken-peer timeout; normal active+drain has no retry.
                    conn.settimeout(300)
                    result = serve_session(conn, out / expected['run_id'], expected, lambda: Backend(args))
                    results.append(dict(run_id=expected['run_id'], integrity_status=result['integrity_status']))
                    print(expected['run_id'], result['integrity_status'], flush=True)
        p.save(out / 'campaign_status.json', dict(planned=len(order), completed=len(results), runs=results))
        return 0 if all(r['integrity_status']=='VALID' for r in results) else 1
    except BaseException:
        p.save(out / 'server_failure.json', dict(traceback=traceback.format_exc()))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
