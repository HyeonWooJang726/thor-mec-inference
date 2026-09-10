# K5→K6 temporal inference queue characterization

K5→K6에서 queue wait가 증가한 현상은 **더 강해진 ready-time concentration보다, 늘어난 period별 observed service demand와 훨씬 빈번한 inference-stage carry-over의 동반 변화**로 설명하는 것이 현재 데이터에 맞다. Ready span의 5-run mean과 p95는 오히려 넓어진다. 이는 observational characterization이며 phase를 조작한 causal experiment가 아니다.

## 입력과 범위

기존 formal 35 runs / 252,000 frames만 사용했다. K5는 run별 9,000 frames × 5, K6는 10,800 frames × 5다. 모든 stream의 frame_id 0…1799 exactly once, per_frame rows, saved count validation, raw-ns ordering와 decomposition을 검증했다. 35개 raw_ns.json 모두 존재하며 **a_ns/r_ns/s_ns/c_ns integer 값을 직접 사용**했다. MS component 합으로 ready time을 복원하지 않았다. b_ns는 ordering/decomposition 검증에만 추가로 사용했다.

Measurement code, formal raw/summary, 이전 CSV/JSON/MD, 기존 smoke와 baseline은 변경하지 않았다. 입력 snapshot의 SHA256/size/mtime_ns 및 파일 집합을 마지막에 대조한다. 신규 benchmark, smoke, GPU inference, phase-stagger, server/network, graph split, counterfactual replay/simulation은 실행하지 않았다.

## 정의와 집계

- `B_m = t0 + floor(m × 10^9 / 30)`이며 period n의 boundary는 `B_(n+1)`이다. 계산은 integer ns로 한다.
- **전체 60초:** n=0…1799, boundary B1…B1800, run별 1,800개. B1800=60초의 마지막 endpoint를 포함한다.
- **첫 1초 제외:** scheduled period n=30…1799, boundary B31…B1800, run별 1,770개. 이때도 boundary 이전에 scheduled된 **모든 older frame**을 센다. 첫 1초에 scheduled되어 아직 남은 work를 버리지 않는다.
- Older frame은 `a_j < B`로 제한한다. 새 boundary와 a가 정확히 같은 새 period frame은 제외한다.
- Waiting: older ∩ `r_j ≤ B < s_j`; in-service: older ∩ `s_j ≤ B < c_j`; unfinished inference stage: 두 depth의 합이다.
- Pre-ready: older ∩ `a_j ≤ B < r_j`. Inference-stage unfinished에 포함하지 않는다.
- 한 boundary에서 waiting과 in-service가 동시에 존재할 수 있다. 따라서 **unfinished period %는 두 percentage의 합이 아니라 union의 비율**이다. Depth는 더할 수 있다.
- Maximum consecutive unfinished periods는 **연속된 boundary 관측**의 최대 길이다. Boundary 사이 모든 순간에 queue가 비어 있지 않다는 뜻이 아니다.
- Ready span은 동일 n에서 생성된 K개 frame의 `max(r)-min(r)`이다. Ratio는 `100×span_ns/(B_(n+1)-B_n)`이며 period 길이는 33,333,333 또는 33,333,334 ns다. Inter-ready gap을 clustering 지표로 사용하지 않았다.
- Service demand는 같은 n의 K개 `(c-s)` 합이다. Exact 1/30초 초과 판정은 `sum_ns×30 > 10^9`다. Period 길이와 service capacity를 동일시하지 않는다.
- 각 run statistic을 먼저 계산하고 K별 5개 값의 arithmetic mean/sample SD(n−1)/min/max를 계산한다. Pooled percentile/correlation을 대표값으로 사용하지 않는다. Percentile은 linear interpolation이다.

## 1. Ready timing: K6은 더 좁게 몰리지 않는다

