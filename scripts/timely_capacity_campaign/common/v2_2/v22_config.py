"""V2.2 validation configuration. Frozen B1 workload; recording/control provenance only."""
import json
from pathlib import Path
import sys
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[3]
OUT=ROOT/'results/timely_capacity_campaign/v2_2/validation01'
PLAN=OUT/'plan.json'
sys.path.insert(0,str(HERE.parent/'service_phase_b1'))
import b1_common as b1
sha=b1.sha
IDLE_SECONDS=10


def order():
    rows=[]
    for index,(enabled,rep) in enumerate(((True,1),(False,1),(True,2),(True,3)),1):
        c=dict(b1.order()[1 if enabled else 0]);mode='ON' if enabled else 'OFF'
        c.update(run_id=f'V22_LOCAL200_{mode}_R{rep}_P01',order_index=index,repeat=rep,block='V22',
                 cell='LOCAL200-'+mode,original_cell='LOCAL200-'+mode,analysis_class='V22-CONTROLLED',
                 pass_name='R'+str(rep),**{'pass':'R'+str(rep)})
        rows.append(c)
    return rows


def load_plan():
    p=json.loads(PLAN.read_text())
    if sha(PLAN)!=PLAN.with_suffix('.sha256').read_text().split()[0]:raise RuntimeError('V22 plan changed')
    if p['order']!=order() or p['smoke'] or p['idle_seconds']!=IDLE_SECONDS or p['source_phase_ns']!=[0]*8:raise RuntimeError('Frozen V22 order/config mismatch')
    b1.load_plan();b1.runtime_record();return p


def runtime_record():
    path=OUT/'runtime_manifest.json'
    if sha(path)!=(OUT/'runtime_manifest.sha256').read_text().split()[0]:raise RuntimeError('Frozen V22 runtime changed')
    r=json.loads(path.read_text())
    for path,h in r['source_sha256'].items():
        if sha(ROOT/path)!=h:raise RuntimeError('Frozen source changed: '+path)
    return dict(version='V2.2_CONTROLLED',runtime_manifest_sha256=sha(OUT/'runtime_manifest.json'),source_sha256=r['source_sha256'],condition_plan_sha256=sha(PLAN))
