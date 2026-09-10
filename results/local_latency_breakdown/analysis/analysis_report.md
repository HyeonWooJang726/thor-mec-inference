# Local latency breakdown formal post-analysis

분석 대상은 이미 완료된 K=1–7 × 5 runs, 252,000 frames다. 이 작업은 CPU에서 저장된 artifact를 읽고 분석했으며, benchmark/GPU inference를 실행하지 않았다. 새 파일은 모두 `results/local_latency_breakdown/analysis/`에만 생성했다. Formal raw artifact, 기존 baseline, measurement code를 수정하지 않았다.

핵심 결과는 K5의 deadline knee, K6의 큰 queue wait와 run 간 변동, K7의 workload 전 구간 backlog 누적이다. K6의 deadline 부담과 K7의 지속적인 처리량 overload는 구분해야 한다. 아래 수치는 60초 finite workload에 대한 관측이며 무한 시간의 안정성이나 최종 application SLA를 보증하지 않는다.

## 1. 근거와 분석 정의

HEAD: `92c67ff301d5d65b67256403e12e660bb1084950`. Formal metadata: `../experiment_metadata.json`; 시작 2026-09-10T07:44:41.466602+00:00, 완료 2026-09-10T08:21:42.040999+00:00. Run별 근거: `../kK/runNN/per_frame.csv`, `raw_ns.json`, `validation.json`, `metadata.json`; 실행 결과와 preflight: `../kK/runNN_execution.json`.

K별 값은 **각 run에서 계산한 statistic 5개의 산술평균**이다. Run 간 sample SD는 분모 n−1=4를 사용한다. Min/max는 5개 run statistic의 최솟값/최댓값이다. Run별 percentile은 전체 frame에 대해 linear interpolation으로 계산한다. K별 p95는 5개 run p95의 평균이며 pooled-frame p95가 아니다. Startup frame을 formal summary에서 제외하지 않았다. 아래 temporal 진단은 별도로 표시한 분석용 구간 통계다.

Candidate deadline은 정확히 **1/30 second**이며 `e2e_ns * 30 > 1_000_000_000`인 frame을 miss로 판단한다. 표시값 33.333… ms를 반올림해서 판정하지 않는다. 이것은 기존 Local 실험과 비교할 candidate deadline이고 최종 application SLA가 아니다.

`a`: logical scheduled job arrival; `b`: front-end 실제 시작; `r`: unbounded ready queue put 완료 직후, accounting lock 안에서 기록; `s`: 같은 accounting lock에서 service-start bookkeeping 후 infer 호출 직전; `c`: infer 반환 직후다. 실제 camera capture time을 측정하지 않는다. Clock은 기존과 같은 performance-counter underlying monotonic clock이며 integer-ns API를 사용한다.

`front_end_ms` boundary (formal metadata 그대로): pull-sample wait/access; caps validation; buffer map; ndarray view; preprocess_bgr; unmap; ready job preparation; accounting lock acquisition; unbounded queue insertion through r; async decode service is not isolated.

`inference_ms` boundary: TensorRT inference-worker service time: input validation, synchronous input H2D, execute_async_v3(stream=0), cudaDeviceSynchronize, synchronous output D2H, Python return; includes tiny s lock-release/call overhead; not pure GPU kernel latency. 따라서 각각 순수 decode service time과 순수 GPU kernel latency로 해석하지 않는다.

Workload는 30 FPS/stream, 1,800 frames/stream, B=1/C=1, 단일 inference worker, phase-aligned arrival이다. Stream i는 기존 formal의 `W027_Camera_000i.mp4`(i=0…6)이며 K 증가 시 누적 mapping이다. 모든 run metadata의 active mapping과 engine/source hashes가 root metadata와 일치한다. Engine은 `models/rtdetr_warehouse_v1.0.2.fp16.b1.canonical.engine`이다. Pipeline, preprocessing, worker ordering, warm-up 없음이 보존된 formal artifact를 분석했다.

MAXN, DVFS unlocked, jetson_clocks 미사용 조건이다. Historical deliberate cooldown은 UNKNOWN, 이번 protocol의 deliberate sleep은 NONE이며 35개 execution artifact 모두 deliberate_sleep_ns=0이다. 각 run의 종료·cleanup·validation 후 다음 run을 시작한다. 이는 과거 cooldown의 재현을 입증하는 것이 아니다.

> Historical deliberate cooldown could not be established. The new latency-breakdown formal protocol therefore uses no additional deliberate inter-run sleep; the next run starts after successful completion, cleanup, and validation of the preceding run.

## 2. Formal integrity: PASS

| 항목 | 결과 |
| --- | --- |
| Formal run directories / per_frame.csv | 35 / 35 |
| 전체 rows | 252,000 |
| 각 K/run frame 수 | K × 1,800; arrivals/source/preprocessed/completions/rows 모두 일치 |
| Stream frame IDs | 모든 stream에서 0…1799 exactly once |
| per_frame schema | 정확한 10 columns |
| per_run_summary schema | 35 rows / 14 columns |
| motivation_summary schema | 7 rows / 15 columns |
| inference_queue_summary schema | 7 rows / 5 columns |
| raw a ≤ b ≤ r ≤ s ≤ c 위반 | 0 |
| raw integer-ns decomposition 위반 / 최대오차 | 0 / 0 ns |
| 음수 queue depth / event sequence 불일치 | 0 / 0 |
| Drain 후 waiting queue | 모든 run 0 |
| Run별 / K별 summary 재계산 | PASS |
| 기존 baseline raw → summary 재계산 | PASS |

`raw_ns.json`이 보존되어 있으므로 반올림된 ms를 더하는 방식 대신 모든 raw integer timestamp를 다시 확인했다. Queue event를 저장된 monotonic sequence 그대로 replay하고, enqueue/start 중복·누락, frame별 r/s 일치, counter 차이, depth, final drain을 검증했다. Event integral과 독립적으로 각 frame의 [r,s) interval을 첫/마지막 enqueue에 clip해 더한 integer frame-ns area가 정확히 같았다. Per-frame CSV의 10개 값과 raw-derived 값도 일치한다. 단일 service interval의 비중첩과 `a=t0+floor(frame_id×10^9/30)`도 검증했다.

Decomposition identity는 arithmetic consistency 검사다. 그 자체가 물리적인 event boundary의 독립 측정 증거는 아니며, boundary 의미는 보존된 code/metadata와 함께 해석한다. 집계 CSV를 부동소수점으로 재표시할 때 나타나는 약 3.6×10⁻¹⁵ ms 수준의 합산 차이는 raw-ns 오차가 아니다. 상세: [formal_integrity_report.json](formal_integrity_report.json).

## 3. Deadline knee와 전체 결과

