"""CPU/log-only pilot analysis with hard actual-schedule and restore gates."""
import argparse
import csv
import json
import math
import numbers
import statistics
import sys
import types
from collections import defaultdict
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parents[1] / 'timely_capacity_scan' / 'analysis_revision01'))
sys.path.insert(0, str(HERE.parents[1] / 'timely_capacity_scan'))
import analyze_revision as revision
import analyze_timely_scan as old_analysis
import run_timely_scan as old_runner
from pilot02_config import OUT, PLAN, order, load_plan, sha, decorate
from pilot_fidelity import validate_trace

PAIR_IDS = (("V22_BLOCKA_D100_A1_P02", "V22_BLOCKA_D100_S1_P02"),
            ("V22_BLOCKA_D100_A2_P02", "V22_BLOCKA_D100_S2_P02"))


def bound_validate():
    fn = old_analysis.validate
    return types.FunctionType(fn.__code__, dict(fn.__globals__, decorate=decorate))


def _read_artifacts(directory):
    b1 = old_analysis.b1
    manifest = json.loads((directory / 'manifest.json').read_text())
    summary = json.loads((directory / 'summary.json').read_text())
    frames = b1.read(directory / 'per_frame.csv.gz')
    phases = b1.read(directory / 'per_frame_phase_timestamps.csv')
    instrumentation = json.loads((directory / 'phase_instrumentation_manifest.json').read_text())
    return manifest, summary, frames, phases, instrumentation


def validate_integrity(directory, condition):
    plan = load_plan()
    manifest, summary, frames, phases, instrumentation = _read_artifacts(directory)
    inherited = bound_validate()(condition, manifest, summary, frames, phases, instrumentation)
    fidelity = validate_trace(frames, manifest, condition, plan)
    admitted = [row for row in frames if row.get('phase') == 'active' and row.get('placement') == 'LOCAL']
    terminal = revision.terminal_partition(admitted, condition['deadline_ms'])
    errors = list(inherited['errors']) + fidelity['errors']
    if not terminal['terminal_accounting_PASS'] or not terminal['terminal_partition_PASS']:
        errors += ['exact mutually exclusive/exhaustive terminal partition FAIL'] + terminal['terminal_partition_errors']
    if summary.get('integrity_status') != 'VALID':
        errors.append('frozen summary integrity != VALID')
    return {'status': 'PASS' if not errors else 'FAIL', 'errors': errors[:100],
            'frozen_integrity': inherited, 'actual_schedule_fidelity': fidelity,
            'terminal_partition': terminal}


def _bound_revision_run(directory, condition):
    base = old_analysis.analyze_run
    rebound_base = types.FunctionType(base.__code__, dict(base.__globals__,
                                       validate=bound_validate(), cohort_metrics=revision.cohort_metrics))
    proxy = types.SimpleNamespace(**dict(revision.prior.__dict__, analyze_run=rebound_base))
    fn = revision.analyze_run
    return types.FunctionType(fn.__code__, dict(fn.__globals__, prior=proxy))(directory, condition)


def _number(row, name):
    value = row.get(name)
    return float(value) if value not in ('', None) else None


def _states(frames, deadline):
    for row in frames:
        if row.get('phase') != 'active' or int(row.get('admitted') or 0) != 1:
            continue
        due = _number(row, 'logical_arrival_ns')
        completion = _number(row, 'completion_timestamp_ns')
        if row.get('terminal_state') == 'EXPIRED_DROP':
            state = 'expired'
        elif completion is not None and due is not None:
            state = 'timely' if completion - due <= deadline * 1_000_000 else 'late'
        else:
            state = 'missing'
        yield row, state


