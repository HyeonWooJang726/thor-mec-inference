"""Confirmation02 parent orchestration only; V2.2 worker text is byte-identical."""
import argparse
import builtins
import json
import re
import subprocess
import sys
import time
import types
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'timely_capacity_scan'))
sys.path.insert(0, str(HERE.parent / 'timely_capacity_scan' / 'attempt02'))
import run_timely_scan as frozen_run
from gpu_precheck import observe, require_ready
import block_b_summary
from grid_config import OUT, PLAN, order, sha, load_plan, runtime_record, decorate

cpu = frozen_run.cpu
save = frozen_run.save


def network_check():
    if any((OUT / name).exists() for name in ('campaign_attempt.json', 'CPU_PIN_READBACK.json',
                                               'CPU_RESTORE_READBACK.json')):
        raise RuntimeError('Stale Confirmation02 execution namespace')
    plan = load_plan()
    edge_ip = plan['edge_host']
    route = subprocess.run(['ip', 'route', 'get', edge_ip], capture_output=True, text=True, timeout=5)
    if route.returncode or not route.stdout.splitlines() or route.stdout.split()[0] != edge_ip:
        raise RuntimeError('PRE_EXECUTION_ROUTE_FAILURE')
    neighbor = subprocess.run(['ip', 'neigh', 'show', edge_ip], capture_output=True, text=True, timeout=5)
    ping = subprocess.run(['ping', '-c', '2', '-W', '1', edge_ip], capture_output=True, text=True, timeout=6)
    record = {'status': 'PASS', 'edge_ip': edge_ip, 'plan_sha256': sha(PLAN),
              'monotonic_ns': time.monotonic_ns(),
              'route': {'command': ['ip','route','get',edge_ip], 'returncode': route.returncode,
                        'stdout': route.stdout, 'stderr': route.stderr},
              'neighbor': {'command': ['ip','neigh','show',edge_ip], 'returncode': neighbor.returncode,
                           'stdout': neighbor.stdout, 'stderr': neighbor.stderr},
              'icmp': {'command': ['ping','-c','2','-W','1',edge_ip], 'returncode': ping.returncode,
                       'stdout': ping.stdout, 'stderr': ping.stderr},
              'warnings': [] if ping.returncode == 0 else ['NETWORK_ICMP_UNAVAILABLE'],
              'scope': 'Route hard; neighbor/ICMP diagnostic; no TCP/protocol probe'}
    save(OUT / 'NETWORK_REACHABILITY_CHECK.json', record)
    return record


def require_network():
    path = OUT / 'NETWORK_REACHABILITY_CHECK.json'
    if not path.is_file():
        raise RuntimeError('Current route check required')
    r = json.loads(path.read_text())
    if r.get('status') != 'PASS' or r.get('plan_sha256') != sha(PLAN) or \
            r.get('edge_ip') != load_plan()['edge_host']:
        raise RuntimeError('Stale route check')
    return r


def pinned_evidence():
    network = require_network()
    path = OUT / 'CPU_PIN_READBACK.json'
    if not path.is_file() or (OUT / 'CPU_RESTORE_READBACK.json').exists():
        raise RuntimeError('Current CPU pin evidence required')
    record = json.loads(path.read_text())
    if record.get('status') != 'PASS' or record.get('plan_sha256') != sha(PLAN) or \
            record.get('monotonic_ns', -1) <= network['monotonic_ns']:
        raise RuntimeError('CPU pin evidence stale')
    if cpu.original.validate(cpu.snapshot(), json.loads((OUT/'CPU_STATE_BEFORE.json').read_text()), 'pinned')['status'] != 'PASS':
        raise RuntimeError('Current CPU not pinned')
    return record


def listener_confirmed(stdout_path, ss_path):
    pin = pinned_evidence()
    stdout_path, ss_path = Path(stdout_path), Path(ss_path)
    if min(stdout_path.stat().st_mtime_ns, ss_path.stat().st_mtime_ns) <= \
            (OUT/'CPU_PIN_READBACK.json').stat().st_mtime_ns:
        raise RuntimeError('Listener evidence predates CPU pin')
    exact = 'LISTENING 5000: 26 CONFIRMATION sessions'
    lines = stdout_path.read_text().splitlines()
    ss = ss_path.read_text().splitlines()
    if exact not in lines or not any(line.lstrip().startswith('LISTEN') and re.search(r':5000\b', line) for line in ss):
        raise RuntimeError('Edge stdout/local ss listener evidence missing')
    record = {'status': 'PASS', 'plan_sha256': sha(PLAN), 'monotonic_ns': time.monotonic_ns(),
              'CPU_pin_monotonic_ns': pin['monotonic_ns'], 'exact_line': exact,
              'stdout_file': str(stdout_path), 'stdout_sha256': sha(stdout_path),
              'ss_file': str(ss_path), 'ss_sha256': sha(ss_path),
              'scope': 'Operator-supplied Edge stdout and Edge-local ss; no Thor TCP probe'}
    save(OUT / 'EDGE_LISTENER_READY_CONFIRMATION.json', record)
    return record


def require_listener():
    pin = pinned_evidence()
    path = OUT / 'EDGE_LISTENER_READY_CONFIRMATION.json'
    if not path.is_file():
        raise RuntimeError('Listener-confirmed required before real workload')
    record = json.loads(path.read_text())
    if record.get('status') != 'PASS' or record.get('plan_sha256') != sha(PLAN) or \
            record.get('CPU_pin_monotonic_ns') != pin['monotonic_ns']:
        raise RuntimeError('Stale listener evidence')
    return record


