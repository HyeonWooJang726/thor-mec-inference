# Thor 환경 점검 및 PyTorch 실행 검증 범위

점검일: **2026-09-15 (Asia/Seoul)**.
작업 경로: `/home/ainet/research/thor-mec-inference-split`, 브랜치: `split-inference`.
사용 모델은 **EfficientNetV2-S**이며 worktree·브랜치 명칭 변경과 무관하다.

## 판정과 근거 구분

- **확인됨 — 이번 read-only 점검:** 로컬 명령 출력·패키지 metadata·서비스 journal 또는 공식 문서를 이번 작업에서 직접 읽었다.
- **확인됨 — 사용자 제공 사전 점검:** 사용자가 확인한 결과를 출처와 함께 기록한다. 이번에 다시 실행한 결과로 표현하지 않는다.
- **미확인:** 실제 실행 또는 공식 근거가 부족하다. 지원 가능성이나 설치 metadata만으로 실행 성공을 주장하지 않는다.
- **제안:** 승인 후 수행할 후속 검증이다. 현재 실행 결과가 아니다.

## 1. 확인됨: 호스트와 설치 도구

| 항목 | 결과 | 이번 점검 근거 |
| --- | --- | --- |
| 하드웨어 | NVIDIA Jetson AGX Thor Developer Kit | `/proc/device-tree/model` |
| Architecture | `aarch64` | `uname -m` |
| OS | Ubuntu **24.04.4 LTS** | `/etc/os-release` |
| L4T | **39.2.1**, package `39.2.1-20260806224157` | `/etc/nv_tegra_release`, `nvidia-l4t-core` package |
| JetPack | **7.2.1**, package `7.2.1-b49` | `nvidia-jetpack` package |
| CUDA | **13.2**, SDK metadata **13.2.2** | `/usr/local/cuda/version.json` |
| cuDNN | **9.20.0.46**, package `9.20.0.46-1` | `libcudnn9-cuda-13` package |
| TensorRT | **10.16.2.10**, package `10.16.2.10-1+cuda13.2` | `libnvinfer10` package |
| 기본 Python | **3.12.3**, `/usr/bin/python3` | `sys.version` 및 기존 실행 파일 확인 |
| 기본 Python pip | **없음** | `importlib.util.find_spec('pip') = None` |
| 기본 Python PyTorch·TorchVision | **없음** | 각 module의 `find_spec(...) = None` |
| APT `python3-torch` | Installed `(none)`, Candidate `(none)` | `apt-cache policy python3-torch` |
| APT `python3-torchvision` | Installed `(none)`, Candidate `(none)` | `apt-cache policy python3-torchvision` |
| Docker CLI | **29.7.2**, build `a7dcaa6` | `docker --version` |
| NVIDIA Container Toolkit | **1.19.1**, package `1.19.1-1` | package 및 `nvidia-ctk --version` |

APT 결과는 **현재 설정된 로컬 APT index**에 한정된다. 다른 저장소 전체의 package 부재를 의미하지 않는다. APT index 갱신·설치는 수행하지 않았다.
Docker CLI 버전 확인은 daemon 연결 확인이 아니다. CUDA·cuDNN·TensorRT package 존재는 컨테이너 내부 PyTorch GPU 호환성 검증이 아니다.
기존 두 가상환경에 PyTorch·TorchVision이 없다는 최초 조사 근거는 [모델 구조 문서](model_structure.md)에 있다.

## 2. 확인됨: CDI 장치와 generation 상태

이번 `nvidia-ctk cdi list`는 정상 종료하여 다음 4개 장치를 열거했다.

```text
nvidia.com/gpu=0
nvidia.com/gpu=all
nvidia.com/pva=0
nvidia.com/pva=all
```

`systemctl show nvidia-cdi-refresh.service`의 관찰값:

```text
Result=success
ExecMainCode=1
ExecMainStatus=0
ActiveState=inactive
SubState=dead
```

`ExecMainCode=1`은 프로세스가 종료된 상태(`CLD_EXITED`)이며 실패 exit code 1이라는 뜻이 아니다. 실제 종료 status는 **0/SUCCESS**다.
2026-09-15 16:07:11 KST journal에 CDI spec version **0.7.0** 생성과 서비스의 성공적인 종료가 기록되어 있다.
일회성 generation service의 **inactive (dead)는 실행 완료 상태**이며 여기서는 실패가 아니다.
NVIDIA 공식 문서도 정상 서비스 상태 예시로 `inactive (dead)`와 `status=0/SUCCESS`를 제시한다. [NVIDIA CDI 공식 문서](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/cdi-support.html)

최초 sandbox 내부 `systemctl show`는 `Failed to connect to bus: Operation not permitted`로 조회가 제한됐다. 승인된 sandbox 외부 read-only 재조회에서 위 상태를 확인했다. 이는 CDI generation 실패 기록이 아니다. 서비스 재시작·재생성·설정 변경은 하지 않았다.

### 관찰된 warning과 해석

같은 journal에서 다음 warning을 확인했다.

