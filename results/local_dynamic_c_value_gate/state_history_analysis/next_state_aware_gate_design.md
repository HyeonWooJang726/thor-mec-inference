# Candidate next gate — design only, not executed

Recommendation: conditionally investigate a small state-aware C2/C4 candidate. Evidence is weak for new adaptive gain over C4, so do not assume Dynamic-C is the core contribution or pre-authorize a GPU campaign.

## Concept

Retain the same non-preemptive P=4 resource architecture and two possible caps. Current K is one input, not the complete state. Observe ready Q, published admission counter/actual completion availability, current/previous C, generated unfinished backlog, due-but-not-generated demand, and deadline-pressure counts/quantiles. Explicitly distinguish near-zero slack of the immediately preceding 30-FPS tick from large negative slack spanning several ticks. Consider startup/readiness context only if online observable; do not expose future trace identity, phase length or future K.

A candidate could defer a reduction while queued/urgent demand remains and use C2 when demand is modest even if K=7. These are hypotheses, not a fitted rule: this analysis does **not** show that retaining C4 at the observed lookup decreases improves DMR. C2's large initial K7 backlog and its better later K7 behavior motivate evaluating state dependence without copying the old K lookup map. Use hysteresis/minimum action spacing only if preregistered separately, with implementation overhead and publication delay included.

No numeric controller threshold is chosen here. The 5/10-ms urgent counts are descriptive reporting features requested for this analysis, not selected action thresholds. Residual prediction, EDF/drop, batching, edge placement and complex optimization are excluded.

## Selection versus evaluation

These 30 primary runs have already informed the hypothesis and are exploratory/selection evidence. Do not choose thresholds here and report performance on the same data. Offline replay cannot synthesize completion/service responses to a different C trajectory. Reserve independent acquisitions and withheld trace/order/content conditions for evaluation after an explicit new experiment scope is approved. If a selection/training measurement is necessary, keep it separate from the evaluation acquisition budget and freeze the final policy before evaluation results are seen.

Keep FIXED_C4, FIXED_C2 and current-K lookup as honest comparators. Primary remains all-request DMR including startup/late completions, with run-level variability and paired block comparisons. Report absolute DMR, regressions and transition-associated effects, not just improvement against the weakest baseline. Preregister future engineering criteria and budgets; do not optimize them to these results. The previous 0.5-pp/4-of-5 criterion is historical and should not be silently changed or retrospectively repurposed.

## Go/no-go evidence needed before treating this as a contribution

1. Verify an online observer can obtain the chosen state at the stated timestamps, with measured publication/decision overhead.
2. On independently held-out acquisitions, show repeat-consistent improvement over the stronger C4 baseline across trace order, not only rescue of the initial C2 backlog.
3. Demonstrate that improvements survive startup/content variation and are not a single-round front-end incident.
4. Preserve all failures and all requests; no threshold retuning on evaluation data or counterfactual service synthesis.

If these are not supported, deprioritize Local Dynamic-C as the core performance contribution. This recommendation does not reject every adaptive policy; it limits claims to the available evidence.

GPU acquisitions executed for this Phase B or next-gate design: **0**. New controller implemented: **NO**. Phase B commit/push: **NO**.