| K | Offered FPS | E2E mean ms | p95 ms | p99 ms | Miss % | p95 > deadline runs |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | 30 | 22.267 | 24.297 | 24.682 | 0.178 | 0/5 |
| 2 | 60 | 19.356 | 23.333 | 24.176 | 0.339 | 0/5 |
| 3 | 90 | 20.014 | 24.574 | 25.416 | 0.563 | 0/5 |
| 4 | 120 | 22.931 | 29.636 | 31.055 | 0.850 | 0/5 |
| 5 | 150 | 25.730 | 33.822 | 104.084 | 4.907 | 1/5 |
| 6 | 180 | 43.621 | 109.433 | 221.505 | 35.048 | 5/5 |
| 7 | 210 | 4,294.064 | 7,213.384 | 7,337.789 | 100.000 | 5/5 |

**Stable region: K1–K4**라는 표현은 낮은 finite-run miss와 deadline 아래 p95/p99를 뜻한다. Zero-miss 보장은 아니다. K4 p95는 29.636 ms, p99는 31.055 ms로 deadline 여유가 작아진다.

**Transition / knee: K5.** Mean은 25.730 ms로 deadline 아래지만 평균 run p95는 33.822 ms로 경계를 넘고, miss는 4.907%, p99는 104.084 ms다. Run별 차이가 있으므로 “모든 K5 run의 p95가 초과한다”는 주장은 하지 않는다.

**Deadline-overloaded region: K6.** Mean 43.621 ms, p95 109.433 ms, miss 35.048%로 deadline 관점의 명백한 저하다. 그러나 queue가 60초 전체에 걸쳐 증가하지 않으므로 이를 지속적인 평균 처리량 overload라고 단정하지 않는다.

**명백한 sustained overload / accumulating-backlog region: K7.** 100% miss, mean 4.294 s, p95 7.213 s이며 5개 run 모두 backlog가 지속적으로 누적된다. 여기서 “unstable”은 이 finite-run backlog 양상을 의미하고 이론적인 무한 시간 안정성 검증을 뜻하지 않는다.

| K | 첫 1초 miss % | 이후 59초 miss % | 전체 miss 중 첫 1초 비율 % |
| --- | --- | --- | --- |
| 1 | 10.667 | 0.000 | 100.000 |
| 2 | 20.333 | 0.000 | 100.000 |
| 3 | 33.778 | 0.000 | 100.000 |
| 4 | 49.667 | 0.023 | 97.499 |
| 5 | 92.933 | 3.415 | 32.859 |
| 6 | 100.000 | 33.947 | 5.099 |
| 7 | 100.000 | 100.000 | 1.667 |

이 표는 scheduled time을 기준으로 run 안에서 먼저 계산하고 5개 run 값을 평균했다. K5의 p99와 일부 miss는 startup에 민감하지만, 이후에도 miss가 남는다. K6은 첫 1초를 제외한 진단에서도 miss 33.947%이므로 startup만으로 설명되지 않는다. Formal summary와 figure A–D에는 모든 startup frame이 포함된다.

## 4. Mean latency decomposition

| K | Lag ms (%) | Front end ms (%) | Queue wait ms (%) | Inference ms (%) | E2E ms |
| --- | --- | --- | --- | --- | --- |
| 1 | 0.359 (1.61%) | 9.633 (43.26%) | 0.179 (0.81%) | 12.096 (54.32%) | 22.267 |
| 2 | 0.558 (2.88%) | 9.972 (51.52%) | 3.015 (15.58%) | 5.811 (30.02%) | 19.356 |
| 3 | 0.716 (3.58%) | 10.297 (51.45%) | 4.358 (21.78%) | 4.643 (23.20%) | 20.014 |
| 4 | 0.846 (3.69%) | 10.957 (47.78%) | 6.513 (28.40%) | 4.615 (20.13%) | 22.931 |
| 5 | 0.968 (3.76%) | 11.163 (43.38%) | 8.975 (34.88%) | 4.624 (17.97%) | 25.730 |
| 6 | 1.022 (2.34%) | 11.917 (27.32%) | 25.778 (59.10%) | 4.903 (11.24%) | 43.621 |
| 7 | 0.989 (0.02%) | 13.446 (0.31%) | 4,274.372 (99.54%) | 5.255 (0.12%) | 4,294.064 |

Component share는 K별 component mean / K별 E2E mean이다. Mean은 additive하지만 **component p95의 합은 E2E p95가 아니다**. 이 분석은 component percentile을 더하지 않는다.

K1에서는 inference service가 mean E2E의 54.32%다. K4에서는 front end 47.78%, queue wait 28.40%이고, K5는 front end 43.38%, queue wait 34.88%다. 따라서 K5에서 queue가 절대적인 평균 지배항이라고 말할 수는 없다. K6부터 queue wait가 59.10%로 가장 큰 항이 되며 K7에서는 99.54%다.

| 변화 | Component | Mean 증가 ms | E2E 증가 기여 % |
| --- | --- | --- | --- |
| K4→K5 | frame_start_lag | 0.122 | 4.36 |
| K4→K5 | front_end | 0.206 | 7.36 |
| K4→K5 | inference_queue_wait | 2.462 | 87.97 |
| K4→K5 | inference | 0.009 | 0.31 |
| K5→K6 | frame_start_lag | 0.054 | 0.30 |
| K5→K6 | front_end | 0.755 | 4.22 |
| K5→K6 | inference_queue_wait | 16.803 | 93.92 |
| K5→K6 | inference | 0.279 | 1.56 |
| K6→K7 | frame_start_lag | -0.033 | -0.00 |
| K6→K7 | front_end | 1.529 | 0.04 |
| K6→K7 | inference_queue_wait | 4,248.595 | 99.96 |
| K6→K7 | inference | 0.352 | 0.01 |

K5→K6 E2E 증가 17.891 ms 중 queue wait 증가가 16.803 ms, 즉 **93.92%**다. Lag, front end, inference service의 변화도 측정되지만 이 증가분의 주된 latency 항은 queue wait다. 이는 관측된 additive decomposition에 대한 판정이며 각 원인을 독립적으로 조작한 causal experiment는 아니다.

## 5. Application-level waiting queue

`Q_inf(t)=#{j:r_j≤t<s_j}`이며 현재 inference service 중인 frame은 제외한다. Pre-enqueue depth는 해당 frame 자신을 제외한 N_enqueue−N_inference_start다. Enqueue가 완료된 event 직후 depth는 여기에 1을 더한 값이다. Peak는 전체 event sequence의 최대 waiting depth다. Time-weighted 값은 **첫 ready enqueue부터 마지막 ready enqueue까지** integer-ns 면적을 interval 길이로 나눈 값이다. Last-enqueue 값은 마지막 ready enqueue 직후 waiting frame 수다. Logical last arrival이나 drain 후 depth와 혼동하지 않는다.

