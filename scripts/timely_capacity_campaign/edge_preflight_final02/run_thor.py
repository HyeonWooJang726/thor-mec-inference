"""Explicit Edge-only temporal preflight; no Thor GPU/frequency or CPU writes."""
import argparse
import ipaddress
from datetime import datetime, timezone
import json
import re
import subprocess
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


def require_fresh_execution_namespace():
    forbidden = ('CPU_PIN_READBACK.json', 'CPU_RESTORE_READBACK.json',
                 'campaign_attempt.json', 'extension_attempt.json',
                 'extension_selection.json', 'base', 'extension',
                 'NETWORK_REACHABILITY_CHECK.json', 'EDGE_LISTENER_READY_BASE.json',
                 'EDGE_LISTENER_READY_EXTENSION.json')
    existing = [name for name in forbidden if (OUT / name).exists()]
    if existing:
        raise RuntimeError('Stale Final02 execution evidence: ' + ', '.join(existing))


def verify_local_artifacts(plan):
    names = ('plan.json', 'plan.sha256', 'source_sha256.json', 'EDGE_ENDPOINT_MANIFEST.json', 'CPU_STATE_BEFORE.json',
             'CPU_PIN_COMMANDS.sh', 'CPU_RESTORE_COMMANDS.sh',
             'EDGE_RATE_PATTERNS.json', 'ALIGNED_EDGE_SCHEDULES.json',
             'STAGGERED_EDGE_SCHEDULES.json', 'TEMPORAL_PATTERN_VALIDATION.json',
             'base_session_plan.json', 'edge_bundle/SHA256SUMS')
    names += tuple(f'extension_{branch}.json' for branch in extension_orders())
    missing = [name for name in names if not (OUT / name).is_file()]
    if missing:
        raise RuntimeError('Required local frozen artifact missing: ' + ', '.join(missing))
    if sha(ROOT / plan['cache']['path']) != plan['cache']['sha256']:
        raise RuntimeError('RAW640 cache mismatch')
    for name, digest in plan['session_plan_sha256'].items():
        if sha(OUT / name) != digest or sha(OUT / 'edge_bundle' / name) != digest:
            raise RuntimeError('Session plan/bundle SHA mismatch: ' + name)
    if sha(OUT / 'edge_bundle/plan.json') != sha(PLAN):
        raise RuntimeError('Edge bundle plan SHA mismatch')
    for line in (OUT / 'edge_bundle/SHA256SUMS').read_text().splitlines():
        digest, name = line.split('  ', 1)
        if Path(name).name != name or sha(OUT / 'edge_bundle' / name) != digest:
            raise RuntimeError('Edge bundle file SHA mismatch: ' + name)


def ping_edge_ip(host):
    if ipaddress.ip_address(host).version != 4:
        raise RuntimeError('Expected frozen IPv4 Edge endpoint')
    command = ['ping', '-c', '2', '-W', '1', host]
    record = {'command': command, 'timestamp_utc': datetime.now(timezone.utc).isoformat(),
              'monotonic_ns': time.monotonic_ns(), 'plan_sha256': sha(PLAN),
              'purpose': 'Diagnostic ICMP only; no TCP port/protocol/HELLO probe'}
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=6, check=False)
        record.update(returncode=result.returncode, stdout=result.stdout, stderr=result.stderr)
        match = re.search(r'(\d+)\s+packets transmitted,\s*(\d+)\s+(?:packets )?received,\s*([\d.]+)%\s+packet loss',
                          result.stdout)
        record.update(packets_transmitted=int(match.group(1)) if match else None,
                      packets_received=int(match.group(2)) if match else None,
                      packet_loss_percent=float(match.group(3)) if match else None)
    except (OSError, subprocess.TimeoutExpired) as exc:
        record.update(returncode=None, stdout='', stderr=repr(exc),
                      packets_transmitted=None, packets_received=None, packet_loss_percent=None)
    record['status'] = ('PASS' if record['returncode'] == 0 and
                        record['packets_received'] is not None and record['packets_received'] > 0
                        else 'NETWORK_ICMP_UNAVAILABLE')
    return record


