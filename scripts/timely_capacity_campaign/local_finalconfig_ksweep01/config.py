"""K-aware, C_L=3 binding of the frozen V2.2 full Local worker."""
import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OUT = ROOT / 'results/timely_capacity_campaign/v2_2/local_finalconfig_ksweep01'
PLAN = OUT / 'plan.json'
RAW = ROOT / 'results/timely_capacity_campaign/v2_2/raw_capacity_scan01'
sys.path.insert(0, str(HERE.parent / 'common/v2_2'))
import v22_config as frozen
from v22_builder import run_source as frozen_run_source

sha = frozen.sha
K_VALUES = tuple(range(1, 9))
ORDER = tuple((k, rep) for rep in range(1, 6)
              for k in (K_VALUES if rep % 2 else tuple(reversed(K_VALUES))))
_C1_CONTEXT_ANCHOR = 'runtime=ConcurrentTensorRT(str(ENGINE),2)'
_SUMMARY_ANCHOR = 'from b1_summary import summarize'


def run_source():
    """Keep the worker/queue path; bind strict Local-only K admission."""
    source = frozen_run_source()
    if source.count(_C1_CONTEXT_ANCHOR) != 1:
        raise RuntimeError('Frozen C1 context-construction anchor changed')
    source = source.replace(_C1_CONTEXT_ANCHOR,
                            'runtime=ConcurrentTensorRT(str(ENGINE),min(c,2))')
    if source.count(_SUMMARY_ANCHOR) != 1:
        raise RuntimeError('Frozen summary binding anchor changed')
    source = source.replace(_SUMMARY_ANCHOR,
        'from summary_adapter import summarize\n    from ksweep_schedule import decorate')
    old = "local_assigned_fps=8*condition['local_r'], edge_assigned_fps=8*condition['edge_r']"
    new = "local_assigned_fps=k*condition['local_r'], edge_assigned_fps=k*condition['edge_r']"
    if source.count(old) != 1:
        raise RuntimeError('Frozen K-assignment manifest anchor changed')
    source = source.replace(old, new)
    old = "admission_fps_per_stream=condition['target_service_FPS']//8"
    if source.count(old) != 1:
        raise RuntimeError('Frozen K-admission manifest anchor changed')
    return source.replace(old, "admission_fps_per_stream=condition['target_service_FPS']//k")


def order():
    rows = []
    for index, (k, repeat) in enumerate(ORDER, 1):
        row = dict(frozen.order()[1])  # V2.2 pruning-OFF Local-only reference.
        offered = 30 * k
        row.update(run_id=f'LOCALFINALKS01_K{k}_R{repeat}',
            repeat=repeat, order_index=index, K=k, C=3,
            target_service_FPS=offered, local_r=30, admission_r=30,
            admitted_FPS=offered, source_demand_FPS=offered, r=30, edge_r=0,
            cell=f'LOCAL_K{k}_C3', original_cell=f'LOCAL_K{k}_C3',
            block='V22_RAW', analysis_class='LOCAL_FINALCONFIG_KSWEEP',
            pass_name=f'R{repeat}', **{'pass':f'R{repeat}'},
            pruning_enabled=False, source_normalization_FPS=offered)
        rows.append(row)
    return rows


def runtime_record():
    manifest = json.loads((RAW/'FINAL_RUNTIME_MANIFEST.json').read_text())
    expected = manifest['effective_runtime_sha256']
    if sha(frozen.OUT/'effective_runtime.txt') != expected or \
            hashlib.sha256(frozen_run_source().encode()).hexdigest() != expected:
        raise RuntimeError('Frozen V2.2 worker source changed')
    derived = hashlib.sha256(run_source().encode()).hexdigest()
    if PLAN.exists() and json.loads(PLAN.read_text()).get('ksweep_worker_sha256') != derived:
        raise RuntimeError('K-sweep worker binding source drift')
    for relative, digest in json.loads((OUT/'source_sha256.json').read_text()).items():
        if sha(ROOT/relative) != digest:
            raise RuntimeError('Calibration preparation source drift: '+relative)
    return dict(frozen.runtime_record(), frozen_worker_sha256=expected,
        ksweep_worker_sha256=derived,
        ksweep_plan_sha256=sha(PLAN))


def load_plan():
    plan = json.loads(PLAN.read_text())
    if sha(PLAN) != (OUT/'plan.sha256').read_text().strip() or \
            plan['order'] != order() or plan['idle_seconds'] != 10 or \
            plan['source_phase_ns'] != [0]*8 or plan['smoke'] or \
            plan['runtime']['B'] != 1:
        raise RuntimeError('K-sweep plan/order drift')
    runtime_record()
    return plan
