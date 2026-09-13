"""Offline integrity, exact interval accounting and predeclared run/window metrics."""
import collections,math,statistics
import numpy as np
from core import *

def numbers(path):
 rows=loadcsv(path)
 for r in rows:
  for k,v in list(r.items()):
   if v and k not in ('trace','policy','acquisition_id','kind'):
    try:r[k]=int(v)
    except ValueError:pass
 return rows

def metrics(rows):
 if not rows:return dict(n=0,DMR_percent=None)
 v={key:np.array([r[key] for r in rows],dtype=np.int64) for key in ('a_ns','b_ns','r_ns','s_ns','c_ns')}
 lat=v['c_ns']-v['a_ns'];result=dict(n=len(rows),miss_count=int(np.count_nonzero(lat*30>1000000000)),DMR_percent=100*np.count_nonzero(lat*30>1000000000)/len(rows))
 for name,x,y in [('start_lag','b_ns','a_ns'),('front_end','r_ns','b_ns'),('queue','s_ns','r_ns'),('service','c_ns','s_ns'),('local','c_ns','a_ns')]:
  ns=v[x]-v[y]
  for stat,val in [('mean',np.mean(ns)),('p95',np.percentile(ns,95)),('p99',np.percentile(ns,99))]:result[f'{name}_{stat}_ms']=float(val)/1e6
 return result

def canonical_expected(row, plan, term, metadata, manifest):
 canonical=len(plan.jobs)
 candidates={'trace':canonical,'row':row['expected_frames'],'termination':term['expected'],'runtime_metadata':metadata['expected_frames']}
 for key in ('acquisition_id','trace','policy','duration_s','expected_frames'):
  if metadata[key]!=row[key]:raise ValueError('runtime metadata mismatch: '+key)
 matches=[r for r in manifest['acquisitions'] if r['acquisition_id']==row['acquisition_id']]
 if len(matches)!=1:raise ValueError('manifest acquisition not unique')
 for key in ('trace','policy','duration_s','expected_frames'):
  if matches[0][key]!=row[key]:raise ValueError('manifest mismatch: '+key)
 candidates['manifest']=matches[0]['expected_frames']
 if any(v!=canonical for v in candidates.values()):raise ValueError('expected_frames disagreement: '+str(candidates))
 return canonical

