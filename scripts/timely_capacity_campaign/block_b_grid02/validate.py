"""CPU-only Block B source/split/terminal and observed dispatch validation."""
import csv
import gzip
import json
import sys
from collections import Counter
from pathlib import Path

from grid_config import OUT, PLAN, local_bit, edge_id, sha, slot_order

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'common'))
from dispatch_observation import positions


def read_frames(path):
    with gzip.open(path, 'rt', newline='') as stream:
        return list(csv.DictReader(stream))


def validate_rows(rows, condition, active_start_ns):
    errors = []
    seconds = condition['seconds']
    expected = seconds * 240
    active = [r for r in rows if r.get('phase') == 'active']
    if len(active) != expected:
        errors.append(f'active source count {len(active)} != {expected}')
    by_id = {}
    terminal = Counter()
    local_count = edge_count = 0
    edge_ids = []
    for r in active:
        try:
            sid, frame = int(r['stream_id']), int(r['frame_id'])
            identity = (sid, frame)
            if sid not in range(8) or frame not in range(seconds*30) or identity in by_id:
                errors.append(f'duplicate/out-of-range source ID {identity}')
                continue
            by_id[identity] = r
            due = active_start_ns + frame * 10**9 // 30
            if int(r['logical_arrival_ns']) != due or int(r['admission_timestamp_ns']) != due:
                errors.append(f'source timestamp shift {identity}')
            expected_path = 'LOCAL' if local_bit(condition['target_service_FPS'],
                                                 condition['admission_pattern'], sid, frame) else 'EDGE'
            if int(r['admitted']) != 1 or r['placement'] != expected_path:
                errors.append(f'wrong destination/mask {identity}')
            if int(r['absolute_deadline_ns']) != due + 100_000_000:
                errors.append(f'wrong deadline {identity}')
            if expected_path == 'LOCAL':
                local_count += 1
                if r.get('edge_request_id') not in ('',None):
                    errors.append(f'Local has Edge ID {identity}')
            else:
                edge_count += 1
                wanted = edge_id(condition['target_service_FPS'], condition['admission_pattern'], sid, frame)
                edge_ids.append(int(r['edge_request_id']))
                if int(r['edge_request_id']) != wanted or int(r['edge_release_target_ns']) != due:
                    errors.append(f'Edge request/deferred admission {identity}')
            complete = r.get('completion_timestamp_ns') not in ('',None)
            drop = r.get('expired_drop_ns') not in ('',None)
            state = r.get('terminal_state')
            if state == 'COMPLETED' and complete and not drop:
                terminal[expected_path+'_completed'] += 1
            elif state == 'EXPIRED_DROP' and drop and not complete:
                terminal[expected_path+'_expired'] += 1
            else:
                errors.append(f'nonexclusive/unfinished terminal {identity}')
        except (KeyError, ValueError, TypeError) as exc:
            errors.append(f'malformed row {exc!r}')
    if len(by_id) != expected:
        errors.append('source ID universe incomplete')
    if local_count != seconds*condition['target_service_FPS'] or edge_count != seconds*(240-condition['target_service_FPS']):
        errors.append('exact split count mismatch')
    if sorted(edge_ids) != list(range(edge_count)):
        errors.append('missing/duplicate Edge request IDs')
    try:
        observed = positions(active)
        for (sid,frame), entry in observed.items():
            intended = slot_order(condition['target_service_FPS'], condition['admission_pattern'],
                                  frame, entry['destination'])
            if intended[entry['dispatch_position']] != sid:
                errors.append(f'canonical-relative dispatch order mismatch {(sid,frame)}')
    except (ValueError, KeyError, IndexError) as exc:
        observed = {}
        errors.append(f'dispatch observation failed {exc!r}')
    if len(observed) != expected:
        errors.append('incomplete position observation')
    return {'status': 'PASS' if not errors else 'FAIL', 'errors': errors[:100],
            'source_count': len(active), 'local_count': local_count, 'edge_count': edge_count,
            'terminal_counts': dict(terminal), 'position_count': len(observed),
            'no_retry': True}


def validate_run(directory, condition):
    directory = Path(directory)
    m = json.loads((directory/'manifest.json').read_text())
    s = json.loads((directory/'summary.json').read_text())
    if m.get('plan_sha256') != sha(PLAN) or m.get('run_id') != condition['run_id']:
        return {'status': 'FAIL', 'errors': ['plan/run manifest mismatch']}
    result = validate_rows(read_frames(directory/'per_frame.csv.gz'), condition, int(m['active_start_ns']))
    if s.get('integrity_status') != 'VALID' or s.get('terminal_accounting_status') != 'PASS' or \
            s.get('true_unfinished_after_drain') != 0 or not s.get('frequency_restore_ok'):
        result['status'] = 'FAIL'
        result['errors'].append('summary terminal/integrity/GPU restoration failure')
    return result
