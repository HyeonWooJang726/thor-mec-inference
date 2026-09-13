"""Recovery-only orchestration; executes original frozen runtime without modification."""
from pathlib import Path
import sys,os,json,fcntl,signal,subprocess,traceback,time
RECOVERY=Path(__file__).resolve().parents[1];ORIGINAL=RECOVERY.parent
sys.path.append(str(ORIGINAL/'_code'))
from core import save,atomic,utc,REPO
from environment import sha,verify,snapshot
from recovery_analysis import run as analyze
from bookkeeping import checkpoint,success,failure,complete
STOP=None
def stopped(sig,frame):
 global STOP
 STOP=f'signal {sig}'
def log(kind,**data):
 text=json.dumps(dict(time=utc(),kind=kind,**data))
 with (RECOVERY/'progress.log').open('a') as f:f.write(text+'\n');f.flush();os.fsync(f.fileno())
 print(text,flush=True)
def guard():
 verify()
 for p,h in json.loads((RECOVERY/'recovery_freeze.json').read_text())['hashes'].items():
  if sha(p)!=h:raise RuntimeError('recovery frozen hash mismatch: '+p)
 if json.loads((ORIGINAL/'campaign_status.json').read_text())['campaign_status']!='HALTED':raise RuntimeError('historical status altered')
 if json.loads((RECOVERY/'smoke_reuse_decision.json').read_text())['reuse_decision']!='VALIDATED_REUSE':raise RuntimeError('first smoke not reusable')
 state=json.loads((RECOVERY/'continuation_status.json').read_text());manifest=json.loads((RECOVERY/'continuation_manifest.json').read_text())
 if len(state['rows'])!=31:raise RuntimeError('wrong continuation length')
 for a,b in zip(state['rows'],manifest['remaining_acquisitions']):
  if any(a.get(k)!=v for k,v in b.items()):raise RuntimeError('execution order/row mismatch')
def execute():
 # Do not truncate or rewrite the old lock. Hold both locks for the whole continuation.
 with (ORIGINAL/'campaign.lock').open('r') as original_lock,(RECOVERY/'continuation.lock').open('a+') as lock:
  fcntl.flock(original_lock,fcntl.LOCK_EX|fcntl.LOCK_NB);fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
  state=json.loads((RECOVERY/'continuation_status.json').read_text())
  if state['campaign_status'] in ('HALTED','COMPLETED'):raise RuntimeError('terminal continuation; no rerun')
  lock.seek(0);lock.truncate();lock.write(json.dumps(dict(pid=os.getpid(),start=utc())));lock.flush()
  state.update(runner_pid=os.getpid(),campaign_status='RUNNING');state.setdefault('start_time',utc());checkpoint(RECOVERY,state)
  row=None
  try:
   for row in state['rows']:
    if row['status']=='RUNNING':row['status']='ABORTED';raise RuntimeError('interrupted acquisition; no retry')
    if row['status'] in ('FAIL','ABORTED'):raise RuntimeError('failed/unknown acquisition; no retry')
    if row['status']=='PASS':continue
    guard();before=snapshot()
    if STOP:raise RuntimeError(STOP)
    if row['stage']=='primary' and row['index']==1:
     if state['rows'][0]['status']!='PASS':raise RuntimeError('lookup smoke did not PASS')
     save(RECOVERY/'pre_primary_freeze_audit.json',dict(time=utc(),measurement_and_postprocessing_hashes='MATCH',environment=before,FIXED_C4='VALIDATED_REUSE',K_LOOKUP='LIVE_END_TO_END_PASS'))
    out=ORIGINAL/row['acquisition_id']
    if out.exists():raise RuntimeError('output collision: '+str(out))
    out.mkdir();save(out/'environment_before.json',before)
    argv=['/usr/bin/python3','-B',str(ORIGINAL/'_code/runtime.py'),'--acquisition-id',row['acquisition_id']]
    save(out/'command.json',dict(argv=argv,cwd=str(REPO),row=dict(row),recovery=str(RECOVERY)))
    row.update(status='RUNNING',started_at=utc(),start_monotonic_ns=time.perf_counter_ns());checkpoint(RECOVERY,state);log('START',acquisition=row['acquisition_id'],stage=row['stage'])
    code=None;child=None;timed_out=False
    with (out/'stdout.log').open('x') as stdout,(out/'stderr.log').open('x') as stderr:
     try:
      child=subprocess.Popen(argv,cwd=REPO,stdin=subprocess.DEVNULL,stdout=stdout,stderr=stderr,start_new_session=True)
      row['child_pid']=child.pid;checkpoint(RECOVERY,state)
      while child.poll() is None:
       if STOP or (time.perf_counter_ns()-row['start_monotonic_ns'])/1e9>420:
        timed_out=not bool(STOP);os.killpg(child.pid,signal.SIGTERM)
        try:child.wait(timeout=10)
        except subprocess.TimeoutExpired:os.killpg(child.pid,signal.SIGKILL);child.wait()
        break
       time.sleep(.5)
      code=child.wait()
     finally:
      if child and child.poll() is None:
       os.killpg(child.pid,signal.SIGTERM)
       try:child.wait(timeout=10)
       except subprocess.TimeoutExpired:os.killpg(child.pid,signal.SIGKILL);child.wait()
      if child:code=child.returncode
      save(out/'exit.json',dict(exit_code=code,actual_child_pid=child.pid if child else None,parent_pid=os.getpid(),started_at=row['started_at'],finished_at=utc(),start_monotonic_ns=row['start_monotonic_ns'],end_monotonic_ns=time.perf_counter_ns(),timeout=timed_out,interruption=STOP))
    if code!=0 or timed_out or STOP:raise RuntimeError(f'actual child exit={code}; timeout={timed_out}; signal={STOP}')
    guard();after=snapshot();save(out/'environment_after.json',after)
    metrics=analyze(row);success(RECOVERY,state,row,metrics)
    log('PASS',acquisition=row['acquisition_id'],frames=metrics['completed_frames'],DMR=metrics['DMR_percent'])
   complete(RECOVERY,state)
  except BaseException as error:
   failure(RECOVERY,state,row,error);log('HALTED',reason=state['halt_reason'])
   save(RECOVERY/'continuation_traceback.json',dict(traceback=traceback.format_exc()))
  try:
   from recovery_report import aggregate
   aggregate(RECOVERY,ORIGINAL)
  except Exception:
   save(RECOVERY/'post_analysis_failure.json',dict(error=traceback.format_exc()));log('POST_ANALYSIS_ERROR')
if __name__=='__main__':
 signal.signal(signal.SIGTERM,stopped);signal.signal(signal.SIGINT,stopped);execute()
