"""One-time preparation refreeze after CPU-only synthetic count regression fix."""
import copy
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

import config as cfg


def tree_hash(path):
    rows = {str(p.relative_to(path)):cfg.sha(p)
            for p in sorted(path.rglob('*')) if p.is_file()}
    return hashlib.sha256(json.dumps(rows,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value,indent=2,ensure_ascii=False)+'\n')


def main():
    out=cfg.OUT
    previous=out/'validation_refreeze_previous'
    if previous.exists() or (out/'validation_refreeze_provenance.json').exists():
        raise RuntimeError('Validation refreeze already performed')
    if any((out/name).exists() for name in (
            'campaign_attempt.json','CPU_PIN_READBACK.json','CPU_RESTORE_READBACK.json',
            'frequency_preflight.json','analysis01')) or any(
            (out/row['run_id']).exists() for row in cfg.order()):
        raise RuntimeError('Execution namespace consumed; cannot refreeze')
    old_sha=cfg.sha(cfg.PLAN)
    if old_sha!=(out/'plan.sha256').read_text().strip():
        raise RuntimeError('Previous plan SHA mismatch')
    old_plan=json.loads(cfg.PLAN.read_text())
    if old_plan['order']!=cfg.order():
        raise RuntimeError('Eight-run scientific order drift')
    preservation=json.loads((out/'preservation.json').read_text())
    protected=preservation['protected_before']
    if {name:tree_hash(Path(name)) for name in protected}!=protected:
        raise RuntimeError('Protected evidence changed before refreeze')
    previous.mkdir(exist_ok=False)
    for name in ('plan.json','plan.sha256','source_sha256.json'):
        shutil.copyfile(out/name,previous/name)
    sources={str(path.relative_to(cfg.ROOT)):cfg.sha(path)
             for path in sorted(cfg.HERE.glob('*.py'))}
    builder=cfg.ROOT/'scripts/timely_capacity_campaign/common/v2_2/v22_builder.py'
    sources[str(builder.relative_to(cfg.ROOT))]=cfg.sha(builder)
    plan=copy.deepcopy(old_plan)
    plan.update(source_sha256=old_plan['source_sha256']|sources,
        previous_calibration05_preparation_sha256=old_sha,
        validation_refreeze_reason='SYNTHETIC_FINAL_ANALYZER_EXPECTED_COUNT_8_FIX_ONLY',
        validation_refrozen_utc=datetime.now(timezone.utc).isoformat())
    allowed={'source_sha256','previous_calibration05_preparation_sha256',
             'validation_refreeze_reason','validation_refrozen_utc'}
    if {k:v for k,v in old_plan.items() if k not in allowed}!={
            k:v for k,v in plan.items() if k not in allowed}:
        raise RuntimeError('Scientific plan fields changed')
    write_json(out/'source_sha256.json',sources)
    write_json(cfg.PLAN,plan)
    new_sha=cfg.sha(cfg.PLAN)
    (out/'plan.sha256').write_text(new_sha+'\n')
    if {name:tree_hash(Path(name)) for name in protected}!=protected:
        raise RuntimeError('Protected evidence changed during refreeze')
    write_json(out/'validation_refreeze_provenance.json',dict(
        previous_plan_sha256=old_sha,new_plan_sha256=new_sha,
        preregistration_sha256=plan['preregistration_sha256'],
        reason='SYNTHETIC_FINAL_ANALYZER_EXPECTED_COUNT_8_FIX_ONLY',
        failed_synthetic_directory='synthetic_regression05',
        rerun_synthetic_directory='synthetic_regression05_fix01',
        scientific_conditions_unchanged=True,
        worker_source_sha256_unchanged=(old_plan['calibration_worker_sha256']==
                                        plan['calibration_worker_sha256']),
        protected_artifacts_unchanged=True,no_workload_executed=True))
    print(json.dumps(dict(previous_plan_sha256=old_sha,new_plan_sha256=new_sha,
        preregistration_sha256=plan['preregistration_sha256'],
        scientific_conditions_unchanged=True),indent=2))


if __name__=='__main__':main()
