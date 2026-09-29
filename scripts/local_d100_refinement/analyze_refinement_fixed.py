#!/usr/bin/env python3
"""Offline fixed-configuration comparison; preserve the plan-hashed raw analyzer.

The frozen analyzer is imported by the runtime and cannot be edited without
invalidating the campaign source hashes. This entry point reuses its raw replay
unchanged and replaces only its final grid comparison in a private namespace.
"""
import argparse
import json
from pathlib import Path
import statistics as st
import types

import analyze_refinement as frozen


RULE = (
    'Select fixed Local and Hybrid configurations independently by maximum '
    '3-repeat mean worst-stream timely FPS, retaining every exact tie. Compare '
    'their actual repeats 1/2/3, never repeat-wise maxima. A directional verdict '
    'requires 3/3 strict gains AND disjoint observed ranges. Equality, range '
    'overlap, mixed directions or integrity issues => EDGE_ROLE_INCONCLUSIVE. '
    'All tied configuration pairs must agree. This is not a significance test.'
)


def grid_analysis(new, historical, reference=None):
    # The frozen plan's old comparison_reference is superseded ONLY offline.
    candidates, selections, comparisons, decision = frozen.grid_analysis(
        new, historical, reference='fixed_mean_winner')
    all_rows = new + historical
    fixed_local = decision['local_winners']['ALL']
    fixed_hybrid = decision['historical_fixed_Hybrid_winners']
    selected_metrics = []
    for mode, cells in [('Best-Local', fixed_local), ('Best-Hybrid', fixed_hybrid)]:
        for cell in cells:
            rows = sorted((r for r in all_rows if r.get('cell') == cell),
                          key=lambda r: r['repeat'])
            for rep in (1, 2, 3, 'ALL'):
                subset = rows if rep == 'ALL' else [r for r in rows if r['repeat'] == rep]
                out = dict(selection_role=mode, cell=cell, repeat=rep,
                           scope='AGGREGATE' if rep == 'ALL' else 'REPEAT',
                           tied_configurations=cells,
                           selection_basis='3-repeat mean worst-stream timely FPS')
                for metric in frozen.METRICS:
                    values = [frozen.flatten(r).get(metric) for r in subset]
                    complete = len(subset) == (3 if rep == 'ALL' else 1) and all(
                        frozen.best_grid.finite(v) for v in values)
                    out[metric] = st.mean(values) if complete else None
                    out[metric + '_sample_SD'] = st.stdev(values) if complete and rep == 'ALL' else None
                selected_metrics.append(out)

    oracle = []
    for row in selections:
        if row['scope'] == 'REPEAT':
            oracle.append(dict(selection_role='Oracle-Local', repeat=row['repeat'],
                               selected=row['primary_tied_configurations'],
                               worst_stream_timely_FPS=row['worst_stream_timely_FPS']))
    # Collapse tied Local winners to one envelope row, retaining all IDs.
    oracle = list({r['repeat']: r for r in oracle}.values())
    oracle += [dict(selection_role='Oracle-Hybrid', **r)
               for r in decision['historical_repeat_best_Hybrid']]
    for row in oracle:
        row.update(primary_gate_used=False,
                   interpretation='Observed-grid repeat-wise upper envelope only; '
                                  'not a fixed configuration or theoretical bound')

    for row in candidates:
        row['selection_role'] = 'Fixed-Local-candidate' if row['scope'] == 'AGGREGATE' else 'Oracle-Local-candidate'
        row['primary_gate_used'] = row['scope'] == 'AGGREGATE' and row['selected']
    for row in comparisons:
        lv, hv = row['Local_values'], row['Hybrid_values']
        deltas = [h - l for l, h in zip(lv, hv)]
        overlap = max(min(lv), min(hv)) <= min(max(lv), max(hv))
        row.update(selection_role='FIXED_CONFIGURATION_PRIMARY',
                   delta_Hybrid_minus_Local_by_repeat=deltas,
                   Hybrid_higher_repeats=sum(d > 0 for d in deltas),
                   Local_higher_repeats=sum(d < 0 for d in deltas),
                   observed_ranges_overlap=overlap,
                   repeat_matching='Same repeat indices; historical cohorts are not contemporaneous pairs')
        verdict = 'EDGE_ROLE_INCONCLUSIVE'
        if not decision['issues'] and not overlap:
            if all(d > 0 for d in deltas):
                verdict = 'EDGE_TIMELY_EXTENSION_CANDIDATE'
            elif all(d < 0 for d in deltas):
                verdict = 'EDGE_NOT_REQUIRED_FOR_D100_TIMELY_CEILING'
        row['verdict'] = verdict
    labels = {r['verdict'] for r in comparisons}
    decision.update(
        verdict=next(iter(labels)) if len(labels) == 1 and not decision['issues'] else 'EDGE_ROLE_INCONCLUSIVE',
        comparison_reference='fixed_mean_winner',
        superseded_frozen_plan_comparison_reference=reference,
        rule=RULE,
        fixed_Best_Local=fixed_local,
        fixed_Best_Hybrid=fixed_hybrid,
        fixed_selected_metrics=selected_metrics,
        oracle_upper_bounds=oracle,
        oracle_used_in_primary_gate=False,
    )
    # Remove old ambiguous fields; repeat maxima remain only labeled Oracles.
    decision.pop('local_winners')
    decision.pop('historical_repeat_best_Hybrid')
    fixed_selections = [r for r in selected_metrics if r['selection_role'] == 'Best-Local']
    return candidates, fixed_selections, comparisons, decision


