#!/usr/bin/env python3
"""CPU-only correctness fixtures; no real socket, GPU, decode or frequency access."""
import argparse
import ast
import copy
import difflib
import hashlib
import inspect
import json
from pathlib import Path
import tempfile
import threading
import time

import numpy as np
from hybrid_common import ROOT,decorate,remaining,edge_runtime,wire,sha,hello
from run_hybrid import adapted_source,base
from analyze_hybrid import summarize
from edge_link import EdgeLink
from formal_cpu_verify import pair
from formal_server import serve_session


def synthetic_fixture():
    """Invented timestamps/power for accounting tests ONLY, never performance data."""
    t0=10**12;duration=10;t1=t0+10**10;rows=[];workers=[t0,t0]
    for f in range(300):
        for sid in range(8):
            a=t0+f*10**9//30
            r=decorate(dict(phase='active',stream_id=sid,frame_id=f,logical_arrival_ns=a,
              admission_timestamp_ns=a,admitted=1,source_timestamp_ns=f*10**9//30,
              b_ns=a,source_pulled_ns=a+10,resize_start_ns=a+20,resize_end_ns=a+30,
              payload_ready_ns=a+40,ready_timestamp_ns=a+50),t0)
            if r['placement']=='LOCAL':
                w=min(range(2),key=lambda i:workers[i]);start=max(a+50,workers[w])
                r.update(inference_start_timestamp_ns=start,completion_timestamp_ns=start+2_000_000)
                workers[w]=r['completion_timestamp_ns']
            else:
                start=max(r['edge_release_target_ns'],a+50)
                r.update(socket_submission_ns=start,socket_send_complete_ns=start+1_000_000,
                         response_completion_ns=start+25_000_000,completion_timestamp_ns=start+25_000_000,
                         payload_sha256='CPU_FIXTURE',raw_sha256='CPU_FIXTURE')
                for j,key in enumerate(('receive_complete_ns','queue_enter_ns','queue_start_ns',
                        'preprocess_start_ns','preprocess_end_ns','inference_start_ns','inference_end_ns','response_ready_ns')):
                    r['edge_'+key]=start+10**15+j*1000
            rows.append(r)
    rows += [dict(phase='warmup',completion_timestamp_ns=t0-1_000_000,stream_id=-1,frame_id=i) for i in range(60)]
    m=dict(run_id='CPU_ONLY',kind='smoke',repeat=0,errors=[],active_start_ns=t0,active_end_ns=t1,
      OC3_before=10,OC3_after=12,requested_freq_MHz=1575,edge_threads_exited=True,edge_path_errors=[],
      ready_queue_accounting=dict(enqueue=2000,start=2000),
      edge_final=dict(received=400,completed=400,responses_sent=400,integrity_status='VALID',
                      drain_completed=True,cleanup_completed=True,worker_thread_exited=True,
                      drops=0,duplicates=0,queue_cap_saturation=False,errors=[]))
    power=[dict(timestamp_ns=t0+i*100_000_000,measured_power_W=50,actual_gpu_freq_MHz=1575,
         min_freq_Hz=1575000000,max_freq_Hz=1575000000,OC3_count=10 if i<50 else 12,
         temperature_C=40,raw_tegrastats='CPU_FIXTURE VDD_GPU 50000mW/50000mW') for i in range(-1,103)]
    return m,rows,power


