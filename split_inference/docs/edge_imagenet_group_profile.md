# EfficientNetV2-S Edge pretrained ImageNet 그룹 프로파일

## 목적과 공식 결과

RTX 5070 Ti의 실제 배포 환경에서 G1–G9 각각의 GPU 처리시간을 측정했다. **공식 Edge group profile은 seeded-order run `20260915T130321_560472Z`만 사용한다.** Thor 문서·코드의 seed 1–5 순서 규칙, 동일한 300장·모델·그룹 정의·warm-up·CUDA Event 경계를 맞춘 실행이다. Thor 원본 raw와 직접 대조한 parity는 아직 미확인이다.

Fixed-order run `20260915T124213_566500Z`는 보조 민감도 결과로 보존한다. 두 실행의 표본을 합치거나 평균내지 않는다. 기존 dummy/suffix 결과도 변경하지 않았다. 네트워크·서버 요청·전체 E2E 지연 측정이 아니다.

## 환경과 입력

- GPU: NVIDIA GeForce RTX 5070 Ti; driver 595.95; power limit 300 W; P0. GPU clock/power 설정을 변경하거나 고정하지 않았다.
- Ubuntu 24.04.4, x86_64, WSL kernel `6.18.33.2-microsoft-standard-WSL2`; WDDM, display 활성화.
- Python 3.12.3, PyTorch `2.13.0+cu132`, torchvision `0.28.0+cu132`, CUDA runtime 13.2, cuDNN API 92000; PIL 12.3.0, NumPy 2.5.2. 기존 전용 venv `/home/ainet/venvs/efficientnet-v2-s-cu132`를 사용했다.
- `torchvision.models.efficientnet_v2_s`, `EfficientNet_V2_S_Weights.IMAGENET1K_V1`. FP32, batch 1, 입력 `[1,3,384,384]`, `eval()`, `torch.inference_mode()`, autocast OFF, TF32 OFF, cuDNN benchmark ON. CUDA Graph/torch.compile/TensorRT 미사용.
- `TORCH_ALLOW_TF32_CUBLAS_OVERRIDE=0`, `NVIDIA_TF32_OVERRIDE=0`. 시작 전 관찰한 cuDNN deterministic 및 deterministic algorithms는 모두 false이며 임의 변경하지 않았다.
- ZIP: `/mnt/c/Users/gusdn/Downloads/imagenet-val.zip`, 6,669,976,535 bytes; JPEG 50,000개. 기존 ZIP과 공식 checkpoint cache를 재사용했고 추출·대체·다운로드하지 않았다.
- 선택은 정렬된 JPEG 목록에서 `random.Random(0).sample(images,300)`이다. 기존 [선택 목록](imagenet_profile/20260915T112015Z/selected_imagenet_members.txt)의 300장과 정확히 일치한다.
- [Evidence](imagenet_profile/20260915T112015Z/selected_image_evidence.csv)의 원본 JPEG SHA-256 및 전처리 FP32 tensor SHA-256, 총 600개를 실행 전에 대조했다. 선택/evidence 파일은 이번 출력과 기존 Thor 커밋본이 바이트 단위로 같다.
- 공식 `weights.transforms()`: RGB, resize 384, center crop 384, bilinear, mean `[0.485,0.456,0.406]`, std `[0.229,0.224,0.225]`.

| 식별값 | SHA-256 |
| --- | --- |
| 선택 목록 | `f198e9fd3da063f0f4ae66dff1d6c76fdb66c7875abae88d462b37f96d338bc2` |
| Evidence CSV | `5706419efb22bd224d7c1b4bac5cceb22d479c3ec1336cc4e9cbb467301bf794` |
| `efficientnet_v2_s-dd5fe13b.pth` | `dd5fe13b1d60ec15317ccc8ca158186e134d3366c3dde9cb9a4e301f2dc66c74` |
| Canonical state_dict | `dcac15dc687d43926f62a7942918dc73d11372abbb612352336b4d5840ca4710` |

Canonical v1은 parameter와 buffer의 key를 정렬하고 각 `[key,dtype,shape]` compact JSON과 contiguous CPU raw bytes에 uint64 little-endian 길이를 붙여 해시한다. `torch.save()` 파일 자체의 해시와 다르다. 측정 스크립트의 `canonical_hash()`를 사용했고 checkpoint state, 로드한 모델 및 종료 모델이 일치했다.

## 그룹 정의와 activation

기존 `src/common/efficientnet_v2_s_partitions.py` 및 manifest를 그대로 사용했다. 아래 shape·bytes는 실제 결과 CSV와 Thor의 커밋된 activation CSV를 필드별로 대조했다. 모든 tensor는 FP32다.

