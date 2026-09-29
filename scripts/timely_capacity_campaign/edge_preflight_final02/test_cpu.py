"""No GPU/network: mask, fidelity, gate and launcher guard fixtures."""
import copy
import csv
import json
import math
import socket
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import config
import run_thor
import analyze

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(config.ROOT / 'scripts/edge_raw_capacity_gate'))
sys.path.insert(0, str(config.ROOT / 'results/timely_capacity_campaign/block_b_split/v2/edge_bundle_v2'))
import edge_server_final02 as server


def trace(rate, pattern, start=10**12):
    condition = config.condition(rate, pattern, 1, 'BASE', 1)
    rows = []
    rid = 0
    for frame in range(config.SECONDS * 30):
        due = start + frame * 10**9 // 30
        for sid in range(8):
            admitted = config.bit(rate, pattern, sid, frame)
            row = {'stream_id': sid, 'frame_id': frame, 'logical_arrival_ns': due,
                   'admission_timestamp_ns': due, 'admission_observed_ns': due + 100 + sid,
                   'admitted': admitted, 'placement': 'EDGE' if admitted else 'SKIP'}
            if admitted:
                row.update(edge_request_id=rid, edge_release_target_ns=due,
                           absolute_deadline_ns=due + 100_000_000)
                rid += 1
            rows.append(row)
    return condition, rows, start


