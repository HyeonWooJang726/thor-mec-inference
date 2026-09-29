"""Portable Edge launcher. No execution on import; unchanged C1 worker/backend."""
import argparse
import json
from pathlib import Path
import socket
import traceback
import formal_protocol as wire
import pruning_edge_server as prior
import config_v2 as conf

def expected(c,digest,phase,cache_sha):
    if phase=='preflight':
        return dict(mode='timely_capacity_preflight_v2',rate=c['rate'],seconds=30,repeat=c['repeat'],run_id=c['run_id'],
            campaign_plan_sha256=digest,cache_sha256=cache_sha,payload_origin='CACHED_REAL_RAW640_30; no decode/Local inference',deadline_ms=100)
    return dict(mode='timely_capacity_campaign_v2',rate=8*c['edge_r'],seconds=60,repeat=c['repeat'],run_id=c['run_id'],
        campaign_plan_sha256=digest,cache_sha256=cache_sha,payload_origin='LIVE_K8_DECODE_RESIZE; cache used for Edge warmup ONLY',
        cell=c['cell'],target_service_FPS=c['target_service_FPS'],frequency_MHz=1575,deadline_ms=100)

def main():
    ap=argparse.ArgumentParser()
    for k in ('plan','engine','cache','output','approve-plan-sha256'):ap.add_argument('--'+k,required=True)
    a=ap.parse_args();digest=wire.sha(a.plan)
    if digest!=a.approve_plan_sha256:raise RuntimeError('Exact phase plan SHA required')
    p=json.loads(Path(a.plan).read_text());phase=p['phase']
    assert p['order']==(conf.preflight_order() if phase=='preflight' else conf.order(p['E_max']))
    for name,h in p['edge_dependency_sha256'].items():
        if wire.sha(Path(__file__).with_name(name))!=h:raise RuntimeError('Edge dependency changed: '+name)
    out=Path(a.output);out.mkdir(parents=True,exist_ok=False)
    try:
        helpers=wire.load_runtime_helpers();gpu=helpers.validate_edge(a);helpers.load_cache(a.cache)
        wire.save(out/'campaign_manifest.json',dict(plan_sha256=digest,conditions=p['order'],phase=phase,gpu=gpu,C_E=1,B=1,port=5000,CUDA_Graph=False,dynamic_batching=False))
        results=[]
        with socket.socket(socket.AF_INET,socket.SOCK_STREAM) as listener:
            listener.bind(('0.0.0.0',5000));listener.listen(1)
            print(f'LISTENING 5000: {len(p["order"])} {phase} sessions',flush=True)
            for c in p['order']:
                with listener.accept()[0] as conn:
                    conn.settimeout(300)
                    s=prior.serve_session(conn,out/c['run_id'],expected(c,digest,phase,helpers.CACHE_SHA256),lambda:prior.Backend(a))
                results.append(dict(run_id=c['run_id'],integrity_status=s['integrity_status']))
                print(results[-1],flush=True)
                if s['integrity_status']!='VALID':break
        wire.save(out/'campaign_status.json',dict(planned=len(p['order']),completed=len(results),runs=results))
        return 0 if len(results)==len(p['order']) and all(r['integrity_status']=='VALID' for r in results) else 1
    except BaseException:wire.save(out/'failure.json',dict(error=traceback.format_exc()));return 1

if __name__=='__main__':raise SystemExit(main())
