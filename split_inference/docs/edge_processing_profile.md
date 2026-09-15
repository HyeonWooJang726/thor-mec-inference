# EfficientNetV2-S Edge GPU 잔여 처리시간

**RTX 5070 Ti의 실제 WSL/Linux 실행환경에서 직접 측정한 Edge GPU 잔여 연산시간이다. 아직 E2E 지연이나 처리량 측정 결과가 아니다.**

## 분할 정의와 결과

기존 [분할 모듈](../src/common/efficientnet_v2_s_partitions.py)과 [manifest](../manifests/efficientnet_v2_s_p0_p9.json)를 변경 없이 사용했다.
G1–G7은 각각 `features[0]`–`features[6]`, G8은 `features[7] → avgpool → flatten`, G9는 `classifier`다.
각 P0–P8은 `partitions.suffix(activation, point)`로 해당 잔여 구간 전체를 직접 실행했다. 개별 그룹 시간의 합을 사용하지 않았다.

단위 **ms**, std는 표본 표준편차(`ddof=1`). 모든 warm-up은 아래 통계에서 제외하되 원본에 보존했다.

| Point | Edge 잔여 구간 | mean | median | p95 | std | n | 경계 activation shape | bytes |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- | ---: |
| P0 | G1–G9 | 8.847000 | 8.497744 | 10.831811 | 1.085948 | 1000 | `[1, 3, 384, 384]` | 1,769,472 |
| P1 | G2–G9 | 8.667827 | 8.405792 | 10.513072 | 0.962709 | 1000 | `[1, 24, 192, 192]` | 3,538,944 |
| P2 | G3–G9 | 8.497883 | 8.250096 | 9.929271 | 0.790711 | 1000 | `[1, 24, 192, 192]` | 3,538,944 |
| P3 | G4–G9 | 8.106785 | 7.850704 | 9.769323 | 0.934598 | 1000 | `[1, 48, 96, 96]` | 1,769,472 |
| P4 | G5–G9 | 7.749134 | 7.504144 | 9.173378 | 0.819182 | 1000 | `[1, 64, 48, 48]` | 589,824 |
| P5 | G6–G9 | 6.518471 | 6.309872 | 7.587637 | 0.710597 | 1000 | `[1, 128, 24, 24]` | 294,912 |
| P6 | G7–G9 | 4.498695 | 4.332544 | 5.384947 | 0.570851 | 1000 | `[1, 160, 24, 24]` | 368,640 |
| P7 | G8–G9 | 0.115432 | 0.102960 | 0.200365 | 0.051030 | 1000 | `[1, 256, 12, 12]` | 147,456 |
| P8 | G9 | 0.047009 | 0.037376 | 0.066005 | 0.155156 | 1000 | `[1, 1280]` | 5,120 |
| P9 | 없음 | 0.000000 | 0.000000 | 0.000000 | 0.000000 | 0 | `[1, 1000]` | 4,000 |

P9는 **Edge 처리 없음에 따른 정의상 0 ms, n=0**이다. 가짜 표본은 만들지 않았다. P9의 `[1,1000]`, 4,000 bytes는 모델 출력 경계의 크기이며, Edge 입력이나 네트워크 전송량이 아니다.

## 환경과 설치 범위

