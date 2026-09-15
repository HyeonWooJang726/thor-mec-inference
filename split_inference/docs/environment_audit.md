# Thor 환경 점검 및 PyTorch 실행 검증 범위

점검일: **2026-09-15 (Asia/Seoul)**.
작업 경로: `/home/ainet/research/thor-mec-inference-split`, 브랜치: `split-inference`.
사용 모델은 **EfficientNetV2-S**이며 worktree·브랜치 명칭 변경과 무관하다.

섹션 1–5는 이전 점검 기록이다. Docker 권한 해결 후 재개한 검증은 섹션 6 이하에 기록하며, 실행 여부의 최신 판정은 후속 기록을 기준으로 한다.

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

## 4. 이전 점검 당시 미확인: 실행 및 모델 검증

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

## 5. 이전 점검 당시 다음 단계 — 제안, 당시 미실행

다음 단계는 **Docker runtime 및 PyTorch GPU smoke test**다. 별도 승인 이후 다음 범위를 확인한다.

1. 현재 사용자 daemon 접근, Docker의 GPU 장치 전달 방식과 NVIDIA runtime/CDI 설정을 read-only로 확인한다.
2. 사용할 image의 공식 호환성 근거와 manifest digest를 기록하고, 승인 범위에서 pull·컨테이너 실행을 검증한다.
3. 컨테이너 Python/PyTorch/TorchVision/CUDA 버전, `torch.cuda.is_available()`, GPU 식별, 작은 CUDA tensor 연산의 결과를 확인한다. 반복 profiling으로 확대하지 않는다.
4. 사용할 TorchVision 구현을 확보한 뒤 `weights=None` 모델 조사와 허용된 CPU 더미 forward 1회로 남은 1단계 구조 검증을 완료한다.

현재는 package 설치, Docker pull·run, ZIP 해제, weight 다운로드, GPU smoke test·profiling, Edge 접속, 전체 실험을 하지 않았다.
실측 latency·throughput·accuracy 및 가상 profiling 그림은 없다.
이번 승인 범위는 linked worktree 이동, 브랜치 이름 변경, 문서 검증·보완, `split_inference/` commit 및 새 origin 브랜치 push다. main 변경·merge·PR 생성은 포함하지 않는다.


## 6. Docker를 사용하는 이유

- 목적은 **성능 향상이 아니라 의존성 격리와 재현성 확보**다. Docker는 필수 전제나 성능 최적화 기법이 아니다.
- 현재 Thor 호스트 Python에는 **pip, PyTorch, TorchVision이 없다**. 이번 재조회에서도 Python `3.12.3`과 세 모듈의 `find_spec(...) is None`을 확인했다.
- 검증되지 않은 host wheel 설치로 JetPack/CUDA/Python 환경을 변경하지 않기 위해 NVIDIA PyTorch 컨테이너를 우선 smoke test한다. 호스트 package 설치나 변경은 하지 않는다.
- 컨테이너는 **Thor 호스트의 커널과 NVIDIA GPU driver**를 사용한다. PyTorch·TorchVision 및 CUDA 관련 사용자 공간 라이브러리는 컨테이너에서 제공한다.
- 소스 코드, 데이터셋, weights, results는 호스트 경로를 bind mount로 연결해 컨테이너 삭제 후에도 보존한다. 이번 smoke test 실행 명령은 소스·weights·results를 포함하는 worktree를 `/workspace`에 읽기 전용으로, 기존 데이터셋 디렉터리를 `/datasets`에 읽기 전용으로 연결하도록 지정했다. 실제로는 OCI 컨테이너 생성 단계에서 실패해 workload가 시작되지 않았다. 원문 stdout/stderr는 호스트의 `logs/pytorch_smoke_20260915/`에 저장한다. 데이터셋을 읽거나 weights를 다운로드하지 않는다. 향후 결과 파일을 생성하는 실험에서는 호스트 results 경로를 쓰기 가능한 bind mount로 연결해야 한다.
- **JetPack 7.2.1과 image 26.08의 공식 호환성은 미확인**이다. 이번 smoke test 결과로 해당 장치에서의 환경 채택 여부를 판단하며, 실측 성공은 이 장치에서의 동작성 확인이지 공식 호환성 보증이 아니다.
- 최종 실험에는 image tag와 실제 image digest, 실행 명령, GPU 전달 방식, PyTorch·TorchVision·CUDA·cuDNN 버전을 함께 기록한다.
- **image pull 시간과 container 시작 시간은 향후 추론 latency 및 throughput 측정 구간에서 제외**한다. 이번에는 latency/throughput profiling을 수행하지 않는다.

