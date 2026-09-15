# Thor EfficientNetV2-S GPU 처리시간 실측

**Thor 단독 GPU 처리시간이며 네트워크·서버·E2E 지연이 아니다.**

## 조건과 재현 정보

- 측정일: 2026-09-15, 18:22:02–18:23:30 KST (metadata의 UTC 시작/종료 시각; 처리시간은 아래 CUDA Event 값).
- 시작 branch `split-inference`, HEAD/upstream `1403a4685480f24a463bf12c3bcb56423e33c3ea`, 작업 트리 clean 확인 후 구현했다. 기존 [분할 구현](../src/common/efficientnet_v2_s_partitions.py)과 [공식 manifest](../manifests/efficientnet_v2_s_p0_p9.json)는 변경하지 않았다.
- NVIDIA Thor, driver `595.78`, 호스트 NVIDIA-SMI CUDA 표시 `13.2`. Python `3.12.3`, PyTorch `2.14.0a0+4fdf77b940.nv26.08`, TorchVision `0.29.0a0+0bc41e67.nv26.08`, 컨테이너 `torch.version.cuda=13.4`, cuDNN API 반환값 `92500`.
- 기존 image tag `nvcr.io/nvidia/pytorch:26.08-py3`, 실제 RepoDigest `nvcr.io/nvidia/pytorch@sha256:3becd068f49bd2ad38f90db5f9a4803019a76933a24e63d821376c44e7a9200a`, linux/arm64. `--pull=never`, 일반 NVIDIA runtime, 외부 네트워크 차단.
- `nvpmodel -q`: **MAXN, mode 0** (측정 전/후 동일). `jetson_clocks --show`: exit 1, stdout `Error: Run this script(/usr/bin/jetson_clocks) as a root user`, stderr 없음. optional clock 조회는 unavailable로 기록하고 sudo 재시도나 설정 변경은 하지 않았다. 클럭 고정 여부는 미확인이다.
- 측정 직전 18:21:20 GPU 온도 42°C, GPU utilization 0%, MIG current/pending Disabled, compute-process 목록 비어 있음. 종료 후 18:24:26 조회는 46°C, GPU utilization 0%, compute-process 목록 비어 있음. Xorg/gnome-shell/nautilus 그래픽 프로세스는 유지됐다. 이 두 온도는 시점 관측값이며 측정 중 최고 온도나 무간섭 보증이 아니다.
- `weights=None`, `torch.manual_seed(0)`, 하나의 모델과 CUDA `torch.randn([1,3,384,384])`, batch 1, FP32, `model.eval()`, `torch.inference_mode()`. TF32 비활성화, **cuDNN benchmark 활성화**. torch.compile/TensorRT, 데이터셋, pretrained weights는 사용하지 않았다.
- 실행 전 기존 [P0–P9 검증](../scripts/verify_efficientnet_v2_s_partitions.py)을 다시 통과했다: exit 0, stderr 0 bytes, 모든 shape 일치 및 모든 logits max absolute/relative difference 0. 이 사전 검증은 기존 스크립트의 cuDNN benchmark=False 조건이며, 처리시간 실측은 요청대로 True다.

## 측정 방법과 표본

[실측 스크립트](../scripts/profile_efficientnet_v2_s_thor.py)는 모델과 manifest를 그대로 참조한다. 그룹 입력은 앞선 그룹을 한 번씩 실행해 모두 미리 생성하고 저장한다. 각 G는 해당 입력으로 독립 실행한다. 각 P1–P9는 모델 입력에서 해당 Thor 담당 구간을 직접 실행하여 측정한다.

각 대상에 warm-up **100회**, 이후 **5 rounds × 200회 = 1,000개** 측정 표본을 수집했다. 전체 실측은 18,000개, warm-up 원본은 1,800개다. warm-up은 별도 phase로 보존하며 통계에서 제외한다. 18개 대상(G1–G9 및 P1–P9)을 round마다 seed 1–5로 섞었고 실제 순서는 metadata에 저장했다. warm-up 순서는 seed 0으로 섞었다.

동일 CUDA stream에서 `start.record() → 해당 구간 실행 → end.record()` 후 `end.synchronize()` 및 `start.elapsed_time(end)`로 **ms**를 얻는다. Event 생성·입력 생성·CPU–GPU 복사·파일 I/O·host synchronize 대기는 구간 밖이다. CUDA Event는 eager 실행의 device timeline을 측정하므로 구간 내부 kernel launch 사이의 GPU idle gap이 포함될 수 있다. 개별 kernel duration의 합을 뜻하지 않는다. `time.perf_counter()`는 사용하지 않았다.

