#!/usr/bin/env python3
"""CPU-only adapter/accounting/fragmented in-memory transport validation."""
import argparse,ast,copy,hashlib,inspect,json,tempfile,threading,time
from pathlib import Path
import numpy as np
from pilot_common import ROOT,RATES,decorate,edge_slots,EdgeLink,hello,old,load_plan
from run_coupling_pilot import adapted_source,bindings
from analyze_coupling import summarize,flatten,aggregate_pairs,diagnostic_report
from verify_hybrid_cpu import synthetic_fixture
from formal_cpu_verify import pair
from formal_server import serve_session

def fixture(e,repeat=1):
    m,rows,power=synthetic_fixture();m.update(edge_r=e,kind='pilot',repeat=repeat)
    count=80*e
    if e:
        for k in ('received','completed','responses_sent'):m['edge_final'][k]=count
    else:m.update(edge_usage='NOT_USED',edge_final={'status':'NOT_USED'})
    for r in rows:
        if r['phase']!='active':continue
        decorate(r,m['active_start_ns'],e)
        if r['placement']=='SKIP':
            for k in list(r):
                if k in ('payload_ready_ns','ready_timestamp_ns','completion_timestamp_ns','socket_submission_ns','socket_send_complete_ns','response_completion_ns','raw_sha256','payload_sha256') or k.startswith('edge_'):r.pop(k,None)
    return m,rows,power

