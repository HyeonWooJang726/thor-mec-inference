#!/usr/bin/env python3
"""Local-latency isolation three B sessions, unchanged C1 RAW640 Backend; A modes never connects."""
import argparse
import json
from pathlib import Path
import socket
import traceback
import formal_protocol as p
from formal_server import Backend, serve_session


def conditions(plan):
    if plan['freeze_status']!='FROZEN_LOCAL_LATENCY_ISOLATION_V1':raise RuntimeError('Wrong plan')
    if len(plan['order'])!=6 or [c['supply_mode'] for c in plan['order']]!=['A','B','B','A','A','B'] or len({c['run_id'] for c in plan['order']})!=6:raise RuntimeError('Wrong order')
    cs=[c for c in plan['order'] if c['supply_mode']=='B']
    if len(cs)!=3 or any(c['seconds']!=60 or c['edge_r']!=2 or c['local_r']!=23 or c['frequency_MHz']!=1413 or c['K']!=8 or c['C']!=2 for c in cs):raise RuntimeError('Wrong Edge plan')
    return cs


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    for key in ('engine','cache','plan','output'):
        ap.add_argument('--'+key, required=True)
    args = ap.parse_args()
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=False)
    try:
        plan = json.loads(Path(args.plan).read_text())
        cs = conditions(plan)
        for name, digest in plan['edge_dependency_sha256'].items():
            if p.sha(Path(__file__).with_name(name)) != digest:
                raise RuntimeError('Edge dependency hash mismatch: '+name)
        h = p.load_runtime_helpers()
        gpu = h.validate_edge(args)
        h.load_cache(args.cache)
        p.save(out/'campaign_manifest.json', dict(plan_sha256=p.sha(args.plan), conditions=cs,
            gpu=gpu, provenance=p.provenance(), C_E=1, B=1, port=5000,
            input='Live K8 decode/resize; existing cache for warmup only', zero_edge='NO CONNECTION'))
        results = []
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.bind(('0.0.0.0',5000))
            listener.listen(1)
            print('LISTENING port=5000; 3 B sessions in frozen 6-run order; A modes has no connection', flush=True)
            for c in cs:
                expected = dict(mode='local_latency_isolation', repeat=c['repeat'], rate=8*c['edge_r'], seconds=60,
                    run_id=c['run_id'], isolation_plan_sha256=p.sha(args.plan), cell=c['cell'], target_service_FPS=c['target_service_FPS'], frequency_MHz=c['frequency_MHz'],
                    payload_origin='LIVE_K8_DECODE_RESIZE; cache used for Edge warmup ONLY')
                with listener.accept()[0] as conn:
                    conn.settimeout(300)
                    s = serve_session(conn, out/c['run_id'], expected, lambda:Backend(args))
                results.append(dict(run_id=c['run_id'], integrity_status=s['integrity_status']))
                print(results[-1], flush=True)
        p.save(out/'campaign_status.json', dict(planned=3, completed=len(results), runs=results))
        return 0 if all(s['integrity_status']=='VALID' for s in results) else 1
    except BaseException:
        p.save(out/'failure.json', dict(traceback=traceback.format_exc()))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
