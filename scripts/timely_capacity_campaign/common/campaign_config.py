"""Pure frozen configuration, admission and placement. No runtime/device imports."""
from collections import Counter
from functools import lru_cache
import hashlib
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
BLOCKS = {'A': 'block_a_stagger', 'B': 'block_b_split'}
IDLE_SECONDS = 10
SPLITS = ((240,200,40),(240,184,56),(240,176,64),(240,168,72),(240,160,80),
          (200,184,16),(200,176,24),(200,168,32),(200,160,40))


def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda:f.read(1048576),b''): h.update(b)
    return h.hexdigest()


def out(block): return ROOT/'results/timely_capacity_campaign'/BLOCKS[block]


def shifts(rate, pattern):
    if pattern == 'ALIGNED': return (0,)*8
    if pattern != 'STAGGERED' or rate not in (22,23,24): raise ValueError('Unplanned pattern/rate')
    g=math.gcd(rate,30)
    phases=[(k*30//8)//g*g for k in range(8)]
    return tuple(next(o for o in range(30) if o*rate%30==a) for a in phases)


@lru_cache(None)
def schedule(target, edge, pattern='ALIGNED'):
    if target%8 or edge%8 or not 0<=edge<=target<=240: raise ValueError('Invalid split')
    rate=target//8
    masks=tuple(tuple(f for f in range(30) if (f+o+1)*rate//30>(f+o)*rate//30)
                for o in shifts(rate,pattern))
    slots={}
    if edge:
        if pattern!='ALIGNED': raise ValueError('No staggered Edge block')
        admitted=masks[0];first=admitted[0]*10**9//30
        for q in range(edge):
            release=first+q*10**9//edge
            frame=max(f for f in admitted if f*10**9//30<=release)
            key=q%8,frame
            if key in slots: raise ValueError('Duplicate Edge identity')
            slots[key]=q,release
    return masks,slots


def decorate(row,start,c):
    sid,f=int(row['stream_id']),int(row['frame_id'])
    if sid not in range(8) or row['logical_arrival_ns']!=start+f*10**9//30: raise ValueError('Source due mismatch')
    second,slot=divmod(f,30)
    masks,edge=schedule(c['target_service_FPS'],8*c['edge_r'],c['admission_pattern'])
    row['admitted']=int(slot in masks[sid]);row['placement']='LOCAL' if row['admitted'] else 'SKIP'
    for k in ('edge_request_id','edge_release_target_ns','absolute_deadline_ns'): row.pop(k,None)
    if row['admitted']: row['absolute_deadline_ns']=row['logical_arrival_ns']+100_000_000
    if (sid,slot) in edge:
        q,release=edge[sid,slot]
        row.update(placement='EDGE',edge_request_id=second*8*c['edge_r']+q,
                   edge_release_target_ns=start+second*10**9+release)
    return row


def expected_order(block):
    rows=[]
    def add(rep,target,local,edge,pattern):
        cell=f'L{local}-{pattern}' if block=='A' else f'S{target}-L{local}E{edge}'
        rows.append(dict(run_id=f'TCC{block}_R{rep}_{cell.replace("-","_")}_P01',kind='formal',
            repeat=rep,order_index=len(rows)+1,cell=cell,block=block,supply_mode='B' if edge else 'A',
            admission_pattern=pattern,target_service_FPS=target,local_r=local//8,edge_r=edge//8,
            deadline_ms=100,K=8,C=2,r=30,frequency='F1575',frequency_MHz=1575,seconds=60,
            pass_name=f'R{rep}',**{'pass':f'R{rep}'}))
    if block=='A':
        for rep,loads in enumerate(((176,184,192),(192,184,176),(184,176,192)),1):
            for load in loads:
                for pattern in (('ALIGNED','STAGGERED') if rep%2 else ('STAGGERED','ALIGNED')):
                    add(rep,load,load,0,pattern)
    else:
        orders=((0,5,1,6,2,7,3,8,4),(4,8,3,7,2,6,1,5,0),(2,7,3,8,4,0,5,1,6),
                (6,1,5,2),(2,5,1,6))
        for rep,indices in enumerate(orders,1):
            for i in indices: add(rep,*SPLITS[i],'ALIGNED')
    return rows


def preflight_order():
    return [dict(run_id=f'TCCB_PREFLIGHT_E{r}_P01',rate=r,seconds=30,repeat=1) for r in (56,72,80)]


def placement_manifest(block):
    entries={}
    for c in expected_order(block):
        masks,slots=schedule(c['target_service_FPS'],8*c['edge_r'],c['admission_pattern'])
        entries[c['cell']]=dict(shifts=list(shifts(c['target_service_FPS']//8,c['admission_pattern'])),
            admitted_frame_ids_mod30=[list(x) for x in masks],edge_slots=[dict(stream_id=k[0],frame_id_mod30=k[1],request_id=v[0],release_ns=v[1]) for k,v in slots.items()])
    return dict(source_phase_ns=[0]*8,source_due='t0+floor(frame_index*1e9/30)',
        physical_decode_resize_FPS=240,pattern='cyclic rotation of the existing floor-accumulator mask; no source-time shift',cells=entries)


def load_plan(block):
    path=out(block)/'plan.json';p=json.loads(path.read_text())
    frozen=(path.with_suffix('.sha256')).read_text().split()[0]
    if sha(path)!=frozen or p['order']!=expected_order(block) or p['placement']!=placement_manifest(block): raise ValueError('Frozen plan mismatch')
    if p['idle_seconds']!=IDLE_SECONDS or p['block']!=block or p['deadlines_ms']!=[100]:raise ValueError('Campaign semantics mismatch')
    return p
