"""CPU fake-process replay of parent supervisor. Never invokes a device helper."""
import datetime
import hashlib
import json
from pathlib import Path
import tempfile
import types
from timely_config import order
from run_timely_scan import supervisor_source
import run_validation as original


def main():
    events=[];runs=order()
    with tempfile.TemporaryDirectory(prefix='raw-scan-supervisor-') as tmp:
        out=Path(tmp);plan=out/'plan.json';plan.write_text('{}');digest=hashlib.sha256(plan.read_bytes()).hexdigest()
        frozen=dict(order=runs,smoke=[],idle_seconds=10)
        class Context:
            PREFLIGHT=out/'frequency_preflight.json';entry=out/'entry.py'
            def check_inputs(self):return frozen
            def load_plan(self):return frozen
            def frequency_preflight(self):events.append(('GPU_PREFLIGHT_STUB',))
            def write_json(self,p,r):p.write_text(json.dumps(r))
            def bindings(self):
                def finalize(d,info,stdout,stderr):
                    m=json.loads((d/'manifest.json').read_text());m['edge_ready']=True
                    (d/'manifest.json').write_text(json.dumps(m));events.append(('cleanup',d.name))
                    return dict(integrity_status='VALID',frequency_restore_ok=True)
                return None,finalize
        ctx=Context()
        class Process:
            pid=123;returncode=0
            def __init__(self,cmd,**kwargs):
                rid=cmd[-1];c=next(c for c in runs if c['run_id']==rid)
                seed=json.loads((out/rid/'manifest.json').read_text())
                assert seed['target_service_FPS']==c['target_service_FPS']
                assert seed['admission_fps_per_stream']==c['local_r']
                assert seed['pruning_enabled'] is True and seed['edge_r']==0
                assert seed['deadline_ms']==c['deadline_ms']
                events.append(('workload_stub',rid))
            def communicate(self,**kwargs):return '', ''
        # Construct a namespace copy; never mutate any original runtime module.
        hybrid=types.SimpleNamespace(**original.prior.old.prior.hybrid.__dict__)
        hybrid.subprocess=types.SimpleNamespace(Popen=Process,TimeoutExpired=TimeoutError,PIPE=-1)
        hybrid.time=types.SimpleNamespace(monotonic_ns=lambda:0,sleep=lambda x:events.append(('idle',x)))
        old=types.SimpleNamespace(prior=types.SimpleNamespace(hybrid=hybrid),rep=original.prior.old.rep,
            frequency=types.SimpleNamespace(read_range=lambda:dict(min_freq=315000000,max_freq=1575000000)))
        prior=types.SimpleNamespace(old=old)
        ns=dict(original.__dict__,prior=prior,OUT=out,PLAN=plan,order=lambda:runs,
            cpu=types.SimpleNamespace(require_pinned=lambda:dict(status='PASS')),
            before_run=lambda c,d:events.append(('preflight',c['run_id'])),
            after_run=lambda d:True,validate_finished=lambda d,c:True)
        exec(compile(supervisor_source(),'<CPU-only-supervisor>','exec'),ns)
        assert ns['campaign'](ctx,digest)==0
        assert [x[1] for x in events if x[0]=='workload_stub']==[c['run_id'] for c in runs]
        assert sum(x[0]=='idle' for x in events)==19
        for i,e in enumerate(events):
            if e[0]=='idle':assert e[1]==10 and events[i-1][0]=='cleanup'
        try:ns['campaign'](ctx,digest)
        except RuntimeError as e:assert 'retry/resume/overwrite' in str(e)
        else:raise AssertionError('Retry allowed')
    print(json.dumps(dict(status='PASS',provenance='SYNTHETIC_STUB_ONLY',runs=20,workloads_executed=0,
        dynamic_rate_seed=True,ON_only=True,cleanup_before_idle=True,retry_rejected=True,events=events),indent=2))


if __name__=='__main__':main()
