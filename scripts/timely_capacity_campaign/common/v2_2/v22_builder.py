"""Exact-anchor source adapter; no device imports/execution."""
import ast
import inspect
import sys
import textwrap
from v22_config import ROOT,b1
rep=b1.build_adapter.replace_one


def event_source():
    s=(ROOT/'scripts/timely_capacity_campaign/common/service_phase_v1/cuda_events.py').read_text()
    s=rep(s,'        self.destroy_codes = []','        self.destroy_codes = []\n        self.last_ms = None\n        self.last_status = 0')
    tree=ast.parse(s)
    method=next(n for n in ast.walk(tree) if isinstance(n,ast.FunctionDef) and n.name=='elapsed_after_existing_sync')
    method.name='record_elapsed_after_existing_sync'
    statuses={'OK':1,'ZERO':2,'CREATE_FAILED':3,'RECORD_FAILED':4,'ELAPSED_FAILED':5,'INVALID_ELAPSED':6}
    class NoTuple(ast.NodeTransformer):
        def visit_Return(self,n):
            assert isinstance(n.value,ast.Tuple) and len(n.value.elts)==2
            value,status=n.value.elts
            if isinstance(status,ast.IfExp):
                code=ast.IfExp(test=status.test,body=ast.Constant(statuses[status.body.value]),orelse=ast.Constant(statuses[status.orelse.value]))
            else:code=ast.Constant(statuses[status.value])
            return [ast.Assign(targets=[ast.Attribute(value=ast.Name(id='self',ctx=ast.Load()),attr='last_ms',ctx=ast.Store())],value=value),
                    ast.Assign(targets=[ast.Attribute(value=ast.Name(id='self',ctx=ast.Load()),attr='last_status',ctx=ast.Store())],value=code),ast.Return(value=None)]
    NoTuple().visit(method);ast.fix_missing_locations(tree)
    return ast.unparse(tree)+'\n'


def trt_source():
    s=(ROOT/'scripts/timely_capacity_campaign/common/service_phase_v1/instrumented_local_runtime.py').read_text()
    s=rep(s,'from cuda_events import EventPair','from v22_events import EventPair\nfrom v22_storage import PhaseBuffer')
    return rep(s,'            self.phase_records = []','            self.phase_records = PhaseBuffer(14400)')


def phase_assign(expired):
    indent='                            ' if expired else '                        '
    values={'stream_id':"job['stream_id']",'frame_id':"job['frame_id']",'terminal_state':'0' if expired else '1',
            't_worker_pop':'ph_pop','t_lock_request':'ph_request','t_lock_acquired':'ph_acquired','t_expiry_check_done':'ph_check_done'}
    if expired:values.update(t_tensor_release_begin='ph_release_begin',t_tensor_release_end='ph_release_end',gpu_event_status='0')
    else:values.update(t_pre_infer='ph_pre',t_infer_return='ph_return',t_bookkeeping_begin='ph_book_begin',t_bookkeeping_end='ph_book_end',
                       service_start="job['s_ns']",service_end="job['c_ns']",gpu_event_status='worker.phase_events.last_status',
                       t_gpu_elapsed_query_begin='ph_query_begin',t_gpu_elapsed_query_end='ph_query_end')
    lines=[indent+'ph_i=worker.phase_records.count',indent+"if ph_i>=worker.phase_records.capacity:raise RuntimeError('V22 phase storage overflow')"]
    for key,value in values.items():lines.append(indent+'worker.phase_records.c_'+key+'[ph_i]='+value)
    if not expired:lines.append(indent+'worker.phase_records.gpu[ph_i]=worker.phase_events.last_ms if worker.phase_events.last_ms is not None else float("nan")')
    lines.append(indent+'worker.phase_records.count=ph_i+1')
    return '\n'.join(lines)


def run_source():
    s=b1.run_source()
    s=rep(s,'from instrumented_local_runtime import ConcurrentTensorRT,ContextWorker','from v22_trt import ConcurrentTensorRT,ContextWorker')
    s=rep(s,'from phase_storage import write_after_join','from v22_storage import write_after_join,FrameLedger,preallocate_source_rows\n    from v22_cpu import require_pinned,thermal_snapshot')
    s=rep(s,'from b1_common import make_accounting','from v22_accounting import make_accounting')
    s=rep(s,'frames=[];power=[];errors=[];pipelines=[];threads=[];runtime=None',
          "frames=FrameLedger(int(condition['seconds']*30*condition['K'])+30*condition['C']);power=[];errors=[];pipelines=[];threads=[];runtime=None\n    source_rows=preallocate_source_rows(condition['K'],condition['seconds'])")
    # Fixed reference slots keep identical publication point/lock and insertion order.
    assert s.count('frames.append(row)')==2
    s=s.replace('frames.append(row)','frames.record(row)')
    tree=ast.parse(s);nodes=[n for n in ast.walk(tree) if isinstance(n,ast.Expr) and isinstance(n.value,ast.Call) and ast.unparse(n.value.func)=='worker.phase_records.append']
    assert len(nodes)==2
    nodes.sort(key=lambda n:n.lineno)
    lines=s.splitlines(keepends=True)
    for node,expired in reversed(list(zip(nodes,(True,False)))):
        lines[node.lineno-1:node.end_lineno]=[phase_assign(expired)+'\n']
    s=''.join(lines)
    s=rep(s,'ph_gpu,ph_status=worker.phase_events.elapsed_after_existing_sync()','worker.phase_events.record_elapsed_after_existing_sync()')
    s=rep(s,"if set(outputs)!={'pred_logits','pred_boxes'}:raise RuntimeError('unexpected outputs')",
          "if len(outputs)!=2 or 'pred_logits' not in outputs or 'pred_boxes' not in outputs:raise RuntimeError('unexpected outputs')")
    s=rep(s,"row={'phase':'active','stream_id':stream_id,'frame_id':frame_id,\n                                 'logical_arrival_ns':target,'admitted':int(logical_admit(frame_id,rate)),\n                                 'admission_timestamp_ns':target,'admission_observed_ns':now,\n                                 'enqueue_timestamp_ns':''}",
          "row=source_rows[frame_id][stream_id]\n                            row['logical_arrival_ns']=target\n                            row['admitted']=int(logical_admit(frame_id,rate))\n                            row['admission_timestamp_ns']=target\n                            row['admission_observed_ns']=now")
    s=rep(s,"        manifest['environment_before']=environment()",
          "        manifest['CPU_pin_child_readback']=require_pinned()\n        manifest['thermal_start']=thermal_snapshot()\n        manifest['python_switch_interval_readback_s']=__import__('sys').getswitchinterval()\n        manifest['environment_before']=environment()")
    # Lifecycle diagnostic only; original worker body and service timestamps otherwise preserved.
    s=rep(s,"        if runtime and not alive:\n            try:write_after_join", "        manifest['thermal_end']=thermal_snapshot()\n        if runtime and not alive:\n            try:write_after_join")
    ast.parse(s);return s
