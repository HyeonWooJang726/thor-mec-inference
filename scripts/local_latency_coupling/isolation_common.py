"""Fixed Equal-Service B200 Local identities; only complementary Edge activity varies."""
import importlib.util
import json
from pathlib import Path
import sys
import types

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts/equal_service_map'))
import common as equal
import run_map as proven_runner
import analyze_map as proven_analysis
OUT=ROOT/'results/local_latency_coupling'
PLAN=OUT/'plan.json'
PREFLIGHT=OUT/'frequency_preflight.json'
sha,remaining,prior=equal.sha,equal.remaining,equal.prior
ORDER=('A','B','B','A','A','B')


def expected_order():
    return [dict(run_id=f'LLCI_R{i//2+1}_{mode}_P01',kind='pilot',repeat=i//2+1,order_index=i+1,
        cell=mode,supply_mode=mode,target_service_FPS=184 if mode=='A' else 200,
        local_r=23,edge_r=0 if mode=='A' else 2,K=8,C=2,r=30,frequency='F1413',
        frequency_MHz=1413,seconds=60,pass_name=f'R{i//2+1}',**{'pass':f'R{i//2+1}'}) for i,mode in enumerate(ORDER)]


def decorate(row,start,target,mode):
    if (mode,target) not in (('A',184),('B',200)):raise ValueError('Unplanned isolation condition')
    equal.decorate(row,start,200,'B')
    if mode=='A' and row['placement']=='EDGE':
        row.update(placement='SKIP',admitted=0)
        row.pop('edge_request_id',None);row.pop('edge_release_target_ns',None)
    return row


def placement_manifest():
    rows={mode:[decorate(dict(stream_id=s,frame_id=f,logical_arrival_ns=f*10**9//30),0,184 if mode=='A' else 200,mode)
               for f in range(30) for s in range(8)] for mode in ('A','B')}
    return dict(origin='Frozen Equal-Service B200 schedule; A excludes B200 Edge IDs, NOT standalone A184 schedule',
        common_decode_resize_FPS=240,local_FPS=184,edge_FPS={'A':0,'B':16},
        cells={mode:{str(s):{path:[r['frame_id'] for r in rows[mode] if r['stream_id']==s and r['placement']==path]
              for path in ('LOCAL','EDGE','SKIP')} for s in range(8)} for mode in ('A','B')},
        B_edge_slots=equal.placement_manifest()['cells']['B200']['edge_slots'],
        source_clock='Unchanged 30-FPS logical arrival; Edge eligibility never moves admission',
        A_network='NO_CONNECTION',exclusions='Explicit admission exclusions after common decode+resize; no service drop')


def load_plan():
    p=json.loads(PLAN.read_text())
    if p['freeze_status']!='FROZEN_LOCAL_LATENCY_ISOLATION_V1' or p['order']!=expected_order() or p['smoke']:
        raise RuntimeError('Frozen isolation order mismatch')
    if p['placement']!=placement_manifest():raise RuntimeError('Frozen identity schedule mismatch')
    return p


def hello(c,run_id,plan_sha):
    return dict(mode='local_latency_isolation',repeat=c['repeat'],rate=16,seconds=c['seconds'],
        run_id=run_id,isolation_plan_sha256=plan_sha,cell=c['cell'],
        target_service_FPS=c['target_service_FPS'],frequency_MHz=1413,
        cache_sha256=prior.old.edge_runtime.CACHE_SHA256,
        payload_origin='LIVE_K8_DECODE_RESIZE; cache used for Edge warmup ONLY')


class ActiveLink(prior.ActiveEdgeLink):pass
_init=prior.ActiveEdgeLink.__init__
ActiveLink.__init__=types.FunctionType(_init.__code__,dict(_init.__globals__,hello=hello),
                                     _init.__name__,_init.__defaults__,_init.__closure__)
def EdgeLink(c,*args,**kwargs):
    return (prior.UnusedEdgeLink if c['edge_r']==0 else ActiveLink)(c,*args,**kwargs)


def require_preflight():
    record=json.loads(PREFLIGHT.read_text())
    if record.get('status')!='PASS' or record.get('plan_sha256')!=sha(PLAN):raise RuntimeError('Current passing preflight required')
    return dict(path=str(PREFLIGHT.relative_to(ROOT)),sha256=sha(PREFLIGHT))
