"""Frozen-stage RAW640 Edge server: independent B=1 TensorRT jobs, C_E workers.

Each process serves one preregistered stage and exits. No dynamic pool rebuild.
GPU resources are created, used, and destroyed on their owning worker thread.
"""
import argparse
import csv
import hashlib
import json
import queue
import socket
import threading
import time
import traceback
from pathlib import Path

import formal_protocol as wire
from pruning_edge_server import partition_end


def expected_hello(c, digest, cache_sha):
    return {'mode':'edge_inflight_robustness02', 'rate':48, 'seconds':30,
            'repeat':c['repeat'], 'run_id':c['run_id'], 'campaign_plan_sha256':digest,
            'cache_sha256':cache_sha,
            'payload_origin':'CACHED_REAL_RAW640_30; K8_30FPS_SOURCE_SLOT_SELECTION',
            'deadline_ms':100, 'admission_pattern':c['pattern'],
            'phase_vector':c['phase_vector'], 'stage':'MEASURED', 'edge_C':c['edge_C']}


def concurrency(rows):
    events=[]
    for row in rows:
        if 'queue_start_ns' in row and 'response_ready_ns' in row:
            events.extend(((row['queue_start_ns'],1),(row['response_ready_ns'],-1)))
    if not events:
        return {'mean':0.0,'p95':0.0,'peak':0}
    level=peak=area=0
    weighted=[]
    prior=min(stamp for stamp,_ in events)
    for stamp,delta in sorted(events):
        span=stamp-prior
        if span>0:
            weighted.append((level,span)); area+=level*span
        level+=delta
        peak=max(peak,level)
        prior=stamp
    total=sum(span for _,span in weighted)
    cutoff=.95*total
    elapsed=0
    p95=0
    for value,span in sorted(weighted):
        elapsed+=span
        if elapsed>=cutoff:
            p95=value;break
    return {'mean':area/total if total else 0.0,'p95':p95,'peak':peak}


class BackendFactory:
    """One frozen engine per session, independent contexts/streams per worker."""
    def __init__(self, args):
        self.args=args
        self.lock=threading.Lock()
        self.runtime=self.engine=None
        self.helpers=None

    def __call__(self, worker_id):
        with self.lock:
            if self.engine is None:
                self._initialize()
            # Context construction is serialized on the shared TensorRT engine;
            # each ContextWorker is still bound/used/destroyed by its owner thread.
            return Backend(self,worker_id)

    def _initialize(self):
        import tensorrt as trt
        self.helpers=wire.load_runtime_helpers()
        # ContextWorker resolves `trt` from the helpers module, not this local scope.
        # Match the frozen formal_server.Backend initialization before any worker exists.
        self.helpers.trt = trt
        self.gpu=self.helpers.validate_edge(self.args)
        self.payloads,self.ids=self.helpers.load_cache(self.args.cache)
        self.trt_version = trt.__version__
        self.logger = trt.Logger(trt.Logger.ERROR)
        trt.init_libnvinfer_plugins(self.logger, '')
        self.runtime = trt.Runtime(self.logger)
        self.engine = self.runtime.deserialize_cuda_engine(Path(self.args.engine).read_bytes())
        if self.engine is None:
            raise RuntimeError('engine deserialize failed')

    def close(self):
        self.engine=None
        self.runtime=None


class Backend:
    """The frozen ContextWorker, one execution context/stream per owning thread."""
    def __init__(self, shared, worker_id):
        self.shared=shared
        self.helpers=shared.helpers
        self.payloads=shared.payloads
        self.worker=self.helpers.ContextWorker(shared.engine,worker_id)
        self.worker.bind_thread()

    def process(self, raw):
        stamps = {'preprocess_start_ns':time.monotonic_ns()}
        tensor = self.helpers.remaining_preprocess(raw)
        stamps['preprocess_end_ns'] = time.monotonic_ns()
        stamps['inference_start_ns'] = time.monotonic_ns()
        outputs = self.worker.infer(tensor)
        stamps['inference_end_ns'] = time.monotonic_ns()
        data = wire.encode_outputs(outputs)
        stamps['response_ready_ns'] = time.monotonic_ns()
        return stamps, data

    def info(self):
        return {'worker_id':self.worker.worker_id, 'resources':self.worker.resources(),
                'TensorRT':self.shared.trt_version, 'engine_aux_streams':self.shared.engine.num_aux_streams,
                'engine_sha256':self.helpers.ENGINE_SHA256,
                'cache_sha256':self.helpers.CACHE_SHA256}

    def close(self):
        self.worker.close()
        self.worker = None