def route_edge_ip(host):
    command = ['ip', 'route', 'get', host]
    record = {'command': command, 'timestamp_utc': datetime.now(timezone.utc).isoformat(),
              'monotonic_ns': time.monotonic_ns()}
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=5, check=False)
        record.update(returncode=result.returncode, stdout=result.stdout, stderr=result.stderr)
    except (OSError, subprocess.TimeoutExpired) as exc:
        record.update(returncode=None, stdout='', stderr=repr(exc))
    first = record['stdout'].splitlines()[0].split() if record['stdout'].splitlines() else []
    record['route_exists'] = (record['returncode'] == 0 and
                              (first[:1] == [host] or first[:2] == ['local', host]))
    record['status'] = 'PASS' if record['route_exists'] else 'PRE_EXECUTION_ROUTE_FAILURE'
    return record


def neighbor_edge_ip(host):
    command = ['ip', 'neigh', 'show', host]
    record = {'command': command, 'timestamp_utc': datetime.now(timezone.utc).isoformat(),
              'monotonic_ns': time.monotonic_ns()}
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=5, check=False)
        record.update(returncode=result.returncode, stdout=result.stdout, stderr=result.stderr)
    except (OSError, subprocess.TimeoutExpired) as exc:
        record.update(returncode=None, stdout='', stderr=repr(exc))
    match = re.search(r'\blladdr\s+([0-9a-fA-F:]+)\b', record['stdout'])
    state = re.search(r'\b(INCOMPLETE|FAILED|REACHABLE|STALE|DELAY|PROBE|PERMANENT|NOARP)\b',
                      record['stdout'])
    record['lladdr'] = match.group(1) if match else None
    record['state'] = state.group(1) if state else None
    record['status'] = ('RECORDED' if record['returncode'] == 0 and record['state']
                        else 'NEIGHBOR_DIAGNOSTIC_UNAVAILABLE')
    return record


def require_network_check():
    path = OUT / 'NETWORK_REACHABILITY_CHECK.json'
    if not path.is_file():
        raise RuntimeError('Fresh Edge route PASS required before CPU pin/workload')
    record = json.loads(path.read_text())
    host = load_plan()['edge_ip']
    route = record.get('route', {})
    first = route.get('stdout', '').splitlines()[0].split() if route.get('stdout', '').splitlines() else []
    if record.get('status') != 'PASS' or record.get('plan_sha256') != sha(PLAN) \
            or record.get('edge_ip') != host \
            or route.get('status') != 'PASS' or route.get('route_exists') is not True \
            or route.get('returncode') != 0 \
            or not (first[:1] == [host] or first[:2] == ['local', host]) \
            or route.get('command') != ['ip', 'route', 'get', host] \
            or record.get('neighbor', {}).get('command') != ['ip', 'neigh', 'show', host] \
            or record.get('icmp', {}).get('command') != ['ping', '-c', '2', '-W', '1', host] \
            or record.get('icmp', {}).get('status') not in ('PASS', 'NETWORK_ICMP_UNAVAILABLE'):
        raise RuntimeError('Edge route evidence invalid/stale')
    return record


def check_preexecution():
    plan = load_plan()
    require_fresh_execution_namespace()
    verify_local_artifacts(plan)
    if cpu_report('restored')['status'] != 'PASS':
        raise RuntimeError('Thor CPU not at frozen pre-pin baseline')
    host = plan['edge_ip']
    route = route_edge_ip(host)
    if route['status'] != 'PASS':
        failed = OUT / f'NETWORK_ROUTE_FAILURE_{route["monotonic_ns"]}.json'
        save(failed, {'status': 'PRE_EXECUTION_ROUTE_FAILURE', 'edge_ip': host,
                      'plan_sha256': sha(PLAN), 'route': route,
                      'neighbor': 'NOT_RUN_ROUTE_FAILURE', 'icmp': 'NOT_RUN_ROUTE_FAILURE'})
        print('FAIL: Edge route lookup; CPU pin and workload blocked. See ' + str(failed))
        return 2
    neighbor = neighbor_edge_ip(host)
    icmp = ping_edge_ip(host)
    warnings = []
    if neighbor['status'] != 'RECORDED':
        warnings.append('NEIGHBOR_DIAGNOSTIC_UNAVAILABLE')
    elif neighbor['state'] in ('FAILED', 'INCOMPLETE'):
        warnings.append('NETWORK_NEIGHBOR_UNRESOLVED')
    if icmp['status'] != 'PASS':
        warnings.append('NETWORK_ICMP_UNAVAILABLE')
    record = {'status': 'PASS', 'edge_ip': host, 'plan_sha256': sha(PLAN),
              'timestamp_utc': datetime.now(timezone.utc).isoformat(),
              'monotonic_ns': time.monotonic_ns(), 'route': route,
              'neighbor': neighbor, 'icmp': icmp, 'warnings': warnings,
              'readiness_scope': 'Route is hard pre-execution check; neighbor/ICMP are diagnostic only; listener evidence is required separately'}
    save(OUT / 'NETWORK_REACHABILITY_CHECK.json', record)
    print('PASS: frozen artifacts, fresh namespace, restored CPU, Edge route; '
          + ('NETWORK_ICMP_UNAVAILABLE warning; ' if 'NETWORK_ICMP_UNAVAILABLE' in warnings else '')
          + 'no TCP probe')
    return 0


