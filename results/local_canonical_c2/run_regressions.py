import sys,unittest,json
from pathlib import Path
from unittest.mock import patch
D=Path(__file__).resolve().parent;R=D.parents[1]
sys.path[:0]=[str(D/'code'),str(R/'scripts')]
import run_local_latency_breakdown_formal as old
original=old.check_empty_formal_root
# Existing fixture patches OUTPUT but its default argument captures the real populated root.
# Test-only rebinding preserves the intended temporary-root isolation; no source file edits.
with patch.object(old,'check_empty_formal_root',side_effect=lambda root=None:original(old.OUTPUT if root is None else root)):
    suite=unittest.defaultTestLoader.discover(str(R/'scripts'),pattern='test_local_*.py')
    result=unittest.TextTestRunner(verbosity=2).run(suite)
loader=unittest.TestLoader()
new=unittest.TextTestRunner(verbosity=2).run(loader.discover(str(D/'code'),pattern='test_*.py'))
sys.path.insert(0,str(R/'results/local_inference_concurrency/eos_termination_fix'))
previous=unittest.TextTestRunner(verbosity=2).run(unittest.TestLoader().discover(str(R/'results/local_inference_concurrency/eos_termination_fix'),pattern='test_termination_contract.py'))
out={'validation':'PASS' if all(v.wasSuccessful() for v in (result,new,previous)) else 'FAIL',
     'existing_local_tests':result.testsRun,'new_termination_tests':new.testsRun,'previous_EOS_tests':previous.testsRun,
     'failures':sum(len(v.failures)+len(v.errors) for v in (result,new,previous)),
     'test_only_fixture_default_rebound':True}
(D/'regression_result.json').write_text(json.dumps(out,indent=2));print(json.dumps(out))
sys.exit(0 if out['validation']=='PASS' else 1)
