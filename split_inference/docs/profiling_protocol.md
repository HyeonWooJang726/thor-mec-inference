# 2단계 profiling protocol 및 결과 그림 설계

## 0. 상태와 범위

이 문서의 모든 측정 방법·반복 수·통계·색상은 **제안**이다. 성능 실측 결과는 없으며 실행 코드를 구현하지 않았다.
1단계 모델 구조 검증은 package 부재로 **BLOCKED**다. 구조·분할 경계 검증 완료와 사용자의 2단계 승인 이후에만 이 계획을 구현·실행한다.
Parecon 원문과 첨부 그림을 직접 확보하지 못했으므로 사용자 설명의 표현 목적만 반영했다.

## 1. 고정 조건과 재현 정보

- 모델: TorchVision EfficientNetV2-S, `EfficientNet_V2_S_Weights.IMAGENET1K_V1`, 입력 `[1,3,384,384]`, logits `[1,1000]`.
- batch size 1, FP32, `eval()`, `torch.inference_mode()`, baseline in-flight limit 1.
- Thor 1대 ↔ RTX 5070 Ti Edge 1대. 하드웨어 및 Edge 환경은 2단계에서 확인한다.
- activation은 FP32 lossless dense contiguous tensor로 전송한다. dtype·shape·layout·byte order·payload 길이·request ID를 명시한다.
- autocast, 임의 FP16 전환, INT8, activation JPEG, quantization, learned compression, channel pruning은 baseline에서 금지한다.
- 양쪽 weight hash와 group mapping을 동일하게 유지한다. CUDA kernel 선택 및 TF32 허용 설정을 기록하고 초기 FP32 비교에서는 TF32를 끄는 것을 제안한다. 환경 차이를 숨기지 않는다.
- software/version/driver/CUDA/cuDNN, GPU 종류·UUID·메모리, OS/JetPack, 모델 source path/hash, Git revision/dirty 상태, preprocessing, tensor layout, random seed를 run metadata에 남긴다.
- power mode, CPU/GPU/EMC clock 상태, 온도·부하·throttling·백그라운드 작업, 링크 종류·속도·MTU·전송 protocol·socket 설정·pinned memory·buffer reuse 여부를 기록한다. 사용자 승인 없이 system/power/clock/network 설정을 변경하지 않는다.
- 전처리 정의는 설치된 weight enum의 transforms에서 확인해 기록한다. 파일 read/decode/전처리·weight load·연결 수립은 steady-state E2E 밖에 두고 포함 여부를 metadata에 명시한다.
- 입력 resident 위치는 **Thor GPU FP32 contiguous tensor가 준비된 시점**으로 고정할 것을 제안한다. 전처리 output이 CPU에 있다면 최초 H2D는 사전 준비에 포함하고 전 point 동일하게 적용한다. CPU-ready를 연구 목표로 선택하면 별도 profile로 분리하고 최초 H2D 귀속을 다시 명시한다.
- 로그와 샘플 ID는 사전 할당하고 per-request disk flush의 영향을 피한다. instrumentation overhead는 승인된 2단계에서 별도 확인하고 처리시간에서 임의 차감하지 않는다.

## 2. 승인 후 수행 순서와 표본 설계

1. 환경·weight·class mapping·모델 분할 correctness를 확인한다. 실패 point의 성능은 유효 결과로 채택하지 않는다.
2. clock synchronization 가능 여부와 uncertainty를 조사한다. one-way 정확도가 불충분하면 아래 제한된 분해 방식을 사용한다.
3. group characterization, 각 partition을 직접 실행하는 E2E latency, 실제 throughput을 서로 식별되는 run 유형으로 측정한다.
4. 모든 point에 같은 이미지 순서·seed를 사용하며 point 실행 순서는 round별 무작위 또는 균형 순환으로 배치한다. 순서와 round ID를 보존한다.
5. 초기 제안은 조건당 **10개 독립 round**, 각 round·조건에서 **warm-up 100요청 후 최소 1,000개 측정 요청과 최소 60초 측정 시간**을 모두 만족할 때 종료한다. group characterization은 최소 1,000개 호출을 기본으로 하고 실행시간과 안정성을 함께 기록한다.
6. 2단계 pilot에서 안정성이 부족하면 횟수·기간을 사전에 수정해 전체 조건에 동일 적용한다. 보고할 결과를 본 뒤 유리한 조건만 늘리지 않는다. warm-up 표본은 별도 phase로 보존한다.
7. 이미지 decode는 measurement 밖에서 준비하며 GPU 메모리에 데이터 전체를 무조건 상주시켜 메모리 조건을 바꾸지 않는다. 동일한 입력 공급·buffer 정책을 양 endpoint에 적용한다.

