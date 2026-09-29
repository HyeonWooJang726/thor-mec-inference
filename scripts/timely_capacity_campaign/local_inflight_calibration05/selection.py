"""Calibration05-only, preregistered final Local concurrency selection."""
import math
from statistics import mean

C_VALUES = (3, 4, 5, 6)
VALID_SUPPLY = ('SATURATED_VALID', 'SOURCE_LIMITED', 'AMBIGUOUS')
PLATEAU_FRACTION = 0.98
EXTENSION_FRACTION = 1.02


def saturation_status(valid, raw_classification, admitted_fps, completed_fps):
    if not valid:
        return 'INVALID'
    if raw_classification == 'UNSUSTAINABLE' and admitted_fps == 240:
        return 'SATURATED_VALID'
    if raw_classification == 'STABLE' and admitted_fps == 240 and completed_fps >= 239.5:
        return 'SOURCE_LIMITED'
    return 'AMBIGUOUS'


def _plateau_choice(rate):
    """Apply the same frozen closure rule to a mean or a single repeat."""
    if rate[6] > EXTENSION_FRACTION * rate[5]:
        return 'FINAL_CLOSURE_NOT_REACHED', None
    maximum = max(rate.values())
    return ('FINAL_SATURATED_PLATEAU_C_SELECTED',
            min(c for c in C_VALUES if rate[c] >= PLATEAU_FRACTION * maximum))


def decide(rows):
    """Use only the eight Calibration05 per-run rows; no historical pooling."""
    by = {}
    for row in rows:
        key = int(row['C_L']), int(row['repeat'])
        if key in by:
            raise ValueError('Duplicate C/repeat')
        by[key] = row
    expected = {(c, rep) for c in C_VALUES for rep in (1, 2)}
    if set(by) != expected:
        raise ValueError('Incomplete/outside frozen 4x2 Calibration05 grid')
    if any(row.get('run_id') != f'LINFLIGHT05_C{c}_R{rep}'
           for (c,rep),row in by.items()):
        raise ValueError('Historical or wrong-namespace run supplied for final selection')

    classes = {}
    for c in C_VALUES:
        pair = [by[c, rep].get('saturation_status') for rep in (1, 2)]
        if any(by[c, rep].get('raw_scan_integrity_status') != 'VALID' or
               pair[rep-1] not in VALID_SUPPLY for rep in (1, 2)):
            classes[str(c)] = 'INVALID'
        else:
            classes[str(c)] = pair[0] if pair[0] == pair[1] else 'C_LEVEL_REPEAT_AMBIGUOUS'
    invalid = [row['run_id'] for row in by.values()
               if row.get('raw_scan_integrity_status') != 'VALID' or
               row.get('saturation_status') not in VALID_SUPPLY or
               not isinstance(row.get('active_completed_FPS'), (int, float)) or
               not math.isfinite(row['active_completed_FPS']) or
               row['active_completed_FPS'] < 0]
    full_load = [c for c in C_VALUES if classes[str(c)] == 'SOURCE_LIMITED']
    common = dict(per_C_supply_class=classes, C_selected=None,
        source_ceiling_reached=bool(full_load), plateau_supported=False,
        C7_extension_required=False, repeat_ambiguity=False,
        repeat_ambiguity_kind=None, invalid_run_ids=invalid,
        calibration05_is_selection_dataset=True,
        previous_calibrations_used_for_selection=False,
        OC3_diagnostic_only=True, no_C7_or_third_repeat_automatic=True)
    if invalid:
        return dict(common, r_3=None, r_4=None, r_5=None, r_6=None,
            r6_over_r5=None, primary_verdict='NO_C_SELECTION_INVALID_DATA',
            selection_reason='At least one Calibration05 measured run is INVALID; no performance selection.')

    rate = {c: mean(float(by[c, rep]['active_completed_FPS']) for rep in (1, 2))
            for c in C_VALUES}
    common.update(r_3=rate[3],r_4=rate[4],r_5=rate[5],r_6=rate[6],
                  r6_over_r5=rate[6]/rate[5] if rate[5] else None)
    if 'C_LEVEL_REPEAT_AMBIGUOUS' in classes.values():
        return dict(common, repeat_ambiguity=True,
            repeat_ambiguity_kind='MIXED_SUPPLY_CLASSES',
            primary_verdict='C_LEVEL_REPEAT_AMBIGUOUS',
            selection_reason='The two repeats of at least one C have different supply classes.')
    if full_load:
        chosen = min(full_load)
        return dict(common, C_selected=chosen,
            primary_verdict='FULL_LOAD_SUSTAINABLE_C_SELECTED',
            selection_reason=f'C={chosen} is the smallest tested C with 2/2 SOURCE_LIMITED evidence for the 240-FPS target workload; true saturated capacity is not estimated.')
    if not all(classes[str(c)] == 'SATURATED_VALID' for c in C_VALUES):
        return dict(common, repeat_ambiguity=True,
            repeat_ambiguity_kind='TWO_OF_TWO_AMBIGUOUS_SUPPLY',
            primary_verdict='REPEAT_AMBIGUOUS',
            selection_reason='No C is 2/2 SOURCE_LIMITED and at least one C is 2/2 AMBIGUOUS; two-repeat evidence cannot resolve final selection.')

    mean_verdict, mean_selected = _plateau_choice(rate)
    repeat_choices = [_plateau_choice({c: float(by[c, rep]['active_completed_FPS'])
                                       for c in C_VALUES}) for rep in (1, 2)]
    common['plateau_supported'] = mean_verdict == 'FINAL_SATURATED_PLATEAU_C_SELECTED'
    if any(choice != (mean_verdict, mean_selected) for choice in repeat_choices):
        return dict(common, repeat_ambiguity=True,
            repeat_ambiguity_kind='CLOSURE_BRANCH_OR_SELECTED_C_CONFLICT',
            primary_verdict='REPEAT_AMBIGUOUS',
            selection_reason='Repeat-level closure branch or selected C conflicts with the two-repeat mean decision.')
    if mean_verdict == 'FINAL_CLOSURE_NOT_REACHED':
        return dict(common, C7_extension_required=True,
            primary_verdict=mean_verdict,
            selection_reason='All C are 2/2 SATURATED_VALID and r6 > 1.02*r5; propose C7 only.')
    return dict(common, C_selected=mean_selected,
        primary_verdict='FINAL_SATURATED_PLATEAU_C_SELECTED',
        selection_reason='All C are 2/2 SATURATED_VALID, r6 <= 1.02*r5, and the selected C is the smallest within 2% of the Calibration05 same-session maximum.')
