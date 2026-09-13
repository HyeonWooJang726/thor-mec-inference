"""One persistent launch, no retry. Host process/metadata guards precede spawn."""
import subprocess,sys,os
from core import *
from environment import snapshot,verify
if __name__=='__main__':
 state=json.loads((ROOT/'campaign_status.json').read_text());assert state['campaign_status']=='READY' and all(r['status']=='UNATTEMPTED' for r in state['rows'])
 verify();env=snapshot()
 save(ROOT/'launch_environment.json',env)
 # O_EXCL reservation: a second launch cannot create this artifact.
 save(ROOT/'persistent_launch.json',dict(status='RESERVED',created_at=utc(),method='Popen(start_new_session=True), detached stdin, dedicated stdout/stderr',no_reboot_autorestart=True))
 argv=['/usr/bin/python3','-B',str(ROOT/'_code/driver.py')]
 with (ROOT/'runner_stdout.log').open('x') as stdout,(ROOT/'runner_stderr.log').open('x') as stderr:
  child=subprocess.Popen(argv,cwd=REPO,stdin=subprocess.DEVNULL,stdout=stdout,stderr=stderr,start_new_session=True,close_fds=True)
 atomic(ROOT/'persistent_launch.json',dict(status='LAUNCHED',created_at=utc(),method='Popen(start_new_session=True)',pid=child.pid,argv=argv,cwd=str(REPO),progress_log=str(ROOT/'progress.log'),state=str(ROOT/'campaign_status.json'),no_reboot_autorestart=True))
 print('Persistent campaign PID',child.pid,flush=True)
