"""Frozen human-readable selection hierarchy embedded in plan.json."""


def selection_rule():
    return dict(kind='C3_C5_FINAL_DEPLOYMENT_SELECTION',
        invalid='any INVALID -> NO_C_SELECTION_INVALID_DATA',
        mixed_supply='any C with discordant repeat supply classes -> C_LEVEL_REPEAT_AMBIGUOUS',
        full_load='smallest C with 2/2 SOURCE_LIMITED -> FULL_LOAD_SUSTAINABLE_C_SELECTED',
        plateau_requires_all_2of2_saturated=True,
        plateau='r5 <= 1.02*r4; smallest C with rC >= 0.98*max(r3,r4,r5) -> SATURATED_PLATEAU_C_SELECTED',
        not_reached='r5 > 1.02*r4 -> PLATEAU_NOT_REACHED_AT_C5_SCAN; propose C6 only',
        repeat_ambiguity='repeat-level plateau branch or selected C differs from mean-based result',
        unresolved_supply='2/2 AMBIGUOUS with no full-load C -> REPEAT_AMBIGUOUS; no selection; distinguish with repeat_ambiguity_kind',
        OC3='DIAGNOSTIC_ONLY',no_automatic_C6_or_third_repeat=True)
