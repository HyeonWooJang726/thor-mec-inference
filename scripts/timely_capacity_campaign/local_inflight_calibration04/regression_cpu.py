"""CPU-only structural replay; synthetic fixtures are never performance data."""
import copy
import csv
import gzip
import hashlib
import json
import shutil
import types
from pathlib import Path

import config as cfg
import summary_adapter
from analyze_scan import analyze_run, assemble_outputs
from integrity import validate_cardinality
from selection import decide
from analyze_b1 import read
from run_scan import Context

SOURCE = cfg.ROOT / 'results/timely_capacity_campaign/v2_2/local_inflight_calibration01/LINFLIGHT01_C1_R1'
SYNTH = cfg.OUT / 'synthetic_regression04_selection_refreeze'


def require(value, message):
    if not value:
        raise AssertionError(message)


def save_json(path, obj):
    with path.open('x') as f:
        json.dump(obj, f, indent=2, allow_nan=False)
        f.write('\n')


def save_csv(path, rows, header):
    with (gzip.open(path, 'wt', newline='') if str(path).endswith('.gz') else path.open('x', newline='')) as f:
        writer = csv.DictWriter(f, fieldnames=header, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(rows)


def production_finalize(directory):
    """Execute the production finalizer code object with synthetic I/O controls."""
    production = Context().bindings()[1]
    globals_for_fixture = dict(production.__globals__,
        read_range=lambda: {'min_freq':315000000,'max_freq':1575000000},
        write_json=lambda path, value: path.write_text(json.dumps(value, indent=2)+'\n'))
    finalizer = types.FunctionType(production.__code__, globals_for_fixture)
    info = dict(child_pid=1,child_returncode=0,child_exit_signal=None,
        child_start_time='2026-01-01T00:00:00+00:00',
        child_exit_time='2026-01-01T00:02:00+00:00',
        child_start_monotonic_ns=1,child_exit_monotonic_ns=2,
        supervisor_interrupted_or_timeout=False,parent_restore_error=None)
    return finalizer(directory,info,'SYNTHETIC_CHILD_EXIT_0','')


def build_fixture(condition, base):
    """Transform preserved C1 trace into a labeled, structurally complete fake run."""
    destination = SYNTH / condition['run_id']
    destination.mkdir(exist_ok=False)
    c = int(condition['C'])
    manifest = copy.deepcopy(base['manifest'])
    manifest.update(run_id=condition['run_id'], C=c, errors=[], child_returncode=0,
                    process_exit_code=0, warmup_inferences_per_worker=30,
                    execution_runtime={'status': 'SYNTHETIC_ONLY'})
    template = base['manifest']['resources'][0]
    resources = []
    for worker_id in range(c):
        item = copy.deepcopy(template)
        item.update(worker_id=worker_id, context_object_id=10_000+worker_id,
                    cuda_stream_pointer=20_000+worker_id)
        item['device_buffers'] = {k:30_000+100*worker_id+i
                                  for i,k in enumerate(item['device_buffers'])}
        item['pinned_host_buffers'] = {k:40_000+100*worker_id+i
                                       for i,k in enumerate(item['pinned_host_buffers'])}
        resources.append(item)
    manifest['resources'] = resources
    raw = []
    for worker_id in range(c):
        for index, old in enumerate(base['warmup']):
            row = dict(old, worker_id=str(worker_id), frame_id=str(30*worker_id+index))
            raw.append(row)
    active = []
    lookup = {}
    for index, old in enumerate(base['active']):
        worker_id = index % c
        row = dict(old, worker_id=str(worker_id))
        active.append(row)
        lookup[row['stream_id'], row['frame_id']] = worker_id
    raw.extend(active)
    phase = [dict(row, worker_id=str(lookup[row['stream_id'], row['frame_id']]))
             for row in base['phase']]
    workers = []
    for worker_id in range(c):
        n = sum(int(row['worker_id']) == worker_id for row in phase)
        worker = copy.deepcopy(base['workers'][0])
        worker.update(worker_id=worker_id, records=n, capacity=14400,
                      record_calls=2*(30+n), elapsed_calls=n)
        workers.append(worker)
    require(validate_cardinality(condition, manifest, raw, phase, workers)['status']=='PASS',
            'Synthetic cardinality construction invalid')
    summary = summary_adapter.summarize(manifest, raw, base['power'])
    require(summary['integrity_status']=='VALID' and not summary['errors'],
            'Synthetic summary rejected C='+str(c)+': '+repr(summary['errors'][:5]))
    manifest.update(summary_written=True,active_phase_completed=True,
                    drain_completed=True,cleanup_started=True,cleanup_completed=True,
                    frequency_restore_ok=True)
    summary.update(integrity_status='PENDING_PROCESS_EXIT',validity='PENDING_PROCESS_EXIT',
                   status_finalized=False,measurement_integrity_status='VALID')
    save_json(destination/'manifest.json', manifest)
    save_json(destination/'summary.json', summary)
    save_json(destination/'phase_instrumentation_manifest.json', workers)
    save_csv(destination/'per_frame.csv.gz', raw, base['raw_header'])
    save_csv(destination/'per_frame_phase_timestamps.csv', phase, base['phase_header'])
    shutil.copyfile(SOURCE/'power_trace.csv.gz', destination/'power_trace.csv.gz')
    for name in ('CPU_BEFORE_RUN.json','CPU_AFTER_RUN.json','CPU_TIME_IN_STATE_DELTA.json'):
        shutil.copyfile(SOURCE/name, destination/name)
    (destination/'stderr.log').write_text('SYNTHETIC_ONLY\n')
    finalized=production_finalize(destination)
    require(finalized['integrity_status']=='VALID' and
            finalized['PIPELINE_AUDIT']=='PASS' and
            finalized['measurement_integrity_status']=='VALID',
            'Production parent finalizer rejected C='+str(c)+': '+repr(finalized['errors']))
    save_json(destination/'SYNTHETIC_ONLY.json', {
        'provenance': 'STRUCTURAL_SYNTHETIC_TRANSFORM_OF_INVALID_C1_TRACE',
        'source_run': 'LINFLIGHT01_C1_R1',
        'not_GPU_runtime_evidence': True, 'not_capacity_evidence': True,
        'not_C2_justification_evidence': True,
        'transforms': ['planned C/worker/context IDs', 'warmup cardinality',
                       'active worker labels', 'phase worker labels', 'process verdict for CPU-only replay']})
    return destination, manifest, raw, phase, workers


def negative_tests(condition, manifest, raw, phase, workers, power):
    cases = {}
    # The warmup rows precede active rows; remove precisely one warmup row.
    fewer = raw[1:]
    cases['warmup_count'] = validate_cardinality(condition,manifest,fewer,phase,workers)
    cases['worker_count'] = validate_cardinality(condition,manifest,raw,phase,workers[:-1])
    wrong_context = dict(manifest, resources=manifest['resources'][:-1])
    cases['context_count'] = validate_cardinality(condition,wrong_context,raw,phase,workers)
    late = [dict(r) for r in raw]
    late[0]['completion_timestamp_ns'] = str(manifest['active_start_ns'])
    cases['warmup_timestamp'] = validate_cardinality(condition,manifest,late,phase,workers)
    cases['worker_accounting_missing'] = validate_cardinality(condition,manifest,raw,phase,workers[1:])
    require(all(r['status']=='FAIL' for r in cases.values()),'A malformed cardinality case passed')
    # Exercise the actual post-run summary predicate as well, not only the
    # independent phase/context validator.
    bad_summary = summary_adapter.summarize(manifest, fewer, power)
    require(bad_summary['integrity_status']=='INVALID' and 'warmup' in bad_summary['errors'],
            'Missing warmup accepted by post-run summary')
    late_summary = summary_adapter.summarize(manifest, late, power)
    require(late_summary['integrity_status']=='INVALID' and 'warmup' in late_summary['errors'],
            'Late warmup completion accepted by post-run summary')
    overlap = [dict(r) for r in raw]
    active = [r for r in overlap if r['phase']=='active']
    first = active[:int(condition['C'])+1]
    stamp = max(int(r['ready_timestamp_ns']) for r in first)
    for row in first:
        row['inference_start_timestamp_ns'] = str(stamp)
        row['expiry_check_ns'] = str(stamp)
        row['completion_timestamp_ns'] = str(stamp+1_000_000)
    overlap_summary = summary_adapter.summarize(manifest, overlap, power)
    require(overlap_summary['integrity_status']=='INVALID' and
            'Local C exceeded' in overlap_summary['errors'],
            'Concurrency exceeding planned C accepted by summary')
    cases['concurrency_peak'] = {'errors':['Local C exceeded']}
    return {name:result['errors'] for name,result in cases.items()}


def negative_parent_tests(first_case):
    """Malformed files must fail via the same finalizer as production."""
    root=SYNTH/'negative_parent'
    root.mkdir(exist_ok=False)
    names=('manifest.json','summary.json','per_frame.csv.gz',
           'power_trace.csv.gz','per_frame_phase_timestamps.csv',
           'phase_instrumentation_manifest.json','stderr.log')
    results={}
    for fault in ('warmup_count','worker_count','context_count','warmup_timestamp',
                  'missing_worker_accounting','active_concurrency','phase_cardinality'):
        dst=root/fault;dst.mkdir(exist_ok=False)
        for name in names:shutil.copyfile(first_case/name,dst/name)
        m=json.loads((dst/'manifest.json').read_text())
        workers=json.loads((dst/'phase_instrumentation_manifest.json').read_text())
        raw=read(dst/'per_frame.csv.gz')
        phase=read(dst/'per_frame_phase_timestamps.csv')
        if fault=='warmup_count':raw.remove(next(r for r in raw if r['phase']=='warmup'))
        elif fault=='worker_count':workers=[]
        elif fault=='context_count':m['resources']=[]
        elif fault=='warmup_timestamp':
            next(r for r in raw if r['phase']=='warmup')['completion_timestamp_ns']=str(m['active_start_ns'])
        elif fault=='missing_worker_accounting':workers[0]['record_calls']=0
        elif fault=='active_concurrency':
            active=[r for r in raw if r['phase']=='active'][:int(m['C'])+1]
            stamp=max(int(r['ready_timestamp_ns']) for r in active)
            for r in active:
                r['inference_start_timestamp_ns']=str(stamp)
                r['expiry_check_ns']=str(stamp)
                r['completion_timestamp_ns']=str(stamp+1_000_000)
        elif fault=='phase_cardinality':phase[0]['worker_id']='9'
        (dst/'manifest.json').write_text(json.dumps(m))
        (dst/'phase_instrumentation_manifest.json').write_text(json.dumps(workers))
        if fault in ('warmup_count','warmup_timestamp','active_concurrency'):
            with gzip.open(dst/'per_frame.csv.gz','wt',newline='') as f:
                writer=csv.DictWriter(f,fieldnames=list(raw[0]),extrasaction='ignore')
                writer.writeheader();writer.writerows(raw)
        if fault=='phase_cardinality':
            with (dst/'per_frame_phase_timestamps.csv').open('w',newline='') as f:
                writer=csv.DictWriter(f,fieldnames=list(phase[0]),extrasaction='ignore')
                writer.writeheader();writer.writerows(phase)
        result=production_finalize(dst)
        require(result['integrity_status']=='INVALID' and result['PIPELINE_AUDIT']=='FAIL',
                'Production parent accepted malformed '+fault)
        results[fault]=result['errors']
    return results


def replay_calibration03_c3_c4():
    results=[]
    for c in (3,4):
        source=cfg.ROOT/f'results/timely_capacity_campaign/v2_2/local_inflight_calibration03/LINFLIGHT03_C{c}_R1'
        dst=cfg.OUT/f'replay_validation/selection_refreeze_calibration03_c{c}'
        dst.mkdir(parents=True,exist_ok=False)
        for name in ('manifest.json','summary.json','per_frame.csv.gz','power_trace.csv.gz',
                     'per_frame_phase_timestamps.csv','phase_instrumentation_manifest.json','stderr.log',
                     'CPU_BEFORE_RUN.json','CPU_AFTER_RUN.json','CPU_TIME_IN_STATE_DELTA.json'):
            shutil.copyfile(source/name,dst/name)
        original=json.loads((source/'summary.json').read_text())
        result=production_finalize(dst)
        compared=('integrity_status','pipeline_audit_status','terminal_accounting_status',
                  'raw_completed_FPS','active_concurrency_peak','missing_frames')
        require(all(result.get(k)==original.get(k) for k in compared) and
                result['PIPELINE_AUDIT']=='PASS','Calibration03 C'+str(c)+' replay changed')
        prior_plan=json.loads((cfg.ROOT/'results/timely_capacity_campaign/v2_2/local_inflight_calibration03/plan.json').read_text())
        condition=next(x for x in prior_plan['order'] if x['run_id']==source.name)
        offline,_=analyze_run(dst,condition)
        require(offline['raw_scan_integrity_status']=='VALID' and
                offline['saturation_status']=='SATURATED_VALID',
                'Calibration03 C'+str(c)+' offline classification changed')
        save_json(dst/'REPLAY_ONLY.json',dict(source_run=str(source),
            original_verdict='VALID',replay_structural_integrity=result['integrity_status'],
            excluded_from_calibration04_repeats=True,not_new_performance_evidence=True))
        results.append({'C':c,'status':'PASS','expected_warmup':30*c,
                        'summary_fields_equal':list(compared),
                        'offline_supply_class':offline['saturation_status']})
    return results


def base_data():
    with gzip.open(SOURCE/'per_frame.csv.gz','rt',newline='') as f:
        reader=csv.DictReader(f);raw_header=reader.fieldnames;raw=list(reader)
    with (SOURCE/'per_frame_phase_timestamps.csv').open(newline='') as f:
        reader=csv.DictReader(f);phase_header=reader.fieldnames;phase=list(reader)
    return dict(manifest=json.loads((SOURCE/'manifest.json').read_text()),
                warmup=[r for r in raw if r['phase']=='warmup'],
                active=[r for r in raw if r['phase']=='active'],raw_header=raw_header,
                phase_header=phase_header,phase=phase,
                workers=json.loads((SOURCE/'phase_instrumentation_manifest.json').read_text()),
                power=read(SOURCE/'power_trace.csv.gz'))


def run():
    plan=json.loads(cfg.PLAN.read_text())  # Final source/SHA guard runs in verify_preparation.
    require(len(plan['order'])==6,'Not the frozen 6-run plan')
    SYNTH.mkdir(exist_ok=False)
    base=base_data()
    rows=[];traces=[];cases=[];negative={}
    for condition in plan['order']:
        path,manifest,raw,phase,workers=build_fixture(condition,base)
        row,trace=analyze_run(path,condition)
        require(row['raw_scan_integrity_status']=='VALID',
                'Synthetic end-to-end rejected '+condition['run_id']+': '+repr(row['validity_errors']))
        require(row['saved_integrity_status']=='VALID', 'Saved summary invalid')
        rows.append(row);traces.extend(trace)
        cases.append({'run_id':condition['run_id'],'C':condition['C'],
                      'contexts':len(manifest['resources']),'workers':len(workers),
                      'warmup_expected':30*condition['C'],
                      'warmup_actual':sum(r['phase']=='warmup' for r in raw),
                      'summary':'PASS','phase_instrumentation':'PASS',
                      'per_run_analyzer':'PASS','supply_class':row['saturation_status']})
        if condition['repeat']==1:
            negative[condition['C']]=negative_tests(condition,manifest,raw,phase,workers,base['power'])
    parent_negative=negative_parent_tests(SYNTH/plan['order'][0]['run_id'])
    real_replay=replay_calibration03_c3_c4()
    decision,supply,per_c,tradeoff,figure,validity=assemble_outputs(rows)
    require(validity['status']=='PASS' and validity['valid_run_count']==6,
            'Final analyzer input validity failed')
    require(len(per_c)==3 and len(tradeoff)==3 and len(figure)==6 and len(supply)==6,
            'Per-C/figure aggregation cardinality failed')
    require(decision['primary_extension_verdict']=='SATURATED_PLATEAU_C_SELECTED' and
            decision['C_selected']==3,
            'Synthetic input rejected by refrozen selection analyzer')
    out=SYNTH/'analysis'
    out.mkdir(exist_ok=False)
    from analyze_scan import write_csv,write_json
    write_csv(out/'per_run.csv',rows)
    write_csv(out/'backlog_1s.csv',traces)
    write_csv(out/'supply_classification.csv',supply)
    write_csv(out/'per_C_summary.csv',per_c)
    write_csv(out/'tradeoff_summary.csv',tradeoff)
    write_csv(out/'fig_local_concurrency_extension.csv',figure)
    write_json(out/'extension_verdict.json',decision)
    write_json(out/'validity_summary.json',validity)
    save_json(SYNTH/'synthetic_regression_report.json',
              {'status':'PASS','provenance':'SYNTHETIC_STRUCTURAL_ONLY',
               'not_performance_or_GPU_evidence':True,'cases':cases,
               'negative_tests':negative,'production_parent_negative_tests':parent_negative,
               'calibration03_c3_c4_real_raw_replay':real_replay,
               'production_finalizer_actual_code_object':'PASS',
               'final_analyzer_input':'PASS',
               'per_C_aggregation':'PASS','figure_source_generation':'PASS'})
    return cases,negative


if __name__=='__main__':
    cases,negative=run()
    print(json.dumps({'status':'PASS','positive_cases':len(cases),
                      'negative_cases_per_C':{str(k):len(v) for k,v in negative.items()}},indent=2))
