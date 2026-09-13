# Original-only temporal / round analysis

Original `campaign_drift_summary.csv` remains the initial 279-valid-row reference (56 cells in R1/2/3/5, 55 in R4). Replacement is never inserted. `round_drift_analysis.csv` additionally uses the **same 55 complete cells** in all five rounds, excluding K2/C1 across all rounds only in this clearly labeled secondary panel. Center each cell on its original five-round mean, then average its round deviation.

| Round | Service cell-centered ms | DMR cell-centered pp |
|---|---|---|
| 1 | +0.01518 | +0.70652 |
| 2 | -0.06348 | +0.77917 |
| 3 | +0.02370 | +0.16531 |
| 4 | +0.01563 | -0.58042 |
| 5 | +0.00896 | -1.07057 |

Service shows no sustained monotone drift: centered round means span -0.06348 to +0.02370 ms. The original-row cell-centered service slope is +0.00335 ms per 100 global indices (correlation 0.0084). These are descriptive, not independent-sample trend tests.

DMR has visible round bias: common-panel R5−R1 = -1.77709 pp. However the median within-cell R5−R1 is only -0.02778 pp. K7/C2 contributes -40.746 pp and K6/C1 -26.028 pp to the unaveraged sum (-97.740 pp): together about 68.3% of the panel change. Thus a few sensitive conditions strongly affect the global average; this is not uniform system-wide improvement. The DMR order slope is -0.8945 pp per 100 indices, correlation -0.1824.

K6/C1 original-round DMR values are 63.954, 100.000, 77.991, 36.139, 37.926%; K7/C2 values are 100.000, 79.460, 84.016, 91.167, 59.254%. All remain included. No outlier deletion or drift correction is applied.

Balanced rounds avoid placing each C in its own campaign epoch and permit same-round contrasts. They reduce one source of temporal confounding, but five rounds cannot establish that all temporal confounding is absent. Temperature/resource causes were not identified here. Verdict on a meaningful **system-wide temporal drift mechanism: UNCLEAR**; observed DMR round variability/bias: YES; sustained service drift: not observed. The opposite K6/K7 C2-versus-C4 DMR directions survive all five within-round comparisons.

## Original 279-valid-run drift reference

Read directly from unchanged ../campaign_drift_summary.csv. Its original cell centering uses four valid observations for K2/C1 and five elsewhere; this is distinct from the complete 55-cell panel above.

| Round | Valid cells | Original service centered ms | Original DMR centered pp |
|---|---|---|---|
| 1 | 56 | +0.014735 | +0.692662 |
| 2 | 56 | -0.062259 | +0.765009 |
| 3 | 56 | +0.023209 | +0.162602 |
| 4 | 55 | +0.015634 | -0.580423 |
| 5 | 56 | +0.008960 | -1.050214 |
