"""Log-only source-slot/admission/dispatch fidelity; never drives a runtime decision."""
from collections import Counter, defaultdict

from phase_schedule import PERIOD, STREAMS, P, mask


def validate_trace(rows, manifest, condition, plan, seconds=60):
    errors = []
    def flag(message):
        if len(errors) < 100:
            errors.append(message)
    active = [row for row in rows if row.get('phase') == 'active']
    expected_frames = seconds * PERIOD * STREAMS
    if len(active) != expected_frames:
        flag(f'active source universe size {len(active)} != {expected_frames}')
    index = {}
    by_slot = defaultdict(list)
    counts = [0] * STREAMS
    actual_slots = [0] * (seconds * PERIOD)
    for row in active:
        try:
            sid, frame_id = int(row['stream_id']), int(row['frame_id'])
            if sid not in range(STREAMS) or frame_id not in range(seconds * PERIOD):
                flag(f'out-of-universe frame {(sid, frame_id)}')
                continue
            key = sid, frame_id
            if key in index:
                flag(f'duplicate frame {key}')
                continue
            index[key] = row
            by_slot[frame_id].append(row)
            logical = int(row['logical_arrival_ns'])
            due = int(manifest['active_start_ns']) + frame_id * 10**9 // 30
            if logical != due or int(row['admission_timestamp_ns']) != due:
                flag(f'logical/admission timestamp mismatch {key}')
            phase = 0 if condition['admission_pattern'] == 'ALIGNED' else plan['placement']['phases'][sid]
            planned = P[(frame_id % PERIOD - phase) % PERIOD]
            admitted = int(row['admitted'])
            if admitted != planned:
                flag(f'planned-vs-runtime x mismatch {key}: {admitted} != {planned}')
            if row['placement'] != ('LOCAL' if admitted else 'SKIP'):
                flag(f'placement mismatch {key}')
            if admitted:
                counts[sid] += 1
                actual_slots[frame_id] += 1
                if int(row['absolute_deadline_ns']) != due + condition['deadline_ms'] * 1_000_000:
                    flag(f'absolute deadline mismatch {key}')
            elif row.get('absolute_deadline_ns') not in ('', None):
                flag(f'skipped frame has deadline {key}')
            if row.get('edge_request_id') not in ('', None):
                flag(f'Edge request in Local-only pilot {key}')
        except (KeyError, ValueError, TypeError) as exc:
            flag(f'malformed source row: {exc!r}')
    if len(index) != expected_frames:
        flag(f'unique source IDs {len(index)} != {expected_frames}')
    expected_count = seconds * 26
    if any(count != expected_count for count in counts):
        flag(f'per-stream Local counts {counts} != {expected_count}')
    if sum(counts) != seconds * 208:
        flag(f'aggregate Local count {sum(counts)} != {seconds * 208}')
    phases = [0] * STREAMS if condition['admission_pattern'] == 'ALIGNED' else plan['placement']['phases']
    expected_m = [sum(mask(phases[sid])[frame_id % PERIOD] for sid in range(STREAMS))
                  for frame_id in range(seconds * PERIOD)]
    if actual_slots != expected_m:
        first = next(i for i, (actual, wanted) in enumerate(zip(actual_slots, expected_m)) if actual != wanted)
        flag(f'planned-vs-runtime m_n mismatch slot {first}: {actual_slots[first]} != {expected_m[first]}')
    source_order = plan['placement']['canonical_dispatch_order']
    for frame_id in range(seconds * PERIOD):
        rr = by_slot[frame_id]
        if len(rr) != STREAMS:
            flag(f'source slot {frame_id} has {len(rr)} stream rows')
            continue
        try:
            observed = sorted(rr, key=lambda row:int(row['admission_observed_ns']))
            stamps = [int(row['admission_observed_ns']) for row in observed]
            if len(set(stamps)) != STREAMS:
                flag(f'non-distinct dispatch timestamps at slot {frame_id}')
            actual_order = [int(row['stream_id']) for row in observed if int(row['admitted'])]
            admitted_set = set(actual_order)
            expected_order = [sid for sid in source_order if sid in admitted_set]
            if actual_order != expected_order:
                flag(f'canonical relative dispatch order mismatch slot {frame_id}')
        except (KeyError, ValueError, TypeError) as exc:
            flag(f'dispatch timestamp unavailable slot {frame_id}: {exc!r}')
    planned_first = [sum(mask(phases[sid])[frame_id] for sid in range(STREAMS)) for frame_id in range(PERIOD)]
    if actual_slots[:PERIOD] != planned_first:
        flag('first-period slot-count vector mismatch')
    if manifest.get('placement_schedule') != plan['placement']:
        flag('child manifest placement schedule mismatch')
    if manifest.get('admission_pattern') != condition['admission_pattern']:
        flag('child manifest admission pattern mismatch')
    if manifest.get('target_service_FPS') != 208 or manifest.get('edge_r') != 0:
        flag('child manifest Local/Edge target mismatch')
    return {'status': 'PASS' if not errors else 'FAIL', 'errors': errors,
            'error_list_truncated_to_100': len(errors) == 100,
            'source_frame_rows': len(active), 'unique_source_frame_IDs': len(index),
            'per_stream_admitted_counts': counts, 'aggregate_admitted_count': sum(counts),
            'actual_m_n_first_period': actual_slots[:PERIOD],
            'planned_m_n_first_period': planned_first,
            'actual_slot_histogram_all_60s': dict(sorted(Counter(actual_slots).items())),
            'dispatch_order_definition': 'ascending admission_observed_ns must be canonical [0..7] restricted to the admitted stream set'}
