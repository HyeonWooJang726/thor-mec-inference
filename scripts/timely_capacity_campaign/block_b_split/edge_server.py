"""New plan/session launcher; byte-identical existing C1 backend and pruning END protocol."""
import argparse
import json
from pathlib import Path
import socket
import time
import traceback
import formal_protocol as p
import pruning_edge_server as old
from campaign_config import expected_order,preflight_order


def expected(c,digest,phase,cache_sha):
    if phase=='preflight':
        return dict(mode='timely_capacity_preflight',rate=c['rate'],seconds=30,repeat=1,run_id=c['run_id'],
            campaign_plan_sha256=digest,cache_sha256=cache_sha,payload_origin='CACHED_REAL_RAW640_30; no decode/Local inference',deadline_ms=100)
    return dict(mode='timely_capacity_campaign',repeat=c['repeat'],rate=8*c['edge_r'],seconds=60,
        run_id=c['run_id'],campaign_plan_sha256=digest,cell=c['cell'],target_service_FPS=c['target_service_FPS'],
        frequency_MHz=1575,deadline_ms=100,cache_sha256=cache_sha,
        payload_origin='LIVE_K8_DECODE_RESIZE; cache used for Edge warmup ONLY')


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--phase',choices=['preflight','primary'],required=True)
    for k in ('plan','engine','cache','output','approve-plan-sha256'):ap.add_argument('--'+k,required=True)
    a=ap.parse_args();digest=p.sha(a.plan)
    if digest!=a.approve_plan_sha256:raise RuntimeError('Explicit block-B hash required')
    plan=json.loads(Path(a.plan).read_text())
    if plan['block']!='B' or plan['order']!=expected_order('B') or plan['edge_preflight_order']!=preflight_order():raise RuntimeError('Wrong frozen order')
    for name,h in plan['edge_dependency_sha256'].items():
        if p.sha(Path(__file__).with_name(name))!=h:raise RuntimeError('Edge dependency mismatch: '+name)
    out=Path(a.output);out.mkdir(parents=True,exist_ok=False)
    try:
        helpers=p.load_runtime_helpers();gpu=helpers.validate_edge(a);helpers.load_cache(a.cache)
        conditions=plan['edge_preflight_order'] if a.phase=='preflight' else plan['order']
        p.save(out/'campaign_manifest.json',dict(plan_sha256=digest,phase=a.phase,conditions=conditions,gpu=gpu,
            C_E=1,B=1,port=5000,CUDA_Graph=False,dynamic_batching=False))
        results=[]
        with socket.socket(socket.AF_INET,socket.SOCK_STREAM) as listener:
            listener.bind(('0.0.0.0',5000));listener.listen(1)
            print(f'LISTENING port=5000; {len(conditions)} {a.phase} sessions',flush=True)
            for c in conditions:
                with listener.accept()[0] as conn:
                    conn.settimeout(300)
                    s=old.serve_session(conn,out/c['run_id'],expected(c,digest,a.phase,helpers.CACHE_SHA256),lambda:old.Backend(a))
                results.append(dict(run_id=c['run_id'],integrity_status=s['integrity_status']))
                print(results[-1],flush=True)
                if s['integrity_status']!='VALID':break
        p.save(out/'campaign_status.json',dict(planned=len(conditions),completed=len(results),runs=results))
        return 0 if len(results)==len(conditions) and all(x['integrity_status']=='VALID' for x in results) else 1
    except BaseException:
        p.save(out/'failure.json',dict(error=traceback.format_exc()));return 1


if __name__=='__main__':raise SystemExit(main())
