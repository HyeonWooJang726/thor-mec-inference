# 공식 EfficientNetV2-S P0–P9 분할 정의

## 기준과 범위

2026-09-15 사용자 확정 정의를 [공식 manifest](../manifests/efficientnet_v2_s_p0_p9.json)에 기록했다. **G1–G9 및 P0–P9를 그대로 사용**하며 pooling과 flatten은 G8, dropout과 linear classifier는 G9에 속한다. 이전의 조건부 후보·flatten 위치 미정 상태를 대체한다.

Parecon이 공개한 9개 그룹·10개 분할점 구성을 참고하되, TorchVision EfficientNetV2-S에 대해 본 프로젝트가 명시적으로 정의한 재현 가능한 경계다. Parecon의 정확한 내부 구현 복제를 주장하지 않는다. Parecon 관련 근거는 사용자 제공 설명이며 원문 내부 구현을 독립 확인하지 않았다.

## 실제 P0–P9 매핑과 activation

CUDA FP32 `[1,3,384,384]` 입력으로 모든 경계의 shape를 실측했고 manifest의 예상값과 일치했다. 모든 dtype은 **torch.float32**다. bytes는 실제 tensor의 `numel() * element_size()`다.

| Point | 직전 모듈/연산 | 직후 모듈/연산 | Activation shape | numel | bytes | max_abs_diff | max_rel_diff |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: |
| P0 | `model input` | `model.features[0]` | `[1, 3, 384, 384]` | 442,368 | 1,769,472 | 0.0 | 0.0 |
| P1 | `model.features[0]` | `model.features[1]` | `[1, 24, 192, 192]` | 884,736 | 3,538,944 | 0.0 | 0.0 |
| P2 | `model.features[1]` | `model.features[2]` | `[1, 24, 192, 192]` | 884,736 | 3,538,944 | 0.0 | 0.0 |
| P3 | `model.features[2]` | `model.features[3]` | `[1, 48, 96, 96]` | 442,368 | 1,769,472 | 0.0 | 0.0 |
| P4 | `model.features[3]` | `model.features[4]` | `[1, 64, 48, 48]` | 147,456 | 589,824 | 0.0 | 0.0 |
| P5 | `model.features[4]` | `model.features[5]` | `[1, 128, 24, 24]` | 73,728 | 294,912 | 0.0 | 0.0 |
| P6 | `model.features[5]` | `model.features[6]` | `[1, 160, 24, 24]` | 92,160 | 368,640 | 0.0 | 0.0 |
| P7 | `model.features[6]` | `model.features[7]` | `[1, 256, 12, 12]` | 36,864 | 147,456 | 0.0 | 0.0 |
| P8 | `torch.flatten(x, 1)` | `model.classifier` | `[1, 1280]` | 1,280 | 5,120 | 0.0 | 0.0 |
| P9 | `model.classifier` | `model output` | `[1, 1000]` | 1,000 | 4,000 | 0.0 | 0.0 |

P1–P7은 각각 G1–G7 출력이다. P8은 `features[7] → avgpool → flatten`을 모두 통과한 **G8 출력이자 classifier 입력**이고, P9는 G9 최종 logits다. 원본 및 각 재결합 최종 출력은 모두 `[1,1000]`이다. 오차는 activation 자체가 아닌 원본 logits 대비 재결합 logits의 수치다. 중간 activation도 별도로 원본 forward 관찰값과 비교하여 통과했다.

## Prefix와 suffix

`EfficientNetV2SPartitions(model)`은 전달된 한 모델 인스턴스를 참조한다. `prefix(x, p)`는 G1–Gp, `suffix(activation, p)`는 G(p+1)–G9를 실행한다. P0 prefix와 P9 suffix는 identity이며 `partitions(x, p)`도 재결합 실행을 제공한다. 정수 0–9 외의 point는 거부한다.

| Point | Prefix (향후 Thor 범위) | Suffix (향후 Edge 범위) |
| --- | --- | --- |
| P0 | 없음: 전처리된 입력 | G1–G9 |
| P1 | G1 | G2–G9 |
| P2 | G1–G2 | G3–G9 |
| P3 | G1–G3 | G4–G9 |
| P4 | G1–G4 | G5–G9 |
| P5 | G1–G5 | G6–G9 |
| P6 | G1–G6 | G7–G9 |
| P7 | G1–G7 | G8–G9 |
| P8 | G1–G8 | G9 |
| P9 | G1–G9 | 없음: 최종 logits |

이번 검증은 두 범위를 같은 Thor CUDA 장치에서 연속 실행했다. Edge 전송·실행 결과가 아니다. 기존 complete-stage 경계만 사용하여 block 내부의 residual을 자르지 않는다.

## Tensor와 통신량 구분

`MiB = bytes / 1,048,576`, FP32 입력 대비 activation 비율은 `bytes / 1,769,472`다. **P9 activation은 4,000 bytes이며, P9 uplink는 0 bytes**다. 두 값을 혼동하지 않는다. P0–P8의 향후 logits downlink application payload는 FP32 `[1,1000]`일 때 4,000 bytes이며 P9에는 downlink가 없다. 실제 wire bytes, serialization, latency, throughput은 측정하지 않았다. activation 크기로 가장 빠른 분할점을 결정하지 않는다.

## 정확성 판정

모든 P0–P9는 `torch.testing.assert_close(rtol=1e-5, atol=1e-6)`를 통과했다. `max_rel_diff` 분모 floor는 `1e-8`이다. 고정 seed 0, `weights=None`, `eval()`, inference mode, 동일 모델/동일 입력 조건의 단일 CUDA FP32 검증이며 ImageNet accuracy 또는 성능 결과가 아니다. 실행 명령·모델 구조·환경 및 한계는 [모델 구조 문서](model_structure.md)에 기록했다.
