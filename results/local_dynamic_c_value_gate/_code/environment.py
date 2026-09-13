"""Read-only host environment and frozen file guards; no GPU measurement."""
import sys,hashlib,shutil,subprocess,json,os
from core import *
sys.path.insert(0,str(REPO/'scripts/common'))
from script_paths import configure
configure()
from run_local_concurrency_trtexec_probe import environment as original_environment

def sha(p):
 h=hashlib.sha256()
 with Path(p).open('rb') as f:
  for chunk in iter(lambda:f.read(8*1024*1024),b''):h.update(chunk)
 return h.hexdigest()
def snapshot():
 data=original_environment()
 if data['pid1'] not in ('systemd','init'):raise RuntimeError('host process visibility required')
 blockers=[]
 for line in data['processes'].splitlines()[1:]:
  fields=line.split(None,4)
  if len(fields)!=5:continue
  pid,ppid,comm,cpu,args=fields
  if int(pid)==os.getpid():continue
  if comm in ('trtexec','gst-launch-1.0','ffmpeg') or ('python' in comm and any(s in args for s in ('profile_fullsource.py','local_dynamic_c_value_gate/_code/runtime.py','scripts/local/profile_','scripts/concurrency/profile_','profile_edge_realtime.py'))):blockers.append(line)
 if blockers:raise RuntimeError('competing GPU workload: '+str(blockers))
 import tensorrt as trt
 data['TensorRT']=trt.__version__
 if trt.__version__!='10.16.2.10':raise RuntimeError('TensorRT version mismatch '+trt.__version__)
 data['disk_free_bytes']=shutil.disk_usage(ROOT).free
 if data['disk_free_bytes']<5*1024**3:raise RuntimeError('disk safety: <5 GiB free')
 data['competing_experiments']=blockers
 return data

def verify():
 pins=json.loads((ROOT/'frozen_hashes.json').read_text())
 for p,h in pins.items():
  if sha(p)!=h:raise RuntimeError('frozen hash mismatch: '+p)