위 횟수는 실행된 값이 아니다. 표준 run metadata에 planned/actual warm-up, attempted/successful/failed count, duration을 모두 남긴다.
환경·clock·동시 부하가 달라진 run은 구분하고 무단 삭제하지 않는다.

## 3. Group-level characterization

각 검증된 group을 Thor와 Edge에서 각각 측정한다.

- 전체 모델에서 얻은 대표적인 **실제 group 입력 activation**을 타이밍 밖에서 준비하고 입력 shape/dtype/bytes를 기록한다. 무작위 tensor로 대체하면 별도 provenance를 명시한다.
- group의 모든 연산이 포함되도록 CUDA event 시작/종료를 같은 stream에 넣는다. 측정 입력은 GPU-ready이며 group 출력이 GPU-ready가 될 때까지 측정한다.
- warm-up 이후 event를 기록하고 종료 event를 synchronize한 뒤 elapsed time을 읽는다. cross-stream 작업이 있다면 종료 event가 모든 의존성을 기다리게 한다.
- group 입력 준비·H2D·직렬화·network·다른 group의 연산을 group event 시간에 넣지 않는다. CUDA event 구간과 별도의 host 관찰 구간이 있다면 이름을 구분한다.
- group마다 input/output shape, elements, FP32 bytes/MiB, output/model-input bytes 비율을 기록한다.
- 처리시간 mean, median, sample standard deviation, p95, p99, mean의 95% CI, 표본 수와 실패 수를 저장한다.

Group 시간은 모델 계산 분포를 설명하는 characterization이다. **group median 또는 mean의 합으로 실제 partition latency를 만들지 않는다.**
각 partition에서 Thor에 배치된 연속 group 전체와 Edge에 배치된 나머지 group 전체를 각각 직접 실행하여 별도로 측정한다.
cache·allocation·launch·fusion 조건 차이 때문에 group 분리 실행과 partition 실행을 동등하다고 가정하지 않는다.

## 4. Partition E2E 경계: 중복 없는 네 구간

### 4.1 관찰 이벤트 — 제안

| 이벤트 | 장치 | 완료 조건 |
| --- | --- | --- |
| A | Thor | 전처리 및 사전 준비 완료, GPU 입력 tensor ready; 요청 timer 시작 |
| B | Thor | 해당 point까지 직접 실행 완료, 전송할 activation GPU-ready |
| C | Edge | 수신·복원·H2D 완료, 해당 point 이후 실행할 GPU 입력 ready |
| D | Edge | 나머지 group 실행 완료, FP32 logits GPU-ready |
| E | Thor | logits 수신·복원 완료, 호출자가 읽을 수 있는 CPU contiguous FP32 `[1,1000]` 준비 |

초기 baseline의 최종 결과 소비 위치는 **Thor CPU**로 명시할 것을 제안한다. 모든 point에서 동일하다.
GPU 결과를 소비하는 연구 조건을 선택하면 별도 설정으로 정의하고 E 경계에 필요한 transfer를 반영한다.
GPU readiness는 CUDA event 완료를 적절히 synchronize한 host 관찰 지점으로 기록한다. GPU event와 host clock 사이 정밀 대응 오차 및 host wake-up 지연도 계측 한계에 남긴다.

| 구성요소 | 구간 | 포함 내용 |
| --- | --- | --- |
| Thor processing | A → B | Thor partition 실행 및 해당 host orchestration·GPU 완료 대기 |
| Uplink transmission | B → C | D2H, lossless 직렬화, header, 송수신·queue, 복원, Edge H2D, 입력 준비 대기 |
| Edge processing | C → D | Edge partition 실행 및 해당 host orchestration·GPU 완료 대기 |
| Downlink transmission | D → E | logits D2H, 직렬화, 송수신, Thor 복원·소비 준비 |

