#!/usr/bin/env python3
"""Only session launcher changes; reuse frozen C1 RAW640 service on port 5000."""
import argparse,json,socket,traceback
from pathlib import Path
import formal_protocol as p
from formal_server import Backend,serve_session

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    for key in ('engine','cache','plan','output'):ap.add_argument('--'+key,required=True)
    args=ap.parse_args();out=Path(args.output);out.mkdir(parents=True,exist_ok=False)
    try:
        plan=json.loads(Path(args.plan).read_text())
        if plan['freeze_status']!='FROZEN_COUPLING_PILOT_AB':raise RuntimeError('invalid plan')
        for name,digest in plan['edge_dependency_sha256'].items():
            if p.sha(Path(__file__).with_name(name))!=digest:raise RuntimeError('source hash mismatch: '+name)
        helpers=p.load_runtime_helpers();gpu=helpers.validate_edge(args);helpers.load_cache(args.cache)
        conditions=[c for c in plan['order'] if c['edge_r']>0]
        assert [c['edge_r'] for c in conditions]==[1,2,3,5,5,3,2,1]
        assert [c['repeat'] for c in conditions]==[1]*4+[2]*4
        p.save(out/'campaign_manifest.json',dict(plan_sha256=p.sha(args.plan),conditions=conditions,gpu=gpu,
           provenance=p.provenance(),C_E=1,B=1,port=5000,zero_edge='Thor-only control; no session',
           input='Live K8 decode/resize; cache warmup only'))
        results=[]
        with socket.socket(socket.AF_INET,socket.SOCK_STREAM) as listener:
            listener.bind(('0.0.0.0',5000));listener.listen(1)
            print('LISTENING port=5000; eight nonzero Edge sessions in A/B order; E=0 has no connection',flush=True)
            for c in conditions:
                expected=dict(mode='coupling_pilot',repeat=c['repeat'],rate=8*c['edge_r'],seconds=c['seconds'],run_id=c['run_id'],
                              coupling_plan_sha256=p.sha(args.plan),
                              payload_origin='LIVE_K8_DECODE_RESIZE; cache used for Edge warmup ONLY')
                with listener.accept()[0] as conn:
                    conn.settimeout(300)
                    s=serve_session(conn,out/c['run_id'],expected,lambda:Backend(args))
                results.append(dict(run_id=c['run_id'],integrity_status=s['integrity_status']));print(results[-1],flush=True)
        p.save(out/'campaign_status.json',dict(planned=8,completed=len(results),runs=results))
        return 0 if all(s['integrity_status']=='VALID' for s in results) else 1
    except BaseException:
        p.save(out/'failure.json',dict(traceback=traceback.format_exc()));return 1
if __name__=='__main__':raise SystemExit(main())
