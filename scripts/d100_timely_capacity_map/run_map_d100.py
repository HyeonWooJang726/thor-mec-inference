#!/usr/bin/env python3
"""D100 map supervisor; execution is explicit, preparation/check is read-only."""
import inspect
import types
from map_common import ROOT,OUT,PLAN,PREFLIGHT,sha,remaining,decorate,EdgeLink,require_preflight,load_plan,proven_runner,prior

base=proven_runner.base
frequency=proven_runner.frequency


def write_json(path,data):
    if path.parent.parent!=OUT:raise RuntimeError('Writer outside D100 run')
    base.base.write_json(path,data)


def adapted_source():
    s=proven_runner.adapted_source();rep=prior.hybrid.replace_once
    s=rep(s,'from analyze_pruning import summarize','from analyze_map_d100 import summarize')
    s=rep(s,"experiment='EXPIRED_WORK_PRUNING'","experiment='D100_TIMELY_CAPACITY_MAP'")
    return s


def bindings():
    ns=dict(proven_runner.__dict__,OUT=OUT,PLAN=PLAN,__file__=__file__,load_plan=load_plan,
        write_json=write_json,sha=sha,EdgeLink=EdgeLink,decorate=decorate,remaining=remaining,
        require_preflight=require_preflight,adapted_source=adapted_source,frequency=frequency)
    s=inspect.getsource(proven_runner.bindings)
    s=prior.hybrid.replace_once(s,'from analyze_pruning import summarize,read_csv','from analyze_map_d100 import summarize,read_csv')
    exec(compile(s,'<D100-bindings>','exec'),ns)
    return ns['bindings']()


def check_inputs():
    fn=base.check_inputs
    return types.FunctionType(fn.__code__,dict(fn.__globals__,load_plan=load_plan,bindings=bindings))()


def frequency_preflight():
    fn=base.frequency_preflight
    return types.FunctionType(fn.__code__,dict(fn.__globals__,PREFLIGHT=PREFLIGHT,PLAN=PLAN,load_plan=load_plan,frequency=frequency))()


def campaign():
    p=load_plan()
    if PREFLIGHT.exists() or any((OUT/c['run_id']).exists() for c in p['order']):raise RuntimeError('No retry/overwrite')
    fn=base.campaign
    return types.FunctionType(fn.__code__,dict(fn.__globals__,OUT=OUT,PLAN=PLAN,__file__=__file__,
        check_inputs=check_inputs,load_plan=load_plan,bindings=bindings,write_json=write_json,
        frequency=frequency,frequency_preflight=frequency_preflight))()


def main():
    fn=base.main
    return types.FunctionType(fn.__code__,dict(fn.__globals__,OUT=OUT,PLAN=PLAN,
        check_inputs=check_inputs,load_plan=load_plan,require_preflight=require_preflight,bindings=bindings,campaign=campaign))()


if __name__=='__main__':raise SystemExit(main())