| K | Run/stat | Mean ms | Median ms | p95 ms | Mean period % | p95 period % |
| --- | --- | --- | --- | --- | --- | --- |
| 5 | run01 | 3.004 | 2.604 | 6.178 | 9.011 | 18.535 |
| 5 | run02 | 4.539 | 4.735 | 6.657 | 13.616 | 19.972 |
| 5 | run03 | 2.766 | 2.632 | 3.567 | 8.299 | 10.700 |
| 5 | run04 | 2.786 | 2.613 | 3.538 | 8.357 | 10.615 |
| 5 | run05 | 2.883 | 2.688 | 4.312 | 8.648 | 12.935 |
| 5 | mean | 3.195 | 3.055 | 4.850 | 9.586 | 14.551 |
| 5 | sample_sd | 0.757 | 0.940 | 1.474 | 2.270 | 4.421 |
| 5 | min | 2.766 | 2.604 | 3.538 | 8.299 | 10.615 |
| 5 | max | 4.539 | 4.735 | 6.657 | 13.616 | 19.972 |
| 6 | run01 | 3.653 | 3.350 | 5.313 | 10.960 | 15.940 |
| 6 | run02 | 4.257 | 3.698 | 7.633 | 12.772 | 22.900 |
| 6 | run03 | 3.698 | 3.431 | 5.755 | 11.095 | 17.265 |
| 6 | run04 | 3.737 | 3.473 | 5.969 | 11.210 | 17.907 |
| 6 | run05 | 3.600 | 3.294 | 5.461 | 10.800 | 16.382 |
| 6 | mean | 3.789 | 3.449 | 6.026 | 11.367 | 18.079 |
| 6 | sample_sd | 0.267 | 0.155 | 0.934 | 0.800 | 2.801 |
| 6 | min | 3.600 | 3.294 | 5.313 | 10.800 | 15.940 |
| 6 | max | 4.257 | 3.698 | 7.633 | 12.772 | 22.900 |

| Reference K | Mean span ms | p95 span ms | Mean period % |
| --- | --- | --- | --- |
| 4 | 2.201 | 3.143 | 6.603 |
| 7 | 5.750 | 8.433 | 17.250 |

K5→K6 span mean은 3.195→3.789 ms (+18.58%), p95는 4.850→6.026 ms다. 두 K 모두 ready span이 period의 작은 부분에 모이지만 K6의 span은 평균적으로 넓다. 최종 표기는 **LESS CLUSTERED (ready-span 기준의 기술적 비교)**다.

Run 간 범위가 겹치고 모든 run pair가 같은 방향은 아니다. K5 run02의 span mean은 4.539 ms로 해당 K6 run02의 4.257 ms보다 넓다. 따라서 population 차이나 모든 run에서의 broadening을 입증했다고 말하지 않는다. 특히 “K6 inter-ready gap이 작으므로 더 bursty하다”는 추론을 하지 않았다.

첫 1초 제외 후에도 ready span mean은 3.093→3.672 ms, p95는 4.509→5.876 ms로 같은 방향이다. “Concentration이 비슷하다”는 말은 양쪽 모두 수 ms/period의 작은 비율이라는 정성적 표현일 뿐 distribution equivalence를 검증한 결과가 아니다.

## 2. Period inference service demand

| K | Run/stat | Mean ms | Median ms | p95 ms | p99 ms | Over-period count | Over-period % |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 5 | run01 | 23.107 | 22.725 | 25.684 | 27.208 | 3.000 | 0.167 |
| 5 | run02 | 23.541 | 22.814 | 27.149 | 28.452 | 1.000 | 0.056 |
| 5 | run03 | 22.946 | 22.612 | 25.455 | 27.105 | 2.000 | 0.111 |
| 5 | run04 | 23.003 | 22.678 | 25.287 | 27.071 | 2.000 | 0.111 |
| 5 | run05 | 23.000 | 22.668 | 25.426 | 27.147 | 1.000 | 0.056 |
| 5 | mean | 23.119 | 22.699 | 25.800 | 27.397 | 1.800 | 0.100 |
| 5 | sample_sd | 0.243 | 0.076 | 0.767 | 0.592 | 0.837 | 0.046 |
| 5 | min | 22.946 | 22.612 | 25.287 | 27.071 | 1.000 | 0.056 |
| 5 | max | 23.541 | 22.814 | 27.149 | 28.452 | 3.000 | 0.167 |
| 6 | run01 | 28.803 | 27.850 | 32.098 | 34.211 | 27.000 | 1.500 |
| 6 | run02 | 30.313 | 29.507 | 36.296 | 41.667 | 275.000 | 15.278 |
| 6 | run03 | 29.365 | 28.323 | 32.719 | 35.645 | 64.000 | 3.556 |
| 6 | run04 | 29.321 | 28.243 | 33.092 | 35.718 | 83.000 | 4.611 |
| 6 | run05 | 29.292 | 28.317 | 32.448 | 35.060 | 52.000 | 2.889 |
| 6 | mean | 29.419 | 28.448 | 33.331 | 36.460 | 100.200 | 5.567 |
| 6 | sample_sd | 0.549 | 0.623 | 1.697 | 2.973 | 99.803 | 5.545 |
| 6 | min | 28.803 | 27.850 | 32.098 | 34.211 | 27.000 | 1.500 |
| 6 | max | 30.313 | 29.507 | 36.296 | 41.667 | 275.000 | 15.278 |