def analyze(output):
    captured = {}

    def compare(new, historical, reference):
        result = grid_analysis(new, historical, reference)
        captured['decision'] = result[-1]
        return result

    # No monkey patch of the module imported by the runtime.
    replay = types.FunctionType(frozen.analyze.__code__,
                               dict(frozen.analyze.__globals__, grid_analysis=compare))
    replay(output)
    decision = captured['decision']
    frozen.write_csv(output / 'best_hybrid_selections.csv', [frozen.flatten(r) for r in
                     decision['fixed_selected_metrics'] if r['selection_role'] == 'Best-Hybrid'])
    frozen.write_csv(output / 'oracle_upper_bounds.csv',
                     [frozen.flatten(r) for r in decision['oracle_upper_bounds']])
    with (output / 'fixed_comparison_policy.json').open('x') as f:
        json.dump(dict(rule=RULE, plan_sha256=frozen.sha(frozen.PLAN),
                       frozen_analyzer_sha256=frozen.sha(Path(frozen.__file__)),
                       comparison_analyzer_sha256=frozen.sha(Path(__file__)),
                       runtime_plan_order_modified=False,
                       oracle_used_in_primary_gate=False), f, indent=2)
    with (output / 'fixed_comparison_policy.md').open('x') as f:
        f.write('# Fixed-configuration primary comparison\n\n' + RULE + '\n\n')
        f.write('This offline policy supersedes only the frozen plan\'s '
                '`repeat_best_envelope` analysis reference. Runtime, source hashes, '
                'plan and run order remain unchanged.\n\n')
        f.write('`best_local_selections.csv` and `best_hybrid_selections.csv` '
                'report actual repeat values and mean/sample SD of the fixed '
                'mean-selected cells. `hybrid_reference_comparison.csv` is the '
                'primary gate. `oracle_upper_bounds.csv` contains only diagnostic '
                'repeat-wise observed-grid maxima; these are not achievable '
                'fixed-policy or theoretical capacity claims.\n\n')
        f.write('`worst_stream_TIR` uses 1,800 physical source frames per stream. '
                'Historical and refinement repeat indices are not contemporaneous '
                'pairs. Selection and evaluation use the same measured data.\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True,
                        help='New, non-existing analysis directory; inputs are read-only')
    analyze(parser.parse_args().output)
