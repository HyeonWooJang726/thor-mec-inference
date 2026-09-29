"""Synthetic CPU functional regression only; never import experiment/CUDA runtimes."""
import ast
import copy
import ctypes
import json
import math
from pathlib import Path
import queue
import tempfile
import types
from build_adapter import ROOT,BASE_RUN,BASE_TRT,run_source,runtime_source,extract_function
from cuda_events import EventPair
from phase_storage import FIELDS,write_after_join
from analyze_phases import metrics,event_validation,startup_bins


def ast_functions(s):
    return {n.name:ast.dump(n,include_attributes=False) for n in ast.walk(ast.parse(s)) if isinstance(n,ast.FunctionDef)}


class StripInstrumentation(ast.NodeTransformer):
    def visit_ImportFrom(self,node):
        if node.module in ('cuda_events','phase_storage'):return None
        if node.module=='instrumented_local_runtime':node.module='local_concurrency_tensorrt'
        return node
    def visit_Assign(self,node):
        if any(isinstance(x,ast.Name) and x.id.startswith('ph_') for x in ast.walk(node.targets[0])):return None
        if any(isinstance(x,ast.Attribute) and x.attr in ('phase_records','phase_events') for x in node.targets):return None
        return self.generic_visit(node)
    def visit_Expr(self,node):
        if any(isinstance(x,ast.Attribute) and x.attr in ('phase_events','phase_records') for x in ast.walk(node)):return None
        return self.generic_visit(node)
    def visit_If(self,node):
        if isinstance(node.test,ast.Call) and any(isinstance(x,ast.Constant) and x.value=='phase_events' for x in node.test.args):return None
        return self.generic_visit(node)


def static_tests():
    old,new=ast_functions(BASE_RUN.read_text()),ast_functions(run_source())
    unchanged=['front','arrivals','sample_tensor','monitor','checkpoint','save_records','fail']
    assert all(old[k]==new[k] for k in unchanged)
    for name in ['infer']:
        a=ast.parse(extract_function(BASE_RUN.read_text(),name));b=ast.parse(extract_function(run_source(),name))
        b=StripInstrumentation().visit(b)
        assert ast.dump(a,include_attributes=False)==ast.dump(b,include_attributes=False)
    a=ast.parse(BASE_TRT.read_text());b=StripInstrumentation().visit(ast.parse(runtime_source()))
    assert ast.dump(a,include_attributes=False)==ast.dump(b,include_attributes=False)
    # Same lock acquisitions. Inside lock, added statements are scalar clock reads only.
    worker=ast.parse(extract_function(run_source(),'infer'))
    for node in ast.walk(worker):
        if isinstance(node,ast.With) and isinstance(node.items[0].context_expr,ast.Name) and node.items[0].context_expr.id=='lock':
            for stmt in node.body:
                if isinstance(stmt,ast.Assign) and isinstance(stmt.targets[0],ast.Name) and stmt.targets[0].id.startswith('ph_'):
                    assert ast.unparse(stmt.value)=='time.monotonic_ns()'
    return dict(unchanged_functions=unchanged,worker_behavior_AST='identical_after_removing_only_instrumentation',
                TRT_runtime_AST='identical_after_removing_only_instrumentation',new_common_lock_acquisitions=0)


def accounting_types():
    ns={}
    for path,name in [('scripts/local/local_latency_breakdown_metrics.py','QueueAccounting'),('scripts/expired_work_pruning/pruning_common.py','expire'),('scripts/expired_work_pruning/pruning_common.py','PruningAccounting')]:
        tree=ast.parse((ROOT/path).read_text());node=next(x for x in tree.body if isinstance(x,(ast.ClassDef,ast.FunctionDef)) and x.name==name)
        if name=='PruningAccounting':ns['PreviousAccounting']=ns['QueueAccounting']
        exec(compile(ast.Module(body=[node],type_ignores=[]),'<exact-frozen-accounting>','exec'),ns)
    return ns


