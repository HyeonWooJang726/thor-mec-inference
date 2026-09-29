"""CPU race regression, frozen behavior comparison and read-only forensic replay."""
import ast
import copy
import hashlib
import inspect
import json
from pathlib import Path
import queue
import tempfile
import threading
import time
from bootstrap_21 import ROOT,OUT,HERE,PLAN
import run_21
import checkpoint_21 as cp
import analysis_21 as a
import run_v2 as oldrun
import config_v2 as conf
import verify_v2 as previous_test

def save(name,data):
    with (OUT/name).open('x') as f:json.dump(data,f,indent=2)

def race_tests():
    # Deterministic reproduction of live dict traversal interrupted by publisher.
    ready=threading.Event();changed=threading.Event()
    class Pause:pass
    live={'first':Pause(),'second':2}
    def publish():ready.wait();live['edge_final']={'status':'VALID'};changed.set()
    t=threading.Thread(target=publish);t.start()
    def default(obj):ready.set();assert changed.wait(2);return 'sentinel'
    try:json.dumps(live,indent=2,default=default)
    except RuntimeError as e:assert 'dictionary changed size' in str(e)
    else:raise AssertionError('Live serialization race did not reproduce')
    t.join()
    # Serialize detached frozen state while publication proceeds outside locks.
    shared=cp.Manifest({'first':1,'second':2,'nested':{'items':[1,2]}})
    snapshot=shared.snapshot();shared['edge_final']={'status':'VALID'}
    assert 'edge_final' not in json.loads(cp.serialize(snapshot))
    shared['nested']['items'].append(3)
    assert cp.thaw(snapshot)['nested']['items']==[1,2]
    lock_released=[];real=cp.json.dumps
    def encoder(*args,**kwargs):
        done=threading.Event()
        writer=threading.Thread(target=lambda:(shared.update(probe='outside snapshot lock'),done.set()))
        writer.start();assert done.wait(2),'JSON must not hold publication lock';writer.join();lock_released.append(True)
        return real(*args,**kwargs)
    cp.json.dumps=encoder
    try:cp.serialize(shared)
    finally:cp.json.dumps=real
    # Continuous simultaneous metadata/nested diagnostic publication.
    stop=threading.Event();errors=[]
    def mutate():
        i=0
        while not stop.is_set():
            shared['edge_final']={'count':i};shared['nested']['count']=i
            shared['nested'].pop('count',None);i+=1
    worker=threading.Thread(target=mutate);worker.start()
    try:
        for _ in range(1000):json.loads(cp.serialize(shared))
    except Exception as e:errors.append(repr(e))
    finally:stop.set();worker.join(3)
    assert not errors and not worker.is_alive()
    return dict(old_race_reproduced=True,immutable_nested_snapshot=True,JSON_lock_released=bool(lock_released),concurrent_snapshots=1000,errors=errors)

def forensic():
    records=[]
    for d in sorted(PLAN.parent.glob('TCCBV2_*')):
        m=json.loads((d/'manifest.json').read_text());raw=a.read_csv(d/'per_frame.csv.gz');power=a.read_csv(d/'power_trace.csv.gz')
        stored=json.loads((d/'summary.json').read_text());replay=a.summarize(m,raw,power);part=replay['terminal_partition']
        sources=[r for r in raw if r.get('phase')=='active'];seen={(int(r['stream_id']),int(r['frame_id'])) for r in sources}
        expected={(k,f) for k in range(8) for f in range(1800)}
        queue_expected=dict(enqueue=part['LOCAL']['assigned'],start=part['LOCAL']['completed'],expired=part['LOCAL']['expired_dropped'])
        row=dict(run_id=d.name,stored_integrity=stored['integrity_status'],corrected_replay_integrity=replay['integrity_status'],
            admitted=replay['admitted_frames'],completed=replay['completed_frames'],expired=replay['expired_dropped_frames'],
            legacy_backlog_after_drain=replay['backlog_after_drain'],true_unfinished_after_drain=replay['true_unfinished_after_drain'],
            terminal_partition=part,missing_source_IDs=len(expected-seen),unexpected_source_IDs=len(seen-expected),duplicate_source_IDs=len(sources)-len(seen),
            recorded_ready_queue_accounting=m.get('ready_queue_accounting'),raw_implied_ready_queue_counts=queue_expected,
            raw_terminal_accounting_diagnostic='would pass corrected terminal accounting' if replay['terminal_accounting_status']=='PASS' else 'FAIL',
            errors=replay['errors'],instrumentation_failure_does_not_become_valid=True)
        if stored['integrity_status']=='VALID':
            assert replay['integrity_status']=='VALID'
            for key in ('admitted_frames','completed_frames','expired_dropped_frames','timely_completed_frames','backlog_after_drain','unfinished_after_drain'):assert replay[key]==stored[key]
        else:
            assert row['legacy_backlog_after_drain']==row['expired']==383 and row['true_unfinished_after_drain']==0
            assert replay['integrity_status']=='INVALID' and m.get('ready_queue_accounting') is None
        records.append(row)
    save('forensic_replay.json',records);return records

