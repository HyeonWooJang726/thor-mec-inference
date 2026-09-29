"""CPU-only calibration03 preparation. Never launches Local/Edge work."""
import copy
import hashlib
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

import config as cfg
from run_scan import memory_snapshot

sys.path.insert(0, str(cfg.HERE.parent/'common/service_phase_b1f'))
import cpu_state
from make_cpu_commands import render

PRIOR = cfg.ROOT/'results/timely_capacity_campaign/v2_2/local_inflight_calibration02'


def save(path, obj):
    with path.open('x') as f:
        if isinstance(obj, str):
            f.write(obj)
        else:
            json.dump(obj, f, indent=2, ensure_ascii=False)
            f.write('\n')


def tree_hash(path):
    rows = {str(p.relative_to(path)):cfg.sha(p)
            for p in sorted(path.rglob('*')) if p.is_file()}
    return hashlib.sha256(json.dumps(rows,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def main():
    out=cfg.OUT
    forbidden=('plan.json','campaign_attempt.json','CPU_PIN_READBACK.json',
               'CPU_RESTORE_READBACK.json','frequency_preflight.json')
    if any((out/name).exists() for name in forbidden):
        raise RuntimeError('Calibration03 already planned/executed; refuse overwrite')
    if not all((out/name).is_file() for name in
               ('CALIBRATION_PREREGISTRATION.md','PARENT_FINALIZER_FIX.md',
                'PRODUCTION_PATH_C_AUDIT.md')):
        raise RuntimeError('Preregistration and C-dependent audit required first')
    original=json.loads((PRIOR/'plan.json').read_text())
    assert original['order'][0]['run_id']=='LINFLIGHT02_C1_R1'
    assert cfg.order()==[dict(row,run_id=row['run_id'].replace('LINFLIGHT02','LINFLIGHT03'))
                          for row in original['order']]
    frozen=cfg.frozen_run_source()
    derived=cfg.run_source()
    assert derived.replace('from summary_adapter import summarize','from b1_summary import summarize').replace(
        'runtime=ConcurrentTensorRT(str(ENGINE),min(c,2))',
        'runtime=ConcurrentTensorRT(str(ENGINE),2)')==frozen
    assert cfg.sha(cfg.frozen.OUT/'effective_runtime.txt')==hashlib.sha256(frozen.encode()).hexdigest()
    state=cpu_state.snapshot()
    assert len(state['policies'])==7 and all(
        p['fields'].get('scaling_governor')=='schedutil' and
        p['fields'].get('scaling_min_freq')=='972000' and
        p['fields'].get('scaling_max_freq')=='2601000' for p in state['policies'])
    for row in state['policies']:
        row['fields']['scaling_available_governors']=(Path(row['path'])/'scaling_available_governors').read_text().strip()
    memory=memory_snapshot()
    if memory['status']!='PASS':raise RuntimeError('Conservative Local memory reserve FAIL')
    sys.path.insert(0,str(cfg.HERE.parent/'timely_capacity_scan/attempt02'))
    from gpu_precheck import observe
    gpu_permission=observe()  # Read-only; execution check still requires PASS.
    protected=[cfg.ROOT/'results/timely_capacity_campaign/v2_2'/name for name in
        ('raw_capacity_scan01','block_b_grid02','block_b_confirmation01',
         'block_b_confirmation02','local_inflight_calibration01',
         'local_inflight_calibration02')]
    before={str(path):tree_hash(path) for path in protected}
    save(out/'CPU_STATE_BEFORE.json',state)
    save(out/'CPU_PIN_COMMANDS.sh',render(state,restore=False))
    save(out/'CPU_RESTORE_COMMANDS.sh',render(state,restore=True))
    save(out/'MEMORY_PREPARATION_SNAPSHOT.json',memory)
    save(out/'GPU_PERMISSION_SNAPSHOT.json',gpu_permission)
    save(out/'session_plan.json',dict(order=cfg.order(),
        warmup='30 Local inference calls per active worker before t0; excluded',
        active_seconds_each=60,idle_seconds_after_drain=10,
        no_retry_resume_overwrite=True,first_invalid_run='stop subsequent workload'))
    sources={str(path.relative_to(cfg.ROOT)):cfg.sha(path)
             for path in sorted(cfg.HERE.glob('*.py'))}
    builder=cfg.ROOT/'scripts/timely_capacity_campaign/common/v2_2/v22_builder.py'
    sources[str(builder.relative_to(cfg.ROOT))]=cfg.sha(builder)
    save(out/'source_sha256.json',sources)
    plan=copy.deepcopy(original)
    plan.update(campaign='LOCAL_INFLIGHT_CALIBRATION03',
        freeze_status='PREPARED_NOT_EXECUTED',frozen_utc=datetime.now(timezone.utc).isoformat(),
        order=cfg.order(),source_sha256={k:v for k,v in original['source_sha256'].items()
            if '/local_inflight_calibration01/' not in k and
               '/local_inflight_calibration02/' not in k} | sources,
        frozen_worker_sha256=hashlib.sha256(frozen.encode()).hexdigest(),
        calibration_worker_sha256=hashlib.sha256(derived.encode()).hexdigest(),
        preregistration_sha256=cfg.sha(out/'CALIBRATION_PREREGISTRATION.md'),
        session_plan_sha256=cfg.sha(out/'session_plan.json'),
        C_dependent_audit_sha256=cfg.sha(out/'PRODUCTION_PATH_C_AUDIT.md'),
        parent_finalizer_fix_sha256=cfg.sha(out/'PARENT_FINALIZER_FIX.md'),
        previous_calibration02_plan_sha256=cfg.sha(PRIOR/'plan.json'),
        previous_C1_status='INVALID_PARENT_FINALIZER_STALE_C2_ASSUMPTION',
        scientific_condition_diff='NONE_EXCEPT_FRESH_RUN_IDS_AND_PARENT_FINALIZER_VALIDATION_FIX',
        no_calibration01_or_02_performance_outcome_used=True)
    save(out/'plan.json',plan)
    save(out/'plan.sha256',cfg.sha(out/'plan.json')+'\n')
    save(out/'RUNTIME_PROVENANCE.json',dict(
        frozen_V22_worker_sha256=plan['frozen_worker_sha256'],
        calibration03_worker_sha256=plan['calibration_worker_sha256'],
        calibration02_worker_sha256=original['calibration_worker_sha256'],
        worker_diff='byte-identical Calibration02 worker source; parent finalizer binding only',
        inference_queue_tensor_path_unchanged=True,
        C2_C3_C4_constructor_arg_unchanged=2,
        summary_adapter_scope='calibration03 child and parent',
        previous_calibration02_plan_sha256=plan['previous_calibration02_plan_sha256']))
    after={str(path):tree_hash(path) for path in protected}
    if before!=after:raise RuntimeError('Protected evidence changed during preparation')
    save(out/'preservation.json',dict(status='PASS',protected_before=before,protected_after=after))
    print(json.dumps(dict(status='PREPARED_NOT_VALIDATED',plan_sha256=cfg.sha(out/'plan.json'),
                          preregistration_sha256=plan['preregistration_sha256'],
                          run_count=len(plan['order']),protected_preservation='PASS'),indent=2))


if __name__=='__main__':main()
