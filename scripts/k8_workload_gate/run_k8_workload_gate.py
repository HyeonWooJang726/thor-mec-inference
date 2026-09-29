#!/usr/bin/env python3
"""K8 fixed-source wrapper around the immutable amended Rate-DVFS pipeline."""
import argparse
import ast
import hashlib
import inspect
import json
from pathlib import Path
import subprocess
import sys
import types

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'scripts/rate_dvfs_gate'))
import run_rate_dvfs_gate as base
from gpu_frequency import inspect as inspect_frequency, read_range, restore

OUT = ROOT/'results/k8_workload_gate'
PLAN = OUT/'EXPERIMENT_PLAN.md'
CAPABILITY = ROOT/'results/rate_dvfs_gate/frequency_capability.json'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_plan():
    plan = json.loads(PLAN.read_text().split('```json\n', 1)[1].split('\n```', 1)[0])
    if plan['freeze_status'] != 'FROZEN_K8_WORKLOAD_GATE':
        raise RuntimeError('K8 plan not frozen')
    expected = [21,27,30,27,30,21,30,21,27]
    assert [x['r'] for x in plan['order']] == expected
    assert len(plan['smoke']) == 1 and plan['smoke'][0]['r'] == 21
    for c in plan['smoke']+plan['order']:
        assert (c['K'],c['C'],c['frequency']) == (8,2,'HIGH')
        assert c['seconds'] == (10 if c['kind']=='smoke' else 60)
    assert len(plan['inputs']) == 8 and len({x['path'] for x in plan['inputs']}) == 8
    return plan


def write_json(path, data):
    if path.parent.parent != OUT:
        raise RuntimeError('run writer outside new K8 output: '+str(path))
    data.update(experiment='K8_WORKLOAD_FEASIBILITY_GATE', configured_C=2)
    if path.name == 'summary.json' and data.get('per_stream'):
        rates = [s['R_k'] for s in data['per_stream']]
        data['max_per_stream_completed_fps'] = max(rates)
        data['per_stream_fps_spread'] = max(rates)-min(rates)
    base.write_json(path, data)


class MetadataAdapter(ast.NodeTransformer):
    """Only rebind historical metadata paths; no workload statements change."""
    def __init__(self):
        self.counts = {'frequency_capability.json':0, 'EXPERIMENT_PLAN_V2.md':0}

    def visit_BinOp(self, node):
        self.generic_visit(node)
        if (isinstance(node.op, ast.Div) and isinstance(node.left, ast.Name)
                and node.left.id == 'OUT' and isinstance(node.right, ast.Constant)
                and node.right.value in self.counts):
            name = node.right.value
            self.counts[name] += 1
            return ast.copy_location(ast.Name(id='CAPABILITY' if name=='frequency_capability.json'
                                             else 'EXECUTION_PLAN', ctx=ast.Load()), node)
        return node


def adapted_tree():
    adapter = MetadataAdapter()
    tree = ast.fix_missing_locations(adapter.visit(ast.parse(inspect.getsource(base.run_one))))
    if adapter.counts != {'frequency_capability.json':2, 'EXPERIMENT_PLAN_V2.md':2}:
        raise RuntimeError('frozen metadata adapter shape changed')
    return tree


def smoke_pass(plan):
    path = OUT/plan['smoke'][0]['run_id']/'summary.json'
    if not path.exists():
        return False, 'K8_SMOKE_NOT_COMPLETED'
    s = json.loads(path.read_text())
    good = (s.get('integrity_status')=='VALID' and s.get('child_returncode')==0
            and s.get('PROCESS_LIFECYCLE')=='PASS' and s.get('pipeline_audit_status')=='PASS'
            and s.get('frequency_restore_ok') is True and s.get('backlog_after_drain')==0
            and s.get('active_concurrency_peak')==2 and s.get('source_frames')==2400
            and s.get('admitted_frames')==1680 and s.get('completed_frames_including_drain')==1680
            and [x['stream_id'] for x in s.get('per_stream',[])]==list(range(8)))
    return good, 'K8_SMOKE_PASS' if good else 'K8_SMOKE_FAIL'


