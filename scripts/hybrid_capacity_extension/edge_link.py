"""Live-frame adapter for the immutable RAW640 formal wire protocol."""
import hashlib
import socket
import struct
import threading
import time
import traceback

from hybrid_common import wire as p, edge_runtime, hello

EDGE_KEYS = ('receive_complete_ns','queue_enter_ns','queue_start_ns','preprocess_start_ns',
             'preprocess_end_ns','inference_start_ns','inference_end_ns','response_ready_ns')


class EdgeLink:
    def __init__(self, condition, run_id, manifest, directory, fail, plan_sha, host,
                 transport=None):
        self.manifest, self.directory, self.fail = manifest, directory, fail
        self.count = int(condition['seconds']*40)
        self.stop, self.done = threading.Event(), threading.Event()
        self.cv = threading.Condition()
        self.pending, self.rows = {}, {}
        self.finished = False
        self.final, self.errors, self.threads = {}, [], []
        self.submitted = 0
        self.conn = transport
        try:
            if self.conn is None:
                self.conn = socket.create_connection((host, 5000), timeout=300)
            h = hello(condition, run_id, plan_sha)
            p.send_message(self.conn, p.HELLO, metadata=h)
            kind, _, ready, _ = p.recv_message(self.conn)
            backend = ready.get('backend', {})
            if (kind != p.READY or ready.get('run_id') != run_id or ready.get('warmup_inferences') != 50
                    or backend.get('C_E') != 1 or backend.get('B') != 1
                    or backend.get('CUDA_Graph') is not False or backend.get('dynamic_batching') is not False
                    or backend.get('engine_sha256') != edge_runtime.ENGINE_SHA256
                    or backend.get('cache_sha256') != edge_runtime.CACHE_SHA256
                    or backend.get('color_conversion') != 'numpy_channel_reverse_BGR_to_RGB'):
                raise RuntimeError('Edge READY/configuration mismatch')
            manifest['edge_ready'] = ready
            p.save(directory/'edge_ready.json', ready)
            self.threads = [threading.Thread(target=self.sender, name='hybrid-edge-sender'),
                            threading.Thread(target=self.receiver, name='hybrid-edge-receiver')]
            for t in self.threads: t.start()
        except BaseException:
            if self.conn is not None:
                try: self.conn.close()
                except OSError: pass
            raise

    def error(self):
        message = traceback.format_exc()
        self.errors.append(message)
        self.fail('Edge path: '+message)
        self.stop.set()
        with self.cv: self.cv.notify_all()
        try: self.conn.shutdown(socket.SHUT_RDWR)
        except OSError: pass

    def put(self, row, raw):
        if len(raw) != p.RAW_BYTES: raise ValueError('RAW640 length mismatch')
        rid = int(row['edge_request_id'])
        row['payload_sha256'] = hashlib.sha256(raw).hexdigest()
        row['payload_ready_ns'] = time.monotonic_ns()
        row['r_ns'] = row['payload_ready_ns']  # diagnostic ready, never a Local GPU enqueue
        with self.cv:
            if rid in self.rows: raise ValueError('duplicate Edge placement')
            self.rows[rid] = row
            self.pending[rid] = (row, raw)
            self.cv.notify_all()

    def finish(self):
        with self.cv:
            self.finished = True
            self.cv.notify_all()

    def sender(self):
        try:
            for rid in range(self.count):
                with self.cv:
                    self.cv.wait_for(lambda: rid in self.pending or self.finished or self.stop.is_set())
                    if self.stop.is_set(): return
                    if rid not in self.pending: raise RuntimeError('missing live Edge frame at frontend drain')
                    row, raw = self.pending.pop(rid)
                delay = (row['edge_release_target_ns']-time.monotonic_ns())/1e9
                if delay > 0 and self.stop.wait(delay): return
                row['socket_submission_ns'] = time.monotonic_ns()
                p.send_message(self.conn, p.REQUEST, rid, payload=raw)
                row['socket_send_complete_ns'] = time.monotonic_ns()
                self.submitted += 1
            p.send_message(self.conn, p.END, metadata={'submitted':self.submitted})
        except BaseException: self.error()

    def receiver(self):
        seen = set()
        try:
            with (self.directory/'edge_responses.bin').open('xb') as outputs:
                while not self.stop.is_set():
                    kind, rid, meta, raw = p.recv_message(self.conn)
                    completion = time.monotonic_ns()
                    if kind == p.FINAL:
                        self.final = meta
                        if len(seen) != self.count: raise RuntimeError('early Edge FINAL')
                        if (meta.get('integrity_status') != 'VALID' or not meta.get('cleanup_completed')
                                or not meta.get('drain_completed') or not meta.get('worker_thread_exited')
                                or any(meta.get(k) != self.count for k in ('received','completed','responses_sent'))
                                or meta.get('drops') or meta.get('duplicates') or meta.get('queue_cap_saturation')):
                            raise RuntimeError('invalid Edge final accounting/cleanup')
                        break
                    if kind != p.RESPONSE or rid in seen or rid not in self.rows:
                        raise RuntimeError('unexpected/duplicate Edge response ID')
                    row = self.rows[rid]
                    p.decode_outputs(raw)
                    if meta.get('raw_sha256') != row['payload_sha256']:
                        raise RuntimeError('live RAW640 wire SHA mismatch')
                    if any(type(meta.get(k)) is not int for k in EDGE_KEYS):
                        raise RuntimeError('missing Edge timestamps')
                    row.update({'edge_'+k:meta[k] for k in EDGE_KEYS})
                    row['raw_sha256'] = meta['raw_sha256']
                    row['response_completion_ns'] = row['c_ns'] = completion
                    outputs.write(struct.pack('!Q',rid)+raw)
                    seen.add(rid)
        except BaseException: self.error()
        finally:
            self.manifest['edge_final'] = self.final
            self.done.set()

    def close(self):
        self.stop.set()
        with self.cv: self.cv.notify_all()
        try: self.conn.shutdown(socket.SHUT_RDWR)
        except OSError: pass
        for t in self.threads: t.join(6)
        self.conn.close()
        self.manifest['edge_threads_exited'] = all(not t.is_alive() for t in self.threads)
        self.manifest['edge_final'] = self.final
        self.manifest['edge_path_errors'] = self.errors
        if not self.manifest['edge_threads_exited']:
            self.fail('Edge threads did not exit')
        p.save(self.directory/'edge_final.json',self.final)
