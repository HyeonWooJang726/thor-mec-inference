"""Pre-registered C_L=2 justification under the unchanged 240-FPS source."""
from statistics import mean

C_VALUES = (1, 2, 3, 4)
EPSILON = 0.02
VALID_SUPPLY = ('SATURATED_VALID', 'SOURCE_LIMITED', 'AMBIGUOUS')


def saturation_status(valid, raw_classification, admitted_fps, completed_fps):
    if not valid:
        return 'INVALID'
    if raw_classification == 'UNSUSTAINABLE' and admitted_fps == 240:
        return 'SATURATED_VALID'
    if raw_classification == 'STABLE' and admitted_fps == 240 and completed_fps >= 239.5:
        return 'SOURCE_LIMITED'
    return 'AMBIGUOUS'


def supply_by_c(by):
    result = {}
    for c in C_VALUES:
        labels = [by[c, rep]['saturation_status'] for rep in (1, 2)]
        result[c] = labels[0] if labels[0] == labels[1] else 'AMBIGUOUS'
    return result


def c2_verdict(r, supply):
    """Apply A before B before C before D; C3/C4 are never selected here."""
    threshold = r[2] / (1-EPSILON)
    if r[1] >= (1-EPSILON)*r[2]:
        return 'C_L2_NOT_MINIMAL'
    if any(r[c] > threshold for c in (3, 4)):
        return 'C_L2_REJECTED_HIGHER_C_REQUIRED'
    if any(supply[c] != 'SATURATED_VALID' for c in C_VALUES):
        return 'C_L2_INCONCLUSIVE_SOURCE_CEILING'
    return 'C_L2_DEPLOYMENT_JUSTIFIED'


def decide(rows):
    by = {}
    for row in rows:
        key = int(row['C_L']), int(row['repeat'])
        if key in by:
            raise ValueError('Duplicate calibration C/repeat')
        by[key] = row
    if set(by) != {(c, rep) for c in C_VALUES for rep in (1, 2)}:
        raise ValueError('Incomplete/outside frozen 4x2 calibration grid')
    if any(row.get('raw_scan_integrity_status') != 'VALID' or
           row.get('saturation_status') not in VALID_SUPPLY for row in by.values()):
        return {'status':'CALIBRATION_INVALID_OR_INCOMPLETE',
                'primary_verdict':None,'r_C':None,'C_selected':None,
                'invalid_or_missing_runs':[row['run_id'] for row in by.values()
                    if row.get('raw_scan_integrity_status') != 'VALID']}
    r = {c:mean(float(by[c,rep]['active_completed_FPS']) for rep in (1,2))
         for c in C_VALUES}
    supply = supply_by_c(by)
    threshold = r[2]/(1-EPSILON)
    mean_verdict = c2_verdict(r,supply)
    each = {}
    for rep in (1,2):
        rates = {c:float(by[c,rep]['active_completed_FPS']) for c in C_VALUES}
        statuses = {c:by[c,rep]['saturation_status'] for c in C_VALUES}
        each[rep] = c2_verdict(rates,statuses)
    ambiguous = each[1] != each[2] or any(v != mean_verdict for v in each.values())
    verdict = 'CALIBRATION_REPEAT_AMBIGUOUS' if ambiguous else mean_verdict
    proposed = set()
    if ambiguous:
        proposed.add(2)  # Every comparison uses the C2 reference threshold.
        if (by[1,1]['active_completed_FPS'] >= (1-EPSILON)*by[2,1]['active_completed_FPS']) != (
            by[1,2]['active_completed_FPS'] >= (1-EPSILON)*by[2,2]['active_completed_FPS']) or \
                by[1,1]['saturation_status'] != by[1,2]['saturation_status']:
            proposed.add(1)
        for c in (3,4):
            if (by[c,1]['active_completed_FPS'] > by[2,1]['active_completed_FPS']/(1-EPSILON)) != (
                by[c,2]['active_completed_FPS'] > by[2,2]['active_completed_FPS']/(1-EPSILON)) or \
                    by[c,1]['saturation_status'] != by[c,2]['saturation_status']:
                proposed.add(c)
    all_saturated = all(supply[c]=='SATURATED_VALID' for c in C_VALUES)
    maximum = max(r.values()) if all_saturated else None
    eligible = ([c for c in C_VALUES if r[c]>=(1-EPSILON)*maximum]
                if all_saturated else None)
    plateau_smallest = min(eligible) if eligible else None
    if verdict=='C_L2_DEPLOYMENT_JUSTIFIED' and plateau_smallest!=2:
        raise AssertionError('C2 justification disagrees with complete saturated plateau')
    return {
        'status':verdict,'primary_verdict':verdict,'r_C':r,
        'r_1':r[1],'r_2':r[2],'r_3':r[3],'r_4':r[4],
        'T_2':threshold,'epsilon':EPSILON,
        'C1_not_minimal_observed':r[1]>=(1-EPSILON)*r[2],
        'higher_C_observed_above_T2':{c:r[c]>threshold for c in (3,4)},
        'per_C_supply_class':supply,'per_repeat_verdict':each,
        'mean_based_verdict_before_ambiguity':mean_verdict,
        'third_repeat_proposal_only':sorted(proposed),
        'all_C_2of2_saturated_valid':all_saturated,
        'auxiliary_plateau_eligible':eligible,
        'auxiliary_smallest_plateau_C':plateau_smallest,
        'C_selected':2 if verdict=='C_L2_DEPLOYMENT_JUSTIFIED' else None,
        'higher_C_final_winner_selected':False,
        'higher_supply_design_needed':verdict in (
            'C_L2_REJECTED_HIGHER_C_REQUIRED',
            'C_L2_INCONCLUSIVE_SOURCE_CEILING'),
        'Grid02_and_Confirmation02_validity_unchanged':True,
    }