def stream_and_position_rows(frames, condition):
    D = condition['deadline_ms']
    grouped = defaultdict(list)
    slots = defaultdict(list)
    for row, state in _states(frames, D):
        sid = int(row['stream_id'])
        frame_id = int(row['frame_id'])
        grouped[sid].append((row, state))
        slots[frame_id].append((row, state))
    streams = []
    for sid in range(8):
        items = grouped[sid]
        counts = {state: sum(xstate == state for _, xstate in items)
                  for state in ('timely', 'late', 'expired', 'missing')}
        n = len(items)
        streams.append({'run_id': condition['run_id'], 'stream_id': sid,
                        'admitted': n, **counts, 'TIR': counts['timely'] / n if n else None,
                        'timely_FPS': counts['timely'] / 60,
                        'late_completed_FPS': counts['late'] / 60,
                        'expired_FPS': counts['expired'] / 60})
    positions = defaultdict(list)
    for frame_id, items in slots.items():
        ordered = sorted(items, key=lambda item: int(item[0]['stream_id']))
        for rank, (row, state) in enumerate(ordered, 1):
            ready = _number(row, 'ready_timestamp_ns')
            start = _number(row, 'inference_start_timestamp_ns')
            wait_ms = (start - ready) / 1e6 if ready is not None and start is not None else None
            positions[rank].append((state, wait_ms))
    position_rows = []
    for rank in range(1, 9):
        items = positions[rank]
        n = len(items)
        waits = [wait for _, wait in items if wait is not None]
        position_rows.append({'run_id': condition['run_id'], 'dispatch_position': rank,
                              'admitted': n,
                              **{state + '_fraction': sum(value == state for value, _ in items) / n if n else None
                                 for state in ('timely', 'late', 'expired')},
                              'executed_queue_wait_p95_ms': float(np.percentile(waits, 95)) if waits else None,
                              'definition': 'canonical ascending stream order restricted to Local-admitted set in each source slot'})
    return streams, position_rows


def analyze_run(directory, condition):
    row, trace = _bound_revision_run(directory, condition)
    manifest, _, frames, _, _ = _read_artifacts(directory)
    fidelity = validate_trace(frames, manifest, condition, load_plan())
    previous = row.get('classification')
    row['timely_99pct_classification'] = previous
    row['actual_schedule_fidelity'] = fidelity['status']
    row['actual_m_n_first_period'] = fidelity['actual_m_n_first_period']
    row['source_frame_rows'] = fidelity['source_frame_rows']
    row['schedule_errors'] = fidelity['errors']
    row['requested_GPU_frequency_MHz'] = condition['frequency_MHz']
    if previous == 'INVALID' or fidelity['status'] != 'PASS':
        row['classification'] = 'INVALID'
        row['TIR_admission_valid'] = False
        row['TIR_admission'] = None
        row['integrity_status'] = 'INVALID'
    else:
        row['classification'] = 'VALID'
    stream_rows, position_rows = stream_and_position_rows(frames, condition)
    if row['classification'] == 'VALID':
        values = [value['TIR'] for value in stream_rows]
        row.update(worst_stream_TIR=min(values), best_stream_TIR=max(values),
                   max_minus_min_TIR=max(values) - min(values),
                   per_stream_TIR_sample_SD=statistics.stdev(values),
                   worst_stream_timely_FPS=min(value['timely_FPS'] for value in stream_rows))
    return row, trace, fidelity, stream_rows, position_rows


def paired_comparison(rows, requested_pairs=PAIR_IDS):
    if tuple(tuple(pair) for pair in requested_pairs) != PAIR_IDS:
        raise ValueError('Wrong D100 pairing; frozen pairs are (A1,S1) and (A2,S2)')
    by_id = {row['run_id']: row for row in rows}
    result = []
    for pair_index, (a_id, s_id) in enumerate(PAIR_IDS, 1):
        a, s = by_id[a_id], by_id[s_id]
        valid = a['classification'] == s['classification'] == 'VALID'
        delta = s['TIR_admission'] - a['TIR_admission'] if valid else None
        result.append({'pair': pair_index, 'aligned_run_id': a_id, 'staggered_run_id': s_id,
                       'aligned_TIR': a['TIR_admission'], 'staggered_TIR': s['TIR_admission'],
                       'delta_TIR_S_minus_A': delta, 'valid': valid})
    deltas = [row['delta_TIR_S_minus_A'] for row in result]
    signal = all(value is not None for value in deltas) and all(abs(value) >= .01 for value in deltas) and deltas[0] * deltas[1] > 0
    verdict = ('TEMPORAL_EFFECT_SUPPORTED_FOR_FORMAL_EXPANSION' if signal else
               'INCONCLUSIVE_INVALID' if any(value is None for value in deltas) else 'NO_FORMAL_EXPANSION_SIGNAL')
    return result, verdict