def verify():
    checks=[]
    source=adapted_source();before=ast.parse(inspect.getsource(base.run_one));after=ast.parse(source)
    def nested(tree,name):return next(n for n in ast.walk(tree) if isinstance(n,ast.FunctionDef) and n.name==name)
    for name in ('infer','monitor','checkpoint','save_records'):
        assert ast.dump(nested(before,name))==ast.dump(nested(after,name)),name
    # Scheduler differs only by the explicit deterministic placement ledger hook.
    sched=copy.deepcopy(nested(after,'arrivals'))
    class StripPlacement(ast.NodeTransformer):
        def visit_Expr(self,node):
            if isinstance(node.value,ast.Call) and isinstance(node.value.func,ast.Name) and node.value.func.id=='decorate':return None
            return self.generic_visit(node)
    sched=StripPlacement().visit(sched)
    assert ast.dump(sched)==ast.dump(nested(before,'arrivals'))
    checks.append('unchanged Local infer/telemetry/checkpoint/raw writer; source scheduler unchanged except placement ledger')
    for seconds in (10,60):
        rows=[decorate(dict(stream_id=s,frame_id=f,logical_arrival_ns=f*10**9//30),0)
              for f in range(seconds*30) for s in range(8)]
        edge=[r for r in rows if r['placement']=='EDGE']
        assert len(edge)==seconds*40
        assert sorted(r['edge_request_id'] for r in edge)==list(range(seconds*40))
        targets=sorted(r['edge_release_target_ns'] for r in edge)
        assert targets==[i*25_000_000 for i in range(seconds*40)]
        for s in range(8):
            assert sum(r['placement']=='EDGE' and r['stream_id']==s for r in rows)==seconds*5
            assert sum(r['placement']=='LOCAL' and r['stream_id']==s for r in rows)==seconds*25
    checks.append('10/60 s placement exact: per-stream 25/5; global 200/40; zero gap; 25-ms Edge target spacing')
    cache=ROOT/'results/edge_raw_capacity_gate/raw/semantic_raw640_30.npz'
    payloads,ids=edge_runtime.load_cache(cache)
    with np.load(cache,allow_pickle=False) as z:
        for image,raw,digest in zip(z['raw640'],payloads,z['reference_tensor_sha256']):
            local=remaining(memoryview(image).cast('B'));remote=remaining(raw)
            assert np.array_equal(local,remote)
            assert hashlib.sha256(local.tobytes()).hexdigest()==str(digest)
    checks.append('30/30 existing RAW640 tensor SHA exact: zero-copy Local view = Edge bytes = cached canonical reference')
    m,rows,power=synthetic_fixture();result=summarize(m,rows,power)
    assert result['integrity_status']=='VALID',result['errors']
    assert result['local_assigned_FPS']==200 and result['edge_assigned_FPS']==40 and result['total_offered_FPS']==240
    assert result['backlog_after_drain']==0 and result['hardware_status']=='PROTECTION_LIMITED'
    assert abs(result['g_B_H']-result['g_B_L']-result['g_B_E'])<1e-9
    assert result['active_concurrency_peak']<=2
    active=[r for r in rows if r['phase']=='active']
    for stamp in sorted({r['logical_arrival_ns'] for r in active}|{r['completion_timestamp_ns'] for r in active}):
        def b(path):return sum(r['logical_arrival_ns']<=stamp<r['completion_timestamp_ns'] for r in active if path is None or r['placement']==path)
        assert b(None)==b('LOCAL')+b('EDGE')
    for change in ('placement','missing','timestamp','cap','power'):
        mm,rr,pp=copy.deepcopy(m),copy.deepcopy(rows),copy.deepcopy(power)
        if change=='placement':rr[0]['placement']='LOCAL'
        if change=='missing':rr[1].pop('completion_timestamp_ns')
        if change=='timestamp':rr[1]['source_pulled_ns']=rr[1]['logical_arrival_ns']-1
        if change=='cap':mm['edge_final']['queue_cap_saturation']=True
        if change=='power':pp=[]
        try:r=summarize(mm,rr,pp)
        except (ValueError,TypeError):continue
        assert r['integrity_status']=='INVALID',change
    checks.append('B_H=B_L+B_E eventwise/slope; drain; C2; canonical power/OC3; corruption rejection (synthetic timestamps ONLY)')
    temp=Path(tempfile.mkdtemp(prefix='hybrid_CPU_ONLY_'))
    client,server=pair()
    client.close=lambda:client.shutdown(0)
    server.close=lambda:server.shutdown(0)
    class MockBackend:
        def __init__(self):self.payloads=payloads
        def process(self,raw):
            timing={k:time.monotonic_ns() for k in ('preprocess_start_ns','preprocess_end_ns',
                    'inference_start_ns','inference_end_ns','response_ready_ns')}
            return timing,wire.encode_outputs(dict(pred_logits=np.zeros((1,300,7),np.float32),pred_boxes=np.zeros((1,300,4),np.float32)))
        def info(self):return dict(C_E=1,B=1,CUDA_Graph=False,dynamic_batching=False,
               engine_sha256=edge_runtime.ENGINE_SHA256,cache_sha256=edge_runtime.CACHE_SHA256,
               color_conversion='numpy_channel_reverse_BGR_to_RGB',provenance='CPU_TEST_NOT_MEASURED')
        def close(self):pass
    condition=dict(kind='smoke',repeat=0,seconds=.2);expected=hello(condition,'CPU_LINK','CPU_PLAN')
    server_results=[]
    t=threading.Thread(target=lambda:server_results.append(serve_session(server,temp/'edge',expected,MockBackend)))
    t.start();(temp/'thor').mkdir();manifest={};errors=[]
    link=EdgeLink(condition,'CPU_LINK',manifest,temp/'thor',errors.append,'CPU_PLAN','unused',transport=client)
    start=time.monotonic_ns()
    jobs=[]
    # Submit readiness out of order: sender must still use the frozen ID/release sequence.
    for s in reversed(range(8)):
        from hybrid_common import RESIDUES
        f=RESIDUES[s];row=decorate(dict(stream_id=s,frame_id=f,logical_arrival_ns=start+f*10**9//30),start)
        link.put(row,payloads[s]);jobs.append(row)
    link.finish();assert link.done.wait(10);link.close();t.join(10)
    assert not t.is_alive() and not errors and manifest['edge_threads_exited']
    assert all(r.get('c_ns') for r in jobs) and server_results[0]['integrity_status']=='VALID'
    sent=sorted(jobs,key=lambda r:r['socket_submission_ns'])
    assert [r['edge_request_id'] for r in sent]==list(range(8))
    assert all(r['socket_submission_ns']>=r['edge_release_target_ns'] for r in jobs)
    checks.append('in-memory live-frame EdgeLink: out-of-order readiness, fixed send order, hashes, FINAL/cleanup, no sockets/GPU')
    return dict(status='PASS',checks=checks,provenance='CPU_ONLY; synthetic timing/power/output fixtures are NOT measurements',
                GPU_executed=False,network_executed=False,clock_accessed=False,scratch_path=str(temp),
                adapted_run_one_sha256=hashlib.sha256(source.encode()).hexdigest())


if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--output',required=True);args=ap.parse_args()
    result=verify();wire.save(args.output,result);print(json.dumps(result,indent=2))
