"""CPU synthetic fixtures, historical replay and isolated memory-wire validation only."""
import argparse
import ast
import copy
import csv
import gzip
import importlib.util
import inspect
import json
import math
from pathlib import Path
import queue
import socket
import tempfile
import types
from collections import Counter
import campaign_config as cfg
import campaign_analysis as analysis
import run_campaign as run
from reuse import pruning,canonical,previous_analysis,prior


def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m


def fixture(c):
    pv=module('tcc_pruning_fixture',cfg.ROOT/'scripts/expired_work_pruning/verify_cpu.py')
    fn=pv.fixture
    changed=types.FunctionType(fn.__code__,dict(fn.__globals__,decorate=lambda row,start,target,mode,D:cfg.decorate(row,start,c)))
    m,rows,power=changed(c,True)
    if not c['edge_r']:
        m.update(edge_usage='NOT_USED',edge_ready={'status':'NOT_USED_NO_CONNECTION'},edge_final={'status':'NOT_USED'})
    for r in rows:
        if r.get('ready_timestamp_ns') is not None:r['enqueue_timestamp_ns']=r['ready_timestamp_ns']+int(r['stream_id'])
    m['run_start_diagnostics']={'provenance':'SYNTHETIC_NOT_MEASUREMENT','GPU_temperature_C':{'gpu':40}}
    for r in power:r['network_tx_bytes']=(r['timestamp_ns']-m['active_start_ns']+1_000_000_000)//100 if c['edge_r'] else None
    return m,rows,power