P0는 모델 연산이 없어 **정의상 0 ms, n=0**이다. 가짜 1,000개 표본을 만들지 않았다. mean/median/p95/std는 warm-up을 제외한 모든 유효 표본에서 계산했고 std는 `ddof=1`, quantile은 linear 방식이다. p99는 metadata에 별도 보존했다. outlier를 제거하거나 보간하지 않았다.

## G1–G9 요약

단위 ms, 각 행 n=1,000. 출력 bytes는 실제 FP32 tensor의 `numel() * element_size()`다.

| Group | mean | median | p95 | std | output bytes |
| --- | ---: | ---: | ---: | ---: | ---: |
| G1 | 0.083044 | 0.082528 | 0.087650 | 0.002767 | 3,538,944 |
| G2 | 1.104075 | 1.102736 | 1.114403 | 0.005166 | 3,538,944 |
| G3 | 2.215825 | 2.208816 | 2.248936 | 0.017581 | 1,769,472 |
| G4 | 0.963872 | 0.960576 | 0.984459 | 0.009051 | 589,824 |
| G5 | 1.116817 | 1.113136 | 1.142536 | 0.021520 | 294,912 |
| G6 | 2.754456 | 2.728512 | 2.797733 | 0.082267 | 368,640 |
| G7 | 4.877744 | 4.901152 | 4.931426 | 0.050619 | 147,456 |
| G8 | 0.073843 | 0.072896 | 0.079427 | 0.004626 | 5,120 |
| G9 | 0.041418 | 0.040704 | 0.045216 | 0.006484 | 4,000 |

## P0–P9 Thor 누적 처리시간

단위 ms. P1–P9 각 행 n=1,000; P0는 위 정의에 따라 n=0이다. 모든 누적 시간은 해당 구간의 직접 실행 결과다.

| Point | mean | median | p95 | std | activation bytes |
| --- | ---: | ---: | ---: | ---: | ---: |
| P0 | 0.000000 | 0.000000 | 0.000000 | 0.000000 | 1,769,472 |
| P1 | 0.083103 | 0.082528 | 0.087334 | 0.002679 | 3,538,944 |
| P2 | 1.161945 | 1.160352 | 1.174374 | 0.005315 | 3,538,944 |
| P3 | 3.315355 | 3.309008 | 3.346410 | 0.019837 | 1,769,472 |
| P4 | 4.275715 | 4.268592 | 4.310181 | 0.037972 | 589,824 |
| P5 | 5.467807 | 5.462704 | 5.529779 | 0.031928 | 294,912 |
| P6 | 8.535286 | 8.538576 | 8.588334 | 0.036968 | 368,640 |
| P7 | 13.384061 | 13.382400 | 13.458453 | 0.052542 | 147,456 |
| P8 | 13.487746 | 13.437216 | 13.805092 | 0.219295 | 5,120 |
| P9 | 13.467527 | 13.465376 | 13.548337 | 0.046795 | 4,000 |

그룹 평균 합 **13.231093 ms**, P9 직접 측정 평균 **13.467527 ms**. `그룹 합 − P9`는 **−0.236434 ms (P9 대비 −1.755587%)**다. 일치를 강제하지 않았으며 P8/P9 평균 순서도 관측 그대로 유지했다.

**G9 출력 4,000 bytes는 그룹 출력 크기이며, P9는 local-only이므로 실제 E2E 실험의 업링크 데이터는 0 bytes다.**

## 결과·그림 검증 및 로컬 보존

결과 디렉터리: `split_inference/results/thor_processing_profile/20260915T181507/` (timestamp는 사전 점검 시작 기준).

- `raw_samples.csv`: phase별 warm-up/measurement, 대상, round, 순서, sample index, duration_ms.
- `group_summary.csv`, `partition_summary.csv`: 지정 열의 요약 및 실제 shape/bytes.
- `metadata.json`: 이미지·패키지·사전 환경·실행 명령·seed·round 순서·source hash·p99·그룹 합/P9 차이.
- `group_processing_output_size.png` (300 DPI), `group_processing_output_size.pdf`: G1–G9 평균 처리시간 bar와 실측 출력 크기. 오른쪽 **MB = 1,000,000 bytes**. 축은 `Layer group`, `Processing time (ms)`, `Output data size (MB)`이며 범례는 `Thor processing time`, `Output data size`다.

