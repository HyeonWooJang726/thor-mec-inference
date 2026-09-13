# Figure captions

1. **Held-out structural calibration.** Ten fixed equal-width probability bins; each point is the unweighted mean predicted and observed fraction over held-out folds with support in that bin. The diagonal is perfect calibration. B0 is coarse direct, B1 adds ready Q/A, and P is the empirical structural chain. No confidence interval or significance claim is attached; sparse bins remain visible in calibration_curves.csv.

2. **Stage rates by workload and concurrency.** Ready-on-time conditional stage rates, means of five run-level observed/predicted fractions for each K,C. Lines connect measured-grid conditions, not time or dynamic transitions. No error bars are shown here; run-level SD and all observations are in structural_by_K_C.csv and structural_per_run_metrics.csv. These are not all-frame DMR or counterfactual C outcomes.

3. **Structural versus direct probability error.** Points show each held-out fold; larger markers show mean and error bars show sample SD across five held-out folds (not confidence intervals). Folds share training runs and are not independent workloads. Brier is the sum over three classes; logloss clips only scoring probabilities at1e-15 and retains exact-zero counts in CSV. Lower is better.

한국어: 그림1은 stage별 확률 calibration, 그림2는 K5–7/C1–8의 실제 stage 비율과 예측 비율, 그림3은 같은 held-out frame에서 direct/structural 모델의 확률 오차를 비교한다. 이번 결과는 ready 시점의 관측 경로 설명력이며 controller 개선이나 다른 C의 성능을 뜻하지 않는다.
