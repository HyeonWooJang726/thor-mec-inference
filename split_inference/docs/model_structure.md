# 설치 환경과 EfficientNetV2-S 구조 조사

## 1. 최초 호스트 조사 기록 — 당시 BLOCKED

| 항목 | 관찰 결과 |
| --- | --- |
| 조사일 | 2026-09-15 |
| 기본 실행 파일 | `/usr/bin/python3` |
| Python | `3.12.3 (main, Jul 15 2026, 23:46:41) [GCC 13.3.0]` |
| CPU architecture | `aarch64` |
| PyTorch | 기본 Python에서 `find_spec('torch') = None` |
| TorchVision | 기본 Python에서 `find_spec('torchvision') = None` |
| import 실패 | `ModuleNotFoundError: No module named 'torch'` |
| 기존 환경 1 | `/home/ainet/research/thor-mec-inference/.venv/bin/python`: Python 3.12.3, 두 package 모두 없음 |
| 기존 환경 2 | `/home/ainet/research/thor-mec-inference/venv/bin/python`: Python 3.12.3, 두 package 모두 없음 |
| CUDA SDK | `/usr/local/cuda/version.json`: `13.2.2` |
| CUDA runtime 배포 metadata | 같은 파일의 `cuda_cudart.version`: `13.2.86` |
| PyTorch CUDA build/runtime | 미확인: PyTorch 없음; SDK 버전과 동일하다고 가정하지 않음 |
| TorchVision EfficientNet 소스 경로 | 미확인: 조사 경로에서 설치본 `efficientnet.py` 발견 못 함 |
| CPU 더미 forward | 0회, package 부재로 미실행 |

`/home/ainet/research`, `/home/ainet/.local`, `/opt`, `/usr/local/lib`, `/usr/lib/python3`의 관련 파일을 탐색했다.
이 결과는 조사한 호스트 경로·Python 환경에 한정되며, 미제공 컨테이너나 다른 환경의 부재까지 증명하지 않는다.
CUDA metadata 조회는 실제 CUDA kernel 실행이나 PyTorch 호환성 검증이 아니다.
패키지 설치·업그레이드·다운로드는 하지 않았다.
후속 호스트·CDI 점검과 NGC 호환성 근거는 [환경 점검 문서](environment_audit.md)에 정리했다. 이후 컨테이너 GPU smoke test는 성공했으며, 최신 분할 구조 검증은 아래에 기록한다.

## 2. 공식 G1–G9 구조와 실제 TorchVision 대조

2026-09-15 사용자가 확정한 **본 프로젝트의 공식 분할 정의**다. 기계 판독 기준은 [분할 manifest](../manifests/efficientnet_v2_s_p0_p9.json), 구현은 [EfficientNetV2SPartitions](../src/common/efficientnet_v2_s_partitions.py)다. 최초 문서에서 미정이던 flatten 소유권은 **G8**로 확정했다.

Parecon이 공개한 9개 그룹·10개 분할점 구성을 참고하되, TorchVision EfficientNetV2-S에 대해 본 프로젝트가 명시적으로 정의한 재현 가능한 경계다. Parecon의 정확한 내부 구현을 복제했다고 주장하지 않는다. Parecon 구성에 대한 출처는 사용자 제공 설명이며 원문 내부 경계를 독립 검증한 것으로 표현하지 않는다.

| Group | 실제 실행 경로 | 확인된 구조 | 출력 경계 |
| --- | --- | --- | --- |
| G1 | `model.features[0]` | Conv2dNormActivation (stem) | P1 |
| G2 | `model.features[1]` | FusedMBConv × 2 | P2 |
| G3 | `model.features[2]` | FusedMBConv × 4 | P3 |
| G4 | `model.features[3]` | FusedMBConv × 4 | P4 |
| G5 | `model.features[4]` | MBConv × 6 | P5 |
| G6 | `model.features[5]` | MBConv × 9 | P6 |
| G7 | `model.features[6]` | MBConv × 15 | P7 |
| G8 | `model.features[7] → model.avgpool → torch.flatten(x, 1)` | Conv2dNormActivation → AdaptiveAvgPool2d(1) → flatten | P8 |
| G9 | `model.classifier` | Dropout(p=0.2, inplace=True) → Linear(1280,1000) | P9 |

설치본 소스는 `/usr/local/lib/python3.12/dist-packages/torchvision/models/efficientnet.py`다. 실제 모델 전체 module repr 및 `_forward_impl`, `FusedMBConv.forward`, `MBConv.forward`를 출력해 확인했다. 모델 순서는 `features → avgpool → torch.flatten(x, 1) → classifier`다. 두 block의 residual은 `result += input`으로 block 안에서 완결된다. 공식 경계는 완전한 stage 이후이며 block 내부를 분리하지 않는다. classifier의 dropout은 `eval()`에서 `training=False`였다.