| Reference K | Service sum mean ms | p95 ms | Over-period % |
| --- | --- | --- | --- |
| 4 | 18.461 | 18.985 | 0.056 |
| 7 | 36.787 | 42.877 | 85.556 |

Mean inference service는 4.624→4.903 ms로 6.04% 증가했다. 완전히 동일하지 않지만 per-frame 변화는 작다. 반면 stream/frame 수가 period당 5→6으로 20% 늘어 **service 합은 23.119→29.419 ms (+27.25%)**가 된다. 산술적으로 `6×mean_service_K6` 대 `5×mean_service_K5`의 비교이며 두 변화를 독립적인 causal effect로 분해한 것은 아니다.

33.333… ms를 초과하는 service sum의 period 비율은 0.100%→5.567%다. 첫 1초 제외 후에도 0.011%→5.220%로 차이가 남는다.

**Service sum < period는 그 period 안에 완료할 수 있다는 뜻이 아니다.** First-ready lag mean도 K5 10.317 ms, K6 10.934 ms다. 즉 inference는 logical period 시작부터 모든 frame을 즉시 처리할 수 없다. 서로 다른 frame의 ready 시점, 기존 work, service 사이 간격도 영향을 준다. 이 평균들만 더해서 개별 period의 feasibility를 판정하지 않았다. Service demand를 system capacity로 부르지 않는다.

## 3. Carry-over: waiting / in-service / pre-ready 분리

### all_60s

| K | Run/stat | Waiting % | In-service % | Unfinished % | Longest consecutive periods | Pre-ready % |
| --- | --- | --- | --- | --- | --- | --- |
| 5 | run01 | 1.556 | 16.722 | 16.889 | 27.000 | 0.444 |
| 5 | run02 | 1.444 | 29.167 | 29.278 | 27.000 | 0.500 |
| 5 | run03 | 1.222 | 15.611 | 15.667 | 22.000 | 0.389 |
| 5 | run04 | 1.389 | 14.111 | 14.167 | 25.000 | 0.444 |
| 5 | run05 | 1.333 | 14.222 | 14.333 | 24.000 | 0.444 |
| 5 | mean | 1.389 | 17.967 | 18.067 | 25.000 | 0.444 |
| 5 | sample_sd | 0.124 | 6.353 | 6.364 | 2.121 | 0.039 |
| 5 | min | 1.222 | 14.111 | 14.167 | 22.000 | 0.389 |
| 5 | max | 1.556 | 29.167 | 29.278 | 27.000 | 0.500 |
| 6 | run01 | 42.389 | 98.333 | 99.667 | 1,794.000 | 0.611 |
| 6 | run02 | 68.500 | 97.889 | 99.778 | 1,796.000 | 0.444 |
| 6 | run03 | 53.889 | 98.833 | 99.778 | 1,796.000 | 0.500 |
| 6 | run04 | 52.833 | 98.611 | 99.778 | 1,796.000 | 0.500 |
| 6 | run05 | 57.000 | 98.500 | 99.722 | 1,795.000 | 0.556 |
| 6 | mean | 54.922 | 98.433 | 99.744 | 1,795.400 | 0.522 |
| 6 | sample_sd | 9.370 | 0.354 | 0.050 | 0.894 | 0.063 |
| 6 | min | 42.389 | 97.889 | 99.667 | 1,794.000 | 0.444 |
| 6 | max | 68.500 | 98.833 | 99.778 | 1,796.000 | 0.611 |