전송 구간은 GPU-ready에서 다음 소비 위치 ready까지의 **전송 경로 전체 시간**이며 NIC만의 전송시간이 아니다.
pure wire time을 별도로 계측하면 이름과 포함 범위를 구분한다. application payload bytes, 실제 wire bytes, header/재전송 bytes는 분리한다.
single-in-flight baseline에서는 해당 요청의 네 구간을 겹치지 않게 구성한다.

\[
T_{E2E,observed}=E_{Thor,mono}-A_{Thor,mono}
\]
\[
T_{E2E,components}=T_{Thor}+T_{Uplink}+T_{Edge}+T_{Downlink}
\]

CUDA event elapsed time은 GPU 실행 보조 지표(`thor_cuda_ms`, `edge_cuda_ms`)로 저장한다.
네 구성요소의 processing 필드는 정의한 host 경계 구간이며 순수 CUDA event elapsed time과 같다고 강제하지 않는다.
이를 바꾸어 사용하면 host orchestration·launch·sync 비용이 빠질 수 있다. E2E 전체는 Thor `monotonic_ns` 기반으로 독립 관찰한다.

### 4.2 Endpoint 예외

- **P0 Edge-only:** B=A, Thor processing=0. 준비된 입력 tensor를 전송한다. Uplink, Edge processing, downlink는 실제 존재한다. preprocessing 시간은 제외한다.
- **P9 Thor-only(9-group 확정 시):** Edge 및 uplink/downlink=0. Thor processing=A→E이며 모든 group 실행과 마지막 로컬 logits D2H·소비 준비를 포함한다. 이 endpoint에서는 GPU logits-ready만으로 timer를 끝내지 않는다. `thor_cuda_ms`는 순수 GPU 시간으로 별도 기록한다.
- component 값의 0은 실제 부재한 구간에만 사용한다. clock 정보 부재나 측정 실패는 null로 저장한다.

### 4.3 Clock 동기화와 one-way 제한

Thor/Edge monotonic clock 원시값은 서로 직접 뺄 수 없다.
PTP 또는 검증된 synchronization의 공통 timebase에 대응하는 **각 호스트 clock mapping**을 구하고 offset·drift·uncertainty를 기록해야 C−B와 E−D를 one-way 시간으로 사용할 수 있다.
E2E duration은 계속 Thor monotonic clock으로 측정한다. 각 sample 또는 짧은 구간에 monotonic↔공통 clock mapping ID를 연결한다.

- run 전후 및 측정 중 clock offset(ns), uncertainty(ns), drift, sync 방식, 검증 시각과 clock source를 보존한다. 단지 동기화 서비스가 켜졌다는 이유로 정확하다고 판단하지 않는다.
- **제안 판정 기준:** 검증된 one-way uncertainty가 해당 구간 대표 시간의 5% 이하일 때 주 one-way 결과로 사용하고 절대 오차도 함께 표시한다. 기준 미달이면 미검증 분해로 표시한다. 음수 시간은 0으로 clip하지 않고 offset·mapping 오류를 조사한다.
- sync가 없으면 host별 local duration과 observed E2E만 신뢰하고 uplink/downlink one-way 필드는 null로 둔다. 해당 필드를 실측으로 주장하지 않는다.
- residual을 쓸 경우 `communication_residual_ms = e2e_observed_ms - thor_processing_ms - edge_processing_ms`로 **양방향 통합 잔여시간**을 별도 저장한다. synchronization·orchestration 누락도 포함할 수 있고 독립 전송 측정이 아님을 명시한다. 1/2씩 나누어 one-way로 해석하지 않는다.
- residual의 오차는 E2E와 local 구간의 timestamp 불확실성 및 drift에서 전파해 기록한다. 보수적 오차 한계는 각 duration 한계의 합으로 제시하고 residual이 음수이면 조사한다.
- payload/bandwidth 모델을 쓰면 `estimated transmission`으로 별도 데이터·그림에 표시한다. latency intercept, effective bandwidth의 근거와 단위, copy·직렬화 포함 여부, 오차를 공개한다. 실측 component 칸을 추정값으로 채우지 않는다.

