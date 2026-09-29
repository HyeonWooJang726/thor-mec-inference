"""Parent orchestration + parameter binding; frozen V2.2 worker code is unchanged."""
import argparse
import builtins
import inspect
import json
import textwrap
import types
from pathlib import Path
from timely_config import HERE,ROOT,OUT,PLAN,order,sha,load_plan,runtime_record,run_source,decorate
import run_scan as raw_launcher
import run_validation as original
import timely_summary
cpu=original.cpu
save=original.save


def before_run(c,d):
    original.before_run(c,d)
    r=cpu.original.validate(cpu.snapshot(),json.loads((OUT/'CPU_STATE_BEFORE.json').read_text()),'pinned')
    save(d/'TIMELY_CPU_BEFORE_RUN.json',r)
    if r['status']!='PASS':raise RuntimeError('CPU pin/topology/affinity mismatch')


def validate_finished(d,c):
    # Mandatory integrity only; full timely analyzer remains blocked until restore.
    from analyze_timely_scan import validate
    from analyze_b1 import read
    r=validate(c,json.loads((d/'manifest.json').read_text()),json.loads((d/'summary.json').read_text()),
        read(d/'per_frame.csv.gz'),read(d/'per_frame_phase_timestamps.csv'),json.loads((d/'phase_instrumentation_manifest.json').read_text()))
    save(d/'timely_integrity_validation.json',r);return r['status']=='PASS'


def supervisor_source():
    s=textwrap.dedent(inspect.getsource(original.Context.campaign));rep=original.prior.old.rep
    return rep(s,"admission_fps_per_stream=25,edge_r=0,local_r=25,cell=c['cell'],target_service_FPS=200,supply_mode='A',deadline_ms=100,block='V22',admission_pattern='ALIGNED',pruning_enabled=c['pruning_enabled'],",
        "admission_fps_per_stream=c['admission_r'],edge_r=0,local_r=c['local_r'],cell=c['cell'],target_service_FPS=c['target_service_FPS'],supply_mode='A',deadline_ms=c['deadline_ms'],block='V22_TIMELY',admission_pattern='ALIGNED',pruning_enabled=True,")


def binding_import(name,globals=None,locals=None,fromlist=(),level=0):
    # Only post-drain summary import changes. No CUDA/TRT/worker import interception.
    if name=='b1_summary' and level==0:return timely_summary
    return builtins.__import__(name,globals,locals,fromlist,level)


class Context(original.Context):
    def __init__(self):
        super().__init__();self.OUT,self.PLAN=OUT,PLAN;self.PREFLIGHT=OUT/'frequency_preflight.json';self.entry=HERE/'run_timely_scan.py'
    def load_plan(self):return load_plan()
    def bindings(self):
        fn=original.prior.Context.bindings
        run,final=types.FunctionType(fn.__code__,dict(fn.__globals__,run_source=run_source,runtime_record=runtime_record))(self)
        # New function namespace, same code object. No mutation of imported modules.
        ns=dict(run.__globals__,decorate=decorate,__builtins__=dict(vars(builtins),__import__=binding_import))
        return (types.FunctionType(run.__code__,ns,run.__name__),types.FunctionType(final.__code__,ns,final.__name__))
    def campaign(self,approval):
        if approval!=sha(PLAN):raise RuntimeError('Exact timely plan approval SHA required')
        ns=dict(original.__dict__,OUT=OUT,PLAN=PLAN,order=order,load_plan=load_plan,
                before_run=before_run,validate_finished=validate_finished,runtime_record=runtime_record)
        exec(compile(supervisor_source(),'<timely-parent-only>','exec'),ns)
        try:return ns['campaign'](self,approval)
        finally:print('USER CPU RESTORE REQUIRED after success/failure/interruption. Analyzer is blocked until restore PASS.')


def main():
    ap=argparse.ArgumentParser();ap.add_argument('action',choices=['check','campaign','one','cpu-pinned','cpu-restored']);ap.add_argument('--approve-plan-sha256');ap.add_argument('--run-id');ap.add_argument('--output',type=Path);a=ap.parse_args()
    if a.action.startswith('cpu-'):
        if not a.output:raise RuntimeError('--output required, must be fresh')
        r=cpu.original.validate(cpu.snapshot(),json.loads((OUT/'CPU_STATE_BEFORE.json').read_text()),a.action.split('-')[1]);save(a.output,r)
        return 0 if r['status']=='PASS' else 2
    ctx=Context()
    if a.action=='check':ctx.check_inputs();print('PASS: input/source/binding check only; no workload or frequency control');return 0
    if a.action=='campaign':return ctx.campaign(a.approve_plan_sha256)
    p=ctx.check_inputs();ctx.require_preflight();cpu.require_pinned()
    candidates=[c for c in p['order'] if c['run_id']==a.run_id]
    if len(candidates)!=1 or not (OUT/'campaign_attempt.json').exists():raise RuntimeError('Parent-approved plan run required')
    seed=OUT/a.run_id/'manifest.json'
    if not seed.exists() or json.loads(seed.read_text()).get('child_has_started'):raise RuntimeError('Fresh parent seed required; no retry')
    return ctx.bindings()[0](candidates[0],a.run_id)


if __name__=='__main__':raise SystemExit(main())
