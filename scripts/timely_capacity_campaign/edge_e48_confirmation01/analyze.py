"""Log-only final Edge temporal calibration; analyzer requires Thor CPU restore."""
import argparse
import csv
import json
import statistics
import math
from pathlib import Path

from config import (OUT, PLAN, frozen_order, robust_class,
                    load_plan, schedule, sha, validate_source_rows)
from run_thor import cpu_report


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
            for path in OUT.glob('sessions/EDGE48C01_*/network_end.json')]
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
        'pattern': condition['pattern'], 'repeat': condition['repeat'],
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


def summarize_conditions(rows):
    summary = []
    for pattern in ('ALIGNED', 'STAGGERED'):
        rr = sorted((row for row in rows if row['pattern'] == pattern and row['rate'] == 48),
                    key=lambda row: row['repeat'])
        values = [row['TIR_admission'] for row in rr]
        summary.append({'pattern': pattern, 'rate': 48, 'classification': robust_class(rr),
            'repeats': len(rr), 'run_ids': [row['run_id'] for row in rr],
            'TIR_values': values, 'TIR_mean': statistics.mean(values),
            'TIR_median': statistics.median(values), 'TIR_min': min(values), 'TIR_max': max(values),
            'TIR_sample_SD': statistics.stdev(values),
            'timely_FPS_values': [row['timely_FPS'] for row in rr],
            'worst_stream_TIR_values': [row['worst_stream_TIR'] for row in rr]})
    rr = sorted((row for row in rows if row['rate']==64), key=lambda row:row['repeat'])
    values = [row['TIR_admission'] for row in rr]
    summary.append({'pattern':'STAGGERED','rate':64,'classification':'DESCRIPTIVE_HEADROOM_ONLY',
        'repeats':len(rr),'run_ids':[row['run_id'] for row in rr], 'TIR_values':values,
        'TIR_mean':statistics.mean(values),'TIR_min':min(values),'TIR_max':max(values),
        'TIR_sample_SD':statistics.stdev(values),
        'worst_stream_TIR_values':[row['worst_stream_TIR'] for row in rr]})
    return summary


def paired(rows):
    by = {(row['pattern'], row['repeat']): row for row in rows if row['rate']==48}
    return [{'pair':i, 'A_run_id':by['ALIGNED',i]['run_id'], 'S_run_id':by['STAGGERED',i]['run_id'],
             'delta_TIR_S_minus_A':by['STAGGERED',i]['TIR_admission']-by['ALIGNED',i]['TIR_admission']}
            for i in range(1,6)]


def scoring_eligible(condition):
    return condition['stage'] in ('CONFIRMATION', 'HEADROOM')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if not args.output.resolve().is_relative_to(OUT.resolve()):
        raise RuntimeError('Analyzer output must be under fresh E48 confirmation root')
    require_restore()
    load_plan()
    status = json.loads((OUT / 'sessions/stage_status.json').read_text())
    conditions = frozen_order()
    if status.get('all_valid') is not True or status.get('run_ids') != [c['run_id'] for c in conditions]:
        raise RuntimeError('Invalid/incomplete frozen 14-session campaign')
    rows, streams, servers = [], [], []
    for condition in conditions:
        row, per_stream, server = run_metrics(condition)
        if row['integrity_status'] != 'VALID':
            raise RuntimeError('Session invalid: '+condition['run_id'])
        if not scoring_eligible(condition):
            warmup = row
        else:
            rows.append(row)
            streams.extend(per_stream)
            servers.append(server)
    if any(row['integrity_status'] != 'VALID' for row in rows):
        raise RuntimeError('At least one run invalid; inspect preserved raw, no retry')
    if len(rows)!=13 or sum(row['rate']==48 for row in rows)!=10:
        raise RuntimeError('Wrong scored-session count')
    classes = summarize_conditions(rows)
    pairs=paired(rows)
    deltas=[p['delta_TIR_S_minus_A'] for p in pairs]
    args.output.mkdir(parents=True, exist_ok=False)
    put_json(args.output / 'warmup_integrity_only.json', {'run_id':warmup['run_id'],
        'integrity_status':warmup['integrity_status'], 'pending_active_end':warmup['Thor_client_pending_active_end'],
        'scoring_eligible':False})
    put_csv(args.output / 'per_run.csv', rows)
    put_csv(args.output / 'per_stream.csv', streams)
    put_csv(args.output / 'server_metrics.csv', servers)
    put_csv(args.output / 'condition_classification.csv', classes)
    put_csv(args.output / 'paired_E48.csv', pairs)
    put_json(args.output / 'paired_descriptive_summary.json', {'deltas':deltas,
        'positive_count':sum(d>0 for d in deltas),'mean':statistics.mean(deltas),
        'median':statistics.median(deltas),'min':min(deltas),'max':max(deltas),
        'significance_test':False,'robust_classification_input':False})
    put_json(args.output / 'provenance.json', {'plan_SHA256': sha(PLAN),
        'CPU_restore_status': 'PASS', 'phase_search_used': False,
        'Thor_versus_Edge_clock_subtraction': False,
        'server_queue_stall_count': 'N/A; queue timestamps and observed peak available',
        'warmup_excluded':True,'E64_robust_classification':False,
        'network_rate_definition':'network_TX_bytes_delta*8/seconds; observed transmitted-data rate, not PHY'})


if __name__ == '__main__':
    main()