| K | Peak mean ± SD [min,max] | Time-weighted mean ± SD [min,max] | At-last mean ± SD [min,max] |
| --- | --- | --- | --- |
| 1 | 2.000 ± 0.000 [2.000, 2.000] | 0.005 ± 0.001 [0.004, 0.006] | 1.000 ± 0.000 [1.000, 1.000] |
| 2 | 5.600 ± 0.894 [5.000, 7.000] | 0.181 ± 0.006 [0.173, 0.188] | 1.000 ± 0.000 [1.000, 1.000] |
| 3 | 13.600 ± 1.140 [12.000, 15.000] | 0.393 ± 0.006 [0.387, 0.402] | 2.000 ± 0.000 [2.000, 2.000] |
| 4 | 22.000 ± 1.581 [20.000, 24.000] | 0.783 ± 0.045 [0.708, 0.829] | 3.000 ± 0.000 [3.000, 3.000] |
| 5 | 33.600 ± 2.302 [30.000, 36.000] | 1.350 ± 0.047 [1.277, 1.394] | 4.000 ± 0.000 [4.000, 4.000] |
| 6 | 44.600 ± 4.879 [40.000, 52.000] | 4.653 ± 3.022 [2.971, 10.036] | 5.000 ± 0.000 [5.000, 5.000] |
| 7 | 1,546.400 ± 58.252 [1,468.000, 1,615.000] | 813.013 ± 24.411 [787.784, 844.162] | 1,546.400 ± 58.252 [1,468.000, 1,615.000] |

각 run의 세 queue metric을 먼저 계산하고 5회 값을 평균했다. Peak와 last-enqueue 평균이 같아 보이더라도 정확한 event 정의는 다르다. K7에서는 실제로 각 run의 마지막 enqueue depth가 해당 run peak와 일치한다. K1–K6의 마지막 enqueue 직후 소수 frame은 마지막 동시 arrival batch의 정상 drain 대상이 될 수 있으므로 그 값만으로 overload를 판정하지 않는다.

Figure E/F의 x축은 logical scheduled arrival이고 각 선은 한 run의 1초 bin mean이다. 실제 event 시간축으로 replay한 Q(t)는 Figure G에 별도로 제공한다. Figure G는 전체 raw event를 적분한 100 ms bin time mean이다. 100 ms 간격의 순간 샘플링은 30 FPS의 세 period마다 같은 위상을 보아 짧은 waiting을 체계적으로 놓칠 수 있으므로 그림에는 사용하지 않았다. Bin averaging은 peak를 평탄화하지만 정확한 peak/integral/continuous-wait 검증은 전체 raw event를 사용한다. 별도 순간 샘플 CSV는 진단용이며 Figure G와 다르다.

| K | Scheduled interval s | Mean pre-enqueue depth | Queue wait mean ms | Miss % |
| --- | --- | --- | --- | --- |
| 5 | 0–10 | 2.617 | 15.495 | 13.173 |
| 5 | 10–20 | 1.186 | 7.740 | 2.920 |
| 5 | 20–30 | 1.181 | 7.609 | 2.920 |
| 5 | 30–40 | 1.184 | 7.640 | 2.720 |
| 5 | 40–50 | 1.182 | 7.688 | 4.173 |
| 5 | 50–60 | 1.181 | 7.681 | 3.533 |
| 6 | 0–10 | 12.852 | 70.684 | 64.322 |
| 6 | 10–20 | 5.860 | 33.367 | 40.111 |
| 6 | 20–30 | 3.497 | 20.271 | 32.844 |
| 6 | 30–40 | 1.671 | 10.154 | 24.411 |
| 6 | 40–50 | 1.668 | 10.061 | 23.811 |
| 6 | 50–60 | 1.670 | 10.132 | 24.789 |
| 7 | 0–10 | 186.935 | 1,023.125 | 100.000 |
| 7 | 10–20 | 445.214 | 2,408.592 | 100.000 |
| 7 | 20–30 | 695.918 | 3,758.231 | 100.000 |
| 7 | 30–40 | 941.571 | 5,051.921 | 100.000 |
| 7 | 40–50 | 1,176.001 | 6,326.033 | 100.000 |
| 7 | 50–60 | 1,418.692 | 7,078.333 | 100.000 |

## 6. K6: 평균 service reciprocal과 deadline의 차이

| 지표 | 값 |
| --- | --- |
| Offered load | 180 FPS |
| Mean inference service | 4.903103 ms |
| 1000 / K6 mean inference service | 203.952 FPS — system capacity 아님 |
| Mean queue wait | 25.778 ms |
| Mean of run queue-wait p95 | 87.654 ms |
| Miss | 35.048% |
| 6-frame tick의 service sum mean | 29.419 ms |
| Service sum > 33.333… ms인 tick 비율 | 5.567% |
| 동일 tick 6개 ready event span mean / p95 | 3.789 / 6.026 ms |
| 6개 ready event가 5 ms 이내 / 10 ms 이내인 tick | 88.944% / 99.267% |
| 다음 logical tick에서 waiting queue > 0 (첫 1초 이후) | 54.418% |
| Waiting queue nonempty 실제 시간비율 (첫 1초 이후) | 73.698% |
| Service busy 실제 시간비율 (첫 1초 이후) | 88.344% |

203.952 FPS는 관측된 inference-worker service mean의 단순 역수다. Front-end arrival delay, phase-aligned burst, service 간 overhead/idle interval, service-time/load dependency와 deadline을 포함한 system capacity가 아니다. 180 FPS가 이 reciprocal 아래라는 사실은 deadline 충족을 보장하지 않는다. 또한 queue 제거 후에도 동일 service distribution이 유지된다고 가정할 수 없다.

**직접 관측: synchronized arrival burst.** 동일 frame_id의 6개 logical a가 정확히 같고, 대부분의 batch는 수 ms 이내에 모두 ready가 된다. 하지만 단일 worker가 6개의 service를 처리하는 시간 합의 평균은 29.419 ms다. 여기에 평균 front end 약 11.917 ms와 start lag가 이미 소비된 상태이므로 평균 service sum이 한 period보다 작아도 뒤쪽 frame의 completion deadline을 만족하기 어렵다. 아래는 각 tick 안에서 s가 빠른 순위로 분류한 결과다. Stream ID 순위가 아니며, 어떤 stream이 항상 마지막이라는 뜻도 아니다.

| K6 within-tick service rank | Queue wait mean ms | E2E mean ms | Miss % |
| --- | --- | --- | --- |
| 1 | 15.560 | 31.425 | 13.889 |
| 2 | 19.661 | 36.304 | 13.967 |
| 3 | 23.634 | 41.088 | 14.022 |
| 4 | 27.728 | 45.677 | 14.222 |
| 5 | 31.716 | 51.009 | 54.189 |
| 6 | 36.369 | 56.221 | 100.000 |

마지막 service-start 순위 frame은 5개 run 모두 100% miss다. 순위별 gradient는 burst와 직렬 service의 deadline 부담을 직접 뒷받침한다. Inter-tick carry-over도 섞여 있으므로 이 표에서 burst만의 독립 causal effect를 추정하지 않는다.