def verify(block):
    checks=[];conditions=cfg.expected_order(block)
    assert len(conditions)==(18 if block=='A' else 35)
    unique={c['cell']:c for c in conditions}
    masks={}
    for c in unique.values():
        target=c['target_service_FPS'];rate=target//8;ms,es=cfg.schedule(target,8*c['edge_r'],c['admission_pattern'])
        assert all(len(mask)==rate for mask in ms)
        if block=='A':
            base=cfg.schedule(target,0,'ALIGNED')[0][0]
            def circular_skip_gaps(mask):
                skip=[i for i in range(30) if i not in mask]
                return Counter((skip[(j+1)%len(skip)]-x)%30 for j,x in enumerate(skip))
            assert all(circular_skip_gaps(mask)==circular_skip_gaps(base) for mask in ms)
            totals=[sum(i in mask for mask in ms) for i in range(30)]
            assert set(totals)=={0,8} if c['admission_pattern']=='ALIGNED' else max(totals)-min(totals)<=1
        else:
            assert all(ms[0]==x for x in ms)
            assert ms[0]==masks.setdefault(target,ms[0])
            per_stream=Counter(sid for sid,f in es)
            assert len(es)==8*c['edge_r'] and max(per_stream.values())-min(per_stream.values())<=1
            if (target,8*c['edge_r']) in ((200,16),(240,40)):
                oldmask,oldslots=canonical.schedule(target,'B');assert ms[0]==oldmask and es==oldslots
        identities=[];count=Counter()
        for f in range(1800):
            for sid in range(8):
                r=cfg.decorate(dict(stream_id=sid,frame_id=f,logical_arrival_ns=1_000_000+f*10**9//30),1_000_000,c)
                count[r['placement']]+=1
                if r['placement']=='EDGE':identities.append(r['edge_request_id'])
        assert count['LOCAL']==8*c['local_r']*60 and count['EDGE']==8*c['edge_r']*60
        assert sorted(identities)==list(range(count['EDGE']))
    checks.append('Full60s source/admission/split identity and per-second counts; circular skip-gap equivalence; slot range; reference E16/E40 exact identity')
    # Existing actual pruning class: same expiry boundary and FIFO survivor sequence.
    q=queue.Queue();a=pruning.PruningAccounting()
    for i in range(4):a.enqueue(q,dict(stream_id=0,frame_id=i,absolute_deadline_ns=100 if i%2==0 else 200),lambda:50)
    assert [a.begin(q.get(),lambda:100) for _ in range(4)]==[False,True,False,True]
    assert (a.n_enqueue,a.n_start,a.n_expired)==(4,2,2)
    checks.append('Frozen expired-only accounting equality and FIFO survivor order')
    # No runtime function is called. Compile and compare unchanged frontend/worker implementation.
    from reuse import previous_runner
    def functions(source):return {x.name:ast.dump(x,include_attributes=False) for x in ast.walk(ast.parse(source)) if isinstance(x,ast.FunctionDef)}
    before=functions(previous_runner.adapted_source());after=functions(run.adapted_source())
    for name in ('infer','front','sample_tensor','save_records'):assert before[name]==after[name],name
    normalized=run.adapted_source().replace("decorate(row,manifest['active_start_ns'],condition)","decorate(row,manifest['active_start_ns'],condition['target_service_FPS'],condition['supply_mode'],condition['deadline_ms'])")
    assert before['arrivals']==functions(normalized)['arrivals']
    ctx=run.Context(block,cfg.ROOT/'scripts/timely_capacity_campaign'/cfg.BLOCKS[block]/'run_block.py');ctx.bindings()
    checks.append('Unchanged Local inference/pruning/frontend/decode/resize/save AST; scheduler differs only by explicit decorator; new bindings compile')
    scratch=Path(tempfile.mkdtemp(prefix='tcc_'+block+'_CPU_'))
    results=[]
    for c in unique.values():
        m,rows,power=fixture(c);s=analysis.summarize(m,rows,power)
        assert s['integrity_status']=='VALID',(c['cell'],s['errors'])
        assert s['admitted_frames']==c['target_service_FPS']*60
        assert s['unfinished_after_drain']==0 and s['backlog_after_drain']==s['expired_dropped_frames']
        assert math.isclose(sum(v['timely_FPS'] for v in s['path_timely'].values()),s['timely_FPS'],abs_tol=1e-10)
        assert s['VIN_active_energy_J']==4800
        results.append((c,m,rows,power,s))
        d=scratch/c['cell'];d.mkdir()
        for name,rr in [('per_frame',rows),('power_trace',power)]:
            keys=list(dict.fromkeys(k for row in rr for k in row))
            with gzip.open(d/(name+'.csv.gz'),'wt',newline='') as f:
                w=csv.DictWriter(f,keys);w.writeheader();w.writerows(rr)
        replay=analysis.summarize(m,analysis.read_csv(d/'per_frame.csv.gz'),analysis.read_csv(d/'power_trace.csv.gz'))
        for k in ('integrity_status','admitted_frames','timely_completed_frames','expired_dropped_frames','unfinished_after_drain'):assert replay[k]==s[k]
    checks.append('Every unique condition full60s synthetic fixture + gzip raw replay; counters, per-path timely, B/U, VIN active energy, diagnostic tables')
    c,m,rows,power,s=results[0]
    for fault in ('duplicate','missing_completion','early_expiry','placement','cap'):
        mm,rr=copy.deepcopy((m,rows));active=[r for r in rr if r.get('phase')=='active']
        if fault=='duplicate':rr.append(copy.deepcopy(active[0]))
        if fault=='missing_completion':next(r for r in active if r.get('terminal_state')=='COMPLETED').pop('completion_timestamp_ns')
        if fault=='early_expiry':
            r=next(r for r in active if r.get('terminal_state')=='EXPIRED_DROP');r['expired_drop_ns']=r['absolute_deadline_ns']-1
        if fault=='placement':next(r for r in active if r['admitted'])['placement']='SKIP'
        if fault=='cap':mm['queue_cap_saturation']=True
        assert analysis.summarize(mm,rr,power)['integrity_status']=='INVALID',fault
    checks.append('Reject duplicate/missing identities, incomplete completion, early expiry, placement corruption, queue-cap saturation')
    # Historical CPU-only replay validates the reused analyzer against real stored counts.
    historical=cfg.ROOT/'results/expired_work_pruning'
    histplan=json.loads((historical/'plan.json').read_text())
    h=next(c for c in histplan['order'] if c['target_service_FPS']==200 and c['deadline_ms']==100)
    d=historical/h['run_id'];mm=json.loads((d/'manifest.json').read_text());mm['admission_pattern']='ALIGNED'
    replay=analysis.summarize(mm,analysis.read_csv(d/'per_frame.csv.gz'),analysis.read_csv(d/'power_trace.csv.gz'))
    stored=json.loads((d/'summary.json').read_text())
    for k in ('integrity_status','admitted_frames','timely_completed_frames','expired_dropped_frames','completed_frames'):assert replay[k]==stored[k],(k,replay.get('errors'))
    checks.append('Existing actual P200-D100 raw/summary count replay; read-only, not new measurement')
    if block=='A':
        assert isinstance(ctx.edge_link(dict(edge_r=0),None,{},None,None,None,None),prior.UnusedEdgeLink)
        checks.append('Block A selects existing no-connection link')
    return dict(status='PASS',block=block,checks=checks,scratch=str(scratch),provenance='SYNTHETIC_CPU_VALIDATION_AND_HISTORICAL_READ_ONLY_REPLAY',GPU_executed=False,network_executed=False,frequency_control_executed=False)


if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--block',choices=['A','B'],required=True);ap.add_argument('--output',type=Path,required=True);a=ap.parse_args()
    if a.output.exists():raise RuntimeError('No output overwrite')
    # Fail closed on accidental real connection creation in all CPU test paths.
    original=socket.create_connection
    socket.create_connection=lambda *a,**k:(_ for _ in ()).throw(AssertionError('Network forbidden during CPU validation'))
    try:r=verify(a.block)
    finally:socket.create_connection=original
    with a.output.open('x') as f:json.dump(r,f,indent=2)
    print(json.dumps(r,indent=2))
