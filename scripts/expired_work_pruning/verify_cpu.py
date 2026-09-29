#!/usr/bin/env python3
"""Synthetic CPU/memory-wire verification. No CUDA, sockets, clock control or measurements."""
import argparse
import ast
import copy
from contextlib import redirect_stdout
import csv
import gzip
import importlib.util
import json
import io
from pathlib import Path
import queue
import socket
import tempfile
import threading
import time
import types
import numpy as np
import pruning_common as common
from pruning_common import ROOT,sha,expected_order,decorate,expire,PruningAccounting,EdgeLink,hello,prior
import run_pruning as run
import analyze_pruning as analysis
from formal_cpu_verify import pair


def module(name,path):
    s=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m


old=module('equal_CPU_fixture',ROOT/'scripts/equal_service_map/verify_cpu.py')
edge=module('pruning_edge_CPU',Path(__file__).with_name('edge_server.py'))
build_plan=module('pruning_prepare_CPU',Path(__file__).with_name('prepare.py')).build_plan


def fixture(c,prune=True):
    def decorated(row,start,target,mode):return decorate(row,start,target,mode,c['deadline_ms'])
    fn=types.FunctionType(old.fixture.__code__,dict(old.fixture.__globals__,decorate=decorated))
    m,rows,power=fn(c)
    for i,r in enumerate(rows):
        if r.get('phase')!='active' or not r.get('admitted'):continue
        if prune and i%13==0:
            for k in ('inference_start_timestamp_ns','completion_timestamp_ns','socket_submission_ns',
                      'socket_send_complete_ns','response_completion_ns'):
                r.pop(k,None)
            for k in list(r):
                if k.startswith('edge_') and k not in ('edge_request_id','edge_release_target_ns'):r.pop(k)
            expire(r,r['absolute_deadline_ns'],'LOCAL_BEFORE_TRT' if r['placement']=='LOCAL' else 'EDGE_BEFORE_SUBMISSION')
        else:
            r['expiry_check_ns']=r['inference_start_timestamp_ns'] if r['placement']=='LOCAL' else r['socket_submission_ns']
            r['terminal_state']='COMPLETED'
    local=[r for r in rows if r.get('placement')=='LOCAL'];erows=[r for r in rows if r.get('placement')=='EDGE']
    ld=sum(r.get('terminal_state')=='EXPIRED_DROP' for r in local)
    ed=sorted(r['edge_request_id'] for r in erows if r.get('terminal_state')=='EXPIRED_DROP')
    m['ready_queue_accounting']=dict(enqueue=len(local),start=len(local)-ld,expired=ld)
    m['edge_final'].update(assigned=len(erows),expired_request_ids=ed,client_expired_before_submission=len(ed),
        received=len(erows)-len(ed),completed=len(erows)-len(ed),responses_sent=len(erows)-len(ed))
    return m,rows,power