| 그룹 | 연산 | 입력 shape | 출력 shape | 입력 bytes | 출력 bytes |
| --- | --- | --- | --- | ---: | ---: |
| G1 | `features[0]` | `[1, 3, 384, 384]` | `[1, 24, 192, 192]` | 1,769,472 | 3,538,944 |
| G2 | `features[1]` | `[1, 24, 192, 192]` | `[1, 24, 192, 192]` | 3,538,944 | 3,538,944 |
| G3 | `features[2]` | `[1, 24, 192, 192]` | `[1, 48, 96, 96]` | 3,538,944 | 1,769,472 |
| G4 | `features[3]` | `[1, 48, 96, 96]` | `[1, 64, 48, 48]` | 1,769,472 | 589,824 |
| G5 | `features[4]` | `[1, 64, 48, 48]` | `[1, 128, 24, 24]` | 589,824 | 294,912 |
| G6 | `features[5]` | `[1, 128, 24, 24]` | `[1, 160, 24, 24]` | 294,912 | 368,640 |
| G7 | `features[6]` | `[1, 160, 24, 24]` | `[1, 256, 12, 12]` | 368,640 | 147,456 |
| G8 | `features[7] → avgpool → flatten(1)` | `[1, 256, 12, 12]` | `[1, 1280]` | 147,456 | 5,120 |
| G9 | `classifier` | `[1, 1280]` | `[1, 1000]` | 5,120 | 4,000 |

**G8의 출력은 pooling·flatten 이후 `[1,1280]`, 5,120 bytes이다.** G9는 classifier이며 출력 `[1,1000]`, 4,000 bytes다. [Activation CSV](imagenet_profile/edge/20260915T130321_560472Z/activation_shapes_bytes.csv)에 원래 정밀도의 bytes·MiB·bit conversion ratio를 보존했다.

Pp의 prefix는 G1…Gp, suffix는 G(p+1)…G9이다. P0 prefix와 P9 suffix는 identity이며 P9는 Edge 연산 없음이다. 이번 결과는 각 그룹 시간이며 suffix 전체 시간을 그룹 평균 합으로 만들지 않았다.

## 측정 프로토콜

1. 300장 모두 CPU에서 디코딩·전처리하고 full forward/분할 재결합 correctness를 확인한다.
2. 선택 목록의 첫 100장으로 그룹당 **warm-up 100회**를 수행한다. 이 명시적 warm-up phase는 전체 5개 round 전에 한 번이며 round마다 반복하지 않는다.
3. **5 rounds × 300장 = 그룹당 1,500개 측정 표본**. round 0–4마다 새 `list(range(300))`에서 시작하여 `Random(1)`, …, `Random(5)`로 각각 shuffle한다. 각 round에 300장 모두 한 번씩 포함한다.
4. 이미지마다 G1→…→G9를 순차 실행한다. 모든 그룹은 같은 round permutation을 사용하며 그룹 입력은 직전 그룹의 실제 출력이다.

```text
이미지별 H2D → torch.cuda.synchronize()
각 그룹: 입력 shape 검사
         start.record() → parts._run(x,i,i+1) → end.record()
         end.synchronize() → start.elapsed_time(end)
         출력 shape 검사 → x=result
G1–G9 종료 후 CSV 기록
```

CUDA Event는 **해당 그룹 forward만** 감싼다. 그룹 내부 연산과 출력 생성은 포함하며, eager kernel launch 사이의 device idle gap은 포함될 수 있다. ZIP 읽기·디코딩·전처리·H2D/D2H 전송·별도 직렬화·파일 I/O·host wall-clock·queue·네트워크·E2E는 측정값에 포함하지 않는다. 타이밍 경로에 명시적 input/output clone은 없고 `x=result`는 event 뒤 참조 전달이다.

전체 raw는 **14,400행 = warm-up 900 + 본 측정 13,500**이다. 모든 elapsed time은 유한한 양수다. 누락·중복·outlier 제외·winsorization·fallback은 없다. mean/median/p95/p99/min/max와 **sample SD (`ddof=1`)**를 계산하며 percentile은 linear interpolation이다. raw로 통계를 독립 재계산해 summary와 일치함을 확인했다.

[Round seed·순서 해시](imagenet_profile/edge/20260915T130321_560472Z/round_order_hashes.csv)는 raw의 실제 member 순서를 검증한 값이다. 해시 입력은 순서대로 UTF-8 member 경로와 LF를 연결하며 마지막 경로 뒤에도 LF가 있다. 모든 G1–G9에 동일하다.

## 공식 Edge 결과

