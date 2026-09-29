"""Local-only admission refinement with frozen canonical source/pruning semantics."""
from functools import lru_cache
import json
from pathlib import Path
import sys
import types

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts/d100_timely_capacity_map'))
import map_common as parent
import run_map_d100 as proven_runner
import analyze_map_d100 as proven_analysis
import analyze_best_of_grid as best_grid
canonical,prior=parent.canonical,parent.prior
sha,remaining=parent.sha,parent.remaining
OUT=ROOT/'results/local_d100_refinement'
PLAN=OUT/'plan.json'
PREFLIGHT=OUT/'frequency_preflight.json'
TARGETS=(168,176,184,192)
GRID=(160,168,176,184,192,200,240)
ORDERS=((168,176,184,192),(192,184,176,168),(176,192,168,184))

# Rebind a private copy, never mutate the existing canonical module or its cache.
cells=dict(canonical.CELLS,**{f'T{n}-A':(n,n,0) for n in TARGETS})
fn=canonical.schedule.__wrapped__
schedule=lru_cache(None)(types.FunctionType(fn.__code__,dict(fn.__globals__,CELLS=cells)))
fn=canonical.decorate
canonical_decorate=types.FunctionType(fn.__code__,dict(fn.__globals__,schedule=schedule,CELLS=cells))
fn=parent.pruning.decorate
_decorate=types.FunctionType(fn.__code__,dict(fn.__globals__,canonical=types.SimpleNamespace(decorate=canonical_decorate)))


def decorate(row,start,target,mode,deadline_ms):
    if mode!='A' or target not in GRID or deadline_ms!=100:raise ValueError('Local-only D100 grid required')
    return _decorate(row,start,target,mode,deadline_ms)


def EdgeLink(c,*args,**kwargs):
    if c['edge_r']!=0 or c['supply_mode']!='A':raise RuntimeError('Edge is forbidden')
    return prior.UnusedEdgeLink(c,*args,**kwargs)


def expected_order():
    return [dict(run_id=f'LDR_R{repeat}_L{n}_P01',kind='formal',repeat=repeat,order_index=(repeat-1)*4+i+1,
        cell=f'L{n}',supply_mode='A',target_service_FPS=n,local_r=n//8,edge_r=0,deadline_ms=100,
        K=8,C=2,r=30,frequency='F1575',frequency_MHz=1575,seconds=60,pass_name=f'R{repeat}',**{'pass':f'R{repeat}'})
        for repeat,order in enumerate(ORDERS,1) for i,n in enumerate(order)]


def placement_manifest():
    return dict(source_phase_ns=[0]*8,source_clock='t0+floor(frame_index*1e9/30)',
        physical_decode_resize_FPS=240,admission='floor((f+1)*r/30)>floor(f*r/30)',
        network='NO_CONNECTION',placement='Every admitted frame LOCAL; exclusion after physical decode AND resize',
        cells={f'L{n}':dict(admitted_frame_ids_mod30=list(schedule(n,'A')[0]),edge_slots=[]) for n in TARGETS})


def load_plan():
    p=json.loads(PLAN.read_text())
    if (p['freeze_status']!='FROZEN_LOCAL_D100_REFINEMENT_V1' or p['order']!=expected_order()
        or p['placement']!=placement_manifest() or p['smoke'] or p['deadlines_ms']!=[100]):
        raise RuntimeError('Frozen refinement plan mismatch')
    return p


def require_preflight():
    r=json.loads(PREFLIGHT.read_text())
    if r.get('status')!='PASS' or r.get('plan_sha256')!=sha(PLAN):raise RuntimeError('Current preflight required')
    return dict(path=str(PREFLIGHT.relative_to(ROOT)),sha256=sha(PREFLIGHT))