def serve_session(conn, output, expected, c_e, backend_factory):
    """Actual production receive/queue/infer/response/finalization path.

    backend_factory injection is only for CPU protocol regression; CLI binds
    the real TensorRT Backend. The same serve_session executes in both paths.
    """
    output = Path(output)
    if c_e not in (1,2) or expected.get('edge_C') != c_e:
        raise ValueError('Frozen C_E/session configuration mismatch')
    output.mkdir(parents=True, exist_ok=False)
    incoming = queue.Queue()
    stop = threading.Event()
    send_lock = threading.Lock()
    accounting_lock = threading.Lock()
    constructed = threading.Barrier(c_e)
    ready = threading.Barrier(c_e + 1)
    errors, rows, warmup, resources = [], [], [], []
    shared = dict(received=0, completed=0, responses_sent=0, duplicates=0,
                  queue_peak_observed=0, queue_cap_saturation=False, drops=0,
                  cleanup_started=False, cleanup_completed=False, end_received=False)
    threads = []

    def fail(exc):
        with accounting_lock:
            errors.append(repr(exc) + '\n' + traceback.format_exc())
        stop.set()
        try: constructed.abort()
        except threading.BrokenBarrierError: pass
        try: ready.abort()
        except threading.BrokenBarrierError: pass
        try: conn.shutdown(socket.SHUT_RDWR)
        except OSError: pass

    def worker(worker_id):
        backend = None
        try:
            backend = backend_factory(worker_id)
            constructed.wait(timeout=300)  # All contexts exist before any warmup/inference.
            for index in range(50):
                stamps, _ = backend.process(backend.payloads[index % len(backend.payloads)])
                with accounting_lock:
                    warmup.append({'worker_id':worker_id, 'warmup_index':index, **stamps})
            with accounting_lock:
                resources.append(backend.info())
            ready.wait(timeout=300)
            while not stop.is_set():
                try: entry = incoming.get(timeout=0.2)
                except queue.Empty: continue
                if entry is None:
                    break
                rid, raw, stamp = entry
                stamp['worker_id'] = worker_id
                stamp['queue_start_ns'] = time.monotonic_ns()
                stamps, payload = backend.process(raw)
                stamp.update(stamps)
                stamp['raw_sha256'] = hashlib.sha256(raw).hexdigest()
                with send_lock:
                    with accounting_lock:
                        shared['completed'] += 1
                    wire.send_message(conn, wire.RESPONSE, rid, stamp, payload)
                    stamp['response_send_complete_ns'] = time.monotonic_ns()
                    with accounting_lock:
                        shared['responses_sent'] += 1
        except BaseException as exc:
            fail(exc)
        finally:
            with accounting_lock: shared['cleanup_started'] = True
            if backend is not None:
                try: backend.close()
                except BaseException as exc: fail(exc)

    try:
        kind, _, hello, _ = wire.recv_message(conn)
        if kind != wire.HELLO or any(hello.get(k) != v for k,v in expected.items()):
            raise ValueError('HELLO/session mismatch')
        helpers = wire.load_runtime_helpers()
        if hello.get('cache_sha256') != helpers.CACHE_SHA256:
            raise ValueError('cache SHA mismatch')
        count = 48 * 30
        wire.save(output/'manifest.json', {'client_hello':hello, 'expected':expected,
                  'queue_policy':'unbounded FIFO; no cap/drop', 'B':1, 'C_E':c_e,
                  'clock':'Edge time.monotonic_ns'})
        threads = [threading.Thread(target=worker, args=(i,), name=f'edge-inference-C{c_e}-{i}')
                   for i in range(c_e)]
        for thread in threads: thread.start()
        ready.wait(timeout=300)
        if errors or len(resources) != c_e or len(warmup) != 50*c_e:
            raise RuntimeError('worker/context/warmup cardinality mismatch')
        ids = [r['resources']['context_object_id'] for r in resources]
        streams = [r['resources']['cuda_stream_pointer'] for r in resources]
        if len(set(ids)) != c_e or len(set(streams)) != c_e or \
                sorted(r['worker_id'] for r in resources) != list(range(c_e)):
            raise RuntimeError('worker/context/stream alias or cardinality mismatch')
        backend = {'C_E':c_e, 'B':1, 'CUDA_Graph':False, 'dynamic_batching':False,
                   'engine_sha256':helpers.ENGINE_SHA256, 'cache_sha256':helpers.CACHE_SHA256,
                   'color_conversion':'numpy_channel_reverse_BGR_to_RGB',
                   'worker_count':len(resources), 'context_count':len(ids),
                   'workers':resources}
        wire.send_message(conn, wire.READY, metadata={'backend':backend,
                          'warmup_inferences':50*c_e, 'run_id':hello['run_id'], 'queue_cap':None})
        seen = set()
        while not stop.is_set():
            kind, rid, meta, raw = wire.recv_message(conn)
            receive_ns = time.monotonic_ns()
            if kind == wire.END:
                expired = partition_end(meta, seen, count)
                shared.update(expired_request_ids=expired,
                              client_expired_before_submission=len(expired), assigned=count,
                              end_received=True)
                break
            if kind != wire.REQUEST or not 0 <= rid < count:
                raise ValueError('unexpected request kind/id')
            if rid in seen:
                shared['duplicates'] += 1
                raise ValueError('duplicate request ID')
            seen.add(rid)
            stamp = {'request_id':rid, 'receive_complete_ns':receive_ns,
                     'queue_enter_ns':time.monotonic_ns()}
            rows.append(stamp)
            with accounting_lock: shared['received'] += 1
            incoming.put((rid, raw, stamp))
            shared['queue_peak_observed'] = max(shared['queue_peak_observed'], incoming.qsize())
    except BaseException as exc:
        fail(exc)
    finally:
        for _ in threads: incoming.put(None)
        for thread in threads: thread.join(timeout=300)
        if hasattr(backend_factory,'close') and all(not t.is_alive() for t in threads):
            try: backend_factory.close()
            except BaseException as exc: fail(exc)
        shared['cleanup_completed'] = len(threads) == c_e and all(not t.is_alive() for t in threads)
        for name, values in [('requests.csv',rows),('warmup.csv',warmup)]:
            with (output/name).open('x',newline='') as stream:
                if values:
                    fields=sorted({key for row in values for key in row})
                    writer=csv.DictWriter(stream,fieldnames=fields)
                    writer.writeheader(); writer.writerows(values)
        valid = (not errors and shared['cleanup_completed'] and shared['end_received']
                 and shared['received'] == shared['completed'] == shared['responses_sent']
                 and len(resources) == c_e)
        summary = {**shared, 'errors':errors, 'integrity_status':'VALID' if valid else 'INVALID',
                   'drain_completed':valid, 'worker_thread_exited':all(not t.is_alive() for t in threads),
                   'worker_count':len(resources), 'context_count':len(resources),
                   'warmup_inferences':len(warmup), 'configured_C_E':c_e,
                   'backend_workers':resources, 'active_concurrency':concurrency(rows)}
        if summary['active_concurrency']['peak']>c_e:
            summary['integrity_status']='INVALID'
            summary['errors'].append('active concurrency exceeded configured C_E')
            summary['drain_completed']=False
        wire.save(output/'summary.json',summary)
        (output/'stderr.log').write_text('\n'.join(errors))
    if summary['integrity_status'] == 'VALID':
        wire.send_message(conn, wire.FINAL, metadata=summary)
    return summary