- `/usr/lib/aarch64-linux-gnu/tegra` 경로와 symlink를 찾지 못했다는 warning.
- `nvgstcapture-1.0_README.txt`, `nvgstipctestapp-1.0_README.txt`, `nvgstplayer-1.0_README.txt`에 대한 soname symlink 탐색 중 `bad magic number` warning.

warning은 보존하되 **CDI 전체 실패로 분류하지 않는다**. 이후 spec 생성 성공과 장치 열거 성공이 확인됐다.
해당 warning이 실제 컨테이너 workload에 영향을 주는지는 **미확인**이다. warning만으로 GPU 실행 실패 또는 무해함을 단정하지 않는다.

## 3. NGC image manifest와 공식 호환성

**확인됨 — 사용자 제공 사전 점검:** `nvcr.io/nvidia/pytorch:26.08-py3` manifest에 **linux/amd64와 linux/arm64**가 모두 존재한다.
이번 문서 정리에서는 manifest를 재조회하지 않았고, 원시 manifest·digest는 확보하지 않았다. 이 기록은 사용자가 제공한 manifest 조회 결과에 근거한다.

**확인됨 — 이번 공식 문서 조회:** NVIDIA PyTorch for Jetson compatibility 표의 NVIDIA Framework Container **26.08** 행에는 JetPack **7.1**이 표시되어 있다. 조회일은 2026-09-15다. [NVIDIA PyTorch for Jetson compatibility](https://docs.nvidia.com/deeplearning/frameworks/install-pytorch-jetson-platform-release-notes/pytorch-jetson-rel.html)

**미확인:** JetPack **7.2.1**과 NGC PyTorch **26.08**의 공식 호환성은 이 표만으로 확정할 수 없다.
`linux/arm64 manifest 존재`는 해당 architecture 이미지가 제공된다는 근거이며, **Thor에서 GPU 실행 가능**의 증명이 아니다.
CDI 열거·manifest 존재·공식 호환성·실제 tensor 연산 성공은 각각 구분해 검증한다.

## 4. 미확인: 실행 및 모델 검증

| 항목 | 현재 상태와 남은 확인 |
| --- | --- |
| 현재 사용자 Docker daemon 접근 | 미확인; daemon 연결 조회 미실행 |
| Docker NVIDIA runtime 설정 | 미확인; runtime 및 daemon 설정 조사 미실행 |
| PyTorch container pull | 미확인; 이번 작업에서 pull하지 않음 |
| 컨테이너 내부 `torch.cuda.is_available()` | 미확인; 컨테이너 실행하지 않음 |
| Thor GPU의 실제 tensor 연산 | 미확인; CUDA tensor 연산하지 않음 |
| 컨테이너 TorchVision 포함 여부·버전 | 미확인; 호스트의 package 부재와 구분 |
| JetPack 7.2.1 / NGC PyTorch 26.08 공식 호환성 | 미확인; 현재 공개 표는 7.1 표시 |
| EfficientNetV2-S 실제 생성·중간 activation shape | 미확인 / BLOCKED; 모델 생성 및 forward 0회 |
| P0–P9 split 경계의 실행 안전성 | 미확인; 9-group이 검증될 때의 조건부 설계 |

입력 `[1,3,384,384]`의 FP32 1.6875 MiB 및 기대 logits `[1,1000]`의 4,000 bytes는 **사용자 지정 shape의 산술 계산**이며 실행 검증값이 아니다.
P1–P8 activation shape·크기는 계속 미확인으로 둔다. [분할점 후보 문서](partition_candidates.md)

## 5. 다음 단계 — 제안, 이번에는 미실행

다음 단계는 **Docker runtime 및 PyTorch GPU smoke test**다. 별도 승인 이후 다음 범위를 확인한다.

1. 현재 사용자 daemon 접근, Docker의 GPU 장치 전달 방식과 NVIDIA runtime/CDI 설정을 read-only로 확인한다.
2. 사용할 image의 공식 호환성 근거와 manifest digest를 기록하고, 승인 범위에서 pull·컨테이너 실행을 검증한다.
3. 컨테이너 Python/PyTorch/TorchVision/CUDA 버전, `torch.cuda.is_available()`, GPU 식별, 작은 CUDA tensor 연산의 결과를 확인한다. 반복 profiling으로 확대하지 않는다.
4. 사용할 TorchVision 구현을 확보한 뒤 `weights=None` 모델 조사와 허용된 CPU 더미 forward 1회로 남은 1단계 구조 검증을 완료한다.

현재는 package 설치, Docker pull·run, ZIP 해제, weight 다운로드, GPU smoke test·profiling, Edge 접속, 전체 실험을 하지 않았다.
실측 latency·throughput·accuracy 및 가상 profiling 그림은 없다.
이번 승인 범위는 linked worktree 이동, 브랜치 이름 변경, 문서 검증·보완, `split_inference/` commit 및 새 origin 브랜치 push다. main 변경·merge·PR 생성은 포함하지 않는다.
