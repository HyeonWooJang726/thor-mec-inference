# 설치 환경과 EfficientNetV2-S 구조 조사

## 1. 환경 — 확인됨 / BLOCKED

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
후속 호스트·CDI 점검과 NGC 호환성 근거는 [환경 점검 문서](environment_audit.md)에 정리했다. 컨테이너 내부 PyTorch·TorchVision 및 GPU 실행은 여전히 미확인이다.

## 2. 구조 판정 — 미확인

현재 설치된 구현을 확보하지 못했으므로 인터넷 표나 기억에 근거한 stage 수·channel·stride·shape를 채우지 않는다.
**9-group의 네 가지 타당성 판정(그대로 사용/결합/분리/부적합)은 모두 보류, BLOCKED**다.
아래 이름과 종류는 사용자 제시 후보이며 실제 모델 조사 결과가 아니다.

| Group 후보 | 사람이 읽을 이름 | TorchVision 경로 | Block 종류 | Block 수 | 입력 shape | 출력 shape | Downsampling | Residual 주의사항 |
| -------: | --------- | -------------- | -------- | ------: | -------- | -------- | ------------ | ------------- |
| 1 | Stem | 미확인 | 제안: convolution | 미확인 | 지정: `[1,3,384,384]` | 미확인 | 미확인 | 구현 확인 필요 |
| 2 | FusedMBConv stage 1 | 미확인 | 제안: FusedMBConv | 미확인 | 미확인 | 미확인 | 미확인 | block 내부 및 stage 간 skip 조사 |
| 3 | FusedMBConv stage 2 | 미확인 | 제안: FusedMBConv | 미확인 | 미확인 | 미확인 | 미확인 | 동일 |
| 4 | FusedMBConv stage 3 | 미확인 | 제안: FusedMBConv | 미확인 | 미확인 | 미확인 | 미확인 | 동일 |
| 5 | MBConv stage 4 | 미확인 | 제안: MBConv | 미확인 | 미확인 | 미확인 | 미확인 | 동일 |
| 6 | MBConv stage 5 | 미확인 | 제안: MBConv | 미확인 | 미확인 | 미확인 | 미확인 | 동일 |
| 7 | MBConv stage 6 | 미확인 | 제안: MBConv | 미확인 | 미확인 | 미확인 | 미확인 | 동일 |
| 8 | Final convolution과 pooling | 미확인 | 제안: convolution + pooling | 미확인 | 미확인 | 미확인 | 미확인 | flatten 소유 group 명시 필요 |
| 9 | Classifier | 미확인 | 제안: dropout + linear | 미확인 | 미확인 | 지정 기대값: `[1,1000]`, 실행 미검증 | 미확인 | dropout 위치·확률·eval 동작 확인 |

## 3. 기존 실행 환경 확보 후 남은 1단계 검증

다음은 미수행 검증 절차이며 profiling 구현 지시가 아니다.

1. 해당 interpreter의 Python/PyTorch/TorchVision/`torch.version.cuda`와 EfficientNet 소스 실제 경로를 기록한다.
2. 설치된 소스에서 모델 factory, stage config, `features`, block forward, 모델 forward를 읽는다.
3. `torchvision.models.efficientnet_v2_s(weights=None)`로 CPU 모델을 구성한다. pretrained enum metadata를 읽는 것은 다운로드와 구분한다.
4. `features` 각 stage의 종류·block 수, 각 block의 input/output channels, expansion, stride, convolution kernel, residual 활성 조건과 더하기 위치, squeeze/excitation 및 stochastic-depth 동작을 기록한다.
5. final convolution, average pooling, flatten, dropout 확률, linear 입출력과 실행 순서를 기록한다. flatten이 module 목록에 없을 수 있으므로 forward 코드를 반드시 확인한다.
6. hooks로 각 stage와 block 입출력을 수집하도록 준비한 뒤 `eval()`, `torch.inference_mode()`, FP32 `[1,3,384,384]` CPU 더미 forward를 **한 번만** 수행한다. 반복·시간측정·GPU 호출은 하지 않는다.
7. source의 residual 사용 조건과 실제 block별 shape를 대조하고 표와 tensor manifest를 갱신한다. tensor가 경계를 넘어 추가로 필요한지 확인한다.
8. G8이 pooling 이후 flatten까지 담당하여 G9 입력을 2D로 만들지, G9이 flatten을 담당할지 명시한다. 실제 forward를 보존하는 방식으로 결정한다.

## 4. 경계 안전성 기준 — 제안

경계 이전의 모든 의존성이 하나의 출력 tensor에 반영되고, 다음 실행 범위가 추가 skip tensor 없이 실행 가능해야 한다.
residual 더하기가 끝나기 전 block 내부를 자르면 입력 branch를 별도로 보존·전송해야 할 수 있으므로 초기 후보에서 제외한다.
완전한 block 이후도 모든 skip이 해당 block 안에서 닫히는 것을 코드로 확인한 경우에만 안전하다고 판정한다.
stage/group 이후를 본 실험 후보, 개별 block 이후를 필요할 때만 사용하는 진단 후보로 구분한다.
현재 구현에 대한 **안전 판정과 block 경계 개수는 미확인**이다.
