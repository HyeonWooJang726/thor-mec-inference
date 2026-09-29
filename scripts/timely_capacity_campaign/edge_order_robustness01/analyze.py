"""Log-only final Edge temporal calibration; analyzer requires Thor CPU restore."""
import argparse
import csv
import json
import statistics
import math
from pathlib import Path

from config import (OUT, PLAN, frozen_order, exposure,
                    load_plan, sha, validate_source_rows)
from run_thor import cpu_report
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'common'))
from dispatch_observation import positions as observed_positions


def read_csv(path):
    with Path(path).open(newline='') as stream:
        return list(csv.DictReader(stream))


def percentile(values, p):
    if not values:
        return None
    ordered = sorted(values)
    index = (len(ordered) - 1) * p / 100
    lo = int(index)
    hi = min(lo + 1, len(ordered) - 1)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (index - lo)


def rank(values):
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i + 1
        while j < len(order) and values[order[j]] == values[order[i]]:
            j += 1
        for index in order[i:j]:
            ranks[index] = (i + 1 + j) / 2
        i = j
    return ranks


def spearman(values):
    a, b = rank(list(range(len(values)))), rank(values)
    ma, mb = statistics.mean(a), statistics.mean(b)
    numerator = sum((x-ma)*(y-mb) for x,y in zip(a,b))
    denominator = math.sqrt(sum((x-ma)**2 for x in a)*sum((y-mb)**2 for y in b))
    return numerator/denominator if denominator else None


def client_pending(rows, active_start, active_end):
    """Admitted-but-not-submitted/expired work, clipped to Thor active time."""
    events = []
    pending_end = 0
    for row in rows:
        begin = int(row['logical_arrival_ns'])
        terminal = row.get('socket_submission_ns') or row.get('expired_drop_ns')
        if terminal in (None, '') or int(terminal) >= active_end:
            pending_end += 1
        end = min(int(terminal) if terminal not in (None, '') else active_end, active_end)
        if begin < end and begin < active_end:
            events.extend(((begin, 1), (end, -1)))
    level = peak = area = 0
    previous = active_start
    for stamp, delta in sorted(events):
        if stamp < active_start:
            level += delta
            continue
        area += level * (stamp - previous)
        level += delta
        peak = max(peak, level)
        previous = stamp
    area += level * (active_end - previous)
    return {'active_mean': area / (active_end - active_start), 'peak': peak,
            'active_end_count': pending_end}


def put_json(path, obj):
    with Path(path).open('x') as stream:
        json.dump(obj, stream, indent=2)
        stream.write('\n')


def put_csv(path, rows):
    with Path(path).open('x', newline='') as stream:
        if not rows:
            return
        keys = list(dict.fromkeys(key for row in rows for key in row))
        writer = csv.DictWriter(stream, fieldnames=keys)
        writer.writeheader()
        writer.writerows(rows)


def require_restore():
    path = OUT / 'CPU_RESTORE_READBACK.json'
    if not path.exists():
        raise RuntimeError('CPU restore PASS required before analyzer')
    report = json.loads(path.read_text())
    if report.get('status') != 'PASS' or report.get('mode') != 'restored' \
            or report.get('plan_sha256') != sha(PLAN):
        raise RuntimeError('CPU restore readback not PASS')
    if cpu_report('restored')['status'] != 'PASS':
        raise RuntimeError('Current CPU restoration state differs from frozen baseline')
    ends = [json.loads(path.read_text())['monotonic_ns']
            for path in OUT.glob('sessions/EDGEORDER01_*/network_end.json')]
    if ends and report['snapshot']['monotonic_ns'] < max(ends):
        raise RuntimeError('CPU restore predates last Edge-only child')