def main():
    parser=argparse.ArgumentParser()
    for name in ('plan','session-plan','engine','cache','output','approve-plan-sha256'):
        parser.add_argument('--'+name,required=True)
    parser.add_argument('--stage', type=int, choices=(1,2,3), required=True)
    args=parser.parse_args()
    plan_path=Path(args.plan)
    digest=wire.sha(plan_path)
    if digest != args.approve_plan_sha256:
        raise RuntimeError('Exact frozen plan SHA required')
    plan=json.loads(plan_path.read_text())
    session_path=Path(args.session_plan)
    session=json.loads(session_path.read_text())
    if wire.sha(session_path)!=plan['session_plan_sha256'] or session['order']!=plan['order']:
        raise RuntimeError('Frozen session plan drift')
    for name, expected in plan['edge_dependency_sha256'].items():
        if wire.sha(Path(__file__).with_name(name))!=expected:
            raise RuntimeError('Frozen Edge source drift: '+name)
    stage=plan['stages'][args.stage-1]
    c_e=stage['C_E']
    order=session['order'][stage['start_index']:stage['end_index']]
    if [r['run_id'] for r in order]!=stage['run_ids'] or any(r['edge_C']!=c_e for r in order):
        raise RuntimeError('Wrong stage/C_E binding')
    output=Path(args.output)
    output.mkdir(parents=True,exist_ok=False)
    try:
        helpers=wire.load_runtime_helpers()
        gpu=helpers.validate_edge(args)
        helpers.load_cache(args.cache)
        wire.save(output/'campaign_manifest.json', {'plan_sha256':digest,'stage':args.stage,
                 'C_E':c_e,'B':1,'sessions':stage['run_ids'],'GPU_preflight':gpu,
                 'worker_count_expected':c_e,'context_count_expected':c_e,
                 'server_code':'edge_server.serve_session + frozen ContextWorker'})
        results=[]
        with socket.socket(socket.AF_INET,socket.SOCK_STREAM) as listener:
            listener.bind(('0.0.0.0',5000));listener.listen(1)
            print(f'LISTENING 5000: {len(order)} STAGE{args.stage} C_E={c_e} sessions',flush=True)
            for c in order:
                with listener.accept()[0] as conn:
                    conn.settimeout(300)
                    result=serve_session(conn,output/c['run_id'],
                        expected_hello(c,digest,helpers.CACHE_SHA256),c_e,
                        BackendFactory(args))
                results.append({'run_id':c['run_id'],'integrity_status':result['integrity_status']})
                print(results[-1],flush=True)
                if result['integrity_status']!='VALID': break
        wire.save(output/'campaign_status.json',{'planned':len(order),'completed':len(results),
                  'runs':results})
        return 0 if len(results)==len(order) and all(r['integrity_status']=='VALID' for r in results) else 1
    except BaseException:
        wire.save(output/'failure.json',{'traceback':traceback.format_exc()})
        return 1


if __name__=='__main__':
    raise SystemExit(main())
