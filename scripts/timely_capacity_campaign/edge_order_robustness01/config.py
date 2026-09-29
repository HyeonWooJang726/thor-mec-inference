"""Frozen E48 mask and submit-order intervention; CPU-only functions."""
import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OUT = ROOT / 'results/timely_capacity_campaign/v2_2/edge_order_robustness01'
PLAN = OUT / 'plan.json'
IDLE_SECONDS = 10
PAYLOAD_BYTES = 691200
MODES = ('BASE', 'REVERSE', 'ROTATE')
sys.path.insert(0, str(HERE.parent / 'common'))
import campaign_config as canonical


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def q6():
    masks, edge = canonical.schedule(48, 0, 'ALIGNED')
    if edge or any(mask != masks[0] for mask in masks):
        raise RuntimeError('Canonical E48 floor mask drift')
    bits = tuple(int(slot in masks[0]) for slot in range(30))
    if sum(bits) != 6:
        raise RuntimeError('Expected six active slots per second')
    return bits


def bit(pattern, sid, frame):
    if sid not in range(8) or frame < 0:
        raise ValueError('Invalid source ID')
    return q6()[(frame - (sid if pattern == 'STAGGERED' else 0)) % 30]


def active_index(frame):
    """0-based E48 ALIGNED active-slot counter, including earlier seconds."""
    if not q6()[frame % 30]:
        raise ValueError('Inactive E48 slot')
    return frame // 30 * 6 + sum(q6()[:frame % 30])


def submit_order(mode, frame):
    if mode == 'BASE':
        return list(range(8))
    if mode == 'REVERSE':
        return list(range(7, -1, -1))
    if mode == 'ROTATE':
        j = active_index(frame)
        return [(j + i) % 8 for i in range(8)]
    if mode == 'WARMUP':
        return list(range(8))
    raise ValueError('Unknown frozen submit order')


def exposure(seconds=30):
    matrix = [[0] * 8 for _ in range(8)]
    for frame in range(seconds * 30):
        if q6()[frame % 30]:
            for position, sid in enumerate(submit_order('ROTATE', frame)):
                matrix[sid][position] += 1
    return matrix


SEQUENCE = (
    ('BASE', 1), ('REVERSE', 1), ('ROTATE', 1),
    ('REVERSE', 2), ('ROTATE', 2), ('BASE', 2),
    ('ROTATE', 3), ('BASE', 3), ('REVERSE', 3),
    ('BASE', 4), ('ROTATE', 4), ('REVERSE', 4),
    ('ROTATE', 5), ('REVERSE', 5), ('BASE', 5),
)


def condition(mode, repeat, index):
    warmup = mode == 'WARMUP'
    if warmup:
        if repeat != 0 or index != 1:
            raise ValueError('Warm-up must be first')
        run_id, seconds, pattern = 'EDGEORDER01_WARMUP_E48_S', 15, 'STAGGERED'
    else:
        if mode not in MODES or repeat not in range(1, 6):
            raise ValueError('Unplanned measured condition')
        token = {'BASE': 'BASE', 'REVERSE': 'REV', 'ROTATE': 'ROT'}[mode]
        run_id, seconds, pattern = f'EDGEORDER01_E48_{token}{repeat}', 30, 'ALIGNED'
    return {'run_id': run_id, 'stage': 'WARMUP' if warmup else 'MEASURED',
            'rate': 48, 'per_stream_rate': 6, 'pattern': pattern,
            'dispatch_order_mode': mode, 'repeat': repeat, 'order_index': index,
            'seconds': seconds, 'deadline_ms': 100, 'source_streams': 8,
            'source_FPS_per_stream': 30, 'phase_vector': list(range(8)) if warmup else [0] * 8,
            'edge_C': 1, 'edge_B': 1}


def frozen_order():
    rows = [condition('WARMUP', 0, 1)]
    rows.extend(condition(mode, repeat, len(rows) + 1) for mode, repeat in SEQUENCE)
    return rows


