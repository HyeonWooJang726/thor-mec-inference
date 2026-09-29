"""Preparation/orchestration only. Frozen V2.2 inference/queue path is retained.

check/CPU readback are read-only. campaign/one require later explicit approval;
no retry, resume, overwrite, CPU writes, Edge connection or new worker logic.
"""
import argparse
import inspect
import json
import textwrap
import types
from pathlib import Path
from config import HERE,ROOT,OUT,PLAN,order,sha,load_plan,runtime_record,run_source
import run_validation as original
import v22_cpu as cpu
save=original.save


def gpu_control_readiness():
    """Read-only check before any campaign marker or user CPU pin."""
    import sys
    sys.path.insert(0,str(HERE.parent/'timely_capacity_scan/attempt02'))
    from gpu_precheck import observe
    report=observe()
    if report['status']!='PASS':
        raise PermissionError('GPU frequency control unavailable: '+str(report['errors']))
    return report


def memory_snapshot():
    mem={line.split(':')[0]:int(line.split()[1])*1024 for line in Path('/proc/meminfo').read_text().splitlines() if len(line.split())==3}
    group=Path('/proc/self/cgroup').read_text().split('0::',1)[1].strip()
    path=Path('/sys/fs/cgroup')/group.lstrip('/');limits=[]
    while str(path).startswith('/sys/fs/cgroup'):
        if (path/'memory.max').exists():
            cap=(path/'memory.max').read_text().strip();used=int((path/'memory.current').read_text())
            limits.append(dict(path=str(path),limit=cap,current=used,headroom=None if cap=='max' else int(cap)-used))
        if path==Path('/sys/fs/cgroup'):break
        path=path.parent
    headroom=min([mem['MemAvailable']]+[x['headroom'] for x in limits if x['headroom'] is not None])
    # Conservative preparation reserve; NOT a measured resident-memory estimate.
    # Covers even all 14,400 cohort tensors + 16 GiB non-queued runtime headroom.
    required=14400*4915200+16*1024**3
    return dict(meminfo_bytes=mem,swaps=Path('/proc/swaps').read_text(),cgroup_limits=limits,
        effective_headroom_bytes=headroom,required_reserve_bytes=required,
        reserve_is_estimate=True,status='PASS' if headroom>=required else 'STOP_MEMORY_REVIEW')


def before_run(c,d):
    original.before_run(c,d)
    current=cpu.snapshot();reference=json.loads((OUT/'CPU_STATE_BEFORE.json').read_text())
    report=cpu.original.validate(current,reference,'pinned');save(d/'SCAN_CPU_BEFORE_RUN.json',report)
    mem=memory_snapshot();save(d/'MEMORY_BEFORE_RUN.json',mem)
    if report['status']!='PASS' or mem['status']!='PASS':raise RuntimeError('CPU topology/control or memory preflight failed; no workload')


def validate_finished(d,c):
    from analyze_scan import analyze_run
    row,_=analyze_run(d,c);save(d/'raw_scan_validation.json',row)
    # Preserve source-limited/ambiguous data and continue the exact eight-run
    # C2 comparison; only an invalid run stops subsequent workload.
    return row['raw_scan_integrity_status']=='VALID'


def supervisor_source():
    # Rebind only existing parent orchestration; no transformation of run_source.
    s=inspect.getsource(original.Context.campaign)
    import textwrap
    s=textwrap.dedent(s)
    old=original.prior.old
    s=old.rep(s,"admission_fps_per_stream=25,edge_r=0,local_r=25,cell=c['cell'],target_service_FPS=200,supply_mode='A',deadline_ms=100,block='V22',admission_pattern='ALIGNED',pruning_enabled=c['pruning_enabled'],",
                "admission_fps_per_stream=c['admission_r'],edge_r=0,local_r=c['local_r'],cell=c['cell'],target_service_FPS=c['target_service_FPS'],supply_mode='A',deadline_ms=100,block='V22_RAW',admission_pattern='ALIGNED',pruning_enabled=False,")
    return s