def server_metrics(directory, condition):
    s = json.loads((directory / 'summary.json').read_text())
    rows = read_csv(directory / 'requests.csv')
    waits, service = [], []
    for row in rows:
        waits.append((int(row['queue_start_ns']) - int(row['queue_enter_ns'])) / 1e6)
        service.append((int(row['inference_end_ns']) - int(row['inference_start_ns'])) / 1e6)
    errors = []
    count = condition['rate'] * condition['seconds']
    if s.get('integrity_status') != 'VALID' or not s.get('drain_completed') \
            or not s.get('worker_thread_exited') or not s.get('cleanup_completed') or s.get('duplicates') or s.get('drops') \
            or s.get('queue_cap_saturation'):
        errors.append('server integrity/drain/duplicate/drop failure')
    if not (s.get('received') == s.get('completed') == s.get('responses_sent') == len(rows)):
        errors.append('server received/completed/response-count mismatch')
    ids = [int(row['request_id']) for row in rows]
    if len(ids) != len(set(ids)) or any(not 0 <= rid < count for rid in ids):
        errors.append('server request ID duplicate/out-of-range')
    return {'status': 'PASS' if not errors else 'FAIL', 'errors': errors,
            'request_ids': sorted(ids),
            'received': s.get('received'), 'completed': s.get('completed'),
            'responses_sent': s.get('responses_sent'),
            'server_queue_max_observed': s.get('queue_peak_observed'),
            'server_queue_wait_p50_ms': percentile(waits, 50),
            'server_queue_wait_p95_ms': percentile(waits, 95),
            'server_queue_wait_p99_ms': percentile(waits, 99),
            'server_inference_p50_ms': percentile(service, 50),
            'server_inference_p95_ms': percentile(service, 95),
            'server_inference_p99_ms': percentile(service, 99),
            'server_queue_stall_event_count': None,
            'server_queue_stall_note': 'N/A: frozen server has queue timestamps/peak, no distinct stall-event counter'}


