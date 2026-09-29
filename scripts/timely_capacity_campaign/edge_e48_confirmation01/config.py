"""Frozen E48 confirmation masks, order, and CPU-only fidelity checks."""
import hashlib
import ipaddress
import json
import math
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OUT = ROOT / 'results/timely_capacity_campaign/v2_2/edge_e48_confirmation01'
PLAN = OUT / 'plan.json'
PHASES = (0, 1, 2, 3, 4, 5, 6, 7)
RATES = (48, 64)
IDLE_SECONDS = 10
PAYLOAD_BYTES = 691200
sys.path.insert(0, str(HERE.parent / 'common'))
import campaign_config as canonical


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def q(rate):
    if rate not in RATES:
        raise ValueError('Unplanned Edge rate')
    r = rate // 8
    masks, placements = canonical.schedule(rate, 0, 'ALIGNED')
    if placements or any(mask != masks[0] for mask in masks):
        raise RuntimeError('Canonical aligned admission changed')
    bits = tuple(int(slot in masks[0]) for slot in range(30))
    if sum(bits) != r:
        raise RuntimeError('Canonical rate mismatch')
    return bits


def bit(rate, pattern, stream_id, frame_id):
    if pattern not in ('ALIGNED', 'STAGGERED') or stream_id not in range(8) or frame_id < 0:
        raise ValueError('Outside frozen source-slot plan')
    shift = 0 if pattern == 'ALIGNED' else PHASES[stream_id]
    return q(rate)[(frame_id - shift) % 30]


def schedule(rate, pattern):
    masks = [[bit(rate, pattern, sid, slot) for slot in range(30)] for sid in range(8)]
    counts = [sum(mask[slot] for mask in masks) for slot in range(30)]
    mean = sum(counts) / 30
    sorted_counts = sorted(counts)
    p95_position = (len(sorted_counts) - 1) * .95
    p95_lower = int(p95_position)
    p95 = sorted_counts[p95_lower] + (sorted_counts[min(p95_lower + 1, 29)] -
                                     sorted_counts[p95_lower]) * (p95_position - p95_lower)
    bound = math.ceil(rate / 30)
    return {'rate_FPS': rate, 'pattern': pattern,
            'phases': [0] * 8 if pattern == 'ALIGNED' else list(PHASES),
            'per_stream_masks': masks, 'per_stream_admissions_per_30_slots': [sum(mask) for mask in masks],
            'm_n': counts, 'mean_m_n': mean, 'p95_m_n': p95, 'max_m_n': max(counts),
            'theoretical_peak_lower_bound': bound, 'peak_minus_lower_bound': max(counts) - bound,
            'variance_population': sum((x - mean) ** 2 for x in counts) / 30,
            'histogram': dict(sorted(Counter(counts).items())),
            'global_optimality_claim': False, 'phase_search_used': False}


def condition(rate, pattern, repeat, stage, index):
    if rate not in RATES or pattern not in ('ALIGNED', 'STAGGERED'):
        raise ValueError('Unplanned condition')
    if stage == 'WARMUP':
        if (rate, pattern, repeat) != (48, 'STAGGERED', 0): raise ValueError('Invalid warm-up')
        run_id, seconds = 'EDGE48C01_WARMUP_E48_S', 15
    else:
        if repeat not in (1, 2, 3, 4, 5) or (stage == 'HEADROOM' and (rate, pattern, repeat) not in
             ((64, 'STAGGERED', 1), (64, 'STAGGERED', 2), (64, 'STAGGERED', 3))):
            raise ValueError('Invalid measured condition')
        token = 'A' if pattern == 'ALIGNED' else 'S'
        run_id, seconds = f'EDGE48C01_E{rate}_{token}{repeat}', 30
    return {'run_id': run_id, 'stage': stage,
            'rate': rate, 'per_stream_rate': rate // 8, 'pattern': pattern,
            'repeat': repeat, 'order_index': index, 'seconds': seconds,
            'deadline_ms': 100, 'source_streams': 8, 'source_FPS_per_stream': 30,
            'phase_vector': [0] * 8 if pattern == 'ALIGNED' else list(PHASES),
            'edge_C': 1, 'edge_B': 1}


def frozen_order():
    rows = [condition(48, 'STAGGERED', 0, 'WARMUP', 1)]
    for pattern, repeat in (('ALIGNED',1),('STAGGERED',1),('STAGGERED',2),('ALIGNED',2),
                            ('ALIGNED',3),('STAGGERED',3),('STAGGERED',4),('ALIGNED',4),
                            ('ALIGNED',5),('STAGGERED',5)):
        rows.append(condition(48, pattern, repeat, 'CONFIRMATION', len(rows)+1))
    for repeat in (1,2,3):
        rows.append(condition(64, 'STAGGERED', repeat, 'HEADROOM', len(rows)+1))
    return rows


def robust_class(rows):
    if any(r.get('integrity_status') != 'VALID' or r.get('TIR_admission') is None
           or r.get('scientific_result_eligible') is False for r in rows):
        return 'INVALID'
    if len(rows) != 5 or {r.get('repeat') for r in rows} != {1,2,3,4,5} \
            or any(r.get('rate') != 48 for r in rows):
        return 'INCOMPLETE'
    vals = [r['TIR_admission'] for r in rows]
    if all(value >= .90 for value in vals):
        return 'ROBUST_EDGE_USABLE'
    if all(value < .80 for value in vals):
        return 'ROBUST_EDGE_FAIL'
    return 'ROBUST_EDGE_BOUNDARY'


