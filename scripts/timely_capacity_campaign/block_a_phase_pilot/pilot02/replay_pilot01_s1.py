"""Read-only replay of the failed pilot01 S1 post-run summary into pilot02 evidence."""
import json
import sys
from pathlib import Path

from pilot02_config import OUT, PRIOR, sha
from block_a_summary import read_csv, summarize_with_plan

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pilot_fidelity import validate_trace


def replay():
    run_id = 'V22_BLOCKA_D100_S1_P01'
    directory = PRIOR / run_id
    m = json.loads((directory / 'manifest.json').read_text())
    stored = json.loads((directory / 'summary.json').read_text())
    plan = json.loads((PRIOR / 'plan.json').read_text())
    condition = next(row for row in plan['order'] if row['run_id'] == run_id)
    frames = read_csv(directory / 'per_frame.csv.gz')
    power = read_csv(directory / 'power_trace.csv.gz')
    s = summarize_with_plan(m, frames, power, PRIOR / 'plan.json')
    fidelity = validate_trace(frames, m, condition, plan)
    active = [r for r in frames if r.get('phase') == 'active' and int(r.get('admitted') or 0) == 1]
    per_stream = []
    for sid in range(8):
        rows = [r for r in active if int(r['stream_id']) == sid]
        timely = sum(r.get('completion_timestamp_ns') not in ('', None)
                     and int(r['completion_timestamp_ns']) - int(r['logical_arrival_ns']) <= 100_000_000
                     for r in rows)
        per_stream.append({'stream_id': sid, 'admitted': len(rows), 'timely': timely,
                           'TIR_admission': timely / len(rows) if rows else None})
    t = s['terminal_partition']['TOTAL']
    report = {'status': 'PASS' if t['terminal_identity_ok'] and t['true_unfinished'] == 0
              and fidelity['status'] == 'PASS' and len(active) == 12480 else 'FAIL',
              'use': 'REGRESSION_ONLY; pilot01 INVALID verdict unchanged; not a formal pilot repeat',
              'original_stored_summary_integrity': stored.get('integrity_status'),
              'original_stored_manifest_child_returncode': m.get('child_returncode'),
              'post_run_summary_replay_completed': True,
              'outside_timely_plan_exception': False,
              'terminal_partition': t,
              'TIR_admission_diagnostic': sum(row['timely'] for row in per_stream) / len(active),
              'per_stream': per_stream,
              'schedule_fidelity': fidelity,
              'actual_x_restored': fidelity['status'] == 'PASS',
              'actual_m_n_first_period': fidelity['actual_m_n_first_period'],
              'cyclic_shift_and_dispatch_order': fidelity['status'],
              'source_files_SHA256': {name: sha(directory / name) for name in
                  ('manifest.json', 'summary.json', 'per_frame.csv.gz', 'power_trace.csv.gz')},
              'replayed_summary_integrity': s.get('integrity_status'),
              'replayed_summary_errors': s.get('errors', []),
              'replayed_summary_terminal_accounting': s.get('terminal_accounting_status')}
    return report


def main():
    target = OUT / 'pilot01_S1_offline_replay' / 'report.json'
    if target.exists():
        raise RuntimeError('Offline replay report already exists; no overwrite')
    report = replay()
    with target.open('x') as stream:
        json.dump(report, stream, indent=2)
        stream.write('\n')
    print(json.dumps({k: report[k] for k in ('status', 'TIR_admission_diagnostic',
          'replayed_summary_terminal_accounting', 'cyclic_shift_and_dispatch_order')}, indent=2))
    if report['status'] != 'PASS':
        raise RuntimeError('Pilot01 S1 offline replay failed')


if __name__ == '__main__':
    main()
