"""Block-A-only post-drain summary binding; frozen worker and timely scan stay intact."""
import json
import sys
import types
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parents[1] / 'timely_capacity_scan'))
import timely_summary
import timely_config
from phase_schedule import decorate as shifted_decorate
from pilot02_config import OUT, PLAN, PRIOR, PHASES, sha

read_csv = timely_summary.read_csv


def _condition(m, plan_path):
    if plan_path.resolve() not in (PLAN.resolve(), (PRIOR / 'plan.json').resolve()):
        raise ValueError('Block A summary accepts only frozen pilot01/pilot02 plans')
    plan = json.loads(plan_path.read_text())
    expected_sha = (plan_path.parent / 'plan.sha256').read_text().strip()
    if sha(plan_path) != expected_sha or m.get('plan_sha256') != expected_sha \
            or m.get('execution_manifest_sha256') != expected_sha:
        raise ValueError('Block A summary plan SHA mismatch')
    matches = [c for c in plan['order'] if c['run_id'] == m.get('run_id')]
    if len(matches) != 1:
        raise ValueError('Run ID outside frozen Block A plan')
    c = matches[0]
    for key in ('run_id', 'deadline_ms', 'target_service_FPS', 'admission_pattern',
                'edge_r', 'local_r', 'K', 'C', 'cell', 'repeat'):
        if m.get(key) != c.get(key):
            raise ValueError('Block A condition/manifest mismatch: ' + key)
    if c['deadline_ms'] not in (100, 67) or c['target_service_FPS'] != 208 \
            or c['edge_r'] != 0 or c['admission_pattern'] not in ('ALIGNED', 'STAGGERED'):
        raise ValueError('Outside frozen Block A pilot conditions')
    if m.get('batch_size') != 1 or m.get('pruning_enabled') is not True \
            or m.get('placement_schedule') != plan['placement']:
        raise ValueError('Block A runtime/placement manifest mismatch')
    if plan['placement']['phases'] != list(PHASES):
        raise ValueError('Frozen Block A phase tuple changed')
    return c


def summarize_with_plan(m, frames, power, plan_path):
    """Reuse the exact timely summary code with a plan-validated decorator."""
    c = _condition(m, Path(plan_path))

    def parameter_decorate(row, start, observed):
        if observed is not m or start != m['active_start_ns']:
            raise ValueError('Block A summary runtime binding mismatch')
        if c['admission_pattern'] == 'ALIGNED':
            return timely_config.decorate(row, start, c)
        return shifted_decorate(row, start, c, PHASES)

    fn = timely_summary.summarize
    bound = types.FunctionType(fn.__code__, dict(fn.__globals__, decorate=parameter_decorate),
                               fn.__name__, fn.__defaults__, fn.__closure__)
    return bound(m, frames, power)


def summarize(m, frames, power):
    return summarize_with_plan(m, frames, power, PLAN)
