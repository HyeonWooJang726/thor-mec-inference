"""Fixed Local frame identities; deterministic thinning of complementary Edge slots."""
from pathlib import Path
import json,sys,inspect,textwrap,threading
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts/hybrid_capacity_extension'))
import hybrid_common as old
import run_hybrid as hybrid
import edge_link as transport
OUT=ROOT/'results/hybrid_coupling_pilot'
PLAN=OUT/'plan_ab.json'
RATES=(0,1,2,3,5)
sha=old.sha
remaining=old.remaining
EXTRA_FIELDS=old.EXTRA_FIELDS

def edge_slots(e):
    """40 original 25-ms eligibility slots/s, phase accumulator per stream.

    For candidate cycle j=0..4 and stream s, accumulator starts s mod 5.
    Select if floor(((j+1)*e+s%5)/5)>floor((j*e+s%5)/5).
    Local complement is invariant. No shifted logical source arrivals.
    """
    return [q for q in range(40) if (((q//8+1)*e+q%8%5)//5 > ((q//8)*e+q%8%5)//5)]

def decorate(row,start,e):
    old.decorate(row,start)
    if row['placement']=='LOCAL':row['admitted']=1;return row
    old_id=row['edge_request_id'];second,q=divmod(old_id,40);slots=edge_slots(e)
    if q in slots:
        row['edge_request_id']=second*(8*e)+slots.index(q)
        row['admitted']=1
    else:
        row['placement']='SKIP';row['admitted']=0
        row.pop('edge_request_id',None);row.pop('edge_release_target_ns',None)
    return row

def hello(c,run_id,plan_sha):
    return dict(mode='coupling_pilot',repeat=c['repeat'],rate=8*c['edge_r'],seconds=c['seconds'],run_id=run_id,
                cache_sha256=old.edge_runtime.CACHE_SHA256,coupling_plan_sha256=plan_sha,
                payload_origin='LIVE_K8_DECODE_RESIZE; cache used for Edge warmup ONLY')

def load_plan():
    p=json.loads(PLAN.read_text())
    if p['freeze_status']!='FROZEN_COUPLING_PILOT_AB':raise RuntimeError('wrong pilot plan')
    assert not p['smoke'] and [c['edge_r'] for c in p['order']]==list(RATES)+list(reversed(RATES))
    assert len({c['run_id'] for c in p['order']})==10
    assert p['placement']['edge_frame_residues_mod6']==list(old.RESIDUES)
    assert p['placement']['selected_25ms_slots_per_second']=={str(e):edge_slots(e) for e in RATES}
    for index,c in enumerate(p['order']):
        assert (c['K'],c['C'],c['r'],c['frequency'],c['seconds'])==(8,2,30,'HIGH',10)
        assert (c['repeat'],c['pass'],c['order_index'])==(1 if index<5 else 2,'A' if index<5 else 'B',index+1)
    return p

# Reuse sender/receiver/private row bookkeeping unchanged. Only expected request
# count and HELLO change; constructor fails closed if frozen hook shape changes.
class ActiveEdgeLink(transport.EdgeLink):pass
s=textwrap.dedent(inspect.getsource(transport.EdgeLink.__init__))
s=hybrid.replace_once(s,"int(condition['seconds']*40)","int(condition['seconds']*8*condition['edge_r'])")
ns=dict(transport.__dict__,hello=hello)
exec(compile(s,'<pilot-variable-count-edge-constructor>','exec'),ns)
ActiveEdgeLink.__init__=ns['__init__']

class UnusedEdgeLink:
    """Explicit E=0 no-network path, not a fabricated Edge measurement."""
    def __init__(self,condition,run_id,manifest,directory,fail,plan_sha,host,transport=None):
        assert condition['edge_r']==0
        self.done=threading.Event();self.done.set();self.manifest=manifest
        manifest.update(edge_usage='NOT_USED',edge_ready={'status':'NOT_USED_NO_CONNECTION'})
    def put(self,*args):raise RuntimeError('Edge request forbidden at E=0')
    def finish(self):pass
    def close(self):self.manifest.update(edge_threads_exited=True,edge_path_errors=[],edge_final={'status':'NOT_USED'})

def EdgeLink(condition,*args,**kwargs):
    return (UnusedEdgeLink if condition['edge_r']==0 else ActiveEdgeLink)(condition,*args,**kwargs)