def before_run(condition, directory):
    require_listener()
    fn = frozen_run.before_run
    return types.FunctionType(fn.__code__, dict(fn.__globals__, OUT=OUT))(condition, directory)


def supervisor_source():
    text = frozen_run.supervisor_source()
    old = "admission_fps_per_stream=c['admission_r'],edge_r=0,local_r=c['local_r'],cell=c['cell'],target_service_FPS=c['target_service_FPS'],supply_mode='A',deadline_ms=c['deadline_ms'],block='V22_TIMELY',admission_pattern='ALIGNED',pruning_enabled=True,"
    new = "admission_fps_per_stream=30,edge_r=c['edge_r'],local_r=c['local_r'],cell=c['cell'],target_service_FPS=c['target_service_FPS'],supply_mode='B',deadline_ms=100,block='V22_BLOCKB',admission_pattern=c['admission_pattern'],pruning_enabled=True,"
    if text.count(old) != 1:
        raise RuntimeError('Frozen parent seed changed')
    return text.replace(old, new, 1)


def validate_finished(directory, condition):
    from validate import validate_run
    report = validate_run(directory, condition)
    save(directory / 'block_b_integrity_validation.json', report)
    return report['status'] == 'PASS'


class Context(frozen_run.Context):
    def __init__(self):
        super().__init__()
        self.OUT, self.PLAN = OUT, PLAN
        self.PREFLIGHT = OUT / 'frequency_preflight.json'
        self.entry = HERE / 'run_thor.py'

    def load_plan(self):
        return load_plan()

    def bindings(self):
        fn = frozen_run.Context.bindings
        run, final = types.FunctionType(fn.__code__, dict(fn.__globals__,
            runtime_record=runtime_record, decorate=decorate))(self)

        def block_b_import(name, globals=None, locals=None, fromlist=(), level=0):
            if name == 'b1_summary' and level == 0:
                return block_b_summary
            return builtins.__import__(name, globals, locals, fromlist, level)

        def bind(func):
            ns = dict(func.__globals__, decorate=decorate,
                      __builtins__=dict(vars(builtins), __import__=block_b_import))
            return types.FunctionType(func.__code__, ns, func.__name__, func.__defaults__, func.__closure__)
        return bind(run), bind(final)

    def campaign(self, approval):
        if approval != sha(PLAN):
            raise RuntimeError('Exact Confirmation02 plan SHA approval required')
        self.check_inputs()
        if (OUT/'campaign_attempt.json').exists() or self.PREFLIGHT.exists() or \
                any((OUT/c['run_id']).exists() for c in order()):
            raise RuntimeError('Existing Confirmation02 attempt; no retry/resume/overwrite')
        require_listener()
        require_ready()
        fn = frozen_run.Context.campaign
        ns = dict(fn.__globals__, OUT=OUT, PLAN=PLAN, order=order,
                  load_plan=load_plan, runtime_record=runtime_record,
                  before_run=before_run, validate_finished=validate_finished,
                  supervisor_source=supervisor_source)
        try:
            return types.FunctionType(fn.__code__, ns, fn.__name__, fn.__defaults__, fn.__closure__)(self, approval)
        finally:
            print('USER CPU RESTORE REQUIRED before Edge raw transfer/analysis.', flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=('check','gpu-check','cpu-pinned','cpu-restored',
                                           'listener-confirmed','campaign','one'))
    parser.add_argument('--approve-plan-sha256')
    parser.add_argument('--run-id')
    parser.add_argument('--stdout-evidence')
    parser.add_argument('--ss-evidence')
    args = parser.parse_args()
    if args.action == 'check':
        Context().check_inputs()
        require_ready()
        network_check()
        print('PASS: source/cache/GPU permission/route; ICMP diagnostic only')
        return 0
    if args.action == 'gpu-check':
        report = observe()
        print(json.dumps(report, indent=2))
        return 0 if report['status'] == 'PASS' else 2
    if args.action in ('cpu-pinned','cpu-restored'):
        network = require_network()
        if args.action == 'cpu-pinned' and any((OUT/name).exists() for name in ('CPU_PIN_READBACK.json','CPU_RESTORE_READBACK.json')):
            raise RuntimeError('Stale CPU evidence')
        mode = args.action.split('-')[1]
        report = cpu.original.validate(cpu.snapshot(), json.loads((OUT/'CPU_STATE_BEFORE.json').read_text()), mode)
        report.update(plan_sha256=sha(PLAN), monotonic_ns=time.monotonic_ns(),
                      network_check_monotonic_ns=network['monotonic_ns'])
        save(OUT / ('CPU_PIN_READBACK.json' if mode == 'pinned' else 'CPU_RESTORE_READBACK.json'), report)
        return 0 if report['status'] == 'PASS' else 2
    if args.action == 'listener-confirmed':
        listener_confirmed(args.stdout_evidence, args.ss_evidence)
        return 0
    ctx = Context()
    if args.action == 'campaign':
        return ctx.campaign(args.approve_plan_sha256)
    plan = ctx.check_inputs()
    ctx.require_preflight()
    pinned_evidence()
    require_listener()
    matches = [c for c in plan['order'] if c['run_id'] == args.run_id]
    if len(matches) != 1 or not (OUT/'campaign_attempt.json').exists():
        raise RuntimeError('Fresh parent-approved run only')
    seed = OUT / args.run_id / 'manifest.json'
    if not seed.exists() or json.loads(seed.read_text()).get('child_has_started'):
        raise RuntimeError('Fresh parent seed required; no retry')
    return ctx.bindings()[0](matches[0], args.run_id)


if __name__ == '__main__':
    raise SystemExit(main())
