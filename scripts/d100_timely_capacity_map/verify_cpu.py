#!/usr/bin/env python3
"""CPU fixtures and fragmented memory transport only; no hardware experiment."""
import argparse
import ast
import copy
import csv
from contextlib import redirect_stdout
import gzip
import importlib.util
import inspect
import io
import json
from pathlib import Path
import socket
import sys
import tempfile
import threading
import time
import numpy as np
import map_common as common
from map_common import ROOT,sha,EdgeLink,hello,canonical,prior
import run_map_d100 as run
import analyze_map_d100 as analysis
from formal_cpu_verify import pair


def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec)
    sys.modules[name]=m;spec.loader.exec_module(m);return m


old=module('pruning_CPU_fixtures',ROOT/'scripts/expired_work_pruning/verify_cpu.py')
pruning_edge=module('pruning_edge_server',ROOT/'scripts/expired_work_pruning/edge_server.py')
edge=module('D100_CPU_edge',Path(__file__).with_name('edge_server.py'))
build_plan=module('D100_CPU_prepare',Path(__file__).with_name('prepare.py')).build_plan


def fixture(c):
    m,rows,power=old.fixture(c)
    if not c['edge_r']:
        m.update(edge_usage='NOT_USED',edge_ready={'status':'NOT_USED_NO_CONNECTION'},edge_final={'status':'NOT_USED'})
    return m,rows,power


