"""Frozen E48 timing/masks and C_E sensitivity order; CPU-only."""
import hashlib
import importlib.util
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OUT = ROOT/'results/timely_capacity_campaign/v2_2/edge_inflight_robustness02'
PLAN = OUT/'plan.json'
IDLE_SECONDS = 10
PAYLOAD_BYTES = 691200

_previous_path = HERE.parent/'edge_e48_confirmation01/config.py'
_spec = importlib.util.spec_from_file_location('frozen_e48_config',_previous_path)
previous = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(previous)


def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1<<20),b''):
            h.update(block)
    return h.hexdigest()


def q6():
    return previous.q(48)


def bit(pattern, sid, frame):
    return previous.bit(48,pattern,sid,frame)


def schedule(pattern):
    return previous.schedule(48,pattern)


def condition(c_e, repeat, pattern, index):
    if c_e not in (1,2) or repeat not in (1,2) or pattern not in ('ALIGNED','STAGGERED'):
        raise ValueError('Unplanned Edge C/rate/pattern/repeat')
    token='A' if pattern=='ALIGNED' else 'S'
    return {'run_id':f'EDGEINFLIGHT02_CE{c_e}_R{repeat}_{token}',
            'stage':'MEASURED','rate':48,'per_stream_rate':6,'pattern':pattern,
            'repeat':repeat,'order_index':index,'seconds':30,'deadline_ms':100,
            'source_streams':8,'source_FPS_per_stream':30,
            'phase_vector':[0]*8 if pattern=='ALIGNED' else list(range(8)),
            'edge_C':c_e,'edge_B':1}


SEQUENCE=((1,1,'ALIGNED'),(1,1,'STAGGERED'),
          (2,1,'ALIGNED'),(2,1,'STAGGERED'),
          (2,2,'STAGGERED'),(2,2,'ALIGNED'),
          (1,2,'STAGGERED'),(1,2,'ALIGNED'))


def frozen_order():
    return [condition(*row,index+1) for index,row in enumerate(SEQUENCE)]


def hello(c,digest,cache_sha):
    return {'mode':'edge_inflight_robustness02','rate':48,'seconds':30,
            'repeat':c['repeat'],'run_id':c['run_id'],'campaign_plan_sha256':digest,
            'cache_sha256':cache_sha,
            'payload_origin':'CACHED_REAL_RAW640_30; K8_30FPS_SOURCE_SLOT_SELECTION',
            'deadline_ms':100,'admission_pattern':c['pattern'],
            'phase_vector':c['phase_vector'],'stage':'MEASURED','edge_C':c['edge_C']}


def validate_source_rows(rows,c,start):
    return previous.validate_source_rows(rows,c,start)


def load_plan():
    plan=json.loads(PLAN.read_text())
    if sha(PLAN)!=(OUT/'plan.sha256').read_text().strip():
        raise RuntimeError('Plan SHA mismatch')
    if plan['order']!=frozen_order() or plan['deadline_ms']!=100 or \
            plan['payload_bytes']!=PAYLOAD_BYTES or plan['idle_seconds']!=IDLE_SECONDS:
        raise RuntimeError('Frozen E48 scientific plan mismatch')
    if plan['session_plan_sha256']!=sha(OUT/'session_plan.json'):
        raise RuntimeError('Session plan SHA mismatch')
    session=json.loads((OUT/'session_plan.json').read_text())
    if session['order']!=plan['order']:
        raise RuntimeError('Session plan order mismatch')
    if plan['preregistration_sha256']!=sha(OUT/'EDGE_INFLIGHT_PREREGISTRATION.md'):
        raise RuntimeError('Preregistration SHA mismatch')
    for name,digest in plan['source_sha256'].items():
        if sha(ROOT/name)!=digest:
            raise RuntimeError('Frozen source drift: '+name)
    return plan
