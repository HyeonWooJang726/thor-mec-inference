"""Bounded CPU regressions exercising the actual adapter's shared state code."""
from core import *
from concurrent.futures import ThreadPoolExecutor

def test():
 checks={}
 for tr in ('A','B'):
  for duration in (4,60):
   p=Trace(tr,duration);assert len(p.jobs)==(780 if duration==4 else 11700)
   assert p.samples==[duration*30]*6+[duration*15]
   for sid in range(7):assert [j['source_sample_index'] for j in p.jobs if j['stream_id']==sid]==list(range(p.samples[sid]))
   assert len({j['request_id'] for j in p.jobs})==len(p.jobs)
   for n in range(duration*30):
    g=[j for j in p.jobs if j['global_tick']==n];assert len(g)==p.ks[n//p.phase_ticks]
    assert all(j['offset_ns']==n*1000000000//30 and j['arrival_phase']==n//p.phase_ticks for j in g)
   checks[f'trace_{tr}_{duration}']='PASS'
 assert not miss(33333333) and miss(33333334);checks['integer_deadline']='PASS'
 clock=[1000000000];p=Trace('B',4);s=State(p,'K_LOOKUP_C2_C4',lambda:clock[0]);s.initialize(clock[0]);assert s.cap==4
 for template in p.jobs[:12]:j=s.generate(template);s.enqueue(j)
 with ThreadPoolExecutor(8) as ex:admitted=list(ex.map(s.admit,range(8)))
 jobs=[j for j in admitted if j];assert len(jobs)==4 and s.active==4
 assert [j['request_id'] for j in jobs]==list(range(4))
 clock[0]+=1000000000
 assert s.admit(0) is None and s.cap==2 and s.active==4
 for j in jobs[:2]:j['c_ns']=clock[0];s.publish_completion(j)
 assert s.active==s.cap==2 and s.admit(0) is None
 jobs[2]['c_ns']=clock[0];s.publish_completion(jobs[2]);assert s.admit(0)['request_id']==4
 checks['atomic_admission_fifo_nonpreemptive_decrease']='PASS'
 e=[e for e in s.events if e['kind']=='cap_apply'];assert all(x['ns']>=x['logical_boundary_ns'] for x in e)
 clock[0]+=1000000000
 with s.cv:s.apply_due()
 assert s.cap==4
 checks['boundary_increase_notification_apply']='PASS'
 # Producer is several phases late: all requests survive; K never rewinds.
 clock[0]=100000000000;s2=State(Trace('A',4),'K_LOOKUP_C2_C4',lambda:clock[0]);s2.initialize(clock[0]);clock[0]+=4000000000
 for template in s2.plan.jobs:s2.generate(template)
 assert s2.k==7 and s2.cap==4 and s2.generated==780
 assert sum(e['kind']=='superseded_cap_decision' for e in s2.events)==2
 for sid in range(7):
  while not s2.arrival[sid].empty():s2.enqueue(s2.arrival[sid].get())
 while s2.ready.qsize():
  j=s2.admit(0);assert j is not None;j['c_ns']=clock[0];s2.publish_completion(j)
 assert s2.completed==780 and s2.active==0 and s2.enqueued-s2.started==0 and s2.generated-s2.completed==0
 checks['delayed_producer_no_drop_no_K_rewind_drain']='PASS'
 for policy in POLICIES:
  s3=State(Trace('A',4),policy,lambda:clock[0]);s3.initialize(clock[0]);clock[0]+=1000000000
  with s3.cv:s3.apply_due()
  assert len([e for e in s3.events if e['kind']=='workload_notification'])==1
 checks['identical_fixed_notification_path']='PASS'
 return checks
if __name__=='__main__':save(ROOT/'cpu_validation.json',dict(validation='PASS',tests=test(),GPU_runs=0));print('CPU PASS')