## 7. 재개한 사전 점검 및 arm64 manifest 확인

2026-09-15 (Asia/Seoul), 최초 HEAD `8bc94f1299746a4b86d066f6aac50e6682b0e256`.

| 항목 | 실제 확인 결과 |
| --- | --- |
| worktree | `/home/ainet/research/thor-mec-inference-split` |
| branch / upstream | `split-inference` / `origin/split-inference` |
| 시작 git status | clean, `## split-inference...origin/split-inference` |
| Docker Client / Server | 모두 `29.7.2`, `linux/arm64`, API `1.55` |
| NVIDIA runtime | `nvidia` 등록, path `nvidia-container-runtime` |
| default runtime | `runc` (변경하지 않음) |
| CDI | `nvidia.com/gpu=0`, `nvidia.com/gpu=all`, `nvidia.com/pva=0`, `nvidia.com/pva=all`; exit 0 |
| 루트 파일시스템 | total `1,004,162,105,344` bytes; available `839,012,724,736` bytes; 12% used (pull 전) |
| 기존 대상 이미지 | `docker image ls`에 행 없음, 로컬 미보유 |
| 대상 tag | `nvcr.io/nvidia/pytorch:26.08-py3` |
| 실제 manifest 조회 | exit 0; OCI index에 `linux/amd64`, **`linux/arm64`** 존재 |
| arm64 child manifest digest | `sha256:237ecf9ac7373daf91b31bb4f86651ce1ce57b676366ed435aa1aba61dad81d5` |
| amd64 child manifest digest | `sha256:33ef5fc15e8937602d64022209cdb2777b32dadf742f41332023d946041b3c14` |

### 실제 사전 점검 명령

저장소 명령은 위 worktree에서 실행했다. 모든 Docker 명령은 **sudo 없이** 실행했다.

```bash
pwd
git branch --show-current
git status --short --branch
git rev-parse HEAD
git rev-parse --abbrev-ref --symbolic-full-name '@{upstream}'
docker version
docker info --format '{{json .Runtimes}} {{json .DefaultRuntime}}'
nvidia-ctk cdi list
df -B1 /
docker image ls --digests --no-trunc nvcr.io/nvidia/pytorch:26.08-py3
docker manifest inspect nvcr.io/nvidia/pytorch:26.08-py3
python3 -c 'import importlib.util, sys; print(sys.version); print({n: importlib.util.find_spec(n) is not None for n in ("pip", "torch", "torchvision")})'
```

### 실행 sandbox 제한 기록

최초 sandbox 내부에서 아래 세 명령은 각각 **exit 1**이었고, 공통 오류 원문은 다음과 같다.

```bash
docker version
docker info --format '{{json .Runtimes}} {{json .DefaultRuntime}}'
docker image ls --digests --no-trunc nvcr.io/nvidia/pytorch:26.08-py3
```

```text
permission denied while trying to connect to the docker API at unix:///var/run/docker.sock
```

실패 단계는 **sandbox 내부 Docker daemon 접근**이다. 출력 수집 도구가 stdout/stderr를 합쳐 반환했으므로 최초 출력의 stream별 원본 파일은 없다. Client 정보는 출력됐지만 Server 정보는 없었고, info의 `null ""`는 유효한 runtime 조회 결과가 아니다.
실행 환경의 sandbox 외부 재조회 승인 후 **동일 명령이 모두 exit 0**으로 성공했다. sudo·chmod·chown·setfacl·usermod, Docker daemon/default runtime 설정 변경은 없었다. 이는 host 권한이나 runtime 재설정으로 우회한 것이 아니라 실행 sandbox 제한의 해소다.


## 8. Image pull 성공 및 로컬 이미지 확인

**pull 전** 섹션 7의 실제 manifest에서 `linux/arm64`를 확인한 후 아래 명령을 실행했다.

