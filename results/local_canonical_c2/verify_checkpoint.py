"""CPU-only checkpoint verification. Never runs a GPU workload or rewrites measurements."""
import argparse,ast,csv,hashlib,importlib,json,sys,unittest
from pathlib import Path
from unittest.mock import patch
D=Path(__file__).resolve().parent;R=D.parents[1]
sys.path[:0]=[str(D/'code'),str(D/'analysis'),str(R/'scripts')]

def main():
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
 import run_local_latency_breakdown_formal as old
 original=old.check_empty_formal_root
 with patch.object(old,'check_empty_formal_root',side_effect=lambda root=None:original(old.OUTPUT if root is None else root)):
  existing=unittest.TextTestRunner(verbosity=1).run(unittest.TestLoader().discover(str(R/'scripts'),pattern='test_local_*.py'))
 current=unittest.TextTestRunner(verbosity=1).run(unittest.TestLoader().discover(str(D/'code'),pattern='test_*.py'))
 events=unittest.TextTestRunner(verbosity=1).run(unittest.TestLoader().discover(str(D/'analysis'),pattern='test_event_analysis.py'))
 sys.path.insert(0,str(R/'results/local_inference_concurrency/eos_termination_fix'))
 historical=unittest.TextTestRunner(verbosity=1).run(unittest.TestLoader().discover(str(R/'results/local_inference_concurrency/eos_termination_fix'),pattern='test_termination_contract.py'))
 tests=[existing,current,events,historical];assert all(r.wasSuccessful() for r in tests)
 modules=['analyze_local_concurrency_formal_control','local_concurrency_control_metrics','local_concurrency_tensorrt','local_concurrency_validation','profile_local_concurrency_control','run_local_concurrency_control','run_local_concurrency_formal_control','run_local_concurrency_trtexec_probe','profile_fullsource','screening_tensorrt','screening_validation','screening_metrics','termination_contract','run_fullsource','analyze','event_analysis','temporal','plot_figures']
 for name in modules:importlib.import_module(name)
 paths=list((D/'code').glob('*.py'))+list((D/'analysis').glob('*.py'))+[R/'scripts'/f'{name}.py' for name in modules if (R/'scripts'/f'{name}.py').exists()]+[D/'verify_checkpoint.py',D/'verify_formal.py',D/'run_regressions.py']
 for p in paths:compile(p.read_text(),str(p),'exec')
 g=json.loads((D/'formal_integrity_report.json').read_text());assert (g['validation'],g['valid_runs'],g['frames'])==('PASS',35,252000)
 for path,sha in g['raw_source_sha256'].items():assert hashlib.sha256((D/path).read_bytes()).hexdigest()==sha,path
 from screening_metrics import validate_run
 rows=list(csv.DictReader((D/'per_run_summary.csv').open()));assert len(rows)==35 and sum(int(r['frames']) for r in rows)==252000
 for row in rows:
  k=int(row['K']);run=row['run_id'];summary,integrity=validate_run(D/f'k{k}'/run,2,k,1800,run)
  for key,val in summary.items():assert str(val)==row[key],(k,run,key)
 pins=json.loads((D/'analysis/plot_inputs_sha256.json').read_text())
 for path,sha in pins.items():assert hashlib.sha256((D/path).read_bytes()).hexdigest()==sha,path
 report={'validation':'PASS','unit_tests':sum(r.testsRun for r in tests),'test_failures':0,'syntax_files':len(paths),'import_modules':modules,'formal_runs_replayed':35,'frames_replayed':252000,'summary_raw_consistency':'PASS','GPU_workload_executed':False,'raw_data_rewritten':False}
 with args.output.open('x') as f:json.dump(report,f,indent=2)
 print(json.dumps(report))
if __name__=='__main__':main()
