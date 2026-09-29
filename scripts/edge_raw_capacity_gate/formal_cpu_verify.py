#!/usr/bin/env python3
"""CPU fixtures only. No sockets, GPU, or measured performance claims.

Actual frozen Warehouse bytes exercise framing. Explicitly synthetic output
arrays stand in for inference solely to verify protocol/lifecycle accounting.
Fixture raw files stay in a new /tmp directory and are NOT experiment evidence.
"""
import argparse
import copy
import csv
import json
from pathlib import Path
import tempfile
import threading
import time

import numpy as np
import formal_protocol as p
from formal_analyzer import backlog, summarize
from formal_client import baseline, run_session
from formal_server import serve_session


class MemoryTransport:
    """Fragmented full-duplex byte stream with no OS socket/network access."""
    def __init__(self):
        self.cv = threading.Condition()
        self.data = bytearray()
        self.closed = False
        self.peer = None
        self.reads = 0

    def sendall(self, data):
        # Deliberately split headers, metadata, arrays, and raw images.
        for left in range(0, len(data), 4093):
            with self.peer.cv:
                if self.peer.closed:
                    raise EOFError('memory transport closed')
                self.peer.data.extend(data[left:left+4093])
                self.peer.cv.notify_all()

    def recv(self, size):
        with self.cv:
            if not self.cv.wait_for(lambda: self.data or self.closed, timeout=10):
                raise TimeoutError('CPU fixture hang')
            if not self.data:
                return b''
            self.reads += 1
            n = min(size, len(self.data), 7 if self.reads % 5 == 0 else 2039)
            value = bytes(self.data[:n])
            del self.data[:n]
            return value

    def shutdown(self, _):
        for side in (self, self.peer):
            with side.cv:
                side.closed = True
                side.cv.notify_all()


def pair():
    a, b = MemoryTransport(), MemoryTransport()
    a.peer, b.peer = b, a
    return a, b