### first_1s_excluded

| K | Run/stat | Waiting % | In-service % | Unfinished % | Longest consecutive periods | Pre-ready % |
| --- | --- | --- | --- | --- | --- | --- |
| 5 | run01 | 0.169 | 15.706 | 15.763 | 7.000 | 0.000 |
| 5 | run02 | 0.113 | 28.305 | 28.362 | 8.000 | 0.000 |
| 5 | run03 | 0.000 | 14.689 | 14.689 | 6.000 | 0.000 |
| 5 | run04 | 0.056 | 12.994 | 12.994 | 6.000 | 0.000 |
| 5 | run05 | 0.000 | 13.220 | 13.220 | 6.000 | 0.000 |
| 5 | mean | 0.068 | 16.983 | 17.006 | 6.600 | 0.000 |
| 5 | sample_sd | 0.074 | 6.425 | 6.448 | 0.894 | 0.000 |
| 5 | min | 0.000 | 12.994 | 12.994 | 6.000 | 0.000 |
| 5 | max | 0.169 | 28.305 | 28.362 | 8.000 | 0.000 |
| 6 | run01 | 41.751 | 98.644 | 100.000 | 1,770.000 | 0.000 |
| 6 | run02 | 68.192 | 98.136 | 100.000 | 1,770.000 | 0.000 |
| 6 | run03 | 53.333 | 99.040 | 100.000 | 1,770.000 | 0.000 |
| 6 | run04 | 52.260 | 98.814 | 100.000 | 1,770.000 | 0.000 |
| 6 | run05 | 56.554 | 98.757 | 100.000 | 1,770.000 | 0.000 |
| 6 | mean | 54.418 | 98.678 | 100.000 | 1,770.000 | 0.000 |
| 6 | sample_sd | 9.494 | 0.336 | 0.000 | 0.000 | 0.000 |
| 6 | min | 41.751 | 98.136 | 100.000 | 1,770.000 | 0.000 |
| 6 | max | 68.192 | 99.040 | 100.000 | 1,770.000 | 0.000 |

| K | Scope | Mean waiting depth | p95 waiting depth | Mean in-service depth | Mean unfinished depth | p95 unfinished depth | Max unfinished depth mean |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 4 | all_60s | 0.063 | 0.000 | 0.007 | 0.070 | 0.000 | 20.800 |
| 4 | first_1s_excluded | 0.000 | 0.000 | 0.001 | 0.001 | 0.000 | 0.800 |
| 5 | all_60s | 0.206 | 0.000 | 0.180 | 0.385 | 1.000 | 31.000 |
| 5 | first_1s_excluded | 0.001 | 0.000 | 0.170 | 0.171 | 1.000 | 2.000 |
| 6 | all_60s | 3.377 | 13.810 | 0.984 | 4.362 | 14.810 | 41.400 |
| 6 | first_1s_excluded | 2.948 | 9.710 | 0.987 | 3.935 | 10.710 | 35.600 |
| 7 | all_60s | 810.497 | 1,471.600 | 0.991 | 811.489 | 1,472.600 | 1,542.800 |
| 7 | first_1s_excluded | 823.387 | 1,472.150 | 0.994 | 824.381 | 1,473.150 | 1,542.800 |

K5는 first 1s 이후 waiting carry-over가 약 0.068%인 반면 in-service carry-over는 16.983%다. 따라서 “waiting queue가 경계에서 거의 비었다”와 “이전 inference work가 전부 완료됐다”는 같은 말이 아니다. K6에서는 waiting이 54.418%, in-service가 98.678%, 두 상태의 union이 100%다. Pre-ready는 두 K 모두 first 1s 제외 후 0%이므로 이 결과를 아직 inference-ready가 되지 않은 이전 frame 수와 혼동하지 않는다.

