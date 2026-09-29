#!/usr/bin/env python3
"""Nine B sessions only; unchanged formal C1/B1 RAW640 Backend and wire protocol."""
import argparse
import json
from pathlib import Path
import socket
import traceback
import formal_protocol as p
from formal_server import Backend, serve_session


def conditions(plan):
    if plan['freeze_status']!='FROZEN_CANONICAL_TIMELY_SERVICE_V1':
        raise RuntimeError('Wrong plan')
    orders=(('T160-A','T160-B','T200-B','T200-A','T240-A','T240-B'),
            ('T240-B','T240-A','T200-A','T200-B','T160-B','T160-A'),
            ('T200-A','T200-B','T240-B','T240-A','T160-A','T160-B'))
    splits={'T160-A':(20,0),'T160-B':(18,2),'T200-A':(25,0),
            'T200-B':(23,2),'T240-A':(30,0),'T240-B':(25,5)}
    rows=plan['order']
    if len(rows)!=18 or plan['smoke'] or plan['placement']['source_phase_ns']!=[0]*8:
        raise RuntimeError('Wrong campaign size/source phase')
    for index,c in enumerate(rows):
        repeat=index//6+1; cell=orders[repeat-1][index%6]
        if (c['cell']!=cell or c['repeat']!=repeat or c['order_index']!=index+1
            or c['run_id']!=f'CTSM_R{repeat}_{cell.replace("-","_")}_P01'
            or (c['local_r'],c['edge_r'])!=splits[cell]
            or c['target_service_FPS']!=int(cell[1:4]) or c['supply_mode']!=cell[-1]
            or c['seconds']!=60 or c['frequency_MHz']!=1575 or c['K']!=8 or c['C']!=2):
            raise RuntimeError('Frozen condition/order mismatch')
    return [c for c in rows if c['supply_mode']=='B']


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    for key in ('engine','cache','plan','output'):ap.add_argument('--'+key,required=True)
    args=ap.parse_args();out=Path(args.output);out.mkdir(parents=True,exist_ok=False)
    try:
        plan=json.loads(Path(args.plan).read_text());cs=conditions(plan)
        for name,digest in plan['edge_dependency_sha256'].items():
            if p.sha(Path(__file__).with_name(name))!=digest:
                raise RuntimeError('Edge dependency hash mismatch: '+name)
        h=p.load_runtime_helpers();gpu=h.validate_edge(args);h.load_cache(args.cache)
        p.save(out/'campaign_manifest.json',dict(plan_sha256=p.sha(args.plan),conditions=cs,
            gpu=gpu,provenance=p.provenance(),C_E=1,B=1,port=5000,
            input='Live K8 decode/resize; existing cache for warmup only',zero_edge='NO CONNECTION'))
        results=[]
        with socket.socket(socket.AF_INET,socket.SOCK_STREAM) as listener:
            listener.bind(('0.0.0.0',5000));listener.listen(1)
            print('LISTENING port=5000; 9 B sessions in frozen18-run order; A never connects',flush=True)
            for c in cs:
                expected=dict(mode='canonical_timely_service',repeat=c['repeat'],rate=8*c['edge_r'],seconds=60,
                    run_id=c['run_id'],timely_plan_sha256=p.sha(args.plan),cell=c['cell'],
                    target_service_FPS=c['target_service_FPS'],frequency_MHz=1575,
                    payload_origin='LIVE_K8_DECODE_RESIZE; cache used for Edge warmup ONLY')
                with listener.accept()[0] as conn:
                    conn.settimeout(300)
                    s=serve_session(conn,out/c['run_id'],expected,lambda:Backend(args))
                results.append(dict(run_id=c['run_id'],integrity_status=s['integrity_status']))
                print(results[-1],flush=True)
        p.save(out/'campaign_status.json',dict(planned=9,completed=len(results),runs=results))
        return 0 if all(s['integrity_status']=='VALID' for s in results) else 1
    except BaseException:
        p.save(out/'failure.json',dict(traceback=traceback.format_exc()));return 1


if __name__=='__main__':
    raise SystemExit(main())