```bash
docker pull --platform=linux/arm64 nvcr.io/nvidia/pytorch:26.08-py3 > logs/pytorch_smoke_20260915/pull.stdout.log 2> logs/pytorch_smoke_20260915/pull.stderr.log
docker image inspect nvcr.io/nvidia/pytorch:26.08-py3 --format '{{json .}}' > logs/pytorch_smoke_20260915/image.inspect.json 2> logs/pytorch_smoke_20260915/image.inspect.stderr.log
docker system df -v > logs/pytorch_smoke_20260915/docker-system-df.stdout.log 2> logs/pytorch_smoke_20260915/docker-system-df.stderr.log
```

위 세 명령은 모두 **exit 0**, stderr는 모두 **0 bytes**였다.

| 항목 | 실제 결과 |
| --- | --- |
| image tag | `nvcr.io/nvidia/pytorch:26.08-py3` |
| image ID (`docker image inspect .Id`) | `sha256:3becd068f49bd2ad38f90db5f9a4803019a76933a24e63d821376c44e7a9200a` |
| RepoDigest | `nvcr.io/nvidia/pytorch@sha256:3becd068f49bd2ad38f90db5f9a4803019a76933a24e63d821376c44e7a9200a` |
| descriptor media type | `application/vnd.oci.image.index.v1+json` |
| image architecture / OS | **arm64 / linux** |
| Docker가 보고한 로컬 디스크 사용량 (`docker system df -v`) | SIZE **38.6 GB**, UNIQUE SIZE **38.57 GB**, SHARED SIZE **0 B**; Docker 출력의 반올림된 값 |
| 별도 metadata 값 (`docker image inspect .Size`) | **11,962,276,999 bytes**; 위 로컬 디스크 사용량과 구분 |
| pull/run 시도 후 루트 가용 공간 | **800,429,301,760 bytes** (`df -B1 /`); 파일시스템 차이는 다른 쓰기를 포함할 수 있어 이미지 단독 크기로 사용하지 않음 |

이 Docker backend에서 관찰한 image ID와 RepoDigest의 hash는 동일하다. image index digest와 섹션 7의 arm64 child manifest digest를 구분한다. 실행은 tag 변동을 피하도록 **실제 RepoDigest**를 지정하고 `--pull=never --platform=linux/arm64`를 사용했다.

pull 마지막 출력:

```text
Digest: sha256:3becd068f49bd2ad38f90db5f9a4803019a76933a24e63d821376c44e7a9200a
Status: Downloaded newer image for nvcr.io/nvidia/pytorch:26.08-py3
nvcr.io/nvidia/pytorch:26.08-py3
```

## 9. GPU smoke test 실패 — OCI 컨테이너 생성 단계에서 중단

### 실제 실행 명령과 입력 스크립트

GPU 전달은 요청된 **`--runtime=nvidia` 및 `-e NVIDIA_VISIBLE_DEVICES=nvidia.com/gpu=all`**을 사용했다. default runtime은 변경하지 않았다. 컨테이너 외부 네트워크는 `--network=none`으로 지정했다.

아래 명령은 worktree에서 **1회 실행**했다. `logs/`는 Git 제외 경로이며 원본 스크립트와 stdout/stderr를 로컬에 보존했다.

```bash
docker run --rm --pull=never --platform=linux/arm64 --runtime=nvidia -e NVIDIA_VISIBLE_DEVICES=nvidia.com/gpu=all --network=none --mount type=bind,src=/home/ainet/research/thor-mec-inference-split,dst=/workspace,readonly --mount type=bind,src=/home/ainet/datasets/imagenet1k,dst=/datasets,readonly -w /workspace -i nvcr.io/nvidia/pytorch@sha256:3becd068f49bd2ad38f90db5f9a4803019a76933a24e63d821376c44e7a9200a python -u - < logs/pytorch_smoke_20260915/gpu_smoke.py > logs/pytorch_smoke_20260915/gpu_smoke.stdout.log 2> logs/pytorch_smoke_20260915/gpu_smoke.stderr.log
```

표준입력으로 전달한 `gpu_smoke.py` 원문은 다음과 같다. **컨테이너 생성 실패로 이 Python 코드는 실행되지 않았다.**

