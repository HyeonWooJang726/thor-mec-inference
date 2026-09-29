#!/usr/bin/env python3
"""CPU fixtures only: no CUDA, network sockets, clock control or inference measurement."""
import argparse
import ast
import copy
import csv
import gzip
from contextlib import contextmanager
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
from timely_common import ROOT, DEADLINES, prior, equal, decorate, schedule, load_plan, hello, EdgeLink, proven_runner
import run_timely as run
import analyze_timely as analysis
import verify_cpu as existing_verify
from formal_cpu_verify import pair
from formal_server import serve_session

# Executing this script as __main__ imports frozen Equal-Service verify_cpu above.
fixture=types.FunctionType(existing_verify.fixture.__code__,dict(existing_verify.fixture.__globals__,decorate=decorate))


def verify():
    plan=load_plan();checks=[];fixtures={};masks={};summaries=[]
    spec=importlib.util.spec_from_file_location('canonical_timely_edge_launcher',Path(__file__).with_name('edge_server.py'))
    edge=importlib.util.module_from_spec(spec);spec.loader.exec_module(edge)
    assert len(edge.conditions(plan))==9
    malformed=copy.deepcopy(plan);malformed['order'][0],malformed['order'][1]=malformed['order'][1],malformed['order'][0]
    try:edge.conditions(malformed)
    except RuntimeError:pass
    else:raise AssertionError('Changed order accepted')
    for c in plan['order']:
        m,rows,power=fixture(c);s=analysis.summarize(m,rows,power)
        assert s['integrity_status']=='VALID',s['errors']
        assert s['source_frames']==14400 and s['decode_ready_FPS']==s['resize_ready_FPS']==240
        assert (s['local_assigned_FPS'],s['edge_assigned_FPS'],s['total_offered_FPS'])==(8*c['local_r'],8*c['edge_r'],c['target_service_FPS'])
        assert s['admission_skipped_frames']==14400-60*c['target_service_FPS']
        assert s['queue_stable'] and s['backlog_after_drain']==0 and s['active_concurrency_peak']<=2
        assert s['backlogs']['H']['regression_start_ns']==m['active_start_ns']+30*10**9
        assert abs(s['g_B_H']-s['g_B_L']-s['g_B_E'])<1e-9
        assert s['hardware_status']=='PROTECTION_LIMITED' and s['device_avg_power_W']==80
        assert s['E_device_J']==4800
        assert all(x['terminal_placement_gap']==0 for x in s['per_stream'])
        mask={(int(r['stream_id']),int(r['frame_id'])) for r in rows if r.get('admitted')}
        target=c['target_service_FPS'];assert mask==masks.setdefault(target,mask)
        for sid in range(8):
            assert sum(sid==sid0 for sid0,_ in mask)==60*target//8
            for path,rate in [('LOCAL',c['local_r']),('EDGE',c['edge_r'])]:
                assert sum(r.get('stream_id')==sid and r.get('placement')==path for r in rows)==60*rate
        for d in s['deadlines']:
            hit=sum(int(r['completion_timestamp_ns'])-int(r['logical_arrival_ns'])<=d['deadline_ms']*10**6
                    for r in rows if r.get('admitted'))
            assert d['on_time_frames']==hit and d['admitted_frames']==target*60
            assert d['late_frames']+hit==target*60 and d['missing_frames']==0
            assert d['timely_FPS']+d['late_FPS']==target
            assert d['TIR']==hit/(target*60)
            assert d['VIN_J_per_timely_frame']==4800/hit
            sr=[x for x in s['stream_deadlines'] if x['deadline_ms']==d['deadline_ms']]
            assert sum(x['on_time_frames'] for x in sr)==hit
            assert min(x['TIR'] for x in sr)==d['worst_stream_TIR']
        erows=[r for r in rows if r.get('placement')=='EDGE'];rate=8*c['edge_r']
        if rate:
            assert sorted(r['edge_request_id'] for r in erows)==list(range(rate*60))
            releases=sorted(r['edge_release_target_ns'] for r in erows)
            assert set(b-a for a,b in zip(releases,releases[1:]))=={10**9//rate}
        else:assert all(x is None for x in s['edge_inference_ms'].values())
        fixtures[c['cell']]=(m,rows,power);s.update(c);summaries.append(s)
    for target in (160,200):
        for mode in ('A','B'):assert schedule(target,mode)==equal.schedule(target,mode)
    checks.append('18 full60s fixtures: zero-phase30FPS,14400decode/resize, exact160/200/240 admission, matching A/B IDs, per-stream quotas, exclusion/drain, LocalC2, final30OLS, additive backlog, OC3 annotation, unchanged160/200 placement')
    # Exact deadline boundary, one-ns late, missing, and completion in drain.
    cohort=[dict(arrival=0,completion=40_000_000),dict(arrival=0,completion=40_000_001),
            dict(arrival=59_990_000_000,completion=60_020_000_000),dict(arrival=0,completion=None)]
    d=analysis.deadline_metrics(cohort,60,40,4800)
    assert (d['on_time_frames'],d['late_frames'],d['missing_frames'],d['TIR'])==(2,1,1,.5)
    assert d['VIN_J_per_timely_frame']==2400
    assert analysis.deadline_metrics([],60,40,4800)['VIN_J_per_timely_frame'] is None
    assert analysis.deadline_metrics(cohort,60,40,None)['VIN_timely_energy_status']=='VIN_UNAVAILABLE'
    # Stable-but-late and valid-unstable remain descriptive, without a timely-good label.
    m,rows,power=copy.deepcopy(fixtures['T240-A'])
    for r in rows:
        if r.get('placement')=='LOCAL':
            r['inference_start_timestamp_ns']+=300_000_000
            r['completion_timestamp_ns']+=300_000_000
    s=analysis.summarize(m,rows,power)
    assert s['integrity_status']=='VALID' and s['queue_stable']
    assert all(d['on_time_frames']==0 and d['VIN_J_per_timely_frame'] is None for d in s['deadlines'])
    for r in rows:
        if r.get('placement')=='LOCAL':
            shift=(r['logical_arrival_ns']-m['active_start_ns'])//10
            r['inference_start_timestamp_ns']+=shift;r['completion_timestamp_ns']+=shift
    s=analysis.summarize(m,rows,power)
    assert s['integrity_status']=='VALID' and not s['queue_stable'] and s['backlog_after_drain']==0
    checks.append('inclusive integer-ns deadlines; drain counted; late/missing separate; zero-timely or absentVIN=>N/A; stable-but-late and valid-unstable never reclassified as timely-good')
    for cell in fixtures:
        for fault in ('completion','admission','due','edge_response','cap','power'):
            if fault=='edge_response' and cell.endswith('A'):continue
            m,rows,power=copy.deepcopy(fixtures[cell]);r=next(r for r in rows if r.get('placement')==('EDGE' if fault=='edge_response' else 'LOCAL'))
            if fault=='completion':r.pop('completion_timestamp_ns')
            if fault=='admission':r['admitted']=0
            if fault=='due':r['logical_arrival_ns']+=1
            if fault=='edge_response':r['response_completion_ns']+=1
            if fault=='cap':m['queue_cap_saturation']=True
            if fault=='power':power=[]
            assert analysis.summarize(m,rows,power)['integrity_status']=='INVALID',(cell,fault)
    m,rows,power=copy.deepcopy(fixtures['T160-A'])
    for r in power:r['raw_tegrastats']=r['raw_tegrastats'].replace(' VIN ',' MISSING_VIN ')
    s=analysis.summarize(m,rows,power)
    assert s['integrity_status']=='VALID' and s['E_device_J'] is None
    assert all(d['VIN_J_per_timely_frame'] is None for d in s['deadlines'])
    checks.append('all6conditions reject completion/admission/due/response/cap/missingGPUtrace corruption; missingVIN remains explicit unavailable')
    all_deadlines=[dict(cell=s['cell'],repeat=s['repeat'],integrity_status='VALID',**d) for s in summaries for d in s['deadlines']]
    assert len(analysis.comparisons(all_deadlines))==9*3*6*6
    stats=analysis.aggregate([dict(cell='CPU',repeat=i,integrity_status='VALID',value=i) for i in (1,2,3)],['cell'])
    assert stats[0]['mean']==2 and stats[0]['sample_SD']==1
    def nested(src):return {n.name:ast.dump(n,include_attributes=False) for n in ast.walk(ast.parse(src)) if isinstance(n,ast.FunctionDef)}
    before,after=nested(proven_runner.adapted_source()),nested(run.adapted_source())
    for name in ('infer','front','arrivals','sample_tensor','monitor','checkpoint','save_records'):
        assert before[name]==after[name],name
    run.bindings()
    checks.append('Local/decode/resize/pacing/telemetry/lifecycle nested AST identical to Equal-Service; pairing and sampleSD aggregation verified')
    scratch=Path(tempfile.mkdtemp(prefix='canonical_timely_CPU_'))
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
    def forbidden(*a,**kw):raise AssertionError('CPU validation attempted real network')
    socket.create_connection=forbidden
    try:
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
    checks.append('nine A sessions never connect; nine fragmented memory-wire B sessions with cached realRAW and mock inference; correct HELLO/16or40requests/drain; no network')
    original_frequency,original_preflight=run.frequency,run.PREFLIGHT
    class FakeFrequency:
        def __init__(self,fault):self.fault=fault;self.state=(315000000,1575000000);self.pins=0;self.legacy=self
        def inspect(self):return {'provenance':'CPU_FAKE'}
        def validate_target(self,mhz):
            assert mhz==1575
            if self.fault=='unsupported':raise ValueError('CPU_FAKE unsupported')
        def require_control(self):
            if self.fault=='permission':raise PermissionError('CPU_FAKE permission')
        def read_range(self):return dict(min_freq=self.state[0],max_freq=self.state[1],cur_freq=0)
        @contextmanager
        def pinned(self,mhz):
            assert mhz==1575;self.pins+=1
            if self.fault!='pin':self.state=(1575000000,1575000000)
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
    finally:run.frequency,run.PREFLIGHT=original_frequency,original_preflight
    checks.append('mock-only1575pin/315-1575restore; permission/support/pin/restore failures block; no real clock access')
    # Full analyzer CSV/JSON round trip, including invalid/missing run retention.
    replay=scratch/'replay_fixture';replay.mkdir()
    previous_out,previous_plan,previous_load=analysis.OUT,analysis.PLAN,analysis.load_plan
    try:
        analysis.OUT=replay;analysis.PLAN=run.PLAN;analysis.load_plan=lambda:plan
        pre=dict(status='PASS',plan_sha256=analysis.sha(run.PLAN),provenance='CPU_FIXTURE')
        (replay/'frequency_preflight.json').write_text(json.dumps(pre))
        for c in plan['order']:
            m,rows,power=copy.deepcopy(fixtures[c['cell']]);m.update(c)
            m.update(requested_freq_MHz=1575,execution_manifest_sha256=analysis.sha(run.PLAN),
                child_returncode=0,PROCESS_LIFECYCLE='PASS',status_finalized=True,
                active_phase_completed=True,drain_completed=True,cleanup_started=True,
                cleanup_completed=True,frequency_restore_ok=True,
                frequency_preflight={'sha256':analysis.sha(replay/'frequency_preflight.json')},
                pin_readback_Hz=dict(min_freq=1575000000,max_freq=1575000000))
            d=replay/c['run_id'];d.mkdir()
            (d/'manifest.json').write_text(json.dumps(m))
            (d/'summary.json').write_text(json.dumps(analysis.summarize(m,rows,power)))
            for name,data in [('per_frame',rows),('power_trace',power)]:
                fields=list(dict.fromkeys(k for row in data for k in row))
                with gzip.open(d/(name+'.csv.gz'),'wt',newline='') as f:
                    writer=csv.DictWriter(f,fieldnames=fields);writer.writeheader();writer.writerows(data)
        analysis.analyze(scratch/'replay_valid')
        v=json.loads((scratch/'replay_valid/verification.json').read_text());assert v['valid']==18
        with (scratch/'replay_valid/per_run_deadlines.csv').open() as f:assert len(list(csv.DictReader(f)))==108
        with (scratch/'replay_valid/per_stream_deadlines.csv').open() as f:assert len(list(csv.DictReader(f)))==864
        # Model missing run without deleting anything; failed-run raw stays intact.
        first=plan['order'][0]['run_id'];last=plan['order'][-1]['run_id']
        saved_verify=analysis.verify_lifecycle;saved_read=analysis.read_csv
        def failed(m,c):
            if c['run_id']==first:raise ValueError('CPU injected lifecycle failure')
            return saved_verify(m,c)
        def missing(path):
            if Path(path).parent.name==last:raise FileNotFoundError('CPU injected missing trace')
            return saved_read(path)
        analysis.verify_lifecycle=failed;analysis.read_csv=missing
        try:analysis.analyze(scratch/'replay_invalid')
        finally:analysis.verify_lifecycle=saved_verify;analysis.read_csv=saved_read
        bad=json.loads((scratch/'replay_invalid/replay.json').read_text())
        assert len(bad)==18 and next(r for r in bad if r['run_id']==first)['integrity_status']=='INVALID'
        assert next(r for r in bad if r['run_id']==last)['integrity_status']=='INVALID'
        assert sum(r['integrity_status']=='VALID' for r in bad)==16
        with (scratch/'replay_invalid/per_run_deadlines.csv').open() as f:assert len(list(csv.DictReader(f)))==108
    finally:analysis.OUT,analysis.PLAN,analysis.load_plan=previous_out,previous_plan,previous_load
    checks.append('full analyzer18-run gzip/JSON/CSV roundtrip;108deadline/864streamrows; preservation, paired comparison, explicit invalid/missing retention and aggregate denominators')
    return dict(status='PASS',checks=checks,provenance='SYNTHETIC_CPU_VALIDATION_NOT_MEASUREMENT',
        GPU_executed=False,network_executed=False,frequency_accessed=False,scratch_path=str(scratch))


if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,required=True);args=ap.parse_args()
    if args.output.exists():raise RuntimeError('No validation overwrite')
    result=verify()
    with args.output.open('x') as f:json.dump(result,f,indent=2);f.write('\n')
    print(json.dumps(result,indent=2))
