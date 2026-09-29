"""Fresh namespace orchestration; no V2.2 inference hot-path changes."""
import argparse
import json
import sys
import types
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import run_timely_scan as frozen_run
from attempt02_config import OUT, PLAN, order, sha, load_plan, runtime_record
from gpu_precheck import observe, require_ready

cpu = frozen_run.cpu
save = frozen_run.save


def before_run(condition, directory):
    # Same code object and behavior; the saved CPU reference lives in scan02.
    fn = frozen_run.before_run
    return types.FunctionType(fn.__code__, dict(fn.__globals__, OUT=OUT))(condition, directory)


class Context(frozen_run.Context):
    def __init__(self):
        super().__init__()
        self.OUT, self.PLAN = OUT, PLAN
        self.PREFLIGHT = OUT / 'frequency_preflight.json'
        self.entry = HERE / 'run_attempt02.py'

    def load_plan(self):
        return load_plan()

    def bindings(self):
        fn = frozen_run.Context.bindings
        return types.FunctionType(fn.__code__, dict(fn.__globals__, runtime_record=runtime_record))(self)

    def campaign(self, approval):
        if approval != sha(PLAN):
            raise RuntimeError('Exact Attempt02 plan SHA approval required')
        self.check_inputs()                 # 1. Source/input and frozen runtime
        if (OUT / 'campaign_attempt.json').exists() or self.PREFLIGHT.exists() or any((OUT / c['run_id']).exists() for c in order()):
            raise RuntimeError('Existing Attempt02; no retry/resume/overwrite')
        readiness = require_ready()         # 2. Read-only; FAIL consumes no attempt
        print(json.dumps({'gpu_control_campaign_precheck': readiness}, sort_keys=True), flush=True)
        fn = frozen_run.Context.campaign
        namespace = dict(fn.__globals__, OUT=OUT, PLAN=PLAN, order=order,
                         load_plan=load_plan, runtime_record=runtime_record,
                         before_run=before_run)
        try:
            return types.FunctionType(fn.__code__, namespace, fn.__name__,
                                      fn.__defaults__, fn.__closure__)(self, approval)
        finally:
            print('USER CPU RESTORE REQUIRED after campaign success/failure/interruption. Analyze only after restore PASS.')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['check', 'gpu-check', 'campaign', 'one', 'cpu-pinned', 'cpu-restored'])
    parser.add_argument('--approve-plan-sha256')
    parser.add_argument('--run-id')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.action.startswith('cpu-'):
        if args.output is None or args.output.parent != OUT:
            raise RuntimeError('Fresh scan02 --output path required')
        reference = json.loads((OUT / 'CPU_STATE_BEFORE.json').read_text())
        result = cpu.original.validate(cpu.snapshot(), reference, args.action.split('-')[1])
        save(args.output, result)
        return 0 if result['status'] == 'PASS' else 2
    if args.action == 'gpu-check':
        result = observe()
        print(json.dumps(result, indent=2))
        return 0 if result['status'] == 'PASS' else 2
    context = Context()
    if args.action == 'check':
        context.check_inputs()
        result = observe()
        print(json.dumps({'input_source_status': 'PASS', 'gpu_control_readiness': result}, indent=2))
        return 0 if result['status'] == 'PASS' else 2
    if args.action == 'campaign':
        return context.campaign(args.approve_plan_sha256)
    plan = context.check_inputs()
    context.require_preflight()
    cpu.require_pinned()
    conditions = [c for c in plan['order'] if c['run_id'] == args.run_id]
    if len(conditions) != 1 or not (OUT / 'campaign_attempt.json').exists():
        raise RuntimeError('Parent-approved Attempt02 condition required')
    seed = OUT / args.run_id / 'manifest.json'
    if not seed.exists() or json.loads(seed.read_text()).get('child_has_started'):
        raise RuntimeError('Fresh parent seed required; no retry')
    return context.bindings()[0](conditions[0], args.run_id)


if __name__ == '__main__':
    raise SystemExit(main())
