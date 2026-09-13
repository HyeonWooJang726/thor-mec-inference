"""CPU-only real-artifact replay and explicitly synthetic regression fixtures."""
from pathlib import Path
import sys,json,copy,shutil,traceback
HERE=Path(__file__).resolve().parents[1];OLD=HERE.parent
sys.path.append(str(OLD/'_code'))
from core import *
from recovery_analysis import run,numbers,metrics
from bookkeeping import success,failure,complete,checkpoint
from recovery_report import aggregate
import test_cpu

def synthetic(row,out):
 """Deterministic CPU trace fixture; no TensorRT/GPU import or execution."""
 out.mkdir();plan=Trace(row['trace'],row['duration_s']);clock=[1000000000]
 def now():clock[0]+=1;return clock[0]
 state=State(plan,row['policy'],now);state.initialize(clock[0]+100)
 for template in plan.jobs:
  clock[0]=max(clock[0],state.t0+template['offset_ns'])
  j=state.generate(template);assert state.arrival[j['stream_id']].get_nowait() is j
  j['b_ns']=now();state.enqueue(j);j=state.admit(0);assert j is not None
  clock[0]+=1000000;j['c_ns']=now();state.publish_completion(j)
 # Final offered time / drain endpoint explicitly included by analyzer.
 term=dict(t0_ns=state.t0,expected=len(plan.jobs),generated=state.generated,enqueued=state.enqueued,started=state.started,completed=state.completed,samples=plan.samples,front_done=[True]*7,pipeline_NULL=[True]*7,joined={str(i):True for i in range(13)},runtime_errors=[],worker_errors=[],watchdog_triggered=False,waiting_after_drain=0,active_counter_after_drain=0,backlog_published_after_drain=0,due_not_generated_after_drain=0,provenance='SYNTHETIC_CPU_FIXTURE_NOT_MEASURED')
 save(out/'termination.json',term);save(out/'exit.json',dict(exit_code=0,provenance='SYNTHETIC_NOT_CHILD_PROCESS'))
 save(out/'runtime_metadata.json',dict(row=row,provenance='SYNTHETIC_CPU_FIXTURE'))
 resources=json.loads((OLD/'smoke_fixed_c4/resources.json').read_text());resources['provenance']='SYNTHETIC_CONFIGURATION_FIXTURE';save(out/'resources.json',resources)
 csvout(out/'per_frame.csv',state.records);csvout(out/'events.csv',state.events)
 return plan

