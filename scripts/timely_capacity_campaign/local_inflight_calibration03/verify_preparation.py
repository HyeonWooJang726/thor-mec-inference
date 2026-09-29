"""Read-only readiness verification; writes only a new calibration03 report."""
import csv
import hashlib
import json
import math
import subprocess
import sys
from pathlib import Path

import config as cfg
import summary_adapter
from analyze_scan import analyze_run
from analyze_b1 import read
from run_scan import Context

PRIOR = cfg.ROOT/'results/timely_capacity_campaign/v2_2/local_inflight_calibration02'


def require(ok, why):
    if not ok:raise AssertionError(why)


def tree_hash(path):
    rows={str(p.relative_to(path)):cfg.sha(p) for p in sorted(path.rglob('*')) if p.is_file()}
    return hashlib.sha256(json.dumps(rows,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def run():
    out=cfg.OUT
    plan=cfg.load_plan()
    Context().check_inputs()  # Source/input check only; no GPU write or workload.
    require(cfg.sha(cfg.PLAN)==(out/'plan.sha256').read_text().strip(), 'Plan SHA')
    require(plan['C_dependent_audit_sha256']==cfg.sha(out/'PRODUCTION_PATH_C_AUDIT.md'), 'Audit SHA')
    require(plan['parent_finalizer_fix_sha256']==cfg.sha(out/'PARENT_FINALIZER_FIX.md'), 'Parent fix SHA')
    require(plan['preregistration_sha256']==cfg.sha(out/'CALIBRATION_PREREGISTRATION.md'), 'Prereg SHA')
    original=json.loads((PRIOR/'plan.json').read_text())
    require(len(plan['order'])==8 and [r['run_id'] for r in plan['order']]==[
        'LINFLIGHT03_C1_R1','LINFLIGHT03_C2_R1','LINFLIGHT03_C3_R1','LINFLIGHT03_C4_R1',
        'LINFLIGHT03_C4_R2','LINFLIGHT03_C3_R2','LINFLIGHT03_C2_R2','LINFLIGHT03_C1_R2'],
        'Exact 8-run order')
    require(plan['order']==[dict(r,run_id=r['run_id'].replace('LINFLIGHT02','LINFLIGHT03'))
                            for r in original['order']], 'Scientific conditions changed')
    require(plan['runtime']==original['runtime'] and plan['inputs']==original['inputs'] and
            plan['selection_rule']==original['selection_rule'], 'Scientific controls/selection changed')
    require(plan['calibration_worker_sha256']==hashlib.sha256(cfg.run_source().encode()).hexdigest(),
            'Derived worker SHA')
    require(plan['calibration_worker_sha256']==original['calibration_worker_sha256'],
            'Calibration02 worker source changed')
    require(cfg.run_source().replace('from summary_adapter import summarize','from b1_summary import summarize').replace(
        'runtime=ConcurrentTensorRT(str(ENGINE),min(c,2))',
        'runtime=ConcurrentTensorRT(str(ENGINE),2)')==cfg.frozen_run_source(),
        'Inference hot path changed')
    source=summary_adapter.summary_source()
    require("len(warm)==m['C']*m['warmup_inferences_per_worker']" in source and
            "overlap['peak']<=m['C']" in source and
            "len(warm)==60" not in source and "overlap['peak']<=2" not in source,
            'C-dependent summary predicates not generalized')
    from run_scan import parent_finalizer_source
    import dis
    parent_source=parent_finalizer_source()
    require('from summary_adapter import summarize,read_csv' in parent_source and
            'validate_parent_artifacts(directory,manifest,frames,measured)' in parent_source and
            'from b1_summary import summarize,read_csv' not in parent_source,
            'Parent summary binding still stale')
    actual_imports=[x.argval for x in dis.get_instructions(Context().bindings()[1])
                    if x.opname=='IMPORT_NAME']
    require(actual_imports==['summary_adapter','parent_validation'],
            'Actual production finalizer import mismatch')
    synthetic=json.loads((out/'synthetic_regression03_fix02/synthetic_regression_report.json').read_text())
    cases=synthetic['cases']
    require(synthetic['status']=='PASS' and len(cases)==8 and
            sorted((r['C'],r['warmup_expected'],r['warmup_actual'],r['workers'],r['contexts']) for r in cases)==
            sorted((c,30*c,30*c,c,c) for c in (1,2,3,4) for _ in (1,2)),
            'C1..C4 synthetic E2E cardinality')
    require(all(len(v)==6 for v in synthetic['negative_tests'].values()), 'Negative fixture coverage')
    require(all((out/'synthetic_regression03_fix02'/r['run_id']/'SYNTHETIC_ONLY.json').exists() for r in cases),
            'Synthetic provenance markers')
    require(len(synthetic['production_parent_negative_tests'])==7 and
            all(synthetic['production_parent_negative_tests'].values()),
            'Production parent negative coverage')
    require(synthetic['calibration02_real_raw_replay']['status']=='PASS' and
            synthetic['calibration02_real_raw_replay']['original_final_verdict']=='INVALID',
            'Calibration02 real raw replay')
    analysis=out/'synthetic_regression03_fix02/analysis'
    require(all((analysis/n).is_file() for n in (
        'per_run.csv','per_C_summary.csv','supply_classification.csv',
        'c2_justification.json','fig_local_concurrency_calibration.csv','validity_summary.json')),
        'Synthetic final-analysis outputs')
    require(json.loads((analysis/'validity_summary.json').read_text())['status']=='PASS',
            'Synthetic final input validity')
    # Preserve exact C2 summary semantics and offline raw-capacity metrics.
    raw=cfg.RAW;run_id='V22_RAW_R1_L240_P01';directory=raw/run_id
    m=json.loads((directory/'manifest.json').read_text())
    stored=json.loads((directory/'summary.json').read_text())
    replay=summary_adapter.summarize(m,read(directory/'per_frame.csv.gz'),
                                     read(directory/'power_trace.csv.gz'))
    summary_fields=['integrity_status','pipeline_audit_status','terminal_accounting_status',
                    'raw_completed_FPS','actual_freq_mean_MHz','active_concurrency_mean','missing_frames']
    require(all(replay.get(k)==stored.get(k) for k in summary_fields), 'Legacy C2 summary changed')
    condition=next(r for r in json.loads((raw/'plan.json').read_text())['order'] if r['run_id']==run_id)
    row,_=analyze_run(directory,condition)
    old=next(r for r in csv.DictReader((raw/'analysis01/per_run_capacity.csv').open())
             if r['run_id']==run_id)
    metrics=['active_completed_FPS','service_mean','service_p95','GPU_span_mean','GPU_span_p95',
             'host_residual_mean','host_residual_p95','active_concurrency_mean','OC3_delta','g_B_H','Delta_FPS']
    require(all(math.isclose(float(row[k]),float(old[k]),abs_tol=1e-9) for k in metrics)
            and row['raw_scan_integrity_status']=='VALID' and
            row['saturation_status']=='SATURATED_VALID', 'Legacy C2 analysis/classification changed')
    # New execution namespace must remain pristine despite synthetic fixtures.
    require(not any((out/n).exists() for n in (
        'campaign_attempt.json','CPU_PIN_READBACK.json','CPU_RESTORE_READBACK.json',
        'frequency_preflight.json')), 'Execution state consumed')
    require(not any((out/r['run_id']).exists() for r in plan['order']), 'Measured run directory exists')
    preservation=json.loads((out/'preservation.json').read_text())
    current={name:tree_hash(Path(name)) for name in preservation['protected_before']}
    require(current==preservation['protected_before'], 'Prior artifacts changed')
    unit=subprocess.run([sys.executable,'-B','-m','unittest','discover','-s',str(cfg.HERE),
                         '-p','test_cpu.py','-v'],cwd=cfg.ROOT,capture_output=True,text=True)
    require(unit.returncode==0,'CPU-only tests: '+unit.stderr)
    diff=subprocess.run(['git','diff','--check'],cwd=cfg.ROOT,capture_output=True,text=True)
    require(diff.returncode==0,'git diff --check: '+diff.stdout+diff.stderr)
    for folder in (cfg.HERE,out):
        for p in folder.rglob('*'):
            if p.is_file() and p.suffix in ('.py','.md'):
                require(all(line==line.rstrip() for line in p.read_text().splitlines()),
                        'Whitespace in '+str(p))
    report=dict(status='PASS',scope='PREPARATION_ONLY_CPU_SYNTHETIC',
        plan_sha256=cfg.sha(cfg.PLAN),preregistration_sha256=plan['preregistration_sha256'],
        C_dependent_audit='PASS',synthetic_C1_to_C4='PASS',synthetic_run_count=len(cases),
        actual_production_parent_finalizer='PASS',production_parent_negative_count=7,
        calibration02_real_raw_replay='PASS',negative_per_C=6,
        legacy_C2_summary='PASS',legacy_C2_analysis='PASS',
        legacy_C2_metric_matches=metrics,unit_tests='PASS',
        final_analyzer_input='PASS',preservation='PASS',git_diff_check='PASS',
        no_execution_evidence=True,no_workload_executed=True,
        synthetic_not_performance_evidence=True)
    with (out/'regression_report.json').open('x') as f:
        json.dump(report,f,indent=2);f.write('\n')
    print(json.dumps(report,indent=2))


if __name__=='__main__':run()