def require_current_pin_evidence():
    net = require_network_check()
    path = OUT / 'CPU_PIN_READBACK.json'
    if not path.is_file() or (OUT / 'CPU_RESTORE_READBACK.json').exists():
        raise RuntimeError('Current-attempt CPU pin evidence missing or restore already recorded')
    report = json.loads(path.read_text())
    if report.get('status') != 'PASS' or report.get('mode') != 'pinned' \
            or report.get('plan_sha256') != sha(PLAN) \
            or report.get('network_check_monotonic_ns') != net['monotonic_ns'] \
            or report.get('snapshot', {}).get('monotonic_ns', -1) <= net['monotonic_ns']:
        raise RuntimeError('Stale/wrong CPU pin evidence')
    return report


def listener_evidence_name(stage):
    return 'EDGE_LISTENER_READY_BASE.json' if stage == 'BASE' else 'EDGE_LISTENER_READY_EXTENSION.json'


def record_listener_evidence(stage, stdout_path, ss_path):
    pin = require_current_pin_evidence()
    require_pin()
    if stage == 'BASE':
        count, branch = len(base_order()), None
    else:
        selection = json.loads((OUT / 'extension_selection.json').read_text())
        branch = selection['branch']
        if branch == 'NONE' or selection['base_plan_sha256'] != sha(PLAN):
            raise RuntimeError('No frozen E88 extension listener expected')
        count = len(extension_orders()[branch])
    stdout_path, ss_path = Path(stdout_path), Path(ss_path)
    stdout_text, ss_text = stdout_path.read_text(), ss_path.read_text()
    exact = f'LISTENING 5000: {count} {stage} sessions'
    if exact not in stdout_text.splitlines():
        raise RuntimeError('Exact Edge LISTENING stdout evidence missing')
    if not any(line.lstrip().startswith('LISTEN') and re.search(r':5000\b', line)
               for line in ss_text.splitlines()):
        raise RuntimeError('Edge-local ss LISTEN :5000 evidence missing')
    record = {'status': 'PASS', 'stage': stage, 'branch': branch, 'expected_sessions': count,
              'plan_sha256': sha(PLAN), 'monotonic_ns': time.monotonic_ns(),
              'CPU_pin_evidence_monotonic_ns': pin['snapshot']['monotonic_ns'],
              'stdout_file': str(stdout_path), 'stdout_sha256': sha(stdout_path),
              'ss_file': str(ss_path), 'ss_sha256': sha(ss_path),
              'stdout_exact_line': exact, 'ss_matching_lines': [line for line in ss_text.splitlines()
                  if line.lstrip().startswith('LISTEN') and re.search(r':5000\b', line)],
              'scope': 'Operator-supplied Edge stdout and Edge-local socket table; no Thor TCP probe'}
    save(OUT / listener_evidence_name(stage), record)
    return record


