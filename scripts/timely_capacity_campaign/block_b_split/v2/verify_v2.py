"""CPU-only synthetic branch/admission/accounting/adapter tests; no sockets/devices."""
import ast
import copy
import csv
import gzip
import importlib.util
import json
import socket
import tempfile
from pathlib import Path
from collections import Counter
from bootstrap import ROOT,HERE,OUT,frozen as cfg
import config_v2 as conf
import run_v2
import analysis_v2 as analysis
import campaign_analysis as original
from reuse import canonical

def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

def synthetic_flags(flags):
    return [dict(rate=e,repeat=r,integrity_status='VALID',Edge_timely_ratio=.95 if v else .89) for e,v in zip(conf.LEVELS,flags) for r in (1,2)]

def run():
    tests=[];branch_records=[];selector=[]
    for flags,expected,nonmono in [([1,0,0,0],56,False),([1,1,0,0],64,False),([1,1,1,0],72,False),([1,1,1,1],80,False),
        ([1,0,1,0],56,True),([1,1,0,1],64,True),([1,0,1,1],56,True),([0,1,1,1],None,True)]:
        s=conf.select(synthetic_flags(flags));assert s['E_max']==expected and bool(s['flags'])==nonmono
        if expected is None:assert s['status']=='EDGE_PATH_LIMITED_BELOW_E56'
        selector.append(dict(pattern=flags,**s))
    mixed=synthetic_flags([1,1,1,1]);mixed[1]['Edge_timely_ratio']=.899;assert conf.select(mixed)['E_max'] is None
    mixed[1]['integrity_status']='INVALID';assert conf.select(mixed)['status']=='INCONCLUSIVE'
    for r in mixed:r['integrity_status']='VALID';r['Edge_timely_ratio']=.90
    assert conf.select(mixed)['E_max']==80
    tests.append('Contiguous PASS, 2/2 rule, equality90%, non-monotone flags, E56 failure, invalid evidence')
    fixturemod=module('v2_previous_cpu_fixture',ROOT/'scripts/timely_capacity_campaign/common/verify_cpu.py')
    scratch=Path(tempfile.mkdtemp(prefix='TCC_B_V2_CPU_'));cache={}
    for e in conf.LEVELS:
        rows=conf.order(e);assert len(rows)==35 and len({r['run_id'] for r in rows})==35
        counts=Counter(c['original_cell'] for c in rows)
        assert len(counts)==9 and sorted(counts.values())==[3]*5+[5]*4
        originals=cfg.expected_order('B')
        assert [(r['original_cell'],r['repeat']) for r in rows]==[(r['cell'],r['repeat']) for r in originals]
        ids={}
        for c in {r['cell']:r for r in rows}.values():
            target=c['target_service_FPS'];rate=target//8;local=8*c['local_r'];edge=8*c['edge_r']
            masks,slots=cfg.schedule(target,edge)
            expected=tuple(f for f in range(30) if (f+1)*rate//30>f*rate//30)
            assert all(m==expected for m in masks) and all(len(m)==rate for m in masks)
            assert len(slots)==edge and Counter(s for s,f in slots)==Counter({s:edge//8 for s in range(8)})
            if c['analysis_class']=='B-PRIMARY':assert masks==ids.setdefault(c['source_demand_FPS'],masks)
            else:assert c['source_demand_FPS']==240 and rate in (27,28,29) and edge==e
            if (target,edge) in ((200,16),(240,40)):
                om,os=canonical.schedule(target,'B');assert masks[0]==om and slots==os
            ac=Counter();edgeids=[];perstream=Counter()
            for f in range(1800):
                for sid in range(8):
                    r=cfg.decorate(dict(stream_id=sid,frame_id=f,logical_arrival_ns=f*10**9//30),0,c)
                    ac[r['placement']]+=1;perstream[sid]+=r['admitted']
                    if r['placement']=='EDGE':edgeids.append(r['edge_request_id'])
            assert ac['LOCAL']==local*60 and ac['EDGE']==edge*60 and len(set(perstream.values()))==1
            assert sorted(edgeids)==list(range(edge*60))
            slotA=[sum(f in m for m in masks) for f in range(30)]
            slotL=[n-sum(k[1]==f for k in slots) for f,n in enumerate(slotA)]
            branch_records.append(dict(E_max=e,cell=c['cell'],analysis_class=c['analysis_class'],r=rate,admitted_FPS=target,
                Local_FPS=local,Edge_FPS=edge,per_stream_admitted_count=dict(perstream),slot_admitted=dict(Counter(slotA)),slot_Local=dict(Counter(slotL)),source_TIR_denominator_FPS=240))
            key=(target,local,edge)
            if key not in cache:
                m,fr,power=fixturemod.fixture(c);m.update(c)
                s=analysis.summarize(m,fr,power)
                assert s['integrity_status']=='VALID',(c['cell'],s.get('errors'))
                assert s['admitted_frames']==target*60 and s['source_normalized_TIR']==s['timely_completed_frames']/14400
                assert s['unfinished_after_drain']==0
                d=scratch/c['cell'];d.mkdir()
                for name,data in [('per_frame',fr),('power_trace',power)]:
                    fields=list(dict.fromkeys(k for row in data for k in row))
                    with gzip.open(d/(name+'.csv.gz'),'wt',newline='') as f:
                        w=csv.DictWriter(f,fields);w.writeheader();w.writerows(data)
                replay=analysis.summarize(m,analysis.read_csv(d/'per_frame.csv.gz'),analysis.read_csv(d/'power_trace.csv.gz'))
                for field in ('admitted_frames','completed_frames','timely_completed_frames','expired_dropped_frames','source_normalized_TIR','integrity_status'):assert replay[field]==s[field]
                (d/'manifest.json').write_text(json.dumps(m));(d/'summary.json').write_text(json.dumps(s))
                cache[key]=s
        # B-CAPPED result must never influence the controlled split-only gate.
        synthetic=[dict(c,integrity_status='VALID',timely_FPS=100 if c['original_cell'] in ('S240-L200E40','S200-L184E16') else 110,worst_stream_TIR=.8) for c in rows]
        assert all(analysis.primary_gate(synthetic,d)=='SPLIT_BY_TIMELY_CAPACITY_SUPPORTED' for d in (200,240))
        for c in synthetic:
            if c['analysis_class']=='B-CAPPED':c.update(integrity_status='INVALID',timely_FPS=9999)
        assert analysis.primary_gate(synthetic,240)=='SPLIT_BY_TIMELY_CAPACITY_SUPPORTED'
        ctx=run_v2.Context(e);ctx.bindings()
    tests.append('4x35 order/repeats, 60s exact IDs and counts, historical E16/E40, canonical r27/28/29, capped source denominator240, unique condition gzip analyzer replay')
    def functions(s):return {x.name:ast.dump(x,include_attributes=False) for x in ast.walk(ast.parse(s)) if isinstance(x,ast.FunctionDef)}
    a,b=functions(run_v2.old.adapted_source()),functions(run_v2.adapted_source())
    for k in ('infer','front','arrivals','sample_tensor','save_records'):assert a[k]==b[k],k
    tests.append('Frozen inference/pruning/frontend/arrival AST unchanged; added endpoint diagnostics/metadata only; all adapter bindings compile')
    # Actual endpoint command is not called by CPU validation.
    from preflight_v2 import hello
    import sys
    oldedge=module('pruning_edge_server',ROOT/'scripts/expired_work_pruning/edge_server.py');sys.modules['pruning_edge_server']=oldedge
    edge=module('v2_edge_cpu',HERE/'edge_v2.py');cacheh=run_v2.old.prior.old.edge_runtime.CACHE_SHA256
    for e in conf.LEVELS:
        ctx=run_v2.Context(e)
        for c in conf.order(e):assert ctx.hello(c,c['run_id'],'CPU')==edge.expected(c,'CPU','campaign',cacheh)
    for c in conf.preflight_order():assert hello(dict(c,edge_r=c['rate']//8),c['run_id'],'CPU')==edge.expected(c,'CPU','preflight',cacheh)
    tests.append('140 primary/capped plus8 preflight handshake equality; no network connection')
    out=OUT/'v2';out.mkdir(exist_ok=True)
    for name,data in [('branch_selector_validation.json',dict(status='PASS',cases=selector)),('canonical_admission_validation.json',dict(status='PASS',conditions=branch_records)),
        ('cpu_validation.json',dict(status='PASS',tests=tests,unique_full60s_replays=len(cache),scratch=str(scratch),provenance='CPU_SYNTHETIC_NOT_MEASUREMENT',GPU=False,network=False,frequency_control=False))]:
        with (out/name).open('x') as f:json.dump(data,f,indent=2)
    print('PASS',tests,'unique replays',len(cache))

if __name__=='__main__':
    socket.create_connection=lambda *a,**k:(_ for _ in ()).throw(AssertionError('Network forbidden'))
    run()
