#!/usr/bin/env python3
"""Synthetic CPU verification only: no GPU, network or frequency access."""
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
import tempfile
import types
import refinement_common as common
from refinement_common import ROOT,sha,decorate,expected_order,canonical
import run_refinement as run
import analyze_refinement as analysis


def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m


old=module('refinement_old_fixture',ROOT/'scripts/expired_work_pruning/verify_cpu.py')
fixture_fn=types.FunctionType(old.fixture.__code__,dict(old.fixture.__globals__,decorate=decorate),argdefs=old.fixture.__defaults__)
build_plan=module('refinement_prepare_CPU',Path(__file__).with_name('prepare.py')).build_plan
toy_history=module('refinement_best_grid_CPU',ROOT/'scripts/d100_timely_capacity_map/verify_best_of_grid.py').fixture


def fixture(c):
    m,rows,power=fixture_fn(c)
    m.update(edge_usage='NOT_USED',edge_ready={'status':'NOT_USED_NO_CONNECTION'},edge_final={'status':'NOT_USED'})
    return m,rows,power


def score(row,n):
    row.update(integrity_status='VALID',source_frames=14400,
        per_stream=[dict(stream_id=k,timely_completed_frames=n) for k in range(8)],
        worst_stream_timely_FPS=n/60,worst_stream_TIR=n/1800,timely_FPS=8*n/60,
        late_completed_FPS=0.,expired_drop_FPS=0.,VIN_J_per_timely_frame=.5)


