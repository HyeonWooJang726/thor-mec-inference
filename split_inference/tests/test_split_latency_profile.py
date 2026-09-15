"""Synthetic CPU-only fixtures; these values are never measurement artifacts."""
from collections import Counter
from copy import deepcopy
import json
import math
from pathlib import Path
import tempfile
import unittest

from split_inference.src.common import split_latency_profile as p
from split_inference.scripts.analyze_efficientnet_v2_s_profile import analyze


def fixture():
    cfg = p.config('pilot', 'synthetic-unit-test')
    client, server, correct = [], [], []
    for planned in p.schedule(cfg):
        point = planned['split_point']
        base = {k: str(v) for k, v in planned.items()}
        base.update(activation_shape=json.dumps(list(p.wire.SHAPES[point])), output_shape='[1, 1000]',
                    payload_bytes=str(4 * math.prod(p.wire.SHAPES[point])) if point < 9 else '0',
                    response_payload_bytes='4000' if point < 9 else '0',
                    request_payload_sha256='a' * 64 if point < 9 else p.NA,
                    response_payload_sha256='b' * 64 if point < 9 else p.NA, success='True', error='')
        wall = 0.0 if point == 0 else 2.0
        c = dict(base, network_used=str(point < 9), device_inference_wall_ms=str(wall),
                 device_inference_cuda_ms=str(wall / 2), remote_roundtrip_ms='7.0' if point < 9 else p.NA,
                 e2e_inference_ms=str(wall + (7 if point < 9 else 1)))
        client.append(c)
        if point < 9:
            server.append(dict(base, edge_inference_wall_ms='3.0', edge_inference_cuda_ms='1.0'))
        if planned['phase'] == 'preflight':
            v = {k: str(v) for k, v in planned.items()}
            v.update(output_shape='[1, 1000]', finite='True', top1='1', reference_top1='1', top1_matches='True',
                     max_abs_error='0.0', mean_abs_error='0.0', max_rel_error='0.0', assert_close_passed='True', error='')
            correct.append(v)
    manifests = []
    for role in ['client', 'server']:
        manifests.append(dict(config=cfg, role=role, provenance='synthetic_unit_test', status='passed',
            shutdown='CLOSE/BYE', identity=dict(p.IDENTITY), connections=1, handshakes=1, model_loads=1,
            retries=0, fallback=False, failed_requests=0, source_sha256={'synthetic_fixture': 'c' * 64},
            correctness_tolerance={'rtol': 1e-4, 'atol': 1e-5},
            phase_counts=p.counts(cfg, network=role == 'server')))
    return client, server, correct, *manifests


