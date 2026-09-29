"""CPU-only: actual server session path over AF_UNIX socketpair, never TCP/GPU."""
import json
import inspect
import queue
import sys
import tempfile
import threading
import time
import types
from pathlib import Path

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
sys.path.insert(0,str(ROOT/'results/timely_capacity_campaign/v2_2/edge_e48_confirmation01/edge_bundle'))
import formal_protocol as wire
import edge_server as server
import config
import analyze
import verify_edge_preflight as edge_preflight


class FakeBackend:
    def __init__(self, worker_id, alias=False):
        self.worker_id=worker_id
        self.alias=alias
        self.payloads=[bytes(wire.RAW_BYTES)]

    def process(self, raw):
        a=time.monotonic_ns()
        return ({'preprocess_start_ns':a,'preprocess_end_ns':a+1,
                 'inference_start_ns':a+2,'inference_end_ns':a+3,
                 'response_ready_ns':a+4}, bytes(wire.OUTPUT_BYTES))

    def info(self):
        resource_id=1 if self.alias else self.worker_id+1
        return {'worker_id':self.worker_id,'resources':
                {'context_object_id':resource_id,'cuda_stream_pointer':resource_id}}

    def close(self): pass


class MemoryTransport:
    """In-memory duplex stream; runs real protocol framing without any socket."""
    def __init__(self):
        self.inbox=queue.Queue()
        self.peer=None
        self.buffer=bytearray()
        self.closed=False

    def sendall(self,data):
        if self.closed: raise BrokenPipeError('closed synthetic transport')
        self.peer.inbox.put(bytes(data))

    def recv(self,n):
        while not self.buffer:
            data=self.inbox.get(timeout=10)
            if data is None:return b''
            self.buffer.extend(data)
        result=bytes(self.buffer[:n]);del self.buffer[:n]
        return result

    def shutdown(self,_how):
        self.closed=True
        self.inbox.put(None)
        self.peer.inbox.put(None)

    def close(self):
        self.shutdown(None)


def memory_pair():
    a,b=MemoryTransport(),MemoryTransport()
    a.peer=b;b.peer=a
    return a,b


def exercise_server(c_e, alias=False, wrong_hello=False):
    expected={'mode':'synthetic','run_id':'SYNTHETIC', 'rate':48,'seconds':30,
              'cache_sha256':wire.load_runtime_helpers().CACHE_SHA256,'edge_C':c_e}
    left,right=memory_pair()
    with tempfile.TemporaryDirectory(prefix='edge_c_synth_') as tmp:
        outcome=[]
        def serve():
            try: outcome.append(server.serve_session(left,Path(tmp)/'run',expected,c_e,
                                lambda i:FakeBackend(i,alias)))
            finally: left.close()
        thread=threading.Thread(target=serve)
        thread.start()
        hello=dict(expected)
        if wrong_hello: hello['edge_C']=3
        wire.send_message(right,wire.HELLO,metadata=hello)
        try:
            kind,_,ready,_=wire.recv_message(right)
            if wrong_hello or alias:
                raise AssertionError('Malformed fixture incorrectly received READY')
            assert kind==wire.READY
            assert ready['backend']['C_E']==c_e
            assert ready['backend']['worker_count']==ready['backend']['context_count']==c_e
            assert ready['warmup_inferences']==50*c_e
            for rid in (0,1):
                wire.send_message(right,wire.REQUEST,rid,payload=bytes(wire.RAW_BYTES))
            wire.send_message(right,wire.END,metadata={'assigned':1440,'submitted':2,
                'expired_request_ids':list(range(2,1440))})
            responses=0
            while True:
                kind,rid,meta,payload=wire.recv_message(right)
                if kind==wire.RESPONSE:
                    assert rid in (0,1) and len(payload)==wire.OUTPUT_BYTES
                    responses+=1
                elif kind==wire.FINAL:
                    assert responses==2 and meta['integrity_status']=='VALID'
                    break
                else: raise AssertionError('Unexpected protocol kind')
        except (EOFError,OSError,ConnectionError):
            if not (alias or wrong_hello): raise
        finally:
            right.close();thread.join(timeout=10)
        assert not thread.is_alive()
        assert len(outcome)==1
        assert outcome[0]['integrity_status']==('INVALID' if alias or wrong_hello else 'VALID')
        if not (alias or wrong_hello):
            assert outcome[0]['worker_count']==c_e
            assert outcome[0]['context_count']==c_e
            assert outcome[0]['warmup_inferences']==50*c_e
            assert outcome[0]['active_concurrency']['peak']<=c_e
        return outcome[0]['integrity_status']