def bindings():
    ns = dict(base.__dict__)
    ns.update(OUT=OUT, EXECUTION_PLAN=PLAN, CAPABILITY=CAPABILITY, load_plan=load_plan,
              write_json=write_json, recovery_report=smoke_pass, __file__=__file__)
    original_finalize = types.FunctionType(base.finalize_run.__code__, ns)

    def finalize(directory, info, stdout='', stderr=''):
        recovery = None
        current = read_range()
        if (current['min_freq'],current['max_freq']) != (315000000,1575000000):
            try:
                recovery = {'parent_restore':restore()}
            except Exception as error:
                recovery = {'parent_restore_error':repr(error)}
        try:
            result = original_finalize(directory, info, stdout, stderr)
        except Exception as error:
            m = json.loads((directory/'manifest.json').read_text())
            m.update(info, status_finalized=True)
            m.setdefault('errors',[]).append('supervisor finalization failure: '+repr(error))
            result = dict(m, integrity_status='INVALID', validity='INVALID', queue_stable=False,
                          backlog_stable=False, energy_per_frame_J=None, PROCESS_LIFECYCLE='FAIL')
            write_json(directory/'manifest.json',m)
        if recovery:
            m = json.loads((directory/'manifest.json').read_text())
            m['parent_frequency_recovery'] = recovery
            result['parent_frequency_recovery'] = recovery
            write_json(directory/'manifest.json',m)
        write_json(directory/'summary.json', result)
        return result

    ns['finalize_run'] = finalize
    exec(compile(adapted_tree(), str(Path(base.__file__).resolve()), 'exec'), ns)
    return ns['run_one'], types.FunctionType(base.campaign.__code__, ns)


def check_inputs(plan, hardware=False):
    if subprocess.check_output(['git','branch','--show-current'],cwd=ROOT,text=True).strip()!='rate-dvfs-gate':
        raise RuntimeError('wrong branch; no checkout attempted')
    for name,digest in plan['source_sha256'].items():
        if sha(ROOT/name)!=digest:
            raise RuntimeError('frozen source mismatch: '+name)
    for entry in plan['inputs']:
        if sha(Path(entry['path']))!=entry['sha256']:
            raise RuntimeError('source SHA256 mismatch: '+entry['path'])
    if sha(base.ENGINE)!=plan['engine_provenance']['sha256']:
        raise RuntimeError('ENGINE_PROVENANCE_FAIL')
    adapted_tree()
    if hardware:
        env = inspect_frequency()
        record = json.loads((OUT/'input_manifest.json').read_text())
        record.setdefault('execution_preflights',[]).append(env)
        base.write_json(OUT/'input_manifest.json',record)
        if env['status']!='FREQUENCY_SWITCHING_NOT_TESTED':
            raise RuntimeError('K8 environment preflight failed: '+env['status'])


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=('check','smoke','primary','one'))
    parser.add_argument('--run-id')
    args = parser.parse_args()
    plan = load_plan()
    check_inputs(plan,hardware=args.action in ('smoke','primary'))
    if args.action=='check':
        print(json.dumps({'check':'PASS','GPU_workload':False,'K':8,'C':2,'inputs':8,
                          'smokes':1,'primary_order':[c['r'] for c in plan['order']]}))
        raise SystemExit(0)
    run_one,campaign = bindings()
    if args.action=='one':
        matches = [c for c in plan['smoke']+plan['order'] if c['run_id']==args.run_id]
        if len(matches)!=1:
            raise RuntimeError('run not in frozen plan')
        # run_one requires an unused supervisor-reserved directory and seed.
        result = run_one(matches[0],args.run_id)
    else:
        result = campaign(args.action)
    raise SystemExit(result)