def require_listener_evidence(stage, pin):
    path = OUT / listener_evidence_name(stage)
    if not path.is_file():
        raise RuntimeError('Edge LISTENING and Edge-local ss evidence required before workload')
    record = json.loads(path.read_text())
    if record.get('status') != 'PASS' or record.get('stage') != stage \
            or record.get('plan_sha256') != sha(PLAN) \
            or record.get('CPU_pin_evidence_monotonic_ns') != pin['snapshot']['monotonic_ns'] \
            or record.get('monotonic_ns', -1) <= pin['snapshot']['monotonic_ns']:
        raise RuntimeError('Stale/wrong listener evidence')
    if stage == 'EXTENSION':
        selection = json.loads((OUT / 'extension_selection.json').read_text())
        if record.get('branch') != selection.get('branch'):
            raise RuntimeError('Edge extension listener branch mismatch')
    return record


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
    if summary['integrity_status'] != 'VALID':
        summary['diagnostic_ratio_before_integrity_exclusion'] = summary.get('TIR_admission')
        summary['TIR_admission'] = None
        summary['Edge_timely_ratio'] = None
        summary['timely_FPS'] = None
        summary['scientific_result_eligible'] = False
        if start is None and any('ConnectionRefusedError' in error for error in errors):
            summary['invalid_reason'] = 'INVALID_PRE_WORKLOAD_NETWORK_CONNECT'
            summary['failure_stage'] = 'TCP_CONNECTION_ESTABLISHMENT'
        elif any(token in error for error in errors for token in
                 ('Edge READY/configuration mismatch', 'protocol magic/version mismatch',
                  'HELLO/session mismatch')):
            summary['invalid_reason'] = 'INVALID_PROTOCOL_SESSION'
            summary['failure_stage'] = 'PROTOCOL_SESSION'
        elif start is None:
            summary['invalid_reason'] = 'INVALID_PRE_WORKLOAD'
            summary['failure_stage'] = 'BEFORE_ACTIVE_START'
        else:
            summary['invalid_reason'] = 'INVALID_ACTIVE_OR_DRAIN_INTEGRITY'
    else:
        summary['scientific_result_eligible'] = True
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
    pin_evidence = require_current_pin_evidence()
    listener_evidence = require_listener_evidence(stage, pin_evidence)
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
             'CPU_pin_evidence_monotonic_ns': pin_evidence['snapshot']['monotonic_ns'],
             'listener_evidence_monotonic_ns': listener_evidence['monotonic_ns'],
             'monotonic_ns': time.monotonic_ns(),
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
             'CPU_pin_evidence_monotonic_ns': pin_evidence['snapshot']['monotonic_ns'],
             'listener_evidence_monotonic_ns': listener_evidence['monotonic_ns'],
             'monotonic_ns': time.monotonic_ns(),
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
    require_current_pin_evidence()
    require_pin()
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
    parser.add_argument('action', choices=('check', 'cpu-pinned', 'cpu-restored', 'listener-confirmed',
                                           'base', 'select-extension', 'extension'))
    parser.add_argument('--approve-plan-sha256')
    parser.add_argument('--branch', choices=tuple(extension_orders()))
    parser.add_argument('--stage', choices=('BASE', 'EXTENSION'))
    parser.add_argument('--stdout-evidence')
    parser.add_argument('--ss-evidence')
    args = parser.parse_args()
    if args.action == 'check':
        return check_preexecution()
    if args.action == 'listener-confirmed':
        if not all((args.stage, args.stdout_evidence, args.ss_evidence)):
            raise RuntimeError('Listener evidence requires stage, stdout and Edge-local ss files')
        record = record_listener_evidence(args.stage, args.stdout_evidence, args.ss_evidence)
        print('PASS: ' + record['stdout_exact_line'] + '; Edge-local ss LISTEN :5000 recorded')
        return 0
    if args.action in ('cpu-pinned', 'cpu-restored'):
        mode = args.action.split('-')[1]
        net = require_network_check()
        if mode == 'pinned' and ((OUT / 'CPU_PIN_READBACK.json').exists() or
                                 (OUT / 'CPU_RESTORE_READBACK.json').exists()):
            raise RuntimeError('Preexisting CPU evidence; no stale PASS reuse')
        if mode == 'restored' and (OUT / 'CPU_RESTORE_READBACK.json').exists():
            raise RuntimeError('CPU restore readback already exists; no overwrite')
        report = cpu_report(mode)
        report.update(plan_sha256=sha(PLAN), network_check_monotonic_ns=net['monotonic_ns'])
        if mode == 'restored':
            report['campaign_attempt_present'] = (OUT / 'campaign_attempt.json').exists()
        save(OUT / ('CPU_PIN_READBACK.json' if mode == 'pinned' else 'CPU_RESTORE_READBACK.json'), report)
        print(report['status'])
        return 0 if report['status'] == 'PASS' else 2
    if args.action == 'select-extension':
        return select_extension()
    return stage_run('BASE' if args.action == 'base' else 'EXTENSION',
                     args.approve_plan_sha256, args.branch)


if __name__ == '__main__':
    raise SystemExit(main())