def verify():
    checks=[];models={};flat=[];plan=load_plan()
    assert [c['edge_r']*8 for c in plan['order']]==[0,8,16,24,40,40,24,16,8,0]
    for c in plan['order']:
        e=c['edge_r']
        rows=[decorate(dict(stream_id=s,frame_id=f,logical_arrival_ns=f*10**9//30),0,e) for f in range(300) for s in range(8)]
        local={(r['stream_id'],r['frame_id']) for r in rows if r['placement']=='LOCAL'};models[e]=local
        edge=[r for r in rows if r['placement']=='EDGE']
        assert len(local)==2000 and len(edge)==80*e
        assert sorted(r['edge_request_id'] for r in edge)==list(range(80*e))
        assert all(r['edge_release_target_ns']>=r['logical_arrival_ns'] for r in edge)
        for sid in range(8):
            assert sum(r['stream_id']==sid for r in edge)==10*e
            assert sum(r['stream_id']==sid and r['placement']=='SKIP' for r in rows)==10*(5-e)
        m,rows,power=fixture(e,c['repeat']);s=summarize(m,rows,power)
        assert s['integrity_status']=='VALID',s['errors']
        assert (s['local_assigned_FPS'],s['edge_assigned_FPS'],s['total_offered_FPS'])==(200,8*e,200+8*e)
        assert s['backlog_after_drain']==0 and s['decode_ready_FPS']==240 and s['resize_ready_FPS']==240
        assert s['admission_skipped_frames']==80*(5-e) and s['admitted_frames']==2000+80*e
        assert all(r['terminal_placement_gap']==0 for r in s['per_stream'])
        assert abs(s['g_B_H']-s['g_B_L']-s['g_B_E'])<1e-9
        assert s['repeat']==c['repeat']
        s.update(run_id=c['run_id'],pass_name=c['pass'],order_index=c['order_index'])
        flat.append(flatten(s))
        for corruption in ('missing_completion','wrong_admission','skip_serviced','wrong_edge_count','negative_timestamp','queue_cap'):
            mm,rr,pp=copy.deepcopy(m),copy.deepcopy(rows),copy.deepcopy(power)
            lr=next(r for r in rr if r.get('placement')=='LOCAL')
            if corruption=='missing_completion':lr.pop('completion_timestamp_ns')
            if corruption=='wrong_admission':lr['admitted']=0
            if corruption=='skip_serviced':
                sk=next((r for r in rr if r.get('placement')=='SKIP'),None)
                if sk is None:continue
                sk['completion_timestamp_ns']=sk['logical_arrival_ns']+1
            if corruption=='wrong_edge_count':
                if not e:continue
                mm['edge_final']['received']+=1
            if corruption=='negative_timestamp':lr['source_pulled_ns']=lr['logical_arrival_ns']-1
            if corruption=='queue_cap':mm['queue_cap_saturation']=True
            z=summarize(mm,rr,pp)
            assert z['integrity_status']=='INVALID',(e,corruption)
    assert all(m==models[0] for m in models.values())
    checks.append('ten 10-s A/B schedules: identical 2000 Local frame IDs; exact Edge/skip counts per stream; contiguous Edge IDs; no early release')
    checks.append('ten synthetic raw replays: repeat labels, B_H=B_L+B_E slopes/drain; E0 NOT_USED; skip separation; corruption rejection')
    # Known synthetic paired differences verify sample SD, invalid/missing handling.
    for r in flat:
        if r['pass_name']=='B':r['local_completed_FPS']+=2
    pairs=aggregate_pairs(flat)
    for r in pairs:
        if r['metric']=='local_completed_FPS':
            assert r['B_minus_A']==2 and abs(r['sample_SD']-2**.5)<1e-12 and r['mean']==r['A_value']+1
        if r['edge_FPS']==0 and r['metric'].startswith(('edge_client_pending_ms','edge_send_ms')):
            assert r['valid_n']==0 and r['mean'] is None and r['sample_SD'] is None
    badflat=copy.deepcopy(flat);badflat[0]['integrity_status']='INVALID'
    q=next(r for r in aggregate_pairs(badflat) if r['edge_FPS']==0 and r['metric']=='local_completed_FPS')
    assert q['valid_n']==1 and q['sample_SD'] is None and q['A_integrity']=='INVALID'
    report=diagnostic_report(flat,pairs)
    assert 'B−A' in report and 'OC3_delta' in report and 'A+B' in report
    checks.append('A/B values retained; mean/ddof=1 SD and paired deltas verified; invalid excluded visibly; E0 latency remains N/A; descriptive report generated in memory')
    before=ast.parse(inspect.getsource(__import__('run_hybrid').base.run_one));after=ast.parse(adapted_source())
    def nested(t,n):return next(x for x in ast.walk(t) if isinstance(x,ast.FunctionDef) and x.name==n)
    for name in ('infer','monitor','checkpoint','save_records'):
        assert ast.dump(nested(before,name))==ast.dump(nested(after,name)),name
    front=nested(after,'front')
    assert 'if True:' in ast.unparse(front) # common resize for skipped frames too
    bindings()
    checks.append('unchanged frozen Local infer/telemetry/checkpoint/raw writer; source-derived adapters compile')
    payloads,_=old.edge_runtime.load_cache(ROOT/'results/edge_raw_capacity_gate/raw/semantic_raw640_30.npz')
    tmp=Path(tempfile.mkdtemp(prefix='coupling_CPU_ONLY_'))
    # No real socket. Deliberately fragmented memory transports reuse frozen wire/parser.
    class MockBackend:
        def __init__(self):self.payloads=payloads
        def process(self,raw):
            keys=('preprocess_start_ns','preprocess_end_ns','inference_start_ns','inference_end_ns','response_ready_ns')
            stamps={k:time.monotonic_ns() for k in keys}
            return stamps,old.wire.encode_outputs(dict(pred_logits=np.zeros((1,300,7),np.float32),pred_boxes=np.zeros((1,300,4),np.float32)))
        def info(self):return dict(C_E=1,B=1,CUDA_Graph=False,dynamic_batching=False,engine_sha256=old.edge_runtime.ENGINE_SHA256,cache_sha256=old.edge_runtime.CACHE_SHA256,color_conversion='numpy_channel_reverse_BGR_to_RGB',provenance='CPU_FIXTURE_NO_INFERENCE')
        def close(self):pass
    for planned in plan['order']:
        e=planned['edge_r'];c=dict(planned,seconds=1)
        td=tmp/f"{c['pass']}_E{e}";td.mkdir();m={};errors=[]
        if not e:
            # Fail immediately if the zero-rate adapter attempts any connection.
            import socket
            original=socket.create_connection
            def forbidden(*a,**k):raise AssertionError('E0 connected')
            socket.create_connection=forbidden
            try:
                link=EdgeLink(c,'CPU_E0',m,td,errors.append,'CPU_PLAN','unused')
                link.finish();link.close();assert link.done.is_set() and m['edge_usage']=='NOT_USED'
            finally:socket.create_connection=original
            continue
        client,server=pair();client.close=lambda:client.shutdown(0);server.close=lambda:server.shutdown(0)
        rid='CPU_'+c['pass']+'_E'+str(e);expected=hello(c,rid,'CPU_PLAN');srv=[]
        assert expected['repeat']==(1 if c['pass']=='A' else 2)
        thread=threading.Thread(target=lambda:srv.append(serve_session(server,td/'edge',expected,MockBackend)))
        thread.start();(td/'thor').mkdir()
        link=EdgeLink(c,rid,m,td/'thor',errors.append,'CPU_PLAN','unused',transport=client)
        start=time.monotonic_ns();jobs=[]
        for f in range(30):
            for sid in range(8):
                row=decorate(dict(stream_id=sid,frame_id=f,logical_arrival_ns=start+f*10**9//30),start,e)
                if row['placement']=='EDGE':jobs.append(row)
        for row in reversed(jobs):link.put(row,payloads[row['stream_id']])
        link.finish();assert link.done.wait(10);link.close();thread.join(10)
        assert not thread.is_alive() and not errors,(e,errors)
        assert srv[0]['integrity_status']=='VALID' and srv[0]['received']==8*e
        assert all(r.get('c_ns') for r in jobs)
        assert [r['edge_request_id'] for r in sorted(jobs,key=lambda r:r['socket_submission_ns'])]==list(range(8*e))
    checks.append('A/B: two E0 controls never connect; eight fragmented memory sessions with repeat 1/2, request hashes/IDs/FINAL/drain; CPU mock only')
    return dict(status='PASS',checks=checks,GPU_executed=False,network_executed=False,clock_control_accessed=False,
       fixture_provenance='Synthetic timestamps/power/mock outputs used only as CPU tests; NOT measured pilot results',scratch_path=str(tmp),
       adapted_source_sha256=hashlib.sha256(adapted_source().encode()).hexdigest())
if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--output',required=True);a=ap.parse_args()
    result=verify()
    with Path(a.output).open('x') as f:json.dump(result,f,indent=2)
    print(json.dumps(result,indent=2))
