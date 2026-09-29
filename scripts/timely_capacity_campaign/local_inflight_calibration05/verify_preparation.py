"""Read-only Calibration05 READY gate; writes one new regression report."""
import dis
import csv
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import config as cfg
from selection_plan import selection_rule
from run_scan import Context,memory_snapshot,parent_finalizer_source

PRIOR=cfg.ROOT/'results/timely_capacity_campaign/v2_2/local_inflight_calibration04'


def require(ok,why):
    if not ok:raise AssertionError(why)


def tree_hash(path):
    rows={str(p.relative_to(path)):cfg.sha(p) for p in sorted(path.rglob('*')) if p.is_file()}
    return hashlib.sha256(json.dumps(rows,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def run():
    out=cfg.OUT
    plan=cfg.load_plan()
    Context().check_inputs()
    prior=json.loads((PRIOR/'plan.json').read_text())
    expected=['LINFLIGHT05_C3_R1','LINFLIGHT05_C4_R1','LINFLIGHT05_C5_R1',
              'LINFLIGHT05_C6_R1','LINFLIGHT05_C6_R2','LINFLIGHT05_C5_R2',
              'LINFLIGHT05_C4_R2','LINFLIGHT05_C3_R2']
    require([x['run_id'] for x in plan['order']]==expected and len(set(expected))==8,
            'Frozen eight-run order')
    require(plan['preregistration_sha256']==cfg.sha(out/'CALIBRATION_PREREGISTRATION.md'),
            'Preregistration SHA')
    require(plan['selection_rule']==selection_rule() and
            plan['selection_rule']['OC3']=='DIAGNOSTIC_ONLY',
            'Refrozen final-C selection rule')
    require(plan['C6_production_path_validation_sha256']==
            cfg.sha(out/'C6_PRODUCTION_PATH_VALIDATION.md') and
            plan['final_C_selection_rule_sha256']==cfg.sha(out/'FINAL_C_SELECTION_RULE.md'),
            'C6 validation/selection-rule SHA')
    require(plan['runtime']==prior['runtime'] and plan['inputs']==prior['inputs'],
            'Fixed model/source/runtime changed')
    require(plan['calibration_worker_sha256']==prior['calibration_worker_sha256'] and
            hashlib.sha256(cfg.run_source().encode()).hexdigest()==prior['calibration_worker_sha256'],
            'Calibration04 Local worker source changed')
    ignored={'run_id','order_index'}
    for row in plan['order']:
        if row['C'] in (3,4,5):
            old=next(x for x in prior['order'] if (x['C'],x['repeat'])==(row['C'],row['repeat']))
            require({k:v for k,v in row.items() if k not in ignored}==
                    {k:v for k,v in old.items() if k not in ignored},
                    'C3/C4/C5 scientific condition drift')
    require(plan['calibration05_only_selection_dataset'] is True and
            plan['previous_calibrations_used_for_selection'] is False,
            'Historical runs entered Calibration05 selection')
    source=parent_finalizer_source()
    require('from summary_adapter import summarize,read_csv' in source and
            'validate_parent_artifacts(directory,manifest,frames,measured)' in source and
            [x.argval for x in dis.get_instructions(Context().bindings()[1])
             if x.opname=='IMPORT_NAME']==['summary_adapter','parent_validation'],
            'Actual parent finalizer binding drift')
    regression=json.loads((out/'synthetic_regression05_fix01/synthetic_regression_report.json').read_text())
    cases=regression['cases']
    require(regression['status']=='PASS' and len(cases)==8 and
            sorted((x['C'],x['contexts'],x['workers'],x['warmup_expected'],x['warmup_actual'])
                   for x in cases)==sorted((c,c,c,30*c,30*c) for c in (3,4,5,6) for _ in (1,2)),
            'C3/C4/C5/C6 production-path synthetic cardinality')
    require(all(x['summary']=='PASS' and x['per_run_analyzer']=='PASS' for x in cases),
            'Synthetic finalizer/analyzer result')
    parent_negative=regression['production_parent_negative_tests']
    require({int(c) for c in parent_negative}=={3,6} and
            all(len(cases)>=7 and all(cases.values()) for cases in parent_negative.values()),
            'Malformed production finalizer fixtures')
    replay=regression['calibration04_c3_c4_c5_real_raw_replay']
    require(len(replay)==3 and {x['C'] for x in replay}=={3,4,5} and
            all(x['status']=='PASS' and x['offline_supply_class']=='SATURATED_VALID' for x in replay),
            'Calibration04 C3/C4/C5 compatibility')
    analysis=out/'synthetic_regression05_fix01/analysis'
    require(all((analysis/name).is_file() for name in (
        'per_run.csv','per_C_summary.csv','supply_classification.csv',
        'final_C_selection.json','tradeoff_summary.csv',
        'fig_local_concurrency_final.csv','validity_summary.json')) and
        json.loads((analysis/'validity_summary.json').read_text())['status']=='PASS',
        'Synthetic analyzer output/validity')
    synthetic_decision=json.loads((analysis/'final_C_selection.json').read_text())
    fields=('r_3','r_4','r_5','r_6','r6_over_r5','per_C_supply_class','C_selected',
            'primary_verdict','selection_reason','source_ceiling_reached',
            'plateau_supported','C7_extension_required','repeat_ambiguity',
            'calibration05_is_selection_dataset','previous_calibrations_used_for_selection')
    require(all(name in synthetic_decision for name in fields) and
            synthetic_decision['primary_verdict']=='FINAL_SATURATED_PLATEAU_C_SELECTED' and
            synthetic_decision['C_selected']==3 and
            synthetic_decision['calibration05_is_selection_dataset'] is True and
            synthetic_decision['previous_calibrations_used_for_selection'] is False,
            'Refrozen synthetic analyzer verdict/schema')
    with (analysis/'tradeoff_summary.csv').open(newline='') as f:
        tradeoff_fields=set(csv.DictReader(f).fieldnames or [])
    require(set(('C_L','R1_run_id','R2_run_id',
        'mean_completion_FPS','gain_vs_previous_C_percent','mean_Delta_FPS','mean_g_B_H',
        'queue_wait_p50_ms','queue_wait_p95_ms','service_mean_ms','service_p95_ms',
        'GPU_span_mean_ms','GPU_span_p95_ms','host_residual_mean_ms',
        'host_residual_p95_ms','active_concurrency_mean','active_concurrency_p95',
        'active_concurrency_peak','OC3_R1','OC3_R2','OC3_mean_delta','combined_supply_class'))
        <= tradeoff_fields,'Trade-off columns changed')
    memory=memory_snapshot()
    require(memory['status']=='PASS' and memory['planned_max_C']==6 and
            memory['headroom_after_reserve_bytes']>0,'C6 memory reserve')
    saved_memory=json.loads((out/'MEMORY_PREPARATION_SNAPSHOT.json').read_text())
    require(saved_memory['status']=='PASS' and saved_memory['planned_max_C']==6,
            'Frozen C6 preparation memory snapshot')
    require(not any((out/name).exists() for name in (
        'campaign_attempt.json','CPU_PIN_READBACK.json','CPU_RESTORE_READBACK.json',
        'frequency_preflight.json')) and
        all(not (out/run_id).exists() for run_id in expected),
        'Execution namespace consumed')
    preservation=json.loads((out/'preservation.json').read_text())
    require(preservation['status']=='PASS' and
            {name:tree_hash(Path(name)) for name in preservation['protected_before']}==
            preservation['protected_before'],'Protected artifacts changed')
    unit=subprocess.run([sys.executable,'-B','-m','unittest','discover','-s',str(cfg.HERE),
                         '-p','test_cpu.py','-v'],cwd=cfg.ROOT,capture_output=True,text=True)
    require(unit.returncode==0,'CPU-only unit tests: '+unit.stderr)
    require(all(name in unit.stderr for name in (
        'test_c6_two_of_two_full_load_selects_6',
        'test_c5_and_c6_full_load_selects_5',
        'test_c4_c5_c6_full_load_selects_4',
        'test_saturated_plateau_selects_3',
        'test_saturated_plateau_selects_4',
        'test_not_reached_and_no_auto_c7',
        'test_mixed_repeat_supply_class_has_no_selection',
        'test_invalid_excluded')),
        'Eight required final-C selection scenarios')
    diff=subprocess.run(['git','diff','--check'],cwd=cfg.ROOT,capture_output=True,text=True)
    require(diff.returncode==0,'git diff --check: '+diff.stdout+diff.stderr)
    report=dict(status='PASS',scope='PREPARATION_ONLY_CPU_SYNTHETIC',
        plan_sha256=cfg.sha(cfg.PLAN),preregistration_sha256=plan['preregistration_sha256'],
        final_C_selection_eight_required_scenarios='PASS',
        final_C_selection_schema='PASS',
        C3_C4_C5_C6_actual_production_finalizer='PASS',production_negative_count=sum(
            len(cases) for cases in parent_negative.values()),
        calibration04_C3_C4_C5_compatibility='PASS',C6_memory_reserve='PASS',
        source_and_scientific_controls='PASS',eight_run_order='PASS',
        calibration05_only_selection='PASS',
        CPU_only_units='PASS',git_diff_check='PASS',preservation='PASS',
        no_workload_executed=True,synthetic_not_performance_evidence=True)
    with (out/'regression_report.json').open('x') as f:
        json.dump(report,f,indent=2);f.write('\n')
    print(json.dumps(report,indent=2))


if __name__=='__main__':run()
