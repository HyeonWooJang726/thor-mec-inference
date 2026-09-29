#!/usr/bin/env python3
"""Hybrid session launcher around unchanged formal C1 receiver/inference worker."""
import argparse
import json
from pathlib import Path
import socket
import traceback

import formal_protocol as p
from formal_server import Backend, serve_session


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--mode',choices=['smoke','primary'],required=True)
    ap.add_argument('--engine',required=True)
    ap.add_argument('--cache',required=True)
    ap.add_argument('--plan',required=True)
    ap.add_argument('--output',required=True)
    args=ap.parse_args()
    out=Path(args.output);out.mkdir(parents=True,exist_ok=False)
    try:
        plan=json.loads(Path(args.plan).read_text())
        if plan['freeze_status']!='FROZEN_HYBRID_200_LOCAL_40_EDGE':raise RuntimeError('invalid frozen plan')
        for name,digest in plan['edge_dependency_sha256'].items():
            if p.sha(Path(__file__).with_name(name))!=digest:raise RuntimeError('Edge source hash mismatch: '+name)
        helpers=p.load_runtime_helpers();gpu=helpers.validate_edge(args);helpers.load_cache(args.cache)
        conditions=plan['smoke'] if args.mode=='smoke' else plan['order']
        p.save(out/'campaign_manifest.json',dict(mode=args.mode,plan_sha256=p.sha(args.plan),
               conditions=conditions,gpu=gpu,provenance=p.provenance(),port=5000,
               cache_role='warmup only; primary requests are live Thor K8 decode/resize',C_E=1,B=1))
        results=[]
        with socket.socket(socket.AF_INET,socket.SOCK_STREAM) as listener:
            listener.bind(('0.0.0.0',5000));listener.listen(1)
            print('LISTENING port=5000 hybrid '+args.mode,flush=True)
            for c in conditions:
                expected=dict(mode='hybrid_smoke' if c['kind']=='smoke' else 'hybrid_primary',
                    repeat=c.get('repeat',0),rate=40,seconds=c['seconds'],run_id=c['run_id'],
                    hybrid_plan_sha256=p.sha(args.plan),
                    payload_origin='LIVE_K8_DECODE_RESIZE; cache used for Edge warmup ONLY')
                with listener.accept()[0] as conn:
                    conn.settimeout(300)
                    s=serve_session(conn,out/c['run_id'],expected,lambda:Backend(args))
                    results.append(dict(run_id=c['run_id'],integrity_status=s['integrity_status']))
                    print(results[-1],flush=True)
        p.save(out/'campaign_status.json',dict(planned=len(conditions),completed=len(results),runs=results))
        return 0 if all(r['integrity_status']=='VALID' for r in results) else 1
    except BaseException:
        p.save(out/'failure.json',dict(traceback=traceback.format_exc()))
        return 1


if __name__=='__main__':raise SystemExit(main())
