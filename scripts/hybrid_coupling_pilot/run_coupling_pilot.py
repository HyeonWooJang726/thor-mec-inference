#!/usr/bin/env python3
"""Prepare/check by default; explicit pilot action reuses frozen Hybrid supervisor.

No GPU, sockets, clock reads/writes on import or check. Never retries an existing ID.
"""
import argparse,inspect,types,ast,json
from pathlib import Path
from pilot_common import ROOT,OUT,PLAN,sha,load_plan,decorate,remaining,EdgeLink,EXTRA_FIELDS,hybrid
base=hybrid.base

def write_json(path,data):
    if Path(path).parent.parent!=OUT:raise RuntimeError('writer outside new pilot run directories')
    base.write_json(path,data)

def adapted_source():
    s=hybrid.adapted_source();rep=hybrid.replace_once
    s=rep(s,'from analyze_hybrid import summarize','from analyze_coupling import summarize')
    s=rep(s,"experiment='K8_HYBRID_CAPACITY_EXTENSION'","experiment='HYBRID_COUPLING_PILOT'")
    s=rep(s,'local_assigned_fps=200, edge_assigned_fps=40,',"local_assigned_fps=200, edge_assigned_fps=8*condition['edge_r'], edge_r=condition['edge_r'], admission_fps_per_stream=25+condition['edge_r'],")
    s=rep(s,'edge_threads_exited=False)',"edge_threads_exited=False, pass_name=condition['pass'], order_index=condition['order_index'])")
    s=rep(s,"if job['admitted']:","if True:  # Common decode AND resize of all 240 source FPS in every pilot.")
    s=rep(s,"else:edge.put(job,image.tobytes(order='C'))","elif job['placement']=='EDGE':edge.put(job,image.tobytes(order='C'))")
    s=rep(s,"decorate(row,manifest['active_start_ns'])","decorate(row,manifest['active_start_ns'],condition['edge_r'])")
    ast.parse(s);return s

def bindings():
    ns=dict(base.__dict__,OUT=OUT,EXECUTION_PLAN=PLAN,CAPABILITY=hybrid.CAPABILITY,
            load_plan=load_plan,write_json=write_json,sha=sha,EdgeLink=EdgeLink,decorate=decorate,
            remaining=remaining,FRAME_FIELDS=base.FRAME_FIELDS+EXTRA_FIELDS,__file__=__file__)
    exec(compile(adapted_source(),'<coupling-frozen-pipeline-adapter>','exec'),ns)
    final=hybrid.replace_once(inspect.getsource(base.finalize_run),
                 'from analyze_rate_dvfs_gate import summarize,read_csv','from analyze_coupling import summarize,read_csv')
    exec(compile(final,'<coupling-frozen-finalizer>','exec'),ns)
    return ns['run_one'],ns['finalize_run']

def check_inputs():
    ns=dict(hybrid.__dict__,load_plan=load_plan,adapted_source=adapted_source)
    plan=types.FunctionType(hybrid.check_inputs.__code__,ns)()
    for path,digest in plan['authoritative_evidence_sha256'].items():
        if sha(ROOT/path)!=digest:raise RuntimeError('evidence SHA mismatch: '+path)
    if sha(ROOT/plan['cache']['path'])!=plan['cache']['sha256']:
        raise RuntimeError('cache SHA mismatch')
    return plan

def campaign():
    # Same child exit/timeout/frequency restoration finalization, no historical smoke prerequisite.
    ns=dict(hybrid.__dict__,OUT=OUT,PLAN=PLAN,__file__=__file__,check_inputs=check_inputs,
            load_plan=load_plan,bindings=bindings,write_json=write_json)
    code=inspect.getsource(hybrid.campaign)
    code=hybrid.replace_once(code,'admission_fps_per_stream=30,',"admission_fps_per_stream=25+c['edge_r'], edge_r=c['edge_r'],")
    code=hybrid.replace_once(code,"return 0 if mode=='primary' or smoke_pass(plan) else 1",
        "return 0 if all(json.loads((OUT/c['run_id']/'summary.json').read_text()).get('integrity_status')=='VALID' for c in plan['order']) else 1")
    exec(compile(code,'<coupling-frozen-supervisor>','exec'),ns)
    return ns['campaign']('pilot')

if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('action',choices=['check','pilot','one']);ap.add_argument('--run-id');args=ap.parse_args()
    if args.action=='check':
        check_inputs();bindings();print('CPU/input/adapter PASS; no GPU/network/clock action');code=0
    elif args.action=='one':
        p=check_inputs();cs=[c for c in p['order'] if c['run_id']==args.run_id]
        if len(cs)!=1:raise RuntimeError('unplanned run ID')
        code=bindings()[0](cs[0],args.run_id)
    else:code=campaign()
    raise SystemExit(code)
