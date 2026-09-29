"""Non-measured K1/K3/K8 structural replay through production finalizer.

Filtered preserved C3 rows are fixture data, never K-sweep measurements.
"""
import copy
import csv
import gzip
import json
import os
import shutil
import types
from pathlib import Path

import config
from analyze import analyze_run
from analyze_b1 import read
from integrity import validate_source
from ksweep_schedule import decorate
from run_ksweep import Context
from summary_adapter import summarize
from v22_storage import preallocate_source_rows

SOURCE = config.ROOT/'results/timely_capacity_campaign/v2_2/local_inflight_calibration05/LINFLIGHT05_C3_R1'
TAG = os.environ.get('KSWEEP_REGRESSION_TAG', 'freeze')
if not TAG.isalnum():
    raise ValueError('Regression tag must be alphanumeric')
DEST = config.OUT/('synthetic_validation_'+TAG)


def require(ok, why):
    if not ok:
        raise AssertionError(why)


def save_json(path, value):
    with path.open('x') as stream:
        json.dump(value, stream, indent=2, allow_nan=False)


def save_rows(path, rows, header):
    with gzip.open(path, 'wt', newline='') if str(path).endswith('.gz') else path.open('x', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=header, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(rows)


def parent_finalize(directory):
    production = Context().bindings()[1]
    namespace = dict(production.__globals__,
        read_range=lambda: {'min_freq':315000000, 'max_freq':1575000000},
        write_json=lambda path, value: path.write_text(json.dumps(value, indent=2)+'\n'))
    finalizer = types.FunctionType(production.__code__, namespace)
    process = dict(child_pid=1, child_returncode=0, child_exit_signal=None,
                   child_start_time='2026-01-01T00:00:00+00:00',
                   child_exit_time='2026-01-01T00:02:00+00:00',
                   child_start_monotonic_ns=1, child_exit_monotonic_ns=2,
                   supervisor_interrupted_or_timeout=False, parent_restore_error=None)
    return finalizer(directory, process, 'SYNTHETIC_CHILD_EXIT_0', '')


def source_slot_check(condition, active):
    k, seconds = condition['K'], condition['seconds']
    slots = preallocate_source_rows(k, seconds)
    require(len(slots) == 30*seconds and all(len(slot) == k for slot in slots),
            'Actual V2.2 source preallocator is not K-aware')
    expected = {(r['stream_id'], r['frame_id']) for slot in slots for r in slot}
    observed = {(int(r['stream_id']), int(r['frame_id'])) for r in active}
    require(expected == observed and len(active) == len(expected), 'source-slot IDs mismatch')
    start = int(active[0]['logical_arrival_ns'])
    for r in active:
        sid, frame = int(r['stream_id']), int(r['frame_id'])
        row = dict(stream_id=sid, frame_id=frame,
                   logical_arrival_ns=start+frame*10**9//30)
        decorate(row, start, condition)
        require(row['placement'] == r['placement'] and row['admitted'] == int(r['admitted']) and
                row['absolute_deadline_ns'] == int(r['absolute_deadline_ns']),
                'scheduler/admission mismatch')
    return dict(source_preallocator='PASS', slot_count=len(slots),
                source_frame_count=len(expected), scheduler='PASS')


def dispatch_completion_check(active):
    """Replay recorded C3 dispatch/completion evidence by source identity."""
    workers = {0:[], 1:[], 2:[]}
    for row in active:
        require(row['placement'] == 'LOCAL' and row['terminal_state'] == 'COMPLETED',
                'Non-Local or noncompleted structural trace')
        worker = int(row['worker_id'])
        require(worker in workers, 'Worker outside planned C_L=3')
        start = int(row['inference_start_timestamp_ns'])
        end = int(row['completion_timestamp_ns'])
        ready = int(row['ready_timestamp_ns'])
        require(ready <= start <= end, 'Queue/service/completion order mismatch')
        workers[worker].append((start,end))
    for spans in workers.values():
        ordered = sorted(spans)
        require(all(left[1] <= right[0] for left,right in zip(ordered,ordered[1:])),
                'Overlapping inference intervals on one worker')
    return dict(local_dispatch='PASS', execution_completion='PASS',
                active_worker_ids=[w for w,spans in workers.items() if spans])


def fixture(condition, base):
    k = condition['K']
    path = DEST/f"positive_K{k}"
    path.mkdir(exist_ok=False)
    manifest = copy.deepcopy(base['manifest'])
    manifest.update(K=k, C=3, run_id=condition['run_id'], repeat=condition['repeat'],
        target_service_FPS=30*k, source_demand_FPS=30*k, admitted_FPS=30*k,
        source_normalization_FPS=30*k, local_assigned_fps=30*k,
        inputs=manifest['inputs'][:k], batch_size=1,
        plan_sha256=config.sha(config.PLAN),
        ready_queue_accounting=dict(enqueue=1800*k,start=1800*k,expired=0),
        last_frame_accounting_counts=dict(source_scheduled=1800*k,source_decoded=1800*k,
            admitted=1800*k,ready=1800*k,started=1800*k,completed=1800*k),
        errors=[], execution_runtime={'status':'STRUCTURAL_SYNTHETIC_ONLY'})
    raw = [dict(row) for row in base['raw'] if row['phase'] == 'warmup' or
           (row['phase'] == 'active' and int(row['stream_id']) < k)]
    active = [row for row in raw if row['phase'] == 'active']
    source_check = source_slot_check(condition, active)
    dispatch_check = dispatch_completion_check(active)
    phase = [dict(row) for row in base['phase'] if int(row['stream_id']) < k]
    workers = copy.deepcopy(base['workers'])
    for worker in workers:
        worker_id = int(worker['worker_id'])
        count = sum(int(row['worker_id']) == worker_id for row in phase)
        worker.update(records=count, record_calls=2*(30+count), elapsed_calls=count)
    summary = summarize(manifest, raw, base['power'])
    require(summary['integrity_status'] == 'VALID' and not summary['errors'],
            f"K{k} child summary failed: {summary['errors'][:2]}")
    summary.update(integrity_status='PENDING_PROCESS_EXIT',
                   validity='PENDING_PROCESS_EXIT',status_finalized=False,
                   measurement_integrity_status='VALID')
    save_json(path/'manifest.json', manifest)
    save_json(path/'summary.json', summary)
    save_json(path/'phase_instrumentation_manifest.json', workers)
    save_rows(path/'per_frame.csv.gz', raw, base['raw_header'])
    save_rows(path/'per_frame_phase_timestamps.csv', phase, base['phase_header'])
    shutil.copyfile(SOURCE/'power_trace.csv.gz', path/'power_trace.csv.gz')
    for name in ('CPU_BEFORE_RUN.json','CPU_AFTER_RUN.json','CPU_TIME_IN_STATE_DELTA.json'):
        shutil.copyfile(SOURCE/name, path/name)
    (path/'stderr.log').write_text('STRUCTURAL_SYNTHETIC_ONLY\n')
    final = parent_finalize(path)
    require(final['integrity_status'] == 'VALID' and final['PIPELINE_AUDIT'] == 'PASS',
            f"K{k} production parent finalizer failed: {final['errors'][:2]}")
    analyzed = analyze_run(path, condition)
    require(analyzed['integrity_status'] == 'VALID',
            f"K{k} offline analyzer failed: {analyzed['errors'][:2]}")
    require(analyzed['actual_source_frames'] == k*1800 and
            analyzed['active_concurrency_peak'] <= 3, 'K/C accounting mismatch')
    save_json(path/'SYNTHETIC_ONLY.json', dict(source=str(SOURCE), K=k,
        status='STRUCTURAL_VALIDATION_ONLY', not_performance_evidence=True,
        no_real_K_specific_runtime_executed=True))
    return dict(status='PASS', **source_check, **dispatch_check,
                child_summary='PASS', parent_finalizer='PASS', analyzer='PASS',
                active_concurrency_peak=analyzed['active_concurrency_peak']), (manifest,raw,phase,workers,final)


def negative_cases(condition, base, positive_path):
    manifest, raw, phase, workers, final = base
    active = [row for row in raw if row['phase'] == 'active']
    cases = {}
    def reject(name, rows, summary=final):
        result = validate_source(condition, manifest, rows, summary)
        require(result['status'] == 'FAIL', name+' incorrectly accepted')
        cases[name] = result['errors']
    extra = [dict(row) for row in raw]
    added = dict(active[0], stream_id='3')
    extra.append(added)
    reject('N1_extra_fourth_stream', extra)
    reject('N2_missing_expected_stream', [row for row in raw if row['phase']=='warmup' or row['stream_id']!='2'])
    missing = list(raw)
    missing.remove(active[0])
    reject('N3_wrong_total_count', missing)
    broken = dict(final, per_stream=final['per_stream'][:-1])
    reject('N4_wrong_per_stream_cardinality', raw, broken)
    outside = [dict(row) for row in raw]
    next(row for row in outside if row['phase']=='active')['stream_id'] = '9'
    reject('N5_out_of_range_stream', outside)
    over = dict(final, active_concurrency_peak=4)
    reject('N6_C_exceeded', raw, over)
    # Also run malformed source traces through the actual production parent
    # finalizer, which recomputes the summary from raw rather than trusting a
    # malformed saved summary.
    for name, rows in (('N1_extra_fourth_stream', extra),
                       ('N2_missing_expected_stream', [row for row in raw if row['phase']=='warmup' or row['stream_id']!='2']),
                       ('N3_wrong_total_count', missing),
                       ('N5_out_of_range_stream', outside)):
        path = DEST/'negative_parent'/name
        path.mkdir(parents=True, exist_ok=False)
        for item in ('manifest.json','summary.json','per_frame_phase_timestamps.csv',
                     'phase_instrumentation_manifest.json','power_trace.csv.gz','stderr.log'):
            shutil.copyfile(positive_path/item, path/item)
        save_rows(path/'per_frame.csv.gz', rows, list(raw[0]))
        verdict = parent_finalize(path)
        require(verdict['integrity_status'] == 'INVALID' and
                verdict['PIPELINE_AUDIT'] == 'FAIL', name+' parent finalizer accepted malformed source')
        cases[name].append('production_parent_finalizer=INVALID')
    overlap = [dict(row) for row in raw]
    first = [row for row in overlap if row['phase']=='active'][:4]
    stamp = max(int(row['ready_timestamp_ns']) for row in first)
    for row in first:
        row['inference_start_timestamp_ns'] = str(stamp)
        row['expiry_check_ns'] = str(stamp)
        row['completion_timestamp_ns'] = str(stamp+1_000_000)
    path = DEST/'negative_parent'/'N6_C_exceeded'
    path.mkdir(parents=True, exist_ok=False)
    for item in ('manifest.json','summary.json','per_frame_phase_timestamps.csv',
                 'phase_instrumentation_manifest.json','power_trace.csv.gz','stderr.log'):
        shutil.copyfile(positive_path/item, path/item)
    save_rows(path/'per_frame.csv.gz', overlap, list(raw[0]))
    verdict = parent_finalize(path)
    require(verdict['integrity_status'] == 'INVALID' and
            'Local C exceeded' in verdict['errors'],
            'N6 parent finalizer accepted active concurrency > 3')
    cases['N6_C_exceeded'].append('production_parent_finalizer=INVALID')
    return cases


def main():
    run, finalizer = Context().bindings()
    source = config.run_source()
    supervisor = __import__('run_ksweep').supervisor_source()
    require(run.__name__ == 'run_one' and finalizer.__name__ == 'finalize_run' and
            'preallocate_source_rows(condition[\'K\'],condition[\'seconds\'])' in source and
            'for stream_id in range(k)' in source and
            "s=old.rep(s,'K=8,C=2,freq_state='" in supervisor,
            'Production K/C source/supervisor binding mismatch')
    require(not DEST.exists(), 'Synthetic validation namespace already exists')
    DEST.mkdir()
    raw = read(SOURCE/'per_frame.csv.gz')
    phase = read(SOURCE/'per_frame_phase_timestamps.csv')
    base = dict(manifest=json.loads((SOURCE/'manifest.json').read_text()),
                raw=raw, phase=phase, power=read(SOURCE/'power_trace.csv.gz'),
                workers=json.loads((SOURCE/'phase_instrumentation_manifest.json').read_text()),
                raw_header=list(raw[0]), phase_header=list(phase[0]))
    report = {}
    fixtures = {}
    for k in (1,3,8):
        condition = next(row for row in config.order() if row['K']==k and row['repeat']==1)
        report[f'K{k}'], fixtures[k] = fixture(condition, base)
    require(report['K3']['active_concurrency_peak'] == 3 and
            report['K8']['active_concurrency_peak'] == 3,
            'C_L=3 capability was not exercised by a positive fixture')
    condition = next(row for row in config.order() if row['K']==3 and row['repeat']==1)
    report['negative'] = negative_cases(condition, fixtures[3], DEST/'positive_K3')
    require(len(report['negative']) == 6, 'All six negative fixtures required')
    save_json(config.OUT/('regression_report_'+TAG+'.json'), dict(status='PASS',
        provenance='STRUCTURAL_SYNTHETIC_FILTER_OF_VALID_K8_C3_TRACE; NOT_MEASURED_K_SWEEP',
        results=report))
    print(json.dumps({k:('PASS' if k=='negative' else v['status']) for k,v in report.items()}))


if __name__ == '__main__':
    main()