def verify():
    plan=build_plan();checks=[];fixtures={};results=[]
    assert len(plan['order'])==18 and len(edge.conditions(plan))==9
    wrong=copy.deepcopy(plan);wrong['order'][0],wrong['order'][1]=wrong['order'][1],wrong['order'][0]
    try:edge.conditions(wrong)
    except ValueError:pass
    else:raise AssertionError('Changed frozen order accepted')
    for c in plan['order']:
        m,rows,power=fixture(c);s=analysis.summarize(m,rows,power)
        assert s['integrity_status']=='VALID',s['errors']
        assert s['source_frames']==14400 and s['admitted_frames']==60*c['target_service_FPS']
        assert s['decode_ready_FPS']==s['resize_ready_FPS']==240
        assert (s['local_assigned_FPS'],s['edge_assigned_FPS'])==(8*c['local_r'],8*c['edge_r'])
        assert s['admitted_frames']==s['completed_frames']+s['expired_dropped_frames']
        assert s['unfinished_after_drain']==0 and s['backlog_after_drain']==s['expired_dropped_frames']
        assert s['TIR_source']==s['timely_completed_frames']/14400
        assert s['worst_stream_TIR']==s['worst_stream_timely_FPS']/30
        assert all(r['TIR_source']==r['timely_completed_frames']/1800 for r in s['per_stream'])
        assert s['active_concurrency_peak']<=2 and s['VIN_active_energy_J']==4800
        assert s['VIN_J_per_timely_frame']==4800/s['timely_completed_frames']
        if c['supply_mode']=='A':
            assert s['edge_usage']=='NOT_USED' and s['edge_active_completed_FPS']==0
            assert all(v is None for v in s['edge_E2E_ms'].values())
        s.update(c);results.append(s);fixtures[c['cell']]=(m,rows,power)
    pairs,streams=analysis.paired(results)
    assert len(pairs)==9 and len(streams)==72 and all(p['integrity_status']=='VALID' and p['admitted_IDs_identical'] for p in pairs)
    for p in pairs:
        rr=[s for s in streams if s['repeat']==p['repeat'] and s['target_service_FPS']==p['target_service_FPS']]
        assert abs(sum(s['delta_timely_FPS'] for s in rr)-p['delta_timely_FPS'])<1e-9
    checks.append('18 full60s fixtures: same A/B source/admitted identities,240FPS frontend, correct splits, physical source TIR, B/U expiry separation, all stream/paired metrics and activeVIN integration')
    for cell in fixtures:
        for fault in ('missing_completion','early_expiry','deadline','due','mode','cap','power','edge_usage'):
            m,rows,power=copy.deepcopy(fixtures[cell])
            if fault=='missing_completion':next(r for r in rows if r.get('terminal_state')=='COMPLETED').pop('completion_timestamp_ns')
            if fault=='early_expiry':
                r=next(r for r in rows if r.get('terminal_state')=='EXPIRED_DROP');r['expired_drop_ns']=r['expiry_check_ns']=r['absolute_deadline_ns']-1
            if fault=='deadline':m['deadline_ms']=150
            if fault=='due':next(r for r in rows if r.get('phase')=='active')['logical_arrival_ns']+=1
            if fault=='mode':m['supply_mode']='A' if m['supply_mode']=='B' else 'B'
            if fault=='cap':m['queue_cap_saturation']=True
            if fault=='power':power=[]
            if fault=='edge_usage':
                if cell.endswith('A'):m['edge_ready']={'status':'CONNECTED'}
                else:m['edge_final']['expired_request_ids']=[]
            assert analysis.summarize(m,rows,power)['integrity_status']=='INVALID',(cell,fault)
    changed=copy.deepcopy(results);changed[0]['admitted_identity_sha256']='CPU_CHANGED_ID'
    pp,_=analysis.paired(changed);assert pp[0]['integrity_status']=='INVALID'
    checks.append('All6cells reject corrupted completion/expiry/deadline/due/placement/cap/power; A connection and B expiry-ledger rejection; paired identity mismatch fails closed')
    def vv(ds,ws):
        return analysis.verdict([dict(integrity_status='VALID',delta_timely_FPS=d,delta_worst_stream_timely_FPS=w) for d,w in zip(ds,ws)])
    assert vv([1]*3,[1]*3)=='HYBRID_TIMELY_CAPACITY_GAIN'
    assert vv([-1]*3,[-1]*3)=='LOCAL_BETTER'
    assert vv([0]*3,[0]*3)=='NO_EDGE_TIMELY_GAIN'
    assert vv([-1,0,-1],[-1,0,-1])=='NO_EDGE_TIMELY_GAIN'
    for ds,ws in [([1,-1,1],[1,-1,1]),([1]*3,[-1]*3),([1]*3,[0]*3)]:assert vv(ds,ws)=='INCONCLUSIVE'
    assert analysis.verdict([])=='INCONCLUSIVE'
    def nested(s):return {n.name:ast.dump(n,include_attributes=False) for n in ast.walk(ast.parse(s)) if isinstance(n,ast.FunctionDef)}
    old_ast,new_ast=nested(common.proven_runner.adapted_source()),nested(run.adapted_source())
    for name in ('infer','front','arrivals','sample_tensor','monitor','checkpoint','save_records'):assert old_ast[name]==new_ast[name],name
    assert common.ActiveEdgeLink.sender is common.pruning.EdgeLink.sender
    assert common.ActiveEdgeLink.receiver is common.pruning.EdgeLink.receiver
    assert edge.ns['serve_session'] is pruning_edge.serve_session and edge.ns['Backend'] is pruning_edge.Backend
    worker,finalizer=run.bindings()
    assert worker.__globals__['OUT']==common.OUT and worker.__globals__['EXECUTION_PLAN']==common.PLAN
    checks.append('All verdict branches/sign conflicts/ties; Local worker/pruning/frontend/telemetry AST and Edge sender/receiver/inference/session implementation unchanged')
    scratch=Path(tempfile.mkdtemp(prefix='D100_map_CPU_'))
    payloads,_=prior.old.edge_runtime.load_cache(ROOT/'results/edge_raw_capacity_gate/raw/semantic_raw640_30.npz')
    class MockBackend:
        def __init__(self):self.payloads=payloads
        def process(self,raw):
            stamps={k:time.monotonic_ns() for k in ('preprocess_start_ns','preprocess_end_ns','inference_start_ns','inference_end_ns','response_ready_ns')}
            return stamps,prior.old.wire.encode_outputs(dict(pred_logits=np.zeros((1,300,7),np.float32),pred_boxes=np.zeros((1,300,4),np.float32)))
        def info(self):return dict(C_E=1,B=1,CUDA_Graph=False,dynamic_batching=False,
            engine_sha256=prior.old.edge_runtime.ENGINE_SHA256,cache_sha256=prior.old.edge_runtime.CACHE_SHA256,
            color_conversion='numpy_channel_reverse_BGR_to_RGB',provenance='CPU_MOCK_NOT_MEASUREMENT')
        def close(self):pass
    saved_connect=socket.create_connection
    def forbidden(*args,**kwargs):raise AssertionError('Real socket forbidden')
    socket.create_connection=forbidden
    try:
        for c in plan['order']:
            if not c['edge_r']:
                m={};errors=[];link=EdgeLink(c,c['run_id'],m,scratch,errors.append,'CPU_PLAN','unused')
                link.finish();link.close();assert m['edge_usage']=='NOT_USED' and not errors
        for planned in [c for c in plan['order'] if c['repeat']==1 and c['edge_r']]:
            c=dict(planned,seconds=1);d=scratch/c['cell'];d.mkdir();(d/'thor').mkdir()
            client,server=pair();client.close=lambda:client.shutdown(0);server.close=lambda:server.shutdown(0)
            expected=hello(c,c['run_id'],'CPU_PLAN');done=[];errors=[];m={}
            thread=threading.Thread(target=lambda:done.append(pruning_edge.serve_session(server,d/'edge',expected,MockBackend)),daemon=True)
            thread.start();link=EdgeLink(c,c['run_id'],m,d/'thor',errors.append,'CPU_PLAN','unused',transport=client)
            now=time.monotonic_ns();jobs=[];n=8*c['edge_r']
            for rid in reversed(range(n)):
                r=dict(edge_request_id=rid,edge_release_target_ns=now-10**9,
                    absolute_deadline_ns=now-1 if rid%3==0 else now+60*10**9)
                link.put(r,payloads[rid%len(payloads)]);jobs.append(r)
            link.finish();assert link.done.wait(10);link.close();thread.join(10)
            assert not thread.is_alive() and not errors and done[0]['integrity_status']=='VALID',errors
            assert done[0]['received']==sum(r.get('terminal_state')=='COMPLETED' for r in jobs)
    finally:socket.create_connection=saved_connect
    checks.append('Nine A sessions cannot connect; all3 Hybrid cells use new HELLO plus proven fragmented memory-wire pruning/drain, cached realRAW/mock inference only')
    replay=scratch/'replay';replay.mkdir();planfile=scratch/'plan.json';planfile.write_text(json.dumps(plan))
    pre=replay/'frequency_preflight.json';pre.write_text(json.dumps(dict(status='PASS',plan_sha256=sha(planfile),provenance='CPU_MOCK')))
    saved=analysis.OUT,analysis.PLAN,analysis.load_plan
    analysis.OUT,analysis.PLAN,analysis.load_plan=replay,planfile,lambda:plan
    try:
        for c in plan['order']:
            m,rows,power=fixture(c);d=replay/c['run_id'];d.mkdir()
            m.update(execution_manifest_sha256=sha(planfile),child_returncode=0,PROCESS_LIFECYCLE='PASS',status_finalized=True,
                frequency_restore_ok=True,active_phase_completed=True,drain_completed=True,cleanup_started=True,cleanup_completed=True,
                frequency_preflight={'sha256':sha(pre)},pin_readback_Hz=dict(min_freq=1575000000,max_freq=1575000000))
            (d/'manifest.json').write_text(json.dumps(m));(d/'summary.json').write_text(json.dumps(analysis.summarize(m,rows,power)))
            for name,data in [('per_frame',rows),('power_trace',power)]:
                fields=list(dict.fromkeys(k for r in data for k in r))
                with gzip.open(d/(name+'.csv.gz'),'wt',newline='') as f:
                    w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(data)
        with redirect_stdout(io.StringIO()):analysis.analyze(scratch/'analysis_valid')
        verified=json.loads((scratch/'analysis_valid/verification.json').read_text());assert verified['valid']==18
        with (scratch/'analysis_valid/per_stream_metrics.csv').open() as f:assert len(list(csv.DictReader(f)))==144
        with (scratch/'analysis_valid/paired_stream_comparison.csv').open() as f:assert len(list(csv.DictReader(f)))==72
        saved_read=analysis.read_csv
        def missing(p):
            if Path(p).parent.name==plan['order'][0]['run_id']:raise FileNotFoundError('CPU injected missing trace, no file removed')
            return saved_read(p)
        analysis.read_csv=missing
        try:
            with redirect_stdout(io.StringIO()):analysis.analyze(scratch/'analysis_invalid')
        finally:analysis.read_csv=saved_read
        assert json.loads((scratch/'analysis_invalid/verification.json').read_text())['valid']==17
        with (scratch/'analysis_invalid/paired_comparison.csv').open() as f:
            pp=list(csv.DictReader(f));assert len(pp)==9 and sum(p['integrity_status']=='INVALID' for p in pp)==1
    finally:analysis.OUT,analysis.PLAN,analysis.load_plan=saved
    checks.append('Full18-run gzip/JSON/CSV raw replay,144stream and72pairedstreamrows; condition/sampleSD, invalid/missing pair retention; no historical pooling')
    return dict(status='PASS',checks=checks,provenance='SYNTHETIC_CPU_VALIDATION_NOT_MEASUREMENT',
        GPU_executed=False,network_executed=False,frequency_accessed=False,scratch_path=str(scratch))


if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,required=True);a=ap.parse_args()
    if a.output.exists():raise RuntimeError('No verification overwrite')
    result=verify()
    with a.output.open('x') as f:json.dump(result,f,indent=2);f.write('\n')
    print(json.dumps(result,indent=2))
