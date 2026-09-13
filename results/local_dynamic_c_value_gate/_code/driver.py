"""Persistent single-owner 2-smoke + 30-primary campaign, fail-stop, no retries."""
import fcntl,signal,subprocess,sys,traceback,hashlib
from core import *
from environment import verify,snapshot
from analyze import run as analyze

STOP=None
def stopped(sig,frame):
 global STOP
 STOP=f'signal {sig}'
def log(kind,**data):
 text=json.dumps(dict(time=utc(),kind=kind,**data))
 with (ROOT/'progress.log').open('a') as f:f.write(text+'\n');f.flush();os.fsync(f.fileno())
 print(text,flush=True)
def checkpoint(state):state['last_update']=utc();atomic(ROOT/'campaign_status.json',state)
def execute():
 with (ROOT/'campaign.lock').open('a+') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
  state=json.loads((ROOT/'campaign_status.json').read_text())
  if state['campaign_status'] in ('COMPLETED','HALTED'):raise RuntimeError('terminal campaign; no automatic rerun')
  lock.seek(0);lock.truncate();lock.write(json.dumps(dict(pid=os.getpid(),start=utc())));lock.flush()
  state['runner_pid']=os.getpid();state['campaign_status']='RUNNING';state.setdefault('start_time',utc());checkpoint(state)
  try:
   for row in state['rows']:
    if row['status']=='RUNNING':row['status']='ABORTED';raise RuntimeError('partial prior RUNNING row: no retry')
    if row['status'] in ('FAIL','ABORTED'):raise RuntimeError('prior failed or unknown acquisition: HALT')
    if row['status']=='PASS':continue
    verify();before=snapshot()
    if STOP:raise RuntimeError(STOP)
    out=ROOT/row['acquisition_id']
    if out.exists():raise RuntimeError('output collision: '+str(out))
    out.mkdir();save(out/'environment_before.json',before)
    argv=['/usr/bin/python3','-B',str(ROOT/'_code/runtime.py'),'--acquisition-id',row['acquisition_id']]
    save(out/'command.json',dict(argv=argv,cwd=str(REPO),row=row))
    row.update(status='RUNNING',started_at=utc(),start_monotonic_ns=time.perf_counter_ns());checkpoint(state);log('START',acquisition=row['acquisition_id'],stage=row['stage'])
    code=None;child=None;timed_out=False
    with (out/'stdout.log').open('x') as stdout,(out/'stderr.log').open('x') as stderr:
     try:
      child=subprocess.Popen(argv,cwd=REPO,stdin=subprocess.DEVNULL,stdout=stdout,stderr=stderr,start_new_session=True)
      row['child_pid']=child.pid;checkpoint(state)
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
    if code!=0 or timed_out or STOP:
     row.update(status='FAIL',reason=f'actual child exit={code}; timeout={timed_out}; signal={STOP}');checkpoint(state)
     raise RuntimeError(row['reason'])
    try:
     verify();after=snapshot();save(out/'environment_after.json',after)
     metrics=analyze(row);row.update(status='PASS',completed_frames=metrics['completed_frames'],finished_at=utc());checkpoint(state)
    except Exception as error:
     row.update(status='FAIL',reason=f'{type(error).__name__}: {error}');checkpoint(state);raise
    log('PASS',acquisition=row['acquisition_id'],frames=row['completed_frames'],DMR=metrics['DMR_percent'])
   state.update(campaign_status='COMPLETED',finish_time=utc());checkpoint(state)
  except BaseException as error:
   state.update(campaign_status='HALTED',halt_reason=f'{type(error).__name__}: {error}',finish_time=utc());checkpoint(state)
   (ROOT/'HALT_REASON.md').write_text('# HALTED\n\n'+state['halt_reason']+'\n\nNo retry or additional GPU run.\n');log('HALTED',reason=state['halt_reason'])
  # All acquisition policies stop on the first failure; analysis cannot launch GPU.
  try:
   from report import aggregate
   aggregate()
  except Exception:
   save(ROOT/'post_analysis_failure.json',dict(error=traceback.format_exc()));log('POST_ANALYSIS_ERROR')
if __name__=='__main__':
 signal.signal(signal.SIGTERM,stopped);signal.signal(signal.SIGINT,stopped);execute()
