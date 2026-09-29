"""Fresh Block A attempt configuration. The pilot01 phase set is frozen, not searched."""
import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PILOT = HERE.parent
sys.path.insert(0, str(PILOT))
sys.path.insert(0, str(PILOT.parent / 'timely_capacity_scan'))
import timely_config as timely
from phase_schedule import CANONICAL_BITS, PATTERN_SHA256, decorate as shifted_decorate

ROOT = timely.ROOT
PRIOR = ROOT / 'results/timely_capacity_campaign/v2_2/block_a_phase_pilot01'
OUT = ROOT / 'results/timely_capacity_campaign/v2_2/block_a_phase_pilot02'
PLAN = OUT / 'plan.json'
PHASES = (0, 1, 2, 3, 4, 5, 6, 7)
sha = timely.sha
run_source = timely.run_source
SEQUENCE = ((100, 'A', 1), (100, 'S', 1), (100, 'S', 2), (100, 'A', 2),
            (67, 'A', 1), (67, 'S', 1), (67, 'S', 2), (67, 'A', 2))


def order():
    rows = []
    old = timely.order()
    for deadline, token, repeat in SEQUENCE:
        source = next(row for row in old if row['deadline_ms'] == deadline
                      and row['target_service_FPS'] == 208 and row['repeat'] == 1)
        row = dict(source)
        pattern = 'ALIGNED' if token == 'A' else 'STAGGERED'
        row.update(run_id=f'V22_BLOCKA_D{deadline}_{token}{repeat}_P02', repeat=repeat,
                   order_index=len(rows) + 1, admission_pattern=pattern,
                   cell=f'BLOCKA-D{deadline}-{pattern}', original_cell=source['cell'],
                   analysis_class='EQUAL_RATE_CROSS_STREAM_TEMPORAL_PHASE_PILOT',
                   pass_name=f'{token}{repeat}', **{'pass': f'{token}{repeat}'})
        rows.append(row)
    return rows


def decorate(row, start, condition):
    if condition['admission_pattern'] == 'ALIGNED':
        return timely.decorate(row, start, condition)
    if condition['admission_pattern'] == 'STAGGERED':
        return shifted_decorate(row, start, condition, PHASES)
    raise ValueError('Outside Block A pilot pattern')


def runtime_record():
    result = timely.frozen.runtime_record()
    source = run_source()
    if source != (timely.frozen.OUT / 'effective_runtime.txt').read_text():
        raise RuntimeError('Frozen V2.2 worker changed')
    for relative, digest in json.loads((OUT / 'source_sha256.json').read_text()).items():
        if sha(ROOT / relative) != digest:
            raise RuntimeError('Pilot02 source drift: ' + relative)
    return dict(result, block_a_pilot_plan_sha256=sha(PLAN),
                worker_source_sha256=hashlib.sha256(source.encode()).hexdigest(),
                pattern_sha256=PATTERN_SHA256, cross_stream_phases=list(PHASES))


def load_plan():
    plan = json.loads(PLAN.read_text())
    if sha(PLAN) != (OUT / 'plan.sha256').read_text().strip():
        raise RuntimeError('Pilot02 plan SHA mismatch')
    if plan['order'] != order() or plan['source_phase_ns'] != [0] * 8 \
            or plan['idle_seconds'] != 10 or plan['smoke']:
        raise RuntimeError('Pilot02 order/source/idle mismatch')
    if plan['placement']['canonical_bits'] != CANONICAL_BITS \
            or plan['placement']['phases'] != list(PHASES) \
            or plan['placement']['canonical_pattern_sha256'] != PATTERN_SHA256:
        raise RuntimeError('Pilot02 frozen phase schedule mismatch')
    for name, expected in plan['artifact_sha256'].items():
        if sha(OUT / name) != expected:
            raise RuntimeError('Pilot02 frozen artifact drift: ' + name)
    if sha(HERE / 'block_a_summary.py') != plan['summary_adapter_sha256']:
        raise RuntimeError('Pilot02 summary adapter drift')
    runtime_record()
    return plan
