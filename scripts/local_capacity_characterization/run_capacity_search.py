#!/usr/bin/env python3
"""Frozen deterministic integer search + exactly three new endpoint repetitions."""
import argparse
import ast
import csv
from datetime import datetime,timezone
import gzip
import hashlib
import importlib.util
import inspect
import json
from pathlib import Path
import signal
import subprocess
import sys
import time
import types

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('capacity_frequency',Path(__file__).with_name('gpu_frequency.py'))
frequency = importlib.util.module_from_spec(spec)
spec.loader.exec_module(frequency)
sys.path.insert(0,str(ROOT/'scripts/rate_dvfs_gate'))
import run_rate_dvfs_gate as base

OUT = ROOT/'results/local_capacity_characterization'
PLAN = OUT/'EXPERIMENT_PLAN.md'
INVENTORY = OUT/'frequency_inventory.json'
CAPABILITY = ROOT/'results/rate_dvfs_gate/frequency_capability.json'
ANCHORS = [315,477,630,792,945,1107,1260,1413,1575]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_plan():
    p = json.loads(PLAN.read_text().split('```json\n',1)[1].split('\n```',1)[0])
    assert p['freeze_status']=='FROZEN_CAPACITY_ANCHORS'
    assert p['anchors_MHz']==ANCHORS and sorted(p['frequency_order_MHz'])==ANCHORS
    return p


def inventory():
    return json.loads(INVENTORY.read_text())


def state_write(state):
    data = inventory();data['campaign_state']=state
    base.write_json(INVENTORY,data)
    fields=['sequence','run_id','frequency_MHz','r','stage','endpoint_role','condition_repeat',
            'lo_before','hi_before','decision_rule','status','integrity_status','queue_stable',
            'supply_status','completed_fps','g_B','OC3_delta','child_returncode','next_lo','next_hi']
    with (OUT/'search_trace.csv').open('w',newline='') as target:
        w=csv.DictWriter(target,fieldnames=fields,extrasaction='ignore');w.writeheader();w.writerows(state['runs'])


def check_inputs(plan,hardware=False):
    assert subprocess.check_output(['git','branch','--show-current'],cwd=ROOT,text=True).strip()=='rate-dvfs-gate'
    for path,h in plan['source_sha256'].items():
        if sha(ROOT/path)!=h:raise RuntimeError('frozen source mismatch: '+path)
    for entry in plan['inputs']:
        if sha(Path(entry['path']))!=entry['sha256']:raise RuntimeError('input SHA256 mismatch: '+entry['path'])
    if sha(base.ENGINE)!=plan['engine_provenance']['sha256']:raise RuntimeError('ENGINE_PROVENANCE_FAIL')
    if frequency.supported()!=inventory()['supported_frequencies_Hz']:raise RuntimeError('frequency table changed')
    for f in ANCHORS:frequency.validate_target(f)
    current=frequency.read_range()
    if (current['min_freq'],current['max_freq'])!=(315000000,1575000000):raise RuntimeError('default range differs')
    if hardware:frequency.require_control()


def write_json(path,data):
    if path.parent.parent!=OUT:raise RuntimeError('run write outside characterization')
    data.update(experiment='K8_C2_FREQUENCY_CAPACITY_ANCHORS',configured_C=2)
    if path.name=='summary.json' and data.get('per_stream'):
        values=[p['R_k'] for p in data['per_stream']]
        data['per_stream_fps_spread']=max(values)-min(values)
    base.write_json(path,data)


class Adapter(ast.NodeTransformer):
    def __init__(self):self.paths=0;self.frequency=0
    def visit_BinOp(self,node):
        self.generic_visit(node)
        if (isinstance(node.op,ast.Div) and isinstance(node.left,ast.Name) and node.left.id=='OUT'
                and isinstance(node.right,ast.Constant) and node.right.value in ('frequency_capability.json','EXPERIMENT_PLAN_V2.md')):
            self.paths+=1
            return ast.copy_location(ast.Name(id='CAPABILITY' if node.right.value=='frequency_capability.json' else 'EXECUTION_PLAN',ctx=ast.Load()),node)
        return node
    def visit_Assign(self,node):
        self.generic_visit(node)
        if any(isinstance(t,ast.Name) and t.id=='freq' for t in node.targets):
            if ast.unparse(node.value)!="{'LOW': 945, 'MID': 1260, 'HIGH': 1575}[condition['frequency']]":
                raise RuntimeError('historical frequency expression changed')
            self.frequency+=1
            node.value=ast.parse("condition['frequency_MHz']",mode='eval').body
        return node


def adapted_tree():
    a=Adapter();tree=ast.fix_missing_locations(a.visit(ast.parse(inspect.getsource(base.run_one))))
    assert (a.paths,a.frequency)==(4,1)
    return tree


