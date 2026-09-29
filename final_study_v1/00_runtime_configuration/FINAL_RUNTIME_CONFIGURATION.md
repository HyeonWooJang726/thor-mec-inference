# Forward primary runtime closeout

**Final forward runtime for Grid03 and later primary evaluation:** C_L=3, C_E=2, B=1. Concurrency is no longer a primary research decision variable. A later change requires a separately preregistered validation experiment.

| Component | Value | Scientific status | Evidence |
| --- | ---: | --- | --- |
| Local in-flight limit | C_L=3 | `FORMAL_SELECTION` | [Calibration05 final selection](../../results/timely_capacity_campaign/v2_2/local_inflight_calibration05/analysis01/final_C_selection.json), [per-C summary](../../results/timely_capacity_campaign/v2_2/local_inflight_calibration05/analysis01/per_C_summary.csv) |
| Historical Edge formal verdict | `EDGE_C_REPEAT_AMBIGUOUS`; C_E selected = null | Preserved preregistered TIR-rule result | [Robustness02 verdict](../../results/timely_capacity_campaign/v2_2/edge_inflight_robustness02/analysis01/edge_C_robustness.json) |
| Forward Edge in-flight limit | C_E=2 | `PROSPECTIVE_CONSERVATIVE_RUNTIME_CONFIGURATION` | [Robustness02 per-run queue evidence](../../results/timely_capacity_campaign/v2_2/edge_inflight_robustness02/analysis01/per_run.csv) |
| TensorRT batch | B=1 | `FIXED_EXPERIMENTAL_CONFIGURATION` | Frozen plans indexed in the [manifest](../98_provenance/FINAL_STUDY_MANIFEST.json) |

## Local formal selection

Calibration05 alone is the selection dataset; Calibration03/04 are historical characterization and compatibility evidence, not pooled repeats. The Calibration05 two-repeat mean completion rates (FPS) are C3 232.800, C4 234.858, C5 235.475, C6 234.767. No tested C sustained the full 240-FPS source. Its preregistered fallback selects the smallest C within 2% of the observed maximum. The threshold is 0.98 × 235.475 = 230.7655 FPS (230.766 rounded), and C3 reaches 232.800 FPS. Calibration05 therefore formally selected C_L=3. Further concurrency gave little aggregate gain and increased per-frame service cost in the measured characterization; no universal optimum is claimed. The later K-sweep measured final-configuration stream scaling and did not retrospectively choose C_L.

## Edge chronology and prospective decision

1. The original Edge rule was preregistered using the two repeat-matched absolute changes in *overall TIR* for the temporally concentrated condition, with a +0.10 threshold.
2. Robustness02 executed. Its changes were +0.1381944444444445 and +0.025000000000000022. The formal result was `EDGE_C_REPEAT_AMBIGUOUS`, with historical `C_E_selected=null`.
3. Only after that result, runtime evidence was inspected. For the temporally concentrated stress condition, server queue-wait p95 fell from 18.501/10.767 ms at C_E=1 to 0.823/1.239 ms at C_E=2 in repeats 1/2. This largely removes the observed single-worker queueing confound; it does not make queue wait exactly zero.
4. **Before Grid03 measured execution**, C_E=2 was prospectively fixed as a conservative runtime configuration for temporal-placement evaluation. This is a runtime deconfounding choice, not a formal TIR-rule selection, throughput optimum, or claim about C_E≥3.
5. Grid03 and later primary measurements use the frozen Configuration B unless a later experiment separately preregisters a change.

At C_E=2, temporally dispersed minus temporally concentrated TIR remained +0.1611111111111111 and +0.24097222222222225. At C_E=1, those gaps were +0.3458333333333333 and +0.2583333333333333. Increasing C_E improved the concentrated condition in both repeats and reduced rather than amplified the placement gap. The remaining gap is **supporting robustness evidence** that the observed temporal-placement effect is not explained solely by single-worker Edge queueing; it was **not** the criterion for the forward C_E decision. C_E=2 is conservative with respect to the temporal-placement hypothesis because it makes the concentrated baseline more competitive.

## Configuration boundary

Configuration A: C_L=2, C_E=1 (and B=1 for the cited experiments). Its Grid02 and Confirmation02 matched comparisons remain valid in that runtime. It includes single-worker Edge serialization and must not be relabeled a failed configuration. Configuration B: C_L=3, C_E=2, B=1, the forward primary runtime. Do not pool A and B repeats as one condition or retroactively change their verdicts. The sensitivity in Robustness02 quantifies why this distinction matters.

Paper terms: **temporally concentrated placement** (`ALIGNED`) and **temporally dispersed placement** (`STAGGERED`). They refer to the assignment-time distribution at the same mean workload split, not changed camera synchronization or submit order alone.
