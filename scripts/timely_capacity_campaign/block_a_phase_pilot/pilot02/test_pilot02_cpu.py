"""CPU/log-only regression for the Block A post-drain summary fix."""
import copy
import hashlib
import json
import tempfile
import types
import unittest
from pathlib import Path

import block_a_summary as adapter
import pilot02_config as config
import run_pilot02 as runner
from replay_pilot01_s1 import replay


class Pilot02CPU(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.plan = config.load_plan()
        cls.old_plan = json.loads((config.PRIOR / 'plan.json').read_text())
        cls.a_dir = config.PRIOR / 'V22_BLOCKA_D100_A1_P01'
        cls.s_dir = config.PRIOR / 'V22_BLOCKA_D100_S1_P01'
        cls.a = json.loads((cls.a_dir / 'manifest.json').read_text())
        cls.s = json.loads((cls.s_dir / 'manifest.json').read_text())
        cls.a_frames = adapter.read_csv(cls.a_dir / 'per_frame.csv.gz')
        cls.a_power = adapter.read_csv(cls.a_dir / 'power_trace.csv.gz')
        cls.s_frames = adapter.read_csv(cls.s_dir / 'per_frame.csv.gz')
        cls.s_power = adapter.read_csv(cls.s_dir / 'power_trace.csv.gz')

    def test_frozen_workload_semantics_and_worker(self):
        new = self.plan
        old = self.old_plan
        for key in ('placement', 'deadlines_ms', 'source_phase_ns', 'idle_seconds',
                    'mechanism_expectations_verdict_effect', 'frozen_worker_sha256'):
            self.assertEqual(new[key], old[key])
        self.assertEqual(config.PHASES, tuple(old['placement']['phases']))
        self.assertEqual(hashlib.sha256(config.run_source().encode()).hexdigest(), old['frozen_worker_sha256'])
        for left, right in zip(old['order'], new['order']):
            left = dict(left)
            right = dict(right)
            self.assertEqual(left.pop('run_id').replace('_P01', '_P02'), right.pop('run_id'))
            self.assertEqual(left, right)

    def test_aligned_historical_summary_unchanged(self):
        old = adapter.timely_summary.summarize(self.a, self.a_frames, self.a_power)
        new = adapter.summarize_with_plan(self.a, self.a_frames, self.a_power, config.PRIOR / 'plan.json')
        self.assertEqual(new, old)
        self.assertEqual(new['terminal_accounting_status'], 'PASS')

    def test_staggered_offline_summary_and_fidelity(self):
        summary = adapter.summarize_with_plan(self.s, self.s_frames, self.s_power, config.PRIOR / 'plan.json')
        self.assertEqual(summary['terminal_accounting_status'], 'PASS')
        self.assertEqual(summary['terminal_partition']['TOTAL']['assigned'], 12480)
        self.assertEqual(summary['terminal_partition']['TOTAL']['true_unfinished'], 0)
        report = replay()
        self.assertEqual(report['status'], 'PASS')
        self.assertEqual(len(report['per_stream']), 8)
        self.assertEqual(report['schedule_fidelity']['status'], 'PASS')
        self.assertEqual(report['original_stored_summary_integrity'], 'INVALID')

    def test_pilot02_live_plan_binding_for_both_patterns(self):
        for old, frames, power, new_id in (
                (self.a, self.a_frames, self.a_power, 'V22_BLOCKA_D100_A1_P02'),
                (self.s, self.s_frames, self.s_power, 'V22_BLOCKA_D100_S1_P02')):
            m = copy.deepcopy(old)
            m.update(run_id=new_id, plan_sha256=config.sha(config.PLAN),
                     execution_manifest_sha256=config.sha(config.PLAN))
            summary = adapter.summarize(m, frames, power)
            self.assertEqual(summary['terminal_accounting_status'], 'PASS')
            self.assertEqual(summary['terminal_partition']['TOTAL']['assigned'], 12480)

    def test_staggered_clean_exit_synthetic_summary(self):
        # Synthetic manifest only: do not alter the pilot01 S1 exit failure.
        m = copy.deepcopy(self.s)
        m.update(run_id='V22_BLOCKA_D100_S1_P02', plan_sha256=config.sha(config.PLAN),
                 execution_manifest_sha256=config.sha(config.PLAN), errors=[],
                 child_returncode=0, process_exit_code=0, clean_shutdown=True)
        summary = adapter.summarize(m, self.s_frames, self.s_power)
        self.assertEqual(summary['integrity_status'], 'VALID')
        self.assertEqual(summary['terminal_accounting_status'], 'PASS')

    def test_outside_plan_manifest_rejected(self):
        for field, value in (('admission_pattern', 'OTHER'), ('deadline_ms', 50),
                             ('target_service_FPS', 216), ('edge_r', 1),
                             ('run_id', 'V22_BLOCKA_D100_S9_P01'),
                             ('plan_sha256', 'wrong')):
            m = copy.deepcopy(self.s)
            m[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                adapter.summarize_with_plan(m, self.s_frames, self.s_power, config.PRIOR / 'plan.json')

    def test_summary_binding_is_block_a_only(self):
        run, final = runner.Context().bindings()
        for fn in (run, final):
            importer = fn.__globals__['__builtins__']['__import__']
            self.assertIs(importer('b1_summary'), adapter)
            self.assertIs(fn.__globals__['decorate'], config.decorate)
        self.assertIs(runner.frozen_run.binding_import('b1_summary'), adapter.timely_summary)

    def test_second_invocation_rejected_before_gpu_or_marker(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'campaign_attempt.json').write_text('{}')
            fn = runner.Context.campaign
            def unreachable():
                raise AssertionError('GPU precheck should not be called')
            bound = types.FunctionType(fn.__code__, dict(fn.__globals__, OUT=root, require_ready=unreachable),
                                       fn.__name__, fn.__defaults__, fn.__closure__)
            fake = types.SimpleNamespace(check_inputs=lambda: None, PREFLIGHT=root / 'frequency_preflight.json')
            with self.assertRaisesRegex(RuntimeError, 'no retry/resume/overwrite'):
                bound(fake, config.sha(config.PLAN))

    def test_precheck_failure_does_not_consume_attempt(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fn = runner.Context.campaign
            def unavailable():
                raise PermissionError('GPU control unavailable')
            bound = types.FunctionType(fn.__code__, dict(fn.__globals__, OUT=root, require_ready=unavailable),
                                       fn.__name__, fn.__defaults__, fn.__closure__)
            fake = types.SimpleNamespace(check_inputs=lambda: None, PREFLIGHT=root / 'frequency_preflight.json')
            with self.assertRaises(PermissionError):
                bound(fake, config.sha(config.PLAN))
            self.assertFalse((root / 'campaign_attempt.json').exists())

    def test_restore_gate_before_analyzer(self):
        from analyze_pilot02 import require_restore
        with self.assertRaisesRegex(RuntimeError, 'CPU restore PASS required'):
            require_restore(config.OUT)

    def test_pilot02_analyzer_fixed_pairs_and_terminal_identity(self):
        from analyze_pilot02 import PAIR_IDS, paired_comparison, revision
        self.assertEqual(PAIR_IDS, (
            ('V22_BLOCKA_D100_A1_P02', 'V22_BLOCKA_D100_S1_P02'),
            ('V22_BLOCKA_D100_A2_P02', 'V22_BLOCKA_D100_S2_P02')))
        rows = [{'run_id': rid, 'classification': 'VALID', 'TIR_admission': value}
                for rid, value in ((PAIR_IDS[0][0], .96), (PAIR_IDS[0][1], .99),
                                   (PAIR_IDS[1][0], .95), (PAIR_IDS[1][1], .98))]
        pair_rows, verdict = paired_comparison(rows)
        self.assertEqual(verdict, 'TEMPORAL_EFFECT_SUPPORTED_FOR_FORMAL_EXPANSION')
        for pair in pair_rows:
            self.assertAlmostEqual(pair['delta_TIR_S_minus_A'], .03)
        with self.assertRaises(ValueError):
            paired_comparison(rows, ((PAIR_IDS[0][0], PAIR_IDS[1][1]), PAIR_IDS[1]))
        self.assertTrue(revision.integer_accounting(100, 90, 6, 4)['terminal_accounting_PASS'])
        self.assertFalse(revision.integer_accounting(100, 90, 5, 4)['terminal_accounting_PASS'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