- 측정일: 2026-09-15. 전체 실행 19:25:56–19:27:05 KST, warm-up 및 실측 19:26:05–19:27:05 KST. 정확한 UTC 시각은 metadata에 보존했다.
- 호스트 `CY415AINET`, Linux x86_64, WSL2 `6.18.33.2-microsoft-standard-WSL2`, Intel Core Ultra 7 265K, 논리 CPU 20개.
- GPU `NVIDIA GeForce RTX 5070 Ti`, driver `595.95`, driver model **WDDM**, compute capability **12.0**, wheel architecture 목록에 `sm_120` 포함.
- 전용 Python 환경 `/home/ainet/venvs/efficientnet-v2-s-cu132`, Python `3.12.3`, `include-system-site-packages=false`. 생성 전 해당 경로가 없었고 가용 공간은 약 922 GiB였다.
- **PyTorch `2.13.0+cu132`, TorchVision `0.28.0+cu132`, `torch.version.cuda=13.2`, cuDNN API 반환값 `92000`**. 설치된 cuDNN wheel은 `nvidia-cudnn-cu13==9.20.0.48`, NumPy `2.5.2`다. 전체 package version은 metadata의 `pip_freeze`와 로컬 설치 로그에 있다.
- 사용자 승인으로 위 전용 환경에 공식 CUDA wheel과 해당 wheel의 필수 의존성만 설치했다. torchaudio는 설치하지 않았다. 기존 시스템 Python, Windows Python, 저장소 venv, 서버 실험환경, OS CUDA/driver를 변경하지 않았다. Docker는 사용하지 않았다.
- 기준 commit `8f4d9fc6672264f9c2406518c669bcb732fd4613`. 필수 commit `1403a4685480f24a463bf12c3bcb56423e33c3ea`와 `8f4d9fc6672264f9c2406518c669bcb732fd4613` 포함을 확인했다. 별도 `profile-efficientnet-v2-s-edge` worktree에서 구현·실행했다. 측정 당시 새 스크립트는 미커밋 상태였으며 소스 SHA-256과 실행본을 로컬에 보존했다.