def hello(condition, digest, cache_sha):
    return {'mode': 'edge_e48_confirmation01', 'rate': condition['rate'],
            'seconds': condition['seconds'], 'repeat': condition['repeat'], 'run_id': condition['run_id'],
            'campaign_plan_sha256': digest, 'cache_sha256': cache_sha,
            'payload_origin': 'CACHED_REAL_RAW640_30; K8_30FPS_SOURCE_SLOT_SELECTION',
            'deadline_ms': 100, 'admission_pattern': condition['pattern'],
            'phase_vector': condition['phase_vector'], 'stage': condition['stage']}


def validate_source_rows(rows, condition, active_start_ns):
    """Hard actual source-slot/admission/relative-order fidelity, including skips."""
    errors = []
    seconds = condition['seconds']
    expected = seconds * 30 * 8
    if len(rows) != expected:
        errors.append(f'source row count {len(rows)} != {expected}')
    by_id = {}
    actual_m = [0] * (seconds * 30)
    admitted = [0] * 8
    ids = []
    for row in rows:
        try:
            sid, frame = int(row['stream_id']), int(row['frame_id'])
            if sid not in range(8) or frame not in range(seconds * 30) or (sid, frame) in by_id:
                errors.append(f'duplicate/out-of-range source ID {(sid, frame)}')
                continue
            by_id[sid, frame] = row
            due = active_start_ns + frame * 10**9 // 30
            if int(row['logical_arrival_ns']) != due or int(row['admission_timestamp_ns']) != due:
                errors.append(f'source due changed {(sid, frame)}')
            actual = int(row['admitted'])
            if actual != bit(condition['rate'], condition['pattern'], sid, frame):
                errors.append(f'admission mask mismatch {(sid, frame)}')
            if row['placement'] != ('EDGE' if actual else 'SKIP'):
                errors.append(f'placement mismatch {(sid, frame)}')
            if actual:
                admitted[sid] += 1
                actual_m[frame] += 1
                ids.append(int(row['edge_request_id']))
                if int(row['edge_release_target_ns']) != due or int(row['absolute_deadline_ns']) != due + 100_000_000:
                    errors.append(f'deferred/deadline mismatch {(sid, frame)}')
            elif row.get('edge_request_id') not in (None, ''):
                errors.append(f'skipped source frame has Edge ID {(sid, frame)}')
        except (KeyError, TypeError, ValueError) as exc:
            errors.append(f'malformed source row: {exc!r}')
    if len(by_id) != expected:
        errors.append('source ID universe incomplete')
    wanted = seconds * condition['per_stream_rate']
    if admitted != [wanted] * 8 or len(ids) != seconds * condition['rate'] \
            or ids != list(range(seconds * condition['rate'])):
        errors.append('per-stream/aggregate Edge IDs or frame order mismatch')
    planned = schedule(condition['rate'], condition['pattern'])['m_n']
    for frame in range(seconds * 30):
        if actual_m[frame] != planned[frame % 30]:
            errors.append(f'planned-vs-actual m_n mismatch slot {frame}')
        slot = [by_id.get((sid, frame)) for sid in range(8)]
        if any(row is None for row in slot):
            continue
        observed = sorted(slot, key=lambda row: int(row['admission_observed_ns']))
        if [int(row['stream_id']) for row in observed] != list(range(8)):
            errors.append(f'canonical-relative dispatch order mismatch slot {frame}')
        if any(int(row['admission_observed_ns']) < int(row['logical_arrival_ns']) for row in slot):
            errors.append(f'observed before source due slot {frame}')
    return {'status': 'PASS' if not errors else 'FAIL', 'errors': errors[:100],
            'source_rows': len(rows), 'per_stream_admitted': admitted,
            'actual_m_n_first_period': actual_m[:30],
            'actual_slot_histogram': dict(sorted(Counter(actual_m).items())),
            'planned_m_n_first_period': planned,
            'actual_total_admitted': len(ids), 'no_deferred_admission': not any('deferred' in e for e in errors)}


def load_plan():
    plan = json.loads(PLAN.read_text())
    if sha(PLAN) != (OUT / 'plan.sha256').read_text().strip():
        raise RuntimeError('Plan SHA mismatch')
    if plan['order'] != frozen_order() or plan['idle_seconds'] != IDLE_SECONDS \
            or plan['phase_vector_staggered'] != list(PHASES) or plan['payload_bytes'] != PAYLOAD_BYTES:
        raise RuntimeError('Frozen duration/phase/payload mismatch')
    endpoint_path = OUT / 'EDGE_ENDPOINT_MANIFEST.json'
    endpoint = json.loads(endpoint_path.read_text())
    if sha(endpoint_path) != plan['endpoint_manifest_sha256'] \
            or plan['edge_ip'] != plan['edge_host'] \
            or endpoint['edge_ip'] != plan['edge_ip'] \
            or ipaddress.ip_address(plan['edge_ip']).version != 4:
        raise RuntimeError('Frozen Edge endpoint/manifest mismatch')
    if sha(OUT / 'source_sha256.json') != plan['source_sha256_manifest_sha256']:
        raise RuntimeError('Frozen source manifest SHA mismatch')
    for name, digest in plan['artifact_sha256'].items():
        if sha(OUT / name) != digest:
            raise RuntimeError('Frozen plan artifact drift: ' + name)
    for name, digest in json.loads((OUT / 'source_sha256.json').read_text()).items():
        if sha(ROOT / name) != digest:
            raise RuntimeError('Source SHA mismatch: ' + name)
    return plan
