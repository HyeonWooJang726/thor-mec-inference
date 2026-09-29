"""Equal-service admission and staggered placement; no hardware access on import."""
import json
import sys
import types
from functools import lru_cache
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'scripts/hybrid_coupling_pilot'))
import pilot_common as prior
OUT = ROOT/'results/equal_service_map'
PLAN = OUT/'plan.json'
PREFLIGHT = OUT/'frequency_preflight.json'
sha, remaining = prior.sha, prior.remaining
CELLS = {'A160':(160,1107,160,0),'B160':(160,945,144,16),
         'A176':(176,1260,176,0),'B176':(176,1107,160,16),
         'A184':(184,1413,184,0),'B184':(184,1260,176,8),
         'A200':(200,1575,200,0),'B200':(200,1413,184,16)}
ORDERS = (('A160','B160','B176','A176','A184','B184','B200','A200'),
          ('A200','B200','B184','A184','A176','B176','B160','A160'),
          ('A176','B176','B160','A160','A200','B200','B184','A184'))


def expected_order():
    result=[]
    for repeat, order in enumerate(ORDERS,1):
        for cell in order:
            target,freq,local,edge=CELLS[cell]
            result.append(dict(run_id=f'ESM_R{repeat}_{cell}_P01',kind='formal',repeat=repeat,
                order_index=len(result)+1,cell=cell,target_service_FPS=target,supply_mode=cell[0],
                local_r=local//8,edge_r=edge//8,K=8,C=2,r=30,frequency=f'F{freq}',
                frequency_MHz=freq,seconds=60,pass_name=f'R{repeat}',**{'pass':f'R{repeat}'}))
    return result


@lru_cache(None)
def schedule(target,mode):
    """Phase accumulator admission; Edge subset with regular eligibility slots.

    Source arrivals never move. Eligibility starts at the first admitted source
    instant. q selects stream q%8; choose latest admitted frame not after slot.
    This retains equal per-stream quotas and unchanged A/B admitted identities.
    """
    total,freq,local,edge=CELLS[f'{mode}{target}'];r=total//8
    admitted=tuple(f for f in range(30) if (f+1)*r//30 > f*r//30)
    slots={}
    if edge:
        first=admitted[0]*10**9//30
        for q in range(edge):
            release=first+q*10**9//edge
            f=max(f for f in admitted if f*10**9//30<=release)
            key=(q%8,f)
            if key in slots:raise RuntimeError('Duplicate Edge frame')
            slots[key]=(q,release)
    return admitted,slots


def decorate(row,start,target,mode):
    sid,f=int(row['stream_id']),int(row['frame_id']);second,within=divmod(f,30)
    admitted,slots=schedule(target,mode)
    row['admitted']=int(within in admitted)
    row['placement']='LOCAL' if row['admitted'] else 'SKIP'
    row.pop('edge_request_id',None);row.pop('edge_release_target_ns',None)
    if (sid,within) in slots:
        q,offset=slots[sid,within];edge=CELLS[f'{mode}{target}'][3]
        row.update(placement='EDGE',edge_request_id=second*edge+q,
                   edge_release_target_ns=start+second*10**9+offset)
        if row['edge_release_target_ns']<row['logical_arrival_ns']:raise RuntimeError('Early Edge release')
    return row


def placement_manifest():
    return dict(common_decode_resize_FPS=240,source_FPS_per_stream=30,
        admission='floor((f+1)*r/30)>floor(f*r/30), r=target/8; same A/B IDs',
        unadmitted='SKIP after decode AND resize; no service/drop',
        edge_eligibility='uniform slots starting at first admitted frame; q%8 stream, latest admitted frame not later than slot; no logical-arrival shift',
        cells={cell:dict(admitted_frame_ids_mod30=list(schedule(s,cell[0])[0]),
             edge_slots=[dict(stream_id=sid,frame_id_mod30=f,request_id_mod_second=q,release_offset_ns=ns)
                         for (sid,f),(q,ns) in sorted(schedule(s,cell[0])[1].items(),key=lambda x:x[1][0])])
               for cell,(s,_,_,_) in CELLS.items()})


def load_plan():
    p=json.loads(PLAN.read_text())
    if p['freeze_status']!='FROZEN_EQUAL_SERVICE_V1' or p['order']!=expected_order() or p['smoke']:
        raise RuntimeError('Frozen plan/order mismatch')
    if p['placement']!=placement_manifest():raise RuntimeError('Frozen placement mismatch')
    return p


def hello(c,run_id,plan_sha):
    return dict(mode='equal_service_map',repeat=c['repeat'],rate=8*c['edge_r'],seconds=c['seconds'],
        run_id=run_id,equal_service_plan_sha256=plan_sha,cell=c['cell'],
        target_service_FPS=c['target_service_FPS'],frequency_MHz=c['frequency_MHz'],
        cache_sha256=prior.old.edge_runtime.CACHE_SHA256,
        payload_origin='LIVE_K8_DECODE_RESIZE; cache used for Edge warmup ONLY')


class ActiveLink(prior.ActiveEdgeLink):pass
_init=prior.ActiveEdgeLink.__init__
ActiveLink.__init__=types.FunctionType(_init.__code__,dict(_init.__globals__,hello=hello),
                                     _init.__name__,_init.__defaults__,_init.__closure__)
def EdgeLink(c,*args,**kwargs):
    return (prior.UnusedEdgeLink if not c['edge_r'] else ActiveLink)(c,*args,**kwargs)


def require_preflight():
    p=json.loads(PREFLIGHT.read_text())
    if p.get('status')!='PASS' or p.get('plan_sha256')!=sha(PLAN):raise RuntimeError('Current passing preflight required')
    return dict(path=str(PREFLIGHT.relative_to(ROOT)),sha256=sha(PREFLIGHT))