def run(row, input_dir=None, output_dir=None, manifest=None):
 source=Path(input_dir) if input_dir else ROOT/row['acquisition_id']
 out=Path(output_dir) if output_dir else source
 frames=numbers(source/'per_frame.csv');events=numbers(source/'events.csv');term=json.loads((source/'termination.json').read_text());plan=Trace(row['trace'],row['duration_s'])
 metadata=json.loads((source/'runtime_metadata.json').read_text())['row']
 manifest=manifest if manifest is not None else json.loads((ROOT/'frozen_plan.json').read_text())
 expected_frames_canonical=canonical_expected(row,plan,term,metadata,manifest)
 # Only validated identity/plan columns enter summaries; runtime bookkeeping is separate.
 summary_row={k:v for k,v in row.items() if k not in ('expected_frames','completed_frames','status','reason','child_pid','start_monotonic_ns','started_at','finished_at')}
 checks=[]
 def check(name,value):
  checks.append(dict(check=name,PASS=bool(value)))
  if not value:raise AssertionError(name)
 try:
  check('actual_child_exit_zero',json.loads((source/'exit.json').read_text())['exit_code']==0)
  check('exact_counts',len(frames)==len(plan.jobs)==term['expected']==term['generated']==term['enqueued']==term['started']==term['completed'])
  check('source_budgets',term['samples']==plan.samples and all(term['front_done']))
  check('pipeline_NULL_and_workers_joined',all(term['pipeline_NULL']) and len(term['joined'])==13 and all(term['joined'].values()))
  check('no_errors_watchdog',not term['runtime_errors'] and not term['worker_errors'] and not term['watchdog_triggered'])
  check('final_counters_zero',all(term[k]==0 for k in ('waiting_after_drain','active_counter_after_drain','backlog_published_after_drain','due_not_generated_after_drain')))
  byid={r['request_id']:r for r in frames};check('unique_request_ids',set(byid)==set(range(len(plan.jobs))) and len(byid)==len(frames))
  t0=term['t0_ns']
  for template in plan.jobs:
   r=byid[template['request_id']]
   assert all(r[k]==template[k] for k in ('stream_id','global_tick','source_sample_index','arrival_K','arrival_phase'))
   assert r['a_ns']==t0+template['offset_ns']
   assert r['a_ns']<=r['actual_generation_ns']<=r['b_ns']<=r['r_ns']<=r['s_ns']<=r['c_ns']<=r['completion_publication_ns']
   assert (r['b_ns']-r['a_ns'])+(r['r_ns']-r['b_ns'])+(r['s_ns']-r['r_ns'])+(r['c_ns']-r['s_ns'])==r['c_ns']-r['a_ns']
  check('source_order_timestamp_integer_decomposition',True)
  for sid in range(7):
   g=sorted((r for r in frames if r['stream_id']==sid),key=lambda r:r['b_ns'])
   assert [r['source_sample_index'] for r in g]==list(range(plan.samples[sid]))
  active=generated=completed=waiting=0;fifo=collections.deque();cap=None;capid=None;admitted=set();published=set();enqueued=set()
  for i,e in enumerate(events):
   assert e['seq']==i and (i==0 or e['ns']>=events[i-1]['ns'])
   kind=e['kind'];rid=e.get('request_id')
   if kind=='generation':generated+=1
   if kind=='ready':waiting+=1;fifo.append(rid);assert rid not in enqueued;enqueued.add(rid)
   if kind=='cap_apply':
    cap=e['new_C'];capid=i
    if e['phase']>0:assert e['logical_boundary_ns']<=e['notification_ns']<=e['ns']
   if kind=='admission':
    r=byid[rid];assert cap==r['admission_C'] and capid==r['cap_event_id'] and active==r['admission_active_before'] and active<cap
    assert fifo.popleft()==rid and rid not in admitted;admitted.add(rid);active+=1;waiting-=1
    assert active==r['admission_active_after'] and e['service_start_ns']==r['s_ns']
    expected_phase=min(3,max(0,(r['reservation_ns']-t0)//(row['duration_s']*1000000000//4)))
    assert events[capid]['phase']==expected_phase
   if kind=='completion_publication':
    assert rid in admitted and rid not in published;published.add(rid);active-=1;completed+=1
    assert e['actual_completion_ns']==byid[rid]['c_ns']
   assert e['active_counter']==active and e['ready_waiting']==waiting and e['backlog_published']==generated-completed
   assert min(active,waiting,generated-completed)>=0 and active<=4
  check('event_order_FIFO_atomic_admission_cap_and_publication',active==waiting==generated-completed==0 and completed==len(frames))
  resources=json.loads((source/'resources.json').read_text())
  check('common_pool_4',all(resources[k]==4 for k in ('configured_workers','execution_context_count','cuda_stream_count','buffer_set_count','pinned_staging_set_count')) and resources['engine_instance_count']==1)
 except Exception as error:
  save(out/'integrity.json',dict(validation='FAIL',checks=checks,reason=str(error),completed_frames=len(frames)))
  raise
 # Exact application state sweep. Event-time completion is separate from publication.
 changes=collections.defaultdict(lambda:[0,0,0,0,None])
 for r in frames:
  changes[r['a_ns']][3]+=1
  changes[r['actual_generation_ns']][2]+=1;changes[r['actual_generation_ns']][3]-=1
  changes[r['r_ns']][1]+=1;changes[r['s_ns']][1]-=1;changes[r['s_ns']][0]+=1
  changes[r['c_ns']][0]-=1;changes[r['c_ns']][2]-=1
 for e in events:
  if e['kind']=='cap_apply':changes[e['ns']][4]=e['new_C']
 endpoint=t0+row['duration_s']*1000000000
 for ns in [t0,endpoint,*[t0+i*1000000000 for i in range(row['duration_s']+1)]]:changes[ns]
 A=Q=B=U=0;C=None;previous=None;timeline=[];areaA=areaQ=areaB=areaU=eq=above=blocked=0;maxA=maxQ=maxB=maxU=0
 for ns,d in sorted(changes.items()):
  if previous is not None:
   dt=max(0,min(ns,endpoint)-max(previous,t0));areaA+=A*dt;areaQ+=Q*dt;areaB+=B*dt;areaU+=U*dt
   if C is not None:eq+=(A==C)*dt;above+=(A>C)*dt;blocked+=(A>=C and Q>0)*dt
  A+=d[0];Q+=d[1];B+=d[2];U+=d[3];C=d[4] if d[4] is not None else C
  assert min(A,Q,B,U)>=0 and A<=4
  maxA=max(maxA,A);maxQ=max(maxQ,Q);maxB=max(maxB,B);maxU=max(maxU,U)
  timeline.append(dict(ns=ns,A_service=A,ready_waiting=Q,generated_backlog=B,due_not_generated=U,C=C));previous=ns
 assert A==Q==B==U==0
 result=dict(**summary_row,**metrics(frames),completed_frames=len(frames),expected_frames=expected_frames_canonical,integrity='PASS',observed_max_A=maxA,
             completed_FPS=len(frames)/((max(r['c_ns'] for r in frames)-t0)/1e9),drain_duration=max(0,(max(r['c_ns'] for r in frames)-endpoint)/1e9),
             time_weighted_mean_A=areaA/(endpoint-t0),time_weighted_ready_waiting=areaQ/(endpoint-t0),time_weighted_generated_backlog=areaB/(endpoint-t0),time_weighted_due_not_generated=areaU/(endpoint-t0),
             fraction_A_eq_C=eq/(endpoint-t0),fraction_A_gt_C=above/(endpoint-t0),fraction_A_ge_C_and_waiting=blocked/(endpoint-t0),
             peak_ready_waiting=maxQ,peak_generated_backlog=maxB,peak_due_not_generated=maxU)
 result['status']='PASS'
 windows=[]
 # Reporting windows fixed at 1 s for primary; smoke phase=1 s has no remainder.
 phase_len=row['duration_s']//4
 for phase in range(4):
  start=phase*phase_len
  for name,lo,hi in [('startup' if phase==0 else 'transition',start,start+1),('phase_remainder',start+1,start+phase_len)]:
   if hi<=lo:continue
   g=[r for r in frames if lo*30<=r['global_tick']<hi*30]
   windows.append(dict(acquisition_id=row['acquisition_id'],round=row['round'],trace=row['trace'],policy=row['policy'],window=name,phase=phase,arrival_start_s=lo,arrival_end_s=hi,**metrics(g)))
 for k in [6,7]:windows.append(dict(acquisition_id=row['acquisition_id'],round=row['round'],trace=row['trace'],policy=row['policy'],window=f'K{k}_arrival_cohort',phase='',**metrics([r for r in frames if r['arrival_K']==k])))
 transitions=[]
 for e in events:
  if e['kind']!='cap_apply' or e['phase']==0:continue
  t=e['ns'];post=[x for x in timeline if x['ns']>=t];value=next(x for x in timeline if x['ns']==t)
  first_admission=next((x['reservation_ns'] for x in events if x['kind']=='admission' and x['reservation_ns']>=t),None)
  le=next((x['ns'] for x in post if x['A_service']<=e['new_C']),None);lt=next((x['ns'] for x in post if x['A_service']<e['new_C']),None)
  postpub=[x for x in events if x['ns']>=t]
  ple=next((x['ns'] for x in postpub if x['active_counter']<=e['new_C']),None);plt=next((x['ns'] for x in postpub if x['active_counter']<e['new_C']),None)
  masks=dict(already_service=lambda r:r['s_ns']<=t<r['c_ns'],already_ready=lambda r:r['r_ns']<=t<r['s_ns'],generated_pre_ready=lambda r:r['actual_generation_ns']<=t<r['r_ns'],generated_after_apply=lambda r:r['actual_generation_ns']>t)
  for group,mask in masks.items():
   transitions.append(dict(acquisition_id=row['acquisition_id'],round=row['round'],trace=row['trace'],policy=row['policy'],phase=e['phase'],logical_boundary_ns=e['logical_boundary_ns'],notification_ns=e['notification_ns'],apply_ns=t,old_C=e['old_C'],new_C=e['new_C'],active_counter_at_apply=e['active_counter'],A_service_at_apply=value['A_service'],ready_at_apply=value['ready_waiting'],generated_backlog_at_apply=value['generated_backlog'],due_not_generated_at_apply=value['due_not_generated'],first_A_service_le_C_ns=le,first_A_service_lt_C_ns=lt,first_counter_le_C_ns=ple,first_counter_lt_C_ns=plt,first_new_admission_ns=first_admission,cohort_at_apply=group,**metrics([r for r in frames if mask(r)])))
 # Per-second exact sample + arrival-window miss, for the bounded second figure.
 bins=[]
 for sec in range(row['duration_s']+1):
  ns=t0+sec*1000000000;x=next(x for x in timeline if x['ns']==ns)
  bins.append(dict(acquisition_id=row['acquisition_id'],round=row['round'],trace=row['trace'],policy=row['policy'],second=sec,**x,**metrics([r for r in frames if sec*30<=r['global_tick']<(sec+1)*30])))
 save(out/'integrity.json',dict(validation='PASS',checks=checks,completed_frames=len(frames),exact_interval_accounting='PASS',scope='static/dynamic application state, not GPU utilization'))
 save(out/'summary.json',result);csvout(out/'window_summary.csv',windows);csvout(out/'transition_summary.csv',transitions);csvout(out/'state_seconds.csv',bins)
 return result
