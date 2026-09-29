"""Single approved B0 session; original Edge worker/protocol are reused byte-for-byte."""
import argparse
import json
from pathlib import Path
import socket
import traceback
import edge_v2 as frozen

RUN_ID='SPI_B0_S240_L176E64_ON_P01'
PLAN_SHA='d8cb78b2c549b4505819302d1d5653c7f929d35b8562d39a3fe5145e399a3b56'


def main():
    ap=argparse.ArgumentParser()
    for key in ('plan','engine','cache','output','approve-plan-sha256'):ap.add_argument('--'+key,required=True)
    args=ap.parse_args();p=json.loads(Path(args.plan).read_text())
    assert frozen.wire.sha(args.plan)==args.approve_plan_sha256==PLAN_SHA
    assert len(p['order'])==1
    c=p['order'][0]
    assert c['run_id']==RUN_ID and (c['seconds'],c['local_r'],c['edge_r'],c['target_service_FPS'])==(60,22,8,240)
    original=next(r for r in frozen.conf.order(72) if r['run_id']==p['B0_original_run_id'])
    assert {k:v for k,v in c.items() if k not in ('run_id','order_index')}=={k:v for k,v in original.items() if k not in ('run_id','order_index')}
    for name,h in p['edge_dependency_sha256'].items():
        assert frozen.wire.sha(Path(__file__).with_name(name))==h,name
    out=Path(args.output);out.mkdir(parents=True,exist_ok=False)
    try:
        helpers=frozen.wire.load_runtime_helpers();gpu=helpers.validate_edge(args);helpers.load_cache(args.cache)
        frozen.wire.save(out/'campaign_manifest.json',dict(plan_sha256=PLAN_SHA,conditions=[c],gpu=gpu,C_E=1,B=1,port=5000,scope='B0_ONLY',CUDA_Graph=False,dynamic_batching=False))
        with socket.socket(socket.AF_INET,socket.SOCK_STREAM) as listener:
            listener.bind(('0.0.0.0',5000));listener.listen(1)
            print('LISTENING 5000: B0 ONLY '+RUN_ID+' plan='+PLAN_SHA,flush=True)
            with listener.accept()[0] as conn:
                conn.settimeout(300)
                summary=frozen.prior.serve_session(conn,out/RUN_ID,frozen.expected(c,PLAN_SHA,'campaign',helpers.CACHE_SHA256),lambda:frozen.prior.Backend(args))
        frozen.wire.save(out/'campaign_status.json',dict(planned=1,completed=1,runs=[dict(run_id=RUN_ID,integrity_status=summary['integrity_status'])]))
        print(summary['integrity_status'],flush=True)
        return 0 if summary['integrity_status']=='VALID' else 1
    except BaseException:
        frozen.wire.save(out/'failure.json',dict(error=traceback.format_exc()));return 1

if __name__=='__main__':raise SystemExit(main())
