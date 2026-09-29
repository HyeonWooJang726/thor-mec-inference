"""Log-only final Edge temporal calibration; analyzer requires Thor CPU restore."""
import argparse
import csv
import json
import statistics
from pathlib import Path

from config import (OUT, PLAN, base_order, extension_orders, extension_branch,
                    load_plan, run_class, schedule, sha, validate_source_rows)
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


def client_pending(rows, active_start, active_end):
    """Admitted-but-not-submitted/expired work, clipped to Thor active time."""
    events = []
    for row in rows:
        begin = int(row['logical_arrival_ns'])
        terminal = row.get('socket_submission_ns') or row.get('expired_drop_ns')
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
            'active_end_count': level}


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
            for path in OUT.glob('*/EDGEF02_*/network_end.json')]
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
    count = condition['rate'] * 30
    if s.get('integrity_status') != 'VALID' or not s.get('drain_completed') \
            or not s.get('worker_thread_exited') or s.get('duplicates') or s.get('drops') \
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
    stage = 'base' if condition['stage'] == 'BASE' else 'extension'
    directory = OUT / stage / condition['run_id']
    m = json.loads((directory / 'manifest.json').read_text())
    s = json.loads((directory / 'summary.json').read_text())
    rows = read_csv(directory / 'source_frames.csv')
    fidelity = validate_source_rows(rows, condition, m['active_start_ns'])
    server_directory = OUT / ('received_edge_base' if stage == 'base' else 'received_edge_extension') / condition['run_id']
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
        per_stream.append({'run_id': condition['run_id'], 'stream_id': sid,
            'admitted': len(rr), 'timely': timely, 'TIR_admission': timely / len(rr) if rr else None})
    terminal = len(admitted) == int(s.get('timely', -1)) + int(s.get('late_completed', -1)) + int(s.get('expired', -1))
    errors = []
    if s.get('integrity_status') != 'VALID' or fidelity['status'] != 'PASS' or server['status'] != 'PASS':
        errors.append('Thor schedule/transport or server integrity failure')
    if m.get('plan_sha256') != sha(PLAN) or m.get('condition') != condition:
        errors.append('frozen plan/condition manifest mismatch')
    if not terminal or len(admitted) != condition['rate'] * 30:
        errors.append('exact terminal/admission accounting failure')
    if sum(row['timely'] for row in per_stream) != s.get('timely'):
        errors.append('per-stream/aggregate timely count mismatch')
    if server['received'] != s.get('completed') or server['received'] != s.get('payload_submitted_frames'):
        errors.append('Thor submission/server receipt mismatch')
    submitted_ids = sorted(int(r['edge_request_id']) for r in admitted
                           if r.get('socket_submission_ns') not in (None, ''))
    if server['request_ids'] != submitted_ids:
        errors.append('Thor submitted IDs differ from Edge received IDs')
    rate = {'run_id': condition['run_id'], 'stage': stage, 'rate': condition['rate'],
        'pattern': condition['pattern'], 'repeat': condition['repeat'],
        'admitted': len(admitted), 'completed': s.get('completed'),
        'timely': s.get('timely'), 'late_completed': s.get('late_completed'),
        'expired': s.get('expired'), 'TIR_admission': s.get('TIR_admission'),
        'admitted_FPS': len(admitted) / 30,
        'completed_FPS': s.get('completed', 0) / 30,
        'timely_FPS': s.get('timely_FPS'),
        'late_completed_FPS': s.get('late_completed', 0) / 30,
        'expired_FPS': s.get('expired', 0) / 30,
        'after_drain_true_unfinished': s.get('after_drain_unfinished'),
        'worst_stream_TIR': min(row['TIR_admission'] for row in per_stream),
        'Thor_offload_wait_p50_ms': percentile(offload_waits, 50),
        'Thor_offload_wait_p95_ms': percentile(offload_waits, 95),
        'Thor_offload_wait_p99_ms': percentile(offload_waits, 99),
        'Thor_client_pending_active_mean': pending['active_mean'],
        'Thor_client_pending_peak': pending['peak'],
        'Thor_client_pending_active_end': pending['active_end_count'],
        'Thor_request_response_p95_ms': s['request_response_latency_ms']['p95'],
        'server_queue_wait_p95_ms': server['server_queue_wait_p95_ms'],
        'server_inference_p95_ms': server['server_inference_p95_ms'],
        'server_queue_max_observed': server['server_queue_max_observed'],
        'server_queue_stall_event_count': None,
        'schedule_fidelity': fidelity['status'], 'integrity_status': 'VALID' if not errors else 'INVALID',
        'errors': errors, 'edge_transport_error_count': len(m.get('edge', {}).get('edge_path_errors', [])),
        'automatic_retry_count': 0, 'payload_submitted_bytes': s.get('payload_submitted_bytes'),
        'network_TX_bytes_delta': s.get('network_TX_bytes_delta')}
    return rate, per_stream, {'run_id': condition['run_id'], **server}