K6의 1,770개 post-startup boundary 모두 unfinished work가 있다는 것은 **startup-only가 아님**을 보여 준다. 그러나 매 순간 queue가 nonempty이거나 backlog가 끝없이 증가한다는 뜻은 아니다. 이전 timeline에서 K6은 후반부 낮은 주기적 queue로 회복했고, 이번 post-startup mean unfinished depth는 3.935다. K7은 같은 metric이 824.381이며 waiting 자체가 모든 post-startup boundary에서 남는 sustained-backlog reference다. Longest-consecutive 값과 growing queue depth를 구분해야 한다.

## 4. Queue depth별 wait distribution

`queue_depth_wait_summary.csv`는 long format이다. K5/K6는 exact integer depth, K7은 [0,50), [50,100), …의 50-frame bin을 사용한다. 각 run/depth에 frame_count, wait_mean_ms, wait_median_ms, wait_p95_ms를 기록한다. 그 뒤 depth가 존재하는 run들의 statistic mean/sample SD/min/max와 run_count_present를 기록한다. 해당 depth가 없는 run의 wait를 0으로 대체하지 않는다. 존재하는 run이 하나뿐이면 정의되지 않는 sample SD 행을 생략한다. Frame-count 평균도 present runs 기준이며 전체 count 확인은 각 run의 frame_count 행을 사용한다.

아래는 exact-depth 조건부 분포 중 일부다. 전체 depth와 모든 run 값은 CSV에 보존했다. n_runs가 5보다 작은 high-depth 값을 5-run formal statistic처럼 해석하지 않는다.

| K | Depth | n_runs | Mean frame count/run | Wait mean ms | Median ms | p95 ms |
| --- | --- | --- | --- | --- | --- | --- |
| 5 | 0 | 5 | 3,499.000 | 1.887 | 0.339 | 4.506 |
| 5 | 1 | 5 | 1,829.200 | 7.434 | 7.482 | 8.849 |
| 5 | 2 | 5 | 1,948.400 | 11.734 | 11.727 | 13.126 |
| 5 | 3 | 5 | 1,589.000 | 15.767 | 15.705 | 16.913 |
| 5 | 4 | 5 | 3.800 | 32.477 | 21.931 | 57.534 |
| 5 | 5 | 5 | 4.600 | 36.198 | 28.205 | 60.725 |
| 5 | 10 | 5 | 5.800 | 64.666 | 57.984 | 84.539 |
| 5 | 20 | 5 | 4.800 | 108.645 | 106.668 | 115.987 |
| 5 | 30 | 4 | 4.000 | 147.146 | 147.579 | 149.016 |
| 6 | 0 | 5 | 3,010.200 | 2.025 | 0.629 | 4.722 |
| 6 | 1 | 5 | 1,614.600 | 7.864 | 7.882 | 9.249 |
| 6 | 2 | 5 | 1,564.800 | 12.016 | 11.953 | 13.382 |
| 6 | 3 | 5 | 1,627.800 | 16.057 | 15.913 | 17.720 |
| 6 | 4 | 5 | 1,476.800 | 20.759 | 19.988 | 24.026 |
| 6 | 5 | 5 | 14.200 | 29.709 | 25.515 | 44.538 |
| 6 | 10 | 5 | 17.200 | 58.059 | 53.430 | 87.263 |
| 6 | 20 | 5 | 94.800 | 107.597 | 105.151 | 126.386 |
| 6 | 30 | 5 | 23.400 | 157.966 | 156.350 | 172.872 |

