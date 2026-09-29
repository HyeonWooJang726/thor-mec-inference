"""Explicit Edge-only temporal preflight; no Thor GPU/frequency or CPU writes."""
import argparse
import json
import sys
import time
import traceback
import types
from pathlib import Path

from config import (OUT, PLAN, ROOT, SECONDS, IDLE_SECONDS, PAYLOAD_BYTES,
                    base_order, extension_orders, extension_branch, hello,
                    load_plan, sha, validate_source_rows)

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'common'))
sys.path.insert(0, str(HERE.parent / 'common' / 'service_phase_b1f'))
sys.path.insert(0, str(HERE.parent / 'block_b_split' / 'v2'))
from reuse import pruning, prior
import edge_preflight as prior_evaluate
import cpu_state
import wifi_v2
from campaign_analysis import write_csv, quantiles


def save(path, value):
    with Path(path).open('x') as stream:
        json.dump(value, stream, indent=2)
        stream.write('\n')


def cpu_report(mode):
    reference = json.loads((OUT / 'CPU_STATE_BEFORE.json').read_text())
    current = cpu_state.snapshot()
    report = cpu_state.validate(current, reference, mode)
    if len(current['policies']) != 7 or any(
            row['fields']['scaling_max_freq'] != '2601000' for row in current['policies']):
        report['status'] = 'FAIL'
        report['errors'].append('Seven 2601000-kHz-max CPU policies required')
    if mode == 'pinned' and not all(row['time_in_state_readable'] for row in current['policies']):
        report['status'] = 'FAIL'
        report['errors'].append('CPU time_in_state unreadable')
    return report


def require_pin():
    report = cpu_report('pinned')
    if report['status'] != 'PASS':
        raise RuntimeError('CPU pin/readback mismatch: ' + str(report['errors']))
    return report


def net_counters():
    base = Path('/sys/class/net/wlP1p1s0')
    result = {}
    for key, rel in (('tx_bytes', 'statistics/tx_bytes'), ('rx_bytes', 'statistics/rx_bytes'),
                     ('carrier_changes', 'carrier_changes'), ('carrier_down_count', 'carrier_down_count'),
                     ('carrier_up_count', 'carrier_up_count'), ('operstate', 'operstate')):
        try:
            value = (base / rel).read_text().strip()
            result[key] = value if key == 'operstate' else int(value)
        except (OSError, ValueError) as exc:
            result[key] = None
            result[key + '_error'] = repr(exc)
    result['monotonic_ns'] = time.monotonic_ns()
    return result


def make_link():
    class Link(pruning.EdgeLink):
        pass

    def local_hello(c, run_id, digest):
        return hello(c, digest, prior.old.edge_runtime.CACHE_SHA256)

    fn = pruning.EdgeLink.__init__
    Link.__init__ = types.FunctionType(fn.__code__, dict(fn.__globals__, hello=local_hello),
                                       fn.__name__, fn.__defaults__, fn.__closure__)
    return Link