def run_metrics(condition):
    stage = condition['stage']
    directory = OUT / 'sessions' / condition['run_id']
    m = json.loads((directory / 'manifest.json').read_text())
    s = json.loads((directory / 'summary.json').read_text())
    rows = read_csv(directory / 'source_frames.csv')
    fidelity = validate_source_rows(rows, condition, m['active_start_ns'])
    server_directory = OUT / 'received_edge' / condition['run_id']
    server = server_metrics(server_directory, condition)
    admitted = [r for r in rows if int(r['admitted']) == 1]
    pending = client_pending(admitted, int(m['active_start_ns']), int(m['active_end_ns']))
    offload_waits = [(int(r['socket_submission_ns']) - int(r['logical_arrival_ns'])) / 1e6
                     for r in admitted if r.get('socket_submission_ns') not in (None, '')]
    per_stream = []
    for sid in range(8):
        rr = [r for r in admitted if int(r['stream_id']) == sid]
        timely = sum(r.get('response_completion_ns') not in (None, '') and
            int(r['response_completion_ns']) - int(r['logical_arrival_ns']) <= 100_000_000 for r in rr)
        completed = sum(r.get('response_completion_ns') not in (None, '') for r in rr)
        expired = sum(r.get('terminal_state') == 'EXPIRED_DROP' for r in rr)
        per_stream.append({'run_id': condition['run_id'], 'stream_id': sid,
            'admitted': len(rr), 'timely': timely, 'late_completed':completed-timely,
            'expired':expired,'TIR_admission': timely / len(rr) if rr else None})
    terminal = len(admitted) == int(s.get('timely', -1)) + int(s.get('late_completed', -1)) + int(s.get('expired', -1))
    errors = []
    if s.get('integrity_status') != 'VALID' or fidelity['status'] != 'PASS' or server['status'] != 'PASS':
        errors.append('Thor schedule/transport or server integrity failure')
    if m.get('plan_sha256') != sha(PLAN) or m.get('condition') != condition:
        errors.append('frozen plan/condition manifest mismatch')
    if not terminal or len(admitted) != condition['rate'] * condition['seconds'] or s.get('after_drain_unfinished') != 0:
        errors.append('exact terminal/admission accounting failure')
    if sum(row['timely'] for row in per_stream) != s.get('timely'):
        errors.append('per-stream/aggregate timely count mismatch')
    if sum(row['late_completed'] for row in per_stream) != s.get('late_completed') or \
            sum(row['expired'] for row in per_stream) != s.get('expired'):
        errors.append('per-stream/aggregate late/expired mismatch')
    if server['received'] != s.get('completed') or server['received'] != s.get('payload_submitted_frames'):
        errors.append('Thor submission/server receipt mismatch')
    submitted_ids = sorted(int(r['edge_request_id']) for r in admitted
                           if r.get('socket_submission_ns') not in (None, ''))
    if server['request_ids'] != submitted_ids:
        errors.append('Thor submitted IDs differ from Edge received IDs')
    if pending['active_end_count'] != s.get('Thor_pending_active_end'):
        errors.append('Thor pending active-end mismatch')
    stream_tir = [row['TIR_admission'] for row in per_stream]
    response = [(int(r['response_completion_ns']) - int(r['socket_submission_ns'])) / 1e6
                for r in admitted if r.get('response_completion_ns') not in (None, '')
                and r.get('socket_submission_ns') not in (None, '')]
    rate = {'run_id': condition['run_id'], 'stage': stage, 'rate': condition['rate'],
        'pattern': condition['pattern'], 'dispatch_order_mode': condition['dispatch_order_mode'],
        'repeat': condition['repeat'],
        'admitted': len(admitted), 'completed': s.get('completed'),
        'timely': s.get('timely'), 'late_completed': s.get('late_completed'),
        'expired': s.get('expired'), 'TIR_admission': s.get('TIR_admission'),
        'seconds': condition['seconds'], 'admitted_FPS': len(admitted) / condition['seconds'],
        'completed_FPS': s.get('completed', 0) / condition['seconds'],
        'timely_FPS': s.get('timely_FPS'),
        'late_completed_FPS': s.get('late_completed', 0) / condition['seconds'],
        'expired_FPS': s.get('expired', 0) / condition['seconds'],
        'after_drain_true_unfinished': s.get('after_drain_unfinished'),
        'worst_stream_TIR': min(stream_tir), 'best_stream_TIR': max(stream_tir),
        'max_minus_min_stream_TIR': max(stream_tir)-min(stream_tir),
        'per_stream_TIR_sample_SD': statistics.stdev(stream_tir),
        'stream0_TIR': stream_tir[0], 'stream7_TIR': stream_tir[7],
        'stream0_minus_stream7_TIR': stream_tir[0]-stream_tir[7],
        'Spearman_dispatch_position_vs_TIR': spearman(stream_tir),
        'Thor_offload_wait_p50_ms': percentile(offload_waits, 50),
        'Thor_offload_wait_p95_ms': percentile(offload_waits, 95),
        'Thor_offload_wait_p99_ms': percentile(offload_waits, 99),
        'Thor_client_pending_active_mean': pending['active_mean'],
        'Thor_client_pending_peak': pending['peak'],
        'Thor_client_pending_active_end': pending['active_end_count'],
        'Thor_request_response_p50_ms': percentile(response,50),
        'Thor_request_response_p95_ms': percentile(response,95),
        'Thor_request_response_p99_ms': percentile(response,99),
        'server_queue_wait_p50_ms': server['server_queue_wait_p50_ms'],
        'server_queue_wait_p95_ms': server['server_queue_wait_p95_ms'],
        'server_queue_wait_p99_ms': server['server_queue_wait_p99_ms'],
        'server_inference_p50_ms': server['server_inference_p50_ms'],
        'server_inference_p95_ms': server['server_inference_p95_ms'],
        'server_inference_p99_ms': server['server_inference_p99_ms'],
        'server_queue_max_observed': server['server_queue_max_observed'],
        'server_received':server['received'], 'server_completed':server['completed'],
        'server_responses_sent':server['responses_sent'],
        'server_queue_stall_event_count': None,
        'schedule_fidelity': fidelity['status'], 'integrity_status': 'VALID' if not errors else 'INVALID',
        'errors': errors, 'edge_transport_error_count': len(m.get('edge', {}).get('edge_path_errors', [])),
        'automatic_retry_count': 0, 'payload_submitted_frames':s.get('payload_submitted_frames'),
        'payload_submitted_bytes': s.get('payload_submitted_bytes'),
        'network_interface':'wlP1p1s0',
        'network_TX_bytes_delta': s.get('network_TX_bytes_delta'),
        'network_carrier_counters_unchanged':s.get('network_carrier_counters_unchanged'),
        'observed_transmitted_data_rate_Mbps': s['network_TX_bytes_delta']*8/condition['seconds']/1e6 if s.get('network_TX_bytes_delta') is not None else None,
        'WiFi_BSSID_start':m.get('wifi_start',{}).get('BSSID'),
        'WiFi_BSSID_end':m.get('wifi_end',{}).get('BSSID'),
        'WiFi_signal_start_dBm':m.get('wifi_start',{}).get('signal_dBm'),
        'WiFi_signal_end_dBm':m.get('wifi_end',{}).get('signal_dBm'),
        'WiFi_tx_bitrate_start_Mbps':m.get('wifi_start',{}).get('tx_bitrate_Mbps'),
        'WiFi_tx_bitrate_end_Mbps':m.get('wifi_end',{}).get('tx_bitrate_Mbps')}
    if stage == 'WARMUP' and (pending['active_end_count'] != 0 or not s.get('server_lifecycle_PASS')):
        rate['integrity_status'] = 'INVALID'
        rate['errors'].append('Warm-up pending/lifecycle failure')
    return rate, per_stream, {'run_id': condition['run_id'], **server}



