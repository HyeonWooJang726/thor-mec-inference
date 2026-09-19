#!/usr/bin/env python3
"""C configuration wrapper; reuses the frozen rate-DVFS pipeline and supervisor."""
import argparse
import ast
import hashlib
import inspect
import json
from pathlib import Path
import sys
import types

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'scripts/rate_dvfs_gate'))
import run_rate_dvfs_gate as base
from gpu_frequency import read_range, restore

OUT = ROOT/'results/c_robustness_gate'
PLAN = OUT/'EXPERIMENT_PLAN.md'
CAPABILITY = ROOT/'results/rate_dvfs_gate/frequency_capability.json'


def load_plan():
    plan = json.loads(PLAN.read_text().split('```json\n', 1)[1].split('\n```', 1)[0])
    if plan['freeze_status'] != 'FROZEN_C_ROBUSTNESS':
        raise RuntimeError('C Gate plan is not frozen')
    return plan


def write_json(path, data):
    """Annotate new-run records without changing inherited measurement fields."""
    if path.name in ('manifest.json', 'summary.json'):
        condition = next(c for c in load_plan()['smoke']+load_plan()['order'] if c['run_id']==path.parent.name)
        data.update(experiment='C_ROBUSTNESS_GATE', operating_point=condition['operating_point'],
                    configured_C=condition['C'], aggregate_demand_fps=condition['K']*condition['r'])
    base.write_json(path, data)


class Adapter(ast.NodeTransformer):
    """Bind only two read-only metadata paths and the initial context count.

    The historical source stays byte-identical. Exact node counts make changes
    to the reused function fail explicitly rather than silently altering it.
    """
    def __init__(self):
        self.counts = {'capability':0, 'plan':0, 'concurrency':0}

    def visit_BinOp(self, node):
        self.generic_visit(node)
        if isinstance(node.op, ast.Div) and isinstance(node.left, ast.Name) and node.left.id=='OUT' and isinstance(node.right, ast.Constant):
            name = node.right.value
            if name in ('frequency_capability.json', 'EXPERIMENT_PLAN_V2.md'):
                key = 'capability' if name=='frequency_capability.json' else 'plan'
                self.counts[key] += 1
                return ast.copy_location(ast.Name(id='CAPABILITY' if key=='capability' else 'EXECUTION_PLAN', ctx=ast.Load()), node)
        return node

    def visit_Call(self, node):
        self.generic_visit(node)
        if isinstance(node.func, ast.Name) and node.func.id=='ConcurrentTensorRT':
            if len(node.args)!=2 or not isinstance(node.args[1], ast.Constant) or node.args[1].value!=2:
                raise RuntimeError('unexpected base context initialization')
            node.args[1] = ast.parse('min(c, 2)', mode='eval').body
            self.counts['concurrency'] += 1
        return node


def adapted_tree():
    tree = ast.parse(inspect.getsource(base.run_one))
    adapter = Adapter()
    tree = ast.fix_missing_locations(adapter.visit(tree))
    if adapter.counts != {'capability':2, 'plan':2, 'concurrency':1}:
        raise RuntimeError('historical pipeline adapter shape changed: '+str(adapter.counts))
    return tree


def smoke_pass(plan):
    path = OUT/plan['smoke'][0]['run_id']/'summary.json'
    if not path.exists():
        return False, 'C1_SMOKE_NOT_COMPLETED'
    s = json.loads(path.read_text())
    good = (s.get('child_returncode')==0 and s.get('integrity_status')=='VALID'
            and s.get('PROCESS_LIFECYCLE')=='PASS' and s.get('backlog_after_drain')==0
            and s.get('active_concurrency_peak')==1 and s.get('configured_C')==1
            and s.get('pipeline_audit_status')=='PASS')
    return good, 'C1_SMOKE_PASS' if good else 'C1_SMOKE_FAIL'