class ProfileTests(unittest.TestCase):
    def setUp(self):
        self.args = fixture()

    def merge(self):
        return p.merge_rows(*self.args)

    def test_formal_schedule_expected_counts_and_ids(self):
        cfg = p.config('formal', 'formal-test')
        rows = list(p.schedule(cfg))
        self.assertEqual(len(rows), 30350)
        self.assertEqual([r['request_id'] for r in rows], list(range(1, 30351)))
        self.assertEqual(p.counts(cfg), {'preflight': 30, 'warmup': 320, 'measurement': 30000})
        self.assertEqual(p.counts(cfg, True), {'preflight': 27, 'warmup': 288, 'measurement': 27000})
        counts = Counter(r['split_point'] for r in rows if r['phase'] == 'measurement')
        self.assertEqual(counts, Counter(dict.fromkeys(range(10), 3000)))
        for round_id in range(1, 11):
            self.assertEqual(sum(r['phase'] == 'measurement' and r['round'] == round_id for r in rows), 3000)

    def test_pilot_counts(self):
        self.assertEqual(p.counts(p.config('pilot', 'pilot')), {'preflight': 12, 'warmup': 8, 'measurement': 12})
        self.assertEqual(p.counts(p.config('pilot', 'pilot'), True), {'preflight': 9, 'warmup': 6, 'measurement': 9})
        self.assertEqual(len(self.merge()), 32)

    def test_primary_decomposition_uses_wall_not_cuda(self):
        self.args[1][0]['edge_inference_cuda_ms'] = '6.0'
        row = self.merge()[0]
        self.assertEqual(row['offloading_overhead_ms'], 4.0)
        self.assertEqual(row['edge_inference_ms'], 3.0)
        self.assertEqual(float(row['e2e_inference_ms']), row['device_inference_ms'] + row['edge_inference_ms'] + row['offloading_overhead_ms'])

    def test_p9_na_and_no_server_rows(self):
        for row in self.merge():
            if row['split_point'] == '9':
                for key in ['remote_roundtrip_ms', 'edge_inference_wall_ms', 'edge_inference_cuda_ms', 'edge_inference_ms', 'offloading_overhead_ms']:
                    self.assertEqual(row[key], p.NA)
        self.assertTrue(all(r['split_point'] != '9' for r in self.args[1]))

    def test_negative_overhead_is_failure_without_clamping(self):
        self.args[1][0]['edge_inference_wall_ms'] = '7.000001'
        with self.assertRaisesRegex(ValueError, 'offloading overhead'):
            self.merge()
        self.assertEqual(self.args[1][0]['edge_inference_wall_ms'], '7.000001')

    def test_duplicate_missing_extra_and_out_of_order_requests(self):
        original = deepcopy(self.args)
        for endpoint in [0, 1]:
            for mutation in ['duplicate', 'missing', 'extra', 'reorder']:
                self.args = deepcopy(original)
                rows = self.args[endpoint]
                if mutation == 'duplicate':
                    rows.append(dict(rows[0]))
                elif mutation == 'missing':
                    rows.pop()
                elif mutation == 'extra':
                    rows.append(dict(rows[0], request_id='999'))
                else:
                    rows[0], rows[1] = rows[1], rows[0]
                with self.subTest(endpoint=endpoint, mutation=mutation), self.assertRaises(ValueError):
                    self.merge()

    def test_server_p9_request_rejected(self):
        self.args[1].append(dict(self.args[1][0], request_id='4', split_point='9'))
        with self.assertRaisesRegex(ValueError, 'server request IDs'):
            self.merge()

    def test_split_phase_round_sample_shape_length_and_hash_mismatches(self):
        for key, value in [('split_point', '4'), ('phase', 'measurement'), ('round', '9'), ('sample_id', '1'),
                           ('activation_shape', '[1,1280]'), ('output_shape', '[1000]'),
                           ('payload_bytes', '1'), ('response_payload_bytes', '3999'),
                           ('request_payload_sha256', 'c' * 64), ('response_payload_sha256', 'd' * 64)]:
            self.args = fixture()
            self.args[1][0][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.merge()

    def test_matching_but_invalid_hash_and_shape_are_rejected(self):
        for key, value in [('request_payload_sha256', 'bad'), ('response_payload_sha256', 'NA'),
                           ('activation_shape', '[true,3,384,384]'), ('response_payload_bytes', '1')]:
            self.args = fixture()
            self.args[0][0][key] = self.args[1][0][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.merge()

    def test_nonfinite_negative_and_na_required_durations(self):
        keys = [(0, k) for k in ['device_inference_wall_ms', 'device_inference_cuda_ms', 'remote_roundtrip_ms', 'e2e_inference_ms']]
        keys += [(1, k) for k in ['edge_inference_wall_ms', 'edge_inference_cuda_ms']]
        for endpoint, key in keys:
            for value in ['NaN', 'inf', '-inf', '-0.01', 'NA', '']:
                self.args = fixture()
                self.args[endpoint][1][key] = value
                with self.subTest(endpoint=endpoint, key=key, value=value), self.assertRaises(ValueError):
                    self.merge()

    def test_p9_network_and_zero_filled_remote_rejected(self):
        for key, value in [('network_used', 'True'), ('remote_roundtrip_ms', '0'), ('payload_bytes', '4000'),
                           ('request_payload_sha256', 'a' * 64)]:
            self.args = fixture()
            self.args[0][3][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.merge()

    def test_boundaries_and_p0_zero_are_checked(self):
        for index, key, value in [(1, 'e2e_inference_ms', '100'), (0, 'device_inference_wall_ms', '1'),
                                   (3, 'e2e_inference_ms', '1')]:
            self.args = fixture()
            self.args[0][index][key] = value
            with self.subTest(index=index, key=key), self.assertRaises(ValueError):
                self.merge()

    def test_failed_rows_preflight_or_manifest_fail_closed(self):
        for endpoint, key, value in [(0, 'success', 'False'), (1, 'error', 'failure'),
                                     (2, 'assert_close_passed', 'False'), (2, 'finite', 'False'),
                                     (2, 'reference_top1', '2')]:
            self.args = fixture()
            self.args[endpoint][0][key] = value
            with self.subTest(endpoint=endpoint, key=key), self.assertRaises(ValueError):
                self.merge()
        for key, value in [('status', 'failed'), ('shutdown', 'EOF'), ('connections', 2), ('model_loads', 2),
                           ('retries', 1), ('fallback', True), ('failed_requests', 1), ('phase_counts', {})]:
            self.args = fixture()
            self.args[4][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.merge()

    def test_run_source_and_all_identity_hashes(self):
        for key in p.IDENTITY:
            self.args = fixture()
            self.args[4]['identity'][key] = 'f' * 64
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, 'hash mismatch'):
                self.merge()
        self.args = fixture()
        self.args[4]['source_sha256'] = {'different': 'f' * 64}
        with self.assertRaisesRegex(ValueError, 'source hash'):
            self.merge()
        self.args = fixture()
        self.args[4]['config'] = p.config('pilot', 'different-run')
        with self.assertRaisesRegex(ValueError, 'run/config'):
            self.merge()

    def test_summary_excludes_preflight_warmup_and_records_round_and_pooled(self):
        merged = self.merge()
        for row in merged:
            if row['phase'] != 'measurement':
                row['e2e_inference_ms'] = '99999'
        summary = p.summarize(merged, self.args[3]['config'], 'synthetic_unit_test')
        self.assertEqual(len(summary), 4 * 2 * len(p.METRICS))
        for row in summary:
            self.assertIn(row['count'], [0, 3])
            self.assertEqual(row['provenance'], 'synthetic_unit_test')
            if row['count']:
                self.assertLess(row['max'], 99999)
            else:
                self.assertEqual(row['p99'], 'NA')

    def test_quantile_interpolation_and_sample_standard_deviation(self):
        self.assertAlmostEqual(p.percentile([3, 1, 2], .95), 2.9)
        self.assertAlmostEqual(p.percentile([3, 1, 2], .99), 2.98)
        merged = self.merge()
        rows = [r for r in merged if r['phase'] == 'measurement' and r['split_point'] == '0']
        for row, value in zip(rows, [1, 2, 3]):
            row['e2e_inference_ms'] = value
        summary = p.summarize(merged, self.args[3]['config'], 'synthetic_unit_test')
        row = next(r for r in summary if r['split_point'] == 0 and r['metric'] == 'e2e_inference_ms' and r['aggregation'] == 'pooled')
        self.assertEqual(row['count'], 3)
        self.assertEqual(row['mean'], 2)
        self.assertEqual(row['sample_standard_deviation'], 1)

    def test_existing_output_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp)
            sentinel = out / 'keep.txt'
            sentinel.write_text('preserve')
            with self.assertRaises(FileExistsError):
                analyze(out / 'client', out / 'server', out)
            self.assertEqual(sentinel.read_text(), 'preserve')

    def test_malformed_csv_schema_and_rows(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'synthetic.csv'
            for content in ['request_id,request_id\n1,1\n', 'request_id,phase\n1\n', 'request_id,phase\n1,measurement,extra\n']:
                path.write_text(content)
                with self.subTest(content=content), self.assertRaises(ValueError):
                    p.read_csv(path, ['request_id', 'phase'])


if __name__ == '__main__':
    unittest.main()
