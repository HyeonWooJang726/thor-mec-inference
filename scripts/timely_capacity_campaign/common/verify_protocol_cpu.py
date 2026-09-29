"""Fragmented in-memory transport and decision-rule tests. No socket connections/GPU."""
import copy
import importlib.util
import json
from pathlib import Path
import socket
import tempfile
import threading
import time
import numpy as np
import campaign_config as cfg
import campaign_analysis as analysis
import edge_preflight
import run_campaign
from reuse import prior,pruning
from formal_cpu_verify import pair


def main():
    spec=importlib.util.spec_from_file_location('tcc_original_pruning_server',cfg.ROOT/'scripts/expired_work_pruning/edge_server.py')
    server=importlib.util.module_from_spec(spec);spec.loader.exec_module(server)
    payloads,_=prior.old.edge_runtime.load_cache(cfg.ROOT/'results/edge_raw_capacity_gate/raw/semantic_raw640_30.npz')
    class MockBackend:
        def __init__(self):self.payloads=payloads
        def process(self,raw):
            stamps={k:time.monotonic_ns() for k in ('preprocess_start_ns','preprocess_end_ns','inference_start_ns','inference_end_ns','response_ready_ns')}
            return stamps,prior.old.wire.encode_outputs(dict(pred_logits=np.zeros((1,300,7),np.float32),pred_boxes=np.zeros((1,300,4),np.float32)))
        def info(self):return dict(C_E=1,B=1,CUDA_Graph=False,dynamic_batching=False,
            engine_sha256=prior.old.edge_runtime.ENGINE_SHA256,cache_sha256=prior.old.edge_runtime.CACHE_SHA256,
            color_conversion='numpy_channel_reverse_BGR_to_RGB',provenance='CPU_MOCK_NOT_MEASUREMENT')
        def close(self):pass
    scratch=Path(tempfile.mkdtemp(prefix='tcc_protocol_CPU_'))
    ctx=run_campaign.Context('B',cfg.ROOT/'scripts/timely_capacity_campaign/block_b_split/run_block.py')
    original=socket.create_connection
    socket.create_connection=lambda *a,**k:(_ for _ in ()).throw(AssertionError('No real sockets'))
    try:
        for mode in ('none','some','all'):
            c=dict(next(c for c in cfg.expected_order('B') if c['edge_r']==10),seconds=1)
            d=scratch/mode;d.mkdir();(d/'thor').mkdir();client,wire=pair()
            client.close=lambda:client.shutdown(0);wire.close=lambda:wire.shutdown(0)
            done=[];errors=[];manifest={};expected=ctx.hello(c,c['run_id'],'CPU_ONLY')
            thread=threading.Thread(target=lambda:done.append(server.serve_session(wire,d/'edge',expected,MockBackend)),daemon=True)
            thread.start();link=ctx.edge_link(c,c['run_id'],manifest,d/'thor',errors.append,'CPU_ONLY','unused',transport=client)
            now=time.monotonic_ns();jobs=[]
            for rid in reversed(range(80)):
                expired=mode=='all' or mode=='some' and rid%3==0
                row=dict(edge_request_id=rid,logical_arrival_ns=now-1_000_000_000 if expired else now,
                    edge_release_target_ns=now-2_000_000_000,absolute_deadline_ns=now-1 if expired else now+60*10**9)
                jobs.append(row);link.put(row,payloads[rid%len(payloads)])
            link.finish();assert link.done.wait(15);link.close();thread.join(15)
            assert not thread.is_alive() and not errors and done[0]['integrity_status']=='VALID',errors
            drops=sum(r.get('terminal_state')=='EXPIRED_DROP' for r in jobs)
            assert done[0]['received']==80-drops and done[0]['client_expired_before_submission']==drops
            assert len({r['edge_request_id'] for r in jobs})==80
            assert all(not r.get('socket_submission_ns') for r in jobs if r.get('terminal_state')=='EXPIRED_DROP')
    finally:socket.create_connection=original
    # Frozen descriptive verdict branches; samples are synthetic, not measurements.
    a=[]
    for c in cfg.expected_order('A'):
        if c['target_service_FPS']!=184:continue
        a.append(dict(c,integrity_status='VALID',timely_FPS=101 if c['admission_pattern']=='STAGGERED' else 100,
            local_queue_ms={'p95':8 if c['admission_pattern']=='STAGGERED' else 10}))
    assert analysis.verdict_a(a)=='STAGGER_SUPPORTED'
    for r in a:
        if r['admission_pattern']=='STAGGERED':r['timely_FPS']=99
    assert analysis.verdict_a(a)=='ALIGNED_BETTER'
    for r in a:r['timely_FPS']=100;r['local_queue_ms']['p95']=10
    assert analysis.verdict_a(a)=='NO_EFFECT'
    a[0]['integrity_status']='INVALID';assert analysis.verdict_a(a)=='INCONCLUSIVE'
    b=[dict(c,integrity_status='VALID',timely_FPS=210 if c['local_r']==25 else 220,
        worst_stream_TIR=.9,path_timely={'EDGE':{'timely_ratio':.96}}) for c in cfg.expected_order('B')]
    assert analysis.verdict_b(b,240)=='SPLIT_BY_TIMELY_CAPACITY_SUPPORTED'
    b2=copy.deepcopy(b)
    for r in b2:
        if r['local_r']==25:r['timely_FPS']=230
    assert analysis.verdict_b(b2,240)=='REFERENCE_BEST'
    next(r for r in b2 if r['edge_r']==10)['path_timely']['EDGE']['timely_ratio']=.89
    assert analysis.verdict_b(b2,240)=='EDGE_PATH_LIMITED'
    b2[0]['integrity_status']='INVALID';assert analysis.verdict_b(b2,240)=='INCONCLUSIVE'
    for block in ('A','B'):
        with (cfg.out(block)/'protocol_and_gate_cpu_validation.json').open('x') as f:
            json.dump(dict(status='PASS',provenance='CPU_MOCK_NOT_MEASUREMENT',scratch=str(scratch),
                checks=['80-request fragmented memory transport; none/some/all expiration and complete drain','Frozen A/B gate branches, invalid precedence; 5-repeat B primary uses R1–R3'],
                GPU_executed=False,network_executed=False,frequency_control_executed=False),f,indent=2)
    print('PASS: memory-wire80, expiry partitions, gate branches')


if __name__=='__main__':main()
