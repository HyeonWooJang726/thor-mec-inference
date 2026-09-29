"""Future approved execution only. Frozen pruning workers; V2 plan/session adapter."""
import argparse
import inspect
import json
import types
from pathlib import Path
from bootstrap import ROOT,HERE,V2,frozen as cfg
import config_v2 as conf
import run_campaign as old
import wifi_v2

def adapted_source():
    s=old.adapted_source()
    s=old.rep(s,'from campaign_analysis import summarize','from analysis_v2 import summarize')
    s=old.rep(s,"manifest.update(summary_written=False", "manifest.update({k:condition[k] for k in ('source_demand_FPS','admitted_FPS','admission_r','original_cell','analysis_class','branch_E_max','source_normalization_FPS')})\n    manifest.update(summary_written=False")
    s=old.rep(s,"manifest['OC3_before']=oc3()","manifest['wifi_start']=wifi_capture()\n        manifest['OC3_before']=oc3()")
    s=old.rep(s,"manifest['environment_after']=environment()","manifest['environment_after']=environment()\n            manifest['run_end_diagnostics']=start_diagnostics(plan.get('network_interface'))\n            manifest['wifi_end']=wifi_capture()")
    return s

class Context(old.Context):
    def __init__(self,emax):
        super().__init__('B',HERE/'run_v2.py')
        self.emax=emax;self.OUT=V2/f'E_MAX_{emax}';self.PLAN=self.OUT/'plan.json'
        self.PREFLIGHT=self.OUT/'frequency_preflight.json'
    def load_plan(self):return conf.load(self.PLAN)
    def hello(self,c,rid,digest):
        h=super().hello(c,rid,digest);h['mode']='timely_capacity_campaign_v2';return h
    def bindings(self):
        ns=dict(old.base.__dict__,OUT=self.OUT,EXECUTION_PLAN=self.PLAN,CAPABILITY=old.prior.hybrid.CAPABILITY,
            load_plan=self.load_plan,write_json=self.write_json,sha=cfg.sha,EdgeLink=self.edge_link,decorate=cfg.decorate,
            remaining=old.previous.remaining,FRAME_FIELDS=old.base.FRAME_FIELDS+old.prior.EXTRA_FIELDS+old.pruning.FIELDS,
            POWER_FIELDS=old.base.POWER_FIELDS+['network_tx_bytes'],require_preflight=self.require_preflight,
            pinned=old.frequency.pinned,read_range=old.frequency.read_range,__file__=str(self.entry),
            start_diagnostics=old.start_diagnostics,read_tx=old.read_tx,wifi_capture=wifi_v2.capture)
        exec(compile(adapted_source(),'<v2-frozen-pruning-adapter>','exec'),ns)
        s=old.rep(inspect.getsource(old.base.finalize_run),'from analyze_rate_dvfs_gate import summarize,read_csv','from analysis_v2 import summarize,read_csv')
        exec(compile(s,'<v2-finalizer>','exec'),ns)
        return ns['run_one'],ns['finalize_run']
    def campaign(self,approval):
        p=self.check_inputs()
        if approval!=cfg.sha(self.PLAN):raise RuntimeError('Exact selected branch approval SHA required')
        from preflight_v2 import require_selected
        require_selected(self.emax)
        if self.PREFLIGHT.exists() or any((self.OUT/c['run_id']).exists() for c in p['order']):raise RuntimeError('No retry/overwrite')
        self.frequency_preflight()
        ns=dict(old.prior.hybrid.__dict__,OUT=self.OUT,PLAN=self.PLAN,__file__=str(self.entry),
            check_inputs=self.check_inputs,load_plan=self.load_plan,bindings=self.bindings,
            write_json=self.write_json,frequency=old.frequency)
        s=inspect.getsource(old.prior.hybrid.campaign)
        s=old.rep(s,"        d=OUT/c['run_id'];d.mkdir(exist_ok=False)","        if c['order_index']>1:time.sleep(plan['idle_seconds'])\n        d=OUT/c['run_id'];d.mkdir(exist_ok=False)")
        s=old.rep(s,'admission_fps_per_stream=30,',"admission_fps_per_stream=c['admission_r'], edge_r=c['edge_r'], local_r=c['local_r'], cell=c['cell'], target_service_FPS=c['target_service_FPS'], supply_mode=c['supply_mode'], deadline_ms=100, block='B', admission_pattern='ALIGNED',")
        s=old.rep(s,"'one','--run-id',c['run_id']","'one','--emax',str(c['branch_E_max']),'--run-id',c['run_id']")
        s=old.rep(s,"return 0 if mode=='primary' or smoke_pass(plan) else 1","return 0")
        s=old.rep(s,"        if interrupted or recovery_error or not s.get('frequency_restore_ok'):return 2","        if interrupted or recovery_error or not s.get('frequency_restore_ok') or s.get('integrity_status')!='VALID':return 2")
        exec(compile(s,'<v2-supervisor>','exec'),ns)
        return ns['campaign']('formal')

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('action',choices=['check','campaign','one']);ap.add_argument('--emax',type=int,choices=conf.LEVELS,required=True)
    ap.add_argument('--approve-plan-sha256');ap.add_argument('--run-id');a=ap.parse_args();ctx=Context(a.emax)
    if a.action=='check':ctx.check_inputs();print('PASS: read-only CPU input/binding check')
    elif a.action=='campaign':raise SystemExit(ctx.campaign(a.approve_plan_sha256))
    else:
        from preflight_v2 import require_selected
        require_selected(a.emax);ctx.require_preflight();p=ctx.check_inputs()
        cs=[c for c in p['order'] if c['run_id']==a.run_id]
        if len(cs)!=1:raise RuntimeError('Unknown run')
        seed=ctx.OUT/a.run_id/'manifest.json'
        if not seed.exists() or json.loads(seed.read_text()).get('child_has_started'):raise RuntimeError('Fresh supervisor seed required')
        raise SystemExit(ctx.bindings()[0](cs[0],a.run_id))