def parent_finalizer_source():
    """Bind the actual inherited finalization body to the C-aware validator."""
    base = original.prior.v2.old.base
    source = textwrap.dedent(inspect.getsource(base.finalize_run))
    old_import = 'from analyze_rate_dvfs_gate import summarize,read_csv'
    old_call = '        measured=summarize(manifest,frames,power)'
    if source.count(old_import) != 1 or source.count(old_call) != 1:
        raise RuntimeError('Frozen parent finalizer anchors changed')
    source = source.replace(old_import, 'from summary_adapter import summarize,read_csv')
    source = source.replace(old_call, old_call +
        '\n        from parent_validation import validate_parent_artifacts'
        '\n        measured=validate_parent_artifacts(directory,manifest,frames,measured)')
    return source


def bind_parent_finalizer(inherited):
    namespace = dict(inherited.__globals__)
    exec(compile(parent_finalizer_source(), '<calibration03-production-parent-finalizer>',
                 'exec'), namespace)
    return namespace['finalize_run']


class Context(original.Context):
    def __init__(self):
        super().__init__();self.OUT,self.PLAN=OUT,PLAN;self.PREFLIGHT=OUT/'frequency_preflight.json';self.entry=HERE/'run_scan.py'
    def load_plan(self):return load_plan()
    def bindings(self):
        fn=original.prior.Context.bindings
        run, inherited_final = types.FunctionType(fn.__code__,dict(fn.__globals__,
            run_source=run_source,runtime_record=runtime_record))(self)
        return run, bind_parent_finalizer(inherited_final)
    def campaign(self,approval):
        if approval!=sha(PLAN):raise RuntimeError('Exact raw-scan plan approval SHA required')
        gpu_control_readiness()
        mem=memory_snapshot()
        if mem['status']!='PASS':raise RuntimeError('STOP_MEMORY_REVIEW')
        ns=dict(original.__dict__,OUT=OUT,PLAN=PLAN,order=order,load_plan=load_plan,
            runtime_record=runtime_record,before_run=before_run,validate_finished=validate_finished)
        exec(compile(supervisor_source(),'<raw-scan-parent-only>','exec'),ns)
        try:return ns['campaign'](self,approval)
        finally:print('USER ACTION REQUIRED: restore CPU using CPU_RESTORE_COMMANDS.sh, including after failure/interruption.')


def main():
    ap=argparse.ArgumentParser();ap.add_argument('action',choices=['check','campaign','one','cpu-pinned','cpu-restored']);ap.add_argument('--approve-plan-sha256');ap.add_argument('--run-id');ap.add_argument('--output',type=Path);a=ap.parse_args()
    if a.action.startswith('cpu-'):
        if not a.output:raise RuntimeError('--output required; exclusive creation')
        current=cpu.snapshot();reference=json.loads((OUT/'CPU_STATE_BEFORE.json').read_text())
        r=cpu.original.validate(current,reference,a.action.split('-')[1]);save(a.output,r);return 0 if r['status']=='PASS' else 2
    ctx=Context()
    if a.action=='check':
        ctx.check_inputs();gpu=gpu_control_readiness();mem=memory_snapshot()
        print(json.dumps(dict(GPU=gpu,memory=mem),indent=2))
        return 0 if mem['status']=='PASS' else 2
    if a.action=='campaign':return ctx.campaign(a.approve_plan_sha256)
    p=ctx.check_inputs();ctx.require_preflight();cpu.require_pinned()
    cs=[c for c in p['order'] if c['run_id']==a.run_id]
    if len(cs)!=1:raise RuntimeError('Run outside frozen scan order')
    if not (OUT/'campaign_attempt.json').exists():raise RuntimeError('Parent-approved campaign required')
    seed=OUT/a.run_id/'manifest.json'
    if not seed.exists() or json.loads(seed.read_text()).get('child_has_started'):raise RuntimeError('Fresh parent seed required')
    return ctx.bindings()[0](cs[0],a.run_id)


if __name__=='__main__':raise SystemExit(main())