def stage_gate_tests():
    plan=config.load_plan();digest=config.sha(config.PLAN)
    for stage in (2,3):
        prior=plan['stages'][stage-2]
        current=plan['stages'][stage-1]
        attempt={'plan_sha256':digest}
        previous={'status':'STAGE_COMPLETE_WAITING_FOR_EDGE_RESTART',
                  'stage':stage-1,'C_E':prior['C_E'],'run_ids':prior['run_ids'],
                  'monotonic_ns':100}
        listener={'status':'PASS','stage':str(stage),'expected_C_E':current['C_E'],
                  'bundle_sha256':plan['bundle_sha256'],'monotonic_ns':101}
        assert __import__('run_thor').validate_stage_continuation(stage,plan,attempt,previous,listener)
        for wrong in ({**listener,'expected_C_E':1 if current['C_E']==2 else 2},
                      {**listener,'status':'MISSING'},
                      {**listener,'monotonic_ns':99},
                      {**listener,'bundle_sha256':'wrong'}):
            try: __import__('run_thor').validate_stage_continuation(stage,plan,attempt,previous,wrong)
            except RuntimeError as exc: assert 'STAGE_CONTINUATION_BLOCKED' in str(exc)
            else: raise AssertionError('Malformed continuation accepted')
    return 'PASS'


def decision_tests():
    base=[{'C_E':c,'pattern':p,'repeat':j,'integrity_status':'VALID',
           'overall_TIR':(.7 if c==1 and p=='ALIGNED' else .85 if c==2 and p=='ALIGNED' else .99)}
          for c in (1,2) for p in ('ALIGNED','STAGGERED') for j in (1,2)]
    assert analyze.verdict(base)['primary_verdict']=='EDGE_BURST_CONCURRENCY_SENSITIVE'
    for r in base:
        if r['C_E']==2 and r['pattern']=='ALIGNED':r['overall_TIR']=.79
    assert analyze.verdict(base)['primary_verdict']=='EDGE_BURST_CONCURRENCY_ROBUST'
    for r in base:
        if r['C_E']==2 and r['pattern']=='ALIGNED' and r['repeat']==1:r['overall_TIR']=.81
    assert analyze.verdict(base)['primary_verdict']=='EDGE_C_REPEAT_AMBIGUOUS'
    return 'PASS'


def backend_binding_test():
    """Exercise the actual production factory with CPU stubs, not FakeBackend injection."""
    source=inspect.getsource(server.BackendFactory._initialize)
    assert source.index('import tensorrt as trt') < source.index('self.helpers.trt = trt')
    fake=types.ModuleType('tensorrt')
    fake.__version__='CPU_STUB'
    fake.Logger=lambda level: object()
    fake.Logger.ERROR=1
    fake.init_libnvinfer_plugins=lambda logger,namespace:None
    engine=types.SimpleNamespace(num_aux_streams=0)
    fake.Runtime=lambda logger:types.SimpleNamespace(deserialize_cuda_engine=lambda data:engine)
    seen=[]
    helper=types.SimpleNamespace(validate_edge=lambda args:{},load_cache=lambda cache:([bytes(wire.RAW_BYTES)],[0]),
                                 ENGINE_SHA256='stub',CACHE_SHA256='stub')
    class Worker:
        def __init__(self,received_engine,worker_id):
            assert helper.trt is fake and received_engine is engine
            seen.append(worker_id)
            self.worker_id=worker_id
        def bind_thread(self):pass
        def close(self):pass
    helper.ContextWorker=Worker
    previous_module=sys.modules.get('tensorrt')
    previous_loader=server.wire.load_runtime_helpers
    try:
        sys.modules['tensorrt']=fake
        server.wire.load_runtime_helpers=lambda:helper
        with tempfile.TemporaryDirectory(prefix='edge_factory_binding_') as tmp:
            engine_path=Path(tmp)/'stub.engine';engine_path.write_bytes(b'stub')
            factory=server.BackendFactory(types.SimpleNamespace(engine=engine_path,cache='stub'))
            workers=[factory(i) for i in (0,1)]
            assert seen==[0,1] and helper.trt is fake
            for backend in workers:backend.close()
            factory.close()
    finally:
        server.wire.load_runtime_helpers=previous_loader
        if previous_module is None:sys.modules.pop('tensorrt',None)
        else:sys.modules['tensorrt']=previous_module
    return 'PASS'


