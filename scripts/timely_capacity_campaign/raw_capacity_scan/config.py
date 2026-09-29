"""Raw scan plan adapter only; frozen V2.2 worker source remains untouched."""
import json
import sys
from pathlib import Path
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
OUT=ROOT/'results/timely_capacity_campaign/v2_2/raw_capacity_scan01'
PLAN=OUT/'plan.json'
sys.path.insert(0,str(HERE.parent/'common/v2_2'))
import v22_config as frozen
from v22_builder import run_source
sha=frozen.sha


def order():
    rows=[]
    for rep,rates in ((1,(200,208,216,224,232,240)),(2,(240,232,224,216,208,200))):
        for rate in rates:
            c=dict(frozen.order()[1]);cell=f'LOCAL{rate}-OFF'
            c.update(run_id=f'V22_RAW_R{rep}_L{rate}_P01',repeat=rep,order_index=len(rows)+1,
                target_service_FPS=rate,local_r=rate//8,admission_r=rate//8,admitted_FPS=rate,
                source_demand_FPS=240,cell=cell,original_cell=cell,block='V22_RAW',
                analysis_class='CANONICAL_ALIGNED_RAW_SCAN',pass_name=f'R{rep}',**{'pass':f'R{rep}'})
            rows.append(c)
    return rows


def runtime_record():
    result=frozen.runtime_record()
    p=OUT/'FINAL_RUNTIME_MANIFEST.json'
    record=json.loads(p.read_text())
    if sha(frozen.OUT/'effective_runtime.txt')!=record['effective_runtime_sha256']:raise RuntimeError('Frozen effective worker changed')
    import hashlib
    if hashlib.sha256(run_source().encode()).hexdigest()!=record['effective_runtime_sha256']:raise RuntimeError('Worker source drift')
    for path,h in json.loads((OUT/'source_sha256.json').read_text()).items():
        if sha(ROOT/path)!=h:raise RuntimeError('Raw scan preparation source changed: '+path)
    return dict(result,raw_scan_plan_sha256=sha(PLAN))


def load_plan():
    p=json.loads(PLAN.read_text())
    if sha(PLAN)!=(OUT/'plan.sha256').read_text().strip():raise RuntimeError('Raw scan plan SHA mismatch')
    if p['order']!=order() or p['idle_seconds']!=10 or p['source_phase_ns']!=[0]*8 or p['smoke']:raise RuntimeError('Frozen order/config mismatch')
    runtime_record();return p
