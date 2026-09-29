#!/usr/bin/env python3
"""Frozen Equal-Service runner reuse; check is CPU/read-only, campaign is explicit."""
import inspect
import types
from isolation_common import (ROOT,OUT,PLAN,PREFLIGHT,sha,remaining,prior,proven_runner,
                              load_plan,decorate,EdgeLink,require_preflight)
frequency=proven_runner.frequency


def write_json(path,data):
    if path.parent.parent!=OUT:raise RuntimeError('Writer outside new isolation run directory')
    proven_runner.base.write_json(path,data)


def adapted_source():
    s=proven_runner.adapted_source()
    s=prior.hybrid.replace_once(s,'from analyze_map import summarize','from analyze_isolation import summarize')
    return prior.hybrid.replace_once(s,"experiment='EQUAL_SERVICE_MAP'","experiment='LOCAL_LATENCY_COUPLING_ISOLATION'")


def bindings():
    # Only namespace, plan, placement and analyzer change; pipeline body is unchanged.
    ns=dict(proven_runner.__dict__,OUT=OUT,PLAN=PLAN,__file__=__file__,load_plan=load_plan,
        write_json=write_json,sha=sha,EdgeLink=EdgeLink,decorate=decorate,remaining=remaining,
        require_preflight=require_preflight,adapted_source=adapted_source,frequency=frequency)
    s=inspect.getsource(proven_runner.bindings).replace('from analyze_map import summarize,read_csv',
                                                     'from analyze_isolation import summarize,read_csv')
    exec(compile(s,'<isolation-existing-bindings>','exec'),ns)
    return ns['bindings']()


def check_inputs():
    fn=proven_runner.check_inputs
    return types.FunctionType(fn.__code__,dict(fn.__globals__,load_plan=load_plan,bindings=bindings))()


def frequency_preflight():
    # Future campaign only; same helper/order/restore, pilot target 1413 rather than1575.
    ns=dict(proven_runner.__dict__,PREFLIGHT=PREFLIGHT,PLAN=PLAN,load_plan=load_plan,frequency=frequency)
    s=inspect.getsource(proven_runner.frequency_preflight)
    s=prior.hybrid.replace_once(s,'with frequency.pinned(1575):','with frequency.pinned(1413):')
    s=prior.hybrid.replace_once(s,'(1575000000, 1575000000)','(1413000000, 1413000000)')
    exec(compile(s,'<isolation-existing-preflight>','exec'),ns)
    return ns['frequency_preflight']()


def campaign():
    fn=proven_runner.campaign
    ns=dict(fn.__globals__,OUT=OUT,PLAN=PLAN,__file__=__file__,check_inputs=check_inputs,
            load_plan=load_plan,bindings=bindings,write_json=write_json,frequency=frequency,frequency_preflight=frequency_preflight)
    return types.FunctionType(fn.__code__,ns)()


def main():
    fn=proven_runner.main
    ns=dict(fn.__globals__,OUT=OUT,PLAN=PLAN,check_inputs=check_inputs,load_plan=load_plan,
            require_preflight=require_preflight,bindings=bindings,campaign=campaign)
    return types.FunctionType(fn.__code__,ns)()

if __name__=='__main__':raise SystemExit(main())
