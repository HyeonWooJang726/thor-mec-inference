#!/usr/bin/env python3
"""Canonical runner with two non-preemptive expiry checks; no pipeline redesign."""
import inspect
import types
from pruning_common import (ROOT,OUT,PLAN,PREFLIGHT,sha,remaining,prior,canonical_runner,canonical,
    load_plan,decorate,EdgeLink,require_preflight,FIELDS)
base=canonical.proven_runner
frequency=base.frequency


def write_json(path,data):
    if path.parent.parent!=OUT:raise RuntimeError('Writer outside pruning run')
    base.base.write_json(path,data)


def adapted_source():
    s=canonical_runner.adapted_source();rep=prior.hybrid.replace_once
    s=rep(s,'from analyze_timely import summarize','from analyze_pruning import summarize')
    s=rep(s,"experiment='CANONICAL_TIMELY_SERVICE'","experiment='EXPIRED_WORK_PRUNING', deadline_ms=condition['deadline_ms']")
    s=rep(s,'from local_latency_breakdown_metrics import QueueAccounting',
          'from pruning_common import PruningAccounting as QueueAccounting')
    s=rep(s,"condition['target_service_FPS'],condition['supply_mode'])",
          "condition['target_service_FPS'],condition['supply_mode'],condition['deadline_ms'])")
    s=rep(s,"with lock:accounting.start(job,time.monotonic_ns)",
          "with lock:execute=accounting.begin(job,time.monotonic_ns)\n"
          "                        if not execute:\n                            del job['tensor']\n                            continue")
    s=rep(s,"job['c_ns']=time.monotonic_ns()","job['c_ns']=time.monotonic_ns()\n                        job['terminal_state']='COMPLETED'")
    s=rep(s,"{'enqueue':accounting.n_enqueue,'start':accounting.n_start}",
          "{'enqueue':accounting.n_enqueue,'start':accounting.n_start,'expired':accounting.n_expired}")
    s=rep(s,'accounting.n_enqueue!=accounting.n_start','accounting.n_enqueue!=accounting.n_start+accounting.n_expired')
    return s


def bindings():
    ns=dict(base.__dict__,OUT=OUT,PLAN=PLAN,__file__=__file__,load_plan=load_plan,
        write_json=write_json,sha=sha,EdgeLink=EdgeLink,decorate=decorate,remaining=remaining,
        require_preflight=require_preflight,adapted_source=adapted_source,frequency=frequency)
    s=inspect.getsource(base.bindings).replace('from analyze_map import summarize,read_csv','from analyze_pruning import summarize,read_csv')
    s=prior.hybrid.replace_once(s,'FRAME_FIELDS=base.FRAME_FIELDS+prior.EXTRA_FIELDS',
        'FRAME_FIELDS=base.FRAME_FIELDS+prior.EXTRA_FIELDS+PRUNING_FIELDS')
    ns['PRUNING_FIELDS']=FIELDS
    exec(compile(s,'<pruning-bindings>','exec'),ns)
    return ns['bindings']()


def check_inputs():
    fn=base.check_inputs
    return types.FunctionType(fn.__code__,dict(fn.__globals__,load_plan=load_plan,bindings=bindings))()


def frequency_preflight():
    fn=base.frequency_preflight
    return types.FunctionType(fn.__code__,dict(fn.__globals__,PREFLIGHT=PREFLIGHT,PLAN=PLAN,
        load_plan=load_plan,frequency=frequency))()


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
        check_inputs=check_inputs,load_plan=load_plan,require_preflight=require_preflight,
        bindings=bindings,campaign=campaign))()


if __name__=='__main__':raise SystemExit(main())