### 4.4 Accounting 검증

\[
\Delta_{accounting}=T_{E2E,observed}-(T_{Thor}+T_{Uplink}+T_{Edge}+T_{Downlink})
\]

네 구간이 모두 관찰된 동일 요청에서 계산한다. missing component 요청은 component summary에서 제외 사유와 개수를 공개하고 observed E2E는 보존한다.
Δ의 mean, median, p95, max absolute, sample count와 계측 uncertainty를 보고한다.
round별 Δ의 95% CI가 0을 벗어나고 계측 uncertainty보다 큰지 확인하며, 개별 `abs(Δ)`가 uncertainty와 E2E의 1% 중 큰 값보다 큰 요청을 조사 대상으로 표시할 것을 제안한다. raw 삭제나 임의 재배분은 하지 않는다.
원인은 orchestration, synchronization, clock drift, 계측 누락 등을 확인한다.
동일 timestamp를 단순히 망원합으로 더하면 Δ≈0이 대수적으로 강제되므로 그것만으로 계측 정확성을 증명하지 않는다. 별도 outer E2E timer와 CUDA event 보조 지표로 누락을 점검한다.
residual을 component로 정의한 경우 Δ가 구성상 0에 가까워지므로 **독립 accounting 검증 불가**로 표시한다.

## 5. 실제 처리량

\[
\mathrm{Throughput}(p)=\frac{N_{successful\ completions}}{measurement\ wall\ time\ (s)}
\]

- 초기 baseline은 batch size=1, inflight limit=1, 이전 요청 완료 후 다음 요청을 제출하는 closed-loop다. offered-load 방식은 `closed_loop_no_think_time`으로 기록한다.
- 실제 admitted/attempted 요청 수를 wall time으로 나눈 offered rate도 저장한다. 일정 목표 fps가 있는 open-loop는 별도 실험으로 분리한다.
- warm-up 요청은 완료까지 배출한 후 measurement를 시작한다. t_start는 첫 측정 요청 제출 직전, t_end는 마지막 측정 요청 완료/실패 확정 직후로 정의한다. 마지막 요청 배출 시간도 duration에 포함한다.
- 성공 완료만 numerator에 넣되 실패·timeout 대기와 요청 사이 orchestration은 denominator에서 제거하지 않는다. deadline/timeout/retry policy를 고정하고, 재시도는 시도 ID를 따로 기록해 중복 완료를 세지 않는다.
- 각 round에 batch size, inflight limit, offered-load mode/target/observed, warm-up 수, measurement attempted 수, wall time, successful completion 수, failure 수, timeout 수를 기록한다.
- `1000 / mean latency(ms)`는 실측 처리량으로 쓰지 않는다. 순차 실행에서도 요청 사이 overhead가 있어 차이가 날 수 있다.
- round별 실측 fps의 mean 및 95% CI를 Figure 2(a)에 표시한다. 보조 표에는 전체 completed / 전체 wall time의 pooled rate를 구분해 제공한다.
- pipelining, 여러 in-flight 요청, batch 증가, 여러 Thor는 별도 실험이며 초기 baseline과 섞지 않는다. 동시성 실험에서는 request latency 구간·queue 및 전체 makespan 관계를 다시 정의한다.

## 6. Raw CSV와 집계 규칙

모든 반복 원시값을 `results/profiling/raw/`에 보존하고 Git에서는 제외한다. warm-up, 실패, outlier를 삭제하지 않는다.

### 6.1 요청/group CSV

요청된 기본 필드를 그대로 유지한다.

```text
run_id,sample_id,partition_point,group_id,device,batch_size,inflight_limit,payload_bytes,thor_processing_ms,uplink_transmission_ms,edge_processing_ms,downlink_transmission_ms,e2e_observed_ms,e2e_component_sum_ms,completion_timestamp,success,error_type
```

추가 제안 필드:

```text
schema_version,record_type,round_id,phase,image_id,attempt_id,input_shape,output_shape,input_bytes,output_bytes,output_input_ratio,dtype,group_processing_ms,thor_cuda_ms,edge_cuda_ms,downlink_payload_bytes,wire_uplink_bytes,wire_downlink_bytes,a_thor_mono_ns,b_thor_mono_ns,c_edge_mono_ns,d_edge_mono_ns,e_thor_mono_ns,clock_mapping_id,clock_offset_ns,clock_uncertainty_ns,transmission_provenance,communication_residual_ms,accounting_delta_ms
```

`record_type`는 group/partition을 구분한다. group 행의 partition_point 및 E2E 관련 필드는 null, partition 행의 group_id는 null로 둔다. group 시간은 `group_processing_ms`에 저장한다.
`completion_timestamp`는 Thor monotonic ns로 정의하고 clock domain/단위를 metadata에 명시한다. UTC timestamp가 필요하면 별도 필드에 저장한다.
payload_bytes는 **uplink application tensor bytes**다. P9=0, logits 크기는 별도 output/downlink 필드로 구분한다.
각 host timestamp는 원래 clock domain으로 저장하고 공통 clock 변환식·anchor를 sidecar metadata에 보존한다.
통신 provenance는 `measured_synchronized`, `unavailable`, `residual_combined`, `estimated`를 구분한다.
성공 여부와 구성요소 유효 여부는 별개로 관리한다. 통신 분해 실패가 성공한 E2E 요청을 없애지 않게 한다.

### 6.2 Run CSV 및 summary

run CSV에는 `run_id,round_id,partition_point,batch_size,inflight_limit,offered_load_mode,offered_target_fps,offered_observed_fps,warmup_count,measurement_attempted_count,completion_count,failure_count,timeout_count,measurement_start_mono_ns,measurement_end_mono_ns,measurement_wall_s,throughput_fps`와 환경 metadata 경로를 기록한다.

각 group/partition/metric summary에는 다음을 포함한다.

- mean, median, sample standard deviation(`ddof=1`), p95, p99.
- mean의 95% CI lower/upper, CI method, resampling seed, rounds, valid sample count, failure count, missing metric count.
- quantile 방식은 linear interpolation으로 고정하고 분석 library/version을 저장한다. 작은 n의 tail 추정은 불안정함을 표에 표시한다.
- latency mean/quantile은 성공한 실제 sample에서 계산하고 실패율을 나란히 보고한다. timeout을 가장 빠른 값으로 대체하거나 조용히 삭제하지 않는다.
- 평균 CI는 **독립 round를 cluster 단위로 재표집하는 bootstrap 10,000회**를 제안한다. round 내 sample을 독립 표본처럼 무조건 재표집하지 않는다. unequal run 길이일 때 sample-weighted latency mean이라는 estimand를 명시하고 각 bootstrap에서도 같은 규칙을 사용한다.
- throughput CI는 round별 fps 평균에 대해 round bootstrap으로 구한다. 반복 독립성·환경 안정성 한계를 공개한다. p95/p99 자체의 CI가 필요하면 round cluster bootstrap에서 quantile을 다시 계산한다.
- 오류 막대는 표준편차나 p95가 아니라 **mean의 95% CI**다. SD/median/p95/p99는 별도 열에 둔다.

stacked bar는 동일한 complete-case 요청 집합의 **component mean 합**이다. 이 집합의 observed E2E와 accounting을 대조하고 전체 성공 sample 결과와 집합 차이를 공개한다.
median E2E는 원시 E2E 표본의 median, p95는 원시 E2E 표본의 p95다. component median/p95를 합산한 값을 사용하지 않는다.

## 7. 분할 정확성 계획

동일 입력·weight·eval 설정으로 각 point에서 다음을 비교한다.

1. 원본 TorchVision 모델 logits.
2. 동일 장치에서 해당 point로 나누어 연속 실행한 logits(Thor 및 Edge 각각).
3. FP32 tensor 직렬화·복원 후 같은 장치 분할 logits.
4. 실제 Thor–Edge 전송 후 분할 logits.

원본 실행 위치를 명시하고 각 장치 원본 간 수치 차이도 별도로 보고한다. Thor 원본을 cross-device 기준으로 제안한다.
동일 장치 직렬화 전후 activation의 dtype/shape/길이 및 **byte equality**를 확인한다. logits 수치 tolerance와 lossless 전송의 byte equality를 혼동하지 않는다.