class EdgeTemporalCPU(unittest.TestCase):
    def test_canonical_q_exact_counts_and_rule(self):
        for rate in (72, 80, 88):
            q = config.q(rate)
            self.assertEqual(len(q), 30)
            self.assertEqual(sum(q), rate // 8)
            self.assertEqual(q, tuple(int((i + 1) * (rate // 8) // 30 > i * (rate // 8) // 30)
                                      for i in range(30)))
            self.assertEqual(sum(config.schedule(rate, 'ALIGNED')['m_n']), rate)
            self.assertEqual(sum(config.schedule(rate, 'STAGGERED')['m_n']), rate)

    def test_aligned_staggered_exact_shift_and_bounds(self):
        for rate in (72, 80, 88):
            a = config.schedule(rate, 'ALIGNED')
            s = config.schedule(rate, 'STAGGERED')
            self.assertEqual(a['per_stream_admissions_per_30_slots'], [rate // 8] * 8)
            self.assertEqual(s['per_stream_admissions_per_30_slots'], [rate // 8] * 8)
            self.assertEqual(s['phases'], list(range(8)))
            self.assertEqual(config.condition(rate, 'ALIGNED', 1, 'BASE', 1)['phase_vector'], [0] * 8)
            self.assertEqual(config.condition(rate, 'STAGGERED', 1, 'BASE', 1)['phase_vector'], list(range(8)))
            for sid in range(8):
                self.assertEqual(s['per_stream_masks'][sid],
                    [config.q(rate)[(i - sid) % 30] for i in range(30)])
            self.assertEqual(s['theoretical_peak_lower_bound'], math.ceil(rate / 30))
            self.assertFalse(s['global_optimality_claim'])
            self.assertFalse(s['phase_search_used'])

    def test_actual_schedule_fidelity_and_adverse_fixtures(self):
        for rate in (72, 80, 88):
            for pattern in ('ALIGNED', 'STAGGERED'):
                c, rows, start = trace(rate, pattern)
                self.assertEqual(config.validate_source_rows(rows, c, start)['status'], 'PASS')
        c, rows, start = trace(80, 'STAGGERED')
        changes = (
            lambda x: x[0].__setitem__('logical_arrival_ns', start + 1),
            lambda x: x[0].__setitem__('admission_timestamp_ns', start + 1),
            lambda x: x[0].__setitem__('admitted', 1 - x[0]['admitted']),
            lambda x: x[0].__setitem__('admission_observed_ns', start + 200),
            lambda x: x[1].__setitem__('admission_observed_ns', start + 50),
        )
        for change in changes:
            bad = copy.deepcopy(rows)
            change(bad)
            self.assertEqual(config.validate_source_rows(bad, c, start)['status'], 'FAIL')
        selected = next(i for i, row in enumerate(rows) if row['admitted'])
        bad = copy.deepcopy(rows)
        bad[selected]['edge_release_target_ns'] += 33_333_333
        self.assertEqual(config.validate_source_rows(bad, c, start)['status'], 'FAIL')

    def test_hello_matches_frozen_edge_adapter(self):
        c = config.base_order()[0]
        self.assertEqual(config.hello(c, 'plan', 'cache'), server.expected_hello(c, 'plan', 'cache'))
        self.assertEqual(config.PAYLOAD_BYTES, 640 * 360 * 3)

    def test_two_repeat_classifications_and_branch(self):
        def two(rate, pattern, values):
            return [dict(run_id=config.condition(rate, pattern, i, 'BASE', i)['run_id'],
                         rate=rate, pattern=pattern, repeat=i, integrity_status='VALID',
                         TIR_admission=value) for i, value in enumerate(values, 1)]
        self.assertEqual(config.run_class(two(80, 'ALIGNED', (.90, .91))), 'EDGE_USABLE')
        self.assertEqual(config.run_class(two(80, 'ALIGNED', (.79, .79))), 'EDGE_FAIL')
        self.assertEqual(config.run_class(two(80, 'ALIGNED', (.90, .79))), 'EDGE_BOUNDARY')
        self.assertEqual(config.run_class(two(80, 'ALIGNED', (.85, .85))), 'EDGE_BOUNDARY')
        for a, s, branch in ((True, True, 'BOTH'), (True, False, 'ALIGNED_ONLY'),
                             (False, True, 'STAGGERED_ONLY'), (False, False, 'NONE')):
            rows = []
            for c in config.base_order():
                usable = a if c['pattern'] == 'ALIGNED' else s
                rows.append(dict(run_id=c['run_id'], rate=c['rate'], pattern=c['pattern'],
                                 repeat=c['repeat'], integrity_status='VALID',
                                 TIR_admission=.95 if c['rate'] == 72 or usable else .85))
            self.assertEqual(config.extension_branch(rows), branch)
        with self.assertRaises(ValueError):
            config.extension_branch(rows[:-1])

    def test_cpu_and_restore_hard_guards(self):
        with mock.patch.object(run_thor, 'cpu_report', return_value={'status': 'FAIL', 'errors': ['pin mismatch']}):
            with self.assertRaises(RuntimeError):
                run_thor.require_pin()
        with tempfile.TemporaryDirectory() as temporary:
            with mock.patch.object(analyze, 'OUT', Path(temporary)):
                with self.assertRaisesRegex(RuntimeError, 'CPU restore PASS required'):
                    analyze.require_restore()

    def test_server_accounting_and_queue_timestamp_fixture(self):
        c = config.base_order()[0]
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            count = c['rate'] * config.SECONDS
            summary = {'integrity_status': 'VALID', 'drain_completed': True,
                'worker_thread_exited': True, 'duplicates': 0, 'drops': 0,
                'queue_cap_saturation': False, 'received': 2, 'completed': 2,
                'responses_sent': 2, 'queue_peak_observed': 1}
            (directory / 'summary.json').write_text(json.dumps(summary))
            with (directory / 'requests.csv').open('w', newline='') as stream:
                writer = csv.DictWriter(stream, fieldnames=('request_id', 'queue_enter_ns',
                    'queue_start_ns', 'inference_start_ns', 'inference_end_ns'))
                writer.writeheader()
                writer.writerows(({'request_id': rid, 'queue_enter_ns': 1000,
                    'queue_start_ns': 2000, 'inference_start_ns': 2000,
                    'inference_end_ns': 4000} for rid in range(2)))
            self.assertEqual(analyze.server_metrics(directory, c)['status'], 'PASS')
            self.assertEqual(analyze.server_metrics(directory, c)['request_ids'], [0, 1])
            summary['received'] = 3
            (directory / 'summary.json').write_text(json.dumps(summary))
            self.assertEqual(analyze.server_metrics(directory, c)['status'], 'FAIL')

    def test_historical_rows_never_enter_new_classifier(self):
        rows = []
        for c in config.base_order():
            rows.append({'run_id': c['run_id'], 'rate': c['rate'], 'pattern': c['pattern'],
                'repeat': c['repeat'], 'integrity_status': 'VALID', 'TIR_admission': .91,
                'timely_FPS': c['rate'] * .91})
        classes = analyze.summarize_conditions(rows)
        self.assertTrue(all(row['historical_rows_in_classification'] == 0 for row in classes))
        self.assertEqual([row['classification'] for row in classes if row['rate'] == 88],
                         ['NOT_TESTED', 'NOT_TESTED'])

    def test_offline_client_pending_integral(self):
        import analyze
        rows = [{'logical_arrival_ns': 0, 'socket_submission_ns': 2_000_000_000},
                {'logical_arrival_ns': 1_000_000_000, 'expired_drop_ns': 3_000_000_000}]
        result = analyze.client_pending(rows, 0, 4_000_000_000)
        self.assertEqual(result['peak'], 2)
        self.assertEqual(result['active_end_count'], 0)
        self.assertEqual(result['active_mean'], 1.0)

    def test_final01_refusal_is_invalid_not_capacity_failure(self):
        old = config.ROOT / 'results/timely_capacity_campaign/v2_2/edge_preflight_final01/base/EDGEF01_E72_A1'
        summary = json.loads((old / 'summary.json').read_text())
        manifest = json.loads((old / 'manifest.json').read_text())
        self.assertEqual(summary['integrity_status'], 'INVALID')
        self.assertIsNone(manifest['active_start_ns'])
        self.assertEqual(summary['payload_admitted_frames'], 0)
        self.assertEqual(summary['completed'], 0)
        self.assertEqual(summary['after_drain_unfinished'], 2160)
        self.assertIn('ConnectionRefusedError', (old / 'stderr.log').read_text())
        invalid = dict(integrity_status='INVALID', repeat=1, TIR_admission=0.0)
        self.assertEqual(config.run_class([invalid, invalid]), 'INVALID')

    def test_final02_connection_refusal_terminal_label(self):
        condition = config.base_order()[0]
        with tempfile.TemporaryDirectory() as temporary:
            wifi = {'status': 'AVAILABLE', 'connected': True, 'BSSID': 'CPU_SYNTHETIC'}
            net = {'tx_bytes': 0, 'carrier_changes': 1,
                   'carrier_down_count': 0, 'carrier_up_count': 1}
            with mock.patch.object(run_thor, 'require_pin', return_value={'status': 'PASS'}), \
                    mock.patch.object(run_thor, 'cpu_report', return_value={'status': 'PASS'}), \
                    mock.patch.object(run_thor.wifi_v2, 'capture', return_value=wifi), \
                    mock.patch.object(run_thor, 'net_counters', return_value=net), \
                    mock.patch.object(run_thor, 'make_link', return_value=mock.Mock(
                        side_effect=ConnectionRefusedError(111, 'Connection refused'))):
                row = run_thor.run_one(condition, [b'CPU_SYNTHETIC'], 'CPU_PLAN',
                                       config.load_plan()['edge_ip'], Path(temporary))
            self.assertEqual(row['integrity_status'], 'INVALID')
            self.assertEqual(row['invalid_reason'], 'INVALID_PRE_WORKLOAD_NETWORK_CONNECT')
            self.assertEqual(row['failure_stage'], 'TCP_CONNECTION_ESTABLISHMENT')
            self.assertIsNone(row['TIR_admission'])
            self.assertIsNone(row['timely_FPS'])
            self.assertEqual(row['payload_admitted_frames'], 0)
            self.assertFalse(row['scientific_result_eligible'])

    def test_protocol_session_mismatch_is_invalid_not_capacity(self):
        condition = config.base_order()[0]
        with tempfile.TemporaryDirectory() as temporary:
            wifi = {'status': 'AVAILABLE', 'connected': True, 'BSSID': 'CPU_SYNTHETIC'}
            net = {'tx_bytes': 0, 'carrier_changes': 1,
                   'carrier_down_count': 0, 'carrier_up_count': 1}
            with mock.patch.object(run_thor, 'require_pin', return_value={'status': 'PASS'}), \
                    mock.patch.object(run_thor, 'cpu_report', return_value={'status': 'PASS'}), \
                    mock.patch.object(run_thor.wifi_v2, 'capture', return_value=wifi), \
                    mock.patch.object(run_thor, 'net_counters', return_value=net), \
                    mock.patch.object(run_thor, 'make_link', return_value=mock.Mock(
                        side_effect=RuntimeError('Edge READY/configuration mismatch'))):
                row = run_thor.run_one(condition, [b'CPU_SYNTHETIC'], 'CPU_PLAN',
                                       config.load_plan()['edge_ip'], Path(temporary))
            self.assertEqual(row['integrity_status'], 'INVALID')
            self.assertEqual(row['invalid_reason'], 'INVALID_PROTOCOL_SESSION')
            self.assertIsNone(row['TIR_admission'])

    def test_ping_success_failure_and_no_tcp_probe(self):
        success = '2 packets transmitted, 2 received, 0% packet loss, time 1000ms\n'
        failure = '2 packets transmitted, 0 received, 100% packet loss, time 1000ms\n'
        current_ip = config.load_plan()['edge_ip']
        stale_ip = json.loads((config.OUT / 'NETWORK_REACHABILITY_FAILURE_18576305639059.json').read_text())['command'][-1]
        self.assertNotEqual(stale_ip, current_ip)
        with mock.patch('socket.create_connection', side_effect=AssertionError('TCP probe forbidden')) as tcp:
            with mock.patch.object(run_thor.subprocess, 'run', return_value=SimpleNamespace(
                    returncode=0, stdout=success, stderr='')) as ping:
                row = run_thor.ping_edge_ip(current_ip)
                self.assertEqual(row['status'], 'PASS')
                self.assertEqual(row['packets_received'], 2)
                ping.assert_called_once()
                self.assertEqual(ping.call_args.args[0], ['ping', '-c', '2', '-W', '1', current_ip])
            with mock.patch.object(run_thor.subprocess, 'run', return_value=SimpleNamespace(
                    returncode=1, stdout=failure, stderr='')):
                self.assertEqual(run_thor.ping_edge_ip(stale_ip)['status'], 'NETWORK_ICMP_UNAVAILABLE')
            tcp.assert_not_called()

    def test_check_route_pass_ping_diagnostic_and_fresh_cpu_evidence(self):
        with tempfile.TemporaryDirectory() as temporary:
            out = Path(temporary)
            host = config.load_plan()['edge_ip']
            route = {'status': 'PASS', 'route_exists': True, 'returncode': 0,
                     'stdout': f'{host} dev wlP1p1s0 src 192.168.0.189\n',
                     'command': ['ip', 'route', 'get', host]}
            neighbor = {'status': 'RECORDED', 'state': 'DELAY',
                        'command': ['ip', 'neigh', 'show', host]}
            ping = {'status': 'NETWORK_ICMP_UNAVAILABLE',
                    'command': ['ping', '-c', '2', '-W', '1', host]}
            with mock.patch.object(run_thor, 'OUT', out), \
                    mock.patch.object(run_thor, 'load_plan', return_value={'edge_ip': host}), \
                    mock.patch.object(run_thor, 'verify_local_artifacts'), \
                    mock.patch.object(run_thor, 'cpu_report', return_value={'status': 'PASS'}), \
                    mock.patch.object(run_thor, 'route_edge_ip', return_value=route) as route_mock, \
                    mock.patch.object(run_thor, 'neighbor_edge_ip', return_value=neighbor), \
                    mock.patch.object(run_thor, 'ping_edge_ip', return_value=ping) as ping_mock:
                self.assertEqual(run_thor.check_preexecution(), 0)
                route_mock.assert_called_once_with(host)
                ping_mock.assert_called_once_with(host)
                self.assertTrue((out / 'NETWORK_REACHABILITY_CHECK.json').exists())
                record = run_thor.require_network_check()
                self.assertEqual(record['status'], 'PASS')
                self.assertIn('NETWORK_ICMP_UNAVAILABLE', record['warnings'])
                with self.assertRaisesRegex(RuntimeError, 'Stale Final02 execution evidence'):
                    run_thor.check_preexecution()
            with mock.patch.object(run_thor, 'OUT', out):
                (out / 'NETWORK_REACHABILITY_CHECK.json').unlink()
                (out / 'CPU_PIN_READBACK.json').write_text('{}')
                with self.assertRaisesRegex(RuntimeError, 'Stale Final02 execution evidence'):
                    run_thor.require_fresh_execution_namespace()
                (out / 'CPU_PIN_READBACK.json').unlink()
                (out / 'CPU_RESTORE_READBACK.json').write_text('{}')
                with self.assertRaisesRegex(RuntimeError, 'Stale Final02 execution evidence'):
                    run_thor.require_fresh_execution_namespace()

    def test_ping_success_route_pass(self):
        with tempfile.TemporaryDirectory() as temporary:
            out = Path(temporary)
            host = config.load_plan()['edge_ip']
            route = {'status': 'PASS', 'route_exists': True, 'returncode': 0,
                     'stdout': f'{host} dev wlP1p1s0 src 192.168.0.189\n',
                     'command': ['ip', 'route', 'get', host]}
            neighbor = {'status': 'RECORDED', 'state': 'FAILED',
                        'command': ['ip', 'neigh', 'show', host]}
            ping = {'status': 'PASS', 'command': ['ping', '-c', '2', '-W', '1', host],
                    'packets_received': 2}
            with mock.patch.object(run_thor, 'OUT', out), \
                    mock.patch.object(run_thor, 'load_plan', return_value={'edge_ip': host}), \
                    mock.patch.object(run_thor, 'verify_local_artifacts'), \
                    mock.patch.object(run_thor, 'cpu_report', return_value={'status': 'PASS'}), \
                    mock.patch.object(run_thor, 'route_edge_ip', return_value=route), \
                    mock.patch.object(run_thor, 'neighbor_edge_ip', return_value=neighbor), \
                    mock.patch.object(run_thor, 'ping_edge_ip', return_value=ping):
                self.assertEqual(run_thor.check_preexecution(), 0)
                self.assertEqual(run_thor.require_network_check()['warnings'],
                                 ['NETWORK_NEIGHBOR_UNRESOLVED'])

    def test_route_failure_before_attempt_marker(self):
        with tempfile.TemporaryDirectory() as temporary:
            out = Path(temporary)
            route = {'status': 'PRE_EXECUTION_ROUTE_FAILURE', 'monotonic_ns': 101,
                     'route_exists': False, 'command': ['ip', 'route', 'get', config.load_plan()['edge_ip']]}
            with mock.patch.object(run_thor, 'OUT', out), \
                    mock.patch.object(run_thor, 'load_plan', return_value={'edge_ip': config.load_plan()['edge_ip']}), \
                    mock.patch.object(run_thor, 'verify_local_artifacts'), \
                    mock.patch.object(run_thor, 'cpu_report', return_value={'status': 'PASS'}), \
                    mock.patch.object(run_thor, 'route_edge_ip', return_value=route), \
                    mock.patch.object(run_thor, 'ping_edge_ip') as ping_mock:
                self.assertEqual(run_thor.check_preexecution(), 2)
                ping_mock.assert_not_called()
                self.assertFalse((out / 'campaign_attempt.json').exists())
                self.assertFalse((out / 'CPU_PIN_READBACK.json').exists())
                self.assertTrue((out / 'NETWORK_ROUTE_FAILURE_101.json').exists())

    def test_route_neighbor_commands_and_no_port_probe(self):
        host = config.load_plan()['edge_ip']
        with mock.patch('socket.create_connection', side_effect=AssertionError('TCP probe forbidden')) as tcp:
            with mock.patch.object(run_thor.subprocess, 'run', return_value=SimpleNamespace(
                    returncode=0, stdout=f'{host} dev wlP1p1s0 src 192.168.0.189\n', stderr='')) as command:
                self.assertEqual(run_thor.route_edge_ip(host)['status'], 'PASS')
                self.assertEqual(command.call_args.args[0], ['ip', 'route', 'get', host])
            with mock.patch.object(run_thor.subprocess, 'run', return_value=SimpleNamespace(
                    returncode=2, stdout='', stderr='Network is unreachable')):
                self.assertEqual(run_thor.route_edge_ip(host)['status'], 'PRE_EXECUTION_ROUTE_FAILURE')
            with mock.patch.object(run_thor.subprocess, 'run', return_value=SimpleNamespace(
                    returncode=0, stdout=f'{host} dev wlP1p1s0 lladdr 20:bd:1d:c8:a0:50 DELAY\n', stderr='')) as command:
                neighbor = run_thor.neighbor_edge_ip(host)
                self.assertEqual(neighbor['state'], 'DELAY')
                self.assertEqual(neighbor['lladdr'], '20:bd:1d:c8:a0:50')
                self.assertEqual(command.call_args.args[0], ['ip', 'neigh', 'show', host])
            tcp.assert_not_called()

    def test_current_attempt_cpu_pin_readback_only(self):
        with tempfile.TemporaryDirectory() as temporary:
            out = Path(temporary)
            net = {'status': 'PASS', 'monotonic_ns': 100, 'packets_received': 2,
                   'plan_sha256': config.sha(config.PLAN)}
            pin = {'status': 'PASS', 'mode': 'pinned', 'plan_sha256': config.sha(config.PLAN),
                   'network_check_monotonic_ns': 100, 'snapshot': {'monotonic_ns': 200}}
            (out / 'CPU_PIN_READBACK.json').write_text(json.dumps(pin))
            with mock.patch.object(run_thor, 'OUT', out), \
                    mock.patch.object(run_thor, 'require_network_check', return_value=net):
                self.assertEqual(run_thor.require_current_pin_evidence(), pin)
                pin['snapshot']['monotonic_ns'] = 50
                (out / 'CPU_PIN_READBACK.json').write_text(json.dumps(pin))
                with self.assertRaisesRegex(RuntimeError, 'Stale/wrong CPU pin evidence'):
                    run_thor.require_current_pin_evidence()

    def test_listener_evidence_is_required_and_stage_specific(self):
        with tempfile.TemporaryDirectory() as temporary:
            out = Path(temporary)
            stdout = out / 'edge_stdout.txt'
            ss = out / 'edge_ss.txt'
            stdout.write_text('LISTENING 5000: 8 BASE sessions\n')
            ss.write_text('LISTEN 0 1 0.0.0.0:5000 0.0.0.0:* users:("python",pid=1)\n')
            pin = {'snapshot': {'monotonic_ns': 0}}
            with mock.patch.object(run_thor, 'OUT', out), \
                    mock.patch.object(run_thor, 'require_current_pin_evidence', return_value=pin), \
                    mock.patch.object(run_thor, 'require_pin'):
                with self.assertRaisesRegex(RuntimeError, 'LISTENING and Edge-local ss evidence required'):
                    run_thor.require_listener_evidence('BASE', pin)
                record = run_thor.record_listener_evidence('BASE', stdout, ss)
                self.assertEqual(record['status'], 'PASS')
                self.assertEqual(run_thor.require_listener_evidence('BASE', pin)['expected_sessions'], 8)
                with self.assertRaises(FileExistsError):
                    run_thor.record_listener_evidence('BASE', stdout, ss)

    def test_final02_second_base_invocation_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            out = Path(temporary)
            (out / 'campaign_attempt.json').write_text('{}')
            with mock.patch.object(run_thor, 'OUT', out), \
                    mock.patch.object(run_thor.prior.old.edge_runtime, 'load_cache', return_value=([b'x'], None)), \
                    mock.patch.object(run_thor, 'require_current_pin_evidence', return_value={'snapshot': {'monotonic_ns': 1}}), \
                    mock.patch.object(run_thor, 'require_listener_evidence', return_value={'monotonic_ns': 2}), \
                    mock.patch.object(run_thor, 'require_pin', return_value={'status': 'PASS'}), \
                    mock.patch.object(run_thor.wifi_v2, 'capture', return_value={'status': 'AVAILABLE', 'connected': True}), \
                    mock.patch.object(run_thor, 'net_counters', return_value={'carrier_changes': 1,
                        'carrier_down_count': 0, 'carrier_up_count': 1}):
                with self.assertRaisesRegex(RuntimeError, 'Existing base attempt'):
                    run_thor.stage_run('BASE', config.sha(config.PLAN))
                self.assertFalse((out / 'base').exists())

    def test_scientific_conditions_equal_final01(self):
        old = json.loads((config.ROOT / 'results/timely_capacity_campaign/v2_2/edge_preflight_final01/plan.json').read_text())
        def normalized(rows):
            return [{k: v for k, v in row.items() if k != 'run_id'} for row in rows]
        self.assertEqual(normalized(config.base_order()), normalized(old['base_order']))
        for branch, rows in config.extension_orders().items():
            self.assertEqual(normalized(rows), normalized(old['extension_orders'][branch]))
        for rate in (72, 80, 88):
            for pattern, artifact in (('ALIGNED', 'ALIGNED_EDGE_SCHEDULES.json'),
                                      ('STAGGERED', 'STAGGERED_EDGE_SCHEDULES.json')):
                old_schedule = json.loads((config.ROOT / 'results/timely_capacity_campaign/v2_2/edge_preflight_final01' / artifact).read_text())
                self.assertEqual(json.loads(json.dumps(config.schedule(rate, pattern))),
                                 old_schedule[str(rate)])

    def test_endpoint_revision_and_fresh_bundle(self):
        plan = config.load_plan()
        manifest = json.loads((config.OUT / 'EDGE_ENDPOINT_MANIFEST.json').read_text())
        diff = json.loads((config.OUT / 'scientific_condition_diff_endpoint.json').read_text())
        failure = json.loads((config.OUT / 'NETWORK_REACHABILITY_FAILURE_18576305639059.json').read_text())
        self.assertEqual(plan['edge_ip'], plan['edge_host'])
        self.assertEqual(plan['edge_ip'], manifest['edge_ip'])
        self.assertNotEqual(plan['edge_ip'], failure['command'][-1])
        self.assertEqual(diff['status'], 'SCIENTIFIC_CONDITIONS_UNCHANGED_EXCEPT_ENDPOINT')
        self.assertTrue(diff['other_fields_exact_equal'])
        self.assertEqual(config.sha(config.PLAN), config.sha(config.OUT / 'edge_bundle/plan.json'))
        for name, digest in json.loads((config.OUT / 'BUNDLE_SHA256.json').read_text()).items():
            self.assertEqual(config.sha(config.OUT / 'edge_bundle' / name), digest)
        for name in ('config.py', 'run_thor.py', 'prepare.py', 'edge_server_final02.py'):
            self.assertNotIn(failure['command'][-1], (config.HERE / name).read_text())


if __name__ == '__main__':
    unittest.main(verbosity=2)
