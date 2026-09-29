#!/usr/bin/env python3
"""Synthetic CPU validation only; network/GPU/frequency access is forbidden."""
import argparse
import ast
from contextlib import contextmanager
import copy
import importlib.util
import inspect
import json
from pathlib import Path
import socket
import tempfile
import threading
import time
import types
import numpy as np
from isolation_common import ROOT,prior,equal,decorate,load_plan,hello,EdgeLink,proven_runner
import run_isolation as run
import analyze_isolation as analysis
import verify_cpu as previous
from formal_cpu_verify import pair
from formal_server import serve_session

fixture=types.FunctionType(previous.fixture.__code__,dict(previous.fixture.__globals__,decorate=decorate))


def verify():
    plan=load_plan();checks=[];fixtures={};flat=[];masks=[]
    spec=importlib.util.spec_from_file_location('isolation_edge_launcher',Path(__file__).with_name('edge_server.py'))
    edge=importlib.util.module_from_spec(spec);spec.loader.exec_module(edge)
    assert [c['run_id'] for c in edge.conditions(plan)]==[c['run_id'] for c in plan['order'] if c['supply_mode']=='B']
    for c in plan['order']:
        m,rows,power=fixture(c);s=analysis.summarize(m,rows,power)
        assert s['integrity_status']=='VALID',s['errors']
        assert s['source_frames']==14400 and s['decode_ready_FPS']==s['resize_ready_FPS']==240
        assert s['local_assigned_frames']==11040 and s['local_assigned_FPS']==184
        assert s['edge_assigned_frames']==(0 if c['supply_mode']=='A' else 960)
        assert s['total_offered_FPS']==(184 if c['supply_mode']=='A' else 200)
        assert s['admission_skipped_frames']==(3360 if c['supply_mode']=='A' else 2400)
        assert s['queue_stable'] and s['backlog_after_drain']==0
        assert s['backlogs']['H']['regression_start_ns']==m['active_start_ns']+30*10**9
        assert abs(s['g_B_H']-s['g_B_L']-s['g_B_E'])<1e-9
        assert s['active_concurrency_peak']<=2 and s['stage_identity_exact']
        assert s['hardware_status']=='PROTECTION_LIMITED' and s['device_avg_power_W']==80
        mask=set(analysis.local_rows(rows));masks.append(mask)
        for sid in range(8):
            assert sum(s==sid for s,_ in mask)==1380
        if c['edge_r']:
            rr=[r for r in rows if r.get('placement')=='EDGE']
            assert sorted(r['edge_request_id'] for r in rr)==list(range(960))
            stamps=sorted(r['edge_release_target_ns'] for r in rr)
            assert set(b-a for a,b in zip(stamps,stamps[1:]))=={62_500_000}
        else:assert all(v is None for v in s['edge_inference_ms'].values())
        flat.append(analysis.flatten(s));fixtures[c['repeat'],c['supply_mode']]=(m,rows,power)
    assert all(mask==masks[0] for mask in masks)
    baseline_mask={(sid,f) for f in range(1800) for sid in range(8) if equal.decorate(dict(stream_id=sid,frame_id=f,logical_arrival_ns=f*10**9//30),0,200,'B')['placement']=='LOCAL'}
    assert masks[0]==baseline_mask
    pairs=[analysis.paired_decomposition(fixtures[r,'A'][1],fixtures[r,'B'][1],r) for r in (1,2,3)]
    assert analysis.classify(flat,pairs)=='LATENCY_COUPLING_NOT_SUPPORTED'
    checks.append('six 60-s fixtures: identical11040 Local IDs match frozen B200, per-stream1380 Local, Edge0/960,14400 decoded/resized, exact admission exclusions, no drops, final30s OLS, additive backlog, full drain')
    shifted=[]
    for c in plan['order']:
        m,rows,power=copy.deepcopy(fixtures[c['repeat'],c['supply_mode']])
        if c['supply_mode']=='B':
            for r in rows:
                if r.get('placement')=='LOCAL':
                    r['inference_start_timestamp_ns']+=5_000_000;r['completion_timestamp_ns']+=5_000_000
        s=analysis.summarize(m,rows,power);assert s['integrity_status']=='VALID',s['errors']
        shifted.append(analysis.flatten(s))
    assert analysis.classify(shifted,pairs)=='LATENCY_COUPLING_SUPPORTED'
    test=copy.deepcopy(shifted)
    for r in test:
        if r['supply_mode']=='B':r['local_service_ms_mean']+=1
    assert analysis.classify(test,pairs)=='INCONCLUSIVE'  # Slower service can amplify queueing.
    for field,value in [('integrity_status','INVALID'),('local_E2E_ms_p95',0),('local_queue_ms_p99',None)]:
        test=copy.deepcopy(shifted);next(r for r in test if r['supply_mode']=='B')[field]=value
        assert analysis.classify(test,pairs)=='INCONCLUSIVE'
    assert analysis.classify(shifted[:-1],pairs)=='INCONCLUSIVE'
    bad=copy.deepcopy(pairs);bad[0]['identity_match']=False
    assert analysis.classify(shifted,bad)=='INCONCLUSIVE'
    checks.append('classification: wait increase with unchanged service, exact null, slower-service confound, missing/invalid/mixed repeats; no equivalence margin invented')
    mm,rr,pp=copy.deepcopy(fixtures[1,'B'])
    for r in rr:
        if r.get('placement')=='LOCAL':
            r['ready_timestamp_ns']+=1;r['inference_start_timestamp_ns']+=3;r['completion_timestamp_ns']+=6
    decomp=analysis.paired_decomposition(fixtures[1,'A'][1],rr,1)
    for key,ns in [('frontend',1),('queue',2),('service',3),('E2E',6),('pre_service',3)]:
        assert abs(decomp[f'mean_B_minus_A_{key}_ms']-ns/1e6)<1e-15
    for mode in ('A','B'):
        for fault in ('completion','admission','identity','timestamp','cap','power'):
            m,rows,power=copy.deepcopy(fixtures[1,mode]);r=next(r for r in rows if r.get('placement')=='LOCAL')
            if fault=='completion':r.pop('completion_timestamp_ns')
            if fault=='admission':r['admitted']=0
            if fault=='identity':r['frame_id']+=1
            if fault=='timestamp':r['source_pulled_ns']=r['logical_arrival_ns']-1
            if fault=='cap':m['queue_cap_saturation']=True
            if fault=='power':power=[]
            assert analysis.summarize(m,rows,power)['integrity_status']=='INVALID',(mode,fault)
    checks.append('matched ns stage identity; corruption tests reject missing completion/admission/ID/timestamp/cap/power')
    def nested(s):return {n.name:ast.dump(n,include_attributes=False) for n in ast.walk(ast.parse(s)) if isinstance(n,ast.FunctionDef)}
    old,new=nested(proven_runner.adapted_source()),nested(run.adapted_source())
    for name in ('infer','front','arrivals','sample_tensor','monitor','checkpoint','save_records'):assert old[name]==new[name],name
    run.bindings()
    checks.append('all Local pipeline nested functions AST-identical to Equal-Service; no new pipeline, controller or serialization')
    scratch=Path(tempfile.mkdtemp(prefix='latency_isolation_CPU_'))
    payloads,_=prior.old.edge_runtime.load_cache(ROOT/'results/edge_raw_capacity_gate/raw/semantic_raw640_30.npz')
    class MockBackend:
        def __init__(self):self.payloads=payloads
        def process(self,raw):
            stamps={k:time.monotonic_ns() for k in ('preprocess_start_ns','preprocess_end_ns','inference_start_ns','inference_end_ns','response_ready_ns')}
            return stamps,prior.old.wire.encode_outputs(dict(pred_logits=np.zeros((1,300,7),np.float32),pred_boxes=np.zeros((1,300,4),np.float32)))
        def info(self):return dict(C_E=1,B=1,CUDA_Graph=False,dynamic_batching=False,engine_sha256=prior.old.edge_runtime.ENGINE_SHA256,cache_sha256=prior.old.edge_runtime.CACHE_SHA256,color_conversion='numpy_channel_reverse_BGR_to_RGB',provenance='CPU_MOCK_NOT_MEASUREMENT')
        def close(self):pass
    saved=socket.create_connection
    def forbidden(*a,**kw):raise AssertionError('Real network forbidden in CPU validation')
    socket.create_connection=forbidden
    try:
        for planned in plan['order']:
            c=dict(planned,seconds=1);d=scratch/c['run_id'];d.mkdir();m={};errors=[]
            if c['supply_mode']=='A':
                link=EdgeLink(c,c['run_id'],m,d,errors.append,'CPU_PLAN','unused');link.finish();link.close();assert m['edge_usage']=='NOT_USED';continue
            client,server=pair();client.close=lambda:client.shutdown(0);server.close=lambda:server.shutdown(0)
            expected=hello(c,c['run_id'],'CPU_PLAN');done=[]
            thread=threading.Thread(target=lambda:done.append(serve_session(server,d/'edge',expected,MockBackend)))
            thread.start();(d/'thor').mkdir()
            link=EdgeLink(c,c['run_id'],m,d/'thor',errors.append,'CPU_PLAN','unused',transport=client)
            start=time.monotonic_ns()-10**9;jobs=[]
            for (sid,f),_ in reversed(list(equal.schedule(200,'B')[1].items())):
                row=decorate(dict(stream_id=sid,frame_id=f,logical_arrival_ns=start+f*10**9//30),start,200,'B')
                link.put(row,payloads[sid]);jobs.append(row)
            link.finish();assert link.done.wait(10);link.close();thread.join(10)
            assert not thread.is_alive() and not errors and done[0]['integrity_status']=='VALID'
            assert done[0]['received']==16 and all(r.get('c_ns') for r in jobs)
    finally:socket.create_connection=saved
    checks.append('A never connects;3 memory-only fragmented RAW640 B sessions, same existing sender/receiver/server, correct count and drain; cached real bytes + mock outputs')
    savedfreq,savedpre=run.frequency,run.PREFLIGHT
    class FakeFrequency:
        def __init__(self,fault):self.fault=fault;self.state=(315000000,1575000000);self.pins=0;self.legacy=self
        def inspect(self):return {'provenance':'CPU_FAKE'}
        def validate_target(self,mhz):
            assert mhz==1413
            if self.fault=='unsupported':raise ValueError('CPU_FAKE unsupported')
        def require_control(self):
            if self.fault=='permission':raise PermissionError('CPU_FAKE permission')
        def read_range(self):return dict(min_freq=self.state[0],max_freq=self.state[1],cur_freq=0)
        @contextmanager
        def pinned(self,mhz):
            assert mhz==1413;self.pins+=1
            if self.fault!='pin':self.state=(1413000000,1413000000)
            try:yield
            finally:
                if self.fault=='restore':raise RuntimeError('CPU_FAKE restore')
                self.state=(315000000,1575000000)
    try:
        for fault in ('none','permission','unsupported','pin','restore'):
            run.frequency=FakeFrequency(fault);run.PREFLIGHT=scratch/f'preflight_{fault}.json'
            try:run.frequency_preflight();ok=True
            except (PermissionError,RuntimeError,ValueError):ok=False
            assert ok==(fault=='none')
            assert json.loads(run.PREFLIGHT.read_text())['status']==('PASS' if ok else 'FAIL')
            assert run.frequency.pins==(0 if fault in ('permission','unsupported') else 1)
    finally:run.frequency,run.PREFLIGHT=savedfreq,savedpre
    checks.append('mock-only preflight1413 pin/default315-1575 restore; permissions/support/readback/restore failures block; no real clocks')
    return dict(status='PASS',checks=checks,provenance='SYNTHETIC_CPU_VALIDATION_NOT_MEASUREMENT',GPU_executed=False,network_executed=False,frequency_accessed=False,scratch_path=str(scratch))

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,required=True);a=ap.parse_args()
    if a.output.exists():raise RuntimeError('No verification overwrite')
    result=verify()
    with a.output.open('x') as f:json.dump(result,f,indent=2);f.write('\n')
    print(json.dumps(result,indent=2))