공식 [torch wheel index](https://download.pytorch.org/whl/cu132/torch/)와 [torchvision wheel index](https://download.pytorch.org/whl/cu132/torchvision/)를 사용했다. 설치 명령:

```bash
python3 -m venv /home/ainet/venvs/efficientnet-v2-s-cu132
/home/ainet/venvs/efficientnet-v2-s-cu132/bin/python -m pip --isolated --disable-pip-version-check --log /home/ainet/venvs/efficientnet-v2-s-cu132/install.log install --no-cache-dir torch==2.13.0 torchvision==0.28.0 --index-url https://download.pytorch.org/whl/cu132
```

**첫 번째 명령은 경로가 없음을 확인한 뒤 새로 생성할 때만 사용한다.** 이미 생성한 환경을 덮어쓰거나 재설치하는 절차가 아니다. `pip check`는 `No broken requirements found`로 통과했다.

## 측정조건과 타이밍 범위

- `torchvision.models.efficientnet_v2_s(weights=None)`, `torch.manual_seed(0)`, batch 1, `[1,3,384,384]`, FP32, `model.eval()`, `torch.inference_mode()`.
- 입력은 Edge GPU에서 생성한 seed 0의 `torch.randn` tensor다. 학습된 weight나 ImageNet 정확성 평가가 아니다.
- CUDA matmul 및 cuDNN TF32 비활성화, **cuDNN benchmark=True**. torch.compile, CUDA Graph, TensorRT는 사용하지 않았다.
- 동일 모델의 `prefix(x, point)`를 실행해 P1–P8 activation을 미리 생성했다. activation을 GPU에 유지하고 prefix 생성은 타이밍 밖에서 수행했다.
- 대상별 warm-up 100회, 이후 **5 rounds × 200회 = 1,000개**. P0–P8 합계 본 표본 **9,000개**, warm-up **900개**. warm-up 순서는 seed 0, 각 round 순서는 seed 1–5로 섞고 metadata에 실제 순서를 저장했다.
- 같은 CUDA stream에서 `start.record() → suffix(...) → end.record()` 후 `end.synchronize()` 및 `start.elapsed_time(end)`로 측정했다. Event를 미리 생성·초기화했고 host 동기화 대기와 파일 기록은 interval 밖이다. 전체 실행 경과시간 기록에는 monotonic clock을 사용했다.
- **네트워크, 직렬화·역직렬화, CPU–GPU 복사, 서버 queue, 요청 프레임워크, activation 생성은 제외**했다. CUDA Event의 eager device timeline에는 host kernel launch 사이 GPU idle gap이 포함될 수 있다. 격리된 개별 kernel duration의 합을 뜻하지 않는다.
- p95/p99는 linear interpolation, std는 `ddof=1`. p99·min·max도 요약 CSV에 있다. NaN·음수·분할점 누락·중복 ID·round별 표본 수 오류는 실패 처리한다. 이상치 제거, 임의 차감, 보간으로 누락된 표본 채우기를 하지 않았다.

## 정확성 및 모델 식별

1. import, CUDA availability, GPU 이름, runtime/cuDNN/capability, 간단한 CUDA tensor 연산과 synchronize, EfficientNetV2-S CUDA FP32 forward가 모두 통과했다. Python warnings를 오류로 취급했고 실행 stderr는 0 bytes였다. CUDA architecture 경고나 kernel incompatibility가 없었다.
2. 기존 [검증 스크립트](../scripts/verify_efficientnet_v2_s_partitions.py)를 CUDA에서 변경 없이 실행했다. 기존 조건인 cuDNN benchmark=False에서 `ALL_P0_P9_PASS`, exit 0, stderr 0 bytes였다.
3. 실측에 사용할 동일 모델을 cuDNN benchmark=True에서 추가 검증했다. 아래 결과는 두 검증 모두에 해당한다.

| Point | 재결합 출력 shape | max_abs_diff | max_rel_diff | tolerance | activation shape/bytes |
| --- | --- | ---: | ---: | --- | --- |
| P0 | `[1,1000]` | 0 | 0 | PASS | PASS |
| P1 | `[1,1000]` | 0 | 0 | PASS | PASS |
| P2 | `[1,1000]` | 0 | 0 | PASS | PASS |
| P3 | `[1,1000]` | 0 | 0 | PASS | PASS |
| P4 | `[1,1000]` | 0 | 0 | PASS | PASS |
| P5 | `[1,1000]` | 0 | 0 | PASS | PASS |
| P6 | `[1,1000]` | 0 | 0 | PASS | PASS |
| P7 | `[1,1000]` | 0 | 0 | PASS | PASS |
| P8 | `[1,1000]` | 0 | 0 | PASS | PASS |
| P9 | `[1,1000]` | 0 | 0 | PASS | PASS |

기존 tolerance `rtol=1e-5`, `atol=1e-6`, relative-error denominator floor `1e-8`를 유지했다.
manifest에는 point별 byte 필드가 없으므로, 명시된 FP32 shape에서 `prod(shape) × 4`로 기대 bytes를 계산하여 실제 tensor의 `numel() × element_size()`와 비교했다.

측정 모델의 state_dict SHA-256:

```text
436cd0fd18cc91ead9ba89df52c49a0b5e7f7b2bcc2c25ba0bbe1fe02336ab4d
```

해시 방법은 key 정렬 후 각 tensor의 `[name,dtype,shape]`를 compact JSON UTF-8와 LF로 넣고, contiguous CPU tensor의 C-order bytes를 이어 SHA-256으로 계산한다. 이 환경의 byte order는 little-endian이다. parameter와 buffer를 모두 포함한다. 대용량 checkpoint는 Git에 추가하지 않았다.

## 전력·클럭 및 측정 한계

- 전후 관찰 성능 상태 P0, 전력 제한 300 W, persistence Enabled, compute mode Default, MIG current/pending N/A. GPU/CPU clock·전력·MIG·네트워크 설정을 변경하지 않았다.
- 실측 직전/직후 GPU 온도 34/40°C, graphics clock 2917/2902 MHz, memory clock 14001/14001 MHz, 평균 전력 snapshot 71.60/109.31 W였다. 이는 두 시점의 관찰값이며 측정 전체 평균·최댓값이 아니다.
- **클럭을 고정하지 않았으며 기존 lock 상태는 확인 불가**다. CPU cpufreq sysfs 항목이 노출되지 않아 CPU governor/clock은 unavailable로 기록했다. EMC clock은 Jetson 플랫폼이 아니므로 해당 조회가 없다.
- CUDA 초기화 전 compute-process 목록은 비어 있었다. 실측 직전에는 PID 5134만 보고됐고, host `ps`로 이 측정 프로세스임을 확인했다. 화면은 활성화돼 있었으며 WSL/WDDM에서 process name과 memory 정보가 `[Not Found]`/`[N/A]`로 표시됐다. 다른 GPU 작업이 완전히 없었다고 보증하지 않는다.
- P8의 최대 표본은 **4.886016 ms**, median **0.037376 ms**, std **0.155156 ms**다. 이 큰 표본도 그대로 포함했다. 원인을 특정하지 않았으며 짧은 suffix의 분산과 WSL/WDDM 실행환경 한계를 함께 고려해야 한다.
- **Thor는 PyTorch `2.14.0a0+4fdf77b940.nv26.08` / TorchVision `0.29.0a0+0bc41e67.nv26.08`, CUDA runtime `13.4`, cuDNN `92500`이다. Edge는 PyTorch `2.13.0+cu132` / TorchVision `0.28.0+cu132`, CUDA runtime `13.2`, cuDNN `92000`이다.** 이는 실제 배포 환경의 Edge GPU 처리시간 프로파일이며, 동일 runtime을 통제한 장치 간 비교로 해석하지 않는다. [Thor 기록](thor_processing_profile.md)을 변경하지 않았다.
- 향후 Thor–Edge 연결 전에 **동일 모델 파라미터를 양쪽에 배포하고 동일 해시 규칙의 state_dict 식별값과 P0–P9 재결합 출력을 다시 검증해야 한다.** seed 0만으로 서로 다른 runtime의 초기 파라미터 동일성을 보증하지 않는다.
- 이번 결과에 전송·queue·framework 시간은 없다. 다음 단계는 위 동일 모델 검증을 포함한 **Thor–Edge 실제 분할추론 연결 및 별도 E2E 측정**이다.

## 재현 명령과 결과 보존

별도 worktree 최상위에서:

```bash
/home/ainet/venvs/efficientnet-v2-s-cu132/bin/python -B -m split_inference.scripts.profile_efficientnet_v2_s_edge
```

스크립트가 매 실행마다 UTC timestamp 디렉터리를 새로 생성하고 기존 결과를 덮어쓰지 않는다. 환경 검증 또는 정확성 검증 실패 시 실측에 진입하지 않고 오류·실패 단계·metadata를 보존한다.

이번 로컬 worktree: `/home/ainet/research/thor-mec-inference-edge-profile`

결과: `split_inference/results/edge_processing_profile/20260915T102556_751828Z/`

- `edge_suffix_samples.csv`: 9,900개 warm-up/measurement 원본, point·round·순서·sample ID·CUDA Event ms.
- `edge_suffix_summary.csv`: P0–P9 통계, n, shape/bytes, start group, p99/min/max, measured/defined provenance.
- `metadata.json`: 환경·패키지·명령·Git commit·소스 및 모델 hash·정확성·시각·실행 순서·GPU 전후 원문.
- `verification.stdout.log`, `verification.stderr.log`, `verification_process.json`: 기존 CUDA 검증 원본.
- `profile_measured.py`: 실측 실행 소스 복사본. `independent_audit.json`: CSV를 Python 표준 라이브러리로 독립 재계산한 검사 결과.
- `profile.stdout.log`, `profile.stderr.log`, `install.log`, `launch_command.json`: 실행 및 설치 원본 로그. 원래 launcher 로그도 `logs/edge_profile_20260915T102556_707313Z/`에 보존했다.

원시 CSV를 독립 재독해 모든 point의 n, round별 200개, warm-up 100개, unique sample ID, 유한·비음수 시간, manifest shape/bytes, mean/median/p95/p99/sample std/min/max를 재계산하고 요약 CSV와 일치함을 확인했다. 측정 exit 0 및 `EDGE_SUFFIX_PROCESSING_PROFILE_PASS`를 확인했다. 실패 표본이나 이상치를 제외하지 않았다.

정확한 `/split_inference/results/edge_processing_profile/` ignore 규칙으로 결과 전체를 Git에서 제외한다. CSV·JSON·로그·모델 artifact는 커밋하지 않는다. 그림은 생성하지 않았다. 기존 main 작업공간의 사용자 변경과 서버 실험 파일은 보존했다.