def run_one(c, payloads, digest, host, stage_root):
    directory = stage_root / c['run_id']
    directory.mkdir(exist_ok=False)
    before_cpu = require_pin()
    before_wifi = wifi_v2.capture()
    before_net = net_counters()
    save(directory / 'CPU_BEFORE.json', before_cpu)
    save(directory / 'wifi_start.json', before_wifi)
    save(directory / 'network_start.json', before_net)
    rows, admitted, errors, manifest = [], [], [], {}
    link = None
    start = None
    try:
        if before_wifi.get('status') != 'AVAILABLE' or before_wifi.get('connected') is not True:
            raise RuntimeError('Wi-Fi start connection unavailable')
        link = make_link()(dict(c, edge_r=c['per_stream_rate']), c['run_id'], manifest,
                           directory, errors.append, digest, host)
        start = time.monotonic_ns() + 200_000_000
        for frame in range(SECONDS * 30):
            due = start + frame * 10**9 // 30
            delay = (due - time.monotonic_ns()) / 1e9
            if delay > 0:
                time.sleep(delay)
            for sid in range(8):
                from config import bit
                selected = bit(c['rate'], c['pattern'], sid, frame)
                row = {'stream_id': sid, 'frame_id': frame,
                       'logical_arrival_ns': due, 'admission_timestamp_ns': due,
                       'admission_observed_ns': time.monotonic_ns(),
                       'admitted': selected, 'placement': 'EDGE' if selected else 'SKIP'}
                if selected:
                    rid = len(admitted)
                    row.update(edge_request_id=rid, edge_release_target_ns=due,
                               absolute_deadline_ns=due + 100_000_000,
                               sample_id=frame % len(payloads))
                    admitted.append(row)
                    link.put(row, payloads[frame % len(payloads)])
                rows.append(row)
        end = start + SECONDS * 10**9
        delay = (end - time.monotonic_ns()) / 1e9
        if delay > 0:
            time.sleep(delay)
        link.finish()
        if not link.done.wait(300):
            raise RuntimeError('Natural Edge drain timeout')
    except BaseException:
        errors.append(traceback.format_exc())
    finally:
        if link is not None:
            link.close()
    after_cpu = cpu_report('pinned')
    after_wifi = wifi_v2.capture()
    after_net = net_counters()
    save(directory / 'CPU_AFTER.json', after_cpu)
    save(directory / 'wifi_end.json', after_wifi)
    save(directory / 'network_end.json', after_net)
    if rows:
        write_csv(directory / 'source_frames.csv', rows)
    fidelity = validate_source_rows(rows, c, start) if start is not None else {'status': 'FAIL', 'errors': ['No active start']}
    save(directory / 'schedule_fidelity.json', fidelity)
    try:
        summary = prior_evaluate.evaluate(admitted, manifest.get('edge_final', {}), errors, c['rate'], start)
    except Exception:
        summary = {'rate': c['rate'], 'integrity_status': 'INVALID',
                   'errors': errors + [traceback.format_exc()]}
    net_ok = all(before_net.get(key) is not None and after_net.get(key) == before_net.get(key)
                 for key in ('carrier_changes', 'carrier_down_count', 'carrier_up_count'))
    wifi_ok = before_wifi.get('status') == after_wifi.get('status') == 'AVAILABLE' \
        and before_wifi.get('connected') is after_wifi.get('connected') is True \
        and before_wifi.get('BSSID') == after_wifi.get('BSSID')
    if fidelity['status'] != 'PASS' or after_cpu['status'] != 'PASS' or not net_ok or not wifi_ok \
            or not manifest.get('edge_threads_exited', False):
        summary['integrity_status'] = 'INVALID'
        summary.setdefault('errors', []).append('schedule/CPU/Wi-Fi/carrier/Edge-thread hard integrity failure')
    lat = [(row['response_completion_ns'] - row['socket_submission_ns']) / 1e6
           for row in admitted if row.get('response_completion_ns') and row.get('socket_submission_ns')]
    active_end = start + SECONDS * 10**9 if start is not None else None
    summary.update(run_id=c['run_id'], pattern=c['pattern'], repeat=c['repeat'], stage=c['stage'],
        TIR_admission=summary.get('Edge_timely_ratio'),
        late_completed=summary.get('completed', 0) - summary.get('timely', 0),
        request_response_latency_ms=quantiles(lat),
        request_response_definition='Thor monotonic socket_submission_ns to response_completion_ns; not one-way network',
        active_completed_FPS=sum(start <= row.get('response_completion_ns', -1) < active_end for row in admitted) / SECONDS if start is not None else None,
        server_queue_peak_from_FINAL=manifest.get('edge_final', {}).get('queue_peak_observed'),
        server_queue_stall_event_count=None,
        server_queue_stall_note='No distinct stall-event counter in frozen server; queue timestamps available in server requests.csv',
        payload_admitted_frames=len(admitted), payload_bytes_per_frame=PAYLOAD_BYTES,
        payload_submitted_frames=sum(row.get('socket_submission_ns') is not None for row in admitted),
        payload_submitted_bytes=PAYLOAD_BYTES * sum(row.get('socket_submission_ns') is not None for row in admitted),
        network_TX_bytes_delta=(after_net['tx_bytes'] - before_net['tx_bytes']) if before_net.get('tx_bytes') is not None and after_net.get('tx_bytes') is not None else None,
        wifi=wifi_v2.compare(before_wifi, after_wifi), network_carrier_counters_unchanged=net_ok,
        CPU_pin_start=before_cpu['status'], CPU_pin_end=after_cpu['status'],
        Thor_GPU_frequency_restore='NOT_APPLICABLE_NO_THOR_GPU_CONTROL')
    if summary.get('admitted') != SECONDS * c['rate'] or summary.get('after_drain_unfinished') != 0 \
            or summary.get('admitted') != summary.get('timely', -1) + summary.get('late_completed', -1) + summary.get('expired', -1):
        summary['integrity_status'] = 'INVALID'
        summary.setdefault('errors', []).append('Exact terminal partition/assigned rate failure')
    save(directory / 'manifest.json', {'plan_sha256': digest, 'condition': c,
         'active_start_ns': start, 'active_end_ns': active_end, 'edge': manifest,
         'input_scope': 'Cached actual RAW64030, source K8x30 synchronized slot admission; no Local inference',
         'source_phase_ns': [0] * 8, 'CPU_before': before_cpu, 'CPU_after': after_cpu,
         'wifi_start': before_wifi, 'wifi_end': after_wifi})
    save(directory / 'summary.json', summary)
    with (directory / 'stderr.log').open('x') as stream:
        stream.write('\n'.join(summary.get('errors', [])))
    return summary


