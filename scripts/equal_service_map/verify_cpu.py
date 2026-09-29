#!/usr/bin/env python3
"""Synthetic accounting, admission, energy and memory-wire tests; no hardware."""
import argparse
import ast
import copy
from contextlib import contextmanager
import inspect
import json
from pathlib import Path
import socket
import tempfile
import threading
import time
import numpy as np
from common import ROOT, prior, decorate, load_plan, hello, EdgeLink, schedule
import run_map as run
import analyze_map as analysis
from formal_cpu_verify import pair
from formal_server import serve_session


def fixture(c):
    t0=10**12;t1=t0+60*10**9;rows=[];workers=[t0,t0]
    for f in range(1800):
        for sid in range(8):
            a=t0+f*10**9//30
            r=decorate(dict(phase='active',stream_id=sid,frame_id=f,logical_arrival_ns=a,
                admission_timestamp_ns=a,source_timestamp_ns=f*10**9//30,
                b_ns=a,source_pulled_ns=a+10,resize_start_ns=a+20,resize_end_ns=a+30),t0,c['target_service_FPS'],c['supply_mode'])
            if r['admitted']:r.update(payload_ready_ns=a+40,ready_timestamp_ns=a+50)
            if r['placement']=='LOCAL':
                w=min(range(2),key=lambda i:workers[i]);start=max(a+50,workers[w])
                r.update(inference_start_timestamp_ns=start,completion_timestamp_ns=start+2_000_000)
                workers[w]=r['completion_timestamp_ns']
            elif r['placement']=='EDGE':
                start=max(r['edge_release_target_ns'],a+50)
                r.update(socket_submission_ns=start,socket_send_complete_ns=start+1_000_000,
                    response_completion_ns=start+25_000_000,completion_timestamp_ns=start+25_000_000,
                    payload_sha256='CPU_FIXTURE',raw_sha256='CPU_FIXTURE')
                for j,k in enumerate(('receive_complete_ns','queue_enter_ns','queue_start_ns','preprocess_start_ns','preprocess_end_ns','inference_start_ns','inference_end_ns','response_ready_ns')):
                    r['edge_'+k]=start+10**15+j*1000
            rows.append(r)
    rows += [dict(phase='warmup',completion_timestamp_ns=t0-1_000_000,stream_id=-1,frame_id=i) for i in range(60)]
    count=60*8*c['edge_r'];local=60*8*c['local_r'];freq=c['frequency_MHz']
    m=dict(c,errors=[],active_start_ns=t0,active_end_ns=t1,OC3_before=10,OC3_after=12,requested_freq_MHz=freq,
        edge_threads_exited=True,edge_path_errors=[],ready_queue_accounting=dict(enqueue=local,start=local),
        edge_final=dict(received=count,completed=count,responses_sent=count,integrity_status='VALID',
            drain_completed=True,cleanup_completed=True,worker_thread_exited=True,drops=0,duplicates=0,queue_cap_saturation=False,errors=[]))
    if not count:m.update(edge_usage='NOT_USED',edge_final={'status':'NOT_USED'})
    power=[dict(timestamp_ns=t0+i*100_000_000,measured_power_W=50,actual_gpu_freq_MHz=freq,
        min_freq_Hz=freq*10**6,max_freq_Hz=freq*10**6,OC3_count=10 if i<50 else 12,temperature_C=40,
        raw_tegrastats='CPU_FIXTURE VDD_GPU 50000mW/99999mW/99999mW VDD_CPU_SOC_MSS 15000mW/99999mW VIN_SYS_5V0 5000mW/99999mW VIN 80000mW/99999mW/99999mW') for i in range(-1,603)]
    return m,rows,power


