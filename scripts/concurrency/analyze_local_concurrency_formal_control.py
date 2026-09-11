#!/usr/bin/env python3
"""Strict 30-run post-run analysis. No GPU, workload launch, or figure generation."""

# Resolve shared experiment modules for direct script and repository-root imports.
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parents[1] / "common"))
from script_paths import configure as _configure, script_path
_configure()

import csv
import json
import statistics
from pathlib import Path

from local_concurrency_control_metrics import METRICS, validate_run
from run_local_concurrency_formal_control import ROOT, REPO, ORDER


def csv_write(path, rows):
    keys = list(dict.fromkeys(k for row in rows for k in row))
    with path.open('x', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=keys)
        writer.writeheader(); writer.writerows(rows)


def statistics_of(values):
    if len(values) != 5:
        raise ValueError('exactly five run-level values required')
    return {'mean': statistics.mean(values), 'sample_sd': statistics.stdev(values),
            'min': min(values), 'max': max(values)}


def write_analysis():
    integrity = json.loads((ROOT/'formal_integrity_report.json').read_text())
    if integrity['validation'] != 'PASS':
        raise ValueError('formal integrity failed; no PASS analysis allowed')
    runs, checks = [], []
    for rep, group in enumerate(ORDER, 1):
        for c,k in group:
            run_id = f'run{rep:02d}'
            output = ROOT/f'c{c}'/f'k{k}'/run_id
            if json.loads((output/'exit.json').read_text())['exit_code'] != 0:
                raise ValueError(f'nonzero run exit: {output}')
            summary, check = validate_run(output,c,k,1800,run_id)
            runs.append(summary); checks.append(check)
    expected = {(c,k,f'run{rep:02d}') for c in (1,2) for k in (5,6,7) for rep in range(1,6)}
    if len(runs)!=30 or {(r['C'],r['K'],r['run_id']) for r in runs} != expected:
        raise ValueError('matrix invalid')
    if sum(r['frames'] for r in runs) != 324000:
        raise ValueError('total frames invalid')
    with (ROOT/'analysis_revalidation.json').open('x') as f:
        json.dump({'validation':'PASS','runs':checks,'actual_frames':324000},f,indent=2)
    csv_write(ROOT/'per_run_summary.csv',runs)
    aggregates=[]
    for c in (1,2):
        for k in (5,6,7):
            group=[r for r in runs if (r['C'],r['K'])==(c,k)]
            summary={'C':c,'K':k,'run_count':len(group),'frames':sum(r['frames'] for r in group)}
            for metric in METRICS:
                summary.update({metric+'_'+stat:value for stat,value in statistics_of([r[metric] for r in group]).items()})
            aggregates.append(summary)
    csv_write(ROOT/'formal_summary.csv',aggregates)
    queue_metrics=['peak_waiting_queue','time_weighted_waiting_queue','max_active_inferences','service_overlap_pair_count','service_overlap_time_ms']
    csv_write(ROOT/'queue_summary.csv',[{key:value for key,value in row.items() if key in ('C','K','run_count','frames') or any(key.startswith(m+'_') for m in queue_metrics)} for row in aggregates])
    by_run={(r['C'],r['K'],r['run_id']):r for r in runs}
    by_group={(r['C'],r['K']):r for r in aggregates}
    paired=[]
    primary=['local_latency_mean_ms','local_latency_p95_ms','local_latency_p99_ms','deadline_miss_pct',
             'queue_wait_mean_ms','queue_wait_p95_ms','inference_mean_ms','inference_p95_ms','peak_waiting_queue','time_weighted_waiting_queue']
    for k in (5,6,7):
        for rep in range(1,6):
            run_id=f'run{rep:02d}';a,b=by_run[1,k,run_id],by_run[2,k,run_id]
            row={'K':k,'run_id':run_id}
            for m in primary:
                delta='deadline_miss_difference_pp' if m=='deadline_miss_pct' else m+'_difference'
                row.update({m+'_C1':a[m],m+'_C2':b[m],delta:b[m]-a[m]})
            for label,m in [('miss','deadline_miss_pct'),('queue_wait','queue_wait_mean_ms'),('local_latency','local_latency_mean_ms')]:
                row['C2_improved_'+label]=int(b[m]<a[m])
            paired.append(row)
    csv_write(ROOT/'paired_run_comparison.csv',paired)
    comparisons=[]
    for k in (5,6,7):
        a,b=by_group[1,k],by_group[2,k]
        row={'K':k,'pairs':5}
        for m in primary:
            delta='deadline_miss_difference_pp' if m=='deadline_miss_pct' else m+'_difference'
            row.update({m+'_C1':a[m+'_mean'],m+'_C2':b[m+'_mean'],delta:b[m+'_mean']-a[m+'_mean']})
            row.update({delta+'_paired_'+stat:value for stat,value in statistics_of([p[delta] for p in paired if p['K']==k]).items()})
        # Positive service/latency denominators; no miss-relative or near-zero-queue percentages.
        for m in ('local_latency_mean_ms','local_latency_p95_ms','local_latency_p99_ms','inference_mean_ms','inference_p95_ms'):
            if a[m+'_mean'] <= 0:
                raise ValueError('nonpositive denominator')
            row[m+'_relative_change_pct']=100*(b[m+'_mean']/a[m+'_mean']-1)
        for label in ('miss','queue_wait','local_latency'):
            row['C2_improved_'+label+'_pairs']=sum(p['C2_improved_'+label] for p in paired if p['K']==k)
        comparisons.append(row)
    csv_write(ROOT/'c1_vs_c2_comparison.csv',comparisons)
    # Old C1 is a separate sensitivity reference, never a primary concurrency denominator.
    oldroot=REPO/'results/local_latency_breakdown'
    oldrows=list(csv.DictReader((oldroot/'per_run_summary.csv').open()))
    mapping={'local_latency_mean_ms':'e2e_mean_ms','local_latency_p95_ms':'e2e_p95_ms',
             'local_latency_p99_ms':'e2e_p99_ms','deadline_miss_pct':'deadline_miss_pct',
             'start_lag_mean_ms':'frame_start_lag_mean_ms','front_end_mean_ms':'front_end_mean_ms',
             'queue_wait_mean_ms':'inference_queue_wait_mean_ms','queue_wait_p95_ms':'inference_queue_wait_p95_ms',
             'inference_mean_ms':'inference_mean_ms','inference_p95_ms':'inference_p95_ms'}
    old_comparison=[]
    for k in (5,6,7):
        group=[r for r in oldrows if int(r['K'])==k]
        if {r['run_id'] for r in group}!={f'run{i:02d}' for i in range(1,6)}:
            raise ValueError('old reference lacks five unique runs')
        for new_key,old_key in mapping.items():
            old=statistics_of([float(r[old_key]) for r in group])
            new={stat:by_group[1,k][new_key+'_'+stat] for stat in old}
            old_comparison.append({'K':k,'metric':new_key,'old_source':str((oldroot/'per_run_summary.csv').relative_to(REPO)),
               **{'old_C1_'+stat:value for stat,value in old.items()}, **{'new_C1_'+stat:value for stat,value in new.items()},
               'new_minus_old':new['mean']-old['mean'],'difference_unit':'percentage points' if new_key=='deadline_miss_pct' else 'ms',
               'comparison_role':'implementation sensitivity reference only'})
        # Queue references come from the actual old per-run raw validation summaries.
        for key,oldkey in [('peak_waiting_queue','inference_queue_peak'),('time_weighted_waiting_queue','inference_queue_time_weighted')]:
            values=[]
            for rep in range(1,6):
                val=json.loads((oldroot/f'k{k}'/f'run{rep:02d}'/'validation.json').read_text())['queue'][oldkey]
                values.append(val['numerator']/val['denominator'] if isinstance(val,dict) else val)
            old=statistics_of(values);new={stat:by_group[1,k][key+'_'+stat] for stat in old}
            old_comparison.append({'K':k,'metric':key,'old_source':f'results/local_latency_breakdown/k{k}/runNN/validation.json',
               **{'old_C1_'+stat:value for stat,value in old.items()}, **{'new_C1_'+stat:value for stat,value in new.items()},
               'new_minus_old':new['mean']-old['mean'],'difference_unit':'frames','comparison_role':'implementation sensitivity reference only'})
    csv_write(ROOT/'old_c1_vs_new_c1.csv',old_comparison)
    report(runs,aggregates,comparisons,paired,old_comparison)


