"""Whole-campaign disk replay gate. No plots or pooled performance analysis."""
import sys,json,hashlib,csv
from pathlib import Path
D=Path(__file__).resolve().parent;R=D.parents[1]
sys.path[:0]=[str(D/'code'),str(R/'scripts')]
from screening_metrics import validate_run
from run_local_concurrency_trtexec_probe import digest,ENGINE

def main():
 checks=[];failure=None;raw_hashes={}
 try:
  plan=json.loads((D/'formal_plan.json').read_text());done=json.loads((D/'campaign_completion.json').read_text())
  assert done['valid_runs']==35 and done['frames']==252000
  assert not (D/'campaign_failure.json').exists()
  assert len(plan['runs'])==len({(r['K'],r['rep']) for r in plan['runs']})==35
  pinned=json.loads((D/'source_sha256.json').read_text())
  assert all(digest(R/p)==h for p,h in pinned.items())
  assert digest(R/ENGINE)==plan['engine_sha256']
  previous_finish=0
  for r in plan['runs']:
   runid=f"run{r['rep']:02d}";out=D/f"k{r['K']}"/runid
   exit_data=json.loads((out/'exit.json').read_text())
   assert exit_data['exit_code']==0 and not exit_data['retried']
   assert exit_data['started_utc_ns']>previous_finish
   previous_finish=exit_data['finished_utc_ns']
   assert json.loads((out/'command.json').read_text())['argv']==r['argv']
   metadata=json.loads((out/'metadata.json').read_text())
   assert metadata['engine_sha256']==plan['engine_sha256']
   videos='/home/ainet/datasets/PhysicalAI-SmartSpaces/MTMC_Tracking_2026/test/Warehouse_027/videos/'
   assert metadata['active_stream_to_video_mapping']==[videos+f'W027_Camera_{i:04d}.mp4' for i in range(r['K'])]
   for which in ('before','after'):
    env=json.loads((out/f'environment_{which}.json').read_text())
    assert env['DVFS_unlocked'] and 'MAXN' in env['power_mode'] and env['jetson_clocks'].startswith('OFF')
   summary,check=validate_run(out,2,r['K'],1800,runid)
   assert check['waiting_after_drain']==check['active_after_drain']==0
   assert check['concurrency']['resource_ownership']=='PASS'
   for name in ('raw_ns.json','per_frame.csv','metadata.json','resources.json','validation.json','termination_evidence.json','lifecycle.json','exit.json'):
    p=out/name
    if p.exists():raw_hashes[str(p.relative_to(D))]=digest(p)
   checks.append(check)
  assert len(list(D.glob('k*/run*/raw_ns.json')))==35
  assert sum(x['frames'] for x in checks)==252000
 except Exception as e:failure=f'{type(e).__name__}: {e}'
 report={'validation':'FAIL' if failure else 'PASS','expected_runs':35,'expected_frames':252000,
 'valid_runs':len(checks),'frames':sum(x['frames'] for x in checks),'failure':failure,
 'independent_whole_campaign_disk_replay':True,'analysis_allowed':failure is None,'runs':checks,
 'raw_source_sha256':raw_hashes,'GPU_kernel_overlap_measured':False}
 with (D/'formal_integrity_report.json').open('x') as f:json.dump(report,f,indent=2)
 print(json.dumps({k:v for k,v in report.items() if k not in ('runs','raw_source_sha256')}))
 return 1 if failure else 0
if __name__=='__main__':sys.exit(main())
