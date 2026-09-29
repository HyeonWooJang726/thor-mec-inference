"""No GPU/network: mask, fidelity, gate and launcher guard fixtures."""
import copy
import csv
import json
import math
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import config
import run_thor
import analyze

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(config.ROOT / 'scripts/edge_raw_capacity_gate'))
sys.path.insert(0, str(config.ROOT / 'results/timely_capacity_campaign/block_b_split/v2/edge_bundle_v2'))
import edge_server_final01 as server


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


if __name__ == '__main__':
    unittest.main(verbosity=2)
