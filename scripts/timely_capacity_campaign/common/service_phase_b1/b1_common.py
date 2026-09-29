"""B1-only frozen configuration/source adapter. Import performs no device operations."""
import hashlib
import inspect
import json
from pathlib import Path
import sys
import textwrap

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
OUT = ROOT / 'results/timely_capacity_campaign/pruning_path_audit/service_phase_validation/b1_01'
PLAN = OUT / 'plan.json'
B0_ROOT = OUT.parent / 'b0_01'
B0_RUN = B0_ROOT / 'SPI_B0_S240_L176E64_ON_P01'
sys.path.insert(0, str(HERE.parent / 'service_phase_v1'))
sys.path.insert(0, str(HERE.parent / 'service_phase_b0'))
import build_adapter


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda: f.read(1048576), b''):
            h.update(chunk)
    return h.hexdigest()


def order():
    result = []
    for index, (enabled, repeat) in enumerate(((False, 1), (True, 1), (True, 2), (False, 2)), 1):
        mode = 'ON' if enabled else 'OFF'
        result.append(dict(run_id=f'SPI_B1_LOCAL200_{mode}_R{repeat}_P01', kind='formal',
            repeat=repeat, order_index=index, cell=f'LOCAL200-{mode}', block='B1',
            supply_mode='A', admission_pattern='ALIGNED', target_service_FPS=200,
            local_r=25, edge_r=0, deadline_ms=100, K=8, C=2, r=30,
            frequency='F1575', frequency_MHz=1575, seconds=60,
            pass_name=f'R{repeat}', **{'pass': f'R{repeat}'},
            source_demand_FPS=200, admitted_FPS=200, admission_r=25,
            original_cell=f'LOCAL200-{mode}', analysis_class='B1-LOCAL-ONLY',
            branch_E_max=None, source_normalization_FPS=240, pruning_enabled=enabled))
    return result


def load_plan():
    p = json.loads(PLAN.read_text())
    if sha(PLAN) != PLAN.with_suffix('.sha256').read_text().split()[0]:
        raise RuntimeError('B1 frozen plan hash mismatch')
    if p['order'] != order() or p['smoke'] or p['source_phase_ns'] != [0]*8 or p['idle_seconds'] != 10:
        raise RuntimeError('B1 ABBA/fixed configuration mismatch')
    if json.loads((B0_ROOT/'analysis01/B0_VALIDATION.json').read_text())['verdict'] != 'B0_INSTRUMENTATION_VALID':
        raise RuntimeError('Valid B0 prerequisite missing')
    return p


def off_begin_source(pruning_type):
    """Disable ONLY the expiration predicate; keep B0 timestamp/bookkeeping positions.

    Calling legacy QueueAccounting.start would move service_start to AFTER event
    bookkeeping. Deliberately avoid that measurement-definition confound.
    """
    s = textwrap.dedent(inspect.getsource(pruning_type.begin))
    return build_adapter.replace_one(s, "if stamp>=job['absolute_deadline_ns']:", 'if False:  # B1 OFF: expiry disabled')


def make_accounting(enabled):
    from pruning_common import PruningAccounting
    if enabled:
        return PruningAccounting()
    class NoExpiryAccounting(PruningAccounting):
        pass
    ns = dict(PruningAccounting.begin.__globals__)
    exec(compile(off_begin_source(PruningAccounting), '<B1-OFF-only-predicate>', 'exec'), ns)
    NoExpiryAccounting.begin = ns['begin']
    return NoExpiryAccounting()


def run_source():
    s = build_adapter.run_source()
    s = build_adapter.replace_one(s, 'from analysis_21 import summarize', 'from b1_summary import summarize')
    s = build_adapter.replace_one(s, 'from pruning_common import PruningAccounting as QueueAccounting',
                                 'from b1_common import make_accounting')
    s = build_adapter.replace_one(s, 'accounting=QueueAccounting()',
                                 "accounting=make_accounting(condition['pruning_enabled'])")
    s = build_adapter.replace_one(s, "manifest['execution_runtime']=runtime_record()",
                                 "manifest['execution_runtime']=runtime_record()\n    manifest['pruning_enabled']=condition['pruning_enabled']")
    return s


def runtime_record():
    p = OUT/'runtime_manifest.json'
    if sha(p) != (OUT/'runtime_manifest.sha256').read_text().split()[0]:
        raise RuntimeError('B1 runtime manifest changed')
    record = json.loads(p.read_text())
    for path, digest in record['source_sha256'].items():
        if sha(ROOT/path) != digest:
            raise RuntimeError('B1 frozen dependency changed: '+path)
    return dict(version='SERVICE_PHASE_B1', condition_plan_sha256=sha(PLAN),
                runtime_manifest_sha256=sha(p), source_sha256=record['source_sha256'])