def verify(root):
    h = p.load_runtime_helpers()
    payloads, ids = h.load_cache(root/'results/edge_raw_capacity_gate/raw/semantic_raw640_30.npz')
    checks = []
    a, b = pair()
    p.send_message(a, p.REQUEST, 13, payload=payloads[0])
    p.send_message(a, p.END, metadata={'submitted':1})
    kind, rid, _, raw = p.recv_message(b)
    assert kind==p.REQUEST and rid==13 and raw==payloads[0]
    assert p.recv_message(b)[0]==p.END
    checks.append('partial reads / coalesced messages / real RAW640 exact bytes')
    a, b = pair()
    a.sendall(p.HEADER.pack(p.MAGIC,p.REQUEST,0,2,p.RAW_BYTES)+b'{}'+b'x')
    a.shutdown(0)
    try:
        p.recv_message(b)
        raise AssertionError('truncated payload accepted')
    except EOFError:
        pass
    for kind, size in [(p.REQUEST, 4), (p.RESPONSE, p.RAW_BYTES), (p.END, 1)]:
        try:
            p.validate_sizes(kind, 2, size)
            raise AssertionError('bad frame accepted')
        except ValueError:
            pass
    checks.append('EOF / malformed length rejection')

    class FixtureBackend:
        closed = False
        calls = 0
        def __init__(self):
            self.payloads = payloads
        def process(self, raw):
            assert raw in payloads
            FixtureBackend.calls += 1
            if FixtureBackend.calls > 50:
                # Deliberate CPU-only delay tests >1 in-flight request without any GPU.
                time.sleep(0.3)
            # Synthetic output values are fixtures, NEVER RT-DETR measurements.
            output = dict(pred_logits=np.full((1,300,7),0.25,np.float32),
                          pred_boxes=np.full((1,300,4),0.5,np.float32))
            stamps = {key: time.monotonic_ns() for key in
                      ('preprocess_start_ns','preprocess_end_ns','inference_start_ns',
                       'inference_end_ns','response_ready_ns')}
            return stamps, p.encode_outputs(output)
        def info(self):
            return dict(C_E=1,B=1,CUDA_Graph=False,dynamic_batching=False,
                        engine_sha256=h.ENGINE_SHA256, cache_sha256=h.CACHE_SHA256,
                        opencv_required=False,color_conversion='numpy_channel_reverse_BGR_to_RGB',
                        provenance='SYNTHETIC_CPU_TEST_DOUBLE_NOT_GPU_MEASUREMENT')
        def close(self):
            FixtureBackend.closed=True

    temp = Path(tempfile.mkdtemp(prefix='raw640_formal_CPU_ONLY_'))
    hello = dict(mode='cpu_fixture',rate=4,seconds=1,repeat=0,run_id='CPU_ONLY',cache_sha256=h.CACHE_SHA256)
    a, b = pair()
    server_results = []
    thread = threading.Thread(target=lambda: server_results.append(
        serve_session(b,temp/'server',hello,FixtureBackend)))
    thread.start()
    result = run_session(a,temp/'client',hello,payloads,ids,
                         baseline(root/'results/edge_raw_capacity_gate/tcp_sender.csv'))
    thread.join(timeout=10)
    assert not thread.is_alive()
    assert result['integrity_status']=='VALID', result
    assert result['stage_counts']==dict(logically_admitted=4,payload_ready=4,submitted=4,
                                        Edge_received=4,Edge_completed=4,Thor_completed=4)
    assert FixtureBackend.calls==54 and FixtureBackend.closed
    assert server_results[0]['cleanup_completed'] and server_results[0]['worker_thread_exited']
    assert (temp/'client/responses.bin').stat().st_size==4*(8+p.OUTPUT_BYTES)
    assert result['after_drain_backlog']==0
    checks.append('producer/sender/receiver + server worker + 50 mock warmups + FINAL after cleanup')

    origin=1_000_000_000_000
    schedule=p.arrivals(origin,40,60)
    assert len(schedule)==2400 and schedule[-1]==origin+59_975_000_000
    # Logical count does not depend on any payload preparation or submission event.
    divergent=[dict(logical_arrival_ns=origin+i*1_000_000_000) for i in range(60)]
    bg=backlog(divergent,origin,origin+60_000_000_000,30)
    assert abs(bg['g_B_E']-(1-1/900))<1e-10
    assert bg['active_end_backlog']==60 and bg['after_drain_backlog']==60
    drained=[dict(r,response_completion_ns=origin+61_000_000_000) for r in divergent]
    dg=backlog(drained,origin,origin+60_000_000_000,30)
    assert dg['g_B_E']==bg['g_B_E'] and dg['after_drain_backlog']==0
    constant=[dict(logical_arrival_ns=origin,response_completion_ns=origin+61_000_000_000)]
    assert abs(backlog(constant,origin,origin+60_000_000_000,30)['g_B_E'])<1e-10
    checks.append('exact OLS / logical backlog includes unsent requests / drain excluded / frozen 2400-event timeline')
    manifest=json.loads((temp/'client/manifest.json').read_text())
    final=json.loads((temp/'client/server_final.json').read_text())
    with (temp/'client/requests.csv').open() as f:
        records=list(csv.DictReader(f))
    for row in records:
        for key in list(row):
            if key.endswith('_ns') or key in ('request_id','sample_id'):
                row[key]=int(row[key]) if row[key] else None
    assert records[1]['socket_submission_ns'] < records[0]['response_completion_ns']
    checks.append('multiple requests in flight despite delayed fixture responses')
    for change in ('duplicate','missing','clock_corruption','cap','cleanup'):
        m,r,f=copy.deepcopy(manifest),copy.deepcopy(records),copy.deepcopy(final)
        if change=='duplicate': m['duplicate_responses']=1
        if change=='missing': r[0]['response_completion_ns']=None
        if change=='clock_corruption': r[0]['inference_end_ns']=r[0]['inference_start_ns']-1
        if change=='cap': f['queue_cap_saturation']=True
        if change=='cleanup': f['cleanup_completed']=False
        s=summarize(m,r,f,[])
        assert s['stability']!='STABLE',change
    shifted=copy.deepcopy(records)
    from formal_analyzer import EDGE_KEYS
    for row in shifted:
        for key in EDGE_KEYS: row[key]+=10**18
    s=summarize(manifest,shifted,final,[])
    assert s['latency_ms']==result['latency_ms'] and s['g_B_E']==result['g_B_E']
    checks.append('duplicate/missing/timestamp/cap/cleanup rejection; independent host-clock offsets')
    class FailingBackend(FixtureBackend):
        def __init__(self):
            super().__init__()
            self.local_calls=0
        def process(self,raw):
            self.local_calls+=1
            if self.local_calls>50:
                raise RuntimeError('INTENTIONAL CPU TEST worker failure; no GPU inference')
            # Keep fixture warmup fast; this is not performance measurement.
            old=FixtureBackend.calls
            FixtureBackend.calls=0
            try:
                return super().process(raw)
            finally:
                FixtureBackend.calls=old
    a,b=pair()
    failure_results=[]
    thread=threading.Thread(target=lambda:failure_results.append(
        serve_session(b,temp/'failure_server',hello,FailingBackend)))
    thread.start()
    failure=run_session(a,temp/'failure_client',hello,payloads,ids,
                        baseline(root/'results/edge_raw_capacity_gate/tcp_sender.csv'))
    thread.join(timeout=10)
    assert not thread.is_alive() and failure['integrity_status']=='INVALID'
    assert failure_results[0]['integrity_status']=='INVALID' and failure_results[0]['cleanup_completed']
    with (temp/'failure_server/requests.csv').open() as f:
        assert len(list(csv.DictReader(f)))>=1
    checks.append('worker failure -> INVALID, socket interruption, cleanup, received-request trace preservation')
    return dict(status='PASS', checks=checks, fixture_provenance='CPU_ONLY_SYNTHETIC_OUTPUTS_NOT_PERFORMANCE',
                scratch_path=str(temp), real_network_opened=False, GPU_inference_executed=False,
                smoke_executed=False, primary_executed=False, cache_sha256=h.CACHE_SHA256)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verification-output',required=True)
    args=parser.parse_args()
    result=verify(Path(__file__).resolve().parents[2])
    p.save(args.verification_output,result)
    print(json.dumps(result,indent=2))