def position_rows(condition):
    """Attribute frame-level Thor and server timestamps by exact request ID."""
    d = OUT / 'sessions' / condition['run_id']
    thor = [r for r in read_csv(d / 'source_frames.csv') if int(r['admitted'])]
    edge = {int(r['request_id']): r for r in read_csv(OUT / 'received_edge' / condition['run_id'] / 'requests.csv')}
    groups = {p: [] for p in range(8)}
    for r in thor:
        rid = int(r['edge_request_id']); pos = int(r['dispatch_position'])
        if pos not in groups:
            raise RuntimeError('Invalid dispatch position')
        groups[pos].append((r, edge.get(rid)))
    result = []
    for pos, group in groups.items():
        if not group:
            continue
        timely = sum(r['response_completion_ns'] not in ('', None) and
            int(r['response_completion_ns']) - int(r['logical_arrival_ns']) <= 100_000_000 for r, _ in group)
        completed = sum(r['response_completion_ns'] not in ('', None) for r, _ in group)
        expired = sum(r['terminal_state'] == 'EXPIRED_DROP' for r, _ in group)
        if timely + (completed - timely) + expired != len(group):
            raise RuntimeError('Position terminal partition mismatch')
        def q(values, level):
            return percentile(values, level)
        wait = [(int(r['socket_submission_ns'])-int(r['logical_arrival_ns']))/1e6
                for r, _ in group if r['socket_submission_ns'] not in ('', None)]
        response = [(int(r['response_completion_ns'])-int(r['socket_submission_ns']))/1e6
                    for r, _ in group if r['response_completion_ns'] not in ('', None)
                    and r['socket_submission_ns'] not in ('', None)]
        queue = [(int(e['queue_start_ns'])-int(e['queue_enter_ns']))/1e6
                 for _, e in group if e is not None]
        infer = [(int(e['inference_end_ns'])-int(e['inference_start_ns']))/1e6
                 for _, e in group if e is not None]
        row = {'run_id': condition['run_id'], 'dispatch_order_mode': condition['dispatch_order_mode'],
               'dispatch_position': pos, 'count': len(group), 'timely': timely,
               'late': completed-timely, 'expired': expired, 'TIR': timely/len(group)}
        for name, values in (('offload_wait', wait), ('request_response', response),
                             ('server_queue_wait', queue), ('server_inference', infer)):
            for level in (50, 95, 99):
                row[f'{name}_p{level}_ms'] = q(values, level)
        result.append(row)
    if condition['stage'] == 'MEASURED' and sum(r['count'] for r in result) != 1440:
        raise RuntimeError('Position count mismatch')
    return result


def exposure_rows(condition):
    rows = read_csv(OUT / 'sessions' / condition['run_id'] / 'source_frames.csv')
    observed_order = observed_positions(rows)
    observed = [[0]*8 for _ in range(8)]
    for row in rows:
        if int(row['admitted']):
            identity = int(row['stream_id']), int(row['frame_id'])
            if observed_order[identity]['dispatch_position'] != int(row['dispatch_position']):
                raise RuntimeError('Logged and reconstructed actual dispatch positions differ')
            observed[int(row['stream_id'])][int(row['dispatch_position'])] += 1
    if condition['dispatch_order_mode'] == 'ROTATE' and observed != exposure():
        raise RuntimeError('ROTATE exposure mismatch')
    return [{'run_id': condition['run_id'], 'stream_id': sid, 'dispatch_position': pos,
             'count': observed[sid][pos]} for sid in range(8) for pos in range(8)]


