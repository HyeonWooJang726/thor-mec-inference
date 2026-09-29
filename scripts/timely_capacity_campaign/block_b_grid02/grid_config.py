"""Block B placement-only adapter over the frozen V2.2 worker."""
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OUT = ROOT / 'results/timely_capacity_campaign/v2_2/block_b_grid02'
PLAN = OUT / 'plan.json'
sys.path.insert(0, str(HERE.parent / 'common'))
import campaign_config as canonical
sys.path.insert(0, str(HERE.parent / 'common' / 'v2_2'))
import v22_config as frozen
from v22_builder import run_source

RATES = (216, 208, 200)
PHASES = tuple(range(8))
ROUNDS = (
    ((216,'A'),(216,'S'),(208,'S'),(208,'A'),(200,'A'),(200,'S')),
    ((208,'A'),(208,'S'),(200,'A'),(200,'S'),(216,'S'),(216,'A')),
    ((200,'S'),(200,'A'),(216,'S'),(216,'A'),(208,'A'),(208,'S')),
    ((216,'A'),(216,'S'),(200,'S'),(200,'A'),(208,'S'),(208,'A')),
    ((208,'S'),(208,'A'),(216,'A'),(216,'S'),(200,'A'),(200,'S')),
)
sha = canonical.sha


def p(rate):
    if rate not in RATES:
        raise ValueError('Unplanned Local rate')
    masks, edge = canonical.schedule(rate, 0, 'ALIGNED')
    if edge or any(mask != masks[0] for mask in masks):
        raise RuntimeError('Canonical floor-mask drift')
    bits = tuple(int(n in masks[0]) for n in range(30))
    if sum(bits) != rate // 8:
        raise RuntimeError('Canonical mask count drift')
    return bits


def local_bit(rate, pattern, sid, frame):
    if pattern not in ('ALIGNED','STAGGERED') or sid not in range(8) or frame < 0:
        raise ValueError('Unplanned source slot')
    return p(rate)[(frame - (sid if pattern == 'STAGGERED' else 0)) % 30]


def slot_order(rate, pattern, frame, destination):
    if destination not in ('LOCAL','EDGE'):
        raise ValueError('Destination')
    return [sid for sid in range(8) if
            ('LOCAL' if local_bit(rate, pattern, sid, frame) else 'EDGE') == destination]


def edge_id(rate, pattern, sid, frame):
    if local_bit(rate, pattern, sid, frame):
        raise ValueError('Local frame has no Edge ID')
    edge_rate = 240-rate
    position = sum(1-local_bit(rate, pattern, k, n)
                   for n in range(frame % 30) for k in range(8))
    position += slot_order(rate, pattern, frame, 'EDGE').index(sid)
    return frame // 30 * edge_rate + position


def masks(rate, pattern):
    local = [[local_bit(rate, pattern, sid, n) for n in range(30)] for sid in range(8)]
    edge = [[1-x for x in row] for row in local]
    m_l = [sum(local[sid][n] for sid in range(8)) for n in range(30)]
    m_e = [8-x for x in m_l]
    return {'local_masks': local, 'edge_masks': edge, 'm_L': m_l, 'm_E': m_e,
            'edge_peak': max(m_e), 'edge_histogram': dict(sorted(Counter(m_e).items())),
            'local_count_per_stream_per_30': [sum(x) for x in local],
            'edge_count_per_stream_per_30': [sum(x) for x in edge],
            'phase_vector': [0]*8 if pattern == 'ALIGNED' else list(PHASES)}


def decorate(row, start, c):
    """Only assign destination/deadline/Edge IDs; source timing is untouched."""
    sid, frame = int(row['stream_id']), int(row['frame_id'])
    due = start + frame * 10**9 // 30
    if sid not in range(8) or row['logical_arrival_ns'] != due:
        raise ValueError('Source due mismatch')
    rate, pattern = c['target_service_FPS'], c['admission_pattern']
    local = local_bit(rate, pattern, sid, frame)
    destination = 'LOCAL' if local else 'EDGE'
    row['admitted'] = 1
    row['placement'] = destination
    row['absolute_deadline_ns'] = due + 100_000_000
    row.pop('edge_request_id', None)
    row.pop('edge_release_target_ns', None)
    if not local:
        row['edge_request_id'] = edge_id(rate, pattern, sid, frame)
        row['edge_release_target_ns'] = due
    return row


def condition(rate, token, repeat, index, warmup=False):
    pattern = 'ALIGNED' if token == 'A' else 'STAGGERED'
    source = dict(json.loads((frozen.OUT / 'plan.json').read_text())['order'][0])
    rid = 'BLOCKB02_WARMUP_L200_E40_S' if warmup else f'BLOCKB02_L{rate}_{token}{repeat}'
    source.update(run_id=rid, kind='formal', repeat=repeat, order_index=index,
        cell=f'BLOCKB-L{rate}E{240-rate}-{pattern}', original_cell=f'BLOCKB-L{rate}E{240-rate}-{pattern}',
        block='V22_BLOCKB', supply_mode='B', admission_pattern=pattern,
        target_service_FPS=rate, local_r=rate/8, edge_r=(240-rate)//8,
        admission_r=30, admitted_FPS=240, source_demand_FPS=240,
        deadline_ms=100, seconds=15 if warmup else 60,
        pass_name='WARMUP' if warmup else f'{token}{repeat}',
        **{'pass':'WARMUP' if warmup else f'{token}{repeat}'},
        analysis_class='BLOCK_B_GRID02', pruning_enabled=True)
    return source


def order():
    rows = [condition(200, 'S', 0, 1, True)]
    for repeat, sequence in enumerate(ROUNDS, 1):
        for rate, token in sequence:
            rows.append(condition(rate, token, repeat, len(rows)+1))
    return rows


def runtime_record():
    record = frozen.runtime_record()
    if run_source() != (frozen.OUT / 'effective_runtime.txt').read_text():
        raise RuntimeError('V2.2 worker not byte-identical')
    for relative, digest in json.loads((OUT / 'source_sha256.json').read_text()).items():
        if sha(ROOT / relative) != digest:
            raise RuntimeError('Block B source drift: ' + relative)
    return dict(record, block_b_plan_sha256=sha(PLAN),
                worker_source_sha256=hashlib.sha256(run_source().encode()).hexdigest())


def load_plan():
    plan = json.loads(PLAN.read_text())
    if sha(PLAN) != (OUT / 'plan.sha256').read_text().strip() or plan['order'] != order():
        raise RuntimeError('Block B frozen plan/order mismatch')
    if plan['source_phase_ns'] != [0]*8 or plan['idle_seconds'] != 10 or plan['smoke']:
        raise RuntimeError('Block B source/idle/smoke mismatch')
    for name, digest in plan['artifact_sha256'].items():
        if sha(OUT / name) != digest:
            raise RuntimeError('Block B frozen artifact drift: '+name)
    runtime_record()
    return plan