**직접 관측: front-end / service-time variation.** K6 front-end p95는 14.737 ms, run별 최대 front-end는 156.019–214.868 ms다. Service p95는 6.775 ms, p99는 8.901 ms, run별 최대 service는 23.024–29.481 ms다. 각 tick의 service 합이 period를 넘는 비율도 run별 1.500–15.278%로 변한다. 이러한 변동은 관측되지만 FE 지연과 service 지연 각각이 queue tail에 미친 독립 기여나 원인(예: CPU/GPU scheduling)은 trace/대조실험 없이 식별할 수 없다.

| K6 run | E2E mean ms | Qwait mean ms | Front end mean ms | Service mean ms | 최장 연속 waiting>0 s (1초 이후) | At-last queue | Drain s |
| --- | --- | --- | --- | --- | --- | --- | --- |
| run01 | 34.073 | 16.450 | 11.617 | 4.801 | 1.809 | 5 | 0.03010 |
| run02 | 74.366 | 55.605 | 12.725 | 5.052 | 24.609 | 5 | 0.02505 |
| run03 | 35.816 | 18.282 | 11.730 | 4.894 | 3.309 | 5 | 0.02749 |
| run04 | 38.372 | 20.748 | 11.813 | 4.887 | 5.175 | 5 | 0.02691 |
| run05 | 35.477 | 17.805 | 11.702 | 4.882 | 2.375 | 5 | 0.02437 |

**직접 관측: 여러 period에 걸친 carry-over, 이후 회복.** Run02의 연속 waiting episode는 24.609초이며 FE/service mean도 K6 run 중 가장 크다. 이것은 동반 변화에 대한 관측이다. 다른 run의 episode는 더 짧고 모든 K6 run은 후반부에 낮은 주기적 queue로 회복한다. 1–59초 sampled Q의 회귀 slope는 모두 음수이고, 마지막 enqueue 직후 waiting은 모두 5 frames다. 따라서 K6은 장시간 carry-over episode를 보이지만 K7 같은 workload 전체의 지속적인 backlog growth는 아니다. 40–60초에도 약 24% miss가 남아, 초기 backlog만으로 전체 deadline 문제를 설명할 수 없다.

추가적인 **산술 진단**에서 K6 전체 frame의 34.507%는 observed nonqueue sum(lag+front end+service)은 deadline 이하지만 queue wait를 포함하면 miss다. 이는 run별 miss 중 평균 98.365%다. 이 분류는 저장된 latency의 구성요소 관계만 보여 준다. Queue를 제거한 실제 시스템의 miss 감소율이나 counterfactual 성능 예측이 아니다.

## 7. K7: transient burst가 아닌 workload 전체의 backlog accumulation

| Run | Q(10s) | Q(30s) | Q(50s) | Q slope frames/s (1–59s) | At-last Q | Drain 이후 completion까지 s |
| --- | --- | --- | --- | --- | --- | --- |
| run01 | 323 | 826 | 1297 | 24.726 | 1,564 | 6.946 |
| run02 | 341 | 784 | 1230 | 22.716 | 1,468 | 6.599 |
| run03 | 328 | 841 | 1353 | 25.587 | 1,615 | 7.224 |
| run04 | 322 | 843 | 1318 | 25.291 | 1,577 | 7.125 |
| run05 | 294 | 801 | 1267 | 24.418 | 1,508 | 6.651 |

5개 run 모두 첫 1초 이후부터 마지막 enqueue까지 Q>0이 연속 유지된다. Q(10s), Q(30s), Q(50s)의 run 평균은 각각 321.6, 819.0, 1,293.0 frames다. 전체 event에서 기다림이 이어지고 1,10,20,…,50,59초의 모든 step이 모든 run에서 증가한다. Q slope는 22.716–25.587 frames/s다. 일시적인 마지막 burst 하나로 이 형태를 설명할 수 없다.

Peak/last-enqueue mean 1,546.4 frames, time-weighted mean 813.013 frames이며 마지막 enqueue 이후에도 6.599–7.224초가 더 필요하다. Drain 후에는 모두 0이지만, 이는 입력 종료 후 backlog를 끝까지 처리했다는 뜻이다. Workload를 수용하는 동안 deadline/queue가 안정적이었다는 뜻이 아니다.

K7 offered load는 210 FPS다. 동일 tick 7개 service 합의 평균은 36.787 ms로 period 33.333… ms보다 크고, 85.556%의 tick이 period를 초과한다. 이 service-demand 관측과 실제 Q timeline이 sustained overload 판정을 함께 뒷받침한다. Mean E2E 중 queue wait 비중은 99.54%다.

## 8. K1 inference latency anomaly

| K | Service mean ms | 5-run min ms | 5-run max ms |
| --- | --- | --- | --- |
| 1 | 12.096 | 11.801 | 12.328 |
| 2 | 5.811 | 5.678 | 5.895 |
| 3 | 4.643 | 4.629 | 4.665 |
| 4 | 4.615 | 4.583 | 4.639 |
| 5 | 4.624 | 4.589 | 4.708 |
| 6 | 4.903 | 4.801 | 5.052 |
| 7 | 5.255 | 5.221 | 5.274 |

**OBSERVED FACT.** K1 service mean은 12.096 ms로 K2 5.811 ms 및 K3–K5 약 4.62 ms보다 크다. K1 첫 1초 mean은 6.810 ms이고 이후 59초 mean은 12.185 ms다. 따라서 단순히 시작 직후의 느린 몇 frame이 전체 service mean을 끌어올렸다는 설명은 맞지 않는다. 첫 1초 이후 K1 service busy 시간비율은 36.549%다.

**POSSIBLE EXPLANATION.** MAXN이 clock 고정을 의미하지 않고 DVFS가 unlocked이므로 낮은 load에서의 clock/power behavior는 가능한 설명이다. Infer boundary에는 CPU input check, host-device copies, synchronization, Python overhead도 포함되어 있어 GPU clock 외의 CPU/runtime/load-dependent 영향도 가능하다.

**NOT PROVEN.** Formal artifact에는 GPU clock 또는 temperature의 연속 trace가 없다. Per-run preflight의 governor/min/max 설정 및 일부 CPU current-frequency snapshot은 실행 중 GPU clock을 대체하지 못한다. 따라서 “DVFS가 원인” 또는 “GPU kernel이 K1에서 두 배 느리다”는 결론을 내릴 수 없다. Clock을 고정한 대조실험도 이번 작업에서 실행하지 않았다.

## 9. Run order / time drift

| Round | 실제 K 순서 |
| --- | --- |
| run01 | 1 → 2 → 3 → 4 → 5 → 6 → 7 |
| run02 | 2 → 3 → 4 → 5 → 6 → 7 → 1 |
| run03 | 3 → 4 → 5 → 6 → 7 → 1 → 2 |
| run04 | 4 → 5 → 6 → 7 → 1 → 2 → 3 |
| run05 | 5 → 6 → 7 → 1 → 2 → 3 → 4 |