| K | Run/stat | Correlation | Value |
| --- | --- | --- | --- |
| 5 | run01 | Pearson | 0.982389 |
| 5 | run01 | Spearman | 0.957209 |
| 5 | run02 | Pearson | 0.983172 |
| 5 | run02 | Spearman | 0.952475 |
| 5 | run03 | Pearson | 0.986472 |
| 5 | run03 | Spearman | 0.956941 |
| 5 | run04 | Pearson | 0.978308 |
| 5 | run04 | Spearman | 0.956779 |
| 5 | run05 | Pearson | 0.984837 |
| 5 | run05 | Spearman | 0.957312 |
| 6 | run01 | Pearson | 0.995674 |
| 6 | run01 | Spearman | 0.975086 |
| 6 | run02 | Pearson | 0.994657 |
| 6 | run02 | Spearman | 0.990023 |
| 6 | run03 | Pearson | 0.995114 |
| 6 | run03 | Spearman | 0.977061 |
| 6 | run04 | Pearson | 0.995747 |
| 6 | run04 | Spearman | 0.979399 |
| 6 | run05 | Pearson | 0.996560 |
| 6 | run05 | Spearman | 0.975956 |
| 7 | run01 | Pearson | 0.992489 |
| 7 | run01 | Spearman | 0.990332 |
| 7 | run02 | Pearson | 0.992656 |
| 7 | run02 | Spearman | 0.990701 |
| 7 | run03 | Pearson | 0.992104 |
| 7 | run03 | Spearman | 0.989858 |
| 7 | run04 | Pearson | 0.992151 |
| 7 | run04 | Spearman | 0.989406 |
| 7 | run05 | Pearson | 0.993113 |
| 7 | run05 | Spearman | 0.990513 |
| 5 | mean | Pearson | 0.983036 |
| 5 | sample_sd | Pearson | 0.003076 |
| 5 | min | Pearson | 0.978308 |
| 5 | max | Pearson | 0.986472 |
| 5 | mean | Spearman | 0.956143 |
| 5 | sample_sd | Spearman | 0.002061 |
| 5 | min | Spearman | 0.952475 |
| 5 | max | Spearman | 0.957312 |
| 6 | mean | Pearson | 0.995550 |
| 6 | sample_sd | Pearson | 0.000718 |
| 6 | min | Pearson | 0.994657 |
| 6 | max | Pearson | 0.996560 |
| 6 | mean | Spearman | 0.979505 |
| 6 | sample_sd | Spearman | 0.006098 |
| 6 | min | Spearman | 0.975086 |
| 6 | max | Spearman | 0.990023 |
| 7 | mean | Pearson | 0.992503 |
| 7 | sample_sd | Pearson | 0.000412 |
| 7 | min | Pearson | 0.992104 |
| 7 | max | Pearson | 0.993113 |
| 7 | mean | Spearman | 0.990162 |
| 7 | sample_sd | Spearman | 0.000526 |
| 7 | min | Spearman | 0.989406 |
| 7 | max | Spearman | 0.990701 |

Pearson/Spearman은 run 안에서 먼저 계산한 뒤 5개 coefficient의 arithmetic mean을 보고한다. Spearman은 tied depth/wait에 average ranks를 사용한다. K5와 K6 모두 depth가 클수록 대체로 wait가 길어지는 강한 association이 관측된다. 그러나 high-depth 표본은 startup/긴 carry-over episode에 편중될 수 있고 일부 depth의 표본 수가 매우 작다. 모든 조건부 quantile이 strictly monotonic이라는 주장이나 correlation의 causal 해석은 하지 않는다.

Depth=0에서도 wait가 0일 필요는 없다. Pre-enqueue depth는 service 중인 frame을 제외하므로 이미 진행 중인 service의 잔여시간 또는 handoff 지연을 기다릴 수 있다. 이 정의를 바꾸지 않았다.

## 5. Hypotheses

| Hypothesis | 판정 | 의미 |
| --- | --- | --- |
| H1 | NOT SUPPORTED | K6 ready span is wider on the five-run mean, not more concentrated; overlapping run ranges preclude a claim of universal broadening. |
| H2 | SUPPORTED | Supported as an observational demand/carry-over explanation: both ready spans occupy a small fraction of the period, but K6 is modestly wider, not statistically established equivalent. |
| H3 | NOT SUPPORTED | The proposed simultaneous H1+H2 explanation lacks support for its stronger-concentration component. |

H2의 SUPPORTED는 **“강한 concentration 증가 없이 demand/carry-over 증가가 동반된다”는 observational 설명**에 대한 판정이다. Ready distribution이 통계적으로 같다고 입증했다는 뜻은 아니다. 실제 span은 평균적으로 넓어졌으므로 “timing concentration remained identical”라고 쓰면 안 된다. H1/H3의 tighter-clustering 주장은 지지되지 않는다.

## 6. Four required questions

