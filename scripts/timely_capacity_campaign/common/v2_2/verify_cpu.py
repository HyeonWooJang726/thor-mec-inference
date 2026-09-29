"""Synthetic CPU behavior validation and preserved-log replay; no GPU/settings writes."""
import ast
import copy
import inspect
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import types
from unittest.mock import patch
import numpy as np
from v22_config import ROOT,OUT,PLAN,order,load_plan,sha,b1
import v22_builder as builder
from v22_storage import PhaseBuffer,FrameLedger,preallocate_source_rows,FIELDS,STATUS
import v22_accounting as acct
import v22_events
import run_validation as launch
import analyze_validation as analysis
import v22_cpu as cpu


def main(destination):
    if destination.exists():raise RuntimeError('CPU output exists; preserve it')
    plan=load_plan();result={};initial=sys.getswitchinterval()
    spec=importlib.util.spec_from_file_location('v22_frozen_test',ROOT/'scripts/timely_capacity_campaign/common/service_phase_v1/verify_cpu.py')
    v=importlib.util.module_from_spec(spec);spec.loader.exec_module(v)
    old=b1.run_source();new=builder.run_source()
    for name in ('front','sample_tensor','monitor','checkpoint','save_records','fail'):
        assert v.ast_functions(old)[name]==v.ast_functions(new)[name],name
    assert v.ast_functions(builder.trt_source())['infer']==v.ast_functions((ROOT/'scripts/timely_capacity_campaign/common/service_phase_v1/instrumented_local_runtime.py').read_text())['infer']
    result['unchanged_functions']=['front','sample_tensor','monitor','checkpoint','save_records','fail','TRT.infer']
    # Active worker never allocates a tuple/dict/list record. Warmup rows remain outside active measurement.
    tree=ast.parse(b1.build_adapter.extract_function(new,'infer'));loop=next(n for n in ast.walk(tree) if isinstance(n,ast.While))
    assert not any(isinstance(n,(ast.Dict,ast.List,ast.Tuple,ast.ListComp,ast.DictComp)) for n in ast.walk(loop))
    assert 'phase_records.append' not in new and 'frames.append' not in new
    # Adapt frozen fixture scaffolding only, execute original vs new worker with actual accounting.
    fs=inspect.getsource(v.worker_fixture);a=fs.index('    nsacct=accounting_types();acct=');z=fs.index('    jobs=',a)
    fs=fs[:a]+'    acct=accounting_factory()\n'+fs[z:]
    def fixture(source,factory,array):
        text=fs
        if array:
            text=text.replace('phase_records=[]','phase_records=PhaseBuffer(6)')
            text=text.replace("def elapsed_after_existing_sync(self):return 4.0,'OK'", "def record_elapsed_after_existing_sync(self):self.last_ms=4.0;self.last_status=1")
            text=text.replace("return trace,jobs,acct.events,worker.phase_records", "return trace,jobs,acct.events,list(worker.phase_records.rows())")
            text=text.replace('frames=[]','frames=FrameLedger(40)')
        ns=dict(v.__dict__,accounting_factory=factory,PhaseBuffer=PhaseBuffer,FrameLedger=FrameLedger)
        exec(compile(text,'<V22-CPU-fixture>','exec'),ns)
        return ns['worker_fixture'](source,True)
    checks=[]
    for enabled in (False,True):
        a=fixture(b1.build_adapter.extract_function(old,'infer'),lambda:b1.make_accounting(enabled),False)
        b=fixture(b1.build_adapter.extract_function(new,'infer'),lambda:acct.make_accounting(enabled),True)
        assert a[0]==b[0] and a[1]==b[1] and a[3]==b[3],(enabled,a,b)
        assert a[2] and b[2]==[]
        checks.append(dict(pruning=enabled,trace_identical=True,phase_rows_identical=True,terminal_states=[r['terminal_state'] for r in b[1]],detailed_events_removed=len(a[2])))
    result['worker_queue_deadline_tensor_and_phase_preservation']=checks
    # Per-frame row preallocation preserves source/admission/placement/logical IDs.
    pool=preallocate_source_rows(8,60);ledger=FrameLedger(14400)
    for f in range(1800):
        target=123456789+f*10**9//30
        for sid in range(8):
            a=dict(phase='active',stream_id=sid,frame_id=f,logical_arrival_ns=target,admitted=1,admission_timestamp_ns=target,admission_observed_ns=target+1,enqueue_timestamp_ns='')
            r=pool[f][sid];r['logical_arrival_ns']=target;r['admitted']=1;r['admission_timestamp_ns']=target;r['admission_observed_ns']=target+1
            analysis.base.cfg.decorate(a,123456789,order()[0]);analysis.base.cfg.decorate(r,123456789,order()[0]);assert a==r
            ledger.record(r)
    assert len(ledger)==14400 and sum(r['admitted'] for r in ledger)==12000
    try:ledger.record({})
    except RuntimeError:pass
    else:raise AssertionError('Ledger silently grew')
    result['preallocated_arrivals']='PASS:14400 exact rows,12000 admitted IDs; overflow rejects'
    # Event CUDA sequence/error semantics unchanged; only returned tuple becomes scalar attributes.
    from cuda_events import EventPair as OldPair
    cases=[]
    for duration in (4.0,0.0,-1.0,float('nan')):
        c1=v.FakeCuda();c2=v.FakeCuda();e1=OldPair(c1,__import__('ctypes').c_void_p(7));e2=v22_events.EventPair(c2,__import__('ctypes').c_void_p(7))
        for e,cuda in ((e1,c1),(e2,c2)):e.begin();e.finish();cuda.sync();cuda.duration=duration
        value,status=e1.elapsed_after_existing_sync();e2.record_elapsed_after_existing_sync()
        assert STATUS[e2.last_status]==status and (value==e2.last_ms or (np.isnan(value) and np.isnan(e2.last_ms)))
        assert c1.trace==c2.trace and c1.trace.count('existing_stream_sync')==1
        cases.append(status)
    result['CUDA_elapsed_event_recording']=dict(status='PASS',cases=cases,extra_sync=0)
    # CPU pin guard, four-run supervisor order and exact fixed idle, no actual child/frequency call.
    attempts=[]
    for failure_index in (None,2):
        with tempfile.TemporaryDirectory(prefix='V22_CPU_supervisor_') as tmp:
            dest=Path(tmp);calls=[];cool=[];pins=[];before=[];after=[]
            class Process:
                def __init__(self,args,**kwargs):self.pid=123;self.returncode=0;calls.append(args[args.index('--run-id')+1])
                def communicate(self,timeout):return 'SYNTHETIC_CPU_ONLY',''
            class Context(launch.Context):
                def check_inputs(self):return plan
                def load_plan(self):return plan
                def frequency_preflight(self):pins.append('FAKE')
                def write_json(self,path,data):Path(path).write_text(json.dumps(data))
                def bindings(self):
                    def finalize(d,*args):
                        m=json.loads((d/'manifest.json').read_text());m['edge_ready']={'status':'NOT_USED_NO_CONNECTION'};(d/'manifest.json').write_text(json.dumps(m))
                        return dict(run_id=d.name,integrity_status='VALID',frequency_restore_ok=True)
                    return None,finalize
            def before_hook(c,d):
                before.append(c['run_id'])
                if c['order_index']==failure_index:raise RuntimeError('FAKE CPU mismatch; no child')
            fakeproc=types.SimpleNamespace(Popen=Process,PIPE=-1,TimeoutExpired=TimeoutError)
            fakefreq=types.SimpleNamespace(read_range=lambda:dict(min_freq=315000000,max_freq=1575000000))
            faketime=types.SimpleNamespace(monotonic_ns=lambda:123,sleep=lambda x:cool.append(x))
            with patch.object(launch,'OUT',dest),patch.object(cpu,'require_pinned',lambda:{'status':'PASS'}),patch.object(launch,'before_run',before_hook),patch.object(launch,'after_run',lambda d:(after.append(d.name) or True)),patch.object(launch,'validate_finished',lambda *args:True),patch.object(launch.prior.old,'frequency',fakefreq),patch.object(launch.prior.old.prior.hybrid,'subprocess',fakeproc),patch.object(launch.prior.old.prior.hybrid,'time',faketime):
                ctx=Context();ctx.PREFLIGHT=dest/'frequency_preflight.json'
                if failure_index:
                    try:ctx.campaign(sha(PLAN))
                    except RuntimeError:pass
                    else:raise AssertionError('Failed CPU preflight accepted')
                    assert calls==[order()[0]['run_id']]
                else:
                    assert ctx.campaign(sha(PLAN))==0
                    assert calls==[c['run_id'] for c in order()] and cool==[10,10,10] and before==calls and after==calls
                try:ctx.campaign(sha(PLAN))
                except RuntimeError:pass
                else:raise AssertionError('Retry accepted')
            assert pins==['FAKE'];attempts.append(dict(failure_index=failure_index,fake_runs=calls,idle_seconds=cool))
    result['supervisor']=attempts
    # Same raw analyzer results with fixed ledger; phase export roundtrip replay on actual B1 logs.
    references=[]
    for c in b1.order():
        d=b1.OUT/c['run_id'];m,s,raw,ph,valid=analysis.base.load_run(d,c);assert valid['status']=='PASS'
        r,ps,bs=analysis.base.summarize_run(c,m,s,raw,ph);references.append(r)
        import b1_summary
        power=analysis.base.read(d/'power_trace.csv.gz');l=FrameLedger(len(raw))
        for row in raw:l.record(row)
        assert b1_summary.summarize(m,l,power)==b1_summary.summarize(m,raw,power)
    result['historical_B1_raw_replay']='PASS:four preserved controls; final summary identical with fixed ledger'
    # Frozen ON gate includes no GPU span check.
    row=dict(integrity_status='VALID',terminal_accounting='PASS',raw_completed_FPS=195,completed_cohort_FPS=197,expired_FPS=5,existing_service_duration_ms_mean=10.1,bookkeeping_duration_ms_p95=.05,frequency_restore_ok=True)
    full={'host_wakeup_delay_ms':{'mean':1.7},'gpu_exec_duration_ms':{'mean':999}}
    assert analysis.accept(row,full,True,True)['status']=='PASS'
    for key,value in [('raw_completed_FPS',194.99),('completed_cohort_FPS',196.99),('expired_FPS',5.01),('existing_service_duration_ms_mean',10.11),('bookkeeping_duration_ms_p95',.051)]:
        bad=dict(row);bad[key]=value;assert analysis.accept(bad,full,True,True)['status']=='FAIL'
    assert analysis.accept(row,full,False,True)['status']=='FAIL'
    assert sys.getswitchinterval()==initial
    result.update(status='PASS',GPU=False,network=False,settings_changed=False,switch_interval_changed=False,limitation='CPU functional tests do not establish GPU performance or overhead')
    destination.mkdir(exist_ok=False);analysis.base.write_json(destination/'validation.json',result);analysis.base.write_csv(destination/'B1_replay_summary.csv',references)
    print(json.dumps(result,indent=2))


if __name__=='__main__':
    import argparse
    ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,default=OUT/'cpu_validation01');a=ap.parse_args();main(a.output)