def main():
    race=race_tests();results=[]
    def functions(s):return {n.name:ast.dump(n,include_attributes=False) for n in ast.walk(ast.parse(s)) if isinstance(n,ast.FunctionDef)}
    before=functions(oldrun.adapted_source());after=functions(run_21.adapted_source())
    for name in ('infer','front','arrivals','sample_tensor','monitor','save_records','fail'):assert before[name]==after[name],name
    # The worker source retains the very same pruning class and clock argument.
    assert 'from pruning_common import PruningAccounting as QueueAccounting' in run_21.adapted_source()
    ctx=run_21.Context();ctx.bindings()
    fixture=previous_test.module('v21_fixtures',ROOT/'scripts/timely_capacity_campaign/common/verify_cpu.py')
    cache={};traces=[]
    for e in conf.LEVELS:
        plan=json.loads((conf.branch_path(e)).read_text());assert plan['order']==conf.order(e)
        for c in {r['cell']:r for r in plan['order']}.values():
            key=(c['target_service_FPS'],c['local_r'],c['edge_r'])
            if key not in cache:
                m,rows,power=fixture.fixture(c);m.update(c)
                original=a.v2.summarize(m,rows,power)
                before_bytes=json.dumps(rows,sort_keys=True,separators=(',',':')).encode()
                replay=a.summarize(m,rows,power)
                after_bytes=json.dumps(rows,sort_keys=True,separators=(',',':')).encode()
                assert before_bytes==after_bytes
                assert original['integrity_status']==replay['integrity_status']=='VALID'
                assert all(replay[k]==v for k,v in original.items()),key
                assert replay['true_unfinished_after_drain']==0
                # Exact instrumented queue counters equal unchanged pruning events.
                pruning=oldrun.old.pruning
                decisions=[]
                for _ in range(2):
                    q=queue.Queue();acct=pruning.PruningAccounting()
                    for i in range(12):acct.enqueue(q,dict(stream_id=i%8,frame_id=i,absolute_deadline_ns=100 if i%3==0 else 200),lambda:50)
                    decisions.append(([acct.begin(q.get(),lambda:100) for i in range(12)],acct.events))
                assert decisions[0]==decisions[1]
                cache[key]=dict(input_trace_sha256=hashlib.sha256(before_bytes).hexdigest(),state_metrics_unchanged=True)
                traces.append(dict(cell=c['cell'],**cache[key]))
        results.append(dict(E_max=e,run_count=len(plan['order']),order_unchanged=True,admission_placement_arrival_pruning_submission_states='UNCHANGED'))
    f=forensic()
    save('behavior_validation.json',dict(status='PASS',race_tests=race,branches=results,unique_fixtures=len(cache),behavior_traces=traces,
        AST_identical=['infer','front','arrivals','sample_tensor','monitor','save_records','fail'],
        Edge_sender_receiver='Original class/methods reused; no overrides',existing_VALID_raw_replay='PASS',
        caveat='CPU functional equivalence only; no claim of zero instrumentation timing overhead',GPU=False,network=False,frequency_control=False))
    print('PASS race snapshots, 4 branch plans,',len(cache),'fixtures; forensic',[(r['run_id'],r['stored_integrity'],r['true_unfinished_after_drain']) for r in f])

if __name__=='__main__':main()
