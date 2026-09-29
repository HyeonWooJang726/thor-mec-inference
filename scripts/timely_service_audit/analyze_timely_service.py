#!/usr/bin/env python3
"""Offline deadline audit. Read existing traces; write only a NEW output directory."""
import argparse
import csv
import gzip
import hashlib
import json
import math
import statistics as st
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEADLINES = (40, 60, 80, 100, 150, 200)
CAMPAIGNS = ('equal_service_map', 'hybrid_e0_e40', 'k8_workload_gate',
             'local_capacity_characterization')


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def inventory():
    return {str(p.relative_to(ROOT)): digest(p)
            for name in CAMPAIGNS
            for p in sorted((ROOT / 'results' / name).rglob('*')) if p.is_file()}


def read_json(path):
    return json.loads(path.read_text())


def write_csv(path, rows):
    with path.open('x', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def avg_sd(values):
    return st.mean(values), st.stdev(values) if len(values) > 1 else None


def metrics(frames, duration, deadline):
    completed = [r for r in frames if r['completion'] is not None]
    on_time = sum(r['completion'] - r['arrival'] <= deadline * 1_000_000
                  for r in completed)
    return dict(admitted_frames=len(frames), completed_frames=len(completed),
                on_time_frames=on_time, late_frames=len(completed) - on_time,
                missing_frames=len(frames) - len(completed),
                admitted_fps=len(frames) / duration,
                timely_fps=on_time / duration,
                TIR=on_time / len(frames) if frames else None)


def fixture():
    # Boundary inclusion, 1 ns late, drain completion, missing completion.
    frames = [{'arrival': 0, 'completion': 40_000_000},
              {'arrival': 0, 'completion': 40_000_001},
              {'arrival': 990_000_000, 'completion': 1_020_000_000},
              {'arrival': 0, 'completion': None}]
    m = metrics(frames, 1, 40)
    assert (m['on_time_frames'], m['late_frames'], m['missing_frames'], m['TIR']) == (2, 1, 1, .5)


def selected_runs():
    result = []
    p = ROOT / 'results/equal_service_map'
    for c in read_json(p / 'plan.json')['order']:
        result.append((p / c['run_id'], 'PRIMARY', c['cell'], c['repeat']))
    assert len(result) == 24
    p = ROOT / 'results/hybrid_e0_e40'
    plan = read_json(p / 'plan.json')
    for c in plan['order']:
        if c['edge_r'] == 5:
            result.append((p / c['run_id'], 'PRIMARY', 'Hybrid240', c['repeat']))
    for repeat, name in enumerate(plan['baseline_local240_run_ids'], 1):
        result.append((ROOT / 'results/k8_workload_gate' / name,
                       'PRIMARY', 'HistoricalLocal240', repeat))
    assert len(result) == 32
    p = ROOT / 'results/local_capacity_characterization'
    for mpath in sorted(p.glob('*/manifest.json')):
        m = read_json(mpath)
        assert m['K'] == 8
        c = m['condition']
        result.append((mpath.parent, 'SECONDARY_LOCAL_CHARACTERIZATION',
                       f"F{c['frequency_MHz']}_r{c['r']}", c['repeat']))
    return result


def analyze_run(path, scope, condition, repeat, hashes):
    m, s = read_json(path / 'manifest.json'), read_json(path / 'summary.json')
    t0, t1 = int(m['active_start_ns']), int(m['active_end_ns'])
    duration = (t1 - t0) / 1e9
    assert duration == float(m['measurement_seconds']) == 60, path
    assert s['integrity_status'] == 'VALID', path
    assert m['child_returncode'] == 0 and m['frequency_restore_ok'], path
    with gzip.open(path / 'per_frame.csv.gz', 'rt', newline='') as f:
        reader = csv.DictReader(f)
        schema = reader.fieldnames
        required = {'phase', 'stream_id', 'frame_id', 'admitted', 'logical_arrival_ns',
                    'admission_timestamp_ns', 'completion_timestamp_ns'}
        assert required <= set(schema), (path, schema)
        active = [r for r in reader if r['phase'] == 'active']
    assert len(active) == s['source_frames'] == 14400, path
    assert len({(r['stream_id'], r['frame_id']) for r in active}) == len(active), path
    frames = []
    for r in active:
        arrival = int(r['logical_arrival_ns'])
        assert t0 <= arrival < t1, (path, r)
        if int(r['admitted']) == 0:
            continue
        admission = int(r['admission_timestamp_ns'])
        assert t0 <= admission < t1 and admission == arrival, (path, r)
        completion = int(r['completion_timestamp_ns']) if r['completion_timestamp_ns'] else None
        placement = r.get('placement', 'LOCAL')
        assert placement in ('LOCAL', 'EDGE'), (path, placement)
        if placement == 'EDGE':
            assert completion == int(r['response_completion_ns']), (path, r)
        assert completion is not None and completion >= arrival, (path, r)
        frames.append(dict(stream=int(r['stream_id']), arrival=arrival,
                           completion=completion, placement=placement))
    completed = sum(r['completion'] is not None for r in frames)
    active_completed = sum(t0 <= r['completion'] < t1 for r in frames)
    replay = dict(admitted_frames=len(frames), completed_frames_including_drain=completed,
                  aggregate_completed_fps=active_completed / duration)
    count_field = 'total_completed_active_frames' if 'total_completed_active_frames' in s else 'completed_active_frames'
    replay[count_field] = active_completed
    for key, value in replay.items():
        assert math.isclose(s[key], value, rel_tol=0, abs_tol=1e-9), (path.name, key, s[key], value)
    assert sorted({r['stream'] for r in frames}) == list(range(8)), path
    assert len({sum(r['stream'] == k for r in frames) for k in range(8)}) == 1, path
    base = dict(scope=scope, condition=condition, run_id=path.name, repeat=repeat,
                duration_s=duration, frequency_MHz=m['requested_freq_MHz'],
                integrity_status=s['integrity_status'], queue_stable=s['queue_stable'],
                supply_status=s['supply_status'], hardware_status=s['hardware_status'])
    inv = dict(**base, run_directory=str(path.relative_to(ROOT)), raw_schema=';'.join(schema),
               replay_status='PASS', admitted_frames=len(frames), completed_frames=completed,
               completed_active_frames=active_completed, raw_completed_fps=active_completed/duration,
               drain_completed_frames=completed-active_completed)
    for name in ('manifest.json', 'summary.json', 'per_frame.csv.gz'):
        inv[name + '_sha256'] = hashes[str((path / name).relative_to(ROOT))]
    runs, streams, paths = [], [], []
    for d in DEADLINES:
        b = dict(**base, deadline_ms=d)
        sk = [dict(**b, stream_id=k, **metrics([r for r in frames if r['stream']==k], duration, d))
              for k in range(8)]
        streams.extend(sk)
        tirs = [r['TIR'] for r in sk]
        runs.append(dict(**b, **metrics(frames, duration, d),
                         raw_completed_fps=active_completed/duration,
                         cohort_completed_per_active_second=completed/duration,
                         mean_stream_TIR=st.mean(tirs), minimum_stream_TIR=min(tirs),
                         maximum_stream_TIR=max(tirs), stream_TIR_sample_SD=st.stdev(tirs)))
        for placement in ('LOCAL', 'EDGE'):
            paths.append(dict(**b, path=placement,
                              **metrics([r for r in frames if r['placement']==placement], duration, d)))
    return inv, runs, streams, paths


def summarize(rows, group_fields, value_fields):
    groups = defaultdict(list)
    for r in rows:
        groups[tuple(r[k] for k in group_fields)].append(r)
    out = []
    for key, group in sorted(groups.items()):
        r = dict(zip(group_fields, key))
        r['repeats'] = len(group)
        r['stable_repeats'] = sum(x['queue_stable'] for x in group)
        for field in value_fields:
            vals = [x[field] for x in group if x[field] is not None]
            mean, sd = avg_sd(vals) if vals else (None, None)
            r[field + '_mean'], r[field + '_sample_SD'] = mean, sd
        out.append(r)
    return out


def tables(summary):
    order = ['A160', 'B160', 'A176', 'B176', 'A184', 'B184', 'A200', 'B200',
             'HistoricalLocal240', 'Hybrid240']
    lookup = {(r['condition'], r['deadline_ms']): r for r in summary if r['scope']=='PRIMARY'}
    main = ['| Condition | Raw active FPS | ' + ' | '.join(f'{d} ms' for d in DEADLINES) + ' |',
            '|---|---|' + '---|' * 6]
    worst = ['| Condition | ' + ' | '.join(f'{d} ms' for d in DEADLINES) + ' |',
             '|---|' + '---|' * 6]
    for c in order:
        first = lookup[c, DEADLINES[0]]
        cells, w = [], []
        for d in DEADLINES:
            r = lookup[c,d]
            cells.append(f"{r['timely_fps_mean']:.2f}±{r['timely_fps_sample_SD']:.2f} / "
                         f"{100*r['TIR_mean']:.2f}±{100*r['TIR_sample_SD']:.2f}%")
            w.append(f"{100*r['minimum_stream_TIR_mean']:.2f}±{100*r['minimum_stream_TIR_sample_SD']:.2f}%")
        main.append(f"| {c} | {first['raw_completed_fps_mean']:.3f}±{first['raw_completed_fps_sample_SD']:.3f} | " + ' | '.join(cells) + ' |')
        worst.append('| ' + c + ' | ' + ' | '.join(w) + ' |')
    return '\n'.join(main), '\n'.join(worst)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'results/timely_service_audit/analysis01')
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit('Refusing to overwrite existing output: ' + str(args.output))
    fixture()
    before = inventory()
    inputs, run_rows, stream_rows, path_rows = [], [], [], []
    for selection in selected_runs():
        inv, run, stream, path = analyze_run(*selection, before)
        inputs.append(inv); run_rows.extend(run); stream_rows.extend(stream); path_rows.extend(path)
    summary = summarize(run_rows, ['scope', 'condition', 'deadline_ms'],
                        ['raw_completed_fps', 'timely_fps', 'TIR', 'minimum_stream_TIR'])
    path_summary = summarize(path_rows, ['scope', 'condition', 'path', 'deadline_ms'], ['timely_fps', 'TIR'])
    after = inventory()
    assert before == after, 'Existing artifacts changed; no successful audit produced'
    args.output.mkdir(parents=True, exist_ok=False)
    for name, rows in [('input_inventory', inputs), ('per_run_deadlines', run_rows),
                       ('per_stream_deadlines', stream_rows), ('per_path_deadlines', path_rows),
                       ('condition_summary', summary), ('path_summary', path_summary)]:
        write_csv(args.output / (name + '.csv'), rows)
    main_table, worst_table = tables(summary)
    report = f'''# Timely-service deadline audit

32 primary runs: Equal-Service 24; historical K8 Local-only240 3; formal Hybrid240 5.
Local characterization {len(inputs)-32} runs are secondary, separately grouped by frequency/admission.
No new workload; no runtime modifications; no fitting; no deadline pass/fail threshold.

## Definitions and validation

Active-admitted cohort: phase=active, admitted=1, logical arrival and admission timestamps inside [start,end).
All completions, including drain completions, are included in deadline metrics.
Local completion_timestamp_ns is the canonical Thor completion; Edge response_completion_ns is
verified equal to completion_timestamp_ns. Only Thor-clock E2E differences are used.
On-time means integer completion-arrival <= D*1,000,000 ns. TIR denominator is admitted frames.
Late counts are completed but late; missing completions are separate. All selected frames completed.
Raw completed FPS retains canonical active-completion/60s accounting; cohort_completed_per_active_second
includes drain completions and must NOT be interpreted as sustained throughput.
Timely FPS=on-time cohort/60s may include on-time completions just after the active end.
Per-run values are aggregated with equal repeat weight; SD is sample SD, not a confidence interval.
Worst-stream TIR is each run's minimum of eight stream TIRs, then mean/sample SD across repeats.
Within-run stream TIR SD is separately provided in per_run_deadlines.csv.
No Edge admissions produces N/A path TIR. Each adaptive secondary condition retains its own repeat count;
one-repeat conditions have no sample SD. Frontend/protection annotations are retained per run.
All admitted/full completion/active completion counts and stored active FPS replay correctly.
All source cohorts contain 14,400 unique frames; admitted streams are 0..7 with equal counts.
All manifests report exit 0 and frequency restore; all stored measurement integrity is VALID.
Existing result-directory SHA-256 inventories match before and after analysis.
Deadline-boundary/drain/missing CPU fixture passes and is not measurement data.

## Primary: timely FPS / TIR percent (mean ± sample SD)

{main_table}

## Primary: worst-stream TIR percent (mean ± sample SD)

{worst_table}

Historical Local240 and formal Hybrid240 are separate campaigns/harnesses, not contemporaneous paired runs.
Equal-Service A/B change both Local frequency and placement; deadline differences do not isolate an Edge causal effect.
These are measured deadline-conditioned service rates at tested operating points, not an optimized timely-capacity curve.
Source frame interval and deadline are distinct. No future experiment has been executed.

Reproduce into a new output directory:
`python3 -B scripts/timely_service_audit/analyze_timely_service.py --output results/timely_service_audit/analysis02`
'''
    (args.output / 'deadline_audit.md').write_text(report)
    verification = dict(status='PASS', primary_runs=32, secondary_runs=len(inputs)-32,
                        replay_mismatches=[], timestamp_clock='Thor monotonic', deadline_ms=DEADLINES,
                        boundary_fixture='PASS', existing_artifact_preservation='PASS',
                        existing_files_hashed=len(before), pre_sha256=before, post_sha256=after,
                        analyzer_sha256=digest(Path(__file__)))
    (args.output / 'verification.json').write_text(json.dumps(verification, indent=2)+'\n')
    assert inventory() == before, 'Post-output preservation failure'
    print(json.dumps({k:v for k,v in verification.items() if k not in ('pre_sha256','post_sha256')}, indent=2))
    print(main_table)
    print(worst_table)


if __name__ == '__main__':
    main()