Metadata order와 각 run raw t0를 대조해 위 순서의 chronological execution position 1–35를 확인했다. 각 K 안에서 5개 run에 대해 position/elapsed-time slope, Pearson r, Spearman rho를 계산했다. 전체 공통 slope는 X와 Y를 K별로 중심화해 K load 차이로 인한 교란을 줄였다. 단순히 모든 run latency를 시간축에 pooled 회귀하지 않았다.

| Metric | K-adjusted slope ms/position | Slope ms/elapsed min | Within-K-centered r | Exploratory permutation p |
| --- | --- | --- | --- | --- |
| inference_mean_ms | -0.000528 | -0.000498 | -0.0615 | 0.7785 |
| front_end_mean_ms | -0.001496 | -0.001409 | -0.0444 | 0.8183 |
| e2e_mean_ms | -0.183590 | -0.173399 | -0.0370 | 0.8119 |

| K | Metric | Slope ms/position | Pearson r | Spearman rho | First→last ms |
| --- | --- | --- | --- | --- | --- |
| 1 | inference_mean_ms | -0.005279 | -0.291 | -0.300 | 12.141 → 11.956 |
| 1 | front_end_mean_ms | 0.000688 | 0.311 | 0.300 | 9.601 → 9.640 |
| 1 | e2e_mean_ms | -0.004610 | -0.247 | -0.300 | 22.310 → 22.231 |
| 2 | inference_mean_ms | 0.003418 | 0.537 | 0.300 | 5.678 → 5.797 |
| 2 | front_end_mean_ms | -0.003784 | -0.698 | -0.700 | 10.081 → 9.944 |
| 2 | e2e_mean_ms | 0.002962 | 0.346 | 0.300 | 19.198 → 19.318 |
| 3 | inference_mean_ms | -0.000278 | -0.228 | -0.100 | 4.665 → 4.634 |
| 3 | front_end_mean_ms | -0.000053 | -0.008 | 0.200 | 10.335 → 10.362 |
| 3 | e2e_mean_ms | -0.001349 | -0.122 | -0.600 | 20.081 → 20.036 |
| 4 | inference_mean_ms | -0.000320 | -0.169 | -0.300 | 4.631 → 4.622 |
| 4 | front_end_mean_ms | 0.019527 | 0.302 | 0.900 | 10.563 → 10.737 |
| 4 | e2e_mean_ms | 0.031965 | 0.711 | 0.900 | 22.496 → 23.239 |
| 5 | inference_mean_ms | -0.002511 | -0.490 | -0.600 | 4.621 → 4.600 |
| 5 | front_end_mean_ms | -0.019114 | -0.419 | -0.800 | 11.018 → 10.966 |
| 5 | e2e_mean_ms | -0.019364 | -0.572 | -0.600 | 25.818 → 25.515 |
| 6 | inference_mean_ms | -0.000039 | -0.004 | 0.000 | 4.801 → 4.882 |
| 6 | front_end_mean_ms | -0.012367 | -0.257 | 0.100 | 11.617 → 11.702 |
| 6 | e2e_mean_ms | -0.553103 | -0.304 | 0.100 | 34.073 → 35.477 |
| 7 | inference_mean_ms | 0.000310 | 0.134 | 0.100 | 5.263 → 5.247 |
| 7 | front_end_mean_ms | -0.007997 | -0.903 | -0.900 | 13.566 → 13.396 |
| 7 | e2e_mean_ms | -1.287101 | -0.083 | 0.100 | 4,326.526 → 4,161.993 |

**판정:** 모든 K에 공통되는 체계적인 증가/감소 drift의 뚜렷한 근거는 없다. 21개 K×metric sequence 중 엄격히 단조인 sequence는 없다. 다만 K7 front-end의 감소 association(r≈−0.903, rho=−0.9)과 K4 E2E의 증가 association(r≈0.711, rho=0.9)은 있다. 따라서 “어떠한 drift도 없다”는 강한 주장은 하지 않는다. K6 run02의 큰 지연은 단조적인 시간 경향과 다르다.

Permutation p는 K별 n=5의 120 permutations, 공통 slope는 K 내부 10,000 permutations(random seed 20260910)로 계산한 **탐색적 수치**다. 다중 비교 보정이 없고 run exchangeability도 입증하지 않았으므로 confirmatory significance로 사용하지 않는다. K7의 큰 E2E scale이 공통 E2E residual 분석에 영향을 주므로 within-K 표를 함께 읽어야 한다. Clock/temperature trace가 없으므로 thermal throttling 원인 해석은 허용하지 않는다.

## 10. Preserved old Local baseline comparison

기존 `results/local_realtime_baseline/capacity_sweep_5rep/b1_sync/kK/runN/per_frame.csv` 35개를 읽어 run별 E2E mean/p95/miss를 재계산하고, 그 5개 값의 평균을 기존 `analysis/per_k_summary.csv`와 대조했다. 모두 일치한다. 아래 비교는 같은 방식의 mean-of-run-statistics다.

| K | Old→New E2E mean ms | Old→New p95 ms | Old→New miss % | Miss 차이 pp |
| --- | --- | --- | --- | --- |
| 1 | 21.111 → 22.267 | 23.090 → 24.297 | 0.133 → 0.178 | 0.044 |
| 2 | 19.521 → 19.356 | 23.583 → 23.333 | 0.217 → 0.339 | 0.122 |
| 3 | 19.639 → 20.014 | 24.495 → 24.574 | 0.441 → 0.563 | 0.122 |
| 4 | 22.324 → 22.931 | 29.153 → 29.636 | 0.797 → 0.850 | 0.053 |
| 5 | 25.371 → 25.730 | 33.336 → 33.822 | 4.998 → 4.907 | -0.091 |
| 6 | 38.878 → 43.621 | 144.745 → 109.433 | 32.178 → 35.048 | 2.870 |
| 7 | 4,500.395 → 4,294.064 | 7,465.567 → 7,213.384 | 100.000 → 100.000 | 0.000 |

**Qualitative trend reproduced: YES.** 두 실험 모두 K1–K4의 낮은 miss, K5의 약 5% miss와 deadline 경계 p95, K6의 큰 tail/miss, K7의 100% miss와 수초 latency를 보여 준다. K1→K2 평균 E2E 감소도 있어 “모든 인접 K에서 모든 metric이 단조 증가한다”는 주장은 하지 않는다.

수치는 동일하지 않다. K6 새 mean은 약 12.2% 증가하지만 p95는 약 24.4% 감소했고 miss는 2.870 percentage points 증가했다. 이는 qualitative reproduction과 양립하며, 모든 차이를 instrumentation overhead로 돌릴 수 없다.

