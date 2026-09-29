"""Campaign parameters only; no GPU/network/system side effects."""
import hashlib
import json
import sys
from pathlib import Path
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
OUT=ROOT/'results/timely_capacity_campaign/v2_2/timely_capacity_scan01'
PLAN=OUT/'plan.json'
sys.path.insert(0,str(HERE.parent/'raw_capacity_scan'))
import config as raw
sys.path.insert(0,str(HERE.parent/'common'))
import campaign_config as canonical
frozen=raw.frozen
sha=raw.sha
run_source=raw.run_source
GRIDS={100:(200,208,212,216,224,240),67:(192,200,208,216)}


def order():
    rows=[]
    for D,rates in GRIDS.items():
        for rep,sequence in ((1,rates),(2,tuple(reversed(rates)))):
            for rate in sequence:
                c=dict(frozen.order()[0]);cell=f'D{D}-LOCAL{rate}-ON'
                c.update(run_id=f'V22_TIMELY_D{D}_R{rep}_L{rate}_P01',repeat=rep,order_index=len(rows)+1,
                    target_service_FPS=rate,local_r=rate/8,admission_r=rate/8,admitted_FPS=rate,
                    source_demand_FPS=240,cell=cell,original_cell=cell,block='V22_TIMELY',deadline_ms=D,
                    analysis_class='CANONICAL_ALIGNED_DEADLINE_SCAN',pass_name=f'R{rep}',**{'pass':f'R{rep}'})
                rows.append(c)
    return rows


def decorate(row,start,c):
    rate=c['target_service_FPS'];D=c['deadline_ms']
    if c['edge_r']!=0 or c['admission_pattern']!='ALIGNED' or D not in GRIDS or rate not in GRIDS[D]:raise ValueError('Outside timely plan')
    if rate%8==0:
        canonical.decorate(row,start,c)
    else:
        # Same rational floor accumulator; 212/240=53/60. No per-stream phase shift.
        k,f=int(row['stream_id']),int(row['frame_id'])
        if k not in range(8) or row['logical_arrival_ns']!=start+f*10**9//30:raise ValueError('Source due mismatch')
        row['admitted']=int((f+1)*rate//240>f*rate//240)
        row['placement']='LOCAL' if row['admitted'] else 'SKIP'
        for key in ('edge_request_id','edge_release_target_ns','absolute_deadline_ns'):row.pop(key,None)
    if row['admitted']:row['absolute_deadline_ns']=row['logical_arrival_ns']+D*1_000_000
    return row


def runtime_record():
    r=frozen.runtime_record()
    if run_source()!=(frozen.OUT/'effective_runtime.txt').read_text():raise RuntimeError('Frozen V2.2 worker changed')
    for name,h in json.loads((OUT/'source_sha256.json').read_text()).items():
        if sha(ROOT/name)!=h:raise RuntimeError('Timely campaign source drift: '+name)
    return dict(r,timely_plan_sha256=sha(PLAN),worker_source_sha256=hashlib.sha256(run_source().encode()).hexdigest(),
                parameter_adapter_sha256=sha(HERE/'timely_config.py'))


def load_plan():
    p=json.loads(PLAN.read_text())
    if sha(PLAN)!=(OUT/'plan.sha256').read_text().strip():raise RuntimeError('Plan drift')
    if p['order']!=order() or p['source_phase_ns']!=[0]*8 or p['idle_seconds']!=10 or p['smoke']:raise RuntimeError('Campaign config mismatch')
    runtime_record();return p
