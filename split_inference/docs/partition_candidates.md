# Layer group과 partition 후보

## 상태와 판정

**미확인 / BLOCKED:** PyTorch·TorchVision 부재로 실제 group 경로, block 수, residual 범위, activation shape를 검증하지 못했다.
9-group 구성은 사용자 제시안이며 타당성이 확인된 구성이 아니다. 임의로 결합·분리·채택하지 않는다.
아래 P0–P9는 **9-group이 검증되는 경우의 조건부 설계**다. 실제 group 수가 바뀌면 point 수와 번호도 함께 수정한다.

## 초기 본 실험 후보 표 — 제안, 채택 보류

| Point | Thor processing 범위 | Edge processing 범위 | Uplink tensor | FP32 MiB | 입력 대비 비율 | 경계 안전성 | 초기 후보 |
| ----: | ------------------ | ------------------ | ------------- | -------: | -------: | ------ | ----- |
| 0 — Edge-only | 전처리만, 모델 group 없음 | G1–G9 | 지정 입력 `[1,3,384,384]` | 1.687500 | 1.000000 | 모델 내부를 자르지 않는 설계; 실행 미검증 | 제안: endpoint baseline |
| 1 — Stem 이후 | G1 | G2–G9 | 미확인 | 미확인 | 미확인 | 미확인 | 보류 |
| 2 — Fused stage 1 이후 | G1–G2 | G3–G9 | 미확인 | 미확인 | 미확인 | 미확인 | 보류 |
| 3 — Fused stage 2 이후 | G1–G3 | G4–G9 | 미확인 | 미확인 | 미확인 | 미확인 | 보류 |
| 4 — Fused stage 3 이후 | G1–G4 | G5–G9 | 미확인 | 미확인 | 미확인 | 미확인 | 보류 |
| 5 — MB stage 4 이후 | G1–G5 | G6–G9 | 미확인 | 미확인 | 미확인 | 미확인 | 보류 |
| 6 — MB stage 5 이후 | G1–G6 | G7–G9 | 미확인 | 미확인 | 미확인 | 미확인 | 보류 |
| 7 — MB stage 6 이후 | G1–G7 | G8–G9 | 미확인 | 미확인 | 미확인 | 미확인 | 보류 |
| 8 — Pooling 이후 | G1–G8 | G9 | 미확인 (flatten 위치 확인 필요) | 미확인 | 미확인 | 미확인 | 보류 |
| 9 — Thor-only | G1–G9 | 없음 | 없음, uplink 0 bytes | 0 | 해당 없음: 통신 없음 | 모델 내부를 자르지 않는 설계; 실행 미검증 | 제안: endpoint baseline |

P8의 flatten 소유 group은 실제 forward를 읽은 뒤 확정한다. 한 연산이 빠지거나 중복되지 않게 한다.
P9의 **uplink 0**과 **최종 출력 activation 4,000 bytes**는 서로 다른 양이다. activation 비율을 0으로 보고하지 않는다.
P0의 입력 shape와 logits shape는 사용자 지정 조건이고, 모델 forward 확인값은 아니다.

## Tensor byte 계산

**확인됨(지정 shape의 산술 계산):** `MiB = bytes / 1,048,576`.
원소 수 `N = product(shape)`, FP32 `4N` bytes, 참고 FP16 `2N` bytes다.

\[
R_{\mathrm{activation}}(p)=\frac{\text{FP32 boundary activation bytes}(p)}{1,769,472}
\]

| Point/출력 | Thor 마지막 group | Edge 첫 group | 경계 activation shape | 원소 수 | FP32 bytes | FP32 MiB | 참고 FP16 bytes | 참고 FP16 MiB | FP32 입력 대비 비율 | 구현 가능성 |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| P0 | 없음 | G1 | `[1,3,384,384]` 지정 | 442,368 | 1,769,472 | 1.687500 | 884,736 | 0.843750 | 1.000000 | 제안: 입력 전송; 미실행 |
| P1 | G1 | G2 | 미확인 | 미확인 | 미확인 | 미확인 | 미확인 | 미확인 | 미확인 | 검증 보류 |
| P2 | G2 | G3 | 미확인 | 미확인 | 미확인 | 미확인 | 미확인 | 미확인 | 미확인 | 검증 보류 |
| P3 | G3 | G4 | 미확인 | 미확인 | 미확인 | 미확인 | 미확인 | 미확인 | 미확인 | 검증 보류 |
| P4 | G4 | G5 | 미확인 | 미확인 | 미확인 | 미확인 | 미확인 | 미확인 | 미확인 | 검증 보류 |
| P5 | G5 | G6 | 미확인 | 미확인 | 미확인 | 미확인 | 미확인 | 미확인 | 미확인 | 검증 보류 |
| P6 | G6 | G7 | 미확인 | 미확인 | 미확인 | 미확인 | 미확인 | 미확인 | 미확인 | 검증 보류 |
| P7 | G7 | G8 | 미확인 | 미확인 | 미확인 | 미확인 | 미확인 | 미확인 | 미확인 | 검증 보류 |
| P8 | G8 | G9 | 미확인 | 미확인 | 미확인 | 미확인 | 미확인 | 미확인 | 미확인 | 검증 보류 |
| P9 최종 출력 | G9 | 없음 | `[1,1000]` 기대값 | 1,000 | 4,000 | 0.0038146973 | 2,000 | 0.0019073486 | 0.0022605613 | 제안: 로컬 반환; 미실행 |