단위 **ms**, 각 그룹 **n=1,500**. 아래 표는 소수점 6자리이며 [group_summary.csv](imagenet_profile/edge/20260915T130321_560472Z/group_summary.csv)에 전체 정밀도·p99·density를 보존했다. GPU 주파수를 곱한 cycles/bit는 사용하지 않고 density는 ms/Mbit다.

| 그룹 | Mean | Median | p95 | Sample SD | Min | Max |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| G1 | 0.088219 | 0.080624 | 0.131291 | 0.026032 | 0.058880 | 0.321152 |
| G2 | 0.174653 | 0.166400 | 0.222389 | 0.032467 | 0.133888 | 0.488320 |
| G3 | 0.600293 | 0.586848 | 0.651827 | 0.073462 | 0.558240 | 2.165216 |
| G4 | 0.428406 | 0.412256 | 0.525832 | 0.087425 | 0.384224 | 2.886048 |
| G5 | 1.252021 | 1.195728 | 1.623738 | 0.285620 | 0.840160 | 5.803264 |
| G6 | 2.022254 | 1.927472 | 2.399322 | 0.282577 | 1.844096 | 5.946528 |
| G7 | 4.178470 | 4.078320 | 4.528360 | 0.552107 | 3.995904 | 22.441759 |
| G8 | 0.097253 | 0.088256 | 0.165707 | 0.039582 | 0.031264 | 0.561568 |
| G9 | 0.082087 | 0.078448 | 0.116064 | 0.054682 | 0.015200 | 1.594528 |

## Correctness

**300 × (G1–G9 전체 순차 경로 1종 + P0–P9 재결합 경로 10종) = 3,300건**이다. `execution` 값은 `G1-G9`, `P0`, …, `P9`이며 항목별 300건, `(sample_id,execution)` 중복·누락은 없다. 모든 최종 출력 `[1,1000]`, 최대 절대·상대오차 0.0, `rtol=1e-5`, `atol=1e-6` 통과다. 상대오차 분모 floor는 1e-8이다.

중간 activation은 shape·dtype·bytes 검증이며 별도 9개 수치 비교가 아니다. ImageNet ground-truth accuracy나 Thor↔Edge logits 직접 비교를 의미하지 않는다. [Correctness summary](imagenet_profile/edge/20260915T130321_560472Z/correctness_summary.json)는 원본 validation CSV와 측정 당시 독립 검증 결과에서 추출했다.

## Fixed-order 보조 비교

[비교 CSV](imagenet_profile/edge/20260915T130321_560472Z/fixed_vs_seeded_comparison.csv)는 fixed/seeded 각각의 mean·median·p95·sample SD·min/max·순위를 보존한다. 차이는 `seeded-fixed`, 백분율은 `(seeded-fixed)/fixed*100`이다. 표본은 합치지 않았다.

모든 그룹의 mean·median·p95는 이번 seeded 실행에서 낮았다. 그러나 G7/G9의 SD와 maximum, G4/G5의 maximum은 증가했다. G7의 maximum 22.441759 ms도 제거하지 않았다. Mean/p95 오름차순은 양쪽 모두 G9<G1<G8<G2<G4<G3<G5<G6<G7이다. Median은 G1/G8 순위가 교체됐다. 두 실행 시점과 비고정 클럭 등 상태가 달라 **빠른 이유가 shuffle 효과라고 주장하지 않으며 순서 효과를 인과적으로 추정할 수 없다.**

## 환경 관측과 한계

- 시작/종료 UTC: `2026-09-15T13:03:28.909553+00:00`–`2026-09-15T13:04:21.928217+00:00`. 이는 준비·검증 등을 포함한 프로파일러 구간이며 처리시간 표의 단위/경계와 다르다.
- 실행 전 13:03:28 UTC: GPU utilization 1%, 평균 전력 snapshot 54.17 W, 32°C, SM 2505 MHz, memory 14001 MHz. 사후 13:45:32 UTC: 6%, 53.18 W, 31°C, SM 2535 MHz, memory 14001 MHz. 두 조회 모두 compute process 없음, P0, power limit 300 W, display 활성화였다.
- **사후 GPU 조회는 종료 약 41분 뒤다.** 종료 직후 상태를 나타내지 않는다. **측정 중 연속 clock trace가 없고 GPU clock도 고정하지 않았다.**
- **Edge는 WSL/WDDM 환경이며 display가 활성화**됐다. GPU process 조회만으로 Windows graphics를 포함한 완전한 무간섭을 보장할 수 없다.
- Thor 문서의 PyTorch `2.14.0a0+4fdf77b940.nv26.08`, torchvision `0.29.0a0+0bc41e67.nv26.08`, CUDA 13.4, cuDNN 92500은 Edge 버전과 다르다. **실제 배포 환경 비교에는 사용할 수 있지만 순수 하드웨어 성능만 분리한 비교는 아니다.**
- maximum tail을 포함한 모든 표본을 유지했다. 별도 반복 run이나 교차 실행으로 통제한 인과 실험이 아니다.
- **네트워크·직렬화·전송·E2E latency는 포함하지 않는다.** 원본 Thor raw sequence와의 직접 parity도 아직 미확인이고 Thor 문서·코드의 실행 규칙과 일치시킨 것이다.

