#!/usr/bin/env python3
"""Synthetic accounting and in-memory protocol tests; no GPU/network/clock access."""
import argparse
import ast
from contextlib import contextmanager
import copy
import inspect
import json
from pathlib import Path
import socket
import tempfile
import threading
import time
import numpy as np

from common import ROOT, prior, decorate, load_plan, hello, EdgeLink
import run_formal as run
import analyze_formal as analysis
import edge_server
from verify_hybrid_cpu import synthetic_fixture
from formal_cpu_verify import pair
from formal_server import serve_session


def fixture(e):
    # Expand the frozen CPU fixture to 60 s without inventing benchmark measurements.
    src=inspect.getsource(synthetic_fixture)
    for old,new in [('duration=10;t1=t0+10**10','duration=60;t1=t0+60*10**9'),
                    ('range(300)','range(1800)'),('enqueue=2000,start=2000','enqueue=12000,start=12000'),
                    ('received=400,completed=400,responses_sent=400','received=2400,completed=2400,responses_sent=2400'),
                    ('range(-1,103)','range(-1,603)')]:
        src=prior.hybrid.replace_once(src,old,new)
    ns=dict(synthetic_fixture.__globals__)
    exec(compile(src,'<60-s-CPU-fixture-only>','exec'),ns)
    m,rows,power=ns['synthetic_fixture']();m.update(edge_r=e,kind='formal',repeat=1)
    if not e:m.update(edge_usage='NOT_USED',edge_final={'status':'NOT_USED'})
    for r in rows:
        if r['phase']!='active':continue
        decorate(r,m['active_start_ns'],e)
        if r['placement']=='SKIP':
            for k in list(r):
                if k in ('payload_ready_ns','ready_timestamp_ns','completion_timestamp_ns','socket_submission_ns',
                         'socket_send_complete_ns','response_completion_ns','raw_sha256','payload_sha256') or k.startswith('edge_'):
                    r.pop(k,None)
    return m,rows,power