```python
import sys
import torch
import torchvision

print("Python:", sys.version, flush=True)
print("PyTorch:", torch.__version__, flush=True)
print("TorchVision:", torchvision.__version__, flush=True)
print("torch.version.cuda:", torch.version.cuda, flush=True)
print("cuDNN:", torch.backends.cudnn.version(), flush=True)
print("torch.cuda.is_available():", torch.cuda.is_available(), flush=True)
print("torch.cuda.device_count():", torch.cuda.device_count(), flush=True)
assert torch.cuda.is_available(), "CUDA is unavailable"
assert torch.cuda.device_count() > 0, "No CUDA device"
for i in range(torch.cuda.device_count()):
    print("GPU:", i, torch.cuda.get_device_name(i), "capability:", torch.cuda.get_device_capability(i), flush=True)
a = torch.arange(16, dtype=torch.float32, device="cuda").reshape(4, 4)
b = torch.eye(4, dtype=torch.float32, device="cuda")
c = a @ b
torch.cuda.synchronize()
actual = c.cpu()
expected = torch.arange(16, dtype=torch.float32).reshape(4, 4)
torch.testing.assert_close(actual, expected, rtol=0, atol=0)
print("CUDA matmul CPU sample:", actual[:2].tolist(), flush=True)
print("GPU_SMOKE_PASS", flush=True)
```

### 실패 원문 및 판정

- 실패 단계: **OCI runtime create / CDI GPU device injection**, Python 시작 전.
- Docker 명령 exit code: **127**.
- stdout: **비어 있음 (0 bytes)**.
- stderr: 아래 원문 그대로 보존. 로컬 원본은 `logs/pytorch_smoke_20260915/gpu_smoke.stderr.log`.

```text
docker: Error response from daemon: failed to create task for container: failed to create shim task: OCI runtime create failed: could not apply required modification to OCI specification: error modifying OCI spec: failed to inject CDI devices: failed to inject devices: failed to stat CDI host device "/dev/dri/card0": no such file or directory

Run 'docker run --help' for more information
```

오류는 CDI가 요구한 호스트 장치 `/dev/dri/card0`의 stat 실패를 명시한다. CDI 목록 조회 성공과 runtime 등록만으로 실제 장치 주입 성공을 보장할 수 없다는 것이 이번 결과다. 해당 장치가 없는 이유나 CDI spec의 원인은 추가 조사하지 않았으며 추정하지 않는다. 이 실패로 PyTorch 자체의 Thor 호환 여부를 판단할 수 없다.

| 검증 항목 | 이번 결과 |
| --- | --- |
| Docker daemon 연결 | 성공 (sandbox 외부, sudo 없음) |
| 대상 이미지 arm64 확인 / pull | 성공 / 성공 |
| NVIDIA GPU runtime 컨테이너 생성 | **실패**, exit 127 |
| 컨테이너 Python / PyTorch / TorchVision 버전 | **미확인**, Python 시작 전 실패 |
| `torch.version.cuda` / cuDNN 버전 | **미확인**, 실행되지 않음; 호스트 버전으로 대체하지 않음 |
| `torch.cuda.is_available()` / device count | **미확인**, 실행되지 않음 |
| GPU 이름 / capability | **미확인**, 컨테이너에서 조회하지 못함 |
| 작은 CUDA tensor 행렬곱 / synchronize / CPU 결과 확인 | **미실행** |
| `torchvision.models.efficientnet_v2_s` 존재 확인 | **미실행**, 최소 GPU smoke test 실패로 후속 단계 차단 |
| EfficientNetV2-S `weights=None`, `eval()`, `[1,3,384,384]`, inference mode CUDA forward | **미실행**, 성공 주장 없음 |
| 출력 `[1,1000]` 확인 | **미실행** |
| CUDA OOM | 발생한 것으로 관찰되지 않음; CUDA 실행 단계에 도달하지 못함 |
| JetPack 7.2.1 / image 26.08 공식 호환성 | **미확인** |
| 이번 채택 판정 | **보류** — 해당 GPU 전달 명령으로 workload를 시작하지 못함 |

실패 후 package 설치, 다른 image pull, runtime/CDI 재설정, 재시도 등의 우회 조치는 하지 않고 검증을 중단했다. pretrained weight 다운로드, ImageNet ZIP 해제·accuracy 측정, P0–P9 분할 검증, latency/throughput profiling, 실제 그래프 생성은 모두 미실행이다. 모델 생성 및 forward는 **0회**다.

이번 결과는 이미지 pull 성공과 GPU 주입 실패를 구분한 환경 검증 기록이다. 향후 smoke test가 성공하더라도 **해당 장치에서의 동작성 확인이지 JetPack 7.2.1과 image 26.08의 공식 호환성 보증이 아니다**. 이번 작업에서는 동작성 성공도 아직 확인하지 못했다.
