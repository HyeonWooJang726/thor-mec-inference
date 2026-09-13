"""CPU-only forensic validation; does not alter frozen code/state or authorize resume."""
import csv,collections,hashlib,json,statistics
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];OUT=Path(__file__).resolve().parent
source=ROOT/'smoke_fixed_c4'
def read(name):
 with (source/name).open() as f:rows=list(csv.DictReader(f))
 for r in rows:
  for k,v in r.items():
   try:r[k]=int(v)
   except (ValueError,TypeError):pass
 return rows
r=read('per_frame.csv');events=read('events.csv');term=json.loads((source/'termination.json').read_text());exit_record=json.loads((source/'exit.json').read_text());t0=term['t0_ns'];checks={}
checks['actual_child_exit_zero']=exit_record['exit_code']==0
checks['counts']=all(term[k]==780 for k in ['expected','generated','enqueued','started','completed']) and len(r)==780
checks['source_samples']=term['samples']==[120]*6+[60]
checks['request_ids']=len({x['request_id'] for x in r})==780 and {x['request_id'] for x in r}==set(range(780))
expected=[];samples=[0]*7
for tick in range(120):
 phase=tick//30;k=[6,7,6,7][phase]
 for sid in range(k):expected.append((sid,tick,samples[sid],k,phase));samples[sid]+=1
byid={x['request_id']:x for x in r}
checks['trace_mapping']=all((byid[i]['stream_id'],byid[i]['global_tick'],byid[i]['source_sample_index'],byid[i]['arrival_K'],byid[i]['arrival_phase'])==v for i,v in enumerate(expected))
checks['timestamp_ordering']=all(x['a_ns']==t0+x['global_tick']*1000000000//30 and x['a_ns']<=x['actual_generation_ns']<=x['b_ns']<=x['r_ns']<=x['s_ns']<=x['c_ns']<=x['completion_publication_ns'] for x in r)
checks['integer_decomposition']=all(x['c_ns']-x['a_ns']==sum(x[a]-x[b] for a,b in [('b_ns','a_ns'),('r_ns','b_ns'),('s_ns','r_ns'),('c_ns','s_ns')]) for x in r)
checks['sample_consumption_order']=all([x['source_sample_index'] for x in sorted((v for v in r if v['stream_id']==sid),key=lambda x:x['b_ns'])]==list(range(samples[sid])) for sid in range(7))
active=waiting=generated=completed=0;cap=None;capid=None;fifo=collections.deque();violations=[]
for i,e in enumerate(events):
 if e['seq']!=i or (i and e['ns']<events[i-1]['ns']):violations.append(('sequence',i))
 kind=e['kind'];rid=e.get('request_id')
 if kind=='cap_apply':
  cap=e['new_C'];capid=i
  if e['phase'] and not e['logical_boundary_ns']<=e['notification_ns']<=e['ns']:violations.append(('boundary time',i))
 if kind=='generation':generated+=1
 if kind=='ready':waiting+=1;fifo.append(rid)
 if kind=='admission':
  x=byid[rid]
  if not (active<cap==x['admission_C'] and active==x['admission_active_before'] and capid==x['cap_event_id'] and fifo.popleft()==rid):violations.append(('admission',i))
  if events[capid]['phase']!=min(3,(x['reservation_ns']-t0)//1000000000):violations.append(('due boundary',i))
  active+=1;waiting-=1
 if kind=='completion_publication':active-=1;completed+=1
 if (e['active_counter'],e['ready_waiting'],e['backlog_published'])!=(active,waiting,generated-completed):violations.append(('accounting',i))
 if min(active,waiting,generated-completed)<0 or active>4:violations.append(('bounds',i))
checks['events_fifo_admission_publication']=not violations and active==waiting==generated-completed==0
sweep=collections.Counter()
for x in r:sweep[x['s_ns']]+=1;sweep[x['c_ns']]-=1
A=maxA=0
for t,d in sorted(sweep.items()):A+=d;maxA=max(maxA,A);assert 0<=A<=4
checks['service_intervals_pool_bound_and_drain']=A==0
checks['teardown_no_errors']=all(term['pipeline_NULL']) and all(term['joined'].values()) and len(term['joined'])==13 and not term['runtime_errors'] and not term['worker_errors'] and not term['watchdog_triggered']
checks['all_final_queues_zero']=all(term[k]==0 for k in ['waiting_after_drain','active_counter_after_drain','backlog_published_after_drain','due_not_generated_after_drain'])
state=json.loads((ROOT/'campaign_status.json').read_text());assert state['campaign_status']=='HALTED' and state['rows'][0]['status']=='FAIL'
result=dict(audit='CPU_ONLY_POSTMORTEM',measurement_checks='PASS' if all(checks.values()) else 'FAIL',checks=checks,violations=violations,observed_max_A=maxA,completed_frames=780,actual_child_exit_code=exit_record['exit_code'],natural_EOS=term['natural_EOS_observed'],campaign_row_remains='FAIL',campaign_remains='HALTED',additional_GPU_runs=0,primary_runs=0,reason='Postprocessor summary construction duplicates expected_frames from **row and explicit keyword; no GPU runtime failure observed',smoke_files_sha256={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in source.iterdir() if p.is_file()})
with (OUT/'smoke_forensic_validation.json').open('x') as f:json.dump(result,f,indent=2)
print(json.dumps({k:v for k,v in result.items() if k!='smoke_files_sha256'},indent=2))