**Q1. Ready timing은 어떻게 다른가?** K5→K6 mean span은 3.195→3.789 ms, median 3.055→3.449 ms, p95 4.850→6.026 ms다. Period 대비 mean span도 9.586→11.367%다. 양쪽 모두 수 ms에 ready가 모이지만 K6가 더 좁게 집중됐다는 증거는 없다. Run 간 겹침을 감안한 descriptive broadening이다.

**Q2. 한 period가 생성하는 observed service demand는 얼마나 늘었는가?** Mean 23.119→29.419 ms, +6.299 ms (+27.25%). Mean service는 약 6.04% 증가했고 frame 수가 20% 증가한 결과다. p95는 25.800→33.331 ms, period 초과 비율은 0.100→5.567%다. 이 합이 period보다 작아도 ready 이후에만 처리할 수 있으므로 intra-period completion을 보장하지 않는다.

**Q3. 이전 inference-stage work가 얼마나 자주 남는가?** 전체 60초에서 K5 waiting/in-service/unfinished 비율은 1.389/17.967/18.067%, K6은 54.922/98.433/99.744%다. 첫 1초 제외 후에는 K5 0.068/16.983/17.006%, K6 54.418/98.678/100.000%다. Waiting/in-service를 구분했고 pre-ready를 합치지 않았다.

**Q4. Unfinished carry-over 증가와 queue wait 증가가 함께 관측되는가?** YES. Post-startup mean unfinished depth는 0.171→3.935 frames, mean queue wait는 8.975→25.778 ms다. 각각 boundary-based post-startup metric과 full-run frame metric이므로 같은 denominator라고 혼동하지 않는다. 기존 formal 후반부/새 carry-over split도 startup만의 설명을 배제한다. 이러한 동반 변화는 causal attribution의 완결된 증명은 아니다.

## 7. Claim strength와 paper wording

**LEVEL 1: SUPPORTED.** Queue wait의 mean E2E 비율은 K5 34.88%, K6 59.10%, K7 99.54%다. K5→K6 E2E mean 증가의 93.92%가 queue wait 증가다. 이는 기존 mean decomposition을 인용한 것이며 component p95를 합산하지 않는다.

**LEVEL 2: SUPPORTED.** Ready timing, 늘어난 period inference demand, inter-period unfinished work가 큰 queue wait와 함께 관측된다.

**LEVEL 3: NOT PROVEN.** Arrival clustering이 deadline miss를 유발했다고 확정할 controlled phase experiment를 수행하지 않았다. Demand/ready distribution/service variation/host effects를 독립적으로 조작하지 않았으므로 각각의 causal 기여는 식별하지 못한다. 기존 raw가 설명하는 association의 범위 안에서 주장한다.

**English:** From K=5 to K=6, the mean inference-ready span widened from 3.20 to 3.79 ms, while observed inference service demand per logical period increased from 23.12 to 29.42 ms. Excluding the first second, unfinished inference work was present at 17.01% versus 100% of subsequent period boundaries, alongside an increase in full-run mean queue wait from 8.98 to 25.78 ms. These observations support an association between increased per-period demand, inter-period carry-over, and queue buildup, rather than stronger ready-time concentration at K=6; they do not establish a causal effect of arrival clustering.

**Korean:** K5에서 K6로 증가할 때 inference-ready span 평균은 3.20에서 3.79 ms로 넓어졌지만, logical period당 observed inference service demand는 23.12에서 29.42 ms로 증가했다. 첫 1초를 제외한 period boundary에서 이전 inference work가 남는 비율은 17.01%에서 100%로 증가했으며, 전체 run의 평균 queue wait도 8.98에서 25.78 ms로 증가했다. 이는 K6의 더 강한 ready-time 집중보다 증가한 period demand와 carry-over가 queue buildup과 연관된다는 설명을 지지하며, arrival clustering의 causal effect를 입증하지는 않는다.

## 8. 최종 논문 figure: PNG 3개

[Figure 1](../figures/figure_1_local_qos_knee.png): (a) K별 mean-of-run E2E mean/p95와 candidate deadline, (b) mean-of-run miss percentage. K7 scale 때문에 (a)는 log y축이다. Error bar는 5-run sample SD, 개별 run line/point는 없다.