마지막 행은 P9 **최종 출력**의 이론적 크기다. P0–P8도 기대 logits가 FP32 `[1,1000]`이면 각 요청 downlink application payload는 4,000 bytes다. P9는 downlink가 없다.
직렬화 header·protocol framing·재전송 등 실제 wire bytes는 별도 측정해야 한다. 표의 activation payload와 같다고 가정하지 않는다.
FP16 열은 저장 크기 비교용 산술값이며 dtype 변환·실험을 수행하지 않았다. 비율은 FP32끼리 계산한다.

구조 검증이 가능해지면 표의 모든 중간 행에 shape/원소 수/두 precision의 bytes·MiB/비율을 채우고, 실제 module 경로와 residual 판정 근거를 연결한다.
현재 0으로 채우거나 일반적인 EfficientNetV2-S 표를 대체 근거로 사용하지 않는다.

## Stage/group 경계와 block 경계

| 구분 | 초기 용도 | 확인할 조건 | 현재 상태 |
| --- | --- | --- | --- |
| 완전한 stage/group 이후 | 제안: 본 실험 비교 | 모든 residual이 경계 이전에 합쳐짐, 한 tensor로 다음 group 실행 가능 | 미확인 |
| 완전한 MBConv/FusedMBConv block 이후 | 제안: 최적 stage 주변 등 세부 진단만 | block의 모든 branch와 residual 더하기 종료, 외부 skip 없음 | 미확인; 개수도 미확정 |
| block 내부 연산 이후 | 초기 후보 제외 | 추가 skip/SE branch 상태가 필요할 수 있음 | 안전하다고 가정하지 않음 |

각 block이 단일 입력·출력이며 skip이 내부에서 완결되는 구현이면 block 이후도 기술적으로 안전하다. 이는 **조건부 설계 원칙**이며 현재 설치본에서 확인된 사실이 아니다.
stage 후보가 검증된 후 그 경계를 포함한 P0–P9 전부를 초기 비교 대상으로 제안한다. activation 크기만으로 빠른 point를 선택하지 않는다.
block 전체 후보를 자동 추가하지 않고 stage 결과에 근거한 추가 진단을 별도 승인 범위에서 수행한다.

## Parecon과 참고 그림

**미확인:** `/home/ainet`의 접근 가능한 사용자 문서·다운로드·연구 경로에서 파일명 검색으로 Parecon PDF를 찾지 못했다. 다른 제목·미제공 위치의 파일 존재 여부는 미확인이다. 현재 대화에 원문/그림 파일도 제공되지 않았다.

> Parecon 세부 group 정의와 수치는 원문 미확보로 직접 검증하지 못했다.
> 제공된 layer-group 및 partition-point 표현 개념만 참고했다.

| 구분 | 이번 작업의 처리 |
| --- | --- |
| 원문에서 직접 확인한 사실 | 없음 |
| 사용자 제공 개념 | layer group 기반 분할, Edge-only/Mobile-only endpoint, E2E 구성요소 분해 |
| EfficientNetV2-S에 새로 적용한 설계 | 제안된 9-group 검증 절차, 조건부 10-point 비교, 단일 tensor 경계 기준 |
| 모델 구조 차이로 그대로 적용할 수 없는 부분 | 원문 group 수·module mapping·수치의 직접 이식은 근거 없음; 실제 차이는 미확인 |

`processing density`, `cycles/bit`, `bit conversion ratio`는 원문의 정의와 계산법을 확인하지 못해 사용하지 않는다.
대신 group 처리시간, activation 크기·입력 대비 비율, 실제 전송시간, 실제 완료 요청 처리량을 사용한다.