def report(runs,aggregates,comparisons,paired,old):
    lines=['# Local inference concurrency formal control', '',
           'Primary comparison: **new control C=1 vs new control C=2**, using identical request, transfer, timing and queue code.',
           'Completed: 30/30 valid runs, 324,000 frames; 162,000 per C. No failed run was excluded or replaced.', '',
           '## Conditions and interpretation boundaries', '',
           '- Canonical RT-DETR B=1 engine, same audited W027 Camera_0000..0006 cumulative K mapping, 30 FPS phase-aligned logical arrivals, 1800 frames/stream, 60-second offered workload; drain included as needed.',
           '- MAXN, DVFS unlocked, jetson_clocks OFF (readable CPU/GPU/EMC min<max), CUDA Graph OFF. No power/clock/model/engine changes. Environment before/after is retained for every run.',
           '- No warm-up or sample exclusion, matching the frozen application workload. The old trtexec warm-up belongs to a separate harness.',
           '- Both C values use private pinned staging, asynchronous H2D, execute_async_v3 on nonblocking worker streams, asynchronous D2H and stream-local synchronization. No cudaDeviceSynchronize is called by this inference path.',
           '- Only concurrency-dependent worker/context/stream/buffer-set counts differ: one vs two. The engine reports two within-inference auxiliary streams per context, unchanged; cuda_stream_count refers to explicit submission streams.',
           '- a/b/r/s/c are raw integer ns. c is host-output availability after stream synchronization. Waiting queue is ready-but-not-started N_enqueue−N_start, excluding all active requests.',
           '- Queue peak covers the whole run through drain; time-weighted waiting queue integrates first to last ready enqueue, identical to the old metric definition.',
           '- Candidate deadline is exactly 1/30 second: e2e_ns*30>1,000,000,000. This is not a final application SLA.',
           '- Specified five rounds interleave C and K; deliberate cooldown NONE. Exact order/commands are in formal_plan.json. Each next run starts only after previous exit, cleanup and artifact validation.',
           '- Paired means matching run indices, not simultaneous execution or a paired randomized trial. Five pairs support descriptive direction/variability, not strong statistical significance claims.',
           '- Host service and submitted-unsynchronized interval overlap establish concurrent submission/outstanding inference only. GPU kernel overlap was not directly measured.', '',
           '## Run-level aggregation', '',
           'Every configuration cell below is the arithmetic mean ± sample SD [min, max] of five run-level statistics. Per-run quantiles use exact linear interpolation of integer ns; no pooling across runs. Full values: per_run_summary.csv and formal_summary.csv.', '',
           '| C | K | Local mean ms | Local median ms | Local p95 ms | Local p99 ms | Miss % | Queue wait mean ms | Inference mean ms |',
           '|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
    show=['local_latency_mean_ms','local_latency_median_ms','local_latency_p95_ms','local_latency_p99_ms','deadline_miss_pct','queue_wait_mean_ms','inference_mean_ms']
    for row in aggregates:
        cells=[f"{row[m+'_mean']:.6f} ± {row[m+'_sample_sd']:.6f} [{row[m+'_min']:.6f}, {row[m+'_max']:.6f}]" for m in show]
        lines.append(f"| {row['C']} | {row['K']} | "+' | '.join(cells)+' |')
    lines += ['', '## Primary C2−C1 comparison', '',
              '| K | Miss difference pp | Queue mean difference ms | Queue p95 difference ms | Local mean difference ms | Local p95 difference ms | Local p99 difference ms | Inference mean difference ms | Inference p95 difference ms | Peak queue difference |',
              '|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
    keys=['deadline_miss_difference_pp','queue_wait_mean_ms_difference','queue_wait_p95_ms_difference','local_latency_mean_ms_difference','local_latency_p95_ms_difference','local_latency_p99_ms_difference','inference_mean_ms_difference','inference_p95_ms_difference','peak_waiting_queue_difference']
    for row in comparisons:
        lines.append(f"| {row['K']} | "+' | '.join(f'{row[key]:.6f}' for key in keys)+' |')
    lines += ['', 'Negative differences indicate lower C2 values. Deadline misses use percentage-point differences. Relative changes are provided only for positive local-latency/inference-service denominators; no relative miss or queue percentage is used.', '',
              '## Paired direction', '', '| K | C2 lower miss | C2 lower queue wait | C2 lower local latency |', '|---:|---:|---:|---:|']
    for row in comparisons:
        lines.append(f"| {row['K']} | {row['C2_improved_miss_pairs']}/5 | {row['C2_improved_queue_wait_pairs']}/5 | {row['C2_improved_local_latency_pairs']}/5 |")
    lines += ['', '| K | Run | Miss C2−C1 pp | Queue wait C2−C1 ms | Local mean C2−C1 ms |', '|---:|---|---:|---:|---:|']
    for row in paired:
        lines.append(f"| {row['K']} | {row['run_id']} | {row['deadline_miss_difference_pp']:.6f} | {row['queue_wait_mean_ms_difference']:.6f} | {row['local_latency_mean_ms_difference']:.6f} |")
    lines += ['', '## Old C1 vs new control C1: sensitivity reference', '',
              'The following values are read from the actual frozen CSV/run validations. This is a historical implementation-sensitivity comparison, not the primary concurrency comparison. It changes transfer/synchronization implementation and was measured at a different time; it cannot isolate which internal change caused a difference. Never use old C1→new C2 as a concurrency effect.', '',
              '| K | Metric | Old C1 mean | New C1 mean | New−old | Unit |', '|---:|---|---:|---:|---:|---|']
    for row in old:
        lines.append(f"| {row['K']} | {row['metric']} | {row['old_C1_mean']:.6f} | {row['new_C1_mean']:.6f} | {row['new_minus_old']:.6f} | {row['difference_unit']} |")
    probe=REPO/'results/local_inference_concurrency/trtexec_probe/concurrency_summary.csv'
    prows=list(csv.DictReader(probe.open()))
    lines += ['', '## Prior trtexec context (separate harness)', '',
              ', '.join(f"infStreams={r['infStreams']}: {float(r['throughput_qps_mean']):.6f} qps" for r in prows)+'.',
              'That probe showed a weak C2 throughput gain and no additional C4 gain. The installed trtexec warned that multi-stream latencies may be inaccurate and recommended throughput. Those values are not equated with application inference service and did not predetermine the application result.', '',
              '## Integrity', '',
              'Every run passed exact arrivals/samples/preprocessing/completions/CSV counts, stream IDs 0..1799 exactly once, phase alignment, a≤b≤r≤s≤c, exact ns decomposition, CSV/raw equality, queue event replay/integral, normal source EOS, waiting=0/active=0 after drain, resource ownership and concurrency bounds. Independent post-run replay rechecked all 30 runs. See formal_integrity_report.json and analysis_revalidation.json.', '',
              'Interpretation and preservation verdict are added after reviewing the completed numeric comparisons.', '']
    with (ROOT/'formal_control_report.md').open('x') as f:
        f.write('\n'.join(lines))


if __name__ == '__main__':
    write_analysis()