def verify():
    plan=load_plan();checks=[];fixtures={};flat=[];masks=[]
    assert len(edge_server.conditions(plan))==5
    for c in plan['order']:
        e=c['edge_r'];m,rows,power=fixture(e)
        m.update(run_id=c['run_id'],repeat=c['repeat'])
        s=analysis.summarize(m,rows,power)
        assert s['integrity_status']=='VALID',s['errors']
        assert (s['local_assigned_FPS'],s['edge_assigned_FPS'],s['total_offered_FPS'])==(200,e*8,200+e*8)
        assert s['source_frames']==14400 and s['local_assigned_frames']==12000
        assert s['edge_assigned_frames']==480*e and s['explicit_admission_exclusions']==480*(5-e)
        assert s['decode_ready_FPS']==s['resize_ready_FPS']==240
        assert s['backlogs']['H']['regression_start_ns']==m['active_start_ns']+30*10**9
        assert abs(s['g_B_H']-s['g_B_L']-s['g_B_E'])<1e-9
        assert s['backlog_after_drain']==0 and s['queue_stable']
        assert s['hardware_status']=='PROTECTION_LIMITED'  # OC3 does not invalidate.
        if not e:assert all(v is None for v in s['edge_inference_ms'].values())
        local={(int(r['stream_id']),int(r['frame_id'])) for r in rows if r.get('placement')=='LOCAL'}
        masks.append(local)
        if e:
            edge=[r for r in rows if r.get('placement')=='EDGE']
            assert sorted(r['edge_request_id'] for r in edge)==list(range(2400))
            assert sorted(r['edge_release_target_ns']-m['active_start_ns'] for r in edge)==[i*25_000_000 for i in range(2400)]
        s.update(edge_r=e,repeat=c['repeat'],order_index=c['order_index'])
        flat.append(analysis.flatten(s));fixtures[e]=(m,rows,power)
    assert all(mask==masks[0] for mask in masks)
    assert analysis.verdict(flat)=='CAPACITY_EXTENSION_CONFIRMED'
    for e,expected in [(0,'HARNESS_BASELINE_NOT_STABLE'),(5,'CAPACITY_EXTENSION_NOT_CONFIRMED')]:
        rr=copy.deepcopy(flat)
        for r in [r for r in rr if r['edge_r']==e][:2]:r['queue_stable']=False
        assert analysis.verdict(rr)==expected
    rr=copy.deepcopy(flat);rr[0]['queue_stable']=False
    assert analysis.verdict(rr)=='INCONCLUSIVE'
    rr=copy.deepcopy(flat);rr[0]['integrity_status']='INVALID'
    assert analysis.verdict(rr)=='INCONCLUSIVE'
    assert analysis.verdict(flat[:-1])=='INCONCLUSIVE'
    synthetic_stats=copy.deepcopy(flat)
    for r in synthetic_stats:r['local_completed_FPS']=r['repeat']
    for q in analysis.aggregate(synthetic_stats):
        if q['metric']=='local_completed_FPS':assert q['mean']==3 and abs(q['sample_SD']-2.5**.5)<1e-12 and q['valid_n']==5
    checks.append('ten 60-s CPU replays: identical 12000 Local IDs; source/resize 14400; Edge 0/2400; exclusion 2400/0; final-30-s OLS; mean/sample SD; four verdicts and single-failure INCONCLUSIVE')
    for e,(m,rows,power) in fixtures.items():
        for fault in ('completion','timestamp','placement','cap','power'):
            mm,rr,pp=copy.deepcopy(m),copy.deepcopy(rows),copy.deepcopy(power)
            r=next(r for r in rr if r.get('placement')=='LOCAL')
            if fault=='completion':r.pop('completion_timestamp_ns')
            if fault=='timestamp':r['source_pulled_ns']=r['logical_arrival_ns']-1
            if fault=='placement':r['admitted']=0
            if fault=='cap':mm['queue_cap_saturation']=True
            if fault=='power':pp=[]
            assert analysis.summarize(mm,rr,pp)['integrity_status']=='INVALID',fault
    checks.append('missing completion, timestamp, placement, cap and power corruption rejected for E0/E40')
    def nested(src):
        return {n.name:ast.dump(n,include_attributes=False) for n in ast.walk(ast.parse(src)) if isinstance(n,ast.FunctionDef)}
    old,new=nested(run.pilot.adapted_source()),nested(run.adapted_source())
    for name in ('infer','front','arrivals','sample_tensor','monitor','checkpoint','save_records'):
        assert old[name]==new[name],name
    run.bindings()
    checks.append('P02 infer/frontend/arrivals/resize/monitor/lifecycle nested functions AST-identical; new bindings compile')
    scratch=Path(tempfile.mkdtemp(prefix='formal_E0_E40_CPU_'))
    payloads,_=prior.old.edge_runtime.load_cache(ROOT/'results/edge_raw_capacity_gate/raw/semantic_raw640_30.npz')
    class MockBackend:
        def __init__(self):self.payloads=payloads
        def process(self,raw):
            stamps={k:time.monotonic_ns() for k in ('preprocess_start_ns','preprocess_end_ns','inference_start_ns','inference_end_ns','response_ready_ns')}
            return stamps,prior.old.wire.encode_outputs(dict(pred_logits=np.zeros((1,300,7),np.float32),pred_boxes=np.zeros((1,300,4),np.float32)))
        def info(self):
            return dict(C_E=1,B=1,CUDA_Graph=False,dynamic_batching=False,engine_sha256=prior.old.edge_runtime.ENGINE_SHA256,
                cache_sha256=prior.old.edge_runtime.CACHE_SHA256,color_conversion='numpy_channel_reverse_BGR_to_RGB',provenance='CPU_MOCK_NOT_MEASURED')
        def close(self):pass
    original_connect=socket.create_connection
    def forbidden(*a,**k):raise AssertionError('CPU verification attempted network')
    socket.create_connection=forbidden
    try:
        for planned in plan['order']:
            c=dict(planned,seconds=.2);d=scratch/c['run_id'];d.mkdir();m={};errors=[]
            if not c['edge_r']:
                link=EdgeLink(c,c['run_id'],m,d,errors.append,'CPU_PLAN','unused')
                link.finish();link.close();assert m['edge_usage']=='NOT_USED';continue
            client,server=pair();client.close=lambda:client.shutdown(0);server.close=lambda:server.shutdown(0)
            expected=hello(c,c['run_id'],'CPU_PLAN');done=[]
            thread=threading.Thread(target=lambda:done.append(serve_session(server,d/'edge',expected,MockBackend)))
            thread.start();(d/'thor').mkdir()
            link=EdgeLink(c,c['run_id'],m,d/'thor',errors.append,'CPU_PLAN','unused',transport=client)
            start=time.monotonic_ns();jobs=[]
            for sid in reversed(range(8)):
                f=prior.old.RESIDUES[sid]
                row=decorate(dict(stream_id=sid,frame_id=f,logical_arrival_ns=start+f*10**9//30),start,5)
                link.put(row,payloads[sid]);jobs.append(row)
            link.finish();assert link.done.wait(10);link.close();thread.join(10)
            assert not thread.is_alive() and not errors and done[0]['integrity_status']=='VALID'
            assert done[0]['received']==8 and all(r.get('c_ns') for r in jobs)
            assert sorted(r['edge_request_id'] for r in jobs)==list(range(8))
    finally:socket.create_connection=original_connect
    checks.append('five E0 controls forbidden from connecting; five matching round HELLO/FINAL memory sessions, fragmented wire, live-cache bytes and CPU mock outputs only')
    original_frequency,original_preflight=run.frequency,run.PREFLIGHT
    class FakeFrequency:
        def __init__(self,fault):self.fault=fault;self.state=(315000000,1575000000);self.pins=0
        def inspect(self):return dict(provenance='CPU_FAKE',writable=self.fault!='permission')
        def require_control(self):
            if self.fault=='permission':raise PermissionError('CPU_FAKE permission')
        def read_range(self):return dict(min_freq=self.state[0],max_freq=self.state[1],cur_freq=0)
        @contextmanager
        def pinned(self,mhz):
            assert mhz==1575;self.pins+=1
            self.state=(1575000000,1575000000) if self.fault!='pin' else (315000000,1575000000)
            try:yield
            finally:
                if self.fault=='restore':raise RuntimeError('CPU_FAKE restore failure')
                self.state=(315000000,1575000000)
    try:
        for fault in ('none','permission','pin','restore'):
            run.frequency=FakeFrequency(fault);run.PREFLIGHT=scratch/f'preflight_{fault}.json'
            try:run.frequency_preflight();ok=True
            except (PermissionError,RuntimeError):ok=False
            assert ok==(fault=='none')
            j=json.loads(run.PREFLIGHT.read_text());assert (j['status']=='PASS')==ok
            assert run.frequency.pins==(0 if fault=='permission' else 1)
            if ok:assert j['pinned']['cur_freq']==0 and j['restored']['min_freq']==315000000
    finally:run.frequency,run.PREFLIGHT=original_frequency,original_preflight
    checks.append('mock-only preflight: one pin/restore; idle cur=0 accepted; permission/pin/restore failures preserved and block; real helper never accessed')
    return dict(status='PASS',checks=checks,provenance='SYNTHETIC_CPU_TESTS_NOT_EXPERIMENTAL_RESULTS',
                GPU_executed=False,network_executed=False,frequency_accessed=False,scratch_path=str(scratch))


if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,required=True);a=ap.parse_args()
    if a.output.exists():raise RuntimeError('No verification overwrite')
    result=verify()
    with a.output.open('x') as f:json.dump(result,f,indent=2);f.write('\n')
    print(json.dumps(result,indent=2))