## 재현과 원본 보존

측정 당시 HEAD는 `8775bfb04018cb9c39c1767698a058116c3f9338`이며 프로파일러의 두 옵션 추가가 unstaged 상태였다. 실행 source SHA-256은 `de2483f02ee89f094ba14eb3f8a741ea2b766a96af9c5a261e7698cbc1a893b1`이다. 기본 shuffle/group/warm-up/timing/통계 코드는 변경하지 않았다. `--fixed-order`는 보조 실험용이며 공식 실행에서는 **생략**, `--skip-render`는 사용했다. 옵션을 생략한 기존 기본 동작은 보존했다.

당시 실제 호출은 `/home/ainet/venvs/efficientnet-v2-s-cu132/bin/python -B /tmp/run_edge_thor_seeded_audit.py`였다. 이 로컬 실행기의 사본 `run_audit.py`는 원본 결과에만 보존하고 Git에 포함하지 않는다. [실행 manifest](imagenet_profile/edge/20260915T130321_560472Z/run_manifest.json)에 실제 argv·환경·cache·관측값·source hash가 있다.

아래는 같은 프로파일러를 직접 호출하는 재현 명령이다. **새 UTC 결과 디렉터리를 만들고**, 현재 장치·다른 compute process 부재·공식 checkpoint 및 600개 이미지 hash를 확인한 후 해당 디렉터리에 실제 점검 기록을 담은 `preflight.json` (`safe_to_measure: true`)을 준비해야 한다. 기존 기록을 복사해 새 실행의 안전 점검을 대신하지 않는다. 아래 `<새 결과 디렉터리>`는 그 경로로 바꾼다. 이번 문서화 작업에서는 이 명령을 실행하지 않았다.

```bash
cd /home/ainet/research/thor-mec-inference-edge-profile
TORCH_ALLOW_TF32_CUBLAS_OVERRIDE=0 NVIDIA_TF32_OVERRIDE=0 \
/home/ainet/venvs/efficientnet-v2-s-cu132/bin/python -B - \
  --zip /mnt/c/Users/gusdn/Downloads/imagenet-val.zip \
  --output '<새 결과 디렉터리>' --skip-render <<'PYRUN'
import torch
from split_inference.scripts import profile_efficientnet_v2_s_imagenet as profile
torch.hub.set_dir('/home/ainet/research/thor-mec-inference-edge-profile/split_inference/results/edge_processing_profile/imagenet_validation/20260915T122814_764707Z/torch_cache')
profile.CONDITIONS = profile.CONDITIONS.replace(
    'Thor MAXN, DVFS ON', 'Edge RTX 5070 Ti, clocks not locked by this run')
profile.main()
PYRUN
```

`CONDITIONS` 교체는 기존 스크립트의 설명 문자열을 Edge 장치로 표시하기 위한 것이며 측정 알고리즘을 변경하지 않는다. 패키지 설치·그림 생성 없이 기존 Python 환경·checkpoint cache를 사용한다.

원본 ignored 경로:

- 공식: `split_inference/results/edge_processing_profile/imagenet_thor_seeded_order/20260915T130321_560472Z/`
- 보조: `split_inference/results/edge_processing_profile/imagenet_fixed_order/20260915T124213_566500Z/`

원시 timing·validation·metadata·로그·실행기 등 기존 artifact는 모두 로컬에 보존한다. [원본 artifact SHA-256 목록](imagenet_profile/edge/20260915T130321_560472Z/raw_artifact_sha256.csv)에 두 실행의 경로·크기·해시를 기록했다. 공식 raw timing SHA-256은 `6add2dfb9ee0a39dc12c784858dfd56cdc662281756e9a7fdc009f2c6e07fe67`이다.

커밋하는 CSV는 기존 Thor tracked CSV와 같이 CRLF만 LF로 정규화했으며 **모든 필드 문자열·수치가 원본과 일치**한다. [Manifest](imagenet_profile/edge/20260915T130321_560472Z/run_manifest.json)의 `copy_verification`에 원본/복사본 해시와 검증 방법을 남겼다. 원본 파일은 변경하지 않았으며 raw timing 전체·checkpoint·ImageNet·stdout/stderr·임시 실행기는 Git에 포함하지 않는다.
