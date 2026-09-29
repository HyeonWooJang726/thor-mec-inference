"""CPU-only calibration05 preparation. Never launches Local/Edge work."""
import copy
import hashlib
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

import config as cfg
from run_scan import memory_snapshot
from selection_plan import selection_rule

sys.path.insert(0, str(cfg.HERE.parent/'common/service_phase_b1f'))
import cpu_state
from make_cpu_commands import render

PRIOR = cfg.ROOT/'results/timely_capacity_campaign/v2_2/local_inflight_calibration04'


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
        raise RuntimeError('Calibration05 already planned/executed; refuse overwrite')
    if not all((out/name).is_file() for name in
               ('CALIBRATION_PREREGISTRATION.md','C6_PRODUCTION_PATH_VALIDATION.md',
                'FINAL_C_SELECTION_RULE.md')):
        raise RuntimeError('Preregistration and C-dependent audit required first')
    original=json.loads((PRIOR/'plan.json').read_text())
    assert original['order'][0]['run_id']=='LINFLIGHT04_C3_R1'
    assert len(cfg.order())==8 and [r['C'] for r in cfg.order()]==[3,4,5,6,6,5,4,3]
    ignored={'run_id','order_index'}
    for row in cfg.order():
        if row['C'] in (3,4,5):
            prior=next(x for x in original['order'] if x['C']==row['C'] and
                       x['repeat']==row['repeat'])
            assert {k:v for k,v in row.items() if k not in ignored}==\
                   {k:v for k,v in prior.items() if k not in ignored}
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
         'local_inflight_calibration02','local_inflight_calibration03',
         'local_inflight_calibration04')]
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
    plan.update(campaign='LOCAL_INFLIGHT_CALIBRATION05_FINAL_C_CLOSURE',
        freeze_status='PREPARED_NOT_EXECUTED',frozen_utc=datetime.now(timezone.utc).isoformat(),
        order=cfg.order(),source_sha256={k:v for k,v in original['source_sha256'].items()
            if not any('/local_inflight_calibration0'+str(i)+'/' in k for i in (1,2,3,4))} | sources,
        frozen_worker_sha256=hashlib.sha256(frozen.encode()).hexdigest(),
        calibration_worker_sha256=hashlib.sha256(derived.encode()).hexdigest(),
        preregistration_sha256=cfg.sha(out/'CALIBRATION_PREREGISTRATION.md'),
        session_plan_sha256=cfg.sha(out/'session_plan.json'),
        C6_production_path_validation_sha256=cfg.sha(out/'C6_PRODUCTION_PATH_VALIDATION.md'),
        final_C_selection_rule_sha256=cfg.sha(out/'FINAL_C_SELECTION_RULE.md'),
        previous_calibration04_plan_sha256=cfg.sha(PRIOR/'plan.json'),
        selection_rule=selection_rule(),
        scientific_condition_diff='SAME_FULL_LOCAL_PIPELINE_NEW_C3_C4_C5_C6_SAME_SESSION_FINAL_C_CLOSURE',
        prior_calibration04_results_read_only=True,
        calibration05_only_selection_dataset=True,
        previous_calibrations_used_for_selection=False)
    plan.pop('C_dependent_audit_sha256',None)
    plan.pop('parent_finalizer_fix_sha256',None)
    plan.pop('C5_production_path_validation_sha256',None)
    plan.pop('selection_rule_refreeze_reason',None)
    plan.pop('selection_rule_refrozen_utc',None)
    save(out/'plan.json',plan)
    save(out/'plan.sha256',cfg.sha(out/'plan.json')+'\n')
    save(out/'RUNTIME_PROVENANCE.json',dict(
        frozen_V22_worker_sha256=plan['frozen_worker_sha256'],
        calibration05_worker_sha256=plan['calibration_worker_sha256'],
        calibration04_worker_sha256=original['calibration_worker_sha256'],
        worker_diff='byte-identical Calibration04 generated Local worker source',
        inference_queue_tensor_path_unchanged=True,
        C3_C4_C5_C6_initial_constructor_arg=2,
        summary_adapter_scope='calibration05 child and parent',
        previous_calibration04_plan_sha256=plan['previous_calibration04_plan_sha256']))
    after={str(path):tree_hash(path) for path in protected}
    if before!=after:raise RuntimeError('Protected evidence changed during preparation')
    save(out/'preservation.json',dict(status='PASS',protected_before=before,protected_after=after))
    print(json.dumps(dict(status='PREPARED_NOT_VALIDATED',plan_sha256=cfg.sha(out/'plan.json'),
                          preregistration_sha256=plan['preregistration_sha256'],
                          run_count=len(plan['order']),protected_preservation='PASS'),indent=2))


if __name__=='__main__':main()
