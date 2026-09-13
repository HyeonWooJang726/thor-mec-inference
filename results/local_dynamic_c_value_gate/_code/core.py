"""CPU-only trace, current-K controller, and serialized application admission."""
import bisect, collections, csv, json, os, queue, threading, time
from pathlib import Path
from datetime import datetime, timezone
ROOT=Path(__file__).resolve().parents[1]
REPO=ROOT.parents[1]
FORMAL=REPO/'results/local_concurrency_formal_full'
POLICIES=('FIXED_C2','FIXED_C4','K_LOOKUP_C2_C4')
def utc():return datetime.now(timezone.utc).isoformat()
def save(path,data):
 with Path(path).open('x') as f:json.dump(data,f,indent=2,allow_nan=False);f.write('\n')
def atomic(path,data):
 p=Path(path);temp=p.with_name(p.name+'.tmp')
 with temp.open('w') as f:json.dump(data,f,indent=2,allow_nan=False);f.flush();os.fsync(f.fileno())
 os.replace(temp,p)
def csvout(path,rows,fields=None):
 fields=fields or list(dict.fromkeys(k for r in rows for k in r))
 with Path(path).open('x',newline='') as f:
  w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)
def loadcsv(path):
 with Path(path).open() as f:return list(csv.DictReader(f))
def miss(latency_ns):return latency_ns*30>1000000000
class Trace:
 def __init__(self,trace,duration):
  assert trace in ('A','B') and duration in (4,60)
  self.duration=duration;self.phase_ticks=duration*30//4;self.ks=[6,7,6,7] if trace=='A' else [7,6,7,6]
  self.offsets=[];self.jobs=[];samples=[0]*7
  for tick in range(duration*30):
   phase=tick//self.phase_ticks;k=self.ks[phase];offset=tick*1000000000//30
   for stream in range(k):
    self.jobs.append(dict(request_id=len(self.jobs),stream_id=stream,global_tick=tick,source_sample_index=samples[stream],arrival_K=k,arrival_phase=phase,offset_ns=offset))
    self.offsets.append(offset);samples[stream]+=1
  self.samples=samples
  self.boundaries=[(i*duration*1000000000//4,self.ks[i],i) for i in range(1,4)]
 def due_count(self,now,t0):return bisect.bisect_right(self.offsets,now-t0)
class Controller:
 """Receives only current observed K, never Trace or next-boundary information."""
 def __init__(self,policy):assert policy in POLICIES;self.policy=policy
 def notify(self,current_k):
  assert current_k in (6,7)
  return 2 if self.policy=='FIXED_C2' else 4 if self.policy=='FIXED_C4' else (2 if current_k==6 else 4)
class State:
 def __init__(self,plan,policy,clock=time.perf_counter_ns):
  self.plan=plan;self.controller=Controller(policy);self.clock=clock
  self.cv=threading.Condition(threading.RLock());self.ready=queue.Queue();self.arrival=[queue.Queue() for _ in range(7)]
  self.events=[];self.records=[];self.active=0;self.generated=0;self.completed=0;self.enqueued=0;self.started=0
  self.cap=None;self.k=None;self.cap_event_id=None;self.boundary_cursor=0;self.t0=None;self.stop=False;self.errors=[]
 def event(self,kind,ns=None,**extra):
  event=dict(seq=len(self.events),kind=kind,ns=self.clock() if ns is None else ns,C=self.cap,K=self.k,
             active_counter=self.active,ready_waiting=self.enqueued-self.started,
             generated=self.generated,completed_published=self.completed,backlog_published=self.generated-self.completed,
             due_not_generated=max(0,self.plan.due_count(self.clock(),self.t0)-self.generated) if self.t0 else 0,**extra)
  self.events.append(event);return event
 def initialize(self,t0):
  with self.cv:
   self.t0=t0;self.k=self.plan.ks[0];self.cap=self.controller.notify(self.k)
   e=self.event('cap_apply',logical_boundary_ns=t0,phase=0,old_C=0,new_C=self.cap,notification_ns=self.clock(),initial=True)
   self.cap_event_id=e['seq']
 def apply_due(self):
  # Caller holds cv. The generator owns schedule; controller only sees current K.
  now=self.clock();due=[]
  while self.boundary_cursor<3:
   offset,k,phase=self.plan.boundaries[self.boundary_cursor]
   if now<self.t0+offset:break
   due.append((self.t0+offset,k,phase));self.boundary_cursor+=1
  for index,(logical,k,phase) in enumerate(due):
   old=self.cap;self.k=k
   notice=self.event('workload_notification',logical_boundary_ns=logical,phase=phase)
   new=self.controller.notify(k)
   if index<len(due)-1:
    self.event('superseded_cap_decision',logical_boundary_ns=logical,phase=phase,old_C=old,new_C=new,notification_ns=notice['ns'])
   else:
    self.cap=new
    e=self.event('cap_apply',logical_boundary_ns=logical,phase=phase,old_C=old,new_C=new,notification_ns=notice['ns'],initial=False)
    self.cap_event_id=e['seq']
  if due:self.cv.notify_all()
 def generate(self,template):
  with self.cv:
   self.apply_due()
   j=dict(template,a_ns=self.t0+template['offset_ns'],actual_generation_ns=self.clock())
   self.arrival[j['stream_id']].put(j);self.generated+=1
   self.event('generation',request_id=j['request_id'],generation_ns=j['actual_generation_ns']);return j
 def enqueue(self,j):
  with self.cv:
   self.ready.put(j);j['r_ns']=self.clock();self.enqueued+=1
   e=self.event('ready',request_id=j['request_id'],ready_ns=j['r_ns']);j['ready_event_id']=e['seq'];self.cv.notify_all()
 def admit(self,worker_id):
  # Entire cap check, FIFO removal and reservation are one critical section.
  with self.cv:
   self.apply_due()
   reserve_ns=self.clock()
   if self.boundary_cursor<3 and reserve_ns>=self.t0+self.plan.boundaries[self.boundary_cursor][0]:
    self.apply_due();reserve_ns=self.clock()
   if self.active>=self.cap or self.ready.empty():return None
   j=self.ready.get_nowait();previous=self.active;self.active+=1;self.started+=1
   j.update(worker_id=worker_id,admission_C=self.cap,admission_active_before=previous,
            admission_active_after=self.active,cap_event_id=self.cap_event_id,reservation_ns=reserve_ns)
   e=self.event('admission',request_id=j['request_id'],cap_event_id=self.cap_event_id,reservation_ns=reserve_ns)
   j['admission_event_id']=e['seq']
   # Same s boundary as Formal: end of bookkeeping, immediately before lock release/infer.
   j['s_ns']=self.clock();e['service_start_ns']=j['s_ns']
   return j
 def publish_completion(self,j):
  with self.cv:
   self.active-=1;self.completed+=1
   e=self.event('completion_publication',request_id=j['request_id'],actual_completion_ns=j['c_ns'])
   j['completion_publication_ns']=e['ns'];j['completion_event_id']=e['seq'];self.records.append(j);self.cv.notify_all()
 def fail(self,error):
  with self.cv:self.errors.append(str(error));self.stop=True;self.cv.notify_all()
