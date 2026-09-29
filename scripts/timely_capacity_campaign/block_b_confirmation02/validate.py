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


def edge_terminal_valid(edge, expected_assigned):
    return (edge.get('integrity_status')=='VALID' and not edge.get('errors') and
            all(edge.get(k) is True for k in ('drain_completed','cleanup_completed','worker_thread_exited')) and
            edge.get('duplicates')==0 and edge.get('drops')==0 and
            not edge.get('queue_cap_saturation') and
            edge.get('received')==edge.get('completed')==edge.get('responses_sent') and
            edge.get('assigned')==expected_assigned and
            edge.get('assigned')==edge.get('received',0)+edge.get('client_expired_before_submission',0))


def cpu_run_valid(directory):
    directory = Path(directory)
    for name in ('CPU_BEFORE_RUN.json', 'CPU_AFTER_RUN.json'):
        path = directory/name
        if not path.is_file():
            return False
        record = json.loads(path.read_text())
        if record.get('status') != 'PASS' or record.get('mode') != 'pinned' or record.get('errors'):
            return False
    return True


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
    if not cpu_run_valid(directory):
        result['status'] = 'FAIL'
        result['errors'].append('CPU before/after pinned readback failure')
    if m.get('edge_path_errors') or m.get('queue_overflow') or m.get('forced_drop') or \
            m.get('queue_cap_saturation') or m.get('process_exit_code') not in (0,None) or \
            m.get('child_returncode') not in (0,None):
        result['status'] = 'FAIL'
        result['errors'].append('transport/backpressure/process failure')
    edge_path=directory/'edge_final.json'
    if not edge_path.is_file():
        result['status'] = 'FAIL'
        result['errors'].append('Edge terminal/server result absent')
    else:
        edge=json.loads(edge_path.read_text())
        if not edge_terminal_valid(edge,result['edge_count']):
            result['status'] = 'FAIL'
            result['errors'].append('Edge protocol/integrity/lifecycle/accounting failure')
    return result
