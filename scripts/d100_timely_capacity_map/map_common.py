"""D100 paired map: frozen canonical placement and proven waiting-only pruning."""
import json
from pathlib import Path
import sys
import types

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts/expired_work_pruning'))
import pruning_common as pruning
import run_pruning as proven_runner
import analyze_pruning as proven_analysis
canonical,prior=pruning.canonical,pruning.prior
sha,remaining,decorate=pruning.sha,pruning.remaining,pruning.decorate
OUT=ROOT/'results/d100_timely_capacity_map'
PLAN=OUT/'plan.json'
PREFLIGHT=OUT/'frequency_preflight.json'
ORDERS=(('T160-A','T160-B','T200-B','T200-A','T240-A','T240-B'),
        ('T240-B','T240-A','T200-A','T200-B','T160-B','T160-A'),
        ('T200-A','T200-B','T240-B','T240-A','T160-A','T160-B'))


def expected_order():
    rows=[]
    for repeat,cells in enumerate(ORDERS,1):
        for cell in cells:
            target,local,edge=canonical.CELLS[cell]
            rows.append(dict(run_id=f'DTC_R{repeat}_{cell.replace("-","_")}_P01',kind='formal',repeat=repeat,
                order_index=len(rows)+1,cell=cell,supply_mode=cell[-1],target_service_FPS=target,
                local_r=local//8,edge_r=edge//8,deadline_ms=100,K=8,C=2,r=30,
                frequency='F1575',frequency_MHz=1575,seconds=60,pass_name=f'R{repeat}',**{'pass':f'R{repeat}'}))
    return rows


def load_plan():
    p=json.loads(PLAN.read_text())
    if (p['freeze_status']!='FROZEN_D100_TIMELY_CAPACITY_MAP_V1' or p['order']!=expected_order()
        or p['source_phase_ns']!=[0]*8 or p['smoke'] or p['deadlines_ms']!=[100]
        or p['placement']!=canonical.placement_manifest()):raise RuntimeError('Frozen D100 plan mismatch')
    return p


def hello(c,run_id,plan_sha):
    h=pruning.hello(c,run_id,plan_sha)
    h['mode']='d100_timely_capacity_map'
    h['map_plan_sha256']=h.pop('pruning_plan_sha256')
    return h


class ActiveEdgeLink(pruning.EdgeLink):
    pass


fn=pruning.EdgeLink.__init__
ActiveEdgeLink.__init__=types.FunctionType(fn.__code__,dict(fn.__globals__,hello=hello),
    fn.__name__,fn.__defaults__,fn.__closure__)


def EdgeLink(c,*args,**kwargs):
    return (prior.UnusedEdgeLink if c['edge_r']==0 else ActiveEdgeLink)(c,*args,**kwargs)


def require_preflight():
    r=json.loads(PREFLIGHT.read_text())
    if r.get('status')!='PASS' or r.get('plan_sha256')!=sha(PLAN):raise RuntimeError('Passing map preflight required')
    return dict(path=str(PREFLIGHT.relative_to(ROOT)),sha256=sha(PREFLIGHT))