def verify():
    plan=build_plan();checks=[];fixtures={}
    for target in (160,200,240):assert common.schedule(target,'A')==canonical.schedule(target,'A')
    for c in plan['order']:
        m,rows,power=fixture(c);s=analysis.summarize(m,rows,power)
        assert s['integrity_status']=='VALID',s['errors']
        assert s['source_frames']==14400 and s['decode_ready_FPS']==s['resize_ready_FPS']==240
        assert s['admitted_frames']==c['target_service_FPS']*60 and s['local_assigned_FPS']==c['target_service_FPS']
        assert s['edge_assigned_FPS']==s['edge_active_completed_FPS']==0 and s['edge_usage']=='NOT_USED'
        assert all(v is None for v in s['edge_E2E_ms'].values())
        assert s['completed_frames']+s['expired_dropped_frames']==s['admitted_frames']
        assert s['unfinished_after_drain']==0 and s['backlog_after_drain']==s['expired_dropped_frames']
        assert s['TIR_source']==s['timely_completed_frames']/14400 and s['active_concurrency_peak']<=2
        assert s['VIN_active_energy_J']==4800 and s['VIN_J_per_timely_frame']==4800/s['timely_completed_frames']
        assert s['backlogs']['L']['regression_start_ns']==m['active_start_ns']+30*10**9
        for sid in range(8):
            ids=[r['frame_id'] for r in rows if r.get('stream_id')==sid and r.get('phase')=='active' and r.get('admitted')]
            expected=[f for f in range(1800) if (f+1)*c['local_r']//30>f*c['local_r']//30]
            assert ids==expected and len(ids)==60*c['local_r']
            assert s['per_stream'][sid]['TIR_source']==s['per_stream'][sid]['timely_completed_frames']/1800
        fixtures[c['cell']]=(m,rows,power)
    checks.append('12full60s fixtures, exact phase-accumulator IDs and21/22/23/24 per-stream rates,240FPSdecode/resize, noEdge, allcount/stream/latency/B/U/activeVIN checks; coarse masks unchanged')
    for cell in fixtures:
        for fault in ('early_expiry','due','completion','edge','cap'):
            m,rows,power=copy.deepcopy(fixtures[cell])
            if fault=='early_expiry':
                r=next(r for r in rows if r.get('terminal_state')=='EXPIRED_DROP');r['expiry_check_ns']=r['expired_drop_ns']=r['absolute_deadline_ns']-1
            if fault=='due':next(r for r in rows if r.get('phase')=='active')['logical_arrival_ns']+=1
            if fault=='completion':next(r for r in rows if r.get('terminal_state')=='COMPLETED').pop('completion_timestamp_ns')
            if fault=='edge':m['edge_r']=1
            if fault=='cap':m['queue_cap_saturation']=True
            assert analysis.summarize(m,rows,power)['integrity_status']=='INVALID',(cell,fault)
    def nested(s):return {n.name:ast.dump(n,include_attributes=False) for n in ast.walk(ast.parse(s)) if isinstance(n,ast.FunctionDef)}
    before,after=nested(common.proven_runner.adapted_source()),nested(run.adapted_source())
    for name in ('infer','front','arrivals','sample_tensor','monitor','checkpoint','save_records'):assert before[name]==after[name],name
    f,g=run.bindings();assert f.__globals__['OUT']==common.OUT
    original=socket.create_connection
    def forbidden(*a,**kw):raise AssertionError('Network forbidden')
    socket.create_connection=forbidden
    try:
        for c in plan['order']:
            m={};errors=[];link=common.EdgeLink(c,c['run_id'],m,Path('/tmp'),errors.append,'CPU','unused')
            link.finish();link.close();assert m['edge_usage']=='NOT_USED' and not errors
        c=dict(plan['order'][0],edge_r=1)
        try:common.EdgeLink(c,None,None,None,None,None,None)
        except RuntimeError:pass
        else:raise AssertionError('Edge configuration accepted')
    finally:socket.create_connection=original
    checks.append('Corrupt timestamp/expiry/completion/Edge/cap rejected; worker/frontend/telemetry AST identical;12Local sessions cannot connect')
    history=toy_history();new=[]
    for c in plan['order']:
        r=dict(c);score(r,{168:1220,176:1240,184:1290,192:1260}[c['target_service_FPS']]);new.append(r)
    ca,se,co,d=analysis.grid_analysis(new,history)
    assert len(ca)==28 and d['local_winners']['ALL']==['L184']
    assert d['verdict']=='EDGE_NOT_REQUIRED_FOR_D100_TIMELY_CEILING'
    high=copy.deepcopy(history)
    for r in high:
        if r['cell']=='T200-B':score(r,1400)
    assert analysis.grid_analysis(new,high)[-1]['verdict']=='EDGE_TIMELY_EXTENSION_CANDIDATE'
    overlap=copy.deepcopy(high)
    for r in overlap:
        if r['cell']=='T200-B' and r['repeat']==2:score(r,1200)
    assert analysis.grid_analysis(new,overlap)[-1]['verdict']=='EDGE_ROLE_INCONCLUSIVE'
    assert analysis.grid_analysis(new[:-1],history)[-1]['verdict']=='EDGE_ROLE_INCONCLUSIVE'
    tied=copy.deepcopy(new)
    for r in tied:
        if r['cell']=='L176':score(r,1290);r['VIN_J_per_timely_frame']=.4
    _,selected,_,d=analysis.grid_analysis(tied,history)
    assert set(d['local_winners']['ALL'])=={'L176','L184'}
    assert [r['cell'] for r in selected if r['repeat']=='ALL']==['L176','L184']
    assert analysis.grid_analysis(new,history,'fixed_mean_winner')[-1]['verdict']=='EDGE_NOT_REQUIRED_FOR_D100_TIMELY_CEILING'
    checks.append('Seven-cell repeat/mean ranking, all primary ties retained with diagnostic energy order; strict observed-range separation/overlap/missing cases and both Hybrid references')
    scratch=Path(tempfile.mkdtemp(prefix='local_D100_refinement_CPU_'));replay=scratch/'runs';replay.mkdir()
    pf=scratch/'plan.json';pf.write_text(json.dumps(plan))
    pre=replay/'frequency_preflight.json';pre.write_text(json.dumps(dict(status='PASS',plan_sha256=sha(pf),provenance='CPU_MOCK')))
    previous=analysis.OUT,analysis.PLAN,analysis.load_plan,analysis.load_history
    analysis.OUT,analysis.PLAN,analysis.load_plan,analysis.load_history=replay,pf,lambda:plan,lambda _:history
    try:
        for c in plan['order']:
            m,rows,power=fixture(c);d=replay/c['run_id'];d.mkdir()
            m.update(execution_manifest_sha256=sha(pf),child_returncode=0,PROCESS_LIFECYCLE='PASS',status_finalized=True,
                frequency_restore_ok=True,active_phase_completed=True,drain_completed=True,cleanup_started=True,cleanup_completed=True,
                frequency_preflight={'sha256':sha(pre)},pin_readback_Hz=dict(min_freq=1575000000,max_freq=1575000000))
            (d/'manifest.json').write_text(json.dumps(m));(d/'summary.json').write_text(json.dumps(analysis.summarize(m,rows,power)))
            for name,data in [('per_frame',rows),('power_trace',power)]:
                fields=list(dict.fromkeys(k for r in data for k in r))
                with gzip.open(d/(name+'.csv.gz'),'wt',newline='') as f:
                    w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(data)
        with redirect_stdout(io.StringIO()):analysis.analyze(scratch/'analysis_valid')
        v=json.loads((scratch/'analysis_valid/verification.json').read_text());assert v['new_valid']==12
        with (scratch/'analysis_valid/per_stream_metrics.csv').open() as f:assert len(list(csv.DictReader(f)))==96
        saved_read=analysis.read_csv
        def missing(p):
            if Path(p).parent.name==plan['order'][0]['run_id']:raise FileNotFoundError('CPU injected missing trace; no deletion')
            return saved_read(p)
        analysis.read_csv=missing
        try:
            with redirect_stdout(io.StringIO()):analysis.analyze(scratch/'analysis_invalid')
        finally:analysis.read_csv=saved_read
        assert json.loads((scratch/'analysis_invalid/verification.json').read_text())['new_valid']==11
        assert json.loads((scratch/'analysis_invalid/refinement_verdict.json').read_text())['verdict']=='EDGE_ROLE_INCONCLUSIVE'
    finally:analysis.OUT,analysis.PLAN,analysis.load_plan,analysis.load_history=previous
    checks.append('12-run gzip/JSON/CSV analyzer roundtrip,96stream rows, historical/new cohort labels and missing-run retention; no measured superiority result generated')
    return dict(status='PASS',provenance='SYNTHETIC_CPU_VALIDATION_NOT_MEASUREMENT',checks=checks,
        GPU_executed=False,network_executed=False,frequency_accessed=False,scratch_path=str(scratch))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    if a.output.exists():raise RuntimeError('No validation overwrite')
    result=verify()
    with a.output.open('x') as f:json.dump(result,f,indent=2)
    print(json.dumps(result,indent=2))
