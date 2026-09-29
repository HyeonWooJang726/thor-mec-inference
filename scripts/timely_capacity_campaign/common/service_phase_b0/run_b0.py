"""User-approved B0 only. Reuse frozen worker, protocol, preflight and supervisor."""
import argparse
import inspect
import json
from pathlib import Path
import sys
import textwrap

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[3]
OUT=ROOT/'results/timely_capacity_campaign/pruning_path_audit/service_phase_validation/b0_01'
PLAN=OUT/'plan.json'
RUN_ID='SPI_B0_S240_L176E64_ON_P01'
PLAN_SHA='d8cb78b2c549b4505819302d1d5653c7f929d35b8562d39a3fe5145e399a3b56'
sys.path.insert(0,str(ROOT/'scripts/timely_capacity_campaign/block_b_split/v2_1'))
import run_21
import checkpoint_21
v2=run_21.v2
old=v2.old
sys.path.insert(0,str(HERE.parent/'service_phase_v1'))
import build_adapter


def runtime_record():
    p=OUT/'runtime_manifest.json';record=json.loads(p.read_text())
    for path,h in record['source_sha256'].items():
        if v2.cfg.sha(ROOT/path)!=h:raise RuntimeError('B0 source changed: '+path)
    return dict(version='SERVICE_PHASE_B0_ONLY',condition_plan_sha256=PLAN_SHA,
                runtime_manifest_sha256=v2.cfg.sha(p),source_sha256=record['source_sha256'])


class Context(run_21.Context):
    def __init__(self):
        super().__init__(72)
        self.OUT=OUT;self.PLAN=PLAN;self.PREFLIGHT=OUT/'frequency_preflight.json';self.entry=HERE/'run_b0.py'
    def load_plan(self):
        runtime_record()
        if v2.cfg.sha(PLAN)!=PLAN_SHA:raise RuntimeError('Frozen singleton B0 plan changed')
        p=json.loads(PLAN.read_text());assert len(p['order'])==1 and not p['smoke']
        c=p['order'][0]
        assert c['run_id']==RUN_ID and (c['local_r'],c['edge_r'],c['seconds'],c['frequency_MHz'])==(22,8,60,1575)
        original=next(r for r in v2.conf.order(72) if r['run_id']==p['B0_original_run_id'])
        assert {k:v for k,v in c.items() if k not in ('run_id','order_index')}=={k:v for k,v in original.items() if k not in ('run_id','order_index')}
        return p
    def bindings(self):
        source=textwrap.dedent(inspect.getsource(v2.Context.bindings))
        source=source.replace("'from analysis_v2 import summarize,read_csv'","'from analysis_21 import summarize,read_csv'")
        source=old.rep(source,'wifi_capture=wifi_v2.capture)',
            'wifi_capture=wifi_v2.capture,SnapshotManifest=checkpoint_21.Manifest,runtime_record=runtime_record)')
        ns=dict(v2.__dict__,adapted_source=build_adapter.run_source,checkpoint_21=checkpoint_21,runtime_record=runtime_record)
        exec(compile(source,'<B0-frozen-bindings>','exec'),ns)
        return ns['bindings'](self)
    def campaign(self,approval,edge_ready):
        if approval!=PLAN_SHA or edge_ready!=RUN_ID:raise RuntimeError('Exact B0 approval and Edge LISTENING confirmation required')
        p=self.check_inputs()
        if self.PREFLIGHT.exists() or (OUT/RUN_ID).exists():raise RuntimeError('Existing attempt; no retry or overwrite')
        # Same proven frequency preflight; only reached after explicit Edge confirmation.
        self.frequency_preflight()
        ns=dict(old.prior.hybrid.__dict__,OUT=OUT,PLAN=PLAN,__file__=str(self.entry),
                check_inputs=self.check_inputs,load_plan=self.load_plan,bindings=self.bindings,
                write_json=self.write_json,frequency=old.frequency)
        source=inspect.getsource(old.prior.hybrid.campaign)
        source=old.rep(source,'admission_fps_per_stream=30,',
            "admission_fps_per_stream=30, edge_r=c['edge_r'],local_r=c['local_r'],cell=c['cell'],target_service_FPS=240,supply_mode='B',deadline_ms=100,block='B',admission_pattern='ALIGNED',")
        source=old.rep(source,"return 0 if mode=='primary' or smoke_pass(plan) else 1",'return 0')
        exec(compile(source,'<B0-singleton-original-supervisor>','exec'),ns)
        return ns['campaign']('formal')


def main():
    ap=argparse.ArgumentParser();ap.add_argument('action',choices=['check','campaign','one'])
    ap.add_argument('--approve-plan-sha256');ap.add_argument('--edge-listening-run-id');ap.add_argument('--run-id')
    a=ap.parse_args();ctx=Context()
    if a.action=='check':ctx.check_inputs();print('PASS: B0 source/input/binding check; no hardware workload');return 0
    if a.action=='campaign':return ctx.campaign(a.approve_plan_sha256,a.edge_listening_run_id)
    if a.run_id!=RUN_ID:raise RuntimeError('Only B0 can execute')
    p=ctx.check_inputs();ctx.require_preflight()
    seed=OUT/RUN_ID/'manifest.json'
    if not seed.exists() or json.loads(seed.read_text()).get('child_has_started'):raise RuntimeError('Fresh B0 supervisor seed required')
    return ctx.bindings()[0](p['order'][0],RUN_ID)

if __name__=='__main__':raise SystemExit(main())