def finalize_run(directory, info, stdout='', stderr=''):
    # A killed child cannot execute its finally block. Attempt the same default
    # restoration in the parent, preserving the child's failure as INVALID.
    recovery = None
    current = read_range()
    if (current['min_freq'], current['max_freq']) != (315000000,1575000000):
        try:
            recovery = {'parent_restore':restore()}
        except Exception as error:
            recovery = {'parent_restore_error':repr(error)}
    try:
        result = base.finalize_run(directory, info, stdout, stderr)
    except Exception as error:
        manifest = json.loads((directory/'manifest.json').read_text())
        manifest.update(info, status_finalized=True)
        manifest.setdefault('errors', []).append('supervisor raw/finalization failure: '+repr(error))
        result = dict(manifest, integrity_status='INVALID', validity='INVALID',
                      queue_stable=False, backlog_stable=False, energy_per_frame_J=None,
                      queue_classification='INVALID', PROCESS_LIFECYCLE='FAIL')
        base.write_json(directory/'manifest.json', manifest)
    manifest = json.loads((directory/'manifest.json').read_text())
    if recovery is not None:
        manifest['parent_frequency_recovery'] = recovery
        result['parent_frequency_recovery'] = recovery
    if result.get('active_concurrency_peak', 0)>manifest['C']:
        result.update(integrity_status='INVALID', validity='INVALID', queue_stable=False,
                      backlog_stable=False, queue_classification='INVALID', energy_per_frame_J=None)
        result.setdefault('errors', []).append('configured C exceeded')
    write_json(directory/'manifest.json', manifest)
    write_json(directory/'summary.json', result)
    return result


def bindings():
    namespace = dict(base.__dict__)
    namespace.update(OUT=OUT, EXECUTION_PLAN=PLAN, CAPABILITY=CAPABILITY,
                     load_plan=load_plan, write_json=write_json, finalize_run=finalize_run,
                     recovery_report=smoke_pass, __file__=__file__)
    exec(compile(adapted_tree(), str(Path(base.__file__).resolve()), 'exec'), namespace)
    campaign = types.FunctionType(base.campaign.__code__, namespace)
    return namespace['run_one'], campaign


def check_parameterization():
    """GPU-free check of the actual adapted initialization statements only."""
    tree = adapted_tree()
    statements = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id=='runtime' for t in node.targets) and isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Name) and node.value.func.id=='ConcurrentTensorRT':
            statements.append(node)
        if isinstance(node, ast.For) and isinstance(node.target, ast.Name) and node.target.id=='worker_id' and isinstance(node.iter, ast.Call) and ast.unparse(node.iter)=='range(2, c)':
            statements.append(node)
    assert len(statements)==2
    statements.sort(key=lambda n:n.lineno)
    code = compile(ast.fix_missing_locations(ast.Module(body=statements, type_ignores=[])), '<C parameterization fixture>', 'exec')
    class Worker:
        def __init__(self, engine, worker_id):
            self.worker_id = worker_id
    class Runtime:
        def __init__(self, engine, count):
            assert count in (1,2)
            self.engine = engine
            self.workers = [Worker(engine,i) for i in range(count)]
    results = []
    for c in (1,2,4):
        ns = dict(c=c, ENGINE='MOCK_ONLY', ConcurrentTensorRT=Runtime, ContextWorker=Worker)
        exec(code, ns)
        ids = [w.worker_id for w in ns['runtime'].workers]
        assert ids==list(range(c))
        results.append({'configured_C':c, 'worker_ids':ids})
    print(json.dumps({'result':'PASS','provenance':'GPU-free parameterization fixture; no GPU inference','cases':results}))


if __name__=='__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('check','smoke','primary','one'))
    parser.add_argument('--run-id')
    args = parser.parse_args()
    if args.action=='check':
        check_parameterization()
        raise SystemExit(0)
    plan = load_plan()
    for path, digest in plan['source_sha256'].items():
        if hashlib.sha256((ROOT/path).read_bytes()).hexdigest()!=digest:
            raise RuntimeError('frozen source hash mismatch: '+path)
    run_one, campaign = bindings()
    if args.action=='one':
        matches = [c for c in plan['smoke']+plan['order'] if c['run_id']==args.run_id]
        if len(matches)!=1:
            raise RuntimeError('unknown/duplicate run ID')
        result = run_one(matches[0], args.run_id)
    else:
        result = campaign(args.action)
    raise SystemExit(result)