def require_restore(out=OUT):
    restore = out / 'CPU_RESTORE_READBACK.json'
    if not restore.exists():
        raise RuntimeError('CPU restore PASS required before analyzer')
    observed = json.loads(restore.read_text())
    reference = json.loads((out / 'CPU_STATE_BEFORE.json').read_text())
    if observed.get('status') != 'PASS' or observed.get('mode') != 'restored':
        raise RuntimeError('CPU restore readback not PASS')
    if old_runner.cpu.original.validate(observed['snapshot'], reference, 'restored')['status'] != 'PASS':
        raise RuntimeError('CPU restore snapshot mismatch')
    exits = [json.loads(path.read_text()).get('child_exit_monotonic_ns', 0)
             for path in out.glob('V22_BLOCKA_*/manifest.json')]
    if exits and observed['snapshot']['monotonic_ns'] < max(exits):
        raise RuntimeError('CPU restore predates last child exit')


def write_csv(path, rows):
    with path.open('x', newline='') as stream:
        if not rows:
            stream.write('')
            return
        keys = list(dict.fromkeys(key for row in rows for key in row))
        writer = csv.DictWriter(stream, fieldnames=keys, extrasaction='ignore')
        writer.writeheader()
        for row in rows:
            writer.writerow({key: json.dumps(value, sort_keys=True) if isinstance(value, (dict, list)) else value for key, value in row.items()})


def condition_summary(rows):
    grouped = defaultdict(list)
    for row in rows:
        grouped[(row['deadline_ms'], row['admission_pattern'])].append(row)
    result = []
    for (deadline, pattern), run_rows in sorted(grouped.items()):
        item = {'deadline_ms': deadline, 'pattern': pattern,
                'run_ids': [row['run_id'] for row in run_rows],
                'valid_repeats': sum(row['classification'] == 'VALID' for row in run_rows)}
        numeric_keys = sorted({key for row in run_rows for key, value in row.items()
                               if isinstance(value, numbers.Real) and not isinstance(value, bool)})
        for key in numeric_keys:
            vals = [float(row[key]) for row in run_rows if row['classification'] == 'VALID'
                    and isinstance(row.get(key), numbers.Real) and not isinstance(row.get(key), bool)
                    and math.isfinite(float(row[key]))]
            item.update({key + '_mean': statistics.mean(vals) if vals else None,
                         key + '_sample_SD': statistics.stdev(vals) if len(vals) > 1 else None,
                         key + '_min': min(vals) if vals else None,
                         key + '_max': max(vals) if vals else None})
        result.append(item)
    return result