def verify():
    plan=load_plan();checks=[];fixtures={};flat=[];masks={}
    import importlib.util
    spec=importlib.util.spec_from_file_location('equal_service_edge_launcher',Path(__file__).with_name('edge_server.py'))
    edge=importlib.util.module_from_spec(spec);spec.loader.exec_module(edge)
    assert len(edge.conditions(plan))==12
    for c in plan['order']:
        m,rows,power=fixture(c);s=analysis.summarize(m,rows,power)
        assert s['integrity_status']=='VALID',s['errors']
        assert (s['local_assigned_FPS'],s['edge_assigned_FPS'],s['total_offered_FPS'])==(8*c['local_r'],8*c['edge_r'],c['target_service_FPS'])
        assert s['source_frames']==14400 and s['decode_ready_FPS']==s['resize_ready_FPS']==240
        assert s['admission_skipped_frames']==14400-60*c['target_service_FPS']
        assert s['backlogs']['H']['regression_start_ns']==m['active_start_ns']+30*10**9
        assert abs(s['g_B_H']-s['g_B_L']-s['g_B_E'])<1e-9
        assert s['queue_stable'] and s['backlog_after_drain']==0 and s['active_concurrency_peak']<=2
        assert s['hardware_status']=='PROTECTION_LIMITED'
        assert all(x['terminal_placement_gap']==0 for x in s['per_stream'])
        assert abs(s['E_device_J']-4800)<1e-9 and s['device_avg_power_W']==80
        assert abs(s['rails']['VDD_GPU']['active_energy_J']-s['active_energy_J'])<1e-9
        if not c['edge_r']:assert all(v is None for v in s['edge_inference_ms'].values())
        mask={(r['stream_id'],r['frame_id']) for r in rows if r.get('admitted')}
        target=c['target_service_FPS'];assert mask==masks.setdefault(target,mask)
        erows=[r for r in rows if r.get('placement')=='EDGE'];rate=8*c['edge_r']
        if rate:
            assert sorted(r['edge_request_id'] for r in erows)==list(range(rate*60))
            releases=sorted(r['edge_release_target_ns'] for r in erows)
            assert set(b-a for a,b in zip(releases,releases[1:]))=={10**9//rate}
        s.update(repeat=c['repeat'],order_index=c['order_index']);flat.append(analysis.flatten(s));fixtures[c['cell']]=(m,rows,power)
    checks.append('24 full 60-s CPU raw replays: equal A/B admitted IDs, exact per-stream splits, 14400 decode/resize, zero terminal gap, complete drain, OLS final30s, additive backlogs, OC3 valid, C_L<=2, uniform Edge eligibility')
    for cell,(m,rows,power) in fixtures.items():
        for fault in ('completion','placement','timestamp','cap','power'):
            mm,rr,pp=copy.deepcopy(m),copy.deepcopy(rows),copy.deepcopy(power)
            r=next(r for r in rr if r.get('placement')=='LOCAL')
            if fault=='completion':r.pop('completion_timestamp_ns')
            if fault=='placement':r['admitted']=0
            if fault=='timestamp':r['source_pulled_ns']=r['logical_arrival_ns']-1
            if fault=='cap':mm['queue_cap_saturation']=True
            if fault=='power':pp=[]
            assert analysis.summarize(mm,rr,pp)['integrity_status']=='INVALID',(cell,fault)
    checks.append('all 8 cells reject missing completions, admission/timestamp corruption, queue cap and missing GPU power')
    m,rows,power=fixtures['B160']
    pp=copy.deepcopy(power)
    for r in pp:r['raw_tegrastats']=r['raw_tegrastats'].replace(' VIN ',' MISSING_VIN ')
    s=analysis.summarize(m,rows,pp)
    assert s['integrity_status']=='VALID' and s['energy_scope_status']=='ENERGY_SCOPE_UNRESOLVED' and s['E_device_J'] is None
    pp=copy.deepcopy(power);pp[50]['raw_tegrastats']=''
    assert analysis.rail_integrals(m,pp,100)['VIN']['status']=='UNAVAILABLE'
    pp=[r for i,r in enumerate(power) if not 100<=i<=110]
    assert analysis.rail_integrals(m,pp,100)['VIN']['status']=='UNAVAILABLE'
    # Analytic ramp integration; instantaneous first field, never average/max or sum.
    pp=copy.deepcopy(power)
    for i,r in enumerate(pp):
        watts=80+(r['timestamp_ns']-m['active_start_ns'])/1e9
        r['raw_tegrastats']=f'VIN {round(watts*1000)}mW/999999mW'
    assert abs(analysis.rail_integrals(m,pp,100)['VIN']['active_energy_J']-6600)<1e-8
    checks.append('VIN constant/ramp analytic integration, independent rails, no sum; missing rail/sample/gap fails energy closed without fabricating measurement invalidity')
    group=[copy.deepcopy(r) for r in flat if r['target_service_FPS']==160]
    for r in group:
        for k in analysis.COSTS:r[k]=10 if r['supply_mode']=='A' else 11
    assert analysis.classify(group)=='LOCAL_ONLY_DOMINATES'
    for r in group:
        if r['supply_mode']=='B':
            for k in analysis.COSTS:r[k]=9
    assert analysis.classify(group)=='HYBRID_DOMINATES'
    for r in group:
        if r['supply_mode']=='B':r['global_E2E_ms_p95']=11
    assert analysis.classify(group)=='TRADEOFF_PARETO'
    for mode,verdict in [('A','ONLY_HYBRID_FEASIBLE'),('B','ONLY_LOCAL_FEASIBLE')]:
        test=copy.deepcopy(group)
        for r in test:
            if r['supply_mode']==mode:r['queue_stable']=False
        assert analysis.classify(test)==verdict
    assert analysis.classify(group[:-1])=='INCONCLUSIVE'
    for key,value in [('queue_stable',False),('integrity_status','INVALID'),('energy_scope_status','ENERGY_SCOPE_UNRESOLVED')]:
        test=copy.deepcopy(group);test[0][key]=value;assert analysis.classify(test)=='INCONCLUSIVE'
    test=copy.deepcopy(group)
    for r in test:r['synthetic_stat']=r['repeat']
    for r in analysis.aggregate(test):
        if r['metric']=='synthetic_stat':assert r['mean']==2 and r['sample_SD']==1
    checks.append('six classifications, invalid/mixed/missing fail closed, three-repeat sample SD; no small-difference significance test')
    def nested(src):return {n.name:ast.dump(n,include_attributes=False) for n in ast.walk(ast.parse(src)) if isinstance(n,ast.FunctionDef)}
    before,after=nested(run.pilot.adapted_source()),nested(run.adapted_source())
    for name in ('infer','front','sample_tensor','monitor','checkpoint','save_records'):assert before[name]==after[name],name
    adjusted=run.pilot.adapted_source().replace("decorate(row,manifest['active_start_ns'],condition['edge_r'])","decorate(row,manifest['active_start_ns'],condition['target_service_FPS'],condition['supply_mode'])")
    assert nested(adjusted)['arrivals']==after['arrivals']
    run.bindings()
    checks.append('frozen infer/frontend/resize/monitor/lifecycle AST identical; source scheduler only placement args changed; imported existing frequency helper')
    scratch=Path(tempfile.mkdtemp(prefix='equal_service_CPU_'))
    payloads,_=prior.old.edge_runtime.load_cache(ROOT/'results/edge_raw_capacity_gate/raw/semantic_raw640_30.npz')
    class MockBackend:
        def __init__(self):self.payloads=payloads
        def process(self,raw):
            times={k:time.monotonic_ns() for k in ('preprocess_start_ns','preprocess_end_ns','inference_start_ns','inference_end_ns','response_ready_ns')}
            return times,prior.old.wire.encode_outputs(dict(pred_logits=np.zeros((1,300,7),np.float32),pred_boxes=np.zeros((1,300,4),np.float32)))
        def info(self):return dict(C_E=1,B=1,CUDA_Graph=False,dynamic_batching=False,engine_sha256=prior.old.edge_runtime.ENGINE_SHA256,
            cache_sha256=prior.old.edge_runtime.CACHE_SHA256,color_conversion='numpy_channel_reverse_BGR_to_RGB',provenance='CPU_MOCK_NOT_MEASURED')
        def close(self):pass
    original=socket.create_connection
    def forbidden(*a,**k):raise AssertionError('CPU test attempted real network')
    socket.create_connection=forbidden
    try:
        # All 24 handshakes/order metadata; cached real RAW bytes, memory transport only.
        for planned in plan['order']:
            c=dict(planned,seconds=1);d=scratch/c['run_id'];d.mkdir();m={};errors=[]
            if not c['edge_r']:
                link=EdgeLink(c,c['run_id'],m,d,errors.append,'CPU_PLAN','unused');link.finish();link.close()
                assert m['edge_usage']=='NOT_USED';continue
            client,server=pair();client.close=lambda:client.shutdown(0);server.close=lambda:server.shutdown(0)
            expected=hello(c,c['run_id'],'CPU_PLAN');done=[]
            thread=threading.Thread(target=lambda:done.append(serve_session(server,d/'edge',expected,MockBackend)))
            thread.start();(d/'thor').mkdir()
            link=EdgeLink(c,c['run_id'],m,d/'thor',errors.append,'CPU_PLAN','unused',transport=client)
            start=time.monotonic_ns()-10**9;jobs=[]
            for (sid,f),_ in reversed(list(schedule(c['target_service_FPS'],'B')[1].items())):
                r=decorate(dict(stream_id=sid,frame_id=f,logical_arrival_ns=start+f*10**9//30),start,c['target_service_FPS'],'B')
                link.put(r,payloads[sid]);jobs.append(r)
            link.finish();assert link.done.wait(10);link.close();thread.join(10)
            assert not thread.is_alive() and not errors and done[0]['integrity_status']=='VALID'
            assert done[0]['received']==8*c['edge_r'] and all(r.get('c_ns') for r in jobs)
    finally:socket.create_connection=original
    checks.append('12 no-connection controls +12 memory-only fragmented RAW640 sessions, count/HELLO/result/clean drain; no real GPU/network')
    savedfreq,savedpre=run.frequency,run.PREFLIGHT
    class FakeFrequency:
        legacy=None
        def __init__(self,fault):self.fault=fault;self.state=(315000000,1575000000);self.pins=0;self.legacy=self
        def inspect(self):return {'provenance':'CPU_FAKE'}
        def validate_target(self,mhz):
            if self.fault=='unsupported':raise ValueError('CPU_FAKE unsupported')
        def require_control(self):
            if self.fault=='permission':raise PermissionError('CPU_FAKE permission')
        def read_range(self):return dict(min_freq=self.state[0],max_freq=self.state[1],cur_freq=0)
        @contextmanager
        def pinned(self,mhz):
            assert mhz==1575;self.pins+=1;self.state=(1575000000,1575000000) if self.fault!='pin' else self.state
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
    checks.append('mock-only frequency preflight: permissions/support/pin/restore failures block; no real clock access')
    return dict(status='PASS',checks=checks,provenance='SYNTHETIC_CPU_VALIDATION_NOT_MEASUREMENT',GPU_executed=False,network_executed=False,frequency_accessed=False,scratch_path=str(scratch))

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,required=True);a=ap.parse_args()
    if a.output.exists():raise RuntimeError('No overwrite')
    result=verify()
    with a.output.open('x') as f:json.dump(result,f,indent=2);f.write('\n')
    print(json.dumps(result,indent=2))