def hello(c, digest, cache_sha):
    return {'mode': 'edge_order_robustness01', 'rate': 48, 'seconds': c['seconds'],
            'repeat': c['repeat'], 'run_id': c['run_id'], 'campaign_plan_sha256': digest,
            'cache_sha256': cache_sha,
            'payload_origin': 'CACHED_REAL_RAW640_30; K8_30FPS_SOURCE_SLOT_SELECTION',
            'deadline_ms': 100, 'admission_pattern': c['pattern'],
            'phase_vector': c['phase_vector'], 'stage': c['stage'],
            'dispatch_order_mode': c['dispatch_order_mode']}


def validate_source_rows(rows, c, start):
    errors = []
    count = c['seconds'] * 30 * 8
    by_id = {}
    by_frame = [[] for _ in range(c['seconds'] * 30)]
    ids = []
    per_stream = [0] * 8
    for row in rows:
        try:
            sid, frame = int(row['stream_id']), int(row['frame_id'])
            if sid not in range(8) or frame not in range(c['seconds'] * 30) or (sid, frame) in by_id:
                errors.append('duplicate/out-of-range source ID')
                continue
            by_id[sid, frame] = row
            by_frame[frame].append(row)
            due = start + frame * 10**9 // 30
            if int(row['logical_arrival_ns']) != due or int(row['admission_timestamp_ns']) != due:
                errors.append('timestamp shift')
            selected = bit(c['pattern'], sid, frame)
            if int(row['admitted']) != selected or row['placement'] != ('EDGE' if selected else 'SKIP'):
                errors.append('mask/placement mismatch')
            if selected:
                per_stream[sid] += 1
                ids.append(int(row['edge_request_id']))
                if int(row['edge_release_target_ns']) != due or int(row['absolute_deadline_ns']) != due + 100_000_000:
                    errors.append('deferred admission/deadline mismatch')
                expected_position = submit_order(c['dispatch_order_mode'], frame).index(sid)
                if int(row['dispatch_position']) != expected_position:
                    errors.append('dispatch position mismatch')
                expected_active = active_index(frame) if c['stage'] == 'MEASURED' else -1
                if int(row['active_slot_index']) != expected_active:
                    errors.append('active slot counter mismatch')
            if row['dispatch_order_mode'] != c['dispatch_order_mode']:
                errors.append('order mode mismatch')
        except (KeyError, TypeError, ValueError) as exc:
            errors.append(f'malformed source row {exc!r}')
    if len(rows) != count or len(by_id) != count:
        errors.append('source universe incomplete')
    if per_stream != [c['seconds'] * 6] * 8 or ids != list(range(c['seconds'] * 48)):
        errors.append('admission count/request ID order mismatch')
    for frame in range(c['seconds'] * 30):
        ordered = [row for row in by_frame[frame] if int(row['admitted'])]
        expected = submit_order(c['dispatch_order_mode'], frame) if c['stage'] == 'MEASURED' and q6()[frame % 30] else [sid for sid in range(8) if bit(c['pattern'], sid, frame)]
        if [int(row['stream_id']) for row in ordered] != expected:
            errors.append(f'actual submit order mismatch slot {frame}')
    return {'status': 'PASS' if not errors else 'FAIL', 'errors': errors[:100],
            'source_rows': len(rows), 'per_stream_admitted': per_stream,
            'actual_total_admitted': len(ids), 'no_deferred_admission': not any('deferred' in e for e in errors)}


def load_plan():
    p = json.loads(PLAN.read_text())
    if sha(PLAN) != (OUT / 'plan.sha256').read_text().strip() or p['order'] != frozen_order():
        raise RuntimeError('Frozen order plan mismatch')
    for relative, digest in p['source_sha256'].items():
        if sha(ROOT / relative) != digest:
            raise RuntimeError('Source drift: ' + relative)
    return p