[Figure 2](../figures/figure_2_latency_decomposition.png): 5-run K-level mean 4개 component의 additive stacked bar. K1–K6와 K7을 서로 다른 linear y축 panel로 나눠 작은 항과 K7의 크기를 동시에 읽을 수 있게 했다. 두 y축 모두 ms이며 percentile을 쌓지 않는다. Variability overlay는 없다.

[Figure 3](../figures/figure_3_k5_k6_temporal_queue.png): K5/K6의 (a) ready span mean, (b) observed per-period service sum mean, (c) unfinished inference carry-over period %. 세 panel 모두 전체 60초 metric이고 error bar는 5-run sample SD다. Panel (b)의 33.333… ms line은 **frame-period reference**, service capacity가 아니다. Startup 제외 결과는 위 표에 별도로 보존한다.

세 PNG는 350 dpi로 저장한다. 개별 run trace/scatter/cloud는 표시하지 않는다. 이전 A–H PNG/PDF는 삭제 대상으로 지정되었으며 기존 CSV/JSON/MD의 수치는 그대로 보존한다. 이전 analysis_report.md와 figure_manifest.json은 historical 분석 기록이므로 삭제된 A–H를 가리키는 링크/목록이 남을 수 있다. 현재 논문 figure의 기준은 이 report의 Figure 1–3이다. 이전 report/manifest를 재작성하거나 원본 CSV를 수정하지 않았다.

## 9. 재현과 검증

단일 `characterize_temporal_queue.py`는 `analyze`(raw 읽기), `report`(이미 계산된 temporal data의 표/해석), `figures`(PNG 3개), `validate`(파일/집계/보존 검증) mode를 제공한다. 파일은 exclusive creation하므로 기존 산출물이 있으면 덮어쓰지 않는다. Python script에 figure 삭제나 Git commit/push 명령은 없다. 삭제와 Git 작업은 명시적인 allowlist로 별도 수행한다.

CSV는 `ready_span_summary.csv`, `period_service_demand_summary.csv`, `carryover_summary.csv`, `queue_depth_wait_summary.csv`, `k5_k6_explanation.csv`다. Run-level 값 및 mean/sample SD/min/max를 포함한다. 추가 로컬 JSON은 input preservation과 offline intermediate/validation evidence이고 raw frame을 Git에 추가하지 않는다.

검증은 NaN/inf/중복 key 없음, K5/K6 각각 5개 run, per-stream IDs, boundary category partition, in-service depth≤1, 5-run aggregate, 원본 SHA256/size/mtime/file count 동일성, 최종 figure PNG=3/PDF=0을 확인한다. 이 과정에서 새로운 workload는 실행하지 않는다.

## 다음 단계

**RT-DETR graph split feasibility analysis로 진행 가능: YES.** Local motivation에 필요한 queue dominance와 demand/carry-over association이 정리되었다. 특정 split/offloading의 이득을 입증한 것은 아니므로 다음 단계는 구조적 feasibility와 비용 분석이다. Level 3 causal claim이 반드시 필요한 경우에만 별도 승인된 controlled phase experiment가 필요하다. 이번 task에서는 어떤 phase/partition experiment도 수행하지 않았다.

## 최종 검증 결과

**PASS:** 35 runs / 252,000 frames. Formal raw 파일은 320개로 전후 동일하며, 보호한 기존 파일 672개의 SHA256/size/mtime_ns가 모두 같다. Waiting carry-over는 raw record 조건식 계산 외에 queue event sequence replay로 독립 검증했다. 새 CSV 5개는 finite/unique 검사를 통과했고, 지정 figure directory에는 350 dpi PNG 3개와 PDF 0개만 남았다. Temporal directory의 PDF도 0개다.

PDF 삭제 범위는 지정된 Local latency breakdown figure directory다. 별도 기존 baseline의 local_capacity_transition_v4/v8/v10.pdf 3개는 baseline 보존 원칙에 따라 유지한다. 따라서 repository 전체 PDF 수가 0이라는 주장은 하지 않는다. 기존 A–H PDF 8개와 PNG 8개 삭제, 새 핵심 PNG 3개 생성만 figure 변경에 포함했다.