def mechanism_checks(rows, expectations):
    """Diagnostic only; the paired pilot gate does not call this function."""
    by_id = {row['run_id']: row for row in rows}
    checks = []
    for expectation in expectations['expectations']:
        D = expectation['deadline_ms']
        pairs = tuple((f'V22_BLOCKA_D{D}_A{rep}_P02', f'V22_BLOCKA_D{D}_S{rep}_P02') for rep in (1, 2))
        pair_rows = [(by_id[a], by_id[s]) for a, s in pairs]
        usable = all(a['classification'] == s['classification'] == 'VALID' for a, s in pair_rows)
        observed = [{'pair': rep, 'A_TIR': a.get('TIR_admission'), 'S_TIR': s.get('TIR_admission'),
                     'A_queue_p95': a.get('queue_p95'), 'S_queue_p95': s.get('queue_p95'),
                     'A_queue_p99': a.get('queue_p99'), 'S_queue_p99': s.get('queue_p99')}
                    for rep, (a, s) in enumerate(pair_rows, 1)]
        matched = 'UNRESOLVED'
        note = 'Not used in validity, phase search, pair gate, or run order.'
        if usable:
            kind = expectation['kind']
            if kind == 'pair_TIR_direction':
                matched = 'MATCHED' if all(s['TIR_admission'] > a['TIR_admission'] for a, s in pair_rows) else 'NOT_MATCHED'
            elif kind == 'pair_delta_001':
                matched = 'MATCHED' if all(s['TIR_admission'] - a['TIR_admission'] >= .01 for a, s in pair_rows) else 'NOT_MATCHED'
            elif kind == 'pair_queue_lower':
                matched = 'MATCHED' if all(s['queue_p95'] < a['queue_p95'] and s['queue_p99'] < a['queue_p99'] for a, s in pair_rows) else 'NOT_MATCHED'
            elif kind == 'descriptive_tir_near_99':
                matched = 'MATCHED' if all(s['TIR_admission'] >= .99 for _, s in pair_rows) else 'UNRESOLVED'
                note += ' "Near 0.99" was not given a numeric threshold; below 0.99 cannot be scored as a definitive mismatch.'
        checks.append({'expectation_id': expectation['id'], 'deadline_ms': D,
                       'expectation': expectation['text'], 'observed': observed,
                       'matched': matched, 'notes': note, 'verdict_effect': 'NONE'})
    return checks


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if not args.output.resolve().is_relative_to(OUT.resolve()):
        raise RuntimeError('Analysis output must be under pilot root')
    require_restore()
    plan = load_plan()
    rows, traces, fidelities, streams, positions = [], [], [], [], []
    for condition in plan['order']:
        directory = OUT / condition['run_id']
        row, trace, fidelity, per_stream, per_position = analyze_run(directory, condition)
        row['admission_pattern'] = condition['admission_pattern']
        rows.append(row)
        traces += trace
        fidelities.append({'run_id': condition['run_id'], **fidelity})
        streams += per_stream
        positions += per_position
    pairs, verdict = paired_comparison(rows)
    args.output.mkdir(parents=True, exist_ok=False)
    for name, values in (('per_run.csv', rows), ('per_condition_summary.csv', condition_summary(rows)),
                         ('D100_pairs.csv', pairs), ('per_stream.csv', streams),
                         ('slot_dispatch_position.csv', positions),
                         ('actual_schedule_fidelity.csv', fidelities), ('backlog_trace.csv', traces)):
        write_csv(args.output / name, values)
    (args.output / 'pilot_gate.json').write_text(json.dumps({'D100_gate': verdict, 'pairs': pairs,
        'D67_role': 'secondary descriptive only', 'historical_208_merged_into_repeat_count': False,
        'statistical_significance_claim': False}, indent=2) + '\n')
    # Mechanism expectations are read only AFTER the paired gate has been computed.
    expectations = json.loads((OUT / 'mechanism_expectations.json').read_text())
    write_csv(args.output / 'mechanism_expectation_check.csv', mechanism_checks(rows, expectations))
    historical = old_analysis.b1.read(OUT / 'historical_208_reference.csv')
    write_csv(args.output / 'historical_208_descriptive_only.csv', historical)
    (args.output / 'analysis_provenance.json').write_text(json.dumps({'plan_sha256': sha(PLAN),
        'historical_208_reference_sha256': sha(OUT / 'historical_208_reference.csv'),
        'historical_rows_in_new_pair_gate': 0, 'frozen_V22_worker_source_sha256': plan['frozen_worker_sha256']}, indent=2) + '\n')


if __name__ == '__main__':
    main()
