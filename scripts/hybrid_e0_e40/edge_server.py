#!/usr/bin/env python3
"""Formal five E40 sessions, unchanged C1 RAW640 Backend; E0 never connects."""
import argparse
import json
from pathlib import Path
import socket
import traceback
import formal_protocol as p
from formal_server import Backend, serve_session


def conditions(plan):
    assert plan['freeze_status'] == 'FROZEN_FORMAL_E0_E40_V1'
    rates = [0,40,40,0,0,40,40,0,0,40]
    assert len(plan['order']) == len(rates)
    for i, (c, rate) in enumerate(zip(plan['order'], rates)):
        assert (c['run_id'], c['repeat'], c['edge_r'], c['seconds'], c['K'], c['C']) == (
            f'HEF_R{i//2+1}_E{rate:02d}_P01', i//2+1, rate//8, 60, 8, 2)
    return [c for c in plan['order'] if c['edge_r'] == 5]


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
            print('LISTENING port=5000; five E40 sessions, rounds 1..5; E0 has no connection', flush=True)
            for c in cs:
                expected = dict(mode='formal_e0_e40', repeat=c['repeat'], rate=40, seconds=60,
                    run_id=c['run_id'], formal_plan_sha256=p.sha(args.plan),
                    payload_origin='LIVE_K8_DECODE_RESIZE; cache used for Edge warmup ONLY')
                with listener.accept()[0] as conn:
                    conn.settimeout(300)
                    s = serve_session(conn, out/c['run_id'], expected, lambda:Backend(args))
                results.append(dict(run_id=c['run_id'], integrity_status=s['integrity_status']))
                print(results[-1], flush=True)
        p.save(out/'campaign_status.json', dict(planned=5, completed=len(results), runs=results))
        return 0 if all(s['integrity_status']=='VALID' for s in results) else 1
    except BaseException:
        p.save(out/'failure.json', dict(traceback=traceback.format_exc()))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