모든 G1–G9/P1–P9에서 정확히 1,000개 유효 표본 및 round별 200개를 확인했다. NaN·음수·누락이 없고 모든 shape/bytes는 manifest와 일치하며 P9 출력은 `[1,1000]`이다. 호스트에서 원시 CSV를 독립 재독해 mean/median/p95/sample std 및 표본 수를 재계산하여 요약 CSV와 대조했다. Docker 측정 exit 0, stderr 0 bytes, `THOR_PROCESSING_PROFILE_PASS`를 확인했다.

PNG를 직접 확인한 뒤 데이터와 겹치던 범례를 위쪽 가운데로 옮겨 **동일 요약 CSV로 그림만 재생성**했다. 측정 조건·표본·통계는 변경하지 않았다. metadata의 측정 source hash를 유지하고 figure source hash를 별도 기록했다. 측정 시점 스크립트는 `logs/thor_profile_20260915T181507/profile_measured.py`에 보존했다. 측정/검증 stdout·stderr, 전후 환경 원문, 재그림 스크립트는 같은 logs 디렉터리에 보존한다.

결과 경로 전체는 `/results/thor_processing_profile/`이라는 좁은 ignore 규칙으로 Git에서 제외한다. 이미지·CSV·JSON·logs·PNG·PDF는 커밋하지 않는다.

## 실제 명령

모든 명령은 worktree에서 sudo 없이 실행했다. 측정용 로컬 결과 디렉터리를 먼저 생성하고, 해당 디렉터리만 `/output`으로 쓰기 가능하게 bind mount했다. 소스는 읽기 전용이다.

사전 정확성 검증:

```bash
docker run --rm --pull=never --runtime=nvidia -e NVIDIA_VISIBLE_DEVICES=all -e NVIDIA_DRIVER_CAPABILITIES=compute,utility -e PYTHONPATH=/workspace --network=none -v "$PWD":/workspace:ro -w /workspace nvcr.io/nvidia/pytorch@sha256:3becd068f49bd2ad38f90db5f9a4803019a76933a24e63d821376c44e7a9200a python -B split_inference/scripts/verify_efficientnet_v2_s_partitions.py > logs/thor_profile_20260915T181507/verify.stdout.log 2> logs/thor_profile_20260915T181507/verify.stderr.log
```

처리시간 측정:

```bash
docker run --rm --pull=never --runtime=nvidia -e NVIDIA_VISIBLE_DEVICES=all -e NVIDIA_DRIVER_CAPABILITIES=compute,utility -e PYTHONPATH=/workspace --network=none -v "$PWD":/workspace:ro -v "$PWD/split_inference/results/thor_processing_profile/20260915T181507":/output -w /workspace nvcr.io/nvidia/pytorch@sha256:3becd068f49bd2ad38f90db5f9a4803019a76933a24e63d821376c44e7a9200a python -B split_inference/scripts/profile_efficientnet_v2_s_thor.py --output /output --preflight /workspace/logs/thor_profile_20260915T181507/preflight_before_profile.json --verification-log /workspace/logs/thor_profile_20260915T181507/verify.stdout.log --host-command /workspace/logs/thor_profile_20260915T181507/profile.command.txt --image nvcr.io/nvidia/pytorch@sha256:3becd068f49bd2ad38f90db5f9a4803019a76933a24e63d821376c44e7a9200a > logs/thor_profile_20260915T181507/profile.stdout.log 2> logs/thor_profile_20260915T181507/profile.stderr.log
```

사전 점검 JSON은 명령별 `command`, `exit_code`, `stdout`, `stderr`와 시작 Git 상태를 포함한다. `--host-command`는 기록할 실제 Docker 명령을 저장한 텍스트 파일 경로다. 재실행 시 새 결과 디렉터리와 최신 사전 환경/검증 로그를 사용해야 하며 기존 결과를 덮어쓰지 않는다.

JetPack 7.2.1과 이미지 26.08의 공식 호환성은 여전히 미확인이다. 이 결과는 기록된 Thor 환경에서의 실측이며 다른 전력·클럭·백그라운드 부하 조건으로 일반화하지 않는다. image pull 및 컨테이너 시작은 처리시간에 포함되지 않는다.
