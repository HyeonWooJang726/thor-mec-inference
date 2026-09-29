"""Fresh calibration05 binding of the frozen V2.2 full Local worker."""
import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OUT = ROOT / 'results/timely_capacity_campaign/v2_2/local_inflight_calibration05'
PLAN = OUT / 'plan.json'
RAW = ROOT / 'results/timely_capacity_campaign/v2_2/raw_capacity_scan01'
sys.path.insert(0, str(HERE.parent / 'common/v2_2'))
import v22_config as frozen
from v22_builder import run_source as frozen_run_source

sha = frozen.sha
C_VALUES = (3, 4, 5, 6)
ORDER = ((3, 1), (4, 1), (5, 1), (6, 1),
         (6, 2), (5, 2), (4, 2), (3, 2))
_C1_CONTEXT_ANCHOR = 'runtime=ConcurrentTensorRT(str(ENGINE),2)'
_SUMMARY_ANCHOR = 'from b1_summary import summarize'


def run_source():
    """Bind initial contexts to planned C; retain the frozen worker/queue path."""
    source = frozen_run_source()
    if source.count(_C1_CONTEXT_ANCHOR) != 1:
        raise RuntimeError('Frozen C1 context-construction anchor changed')
    source = source.replace(_C1_CONTEXT_ANCHOR,
                            'runtime=ConcurrentTensorRT(str(ENGINE),min(c,2))')
    if source.count(_SUMMARY_ANCHOR) != 1:
        raise RuntimeError('Frozen summary binding anchor changed')
    return source.replace(_SUMMARY_ANCHOR, 'from summary_adapter import summarize')


def order():
    rows = []
    for index, (concurrency, repeat) in enumerate(ORDER, 1):
        row = dict(frozen.order()[1])  # V2.2 pruning-OFF Local-only reference.
        row.update(run_id=f'LINFLIGHT05_C{concurrency}_R{repeat}',
            repeat=repeat, order_index=index, C=concurrency,
            target_service_FPS=240, local_r=30, admission_r=30,
            admitted_FPS=240, source_demand_FPS=240, r=30, edge_r=0,
            cell=f'LOCAL240-OFF-C{concurrency}',
            original_cell=f'LOCAL240-OFF-C{concurrency}',
            block='V22_RAW', analysis_class='LOCAL_INFLIGHT_CALIBRATION',
            pass_name=f'R{repeat}', **{'pass':f'R{repeat}'},
            pruning_enabled=False)
        rows.append(row)
    return rows


def runtime_record():
    manifest = json.loads((RAW/'FINAL_RUNTIME_MANIFEST.json').read_text())
    expected = manifest['effective_runtime_sha256']
    if sha(frozen.OUT/'effective_runtime.txt') != expected or \
            hashlib.sha256(frozen_run_source().encode()).hexdigest() != expected:
        raise RuntimeError('Frozen V2.2 worker source changed')
    derived = hashlib.sha256(run_source().encode()).hexdigest()
    if PLAN.exists() and json.loads(PLAN.read_text()).get('calibration_worker_sha256') != derived:
        raise RuntimeError('Calibration C-aware binding source drift')
    for relative, digest in json.loads((OUT/'source_sha256.json').read_text()).items():
        if sha(ROOT/relative) != digest:
            raise RuntimeError('Calibration preparation source drift: '+relative)
    return dict(frozen.runtime_record(), frozen_worker_sha256=expected,
                calibration_worker_sha256=derived,
                calibration_plan_sha256=sha(PLAN))


def load_plan():
    plan = json.loads(PLAN.read_text())
    if sha(PLAN) != (OUT/'plan.sha256').read_text().strip() or \
            plan['order'] != order() or plan['idle_seconds'] != 10 or \
            plan['source_phase_ns'] != [0]*8 or plan['smoke']:
        raise RuntimeError('Calibration plan/order drift')
    runtime_record()
    return plan