원본 logits z, 비교 logits z'에 대해:

- `max_abs_error = max(abs(z' - z))`.
- `max_relative_error = max(abs(z' - z) / max(abs(z), epsilon))`, 제안 `epsilon=1e-8`; 분모 floor와 logits scale 민감도를 caption에 명시한다.
- top-1 일치율: 두 logits의 argmax class가 같은 입력 비율.
- top-5 일치율: **top-5 class 집합이 완전히 같은 입력 비율**로 정의한다(순서 무시). 교집합 개수/5 평균은 필요하면 별도 이름으로 보고한다. tie-breaking은 class index 기준으로 고정한다.
- sample별 값을 보존하고 point별 최대 오차, error 분포, top-1/top-5 비율과 분모 n, 실패 수를 제공한다. 이 값들은 ground-truth ImageNet accuracy와 구분한다.

제안 사전 numerical 기준은 동일 장치 `atol=1e-6, rtol=1e-5`, cross-device FP32 `atol=1e-4, rtol=1e-4`의 elementwise `abs(z'-z) <= atol + rtol*abs(z)`다. 실제 검증 기준은 승인된 pilot 전에 확정하고 사후 조용히 완화하지 않는다.
top-1/top-5 불일치는 작은 오차에 의한 근접 class 순위 변동일 수도 있으므로 margin과 입력 ID를 함께 조사한다.
NaN/Inf, shape/dtype 오류, payload 불일치는 즉시 실패다. 모든 point correctness를 통과하기 전 해당 성능 결과를 최종 비교에 넣지 않는다.
2단계 초기 correctness subset은 고정 seed의 class별 1장(1,000장)을 제안하고, 최종 분할 정확성은 승인된 ImageNet validation 50,000장 전체에서 확인한다. timing·accuracy run은 분리한다.
전처리 및 synset→class index 대응이 확인되기 전 top-1/top-5 ground-truth accuracy를 주장하지 않는다.

## 8. 최종 그림 설계

모든 그림은 구조 확정 후 고정한 point 순서(P0…마지막 point)를 사용한다. 모든 point 축에는 `P0 Edge-only`, `P1 Stem 이후`처럼 **번호와 의미**를 함께 표시하고 마지막에 `Thor-only`를 명시한다.
group panel은 G1…G9 순서, boundary panel은 B0 입력 및 G1…G9 출력 순서로 맞춘다. G9 출력은 uplink가 아니라 최종 logits라고 명시한다.

### 색상 — 제안

Okabe–Ito 계열의 다음 색상과 hatch/marker를 일관되게 사용한다. 노랑에는 어두운 테두리를 넣어 흰 배경 가독성을 확보한다.

| 의미 | 색상 | 추가 구분 |
| --- | --- | --- |
| Thor processing | 파랑 `#0072B2` | solid |
| Uplink transmission | 주황 `#E69F00` | `/` hatch |
| Edge processing | 노랑 `#F0E442` | 어두운 테두리 |
| Downlink transmission | 보라 `#CC79A7` | `\\` hatch |
| p95/tail | 검정 `#000000` | diamond |

장치·구성요소 의미가 없는 activation/throughput/accuracy는 중립 회색을 사용한다. mean/median/p95는 marker 모양과 선 종류로도 구분해 색만으로 판독하지 않게 한다.

### Figure 1: Layer-group 특성 — 정렬된 3패널

- **1(a) Group processing time**: x=group, y=`Processing time (ms)`; Thor/Edge grouped **mean** bar + mean 95% CI error bar. median/p95는 보조 표로 제공한다.
- **1(b) Boundary activation size**: x=boundary, y=`FP32 activation size (MiB)`; 입력 1.6875 MiB 수평선. 산술 크기는 실측 latency와 구분하고 error bar를 붙이지 않는다.
- **1(c) Activation-size ratio**: x=동일 boundary, y=`Activation / input bytes (ratio)`; ratio=1 기준선. 1 초과는 입력보다 큰 activation, 1 미만은 작은 activation이다.
- 이중 y축을 쓰지 않는다. 입력 boundary는 size/ratio 패널에만 추가하고 group 출력 위치는 맞춘다.