def stage_run(stage, approval, branch=None):
    plan = load_plan()
    digest = sha(PLAN)
    if approval != digest:
        raise RuntimeError('Exact Edge preflight plan SHA approval required')
    if sha(ROOT / plan['cache']['path']) != plan['cache']['sha256']:
        raise RuntimeError('RAW640 cache mismatch')
    payloads, _ = prior.old.edge_runtime.load_cache(ROOT / plan['cache']['path'])
    pin = require_pin()
    wifi_ready = wifi_v2.capture()
    network_ready = net_counters()
    if wifi_ready.get('status') != 'AVAILABLE' or wifi_ready.get('connected') is not True \
            or any(network_ready.get(key) is None for key in
                   ('carrier_changes', 'carrier_down_count', 'carrier_up_count')):
        raise RuntimeError('Wi-Fi endpoint/carrier diagnostics unavailable before attempt marker')
    if stage == 'BASE':
        if (OUT / 'campaign_attempt.json').exists() or (OUT / 'base').exists():
            raise RuntimeError('Existing base attempt; no retry/resume/overwrite')
        order = base_order()
        save(OUT / 'campaign_attempt.json', {'plan_sha256': digest, 'CPU_pin': pin,
             'status': 'BASE_STARTED; user CPU restore required after success/failure/interruption'})
        stage_root = OUT / 'base'
    else:
        selection = json.loads((OUT / 'extension_selection.json').read_text())
        if branch != selection['branch'] or branch == 'NONE' or selection['base_plan_sha256'] != digest:
            raise RuntimeError('Requested extension differs from deterministic frozen selection')
        if (OUT / 'extension').exists() or (OUT / 'extension_attempt.json').exists():
            raise RuntimeError('Existing extension attempt; no retry/resume/overwrite')
        prior_end = OUT / 'base' / base_order()[-1]['run_id'] / 'network_end.json'
        if not prior_end.exists():
            raise RuntimeError('Base final run lacks end timestamp; no extension')
        order = extension_orders()[branch]
        save(OUT / 'extension_attempt.json', {'plan_sha256': digest, 'branch': branch,
             'CPU_pin': pin, 'status': 'EXTENSION_STARTED; user CPU restore required'})
        stage_root = OUT / 'extension'
    stage_root.mkdir(exist_ok=False)
    if stage == 'EXTENSION':
        last_end_ns = json.loads(prior_end.read_text())['monotonic_ns']
        remaining = IDLE_SECONDS - (time.monotonic_ns() - last_end_ns) / 1e9
        if remaining > 0:
            time.sleep(remaining)
    results = []
    for index, condition in enumerate(order):
        if index:
            time.sleep(IDLE_SECONDS)
        require_pin()
        result = run_one(condition, payloads, digest, plan['edge_host'], stage_root)
        results.append(result)
        print(json.dumps({'run_id': condition['run_id'], 'integrity_status': result['integrity_status'],
                          'TIR_admission': result.get('TIR_admission')}), flush=True)
        if result['integrity_status'] != 'VALID':
            break
    save(stage_root / 'stage_status.json', {'planned': len(order), 'completed': len(results),
         'run_ids': [row['run_id'] for row in results], 'all_valid': len(results) == len(order)
         and all(row['integrity_status'] == 'VALID' for row in results)})
    return 0 if len(results) == len(order) and all(row['integrity_status'] == 'VALID' for row in results) else 2


def select_extension():
    plan = load_plan()
    if (OUT / 'extension_selection.json').exists():
        raise RuntimeError('Extension already selected; no overwrite')
    status = json.loads((OUT / 'base/stage_status.json').read_text())
    if status.get('all_valid') is not True:
        raise RuntimeError('Invalid/incomplete base; no extension')
    rows = [json.loads((OUT / 'base' / c['run_id'] / 'summary.json').read_text()) for c in base_order()]
    branch = extension_branch(rows)
    save(OUT / 'extension_selection.json', {'base_plan_sha256': sha(PLAN), 'branch': branch,
         'condition_ids': [row['run_id'] for row in extension_orders()[branch]],
         'rule': 'Each pattern E80 must be 2/2 EDGE_USABLE; no result-based retuning'})
    print(branch)
    return 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=('check', 'cpu-pinned', 'cpu-restored', 'base', 'select-extension', 'extension'))
    parser.add_argument('--approve-plan-sha256')
    parser.add_argument('--branch', choices=tuple(extension_orders()))
    args = parser.parse_args()
    if args.action == 'check':
        p = load_plan()
        if sha(ROOT / p['cache']['path']) != p['cache']['sha256']:
            raise RuntimeError('RAW640 cache mismatch')
        print('PASS: frozen plan/source/cache; no network or CPU/GPU changes')
        return 0
    if args.action in ('cpu-pinned', 'cpu-restored'):
        mode = args.action.split('-')[1]
        report = cpu_report(mode)
        save(OUT / ('CPU_PIN_READBACK.json' if mode == 'pinned' else 'CPU_RESTORE_READBACK.json'), report)
        print(report['status'])
        return 0 if report['status'] == 'PASS' else 2
    if args.action == 'select-extension':
        return select_extension()
    return stage_run('BASE' if args.action == 'base' else 'EXTENSION',
                     args.approve_plan_sha256, args.branch)


if __name__ == '__main__':
    raise SystemExit(main())