def bindings():
    # Empty smoke list: reuse already-validated identical K8 pipeline, no extra GPU workload.
    ns=dict(base.__dict__)
    ns.update(OUT=OUT,EXECUTION_PLAN=PLAN,CAPABILITY=CAPABILITY,load_plan=load_plan,
              write_json=write_json,pinned=frequency.pinned,read_range=frequency.read_range,__file__=__file__)
    exec(compile(adapted_tree(),str(Path(base.__file__).resolve()),'exec'),ns)
    return ns['run_one'],types.FunctionType(base.finalize_run.__code__,ns)


def run_candidate(state,fs,f,r,stage,role=''):
    plan=load_plan();check_inputs(plan,hardware=True)
    rep=1+sum(x['frequency_MHz']==f and x['r']==r for x in state['runs'])
    sequence=len(state['runs'])+1
    run_id=f'LCCA_{plan["campaign_date"]}_F{f:04}_R{r:02}_{rep:02}'
    condition={'run_id':run_id,'kind':'primary','repeat':rep,'K':8,'C':2,'r':r,'frequency':f'F{f}',
               'frequency_MHz':f,'seconds':60,'search_stage':stage,'endpoint_role':role}
    record=dict(sequence=sequence,run_id=run_id,frequency_MHz=f,r=r,stage=stage,endpoint_role=role,
                condition_repeat=rep,lo_before=fs['lo'],hi_before=fs['hi'],
                decision_rule='floor((lo+hi)/2)' if stage=='search' else 'frozen endpoint confirmation to 3 total attempts',
                status='PLANNED',condition=condition)
    state['runs'].append(record);state_write(state)
    directory=OUT/run_id;directory.mkdir(exist_ok=False)
    begin=datetime.now(timezone.utc);start=time.monotonic_ns()
    seed=dict(protocol_version=2,run_id=run_id,kind='primary',repeat=rep,K=8,C=2,
              freq_state=f'F{f}',requested_freq_MHz=f,admission_fps_per_stream=r,errors=[],
              child_start_time=begin.isoformat(),child_start_monotonic_ns=start,
              child_pid=None,child_returncode=None,child_exit_signal=None,status_finalized=False,
              summary_written=False,active_phase_completed=False,drain_completed=False,
              cleanup_started=False,cleanup_completed=False,frequency_restore_ok=False,
              active_start_ns=None,active_end_ns=None,condition=condition,
              adaptive_search_decision={k:v for k,v in record.items() if k!='condition'},
              historical_search_initialization=plan['historical_prior'] if f==1575 else None)
    write_json(directory/'manifest.json',seed);(directory/'stderr.log').touch()
    for filename,fields in [('per_frame.csv.gz',base.FRAME_FIELDS),('power_trace.csv.gz',base.POWER_FIELDS)]:
        with gzip.open(directory/filename,'wt',newline='') as target:
            csv.DictWriter(target,fieldnames=fields).writeheader()
    print('START '+json.dumps(record),flush=True)
    process=subprocess.Popen([sys.executable,'-X','faulthandler','-B',__file__,'one','--run-id',run_id],
                             cwd=ROOT,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    interrupted=False;timed_out=False
    try:stdout,stderr=process.communicate(timeout=360)
    except (subprocess.TimeoutExpired,KeyboardInterrupt) as error:
        interrupted=isinstance(error,KeyboardInterrupt);timed_out=not interrupted;process.terminate()
        try:stdout,stderr=process.communicate(timeout=15)
        except subprocess.TimeoutExpired:process.kill();stdout,stderr=process.communicate()
    end=datetime.now(timezone.utc);signo=-process.returncode if process.returncode<0 else None
    info=dict(child_pid=process.pid,child_returncode=process.returncode,
              child_exit_signal=signal.Signals(signo).name if signo else None,
              child_start_time=begin.isoformat(),child_exit_time=end.isoformat(),
              child_start_monotonic_ns=start,child_exit_monotonic_ns=time.monotonic_ns(),
              supervisor_timeout=timed_out,supervisor_interrupted=interrupted)
    recovery=None
    if (frequency.read_range()['min_freq'],frequency.read_range()['max_freq'])!=(315000000,1575000000):
        try:recovery={'parent_restore':frequency.restore()}
        except Exception as error:recovery={'parent_restore_error':repr(error)}
    _,finalize=bindings()
    try:s=finalize(directory,info,stdout,stderr)
    except Exception as error:
        m=json.loads((directory/'manifest.json').read_text());m.update(info,status_finalized=True)
        m.setdefault('errors',[]).append('supervisor finalization failure: '+repr(error))
        s=dict(m,integrity_status='INVALID',validity='INVALID',queue_stable=False,energy_per_frame_J=None,
               PROCESS_LIFECYCLE='FAIL',pipeline_audit_status='INCONCLUSIVE')
        write_json(directory/'manifest.json',m)
    if recovery:
        m=json.loads((directory/'manifest.json').read_text());m['parent_frequency_recovery']=recovery
        write_json(directory/'manifest.json',m);s['parent_frequency_recovery']=recovery
    write_json(directory/'summary.json',s)
    record.update(status='COMPLETED',integrity_status=s['integrity_status'],queue_stable=s.get('queue_stable'),
                  supply_status=s.get('supply_status'),completed_fps=s.get('aggregate_completed_fps'),g_B=s.get('g_B'),
                  OC3_delta=s.get('OC3_delta'),child_returncode=process.returncode)
    state_write(state)
    print('DONE '+json.dumps({k:v for k,v in record.items() if k!='condition'}),flush=True)
    if interrupted:raise KeyboardInterrupt('campaign interrupted; child preserved; no automatic retry')
    current=frequency.read_range()
    if (current['min_freq'],current['max_freq'])!=(315000000,1575000000):raise RuntimeError('RESTORE_BLOCKER')
    return s,record


def campaign():
    plan=load_plan();check_inputs(plan,hardware=True)
    if 'campaign_state' in inventory():raise RuntimeError('campaign already started; no automatic rerun/resume')
    state={'status':'RUNNING','runs':[],'frequencies':{}}
    state_write(state)
    for f in plan['frequency_order_MHz']:
        fs={'lo':21 if f==1575 else 0,'hi':27 if f==1575 else 31,'status':'SEARCHING'}
        state['frequencies'][str(f)]=fs;state_write(state)
        while fs['hi']-fs['lo']>1:
            r=(fs['lo']+fs['hi'])//2
            s,record=run_candidate(state,fs,f,r,'search')
            if s['integrity_status']!='VALID' or s.get('pipeline_audit_status')!='PASS':
                fs.update(status='INCONCLUSIVE',reason='invalid search measurement; no inferred decision or retry')
                state_write(state);break
            fs['lo' if s['queue_stable'] else 'hi']=r
            record.update(next_lo=fs['lo'],next_hi=fs['hi']);state_write(state)
        if fs['status']=='INCONCLUSIVE':continue
        fs.update(status='CONFIRMING',candidate_stable_r=fs['lo'] if fs['lo']>=1 else None,
                  candidate_unstable_r=fs['hi'] if fs['hi']<=30 else None)
        state_write(state)
        # Round-robin stable then unstable; includes one search attempt if present.
        for target_rep in (1,2,3):
            for role,r in [('stable',fs['candidate_stable_r']),('unstable',fs['candidate_unstable_r'])]:
                if r is None:continue
                attempts=sum(x['frequency_MHz']==f and x['r']==r for x in state['runs'])
                if attempts<target_rep:run_candidate(state,fs,f,r,'confirmation',role)
        fs['status']='MEASUREMENTS_COMPLETE';state_write(state)
        print('ANCHOR_COMPLETE '+str(f),flush=True)
    state['status']='COMPLETE';state_write(state)


def offline_check():
    from unittest.mock import patch
    for f in ANCHORS:assert frequency.validate_target(f)==f*1000000
    # Validate helper pin/restore call targets with no hardware writes.
    with patch.object(frequency,'require_control'),patch.object(frequency.legacy,'_range') as write:
        for f in ANCHORS:frequency.set_frequency(f)
        frequency.restore()
        assert [c.args for c in write.call_args_list]==[(f*1000000,f*1000000) for f in ANCHORS]+[(315000000,1575000000)]
    adapted_tree()
    for boundary in range(31):
        lo,hi=0,31;seen=[]
        while hi-lo>1:
            r=(lo+hi)//2;assert 1<=r<=30 and r not in seen;seen.append(r)
            if r<=boundary:lo=r
            else:hi=r
        assert lo==boundary and hi==boundary+1 and len(seen)<=5
    print(json.dumps({'offline_check':'PASS','GPU_workload':False,'anchors':ANCHORS,'binary_search_boundaries_checked':31}))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('action',choices=('check','run','one'));p.add_argument('--run-id');args=p.parse_args()
    if args.action=='check':check_inputs(load_plan());offline_check()
    elif args.action=='run':campaign()
    else:
        plan=load_plan();check_inputs(plan)
        matches=[r for r in inventory()['campaign_state']['runs'] if r['run_id']==args.run_id]
        if len(matches)!=1 or matches[0]['status']!='PLANNED':raise RuntimeError('child not in pending deterministic plan')
        condition=matches[0]['condition']
        if condition['frequency_MHz'] not in ANCHORS or not 1<=condition['r']<=30:raise RuntimeError('out of scope')
        one,_=bindings();raise SystemExit(one(condition,args.run_id))