def summarize_conditions(rows):
    summary = []
    for pattern in ('ALIGNED', 'STAGGERED'):
        for rate in (72, 80, 88):
            rr = [row for row in rows if row['pattern'] == pattern and row['rate'] == rate]
            if not rr:
                status = 'NOT_TESTED'
            else:
                status = run_class(rr)
            summary.append({'pattern': pattern, 'rate': rate, 'classification': status,
                'repeats': len(rr), 'run_ids': [row['run_id'] for row in rr],
                'TIR_values': [row['TIR_admission'] for row in rr],
                'TIR_mean': statistics.mean(row['TIR_admission'] for row in rr) if rr else None,
                'timely_FPS_mean': statistics.mean(row['timely_FPS'] for row in rr) if rr else None,
                'historical_rows_in_classification': 0})
    return summary


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if not args.output.resolve().is_relative_to(OUT.resolve()):
        raise RuntimeError('Analyzer output must be under fresh final02 root')
    require_restore()
    plan = load_plan()
    base_status = json.loads((OUT / 'base/stage_status.json').read_text())
    if base_status.get('all_valid') is not True:
        raise RuntimeError('Invalid/incomplete base preflight')
    selection = json.loads((OUT / 'extension_selection.json').read_text())
    base_rows = [json.loads((OUT / 'base' / c['run_id'] / 'summary.json').read_text()) for c in base_order()]
    branch = extension_branch(base_rows)
    if branch != selection['branch'] or selection['base_plan_sha256'] != sha(PLAN):
        raise RuntimeError('Frozen E88 branch selection mismatch')
    if branch != 'NONE':
        ext = json.loads((OUT / 'extension/stage_status.json').read_text())
        if ext.get('all_valid') is not True:
            raise RuntimeError('Selected E88 extension incomplete/invalid')
    conditions = base_order() + extension_orders()[branch]
    rows, streams, servers = [], [], []
    for condition in conditions:
        row, per_stream, server = run_metrics(condition)
        rows.append(row)
        streams.extend(per_stream)
        servers.append(server)
    if any(row['integrity_status'] != 'VALID' for row in rows):
        raise RuntimeError('At least one run invalid; inspect preserved raw, no retry')
    classes = summarize_conditions(rows)
    usable = {pattern: max((row['rate'] for row in classes if row['pattern'] == pattern
             and row['classification'] == 'EDGE_USABLE'), default=None)
             for pattern in ('ALIGNED', 'STAGGERED')}
    checks = []
    for rate in (72, 80):
        a = [r for r in rows if r['rate'] == rate and r['pattern'] == 'ALIGNED']
        s = [r for r in rows if r['rate'] == rate and r['pattern'] == 'STAGGERED']
        checks.append({'rate': rate,
          'TIR_STAGGERED_ge_ALIGNED_both_repeats': all(x['TIR_admission'] >= y['TIR_admission'] for x, y in zip(s, a)),
          'server_queue_tail_STAGGERED_le_ALIGNED_both_repeats': all(
              x['server_queue_wait_p95_ms'] <= y['server_queue_wait_p95_ms'] for x, y in zip(s, a)),
          'verdict_effect': 'NONE'})
    args.output.mkdir(parents=True, exist_ok=False)
    put_csv(args.output / 'per_run.csv', rows)
    put_csv(args.output / 'per_stream.csv', streams)
    put_csv(args.output / 'server_metrics.csv', servers)
    put_csv(args.output / 'condition_classification.csv', classes)
    put_csv(args.output / 'mechanism_expectation_check.csv', checks)
    put_json(args.output / 'capacity_by_pattern.json', {'C_E_usable': usable,
        'E88_branch': branch, 'not_hybrid_capacity': True,
        'classification_rule': '2/2 TIR_admission >=0.90 usable; 2/2 <0.80 fail; otherwise boundary',
        'historical_rows_in_new_classification': 0})
    put_json(args.output / 'provenance.json', {'plan_SHA256': sha(PLAN),
        'CPU_restore_status': 'PASS', 'phase_search_used': False,
        'Thor_versus_Edge_clock_subtraction': False,
        'server_queue_stall_count': 'N/A; queue timestamps and observed peak available'})


if __name__ == '__main__':
    main()