def verify():
    plan=build_plan();checks=[];fixtures={}
    assert len(edge.conditions(plan))==12
    baseline=analysis.baseline(plan);assert len(baseline)==12
    q=queue.Queue();a=PruningAccounting();jobs=[]
    for i in range(4):
        job=dict(stream_id=0,frame_id=i,absolute_deadline_ns=100 if i in (0,2) else 200)
        a.enqueue(q,job,lambda:50);jobs.append(job)
    states=[a.begin(q.get(),lambda:100) for _ in range(4)]
    assert states==[False,True,False,True] and (a.n_enqueue,a.n_start,a.n_expired)==(4,2,2)
    assert all('c_ns' not in j for j in jobs) and all('s_ns' not in jobs[i] for i in (0,2))
    assert [e['frame_id'] for e in a.events if e['kind']=='start']==[1,3]
    for job,stamp in [(dict(absolute_deadline_ns=100),99),(dict(absolute_deadline_ns=100,s_ns=90),101),
                      (dict(absolute_deadline_ns=100,socket_submission_ns=90),101)]:
        try:expire(job,stamp,'CPU')
        except ValueError:pass
        else:raise AssertionError('Early expiry/preemption allowed')
    checks.append('Local FIFO, exact-deadline expiry, separate terminal accounting; reject early expiry and post-start/post-submission cancellation')
    masks={}
    for c in plan['order']:
        m,rows,power=fixture(c);s=analysis.summarize(m,rows,power)
        assert s['integrity_status']=='VALID',s['errors']
        assert s['source_frames']==14400 and s['admitted_frames']==60*c['target_service_FPS']
        assert s['completed_frames']+s['expired_dropped_frames']==s['admitted_frames']
        assert s['executed_frames']==s['completed_frames']
        assert s['backlog_after_drain']==s['expired_dropped_frames']>0 and s['unfinished_after_drain']==0
        assert s['TIR_source']==s['timely_completed_frames']/14400
        assert s['TIR_admission']==s['timely_completed_frames']/s['admitted_frames']
        assert s['VIN_active_energy_J']==4800 and s['VIN_J_per_timely_frame']==4800/s['timely_completed_frames']
        assert s['backlogs']['H']['regression_start_ns']==m['active_start_ns']+30*10**9
        assert abs(s['g_B_H']-s['g_B_L']-s['g_B_E'])<1e-8
        assert abs(s['g_U_H']-s['g_U_L']-s['g_U_E'])<1e-8
        assert s['decode_ready_FPS']==s['resize_ready_FPS']==240 and s['active_concurrency_peak']<=2
        assert sum(x['timely_completed_frames'] for x in s['per_stream'])==s['timely_completed_frames']
        assert all(x['TIR_source']==x['timely_completed_frames']/1800 for x in s['per_stream'])
        mask=[(r['stream_id'],r['frame_id'],r['placement']) for r in rows if r.get('phase')=='active']
        assert mask==masks.setdefault(c['target_service_FPS'],mask)
        fixtures[c['cell']]=(m,rows,power)
    checks.append('12 full60s synthetic raw fixtures:14400sources, canonical placement/IDs across deadlines, no false completions, B/U distinct, final30OLS additive, per-stream source denominators, independent activeVIN integration')
    m,rows,power=fixture(plan['order'][0],False)
    local=next(r for r in rows if r.get('placement')=='LOCAL')
    # A started request finishing exactly at D is timely; one ns later is not.
    local['inference_start_timestamp_ns']=local['absolute_deadline_ns']-1
    local['expiry_check_ns']=local['inference_start_timestamp_ns']
    local['completion_timestamp_ns']=local['absolute_deadline_ns']
    s=analysis.summarize(m,rows,power);n=s['timely_completed_frames']
    local['completion_timestamp_ns']+=1
    assert analysis.summarize(m,rows,power)['timely_completed_frames']==n-1
    for cell in fixtures:
        for fault in ('completion','due','early_expiry','started_expiry','edge_partition','queue_count','cap','power'):
            m,rows,power=copy.deepcopy(fixtures[cell]);r=next(r for r in rows if r.get('terminal_state')=='EXPIRED_DROP')
            if fault=='completion':next(x for x in rows if x.get('terminal_state')=='COMPLETED').pop('completion_timestamp_ns')
            if fault=='due':r['logical_arrival_ns']+=1
            if fault=='early_expiry':r['expired_drop_ns']=r['expiry_check_ns']=r['absolute_deadline_ns']-1
            if fault=='started_expiry':r['inference_start_timestamp_ns']=r['expired_drop_ns']
            if fault=='edge_partition':m['edge_final']['expired_request_ids']=[]
            if fault=='queue_count':m['ready_queue_accounting']['start']+=1
            if fault=='cap':m['queue_cap_saturation']=True
            if fault=='power':power=[]
            assert analysis.summarize(m,rows,power)['integrity_status']=='INVALID',(cell,fault)
    checks.append('inclusive timely deadline, absent completion, early/post-start expiry, wrong due, wrong terminal partitions, queue cap, missing power all handled explicitly')
    c=plan['order'][0];m,rows,power=fixture(c,False)
    for r in rows:
        if r.get('phase')!='active' or not r.get('admitted'):continue
        for k in ('inference_start_timestamp_ns','completion_timestamp_ns','socket_submission_ns','socket_send_complete_ns','response_completion_ns'):
            r.pop(k,None)
        for k in list(r):
            if k.startswith('edge_') and k not in ('edge_request_id','edge_release_target_ns'):r.pop(k)
        expire(r,r['absolute_deadline_ns'],'LOCAL_BEFORE_TRT' if r['placement']=='LOCAL' else 'EDGE_BEFORE_SUBMISSION')
    n=8*c['local_r']*60;en=8*c['edge_r']*60
    m['ready_queue_accounting']=dict(enqueue=n,start=0,expired=n)
    m['edge_final'].update(assigned=en,received=0,completed=0,responses_sent=0,
        expired_request_ids=list(range(en)),client_expired_before_submission=en)
    s=analysis.summarize(m,rows,power)
    assert s['integrity_status']=='VALID' and s['timely_completed_frames']==0 and s['VIN_J_per_timely_frame'] is None,s['errors']
    assert s['unfinished_after_drain']==0 and s['backlog_after_drain']==c['target_service_FPS']*60
    checks.append('All-expired fixture:zeroexecuted/zerotimely, empty latency=>N/A, VINJ/timely=>N/A, Udrain0 but B retains all admitted')
    def nested(s):return {n.name:ast.dump(n,include_attributes=False) for n in ast.walk(ast.parse(s)) if isinstance(n,ast.FunctionDef)}
    before,after=nested(common.canonical_runner.adapted_source()),nested(run.adapted_source())
    for name in ('front','sample_tensor','monitor','checkpoint','save_records'):
        assert before[name]==after[name],name
    normalized=run.adapted_source().replace("condition['supply_mode'],condition['deadline_ms'])","condition['supply_mode'])")
    assert before['arrivals']==nested(normalized)['arrivals']
    assert edge.Backend is edge.original.Backend
    assert nested(edge.adapted_session_source())['worker']==nested(__import__('inspect').getsource(edge.original.serve_session))['worker']
    run.bindings()
    checks.append('Frontend/pacing/resize/telemetry/save AST unchanged; Edge Backend and inference worker unchanged; guarded adapters compile')
    scratch=Path(tempfile.mkdtemp(prefix='expired_pruning_CPU_'))
    payloads,_=prior.old.edge_runtime.load_cache(ROOT/'results/edge_raw_capacity_gate/raw/semantic_raw640_30.npz')
    class MockBackend:
        def __init__(self):self.payloads=payloads
        def process(self,raw):
            times={k:time.monotonic_ns() for k in ('preprocess_start_ns','preprocess_end_ns','inference_start_ns','inference_end_ns','response_ready_ns')}
            return times,prior.old.wire.encode_outputs(dict(pred_logits=np.zeros((1,300,7),np.float32),pred_boxes=np.zeros((1,300,4),np.float32)))
        def info(self):return dict(C_E=1,B=1,CUDA_Graph=False,dynamic_batching=False,
            engine_sha256=prior.old.edge_runtime.ENGINE_SHA256,cache_sha256=prior.old.edge_runtime.CACHE_SHA256,
            color_conversion='numpy_channel_reverse_BGR_to_RGB',provenance='CPU_MOCK_NOT_MEASUREMENT')
        def close(self):pass
    original=socket.create_connection
    def forbidden(*a,**kw):raise AssertionError('Real network forbidden in CPU tests')
    socket.create_connection=forbidden
    try:
        for mode in ('none_expired','some_expired','all_expired'):
            c=dict(plan['order'][0],seconds=1);d=scratch/mode;d.mkdir();(d/'thor').mkdir()
            client,server=pair();client.close=lambda:client.shutdown(0);server.close=lambda:server.shutdown(0)
            expected=hello(c,c['run_id'],'CPU_PLAN');done=[];errors=[];m={}
            thread=threading.Thread(target=lambda:done.append(edge.serve_session(server,d/'edge',expected,MockBackend)),daemon=True)
            thread.start();link=EdgeLink(c,c['run_id'],m,d/'thor',errors.append,'CPU_PLAN','unused',transport=client)
            now=time.monotonic_ns();jobs=[];count=8*c['edge_r']
            for rid in reversed(range(count)):
                expired=mode=='all_expired' or mode=='some_expired' and rid%3==0
                row=dict(edge_request_id=rid,edge_release_target_ns=now-10**9,
                    absolute_deadline_ns=now-1 if expired else now+60*10**9)
                link.put(row,payloads[rid%len(payloads)]);jobs.append(row)
            link.finish();assert link.done.wait(10),'Memory-wire did not drain';link.close();thread.join(10)
            assert not thread.is_alive() and not errors and done[0]['integrity_status']=='VALID',errors
            expires=sum(r.get('terminal_state')=='EXPIRED_DROP' for r in jobs)
            assert done[0]['received']==count-expires and done[0]['client_expired_before_submission']==expires
            assert all(not r.get('socket_submission_ns') and not r.get('c_ns') for r in jobs if r.get('terminal_state')=='EXPIRED_DROP')
            received=[]
            with (d/'edge/requests.csv').open() as f:
                if f.read(1):
                    f.seek(0);received=[int(r['request_id']) for r in csv.DictReader(f)]
            assert received==sorted(r['edge_request_id'] for r in jobs if r.get('terminal_state')=='COMPLETED')
    finally:socket.create_connection=original
    for meta,seen in [(dict(assigned=3,submitted=1,expired_request_ids=[1]),{0}),
                      (dict(assigned=3,submitted=1,expired_request_ids=[1,1,2]),{0}),
                      (dict(assigned=3,submitted=1,expired_request_ids=[0,1,2]),{0})]:
        try:edge.partition_end(meta,seen,3)
        except ValueError:pass
        else:raise AssertionError('Corrupt END ledger accepted')
    checks.append('Fragmented in-memory protocol: no/partial/all Edge expiry, out-of-order producers preserve surviving sender FIFO, real cachedRAW/mockinference, natural drain, complete explicit ID partition; no sockets')
    good=[dict(integrity_status='VALID',delta_timely_FPS=1,delta_worst_stream_TIR=0,stream_delta_timely_FPS=[0]*8,
        pruning_expired_drop_FPS=2,delta_late_completed_FPS=-2) for _ in range(3)]
    assert analysis.verdict(good)=='PRUNING_SUPPORTED'
    bad=copy.deepcopy(good);bad[1]['stream_delta_timely_FPS'][3]=-1;assert analysis.verdict(bad)=='FAIRNESS_REGRESSION'
    bad=copy.deepcopy(good);bad[1]['delta_timely_FPS']=-1;assert analysis.verdict(bad)=='INCONCLUSIVE'
    bad=copy.deepcopy(good)
    for p in bad:p['delta_timely_FPS']=0
    assert analysis.verdict(bad)=='NO_TIMELY_GAIN'
    bad[1]['integrity_status']='INVALID';assert analysis.verdict(bad)=='INCONCLUSIVE'
    checks.append('Four descriptive verdict branches; no inferred significance, mixed/invalid evidence inconclusive; historical baseline12cells available')
    # Full gzip/JSON analyzer round trip, without touching baseline results.
    replay=scratch/'replay';replay.mkdir();test_plan=scratch/'plan.json';test_plan.write_text(json.dumps(plan))
    pre=replay/'frequency_preflight.json';pre.write_text(json.dumps(dict(status='PASS',plan_sha256=sha(test_plan),provenance='CPU_MOCK')))
    saved=analysis.OUT,analysis.PLAN,analysis.load_plan
    analysis.OUT,analysis.PLAN,analysis.load_plan=replay,test_plan,lambda:plan
    try:
        for c in plan['order']:
            m,rows,power=fixture(c);d=replay/c['run_id'];d.mkdir()
            m.update(execution_manifest_sha256=sha(test_plan),child_returncode=0,PROCESS_LIFECYCLE='PASS',status_finalized=True,
                frequency_restore_ok=True,active_phase_completed=True,drain_completed=True,cleanup_completed=True,
                frequency_preflight={'sha256':sha(pre)},pin_readback_Hz={'min_freq':1575000000,'max_freq':1575000000})
            (d/'manifest.json').write_text(json.dumps(m));(d/'summary.json').write_text(json.dumps(analysis.summarize(m,rows,power)))
            for name,data in [('per_frame',rows),('power_trace',power)]:
                fields=list(dict.fromkeys(k for r in data for k in r))
                with gzip.open(d/(name+'.csv.gz'),'wt',newline='') as f:
                    w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(data)
        with redirect_stdout(io.StringIO()):analysis.analyze(scratch/'analysis_valid')
        replayed=json.loads((scratch/'analysis_valid/replay.json').read_text())
        assert len(replayed)==12 and all(s['integrity_status']=='VALID' for s in replayed),[(s['run_id'],s['errors']) for s in replayed if s['integrity_status']!='VALID']
        saved_read=analysis.read_csv
        def missing(p):
            if Path(p).parent.name==plan['order'][0]['run_id']:raise FileNotFoundError('CPU injected failure; no file deleted')
            return saved_read(p)
        analysis.read_csv=missing
        try:
            with redirect_stdout(io.StringIO()):analysis.analyze(scratch/'analysis_invalid')
        finally:analysis.read_csv=saved_read
        replayed=json.loads((scratch/'analysis_invalid/replay.json').read_text());assert sum(s['integrity_status']=='VALID' for s in replayed)==11
    finally:analysis.OUT,analysis.PLAN,analysis.load_plan=saved
    checks.append('12-run analyzer roundtrip + missing-run preservation; per-stream/repeat mean/sampleSD, source renormalization, baseline comparison and hash checks')
    return dict(status='PASS',checks=checks,provenance='SYNTHETIC_CPU_VALIDATION_NOT_MEASUREMENT',
        GPU_executed=False,network_executed=False,frequency_accessed=False,scratch_path=str(scratch))


if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--output',required=True,type=Path);a=ap.parse_args()
    if a.output.exists():raise RuntimeError('No verification overwrite')
    result=verify()
    with a.output.open('x') as f:json.dump(result,f,indent=2);f.write('\n')
    print(json.dumps(result,indent=2))