def validate():
 attempts=HERE/'cpu_tests';attempts.mkdir(exist_ok=True)
 i=1
 while (attempts/f'attempt_{i:03d}').exists():i+=1
 base=attempts/f'attempt_{i:03d}';base.mkdir()
 checks={};plan=json.loads((OLD/'frozen_plan.json').read_text())
 try:
  checks.update(test_cpu.test())
  real=base/'smoke_fixed_c4';real.mkdir();row=dict(plan['acquisitions'][0],status='RUNNING')
  result=run(row,input_dir=OLD/'smoke_fixed_c4',output_dir=real)
  assert result['completed_frames']==result['expected_frames']==780
  for f in ['integrity.json','summary.json','window_summary.csv','transition_summary.csv','state_seconds.csv']:assert (real/f).stat().st_size>0
  checks['real_FULL_FIXED_C4_summary_CSV_JSON_validator']='PASS'
  checks['original_exit_0']=json.loads((OLD/'smoke_fixed_c4/exit.json').read_text())['exit_code']==0
  ledger=base/'success_ledger';ledger.mkdir();state=dict(campaign_status='RUNNING',rows=[row]);success(ledger,state,row,result);complete(ledger,state);assert state['campaign_status']=='COMPLETED'
  aggregate(ledger,base);assert json.loads((ledger/'integrity.json').read_text())['verdict']=='INCONCLUSIVE_VALIDITY'
  checks['real_success_bookkeeping_report_input']='PASS'
  for source in ['row','manifest','metadata','termination']:
   from recovery_analysis import canonical_expected
   badrow=copy.deepcopy(plan['acquisitions'][0]);meta=copy.deepcopy(badrow);term={'expected':780};man=copy.deepcopy(plan)
   if source=='row':badrow['expected_frames']=779
   elif source=='manifest':man['acquisitions'][0]['expected_frames']=779
   elif source=='metadata':meta['expected_frames']=779
   else:term['expected']=779
   try:canonical_expected(badrow,Trace('A',4),term,meta,man)
   except ValueError:pass
   else:raise AssertionError('expected_frames mismatch accepted '+source)
   checks['expected_frames_mismatch_'+source]='PASS'
  # Failure validator path with real artifact read and an explicit synthetic exit fixture.
  bad=base/'failed_fixture';bad.mkdir()
  for p in (OLD/'smoke_fixed_c4').iterdir():
   if p.is_file() and p.name!='exit.json':(bad/p.name).symlink_to(p)
  save(bad/'exit.json',dict(exit_code=-11,provenance='CPU_FAILURE_FIXTURE_NOT_ACTUAL_EXIT'))
  failed_out=base/'failed_derived';failed_out.mkdir();badrow=dict(plan['acquisitions'][0],status='RUNNING');badstate=dict(campaign_status='RUNNING',rows=[badrow]);failledger=base/'failure_ledger';failledger.mkdir()
  try:run(badrow,input_dir=bad,output_dir=failed_out)
  except AssertionError as error:failure(failledger,badstate,badrow,error)
  else:raise AssertionError('invalid fixture accepted')
  assert badrow['status']=='FAIL' and badstate['campaign_status']=='HALTED'
  aggregate(failledger,base);assert json.loads((failed_out/'integrity.json').read_text())['validation']=='FAIL'
  checks['validator_failure_campaign_FAILURE_HALT_report']='PASS'
  fixture=base/'synthetic';fixture.mkdir();summaries={}
  for duration in [4,60]:
   for tr in ['A','B']:
    for policy in POLICIES:
     r=dict(acquisition_id=f'cpu_{duration}_{tr}_{policy}',trace=tr,policy=policy,duration_s=duration,expected_frames=780 if duration==4 else 11700,stage='primary' if duration==60 else 'smoke',round=1,index=1,position=1)
     dest=fixture/r['acquisition_id'];p=synthetic(r,dest);sm=run(dict(r,status='RUNNING'),input_dir=dest,manifest={'acquisitions':[r]})
     win=numbers(dest/'window_summary.csv');assert len(win)==(6 if duration==4 else 10)
     assert sum(w['n'] for w in win if w['window'] in ('startup','transition','phase_remainder'))==len(p.jobs)
     assert len(numbers(dest/'transition_summary.csv'))==12
     checks['full_fixture_'+r['acquisition_id']]='PASS';summaries[(duration,tr,policy)]=dest
  # Full 30-row aggregation/report/figure route, explicitly synthetic, never primary measurements.
  full=base/'synthetic_full_report';full.mkdir();rows=[]
  for r in plan['acquisitions'][2:]:
   d=full/r['acquisition_id'];d.mkdir();template=summaries[(60,r['trace'],r['policy'])]
   for f in ['summary.json','window_summary.csv','transition_summary.csv','state_seconds.csv']:
    if f.endswith('.json'):
     z=json.loads((template/f).read_text());z.update(r);save(d/f,z)
    else:
     z=numbers(template/f)
     for x in z:x.update({k:r[k] for k in ('acquisition_id','round','trace','policy')})
     csvout(d/f,z)
   rows.append(dict(r,status='PASS',completed_frames=11700))
  save(full/'continuation_status.json',dict(campaign_status='COMPLETED',rows=rows,provenance='SYNTHETIC_CPU_REGRESSION_NOT_MEASURED'))
  aggregate(full,full);assert json.loads((full/'integrity.json').read_text())['primary_valid_frames']==351000
  checks['all_policy_complete_30_row_report_figures']='PASS'
  result=dict(validation='PASS',checks=checks,GPU_acquisitions=0,real_replay=str(real),synthetic_fixture_directory=str(base),synthetic_excluded_from_research=True)
  save(HERE/'cpu_replay_validation.json',result)
 except BaseException:
  save(base/'CPU_FAILURE.json',dict(traceback=traceback.format_exc(),checks=checks,GPU_acquisitions=0));raise
 print(json.dumps(result,indent=2))
if __name__=='__main__':validate()