def preflight_gate_test():
    plan=config.load_plan()
    old_evidence,old_ready=edge_preflight.EVIDENCE,edge_preflight.READY
    try:
        with tempfile.TemporaryDirectory(prefix='edge_preflight_gate_') as tmp:
            edge_preflight.EVIDENCE=Path(tmp)
            edge_preflight.READY=Path(tmp)/'READY.json'
            try:edge_preflight.require_ready(plan)
            except RuntimeError as exc:assert 'EDGE_PREFLIGHT_REQUIRED' in str(exc)
            else:raise AssertionError('Missing Edge preflight evidence accepted')
            for c in (1,2):
                workers=[]
                for i in range(c):
                    base=1000+c*100+i*10
                    workers.append({'worker_id':i,'warmup_completed':2,'real_inference_completed':1,
                        'finite_expected_output':True,'clean_teardown':True,'resources':{
                        'context_object_id':base,'cuda_stream_pointer':base+1,
                        'device_buffers':{'inputs':base*10,'pred_logits':base*10+1,'pred_boxes':base*10+2},
                        'pinned_host_buffers':{'inputs':base*20,'pred_logits':base*20+1,'pred_boxes':base*20+2}}})
                row={'status':'PASS','campaign':'EDGE_INFLIGHT_ROBUSTNESS02','C_E':c,'B':1,
                    'plan_sha256':config.sha(config.PLAN),'bundle_sha256':plan['bundle_sha256'],
                    'server_source_sha256':plan['edge_dependency_sha256']['edge_server.py'],
                    'engine_sha256':plan['edge_engine_SHA256'],'cache_sha256':plan['cache']['sha256'],
                    'TensorRT_import':'PASS','engine_deserialization':'PASS','helpers_trt_binding':'PASS',
                    'worker_count':c,'context_count':c,'stream_count':c,'no_resource_alias':True,
                    'dtype_mapping':'PASS','warmup_status':'PASS','real_inference_status':'PASS',
                    'output_validity':'PASS','clean_teardown':True,'TensorRT_version':'CPU_STUB',
                    'timestamp_utc':'SYNTHETIC','errors':[],'workers':workers}
                (Path(tmp)/f'edge_preflight_CE{c}.json').write_text(json.dumps(row))
            (Path(tmp)/'edge_preflight_stdout.txt').write_text('PASS C_E=1 Edge-local backend smoke\nPASS C_E=2 Edge-local backend smoke\n')
            digests=edge_preflight.validate_evidence(plan)
            edge_preflight.READY.write_text(json.dumps({'status':'EDGE_INFLIGHT_ROBUSTNESS02_READY_WAITING_FOR_EXECUTION_APPROVAL',
                'plan_sha256':config.sha(config.PLAN),'bundle_sha256':plan['bundle_sha256'],
                'engine_sha256':plan['edge_engine_SHA256'],'evidence_sha256':digests}))
            edge_preflight.require_ready(plan)
            row=json.loads((Path(tmp)/'edge_preflight_CE2.json').read_text());row['B']=2
            (Path(tmp)/'edge_preflight_CE2.json').write_text(json.dumps(row))
            try:edge_preflight.require_ready(plan)
            except RuntimeError:pass
            else:raise AssertionError('Tampered Edge preflight evidence accepted')
    finally:
        edge_preflight.EVIDENCE,edge_preflight.READY=old_evidence,old_ready
    return 'PASS'


def main():
    results={'C_E1_actual_server_path':exercise_server(1),
             'C_E2_actual_server_path':exercise_server(2),
             'malformed_context_alias':'PASS' if exercise_server(2,alias=True)=='INVALID' else 'FAIL',
             'malformed_hello':'PASS' if exercise_server(1,wrong_hello=True)=='INVALID' else 'FAIL',
             'stage_continuation':stage_gate_tests(),'absolute_TIR_rule':decision_tests(),
             'actual_BackendFactory_TensorRT_binding_CPU_stub':backend_binding_test(),
             'real_Edge_preflight_evidence_gate_CPU_synthetic':preflight_gate_test()}
    print(json.dumps(results,indent=2))
    if any(v not in ('VALID','PASS') for v in results.values()):raise SystemExit(2)


if __name__=='__main__':main()