**비교의 한계:** 동일 mapping, phase alignment, FPS/frame count, B/C, TRT runner, pipeline/preprocessing, warm-up 없음, rotation order라는 공통점이 있다. 그러나 기존은 perf_counter float timestamp이고 새 실험은 같은 underlying clock의 perf_counter_ns다. 기존 completion은 output-name validation 뒤에 sample되고 새 c는 infer 반환 직후다. 기존 ready 시각은 queue insertion 전이고 새 r는 enqueue 완료 event이며, 새 accounting lock/event bookkeeping도 존재한다. 동일 machine의 다른 시간에 실행했고, historical deliberate cooldown은 UNKNOWN인 반면 새 protocol은 NONE이다. 이러한 차이 때문에 bitwise equivalence 또는 통제된 instrumentation overhead estimate를 주장하지 않는다. 기존 총 arrival→completion backlog metric은 새 r→s waiting queue와 정의가 다르므로 queue 수치를 직접 비교하지 않는다.

## 11. Run-level variability: 모든 35개 run과 5-run statistics

아래 표는 요청한 9개 metric을 각 K의 5개 run에 대해 모두 제공한다. 단위는 latency ms, DMR %, queue peak frames다. Lag/FE/Wait/Service는 각각 run mean이다. Mean/SD/min/max 행은 5개 run statistic에 대한 값이다. 자세한 원본 정밀도는 [run_level_variability.csv](run_level_variability.csv)에 있다. SD는 run 간 산포이고 frame-level SD나 confidence interval이 아니다.

### K1

| Run/stat | E2E mean | p95 | p99 | DMR % | Lag | FE | Wait | Service | Q peak |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| run01 | 22.310 | 24.419 | 24.846 | 0.167 | 0.392 | 9.601 | 0.176 | 12.141 | 2.000 |
| run02 | 22.544 | 24.278 | 24.612 | 0.167 | 0.331 | 9.673 | 0.212 | 12.328 | 2.000 |
| run03 | 21.929 | 24.221 | 24.591 | 0.167 | 0.358 | 9.627 | 0.143 | 11.801 | 2.000 |
| run04 | 22.319 | 24.315 | 24.659 | 0.167 | 0.270 | 9.624 | 0.172 | 12.252 | 2.000 |
| run05 | 22.231 | 24.251 | 24.702 | 0.222 | 0.441 | 9.640 | 0.194 | 11.956 | 2.000 |
| mean | 22.267 | 24.297 | 24.682 | 0.178 | 0.359 | 9.633 | 0.179 | 12.096 | 2.000 |
| sample_std | 0.222 | 0.076 | 0.101 | 0.025 | 0.064 | 0.026 | 0.026 | 0.216 | 0.000 |
| min | 21.929 | 24.221 | 24.591 | 0.167 | 0.270 | 9.601 | 0.143 | 11.801 | 2.000 |
| max | 22.544 | 24.419 | 24.846 | 0.222 | 0.441 | 9.673 | 0.212 | 12.328 | 2.000 |

### K2

| Run/stat | E2E mean | p95 | p99 | DMR % | Lag | FE | Wait | Service | Q peak |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| run01 | 19.198 | 22.958 | 23.792 | 0.333 | 0.556 | 10.081 | 2.884 | 5.678 | 5.000 |
| run02 | 19.452 | 23.460 | 24.343 | 0.333 | 0.549 | 9.979 | 3.069 | 5.855 | 5.000 |
| run03 | 19.339 | 23.418 | 24.470 | 0.389 | 0.615 | 9.888 | 3.009 | 5.827 | 7.000 |
| run04 | 19.472 | 23.583 | 24.359 | 0.278 | 0.476 | 9.965 | 3.136 | 5.895 | 6.000 |
| run05 | 19.318 | 23.244 | 23.917 | 0.361 | 0.596 | 9.944 | 2.980 | 5.797 | 5.000 |
| mean | 19.356 | 23.333 | 24.176 | 0.339 | 0.558 | 9.972 | 3.015 | 5.811 | 5.600 |
| sample_std | 0.111 | 0.242 | 0.301 | 0.041 | 0.053 | 0.070 | 0.095 | 0.082 | 0.894 |
| min | 19.198 | 22.958 | 23.792 | 0.278 | 0.476 | 9.888 | 2.884 | 5.678 | 5.000 |
| max | 19.472 | 23.583 | 24.470 | 0.389 | 0.615 | 10.081 | 3.136 | 5.895 | 7.000 |

### K3

| Run/stat | E2E mean | p95 | p99 | DMR % | Lag | FE | Wait | Service | Q peak |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| run01 | 20.081 | 24.520 | 25.341 | 0.611 | 0.720 | 10.335 | 4.361 | 4.665 | 14.000 |
| run02 | 20.148 | 24.677 | 25.340 | 0.574 | 0.771 | 10.359 | 4.388 | 4.629 | 14.000 |
| run03 | 19.770 | 24.522 | 25.384 | 0.500 | 0.686 | 10.166 | 4.287 | 4.631 | 12.000 |
| run04 | 20.036 | 24.494 | 25.400 | 0.574 | 0.659 | 10.263 | 4.459 | 4.655 | 15.000 |
| run05 | 20.036 | 24.655 | 25.614 | 0.556 | 0.743 | 10.362 | 4.297 | 4.634 | 13.000 |
| mean | 20.014 | 24.574 | 25.416 | 0.563 | 0.716 | 10.297 | 4.358 | 4.643 | 13.600 |
| sample_std | 0.144 | 0.085 | 0.114 | 0.041 | 0.045 | 0.083 | 0.071 | 0.016 | 1.140 |
| min | 19.770 | 24.494 | 25.340 | 0.500 | 0.659 | 10.166 | 4.287 | 4.629 | 12.000 |
| max | 20.148 | 24.677 | 25.614 | 0.611 | 0.771 | 10.362 | 4.459 | 4.665 | 15.000 |

### K4

| Run/stat | E2E mean | p95 | p99 | DMR % | Lag | FE | Wait | Service | Q peak |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| run01 | 22.496 | 29.052 | 30.061 | 0.806 | 0.772 | 10.563 | 6.530 | 4.631 | 22.000 |
| run02 | 22.550 | 29.099 | 30.067 | 0.833 | 0.818 | 10.572 | 6.557 | 4.602 | 20.000 |
| run03 | 22.645 | 29.365 | 30.257 | 0.764 | 0.723 | 10.584 | 6.699 | 4.639 | 21.000 |
| run04 | 23.727 | 31.150 | 32.254 | 0.847 | 0.926 | 12.327 | 5.891 | 4.583 | 23.000 |
| run05 | 23.239 | 29.515 | 32.637 | 1.000 | 0.990 | 10.737 | 6.890 | 4.622 | 24.000 |
| mean | 22.931 | 29.636 | 31.055 | 0.850 | 0.846 | 10.957 | 6.513 | 4.615 | 22.000 |
| sample_std | 0.535 | 0.868 | 1.279 | 0.090 | 0.110 | 0.769 | 0.376 | 0.023 | 1.581 |
| min | 22.496 | 29.052 | 30.061 | 0.764 | 0.723 | 10.563 | 5.891 | 4.583 | 20.000 |
| max | 23.727 | 31.150 | 32.637 | 1.000 | 0.990 | 12.327 | 6.890 | 4.639 | 24.000 |

