"""Frozen Edge-only source-slot masks and result-independent branch rules."""
import hashlib
import ipaddress
import json
import math
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OUT = ROOT / 'results/timely_capacity_campaign/v2_2/edge_preflight_final02'
PLAN = OUT / 'plan.json'
PHASES = (0, 1, 2, 3, 4, 5, 6, 7)
RATES = (72, 80, 88)
SECONDS = 30
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
    bound = math.ceil(rate / 30)
    return {'rate_FPS': rate, 'pattern': pattern,
            'phases': [0] * 8 if pattern == 'ALIGNED' else list(PHASES),
            'per_stream_masks': masks, 'per_stream_admissions_per_30_slots': [sum(mask) for mask in masks],
            'm_n': counts, 'mean_m_n': mean, 'max_m_n': max(counts),
            'theoretical_peak_lower_bound': bound, 'peak_minus_lower_bound': max(counts) - bound,
            'variance_population': sum((x - mean) ** 2 for x in counts) / 30,
            'histogram': dict(sorted(Counter(counts).items())),
            'global_optimality_claim': False, 'phase_search_used': False}


def condition(rate, pattern, repeat, stage, index):
    if rate not in RATES or pattern not in ('ALIGNED', 'STAGGERED') or repeat not in (1, 2):
        raise ValueError('Unplanned condition')
    token = 'A' if pattern == 'ALIGNED' else 'S'
    return {'run_id': f'EDGEF02_E{rate}_{token}{repeat}', 'stage': stage,
            'rate': rate, 'per_stream_rate': rate // 8, 'pattern': pattern,
            'repeat': repeat, 'order_index': index, 'seconds': SECONDS,
            'deadline_ms': 100, 'source_streams': 8, 'source_FPS_per_stream': 30,
            'phase_vector': [0] * 8 if pattern == 'ALIGNED' else list(PHASES),
            'edge_C': 1, 'edge_B': 1}


def base_order():
    rows = []
    for rate in (72, 80):
        for pattern, repeat in (('ALIGNED', 1), ('STAGGERED', 1),
                                ('STAGGERED', 2), ('ALIGNED', 2)):
            rows.append(condition(rate, pattern, repeat, 'BASE', len(rows) + 1))
    return rows


def extension_orders():
    sequences = {'NONE': (),
                 'ALIGNED_ONLY': (('ALIGNED', 1), ('ALIGNED', 2)),
                 'STAGGERED_ONLY': (('STAGGERED', 1), ('STAGGERED', 2)),
                 'BOTH': (('ALIGNED', 1), ('STAGGERED', 1),
                          ('STAGGERED', 2), ('ALIGNED', 2))}
    return {branch: [condition(88, pattern, repeat, 'EXTENSION', i + 1)
                     for i, (pattern, repeat) in enumerate(seq)]
            for branch, seq in sequences.items()}


def run_class(rows):
    if any(r.get('integrity_status') != 'VALID' or r.get('TIR_admission') is None
           or r.get('scientific_result_eligible') is False for r in rows):
        return 'INVALID'
    if len(rows) != 2 or {r.get('repeat') for r in rows} != {1, 2}:
        return 'INCOMPLETE'
    vals = [r['TIR_admission'] for r in rows]
    if all(value >= .90 for value in vals):
        return 'EDGE_USABLE'
    if all(value < .80 for value in vals):
        return 'EDGE_FAIL'
    return 'EDGE_BOUNDARY'


def extension_branch(base_rows):
    expected = {row['run_id'] for row in base_order()}
    if len(base_rows) != 8 or {row.get('run_id') for row in base_rows} != expected \
            or any(row.get('integrity_status') != 'VALID' for row in base_rows):
        raise ValueError('Incomplete/invalid base preflight; no extension')
    usable = {}
    for pattern in ('ALIGNED', 'STAGGERED'):
        rows = [row for row in base_rows if row['rate'] == 80 and row['pattern'] == pattern]
        usable[pattern] = run_class(rows) == 'EDGE_USABLE'
    return ('BOTH' if all(usable.values()) else 'ALIGNED_ONLY' if usable['ALIGNED']
            else 'STAGGERED_ONLY' if usable['STAGGERED'] else 'NONE')


def hello(condition, digest, cache_sha):
    return {'mode': 'edge_temporal_preflight_final02', 'rate': condition['rate'],
            'seconds': SECONDS, 'repeat': condition['repeat'], 'run_id': condition['run_id'],
            'campaign_plan_sha256': digest, 'cache_sha256': cache_sha,
            'payload_origin': 'CACHED_REAL_RAW640_30; K8_30FPS_SOURCE_SLOT_SELECTION',
            'deadline_ms': 100, 'admission_pattern': condition['pattern'],
            'phase_vector': condition['phase_vector'], 'stage': condition['stage']}


def validate_source_rows(rows, condition, active_start_ns):
    """Hard actual source-slot/admission/relative-order fidelity, including skips."""
    errors = []
    expected = SECONDS * 30 * 8
    if len(rows) != expected:
        errors.append(f'source row count {len(rows)} != {expected}')
    by_id = {}
    actual_m = [0] * (SECONDS * 30)
    admitted = [0] * 8
    ids = []
    for row in rows:
        try:
            sid, frame = int(row['stream_id']), int(row['frame_id'])
            if sid not in range(8) or frame not in range(SECONDS * 30) or (sid, frame) in by_id:
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
    wanted = SECONDS * condition['per_stream_rate']
    if admitted != [wanted] * 8 or len(ids) != SECONDS * condition['rate'] \
            or ids != list(range(SECONDS * condition['rate'])):
        errors.append('per-stream/aggregate Edge IDs or frame order mismatch')
    planned = schedule(condition['rate'], condition['pattern'])['m_n']
    for frame in range(SECONDS * 30):
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
    if plan['base_order'] != base_order() or plan['extension_orders'] != extension_orders():
        raise RuntimeError('Frozen order/branch mismatch')
    if plan['seconds'] != SECONDS or plan['idle_seconds'] != IDLE_SECONDS \
            or plan['phase_vector'] != list(PHASES) or plan['payload_bytes'] != PAYLOAD_BYTES:
        raise RuntimeError('Frozen duration/phase/payload mismatch')
    endpoint_path = OUT / 'EDGE_ENDPOINT_MANIFEST.json'
    endpoint = json.loads(endpoint_path.read_text())
    if sha(endpoint_path) != plan['endpoint_manifest_sha256'] \
            or plan['edge_ip'] != plan['edge_host'] \
            or endpoint['edge_ip'] != plan['edge_ip'] \
            or ipaddress.ip_address(plan['edge_ip']).version != 4:
        raise RuntimeError('Frozen Edge endpoint/manifest mismatch')
    for name, digest in plan['artifact_sha256'].items():
        if sha(OUT / name) != digest:
            raise RuntimeError('Frozen plan artifact drift: ' + name)
    for name, digest in json.loads((OUT / 'source_sha256.json').read_text()).items():
        if sha(ROOT / name) != digest:
            raise RuntimeError('Source SHA mismatch: ' + name)
    return plan
