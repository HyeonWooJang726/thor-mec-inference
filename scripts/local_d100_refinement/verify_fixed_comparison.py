#!/usr/bin/env python3
"""Synthetic CPU regression checks; no GPU, network, or frequency access."""
import argparse
import copy
import csv
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
from unittest.mock import patch

import analyze_refinement_fixed as analysis

frozen = analysis.frozen


def score(row, n):
    row.update(integrity_status='VALID', source_frames=14400,
               per_stream=[dict(stream_id=k, timely_completed_frames=n) for k in range(8)],
               worst_stream_timely_FPS=n / 60, worst_stream_TIR=n / 1800,
               timely_FPS=8 * n / 60, late_completed_FPS=1.,
               expired_drop_FPS=2., VIN_J_per_timely_frame=.5)


def fixture():
    new, history = [], []
    for conditions, rows in [(frozen.expected_order(), new),
                             (frozen.best_grid.expected_order(), history)]:
        for c in conditions:
            row = dict(c)
            score(row, 500)
            rows.append(row)
    return new, history


def set_values(rows, cell, values):
    for row in rows:
        if row['cell'] == cell:
            score(row, values[row['repeat'] - 1])


def verify():
    new, history = fixture()
    set_values(new, 'L184', [900, 900, 900])
    set_values(new, 'L176', [1000, 800, 800])
    set_values(history, 'T160-B', [800, 800, 800])
    set_values(history, 'T200-B', [1000, 600, 600])
    result = analysis.grid_analysis(new, history, 'repeat_best_envelope')
    candidates, selected, comp, decision = result
    assert decision['fixed_Best_Local'] == ['L184']
    assert decision['fixed_Best_Hybrid'] == ['T160-B']
    assert decision['verdict'] == 'EDGE_NOT_REQUIRED_FOR_D100_TIMELY_CEILING'
    # The old Oracle reference would be inconclusive; fixed comparison must differ.
    assert frozen.grid_analysis(new, history)[-1]['verdict'] == 'EDGE_ROLE_INCONCLUSIVE'
    assert comp[0]['Local_values'] == [15.] * 3
    assert comp[0]['Hybrid_values'] == [800 / 60] * 3
    assert len(selected) == 4 and {r['cell'] for r in selected} == {'L184'}
    assert len(decision['oracle_upper_bounds']) == 6
    assert all(not r['primary_gate_used'] for r in decision['oracle_upper_bounds'])
    assert next(r for r in decision['oracle_upper_bounds'] if r['repeat'] == 1
                and r['selection_role'] == 'Oracle-Hybrid')['selected'] == ['T200-B']
    assert decision['comparison_reference'] == 'fixed_mean_winner'
    checks = ['Fixed mean winners, real repeat values, both Oracle envelopes isolated; '
              'different verdict from former per-repeat-max reference']

    high = copy.deepcopy(history)
    set_values(high, 'T160-B', [1001, 1002, 1003])
    assert analysis.grid_analysis(new, high)[-1]['verdict'] == 'EDGE_TIMELY_EXTENSION_CANDIDATE'
    overlap = copy.deepcopy(history)
    varied = copy.deepcopy(new)
    set_values(varied, 'L184', [900, 1000, 1100])
    set_values(overlap, 'T160-B', [901, 1001, 1101])
    _, _, co, d = analysis.grid_analysis(varied, overlap)
    assert co[0]['Hybrid_higher_repeats'] == 3 and co[0]['observed_ranges_overlap']
    assert d['verdict'] == 'EDGE_ROLE_INCONCLUSIVE'
    set_values(overlap, 'T160-B', [1100, 1000, 900])
    assert analysis.grid_analysis(varied, overlap)[-1]['verdict'] == 'EDGE_ROLE_INCONCLUSIVE'
    set_values(overlap, 'T160-B', [1100, 1101, 1102])
    assert analysis.grid_analysis(varied, overlap)[-1]['verdict'] == 'EDGE_ROLE_INCONCLUSIVE'
    checks.append('Hybrid strict gain, mixed signs, equal endpoints, and 3/3 gains '
                  'with overlapping observed ranges follow requested verdicts')

    tied_new, tied_history = copy.deepcopy(new), copy.deepcopy(history)
    set_values(tied_new, 'L176', [900, 900, 900])
    set_values(tied_history, 'T200-B', [800, 800, 800])
    for r in tied_new:
        if r['cell'] == 'L176':
            r['VIN_J_per_timely_frame'] = .4
    _, sel, co, d = analysis.grid_analysis(tied_new, tied_history)
    assert set(d['fixed_Best_Local']) == {'L176', 'L184'}
    assert set(d['fixed_Best_Hybrid']) == {'T160-B', 'T200-B'}
    assert len(co) == 4 and len(sel) == 8
    assert d['verdict'] == 'EDGE_NOT_REQUIRED_FOR_D100_TIMELY_CEILING'
    set_values(tied_history, 'T200-B', [1000, 700, 700])  # Same mean; mixed paired gains.
    assert analysis.grid_analysis(tied_new, tied_history)[-1]['verdict'] == 'EDGE_ROLE_INCONCLUSIVE'
    checks.append('All mean ties preserved despite diagnostic energy ordering; '
                  'every tied Local/Hybrid pair must agree')

    for fault in ('missing', 'duplicate', 'invalid', 'bad_count'):
        bad = copy.deepcopy(new)
        if fault == 'missing': bad.pop()
        if fault == 'duplicate': bad.append(copy.deepcopy(bad[0]))
        if fault == 'invalid': bad[0]['integrity_status'] = 'INVALID'
        if fault == 'bad_count': bad[0]['worst_stream_timely_FPS'] += 1
        assert analysis.grid_analysis(bad, history)[-1]['verdict'] == 'EDGE_ROLE_INCONCLUSIVE'
    unknown_energy = copy.deepcopy(new)
    for r in unknown_energy: r['VIN_J_per_timely_frame'] = None
    _, sel, _, d = analysis.grid_analysis(unknown_energy, history)
    assert all(r['VIN_J_per_timely_frame'] is None for r in sel)
    assert d['verdict'] == 'EDGE_NOT_REQUIRED_FOR_D100_TIMELY_CEILING'
    checks.append('Missing/duplicate/invalid/count mismatch fails closed; missing energy remains N/A')

    # Output plumbing test uses explicit synthetic summaries, not simulated raw measurements.
    scratch = Path(tempfile.mkdtemp(prefix='refinement_fixed_CPU_'))
    runs = scratch / 'runs'
    runs.mkdir()
    plan = dict(order=frozen.expected_order(), comparison_reference='repeat_best_envelope',
                historical_sha256={})
    pf = scratch / 'plan.json'
    pf.write_text(json.dumps(plan))
    for row in new:
        run = runs / row['run_id']
        run.mkdir()
        for name in ('manifest.json', 'summary.json'):
            (run / name).write_text(json.dumps(row))
    hashes = {str(p): frozen.sha(p) for p in scratch.rglob('*') if p.is_file()}
    # frozen.analyze.__globals__ is privately copied by the production entry point.
    with patch.multiple(frozen, OUT=runs, PLAN=pf, load_plan=lambda: plan,
                        load_history=lambda _: history, verify_lifecycle=lambda *_: None,
                        read_csv=lambda _: [], summarize=lambda m, *_: dict(m)):
        with redirect_stdout(io.StringIO()):
            analysis.analyze(scratch / 'analysis')
            frozen.analyze(scratch / 'frozen_analysis')
        for name in ('per_run_metrics.csv', 'per_stream_metrics.csv',
                     'condition_metrics.csv', 'condition_stream_metrics.csv', 'replay.json'):
            assert (scratch / 'analysis' / name).read_bytes() == (scratch / 'frozen_analysis' / name).read_bytes()
        decision = json.loads((scratch / 'analysis/refinement_verdict.json').read_text())
        assert decision['verdict'] == 'EDGE_NOT_REQUIRED_FOR_D100_TIMELY_CEILING'
        try:
            analysis.analyze(scratch / 'analysis')
        except RuntimeError:
            pass
        else:
            raise AssertionError('Existing output accepted')
    assert all(frozen.sha(Path(p)) == h for p, h in hashes.items())
    for name, count in [('best_local_selections.csv', 4), ('best_hybrid_selections.csv', 4),
                        ('oracle_upper_bounds.csv', 6)]:
        with (scratch / 'analysis' / name).open() as f:
            assert len(list(csv.DictReader(f))) == count
    checks.append('Exclusive output end-to-end, fixed selections/Oracle CSVs, policy provenance '
                  'and input preservation; per-run/per-stream/condition/replay outputs identical '
                  'to frozen analyzer on synthetic fixtures')
    return dict(status='PASS', provenance='SYNTHETIC_CPU_TEST_NOT_MEASUREMENT', checks=checks,
                GPU_executed=False, network_executed=False, frequency_accessed=False,
                scratch_path=str(scratch))


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    if args.output.exists():
        raise RuntimeError('No validation overwrite')
    result = verify()
    with args.output.open('x') as f:
        json.dump(result, f, indent=2)
    print(json.dumps(result, indent=2))
