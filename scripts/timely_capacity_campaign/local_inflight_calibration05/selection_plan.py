"""Frozen human-readable Calibration05-only final-C hierarchy for plan.json."""


def selection_rule():
    return dict(kind='CALIBRATION05_FINAL_LOCAL_C_SELECTION',
        selection_dataset='Calibration05 8 measured runs only; no Calibration03/04 pooling',
        invalid='any INVALID -> NO_C_SELECTION_INVALID_DATA',
        mixed_supply='any C with discordant repeat supply classes -> C_LEVEL_REPEAT_AMBIGUOUS',
        full_load='smallest C with 2/2 SOURCE_LIMITED -> FULL_LOAD_SUSTAINABLE_C_SELECTED',
        plateau_requires_all_2of2_saturated=True,
        closure_exception='r6 > 1.02*r5 -> FINAL_CLOSURE_NOT_REACHED; propose C7 only',
        plateau='r6 <= 1.02*r5; smallest C with rC >= 0.98*max(r3,r4,r5,r6) -> FINAL_SATURATED_PLATEAU_C_SELECTED',
        repeat_ambiguity='repeat-level closure branch or selected C differs from mean-based result',
        unresolved_supply='2/2 AMBIGUOUS with no full-load C -> REPEAT_AMBIGUOUS; no selection; distinguish with repeat_ambiguity_kind',
        queue_service_GPU_span='SUPPORTING_CHARACTERIZATION_ONLY',
        OC3='DIAGNOSTIC_ONLY',no_automatic_C7_or_third_repeat=True)