def worker_fixture(source, pruning=True):
    trace=[];clock=types.SimpleNamespace(value=50,monotonic_ns=lambda:clock.value)
    class Flag:
        def is_set(self):return False
        def set(self):trace.append('warm_ready')
    class Lock:
        def __enter__(self):trace.append('lock_enter')
        def __exit__(self,*args):trace.append('lock_exit')
    class Tensor:
        def __del__(self):trace.append('host_tensor_release')
    class Events:
        def elapsed_after_existing_sync(self):return 4.0,'OK'
    worker=types.SimpleNamespace(phase_records=[],phase_events=Events(),submission_return_ns=100,stream_sync_return_ns=100,
                                 bind_thread=lambda:trace.append('bind_thread'))
    def infer(tensor):trace.append('TRT');return dict(pred_logits=0,pred_boxes=0)
    worker.infer=infer
    nsacct=accounting_types();acct=nsacct['PruningAccounting']()
    if not pruning:
        # Proposed OFF uses same worker and bookkeeping, bypassing only expiry branch.
        # Exact FIFO start is used for the CPU control; not implemented as production runtime.
        def begin(job,clock):nsacct['QueueAccounting'].start(acct,job,clock);return True
        acct.begin=begin
    jobs=[dict(stream_id=i%8,frame_id=i,absolute_deadline_ns=d,tensor=Tensor()) for i,d in enumerate([99,100,101,200,100,101])]
    aq=queue.Queue()
    for j in jobs:acct.enqueue(aq,j,lambda:50)
    class Ready:
        def get(self,timeout):
            try:j=aq.get_nowait()
            except queue.Empty:raise
            clock.value=100;trace.append(('pop',j['frame_id']));return j
    failures=[]
    ns=dict(runtime=types.SimpleNamespace(workers=[worker]),warm_tensor=None,stop=Flag(),warm_ready=[Flag()],
            lock=Lock(),frames=[],ready_queue=Ready(),queue=queue,front_done=[types.SimpleNamespace(is_set=lambda:True)],
            accounting=acct,time=clock,fail=lambda e:failures.append(e),traceback=__import__('traceback'))
    exec(compile(source,'<CPU-only-worker-fixture>','exec'),ns)
    ns['infer'](0)
    assert not failures,failures
    return trace,jobs,acct.events,worker.phase_records


class FakeFunction:
    def __init__(self,fn):self.fn=fn
    def __call__(self,*args):return self.fn(*args)


class FakeCuda:
    def __init__(self):
        self.trace=[];self.next=1;self.ready=False;self.duration=4.0;self.record_error=0;self.elapsed_error=0
        for name,fn in [('cudaEventCreateWithFlags',self.create),('cudaEventRecord',self.record),('cudaEventElapsedTime',self.elapsed),('cudaEventDestroy',self.destroy),('cudaMemcpyAsync',self.copy),('cudaStreamSynchronize',self.sync)]:setattr(self,name,FakeFunction(fn))
    def create(self,p,flags):p._obj.value=self.next;self.next+=1;self.trace.append('event_create');return 0
    def record(self,e,stream):assert stream.value==7;self.ready=False;self.trace.append('event_record');return self.record_error
    def elapsed(self,p,a,b):
        self.trace.append('event_elapsed')
        if not self.ready:return 600  # Fake not-ready: proves no query-triggered completion.
        p._obj.value=self.duration;return self.elapsed_error
    def destroy(self,e):self.trace.append('event_destroy');return 0
    def copy(self,*args):self.trace.append('memcpy');return 0
    def sync(self,*args):self.ready=True;self.trace.append('existing_stream_sync');return 0


def runtime_tests():
    cuda=FakeCuda();pair=EventPair(cuda,ctypes.c_void_p(7));pair.begin();pair.finish()
    assert pair.elapsed_after_existing_sync()==(None,'ELAPSED_FAILED')
    assert cuda.trace.count('existing_stream_sync')==0
    cuda.sync();assert pair.elapsed_after_existing_sync()==(4.0,'OK')
    for v,status in [(0,'ZERO'),(-1,'INVALID_ELAPSED'),(float('nan'),'INVALID_ELAPSED')]:
        cuda.duration=v;assert pair.elapsed_after_existing_sync()[1]==status
    cuda.duration=4;cuda.record_error=9;pair.begin();pair.finish();assert pair.elapsed_after_existing_sync()==(None,'RECORD_FAILED')
    pair.close_after_existing_sync();assert cuda.trace.count('event_create')==2 and cuda.trace.count('event_destroy')==2
    traces=[]
    for source in [BASE_TRT.read_text(),runtime_source()]:
        cuda=FakeCuda();events=EventPair(cuda,ctypes.c_void_p(7));cuda.trace=[]
        fake_np=types.SimpleNamespace(float32='f32',copyto=lambda *a:cuda.trace.append('host_copy'))
        tensor=types.SimpleNamespace(dtype='f32',shape=(1,3,640,640),flags=types.SimpleNamespace(c_contiguous=True))
        obj=types.SimpleNamespace(owner_thread=1,host={'inputs':0},host_ptrs={'inputs':0,'pred_logits':1,'pred_boxes':2},device={'inputs':0,'pred_logits':1,'pred_boxes':2},sizes={'inputs':1,'pred_logits':1,'pred_boxes':1},outputs={'pred_logits':0,'pred_boxes':0},stream=ctypes.c_void_p(7),cuda=cuda,phase_events=events,
            check=lambda code,operation:None,context=types.SimpleNamespace(execute_async_v3=lambda **kw:(cuda.trace.append('execute_async_v3') or True)))
        ns=dict(np=fake_np,threading=types.SimpleNamespace(get_ident=lambda:1),time=types.SimpleNamespace(perf_counter_ns=lambda:100))
        exec(compile(extract_function(source,'infer'),'<CPU-fake-TRT>','exec'),ns);ns['infer'](obj,tensor)
        traces.append(cuda.trace[:])
        if 'event_record' in cuda.trace:
            assert events.elapsed_after_existing_sync()==(4.0,'OK')
            assert cuda.trace.index('event_record')<cuda.trace.index('execute_async_v3')
            assert max(i for i,x in enumerate(cuda.trace) if x=='event_record')<cuda.trace.index('existing_stream_sync')
    assert traces[0]==[x for x in traces[1] if x!='event_record']
    return dict(fake_TRT_call_trace=traces,original_sync_count=1,instrumented_sync_count=1,events_reused=True,
                not_ready_does_not_poll_or_wait=True,error_negative_NaN_zero_preserved=True,GPU_validation=False)


