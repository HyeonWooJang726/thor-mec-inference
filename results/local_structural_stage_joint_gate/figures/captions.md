# Captions

1. **Held-out model error.** Five-fold means with sample SD error bars and individual fold points, on identical ready-on-time frames. Brier sums squared errors across three classes; logloss uses the previous1e-15 scoring clip, not smoothed predictions. Folds share training data; error bars are not confidence intervals or frame-level uncertainty.

2. **K5 Service-stage calibration across C.** Left: observed and predicted fractions, equal-weighted means of five run rates per condition. Right: absolute difference between the two mean rates, in percentage points. All eight C cells retained; these are separate static acquisitions. No error bars are plotted here; run SD and mean run absolute error are retained separately in CSV. Calibration is conditional on ready-on-time, not all-frame DMR.

3. **Prespecified calibration checks.** Predicted run-rate means with sample SD error bars and the observed mean reference. K5 aggregates40 runs across C; K6/C1 contains five runs. The K5 SD includes C-condition variation and must not be read as uncertainty of five repeats at one C. P-joint preserves P-old Queue risk algebraically because transition lookup and the W marginal do not change; overlap in the right panel is expected. The guardrail concerns absolute mean-rate error<=5pp.

한국어: 기존 factorized 분포와 같은 training frame의 joint triplet 분포를 비교한 offline 결과다. 전체 예측 오차, K5 service calibration 및 기존 K6/C1 Queue 성공 보존을 보여준다. GPU 실험, 다른 C의 counterfactual 성능 또는 controller 이득을 의미하지 않는다.