### K5

| Run/stat | E2E mean | p95 | p99 | DMR % | Lag | FE | Wait | Service | Q peak |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| run01 | 25.818 | 33.299 | 112.133 | 4.811 | 0.974 | 11.018 | 9.204 | 4.621 | 34.000 |
| run02 | 26.233 | 36.223 | 110.145 | 7.167 | 1.106 | 11.932 | 8.487 | 4.708 | 35.000 |
| run03 | 25.408 | 33.237 | 90.481 | 4.289 | 0.905 | 11.009 | 8.905 | 4.589 | 30.000 |
| run04 | 25.676 | 33.169 | 111.600 | 4.089 | 0.912 | 10.889 | 9.275 | 4.601 | 36.000 |
| run05 | 25.515 | 33.183 | 96.063 | 4.178 | 0.943 | 10.966 | 9.006 | 4.600 | 33.000 |
| mean | 25.730 | 33.822 | 104.084 | 4.907 | 0.968 | 11.163 | 8.975 | 4.624 | 33.600 |
| sample_std | 0.321 | 1.343 | 10.092 | 1.294 | 0.082 | 0.433 | 0.311 | 0.049 | 2.302 |
| min | 25.408 | 33.169 | 90.481 | 4.089 | 0.905 | 10.889 | 8.487 | 4.589 | 30.000 |
| max | 26.233 | 36.223 | 112.133 | 7.167 | 1.106 | 11.932 | 9.275 | 4.708 | 36.000 |

### K6

| Run/stat | E2E mean | p95 | p99 | DMR % | Lag | FE | Wait | Service | Q peak |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| run01 | 34.073 | 43.150 | 251.528 | 26.648 | 1.206 | 11.617 | 16.450 | 4.801 | 52.000 |
| run02 | 74.366 | 165.467 | 193.021 | 56.389 | 0.983 | 12.725 | 55.605 | 5.052 | 40.000 |
| run03 | 35.816 | 122.906 | 210.519 | 30.287 | 0.910 | 11.730 | 18.282 | 4.894 | 42.000 |
| run04 | 38.372 | 139.906 | 213.852 | 32.167 | 0.925 | 11.813 | 20.748 | 4.887 | 42.000 |
| run05 | 35.477 | 75.738 | 238.604 | 29.750 | 1.088 | 11.702 | 17.805 | 4.882 | 47.000 |
| mean | 43.621 | 109.433 | 221.505 | 35.048 | 1.022 | 11.917 | 25.778 | 4.903 | 44.600 |
| sample_std | 17.257 | 49.443 | 23.369 | 12.094 | 0.124 | 0.457 | 16.746 | 0.092 | 4.879 |
| min | 34.073 | 43.150 | 193.021 | 26.648 | 0.910 | 11.617 | 16.450 | 4.801 | 40.000 |
| max | 74.366 | 165.467 | 251.528 | 56.389 | 1.206 | 12.725 | 55.605 | 5.052 | 52.000 |

### K7

| Run/stat | E2E mean | p95 | p99 | DMR % | Lag | FE | Wait | Service | Q peak |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| run01 | 4,326.526 | 7,290.762 | 7,417.110 | 100.000 | 0.829 | 13.566 | 4,306.868 | 5.263 | 1,564.000 |
| run02 | 4,127.445 | 6,837.969 | 6,965.458 | 100.000 | 1.281 | 13.491 | 4,107.452 | 5.221 | 1,468.000 |
| run03 | 4,475.071 | 7,532.575 | 7,663.029 | 100.000 | 1.271 | 13.429 | 4,455.097 | 5.274 | 1,615.000 |
| run04 | 4,379.284 | 7,367.263 | 7,489.752 | 100.000 | 0.764 | 13.351 | 4,359.897 | 5.272 | 1,577.000 |
| run05 | 4,161.993 | 7,038.349 | 7,153.599 | 100.000 | 0.802 | 13.396 | 4,142.549 | 5.247 | 1,508.000 |
| mean | 4,294.064 | 7,213.384 | 7,337.789 | 100.000 | 0.989 | 13.446 | 4,274.372 | 5.255 | 1,546.400 |
| sample_std | 146.871 | 275.283 | 277.364 | 0.000 | 0.263 | 0.084 | 146.860 | 0.022 | 58.252 |
| min | 4,127.445 | 6,837.969 | 6,965.458 | 100.000 | 0.764 | 13.351 | 4,107.452 | 5.221 | 1,468.000 |
| max | 4,475.071 | 7,532.575 | 7,663.029 | 100.000 | 1.281 | 13.566 | 4,455.097 | 5.274 | 1,615.000 |

K6 E2E mean의 run 범위는 34.073–74.366 ms, sample SD는 17.257 ms다. Miss 범위는 26.648–56.389%, p95 범위는 43.150–165.467 ms다. K6 하나의 평균만 제시하면 실제 variability를 숨기므로 figure A/B와 이 표를 함께 사용해야 한다.

## 12. Paper-level questions와 지원되는 주장

**Q1 — Deadline transition은 어디서 시작하는가?** K5다. 평균 run p95 33.822 ms, miss 4.907%로 K4 p95 29.636 ms / miss 0.850%와 구분된다.

**Q2 — 명백한 overload는 어디부터인가?** Deadline failure라는 의미에서는 K6(35.048% miss)이 명백하다. 지속적인 backlog growth를 수반한 처리량 overload는 K7에서 명백하다. 두 의미를 분리해서 논문에 쓴다.

**Q3 — K6 miss/E2E 증가를 가장 많이 설명하는 latency component는?** Inference queue wait다. Mean 25.778 ms, mean E2E의 59.10%, K5→K6 mean E2E 증가의 93.92%를 차지한다. Miss에 대해서는 observed component sum의 진단과 service-rank gradient가 보조 근거이며 causal miss-reduction 비율을 추정하지 않았다.

**Q4 — K7 catastrophic latency와 연결되는 queue behavior는?** 60초 workload 동안 모든 run에서 지속적으로 누적되는 waiting backlog다. Mean last-enqueue depth 1,546.4 frames, mean wait 4,274.372 ms, E2E의 99.54%; 입력이 끝난 후에도 약 6.6–7.2초의 drain이 필요하다.

**Q5 — Average service reciprocal이 충분해 보여도 timing/queue 때문에 deadline을 놓칠 수 있다는 motivation을 지지하는가?** YES, K6가 직접적인 근거다. Offered 180 FPS, service mean 4.903 ms의 reciprocal 203.952 FPS인데 miss 35.048%다. Phase-aligned batch의 ready span mean 3.789 ms, 6개 직렬 service 합 mean 29.419 ms, front end mean 11.917 ms, queue carry-over 및 뒤쪽 service-rank miss가 동시에 관측된다. 이 reciprocal을 system capacity라고 부르지 않는 조건에서 주장이 성립한다.