### Figure 2: 실제 partition 성능 — 3패널

- **2(a) Processed throughput**: x=point, y=`Processed throughput (frames/s)`; 실제 round별 completed/wall-time fps의 mean + 95% CI. batch 1, inflight 1을 caption에 명시한다.
- **2(b) E2E latency breakdown**: x=point, y=`E2E latency (ms)`; Thor/uplink/Edge/downlink **component mean** stacked bar; 직접 측정한 E2E p95를 검정 diamond로 표시한다. 최저 **observed mean E2E** point는 별표 또는 테두리, 최저 observed p95가 다르면 다른 표시로 구분한다. stack과 observed mean의 차이는 accounting delta 표 및 필요시 observed mean marker로 드러낸다.
- 동기화가 없어 four-way one-way 분해가 성립하지 않으면 요청된 핵심 4색 Figure 2(b)는 **생성 보류**한다. 별도 figure에 observed E2E와 local processing/양방향 통합 residual을 명확히 표기할 수 있지만 핵심 four-way 실측 그림으로 대신 제시하지 않는다.
- **2(c) Tail latency**: x=point, y=`E2E latency (ms)`; observed mean(circle), median(square), p95(검정 diamond) 선/점으로 표시한다. 모든 quantile은 직접 E2E sample에서 계산한다.
- 최적 point 선정은 observed mean과 p95를 각각 구분한다. CI가 겹치거나 차이가 작으면 통계적 우월성을 단정하지 않는다. 실패율과 accounting 유효성도 함께 제시한다.

### Figure 3: 분할 정확성 — 성능과 별도

- x=point, y는 각각 max absolute logit error, max relative logit error, top-1 agreement(%), top-5 set agreement(%)로 분리한 4패널 또는 표.
- 동일 장치/직렬화/장치 간 전송 비교를 별도 열 또는 marker로 구분한다. 장치 원본 비교 위치와 epsilon을 명시한다.
- 0 error를 임의 양수로 바꿔 log 축에 넣지 않는다. 필요하면 symlog 또는 0을 표시할 수 있는 선형 축을 사용한다.
- 정확성 sample 수, 실패 수, aggregation(전체 sample/class의 최대값인지 sample별 통계인지)을 caption에 명시한다.

### 표, caption, 파일

최종 표는 (1)환경·실행 조건, (2)group mean/median/SD/p95/p99/CI와 tensor, (3)partition E2E·components·fps·accounting·실패, (4)correctness로 구성한다.
caption마다 n(요청 수), 독립 rounds 수, warm-up, precision, batch/inflight, error bar=mean 95% CI 및 bootstrap 방법, 전송 provenance와 clock uncertainty를 넣는다.
최적화 기준(mean 또는 p95), 단위, endpoint 이름을 그림만 읽어도 알 수 있게 한다. 의미 없는 3D와 이중 y축은 사용하지 않는다.
PNG 최소 **300 DPI**와 벡터 **PDF 또는 SVG**를 함께 저장하고 크기·font·palette·label mapping을 설정으로 고정한다.
향후 `scripts/`의 별도 분석·그림 생성 코드가 같은 summary CSV에서 재생성하도록 한다. figure manifest에 CSV hash/분석 revision/seed 및 출력 이름을 연결한다.
현재 raw 값이 없으므로 그래프 파일이나 가상 성능 수치는 만들지 않는다.

## 9. 남은 검증과 단계 종료

- 미확인: 실제 설치본 구조, 안전한 group/block 경계, P1–P8 shape·bytes, pooling/flatten 위치, 기대 logits shape의 실행 확인.
- 미확인: 사용할 Python/컨테이너, Thor의 PyTorch CUDA 호환성, Edge 환경, 공식 weight/전처리·class index mapping.
- 미확인: 실제 연결·전송 overhead·clock synchronization과 uncertainty, 성능·처리량·분할 정확성.
- 미확인: Parecon 원문 group 정의·수치 및 참고 그림 지표의 원문 정의.

1단계 보고 후 중단한다. 기존 환경 정보가 확보되더라도 먼저 1단계 구조 검증을 완료해야 하며, 사용자 승인 없이 2단계를 시작하지 않는다.
