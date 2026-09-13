"""Exclusive persistent continuation launch. No GPU retry or historical state writes."""
from continuation import *
if __name__=='__main__':
 state=json.loads((RECOVERY/'continuation_status.json').read_text())
 if state['campaign_status']!='READY' or not all(r['status']=='UNATTEMPTED' for r in state['rows']):raise RuntimeError('not pristine READY continuation; audit instead')
 guard();env=snapshot()
 if any((ORIGINAL/r['acquisition_id']).exists() for r in state['rows']):raise RuntimeError('existing acquisition; audit instead')
 with (ORIGINAL/'campaign.lock').open('r') as oldlock:
  fcntl.flock(oldlock,fcntl.LOCK_EX|fcntl.LOCK_NB)
  save(RECOVERY/'persistent_launch.json',dict(status='RESERVED',time=utc()))
 save(RECOVERY/'launch_environment.json',env)
 argv=['/usr/bin/python3','-B',str(RECOVERY/'_code/continuation.py')]
 with (RECOVERY/'runner_stdout.log').open('x') as stdout,(RECOVERY/'runner_stderr.log').open('x') as stderr:
  child=subprocess.Popen(argv,cwd=REPO,stdin=subprocess.DEVNULL,stdout=stdout,stderr=stderr,start_new_session=True,close_fds=True)
 atomic(RECOVERY/'persistent_launch.json',dict(status='LAUNCHED',time=utc(),pid=child.pid,argv=argv,cwd=str(REPO),method='setsid via Popen(start_new_session=True), detached stdin, dedicated stdout/stderr',no_reboot_autorestart=True,progress_log=str(RECOVERY/'progress.log'),state=str(RECOVERY/'continuation_status.json')))
 print('Persistent continuation PID',child.pid,flush=True)
