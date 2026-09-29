"""B1 preparation tests: pure fixtures + existing B0 replay; no workload or clock control."""
import ast
import copy
import inspect
import json
from pathlib import Path
import sys
import tempfile
import types
from b1_common import ROOT,OUT,B0_ROOT,B0_RUN,load_plan,run_source,make_accounting,off_begin_source,sha
import build_adapter
# Load frozen Phase-A tests under a distinct name.
import importlib.util
spec=importlib.util.spec_from_file_location('frozen_phase_cpu',ROOT/'scripts/timely_capacity_campaign/common/service_phase_v1/verify_cpu.py')
v=importlib.util.module_from_spec(spec);spec.loader.exec_module(v)
import analyze_b1 as a


def main(destination):
    if destination.exists():raise RuntimeError('CPU validation output exists; no overwrite')
    p=load_plan();report={}
    for fn in ('static_tests','runtime_tests'):
        report[fn]=getattr(v,fn)()
    old,new=v.ast_functions(build_adapter.run_source()),v.ast_functions(run_source())
    names=['infer','front','arrivals','sample_tensor','monitor','checkpoint','save_records','fail']
    assert all(old[k]==new[k] for k in names)
    report['B0_worker_frontend_timestamps_AST_identical']=names
    import run_b1 as launcher
    from pruning_common import PruningAccounting
    assert type(make_accounting(True)) is PruningAccounting
    off=make_accounting(False)
    s=off_begin_source(PruningAccounting)
    assert s.replace('if False:  # B1 OFF: expiry disabled',"if stamp>=job['absolute_deadline_ns']:")==__import__('textwrap').dedent(inspect.getsource(PruningAccounting.begin))
    # Execute the real B1 ON/OFF class in the frozen fake-worker fixture.
    fs=inspect.getsource(v.worker_fixture)
    start=fs.index("    nsacct=accounting_types();acct=")
    end=fs.index('    jobs=',start)
    fs=fs[:start]+'    acct=make_accounting(pruning)\n'+fs[end:]
    ns=dict(v.__dict__,make_accounting=make_accounting)
    exec(compile(fs,'<B1-actual-accounting-CPU-fixture>','exec'),ns)
    worker_source=build_adapter.extract_function(run_source(),'infer')
    results=[]
    for enabled in (False,True):
        trace,jobs,events,ph=ns['worker_fixture'](worker_source,enabled)
        expected=['EXPIRED_DROP','EXPIRED_DROP','COMPLETED','COMPLETED','EXPIRED_DROP','COMPLETED'] if enabled else ['COMPLETED']*6
        assert [j['terminal_state'] for j in jobs]==expected
        assert sum(x=='TRT' for x in trace)==30+expected.count('COMPLETED')
        assert len(ph)==6 and all('tensor' not in j for j in jobs)
        assert all(j['s_ns']==100 for j in jobs if j['terminal_state']=='COMPLETED')
        assert all(j['expiry_check_ns']==100 for j in jobs)
        if enabled:
            reference=v.worker_fixture(worker_source,True)
            assert trace==reference[0] and jobs==reference[1] and events==reference[2] and ph==reference[3]
        results.append(dict(pruning=enabled,dispositions=expected,TRT_calls=trace.count('TRT'),same_timestamp_positions=True))
    report['actual_B1_accounting_worker_fixtures']=results
    # Slot IDs and source due offsets are identical for all four planned runs.
    cohorts=[]
    for c in p['order']:
        local=[];source=[];counts={k:0 for k in range(8)}
        for f in range(1800):
            for k in range(8):
                r=dict(stream_id=k,frame_id=f,logical_arrival_ns=f*10**9//30)
                a.cfg.decorate(r,0,c);source.append((k,f,r['logical_arrival_ns']))
                if r['admitted']:local.append((k,f));counts[k]+=1
                assert r['placement'] in ('LOCAL','SKIP')
        assert len(source)==14400 and len(local)==12000 and set(counts.values())=={1500}
        cohorts.append(local)
        ctx=launcher.Context();m={}
        link=ctx.edge_link(c,c['run_id'],m,None,None,'CPU','NO_HOST')
        assert m['edge_usage']=='NOT_USED' and link.done.is_set()
    assert all(x==cohorts[0] for x in cohorts)
    report['admission_placement_arrivals']=dict(status='PASS',physical=14400,local=12000,per_stream=1500,no_Edge_connection=True,order=[c['run_id'] for c in p['order']])
    # Hand-calculated union coverage, touching endpoints, partial gaps, and containment.
    idx=a.interval_index([(2,5),(5,8),(10,12)])
    assert a.overlap_ns(2,8,idx)==6
    assert a.overlap_ns(0,2,idx)==0 and a.overlap_ns(8,10,idx)==0
    assert a.overlap_ns(3,11,idx)==6 and a.overlap_ns(3,4,idx)==1
    assert a.overlap_ns(0,20,idx)==8
    assert a.overlap_ns(0,20,a.interval_index([]))==0
    report['overlap_union_exact_fixtures']='PASS'
    # Existing actual B0 logs; never run B0 again or write inside B0 outputs.
    c=json.loads((B0_ROOT/'plan.json').read_text())['order'][0];c['pruning_enabled']=True
    m,s,raw,ph,valid=a.load_run(B0_RUN,c)
    assert valid['status']=='PASS',valid
    r,stats,bins=a.summarize_run(c,m,s,raw,ph)
    previous=json.loads((B0_ROOT/'analysis01/B0_VALIDATION.json').read_text())
    assert abs(r['raw_completed_FPS']-previous['metrics']['local_raw_completed_FPS'])<1e-10
    assert abs(r['queue_p95_ms']-previous['metrics']['local_queue_p95_ms'])<1e-10
    assert abs(r['active_concurrency_mean']-previous['metrics']['active_concurrency_mean'])<1e-10
    assert abs(r['existing_service_duration_ms_mean']-previous['phases'][0]['mean'])<1e-10
    ov=a.overlap_rows(ph,c['run_id']);ovs=a.summarize_overlap(ov,c['run_id'])
    assert len(ov)==len(ph)==10560
    # Fast indexed overlaps checked independently by brute force for deterministic samples.
    for row in ov[::101]:
        start,end=int(row['t_pre_infer']),int(row['t_infer_return'])
        intervals=[(max(start,int(other['t_pre_infer'])),min(end,int(other['t_infer_return']))) for other in ov if other['worker_id']!=row['worker_id'] and int(other['t_pre_infer'])<end and int(other['t_infer_return'])>start]
        union=a.interval_index(intervals)[2][-1]
        assert union==row['overlap_ns']
    assert len(bins)==30 and all(x['end_ns']-x['start_ns']==100000000 for x in bins)
    report['B0_raw_replay']=dict(status='PASS',integrity=valid,executed=len(ov),existing_metrics_exact=True,overlap_counts=dict(__import__('collections').Counter(x['overlap_group'] for x in ov)))
    # Ensure cloned summary is exactly equivalent on unmodified B0.
    import b1_summary
    power=a.read(B0_RUN/'power_trace.csv.gz')
    original=b1_summary.frozen.summarize(m,raw,power)
    current=b1_summary.summarize(m,raw,power)
    assert current==original
    # Synthetic late start demonstrates that only OFF accepts expired waiting execution.
    mr=copy.deepcopy(m);mr['pruning_enabled']=False
    rr=copy.deepcopy(raw);victim=next(x for x in rr if x.get('phase')=='active' and x.get('placement')=='LOCAL')
    stamp=int(victim['absolute_deadline_ns'])+1
    victim['expiry_check_ns']=str(stamp);victim['inference_start_timestamp_ns']=str(stamp)
    victim['completion_timestamp_ns']=str(stamp+10_000_000)
    off_s=b1_summary.summarize(mr,rr,power)
    mr['pruning_enabled']=True;on_s=b1_summary.summarize(mr,rr,power)
    assert 'expired waiting work executed' in on_s['errors']
    assert 'expired waiting work executed' not in off_s['errors']
    report['pruning_OFF_validator_regression']='PASS: rejects late-start ON, permits late-start OFF; frozen B0 summary identical'
    # Corruption fixtures must fail without hiding any measured values.
    broken=copy.deepcopy(ph);broken[0]['gpu_exec_duration_ms']='nan'
    assert a.validate_run(c,m,s,raw,broken,json.loads((B0_RUN/'phase_instrumentation_manifest.json').read_text()))['status']=='FAIL'
    broken=copy.deepcopy(ph);broken.append(broken[0])
    assert a.validate_run(c,m,s,raw,broken,json.loads((B0_RUN/'phase_instrumentation_manifest.json').read_text()))['status']=='FAIL'
    report['invalid_event_and_duplicate_detection']='PASS'
    # Exercise all plotting/report writers with CLEARLY synthetic CPU test copies.
    with tempfile.TemporaryDirectory(prefix='B1_CPU_plot_') as scratch:
        temp=Path(scratch);runs=[];osummary=list(ovs);startup=[]
        for condition in p['order']:
            mode='ON' if condition['pruning_enabled'] else 'OFF'
            synthetic=dict(r,run_id=condition['run_id'],mode=mode,repeat=condition['repeat'])
            runs.append(synthetic)
            osummary.extend(dict(x,run_id=condition['run_id']) for x in ovs)
            startup.extend(dict(x,run_id=condition['run_id'],mode=mode,repeat=condition['repeat']) for x in bins)
        a.plots(temp,runs,osummary,startup)
        assert len(list(temp.glob('*.png')))==4
        assert 'Axis A' in a.paired_description(runs,osummary)
    # Postprocessing skeleton can be instantiated without touching runtime.
    fn,final=launcher.Context().bindings()
    assert callable(fn) and callable(final)
    report.update(status='PASS',GPU=False,network=False,frequency_control=False,
                  limitation='CPU fixtures do not validate future GPU performance; B0 already validated the identical CUDA event implementation.')
    destination.mkdir(exist_ok=False)
    a.write_csv(destination/'B0_replay_overlap_conditioned_metrics.csv',ovs)
    a.write_csv(destination/'B0_replay_startup_100ms.csv',bins)
    a.write_json(destination/'validation.json',report)
    print(json.dumps(report,indent=2))


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,default=OUT/'cpu_validation01')
    main(parser.parse_args().output)
