"""Frozen B1 ON runtime; CPU policy is changed manually, never by this module."""
import json
from pathlib import Path
import sys
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[3]
OUT=ROOT/'results/timely_capacity_campaign/pruning_path_audit/service_phase_validation/b1f_01'
PLAN=OUT/'plan.json'
RUN_ID='SPI_B1F_LOCAL200_ON_CPU_PIN_P01'
sys.path.insert(0,str(HERE.parent/'service_phase_b1'))
import b1_common as b1
sha=b1.sha


def condition():
    c=dict(b1.order()[1]);c.update(run_id=RUN_ID,order_index=1,block='B1F',cell='LOCAL200-ON-CPU-PIN',
        original_cell='LOCAL200-ON-CPU-PIN',analysis_class='B1F-DIAGNOSTIC')
    return c


STARTUP="""        from cpu_state import require_pinned
        manifest['CPU_pin_child_readback']=require_pinned()
        manifest['python_switch_interval_readback_s']=__import__('sys').getswitchinterval()
"""


def run_source():
    return b1.build_adapter.replace_one(b1.run_source(),"        manifest['environment_before']=environment()",
        STARTUP+"        manifest['environment_before']=environment()")


def load_plan():
    p=json.loads(PLAN.read_text())
    if sha(PLAN)!=PLAN.with_suffix('.sha256').read_text().split()[0]:raise RuntimeError('B1F frozen plan mismatch')
    if p['order']!=[condition()] or p['smoke'] or p['source_phase_ns']!=[0]*8 or p['idle_seconds']!=10:
        raise RuntimeError('B1F singleton condition mismatch')
    b1.load_plan();b1.runtime_record()
    return p


def runtime_record():
    path=OUT/'runtime_manifest.json'
    if sha(path)!=(OUT/'runtime_manifest.sha256').read_text().split()[0]:raise RuntimeError('Frozen B1F runtime changed')
    r=json.loads(path.read_text())
    for p,h in r['source_sha256'].items():
        if sha(ROOT/p)!=h:raise RuntimeError('Frozen dependency changed: '+p)
    return dict(version='B1F_MANUAL_CPU_PIN',condition_plan_sha256=sha(PLAN),runtime_manifest_sha256=sha(path),source_sha256=r['source_sha256'])
