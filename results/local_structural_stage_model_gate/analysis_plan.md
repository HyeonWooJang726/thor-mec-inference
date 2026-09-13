# Structural stage model feasibility gate — frozen analysis plan

CPU-only; new outputs only in this directory. No GPU, controller, policy replay, counterfactual C, production edits, old result edits or Git writes.

## Population and folds
Canonical valid5 membership and statistical_slot define 280 runs, 56 conditions, five held-out slots. Replacement slot4 is a statistical slot, not original Round4. Independently audit raw_ns.json, per_frame.csv and before-state event accounting. Stop on semantics/membership/hash inconsistency. Primary training and evaluation both use all ready-on-time frames; transition and service distributions include queue-stage-miss frames, avoiding selection on service-start punctuality. PRE_READY_LATE is reported but excluded. No startup/outlier exclusion.

## Models fixed before fitting
B0: multinomial logistic [K,C,b]. B1: multinomial logistic [K,C,Q,A,b]. K and C use reference-coded categories K1/C1. Numeric variables are standardized with training-only mean/population SD. Reference class ON_TIME; train mean multinomial NLL plus 0.001/2 times squared nonintercept coefficients. SciPy L-BFGS-B, zero initialization, maxiter1000, gtol1e-7, ftol1e-12, maxls40. No tuning or additional model families.

P transition: full empirical joint pairs W,A_start from training only, KCQA -> KCQ -> KCA -> KC -> C. Service: training empirical S CDF, KC A_start -> C A_start -> KC -> C. Both require >=200 samples and >=3 distinct training runs. Q,A are exact integers, no outcome-selected bins. Record support and backoff for every prediction via group IDs and lookup tables. All empirical observations retain equal weight; no subsampling. Use exact integer-ns sum-CDF counting, not Monte Carlo or a fitted residual model. Service conditional independence from W is the tested structural assumption.

## Metrics and audit
Three classes ordered Queue, Service, On-time. Brier=sum of three squared probability errors (no division by 3); logloss uses probability clipped at 1e-15 only for scoring, with exact-zero true-class counts also reported. Fold metrics pool eligible frames within a held-out fold; primary cross-fold summary is unweighted five-fold mean and sample SD. Additionally preserve run metrics and condition/run summaries. Calibration curves use fixed ten equal probability bins; calibration errors include absolute predicted-minus-observed stage rate. Fold is the paired holdout unit, run is the experimental unit, no frame-level significance claim.

Structural assumption audit: within each train-supported K,C,A_start group, derive W quartiles from training only; compare held-out S means in train-defined lowest/highest W quartiles, alongside training-only service CDF PIT and held-out W/S rank association. Preserve run identities and n; no refitting or feature expansion in response. These diagnostics are descriptive and can reflect omitted time/history state.

## Verdict fixed rules
SUPPORTED requires P vs B1 mean improvement in both Brier/logloss, >=4/5 improving folds for each, and broadly lower K5/6/7 stage-rate errors. WEAKLY_SUPPORTED for partial improvement/inconsistency. NOT_SUPPORTED for no mean improvement, <=2/5 improving folds or unimproved important calibration. Do not tune/extend after a negative result.

## Numerical verification and preservation
Check exact empirical integration against brute-force small deterministic arrays and direct full-distribution sums for selected held-out queries. Verify probabilities sum to one, finite and in range, no train/test run intersection. Hash all pre-existing results, scripts/configs and preservation metadata before/after. Three figure types maximum, PNG/PDF only. Record zero-support fallbacks/errors rather than invent observations.