def main():
    result=dict(static=static_tests(),runtime=runtime_tests())
    traces=[]
    for on in [True,False]:
        old=worker_fixture(extract_function(BASE_RUN.read_text(),'infer'),on)
        new=worker_fixture(extract_function(run_source(),'infer'),on)
        assert old[:3]==new[:3]
        assert len(new[3])==6 and all(len(r)==len(FIELDS) for r in new[3])
        assert len({(r[0],r[1]) for r in new[3]})==6
        assert [r[2] for r in new[3]].count('EXPIRED_DROP')==(3 if on else 0)
        traces.append(dict(pruning=on,behavior_equal=True,dispositions=[r[2] for r in new[3]],same_legacy_timestamps=True))
    result['worker_fixtures']=traces
    sample=dict(zip(FIELDS,new[3][0]));sample.update(t_pre_infer=10_000_000,t_infer_return=18_000_000,gpu_exec_duration_ms=4.0,gpu_event_status='OK')
    assert metrics(sample)['host_wakeup_delay_ms']==4
    assert event_validation([sample])['status']=='PASS'
    for value in [-1,float('nan'),0,None]:assert event_validation([dict(sample,gpu_exec_duration_ms=value)])['status']=='INCONCLUSIVE'
    # Exact 100ms integrated concurrency and queue, including a boundary-crossing interval.
    row=dict(phase='active',stream_id=0,frame_id=0,placement='LOCAL',ready_timestamp_ns=0,inference_start_timestamp_ns=50_000_000,completion_timestamp_ns=150_000_000,expired_drop_ns='',absolute_deadline_ns=100_000_000)
    ph=dict(sample,service_start=50_000_000,service_end=150_000_000)
    bins=startup_bins([ph],[row],0);assert len(bins)==30
    assert bins[0]['host_active_concurrency_mean']==bins[1]['host_active_concurrency_mean']==.5
    assert bins[1]['local_completed_count']==bins[1]['local_late_count']==1
    assert bins[0]['conceptual_local_waiting_queue_mean']==.5
    assert bins[0]['gpu_exec_duration_ms_p95'] is None
    # Real CSV cells arrive as strings; retain arithmetic behavior after serialization.
    csv_ph = {k: str(v) if v is not None else '' for k, v in ph.items()}
    assert startup_bins([csv_ph], [row], 0) == bins
    # Independent storage and post-join CSV output; no append/overwrite of an old file.
    scratch = Path(tempfile.mkdtemp(prefix='service_phase_CPU_storage_'))
    workers = [types.SimpleNamespace(worker_id=i, phase_records=[tuple(new[3][i])],
               phase_events=types.SimpleNamespace(create_code=0,record_calls=2,
                                                  record_errors=0,elapsed_calls=1)) for i in range(2)]
    assert workers[0].phase_records is not workers[1].phase_records
    write_after_join(scratch, workers)
    import csv
    with (scratch/'per_frame_phase_timestamps.csv').open() as stream:
        written=list(csv.DictReader(stream))
    assert len(written)==2 and {r['worker_id'] for r in written}=={'0','1'}
    try:write_after_join(scratch,workers)
    except FileExistsError:pass
    else:raise AssertionError('Existing output must not be overwritten')
    result.update(status='PASS',CPU_only=True,GPU=False,network=False,frequency=False,
                  timestamp_equivalence_scope='synthetic fixed-clock inputs; no claim of identical real wall-clock decisions near deadline',
                  source_admission_placement='same untouched front/arrivals/decorate bindings; no new policy',
                  phase_storage='worker-owned scalar tuples; no job/tensor references',startup_100ms_fixture='PASS',
                  CSV_string_roundtrip='PASS',private_storage_and_no_overwrite='PASS',CPU_scratch=str(scratch))
    print(json.dumps(result,indent=2))

if __name__=='__main__':main()
