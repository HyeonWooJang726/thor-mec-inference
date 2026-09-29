"""Fresh eight-run parent adapter; Block-A-only post-drain summary binding."""
import argparse
import builtins
import json
import sys
import types
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parents[1] / 'timely_capacity_scan'))
sys.path.insert(0, str(HERE.parents[1] / 'timely_capacity_scan' / 'attempt02'))
import run_timely_scan as frozen_run
from gpu_precheck import observe, require_ready
import block_a_summary
from pilot02_config import OUT, PLAN, order, sha, load_plan, runtime_record, decorate

cpu = frozen_run.cpu
save = frozen_run.save


def before_run(condition, directory):
    fn = frozen_run.before_run
    return types.FunctionType(fn.__code__, dict(fn.__globals__, OUT=OUT))(condition, directory)


def supervisor_source():
    original = frozen_run.supervisor_source()
    old = "admission_pattern='ALIGNED',pruning_enabled=True,"
    if original.count(old) != 1:
        raise RuntimeError('Frozen parent admission binding changed')
    # Parent seed only. The V2.2 worker source and TRT/queue path are untouched.
    return original.replace(old, "admission_pattern=c['admission_pattern'],pruning_enabled=True,", 1)


def validate_finished(directory, condition):
    from analyze_pilot02 import validate_integrity
    report = validate_integrity(directory, condition)
    save(directory / 'pilot_integrity_validation.json', report)
    return report['status'] == 'PASS'


class Context(frozen_run.Context):
    def __init__(self):
        super().__init__()
        self.OUT, self.PLAN = OUT, PLAN
        self.PREFLIGHT = OUT / 'frequency_preflight.json'
        self.entry = HERE / 'run_pilot02.py'

    def load_plan(self):
        return load_plan()

    def bindings(self):
        fn = frozen_run.Context.bindings
        namespace = dict(fn.__globals__, runtime_record=runtime_record, decorate=decorate)
        run, final = types.FunctionType(fn.__code__, namespace)(self)

        def block_a_import(name, globals=None, locals=None, fromlist=(), level=0):
            if name == 'b1_summary' and level == 0:
                return block_a_summary
            return builtins.__import__(name, globals, locals, fromlist, level)

        # The frozen worker code object is unchanged. Only its post-run summary
        # import resolves to the Block-A-specific adapter in this private binding.
        def bound(func):
            context = dict(func.__globals__, decorate=decorate,
                           __builtins__=dict(vars(builtins), __import__=block_a_import))
            return types.FunctionType(func.__code__, context, func.__name__,
                                      func.__defaults__, func.__closure__)
        return bound(run), bound(final)

    def campaign(self, approval):
        if approval != sha(PLAN):
            raise RuntimeError('Exact fresh Block A pilot02 plan SHA approval required')
        self.check_inputs()
        if (OUT / 'campaign_attempt.json').exists() or self.PREFLIGHT.exists() or any((OUT / c['run_id']).exists() for c in order()):
            raise RuntimeError('Existing Block A pilot02 attempt; no retry/resume/overwrite')
        readiness = require_ready()
        print(json.dumps({'gpu_control_campaign_precheck': readiness}, sort_keys=True), flush=True)
        fn = frozen_run.Context.campaign
        namespace = dict(fn.__globals__, OUT=OUT, PLAN=PLAN, order=order,
                         load_plan=load_plan, runtime_record=runtime_record,
                         before_run=before_run, validate_finished=validate_finished,
                         supervisor_source=supervisor_source)
        try:
            return types.FunctionType(fn.__code__, namespace, fn.__name__,
                                      fn.__defaults__, fn.__closure__)(self, approval)
        finally:
            print('USER CPU RESTORE REQUIRED after success/failure/interruption. Analyzer requires restore PASS.')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=('check', 'gpu-check', 'campaign', 'one', 'cpu-pinned', 'cpu-restored'))
    parser.add_argument('--approve-plan-sha256')
    parser.add_argument('--run-id')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.action.startswith('cpu-'):
        if args.output is None or args.output.parent.resolve() != OUT.resolve():
            raise RuntimeError('Fresh pilot --output path required')
        reference = json.loads((OUT / 'CPU_STATE_BEFORE.json').read_text())
        report = cpu.original.validate(cpu.snapshot(), reference, args.action.split('-')[1])
        save(args.output, report)
        return 0 if report['status'] == 'PASS' else 2
    if args.action == 'gpu-check':
        report = observe()
        print(json.dumps(report, indent=2))
        return 0 if report['status'] == 'PASS' else 2
    context = Context()
    if args.action == 'check':
        context.check_inputs()
        report = observe()
        print(json.dumps({'source_input_status': 'PASS', 'gpu_control_readiness': report}, indent=2))
        return 0 if report['status'] == 'PASS' else 2
    if args.action == 'campaign':
        return context.campaign(args.approve_plan_sha256)
    plan = context.check_inputs()
    context.require_preflight()
    cpu.require_pinned()
    candidates = [row for row in plan['order'] if row['run_id'] == args.run_id]
    if len(candidates) != 1 or not (OUT / 'campaign_attempt.json').exists():
        raise RuntimeError('Parent-approved pilot run required')
    seed = OUT / args.run_id / 'manifest.json'
    if not seed.exists() or json.loads(seed.read_text()).get('child_has_started'):
        raise RuntimeError('Fresh parent seed required; no retry')
    return context.bindings()[0](candidates[0], args.run_id)


if __name__ == '__main__':
    raise SystemExit(main())