def describe(values):
    return {'values': values, 'positive_count': sum(x > 0 for x in values),
            'mean': statistics.mean(values), 'min': min(values), 'max': max(values)}


def mechanism(rows):
    by = {(r['dispatch_order_mode'], r['repeat']): r for r in rows}
    base = [by['BASE', i]['stream0_minus_stream7_TIR'] for i in range(1, 6)]
    reverse = [by['REVERSE', i]['stream0_minus_stream7_TIR'] for i in range(1, 6)]
    return {'verdict': 'ORDER_EFFECT_SUPPORTED' if all(x > 0 for x in base) and
            all(x < 0 for x in reverse) else 'ORDER_EFFECT_NOT_FULLY_SUPPORTED',
            'BASE_G_id': base, 'REVERSE_G_id': reverse,
            'rule': 'BASE 5/5 G_id>0 AND REVERSE 5/5 G_id<0',
            'statistical_significance_test': False}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if not args.output.resolve().is_relative_to(OUT.resolve()):
        raise RuntimeError('Analyzer output outside Order namespace')
    require_restore()
    load_plan()
    conditions = frozen_order()
    status = json.loads((OUT / 'sessions/stage_status.json').read_text())
    if status.get('all_valid') is not True or status.get('run_ids') != [c['run_id'] for c in conditions]:
        raise RuntimeError('Incomplete/INVALID 16-session Order campaign')
    measured, streams, servers, positions, exposures = [], [], [], [], []
    for condition in conditions:
        run, per_stream, server = run_metrics(condition)
        if run['integrity_status'] != 'VALID':
            raise RuntimeError('INVALID session: ' + condition['run_id'])
        if condition['stage'] == 'WARMUP':
            warmup = run
            continue
        measured.append(run)
        streams.extend(per_stream)
        servers.append(server)
        positions.extend(position_rows(condition))
        exposures.extend(exposure_rows(condition))
    if len(measured) != 15:
        raise RuntimeError('Wrong measured count')
    by = {(r['dispatch_order_mode'], r['repeat']): r for r in measured}
    rounds = []
    for i in range(1, 6):
        base, reverse, rotate = (by[mode, i] for mode in ('BASE','REVERSE','ROTATE'))
        rounds.append({'round': i,
                       'REV_minus_BASE_aggregate_TIR': reverse['TIR_admission']-base['TIR_admission'],
                       'ROT_minus_BASE_aggregate_TIR': rotate['TIR_admission']-base['TIR_admission'],
                       'REV_minus_BASE_worst_TIR': reverse['worst_stream_TIR']-base['worst_stream_TIR'],
                       'ROT_minus_BASE_worst_TIR': rotate['worst_stream_TIR']-base['worst_stream_TIR']})
    for run in measured:
        rr = [r for r in positions if r['run_id'] == run['run_id']]
        rr.sort(key=lambda r: r['dispatch_position'])
        if len(rr) != 8:
            raise RuntimeError('Incomplete position metrics')
        run['H_position'] = rr[0]['TIR']-rr[7]['TIR']
        run['Spearman_dispatch_position_vs_TIR'] = spearman([r['TIR'] for r in rr])
    args.output.mkdir(parents=True, exist_ok=False)
    put_csv(args.output / 'per_run.csv', measured)
    put_csv(args.output / 'per_stream.csv', streams)
    put_csv(args.output / 'per_dispatch_position.csv', positions)
    put_csv(args.output / 'dispatch_exposure_matrix.csv', exposures)
    put_csv(args.output / 'order_rounds.csv', rounds)
    put_csv(args.output / 'server_metrics.csv', servers)
    put_json(args.output / 'order_mechanism_summary.json', {
        **mechanism(measured),
        'round_descriptives': {key: describe([r[key] for r in rounds])
                               for key in rounds[0] if key != 'round'},
        'warmup_excluded': True, 'warmup_run_id': warmup['run_id']})
    put_json(args.output / 'provenance.json', {'plan_sha256': sha(PLAN),
        'CPU_restore_status': 'PASS', 'Edge_raw_required': True,
        'run_level_metrics_not_allocated_to_positions': ['pending', 'TX_bytes', 'observed_transmitted_data_rate'],
        'Thor_Edge_clock_subtraction': False})


if __name__ == '__main__':
    main()
