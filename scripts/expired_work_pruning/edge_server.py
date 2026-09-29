#!/usr/bin/env python3
"""Unchanged Edge inference; END accounts for Thor-expired, never-submitted IDs."""
import argparse
import inspect
import json
from pathlib import Path
import socket
import traceback
import formal_protocol as p
import formal_server as original
Backend=original.Backend


def partition_end(meta,seen,count):
    expired=meta.get('expired_request_ids')
    if not isinstance(expired,list) or any(type(x) is not int or not 0<=x<count for x in expired):
        raise ValueError('Malformed expiry ledger')
    if expired!=sorted(set(expired)) or set(expired)&seen or seen|set(expired)!=set(range(count)):
        raise ValueError('Missing/duplicate/overlapping terminal IDs')
    if meta.get('assigned')!=count or meta.get('submitted')!=len(seen):raise ValueError('END count mismatch')
    return expired


def adapted_session_source():
    s=inspect.getsource(original.serve_session)
    old="if meta.get('submitted') != count or len(seen) != count:\n                    raise ValueError('END accounting mismatch')"
    if s.count(old)!=1:raise RuntimeError('Frozen server hook changed')
    return s.replace(old,"expired = partition_end(meta, seen, count)\n"
        "                shared['expired_request_ids'] = expired\n"
        "                shared['client_expired_before_submission'] = len(expired)\n"
        "                shared['assigned'] = count")


ns=dict(original.__dict__,partition_end=partition_end)
exec(compile(adapted_session_source(),'<pruning-END-accounting-only>','exec'),ns)
serve_session=ns['serve_session']


def conditions(plan):
    orders=(((200,100),(240,150),(200,150),(240,100)),
            ((240,100),(200,150),(240,150),(200,100)),
            ((200,150),(200,100),(240,100),(240,150)))
    if plan['freeze_status']!='FROZEN_EXPIRED_WORK_PRUNING_V1' or len(plan['order'])!=12 or plan['smoke']:
        raise ValueError('Wrong campaign')
    for index,c in enumerate(plan['order']):
        repeat=index//4+1;target,d=orders[repeat-1][index%4]
        if (c['run_id']!=f'EWP_R{repeat}_P{target}_D{d}_P01' or c['repeat']!=repeat
            or c['deadline_ms']!=d or c['target_service_FPS']!=target or c['supply_mode']!='B'
            or c['cell']!=f'P{target}-D{d}' or c['order_index']!=index+1
            or (c['local_r'],c['edge_r'])!=((23,2) if target==200 else (25,5))
            or (c['frequency_MHz'],c['K'],c['C'],c['seconds'])!=(1575,8,2,60)):
            raise ValueError('Frozen condition mismatch')
    return plan['order']


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    for key in ('engine','cache','plan','output'):ap.add_argument('--'+key,required=True)
    args=ap.parse_args();out=Path(args.output);out.mkdir(parents=True,exist_ok=False)
    try:
        plan=json.loads(Path(args.plan).read_text());cs=conditions(plan)
        for name,digest in plan['edge_dependency_sha256'].items():
            if p.sha(Path(__file__).with_name(name))!=digest:raise RuntimeError('Dependency hash mismatch: '+name)
        h=p.load_runtime_helpers();gpu=h.validate_edge(args);h.load_cache(args.cache)
        p.save(out/'campaign_manifest.json',dict(plan_sha256=p.sha(args.plan),conditions=cs,
            gpu=gpu,provenance=p.provenance(),C_E=1,B=1,port=5000,
            pruning='Thor waiting-only; Edge received requests never cancelled'))
        results=[]
        with socket.socket(socket.AF_INET,socket.SOCK_STREAM) as listener:
            listener.bind(('0.0.0.0',5000));listener.listen(1)
            print('LISTENING port=5000; 12 pruning sessions; no Edge-side cancellation',flush=True)
            for c in cs:
                expected=dict(mode='expired_work_pruning',repeat=c['repeat'],rate=8*c['edge_r'],seconds=60,
                    run_id=c['run_id'],pruning_plan_sha256=p.sha(args.plan),cell=c['cell'],
                    target_service_FPS=c['target_service_FPS'],frequency_MHz=1575,deadline_ms=c['deadline_ms'],
                    payload_origin='LIVE_K8_DECODE_RESIZE; cache used for Edge warmup ONLY')
                with listener.accept()[0] as conn:
                    conn.settimeout(300);s=serve_session(conn,out/c['run_id'],expected,lambda:Backend(args))
                results.append(dict(run_id=c['run_id'],integrity_status=s['integrity_status']))
                print(results[-1],flush=True)
        p.save(out/'campaign_status.json',dict(planned=12,completed=len(results),runs=results))
        return 0 if all(s['integrity_status']=='VALID' for s in results) else 1
    except BaseException:
        p.save(out/'failure.json',dict(traceback=traceback.format_exc()));return 1


if __name__=='__main__':raise SystemExit(main())
