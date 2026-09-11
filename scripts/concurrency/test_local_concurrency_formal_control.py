"""CPU-only orchestration gates; never starts inference."""

# Resolve shared experiment modules for direct script and repository-root imports.
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parents[1] / "common"))
from script_paths import configure as _configure, script_path
_configure()

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import run_local_concurrency_formal_control as runner


class OrchestrationTests(unittest.TestCase):
    def test_exact_matrix_order_and_frames(self):
        expected = ['15 25 16 26 17 27', '26 16 27 17 25 15',
                    '17 27 15 25 16 26', '25 15 26 16 27 17', '16 26 17 27 15 25']
        self.assertEqual([' '.join(f'{c}{k}' for c,k in group) for group in runner.ORDER], expected)
        runs = runner.plan()['runs']
        self.assertEqual(len({(r['C'],r['K'],r['round']) for r in runs}),30)
        self.assertEqual(sum(r['K']*1800 for r in runs),324000)

    def test_C_only_resource_parameter_same_profile(self):
        first = runner.command(1,6,1)[0]
        second = runner.command(2,6,1)[0]
        differences = [i for i,(a,b) in enumerate(zip(first,second)) if a!=b]
        self.assertEqual(differences, [first.index('--concurrency')+1, first.index('--output-dir')+1])

    def test_failed_smoke_forbids_formal(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);(p/'smoke').mkdir()
            (p/'smoke/validation_report.json').write_text(json.dumps({'validation':'FAIL'}))
            with patch.object(runner,'PREP',p), patch.object(runner,'ROOT',p/'formal'), patch.object(runner,'one_run') as child:
                with self.assertRaisesRegex(RuntimeError,'smoke PASS'):
                    runner.execute()
                child.assert_not_called()
                self.assertFalse((p/'formal').exists())

    def test_changed_source_forbids_formal(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);(p/'smoke').mkdir()
            (p/'smoke/validation_report.json').write_text(json.dumps({'validation':'PASS','source_sha256':{'source':'old'}}))
            with patch.object(runner,'PREP',p), patch.object(runner,'ROOT',p/'formal'), patch.object(runner,'hashes',return_value={'source':'new'}), patch.object(runner,'one_run') as child:
                with self.assertRaisesRegex(RuntimeError,'identical source'):
                    runner.execute()
                child.assert_not_called()

    def test_smoke_failure_preserved_and_stops(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)
            with patch.object(runner,'PREP',p), patch.object(runner,'hashes',return_value={}), patch.object(runner,'one_run',side_effect=RuntimeError('injected child failure')) as child:
                with self.assertRaisesRegex(RuntimeError,'injected'):
                    runner.smoke()
                self.assertEqual(child.call_count,1)
                self.assertEqual(json.loads((p/'smoke/validation_report.json').read_text())['validation'],'FAIL')


if __name__ == '__main__':
    unittest.main()
