"""Block-isolated supervisor adapter over the frozen expired-only pruning pipeline."""
import argparse
import inspect
import json
from pathlib import Path
import subprocess
import sys
import time
import types
import campaign_config as cfg
from reuse import previous_runner, previous, prior, pruning, replace_once as rep

frequency=previous_runner.frequency
equal=previous_runner.base
base=equal.base


def read_tx(interface):
    if not interface:return None
    try:return int((Path('/sys/class/net')/interface/'statistics/tx_bytes').read_text())
    except OSError:return None


def start_diagnostics(interface):
    temps={}
    for p in Path('/sys/class/thermal').glob('thermal_zone*'):
        try:
            name=(p/'type').read_text().strip()
            if 'gpu' in name.lower():temps[name]=int((p/'temp').read_text())/1000
        except OSError:pass
    return dict(monotonic_ns=time.monotonic_ns(),GPU_temperature_C=temps,
        GPU_temperature_status='AVAILABLE' if temps else 'UNAVAILABLE',interface=interface,network_tx_bytes=read_tx(interface))


def adapted_source():
    s=previous_runner.adapted_source()
    s=rep(s,'from analyze_map_d100 import summarize','from campaign_analysis import summarize')
    s=rep(s,"experiment='D100_TIMELY_CAPACITY_MAP'","experiment='TIMELY_CAPACITY_CAMPAIGN', block=condition['block'], admission_pattern=condition['admission_pattern']")
    s=rep(s,"decorate(row,manifest['active_start_ns'],condition['target_service_FPS'],condition['supply_mode'],condition['deadline_ms'])", "decorate(row,manifest['active_start_ns'],condition)")
    s=rep(s,"manifest['OC3_before']=oc3()","manifest['OC3_before']=oc3()\n        manifest['run_start_diagnostics']=start_diagnostics(plan.get('network_interface') if condition['edge_r'] else None)")
    s=rep(s,"'raw_tegrastats':line.rstrip()}","'raw_tegrastats':line.rstrip(), 'network_tx_bytes':read_tx(plan.get('network_interface') if condition['edge_r'] else None)}")
    return s