## 3. CUDA 분할 정확성 검증 — 통과

[검증 스크립트](../scripts/verify_efficientnet_v2_s_partitions.py)는 다음 순서로 확인한다.

1. `torch.manual_seed(0)` 후 **한 번만** `efficientnet_v2_s(weights=None)`를 생성하고 FP32 CUDA 및 `eval()`을 적용한다. partition wrapper는 이 객체와 동일한 parameter 객체들을 참조하며 복사하거나 별도 랜덤 모델을 만들지 않는다.
2. `torch.inference_mode()`에서 `torch.randn([1,3,384,384], device="cuda", dtype=torch.float32)` 입력 한 개를 생성한다. TF32와 cuDNN benchmark를 끈다. 시간 측정·warm-up·성능 profiling은 하지 않는다.
3. 원본 모델 전체 forward를 기준값으로 사용한다. 원본 module hooks로 실제 features/avgpool/classifier 실행 순서와 P0–P9 tensor를 확인한다. P8은 classifier pre-hook으로 flatten 이후 입력을 관찰한다.
4. 각 P에서 `suffix(prefix(x, p), p)`를 실행한다. prefix의 중간 tensor도 원본 hook 관찰값과 비교한다. P0 prefix 및 P9 suffix는 identity다.
5. 모든 경계의 지정 shape, CUDA/FP32, 유한값을 확인하고 모든 출력 `[1,1000]`을 `torch.testing.assert_close(rtol=1e-5, atol=1e-6)`로 비교한다. 예외는 숨기거나 재시도하지 않는다.

`max_abs_diff = max(abs(split - reference))`, `max_rel_diff = max(abs(split - reference) / max(abs(reference), 1e-8))`로 정의한다.

**실측 결과:** 모든 P0–P9의 shape 일치, 모든 최종 출력 `[1,1000]`, 각 point의 **max_abs_diff=0.0, max_rel_diff=0.0**, `ALL_P0_P9_PASS`, Docker exit **0**, stderr **0 bytes**. 원본 logits의 max absolute value는 약 `3.3570473e-6`이며 모든 값이 0인 입력/출력끼리의 비교가 아니다. [분할별 shape·numel·bytes 표](partition_candidates.md)에 경계 tensor를 정리했다.

검증 환경: Python `3.12.3`, PyTorch `2.14.0a0+4fdf77b940.nv26.08`, TorchVision `0.29.0a0+0bc41e67.nv26.08`, `torch.version.cuda=13.4`, cuDNN API 반환값 `92500`, NVIDIA Thor. JetPack 7.2.1과 이 이미지의 공식 호환성은 여전히 미확인이며 이 장치에서의 실행 성공과 구분한다.

### 실제 Docker 실행 명령

worktree `/home/ainet/research/thor-mec-inference-split`, 시작 HEAD와 upstream 모두 `266da5db93a690af57a64ab5ce7b9afec98db9f7`, branch `split-inference`, 시작 작업 트리 clean을 확인했다. 아래 명령은 sudo 없이 실행했다. 원문 출력은 호스트 `logs/efficientnet_partitions_20260915/`에 보존하며 Git에 넣지 않는다.

```bash
docker run --rm --pull=never --runtime=nvidia -e NVIDIA_VISIBLE_DEVICES=all -e NVIDIA_DRIVER_CAPABILITIES=compute,utility -e PYTHONPATH=/workspace --network=none -v "$PWD":/workspace:ro -w /workspace nvcr.io/nvidia/pytorch@sha256:3becd068f49bd2ad38f90db5f9a4803019a76933a24e63d821376c44e7a9200a python -B split_inference/scripts/verify_efficientnet_v2_s_partitions.py > logs/efficientnet_partitions_20260915/verify.stdout.log 2> logs/efficientnet_partitions_20260915/verify.stderr.log
```

## 4. 검증 범위

이 결과는 동일 장치·동일 모델·고정 seed의 단일 dummy 입력에 대한 분할 실행 정확성이다. pretrained weights, ImageNet accuracy, 직렬화/네트워크 전송, Edge 장치, 성능은 검증하지 않았다. 추가 block 경계를 정의하지 않았으며 pooling/flatten/dropout/classifier 순서를 변경하지 않았다. image 재pull·build·삭제, package 설치, CDI/MIG/runtime 설정 변경은 수행하지 않았다.