논문에 사용할 수 있는 주장:

- 이 Local B=1/C=1 phase-aligned workload에서 deadline knee는 K5이며 K6에서 miss가 크게 증가한다.
- K5→K6 mean E2E 증가의 93.92%는 queue wait 증가이고, inference service mean 증가만으로 큰 E2E tail을 설명할 수 없다.
- K6의 평균 service reciprocal은 offered load보다 높지만 동시 arrival burst, 직렬 service, FE/service 변동과 carry-over가 관측되는 조건에서 35.048%의 frame이 candidate deadline을 놓친다.
- K7은 모든 run에서 workload 전 구간 waiting backlog가 누적되며 mean E2E의 99.54%가 inference queue wait다.
- 기존 Local baseline의 K5 knee / K6 심한 deadline 저하 / K7 catastrophic backlog라는 qualitative motivation은 재현되었다. DVFS/thermal causal mechanism 및 offloading 이득은 이 결과로 증명되지 않는다.

## 13. Figures와 산출물

**figure_A_e2e** — Mean and p95 are arithmetic means of five run statistics. Error bars: sample SD across five runs; small points: individual runs. Left log scale, right linear detail. Candidate deadline is not a final application SLA.

[PNG](figures/figure_A_e2e.png) · [PDF](figures/figure_A_e2e.pdf)

**figure_B_deadline_miss** — Mean of five run miss percentages with sample SD and individual-run points. Deadline uses exact raw-ns comparison e2e_ns × 30 > 1,000,000,000.

[PNG](figures/figure_B_deadline_miss.png) · [PDF](figures/figure_B_deadline_miss.pdf)

**figure_C_latency_decomposition** — Additive mean decomposition and component shares. K7 uses seconds on its own axis; K1–K6 use milliseconds. Shares are ratios of K-level component means to K-level E2E mean. Component percentiles are never added.

[PNG](figures/figure_C_latency_decomposition.png) · [PDF](figures/figure_C_latency_decomposition.pdf)

**figure_D_queue_metrics** — Means of five run queue metrics, sample SD, and individual runs. Q(t) counts r ≤ t < s and excludes service. Time-weighted integration: first through last ready enqueue; last-enqueue depth is immediately after that event. All panels log scale.

[PNG](figures/figure_D_queue_metrics.png) · [PDF](figures/figure_D_queue_metrics.pdf)

**figure_E_queue_depth_timeline** — Each line is one run; points are within-run means of frames in one-second logical-arrival bins, including startup. This is a frame-progression view, not an actual-time Q(t) integral; different runs are never concatenated. Independent panel y scales. Bin p95/max are also exported in queue_timeline_1s.csv.

[PNG](figures/figure_E_queue_depth_timeline.png) · [PDF](figures/figure_E_queue_depth_timeline.pdf)

**figure_F_queue_wait_timeline** — Each line is one run; points are within-run means of frames in one-second logical-arrival bins, including startup. This is a frame-progression view, not an actual-time Q(t) integral; different runs are never concatenated. Independent panel y scales. Bin p95/max are also exported in queue_timeline_1s.csv.

[PNG](figures/figure_F_queue_wait_timeline.png) · [PDF](figures/figure_F_queue_wait_timeline.pdf)

**figure_G_actual_queue_and_drain** — Exact time integral of Q(t) in each 100 ms actual-clock bin, divided by 100 ms, through drain. Event sequence is preserved and total area is checked against sum(s-r). Binning smooths brief peaks; exact peaks are in Figure D. Time means avoid phase aliasing from point-sampling every three 30-FPS ticks. Dashed line marks 60 s logical workload duration, not exact last enqueue. K7 accumulates backlog throughout the workload and drains afterward.

[PNG](figures/figure_G_actual_queue_and_drain.png) · [PDF](figures/figure_G_actual_queue_and_drain.pdf)

**figure_H_execution_order_drift** — Each run statistic minus its own K mean, against chronological position. Separate K lines avoid conflating load with time. E2E residual axis is symmetric log with linear threshold 1 ms. Descriptive time-order check; no thermal or DVFS causal inference.

[PNG](figures/figure_H_execution_order_drift.png) · [PDF](figures/figure_H_execution_order_drift.pdf)

필수 CSV/JSON: `formal_integrity_report.json`, `run_level_variability.csv`, `latency_decomposition.csv`, `deadline_knee_analysis.csv`, `order_drift_analysis.csv`, `baseline_comparison.csv`.

추가 근거: `queue_analysis.csv`(run queue metric 산포), `run_queue_diagnostics.csv`(burst/variation/carry-over), `queue_timeline_1s.csv`, `actual_waiting_queue_timeline_100ms.csv`, `actual_waiting_queue_bins_100ms.csv`, `within_tick_rank_analysis.csv`, `temporal_queue_summary.csv`, `component_change_analysis.csv`, `analysis_data.json`, `figure_manifest.json`. 분석 코드도 이 analysis directory에만 저장했다. 분석 script들은 기본적으로 existing analysis 출력에 대해 exclusive creation을 사용한다. `plot_analysis.py --replace-generated`는 이 작업에서 만든 figure 8개와 manifest만 다시 렌더링할 수 있다. Formal raw를 overwrite하는 경로는 없다.

입력 보존 근거는 `input_preservation_before.json`과 최종 `input_preservation_after.json`이다. Formal root 전체(기존 smoke 포함), old baseline 전체, scripts/configs snapshot의 SHA256·size·mtime 및 파일 집합을 비교한다. `repository_before.json` / `repository_after.json`에서 기존 uncommitted 상태가 보존되었는지 확인한다.

## 14. 다음 단계

**RT-DETR graph split feasibility analysis로 진행 가능: YES.** Local motivation의 deadline knee, queue bottleneck, finite-run backlog mechanism은 검증된 artifact와 수치로 정리되었다. 다음 단계에서 split 가능성/activation boundary를 검토할 근거는 충분하다. 그러나 이 분석이 partition/offloading 이득이나 특정 split point를 증명하지는 않는다. 그 판단에는 별도의 feasibility 및 비용 분석이 필요하다. 이번 작업에서는 graph partition 작업을 시작하지 않았다.

이번 task에서는 새 benchmark, GPU inference, raw/baseline/measurement code 변경, commit/push를 수행하지 않았다.

## 15. 최종 보존 검증

**PASS:** 작업 전 snapshot의 642개 파일 모두 SHA256, size, mtime_ns가 그대로다. Formal/smoke 401개 및 기존 baseline 224개 파일의 집합도 같다. Measurement 관련 16개 Python source와 formal order config 1개를 포함한다. Formal metadata에 기록된 source hash와 현재 source hash도 일치한다. Git HEAD/status는 작업 전과 동일하다. 분석 CSV/JSON 및 8개 figure의 PNG/PDF, 보고서 링크를 검증했다. 근거: [analysis_validation.json](analysis_validation.json), [input_preservation_after.json](input_preservation_after.json).
