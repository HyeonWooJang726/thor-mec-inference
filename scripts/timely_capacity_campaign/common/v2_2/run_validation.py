"""Four-run V2.2 supervisor. CPU pin/restore is manual; settings are never written here."""
import argparse
import inspect
import json
import types
from v22_config import HERE,OUT,PLAN,sha,order,load_plan,runtime_record
from v22_builder import run_source
import run_b1 as prior
import v22_cpu as cpu


def save(path,data):
    with path.open('x') as f:json.dump(data,f,indent=2)


def before_run(c,d):
    report=cpu.validate(cpu.snapshot(),'pinned')
    save(d/'CPU_BEFORE_RUN.json',report);save(d/'THERMAL_BEFORE_RUN.json',cpu.thermal_snapshot())
    if report['status']!='PASS' or not all(p['time_in_state_readable'] for p in report['snapshot']['policies']):
        raise RuntimeError('CPU controls/residency preflight failed; this run not started')


def after_run(d):
    report=cpu.validate(cpu.snapshot(),'pinned');save(d/'CPU_AFTER_RUN.json',report)
    save(d/'THERMAL_AFTER_RUN.json',cpu.thermal_snapshot())
    before=json.loads((d/'CPU_BEFORE_RUN.json').read_text())['snapshot']
    delta=cpu.residency(before,report['snapshot']);save(d/'CPU_TIME_IN_STATE_DELTA.json',delta)
    return report['status']=='PASS'


class Context(prior.Context):
    def __init__(self):
        super().__init__();self.OUT,self.PLAN=OUT,PLAN;self.PREFLIGHT=OUT/'frequency_preflight.json';self.entry=HERE/'run_validation.py'
    def load_plan(self):runtime_record();return load_plan()
    def bindings(self):
        fn=prior.Context.bindings
        run,final=types.FunctionType(fn.__code__,dict(fn.__globals__,run_source=run_source,runtime_record=runtime_record))(self)
        return run,final
    def campaign(self,approval):
        self.check_inputs()
        if approval!=sha(PLAN):raise RuntimeError('Exact V22 plan approval SHA required')
        if (OUT/'campaign_attempt.json').exists() or self.PREFLIGHT.exists() or any((OUT/c['run_id']).exists() for c in order()):
            raise RuntimeError('Existing V22 attempt; no retry/resume/overwrite')
        pin=cpu.require_pinned();save(OUT/'campaign_attempt.json',dict(CPU_pin=pin,approved_plan_sha256=approval,CPU_restore='USER_REQUIRED'))
        self.frequency_preflight()
        old=prior.old
        ns=dict(old.prior.hybrid.__dict__,OUT=OUT,PLAN=PLAN,__file__=str(self.entry),
                check_inputs=self.check_inputs,load_plan=self.load_plan,bindings=self.bindings,
                write_json=self.write_json,frequency=old.frequency,validate_finished=validate_finished,
                before_run=before_run,after_run=after_run)
        s=inspect.getsource(old.prior.hybrid.campaign)
        s=old.rep(s,"        d=OUT/c['run_id'];d.mkdir(exist_ok=False)",
                  "        if c['order_index']>1:time.sleep(plan['idle_seconds'])\n        d=OUT/c['run_id'];d.mkdir(exist_ok=False)\n        before_run(c,d)")
        s=old.rep(s,'admission_fps_per_stream=30,',
                  "admission_fps_per_stream=25,edge_r=0,local_r=25,cell=c['cell'],target_service_FPS=200,supply_mode='A',deadline_ms=100,block='V22',admission_pattern='ALIGNED',pruning_enabled=c['pruning_enabled'],")
        s=old.rep(s,"        print(json.dumps({k:s.get(k)","        cpu_after_ok=after_run(d)\n        print(json.dumps({k:s.get(k)")
        s=old.rep(s,"        if interrupted or recovery_error or not s.get('frequency_restore_ok'):return 2",
                  "        if interrupted or recovery_error or not s.get('frequency_restore_ok') or s.get('integrity_status')!='VALID' or not cpu_after_ok:return 2\n        if not validate_finished(d,c):return 2")
        s=old.rep(s,"return 0 if mode=='primary' or smoke_pass(plan) else 1",'return 0')
        exec(compile(s,'<V22-preserved-supervisor-CPU-hooks>','exec'),ns)
        return ns['campaign']('formal')


def validate_finished(d,c):
    from analyze_b1 import validate_run,read
    m=json.loads((d/'manifest.json').read_text());s=json.loads((d/'summary.json').read_text())
    r=validate_run(c,m,s,read(d/'per_frame.csv.gz'),read(d/'per_frame_phase_timestamps.csv'),json.loads((d/'phase_instrumentation_manifest.json').read_text()))
    if m.get('CPU_pin_child_readback',{}).get('status')!='PASS':r['status']='FAIL';r['errors'].append('CPU child pin failed')
    save(d/'v22_instrumentation_validation.json',r)
    return r['status']=='PASS'


def main():
    ap=argparse.ArgumentParser();ap.add_argument('action',choices=['check','campaign','one']);ap.add_argument('--approve-plan-sha256');ap.add_argument('--run-id');a=ap.parse_args();ctx=Context()
    if a.action=='check':ctx.check_inputs();print('PASS: V22 source/input CPU check only');return 0
    if a.action=='campaign':return ctx.campaign(a.approve_plan_sha256)
    p=ctx.check_inputs();ctx.require_preflight();cpu.require_pinned()
    cs=[c for c in p['order'] if c['run_id']==a.run_id]
    if len(cs)!=1:raise RuntimeError('Run outside frozen order')
    seed=OUT/a.run_id/'manifest.json'
    if not seed.exists() or json.loads(seed.read_text()).get('child_has_started'):raise RuntimeError('Fresh supervisor seed required')
    return ctx.bindings()[0](cs[0],a.run_id)


if __name__=='__main__':raise SystemExit(main())
