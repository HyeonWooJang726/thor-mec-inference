"""V2.1 instrumentation adapter; original plan/order/workers/protocol unchanged."""
import argparse
import ast
import inspect
import json
import types
from pathlib import Path
from bootstrap_21 import ROOT,HERE,OUT,PLAN,EXPECTED_PLAN_SHA
import run_v2 as v2
import checkpoint_21

def runtime_record():
    p=OUT/'runtime_manifest.json';r=json.loads(p.read_text())
    if v2.cfg.sha(PLAN)!=EXPECTED_PLAN_SHA:raise RuntimeError('Original experimental plan changed')
    if v2.cfg.sha(p)!=(OUT/'runtime_manifest.sha256').read_text().split()[0]:raise RuntimeError('V2.1 runtime manifest changed')
    for rel,h in r['new_source_sha256'].items():
        if v2.cfg.sha(ROOT/rel)!=h:raise RuntimeError('V2.1 source changed: '+rel)
    return dict(version='V2.1',runtime_manifest_sha256=v2.cfg.sha(p),condition_plan_sha256=EXPECTED_PLAN_SHA,
        source_sha256=r['new_source_sha256'])

def adapted_source():
    s=v2.adapted_source();rep=v2.old.rep
    s=rep(s,'from analysis_v2 import summarize','from analysis_21 import summarize')
    s=rep(s,'    manifest.update(experiment=',"    manifest=SnapshotManifest(manifest)\n    manifest['execution_runtime']=runtime_record()\n    manifest.update(experiment=")
    tree=ast.parse(s);node=next(n for n in ast.walk(tree) if isinstance(n,ast.FunctionDef) and n.name=='checkpoint')
    lines=s.splitlines(keepends=True)
    replacement='''    def checkpoint(phase, **fields):
        # Copy only membership and queue counters under the existing accounting
        # lock; no JSON encoding or I/O while this lock is held.
        with lock:
            observed_frames=tuple(frames)
            observed_queue=dict(enqueue=accounting.n_enqueue,start=accounting.n_start,expired=accounting.n_expired)
        counts={
            'source_scheduled':sum(r['phase']=='active' for r in observed_frames),
            'source_decoded':sum(r['phase']=='active' and bool(r.get('source_pulled_ns')) for r in observed_frames),
            'admitted':sum(r['phase']=='active' and bool(r.get('admitted')) for r in observed_frames),
            'ready':observed_queue['enqueue'],'started':observed_queue['start'],
            'completed':sum(r['phase']=='active' and bool(r.get('c_ns')) for r in observed_frames)}
        with manifest.capture_lock:
            manifest.update(fields)
            manifest['last_completed_lifecycle_phase']=phase
            manifest['last_frame_accounting_counts']=counts
            manifest['ready_queue_accounting']=observed_queue
            manifest['lifecycle_events'].append({'phase':phase,'monotonic_ns':time.monotonic_ns(),
                                               'utc':datetime.now(timezone.utc).isoformat()})
            snapshot=manifest.snapshot()
        write_json(directory/'manifest.json',snapshot)
'''
    lines[node.lineno-1:node.end_lineno]=[replacement]
    return ''.join(lines)

class Context(v2.Context):
    def __init__(self,emax=72):
        if emax!=72:raise ValueError('Only approved E_MAX_72 restart namespace')
        super().__init__(emax);self.OUT=OUT/'E_MAX_72';self.PLAN=PLAN;self.PREFLIGHT=self.OUT/'frequency_preflight.json';self.entry=HERE/'run_21.py'
    def load_plan(self):runtime_record();return super().load_plan()
    def write_json(self,path,data):
        if Path(path).parent.parent!=self.OUT:raise RuntimeError('Outside fresh V2.1 output')
        checkpoint_21.write_json(path,data)
    def bindings(self):
        # Reuse the V2 binding builder; only its adapter text/finalizer import and
        # snapshot helper globals differ. No worker, sender or receiver rewrite.
        source=inspect.getsource(v2.Context.bindings)
        source=__import__('textwrap').dedent(source)
        source=source.replace("'from analysis_v2 import summarize,read_csv'","'from analysis_21 import summarize,read_csv'")
        source=v2.old.rep(source,'wifi_capture=wifi_v2.capture)',
            'wifi_capture=wifi_v2.capture,SnapshotManifest=checkpoint_21.Manifest,runtime_record=runtime_record)')
        ns=dict(v2.__dict__,adapted_source=adapted_source,checkpoint_21=checkpoint_21,runtime_record=runtime_record)
        exec(compile(source,'<V2.1-bindings>','exec'),ns)
        return ns['bindings'](self)
    def campaign(self,approval):
        runtime=runtime_record()
        if approval!=runtime['runtime_manifest_sha256']:raise RuntimeError('Explicit V2.1 runtime approval SHA required')
        # Parent supervisor starts R1 from original order in a fresh output tree.
        return super().campaign(EXPECTED_PLAN_SHA)

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('action',choices=['check','campaign','one']);ap.add_argument('--emax',type=int,choices=[72],default=72)
    ap.add_argument('--approve-runtime-sha256');ap.add_argument('--run-id');a=ap.parse_args();ctx=Context()
    if a.action=='check':ctx.check_inputs();print('PASS: V2.1 read-only input/binding check')
    elif a.action=='campaign':raise SystemExit(ctx.campaign(a.approve_runtime_sha256))
    else:
        from preflight_v2 import require_selected
        require_selected(72);ctx.require_preflight();p=ctx.check_inputs();cs=[c for c in p['order'] if c['run_id']==a.run_id]
        if len(cs)!=1:raise RuntimeError('Run outside original order')
        seed=ctx.OUT/a.run_id/'manifest.json'
        if not seed.exists() or json.loads(seed.read_text()).get('child_has_started'):raise RuntimeError('Fresh supervisor seed required')
        raise SystemExit(ctx.bindings()[0](cs[0],a.run_id))