class Context:
    def __init__(self,block,entry):
        self.block=block;self.OUT=cfg.out(block);self.PLAN=self.OUT/'plan.json'
        self.PREFLIGHT=self.OUT/'frequency_preflight.json';self.entry=Path(entry)

    def load_plan(self):return cfg.load_plan(self.block)

    def write_json(self,path,data):
        if Path(path).parent.parent!=self.OUT:raise RuntimeError('Run writer outside new block')
        base.write_json(path,data)

    def require_preflight(self):
        r=json.loads(self.PREFLIGHT.read_text())
        if r.get('status')!='PASS' or r.get('plan_sha256')!=cfg.sha(self.PLAN):raise RuntimeError('Frequency preflight required')
        return dict(path=str(self.PREFLIGHT.relative_to(cfg.ROOT)),sha256=cfg.sha(self.PREFLIGHT))

    def hello(self,c,run_id,plan_sha):
        h=pruning.hello(c,run_id,plan_sha);h['mode']='timely_capacity_campaign';h['campaign_plan_sha256']=h.pop('pruning_plan_sha256')
        return h

    def edge_link(self,c,*args,**kwargs):
        if not c['edge_r']:return prior.UnusedEdgeLink(c,*args,**kwargs)
        if self.block!='B':raise RuntimeError('Block A forbids Edge')
        class ActiveLink(pruning.EdgeLink):pass
        fn=pruning.EdgeLink.__init__
        ActiveLink.__init__=types.FunctionType(fn.__code__,dict(fn.__globals__,hello=self.hello),fn.__name__,fn.__defaults__,fn.__closure__)
        return ActiveLink(c,*args,**kwargs)

    def bindings(self):
        ns=dict(base.__dict__,OUT=self.OUT,EXECUTION_PLAN=self.PLAN,CAPABILITY=prior.hybrid.CAPABILITY,
            load_plan=self.load_plan,write_json=self.write_json,sha=cfg.sha,EdgeLink=self.edge_link,decorate=cfg.decorate,
            remaining=previous.remaining,FRAME_FIELDS=base.FRAME_FIELDS+prior.EXTRA_FIELDS+pruning.FIELDS,
            POWER_FIELDS=base.POWER_FIELDS+['network_tx_bytes'],require_preflight=self.require_preflight,
            pinned=frequency.pinned,read_range=frequency.read_range,__file__=str(self.entry),
            start_diagnostics=start_diagnostics,read_tx=read_tx)
        exec(compile(adapted_source(),'<timely-capacity-expired-runtime>','exec'),ns)
        s=rep(inspect.getsource(base.finalize_run),'from analyze_rate_dvfs_gate import summarize,read_csv','from campaign_analysis import summarize,read_csv')
        exec(compile(s,'<timely-capacity-finalizer>','exec'),ns)
        return ns['run_one'],ns['finalize_run']

    def check_inputs(self):
        fn=equal.check_inputs
        return types.FunctionType(fn.__code__,dict(fn.__globals__,load_plan=self.load_plan,bindings=self.bindings))()

    def frequency_preflight(self):
        fn=equal.frequency_preflight
        return types.FunctionType(fn.__code__,dict(fn.__globals__,PREFLIGHT=self.PREFLIGHT,PLAN=self.PLAN,load_plan=self.load_plan,frequency=frequency))()

    def campaign(self,approval):
        plan=self.check_inputs()
        if approval!=cfg.sha(self.PLAN):raise RuntimeError('Explicit block plan SHA approval argument required')
        if self.PREFLIGHT.exists() or any((self.OUT/c['run_id']).exists() for c in plan['order']):raise RuntimeError('No retry/overwrite')
        if self.block=='B':
            from edge_preflight import require_pass
            require_pass(self.PLAN,self.OUT/'edge_preflight01')
        self.frequency_preflight()
        ns=dict(prior.hybrid.__dict__,OUT=self.OUT,PLAN=self.PLAN,__file__=str(self.entry),
            check_inputs=self.check_inputs,load_plan=self.load_plan,bindings=self.bindings,
            write_json=self.write_json,frequency=frequency)
        s=inspect.getsource(prior.hybrid.campaign)
        s=rep(s,"        d=OUT/c['run_id'];d.mkdir(exist_ok=False)",
            "        if c['order_index']>1:time.sleep(plan['idle_seconds'])\n        d=OUT/c['run_id'];d.mkdir(exist_ok=False)")
        s=rep(s,'admission_fps_per_stream=30,',"admission_fps_per_stream=c['target_service_FPS']//8, edge_r=c['edge_r'], local_r=c['local_r'], cell=c['cell'], target_service_FPS=c['target_service_FPS'], supply_mode=c['supply_mode'], deadline_ms=100, block=c['block'], admission_pattern=c['admission_pattern'],")
        s=rep(s,"return 0 if mode=='primary' or smoke_pass(plan) else 1", "return 0 if all(json.loads((OUT/c['run_id']/'summary.json').read_text()).get('integrity_status')=='VALID' for c in plan['order']) else 1")
        s=rep(s,"        if interrupted or recovery_error or not s.get('frequency_restore_ok'):return 2", "        if interrupted or recovery_error or not s.get('frequency_restore_ok') or s.get('integrity_status')!='VALID':return 2")
        exec(compile(s,'<timely-capacity-supervisor>','exec'),ns)
        return ns['campaign']('formal')


def main(block,entry):
    ap=argparse.ArgumentParser();ap.add_argument('action',choices=['check','campaign','one']);ap.add_argument('--run-id');ap.add_argument('--approve-plan-sha256')
    a=ap.parse_args();ctx=Context(block,entry)
    if a.action=='check':ctx.check_inputs();print('PASS: CPU/input checks only');return 0
    if a.action=='campaign':return ctx.campaign(a.approve_plan_sha256)
    plan=ctx.check_inputs();ctx.require_preflight();cs=[c for c in plan['order'] if c['run_id']==a.run_id]
    if len(cs)!=1:raise RuntimeError('Unknown run')
    seed=ctx.OUT/a.run_id/'manifest.json'
    if not seed.exists() or json.loads(seed.read_text()).get('child_has_started'):raise RuntimeError('Fresh supervisor seed required')
    return ctx.bindings()[0](cs[0],a.run_id)
