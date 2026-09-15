# Single-flight split-inference latency profile

이 경로는 **single-flight closed-loop split-inference baseline**이다. persistent TCP connection 1개,
outstanding request 1개, Edge 순차 처리만 사용한다. 동시성·queueing·부하 tail latency 실험이 아니다.
기존 smoke Client와 기본 Server 동작은 그대로다. Server의 `--profile-mode` 지정 시에만 새 경로를 사용한다.

## 실행 조건과 phase

공식 `EfficientNet_V2_S_Weights.IMAGENET1K_V1` cached checkpoint, 기존 300개 선택 목록·evidence와
preprocessing, P0–P9 그룹을 재사용한다. cache가 없거나 고정 hash와 다르면 실패한다. 다운로드,
압축, FP16, 재접속, retry, fallback은 없다. 모델은 endpoint별 한 번 로드한다.
FP32, eval, inference_mode/no-grad, autocast OFF, TF32 OFF, cuDNN benchmark ON을 유지한다.

ESFP v2의 48-byte header, contiguous little-endian FP32 payload, 32-byte SHA-256 trailer를 그대로 쓴다.
양쪽에 **`--verify-payload`가 필수**다. HELLO/READY identity와 RESULT 형식은 바뀌지 않으며
Server timing은 Client에 전송하지 않는다. 같은 `--profile-run-id`와 `--profile-mode`를 양쪽에 지정한다.
wire에 phase를 추가하지 않고 양쪽의 동일한 실행 순서표에서 request ID의 phase·round·sample·split을 결정한다.
P9는 Client local-only이며 Server에 해당 request ID가 존재하면 분석이 실패한다.

| Mode | Phase | Client | Server | 정의 |
| --- | --- | ---: | ---: | --- |
| formal | preflight | 30 | 27 | samples 0,149,299 × P0–P9 |
| formal | warmup | 320 | 288 | split별 32회, 0,149,299 순환 |
| formal | measurement | 30,000 | 27,000 | 300 images × 10 rounds × P0–P9 |
| pilot | preflight | 12 | 9 | samples 0,149,299 × P0,P4,P8,P9 |
| pilot | warmup | 8 | 6 | 위 split별 2회 |
| pilot | measurement | 12 | 9 | 위 samples × splits, 1 round |

formal measurement P9는 3,000행이다. 전체 phase 합계는 formal Client 30,350/Server 27,315,
pilot Client 32/Server 24다. 각 round는 커밋된 이미지 선택 순서로 실행하며 이미지별 split 오름차순이다.
preflight가 모두 통과해야 warmup, 이어 measurement로 진행한다. rtol=1e-4, atol=1e-5의
기존 full-local-reference correctness와 finite·shape·top1 검사를 사용한다. 모든 phase의 최종 logits는
`[1,1000]` FP32 finite인지 확인한다. measurement에서 별도 reference forward를 수행하지 않는다.

## Timing 경계

모든 측정 wall duration은 각 호스트의 **`time.perf_counter_ns()`** 차이다. 원격 호스트 간 절대
timestamp를 빼지 않는다. CUDA Event는 보조값으로만 저장한다. CUDA Event 기록과 완료 동기화의
CPU overhead는 해당 DNN wall interval 안에 들어가며 event elapsed 조회는 interval 밖이다.

| CSV 열 | 정의 |
| --- | --- |
| `device_inference_wall_ms` | GPU inference-ready 입력에서 device-side DNN 실행·GPU 완료 동기화까지 |
| `device_inference_cuda_ms` | 같은 device-side DNN 실행의 CUDA Event 값; 보조값 |
| `remote_roundtrip_ms` | device activation 준비 직후부터 SHA/응답 검증·역직렬화가 끝난 CPU FP32 logits 준비까지 |
| `edge_inference_wall_ms` | 입력 H2D와 동기화 후부터 edge-side DNN 실행·GPU 완료 동기화까지 |
| `edge_inference_cuda_ms` | 같은 edge-side DNN 실행의 CUDA Event 값; 보조값 |
| `e2e_inference_ms` | inference-ready GPU 입력부터 최종 CPU FP32 logits까지 직접 측정 |

ZIP read/JPEG decode/공식 transform/초기 입력 H2D, preflight reference, 최종 correctness 비교와 CSV 쓰기는
E2E 밖이다. P0는 identity이므로 device DNN wall/CUDA=0이며 E2E와 remote의 시작이 같다.
P1–P8은 device DNN 완료 wall 경계를 remote의 시작으로 공유한다.

오프라인 병합 후 주된 네 지표는 다음과 같다. CSV와 문서에서 아래 용어를 사용한다.

- `device_inference_ms` = `device_inference_wall_ms`: **device-side inference**
- `edge_inference_ms` = `edge_inference_wall_ms`: **edge-side inference**
- `offloading_overhead_ms` = `remote_roundtrip_ms - edge_inference_wall_ms`: **offloading overhead**
- `e2e_inference_ms`: **E2E inference latency**

P0–P8의 device + remote = E2E를 검증한다. offloading overhead는 activation 변환, 검증,
SHA-256, TCP/protocol 처리, Edge H2D·logits D2H 및 기타 endpoint overhead를 포함한다.
**순수 network latency가 아니다.** SHA/send/receive/pack/unpack 등으로 더 세분화하지 않는다.
P9는 `network_used=false`, wire bytes=0이고 remote·edge·offloading 관련 값은 `NA`다.
P9 E2E에는 최종 logits D2H가 들어가므로 device wall과 같다고 가정하지 않는다.

## 결과와 무결성

새 ignored `split_inference/results/split_latency_profile/<RUN_ID>/` 아래에 저장한다.
각 endpoint는 기존에 없는 `client/`, `server/` 디렉터리를 생성하고 `run_manifest.json`, `stderr.log`를 쓴다.
Client는 `client_raw.csv`, `correctness.csv`; Server는 `server_raw.csv`, `ready.json`을 추가한다.
CSV의 preflight/warmup/measurement는 모두 보존한다. Server 로컬 timing만 선택적으로 기록하며 wire에는 없다.
환경, Python/CUDA/GPU, nvidia-smi power·clock, read-only nvpmodel/CPU·EMC 조회, 정확한 argv,
모델·checkpoint·선택·evidence·소스 hash와 연결·phase별 실제 count를 manifest에 보존한다.
조회 실패는 원문과 unavailable로 기록하며 시스템 설정을 선택·변경하지 않는다.

`analyze_efficientnet_v2_s_profile`은 **request_id**로 오프라인 병합한다. 두 run manifest,
성공한 정상 CLOSE/BYE, expected phase counts, request ID 중복·누락·순서, P0–P8 1:1 대응,
P9 Server row 부재, sample/split/shape/length/hash, 필수 timing의 finite/nonnegative,
correctness를 검사한다. 음수 offloading overhead는 실패다. 제거·clamp·대체·보정하지 않는다.
원본 파일은 수정하지 않으며 분석 실패는 새 디렉터리의 failure manifest와 stderr로 보존한다.

성공 시 `merged_raw.csv`는 모든 phase를 담고, `summary_by_split.csv`는 **measurement만** 사용한다.
summary는 split × metric × (`aggregation=round`, round 1–10 / `aggregation=pooled`)의 long format이다.
count, mean, sample standard deviation (`n-1`), p50/p95/p99 (선형 보간), min/max를 기록한다.
P9에 적용되지 않는 metric은 count=0과 `NA` 통계다. 실제 표본이 없는 값을 만들어 내지 않는다.

formal pooled p99는 **split당 3,000개** 표본의 기술통계다. 300 images × 10 rounds와 맞지 않는
1,500개로 표시하지 않는다. 같은 환경의 round를 독립적인 환경 반복으로 간주하거나 강한 tail 보장,
신뢰구간을 주장하지 않는다. pilot 값은 연구 결과로 사용하지 않는다.

## 검증과 pilot (한 번만 실행)

먼저 Python compile과 `python -B -m unittest discover -v -s split_inference/tests`를 실행한다.
다음 pilot은 서버를 loopback ephemeral port에 한 번만 시작하고 Client를 한 번 실행한다.
양쪽 종료와 오프라인 병합까지 검사한다. 실패한 pilot은 수정·재실행하지 않고 최초 결과를 보존한다.

```bash
/home/ainet/venvs/efficientnet-v2-s-cu132/bin/python -B -m split_inference.scripts.pilot_efficientnet_v2_s_profile \
  --cache /home/ainet/research/thor-mec-inference-edge-profile/split_inference/results/edge_processing_profile/imagenet_validation/20260915T122814_764707Z/torch_cache \
  --zip /mnt/c/Users/gusdn/Downloads/imagenet-val.zip \
  --output split_inference/results/split_latency_profile/NEW_UTC_RUN_ID_pilot
```

## 이후 formal 실행 (이 구현 세션에서는 실행하지 않음)

공유 UTC `RUN_ID`를 한 번 정하고 모든 shell에 동일하게 지정한다. Edge 주소는 `192.168.0.6:5000`이다.
각 장치의 현재 환경과 가용성을 확인한 후 기존 power·clock 상태를 기록한다. 아래 경로와 Thor Docker
digest는 기존 저장소 기록에서 가져왔으며 실제 Thor의 현재 경로·image cache·SSH 접근성은 별도 확인이 필요하다.
서버는 foreground 단일 세션이며 정상 CLOSE/BYE 후 종료한다. 유한 timeout은 접속 대기와 각 frame에 적용된다.

1. Thor: 저장소 동기화.

```bash
cd /home/ainet/research/thor-mec-inference-split
git pull --ff-only origin split-inference
```

2. Edge: 새 결과 root 생성 후 서버를 foreground 실행한다. `RUN_ID`는 동일한 공유 값으로 설정한다.

```bash
set -euo pipefail
EDGE_REPO=/home/ainet/research/thor-mec-inference-edge-profile
EDGE_RUN="$EDGE_REPO/split_inference/results/split_latency_profile/$RUN_ID"
cd "$EDGE_REPO"
mkdir -p "$(dirname "$EDGE_RUN")"
mkdir "$EDGE_RUN"
/home/ainet/venvs/efficientnet-v2-s-cu132/bin/python -B -m split_inference.scripts.serve_efficientnet_v2_s_tcp \
  --cache "$EDGE_REPO/split_inference/results/edge_processing_profile/imagenet_validation/20260915T122814_764707Z/torch_cache" \
  --host 0.0.0.0 --port 5000 --timeout 3600 --verify-payload \
  --profile-mode formal --profile-run-id "$RUN_ID" --output "$EDGE_RUN/server" \
  > "$EDGE_RUN/server.stdout.log" 2> "$EDGE_RUN/server.stderr.log"
```

3. Thor: **Thor 사용자 권한으로 output bind-mount root를 Docker 실행 전에 생성**한다.
   Server READY를 확인한 후 동일 RUN_ID로 Client를 시작한다.

```bash
set -euo pipefail
THOR_REPO=/home/ainet/research/thor-mec-inference-split
THOR_RUN="$THOR_REPO/split_inference/results/split_latency_profile/$RUN_ID"
mkdir -p "$(dirname "$THOR_RUN")"
mkdir "$THOR_RUN"
docker run --rm --pull=never --runtime=nvidia --network=host --user "$(id -u):$(id -g)" \
  -e NVIDIA_VISIBLE_DEVICES=all -e NVIDIA_DRIVER_CAPABILITIES=compute,utility \
  -e PYTHONPATH=/workspace -e TORCH_ALLOW_TF32_CUBLAS_OVERRIDE=0 -e NVIDIA_TF32_OVERRIDE=0 \
  -v "$THOR_REPO:/workspace:ro" -v /home/ainet/datasets/imagenet1k:/dataset:ro \
  -v /home/ainet/.cache/torch:/torch-cache:ro -v "$THOR_RUN:/output" -w /workspace \
  nvcr.io/nvidia/pytorch@sha256:3becd068f49bd2ad38f90db5f9a4803019a76933a24e63d821376c44e7a9200a \
  python -B -m split_inference.scripts.profile_efficientnet_v2_s_tcp \
  --cache /torch-cache/hub --zip /dataset/imagenet-val.zip --host 192.168.0.6 --port 5000 \
  --timeout 3600 --verify-payload --profile-mode formal --profile-run-id "$RUN_ID" --output /output/client \
  > "$THOR_RUN/docker.stdout.log" 2> "$THOR_RUN/docker.stderr.log"
```

4. Edge: 정상 종료 후 원본을 보존하며 Server 디렉터리를 Thor의 새 전송 디렉터리로 복사한다.

```bash
set -euo pipefail
THOR_RUN="/home/ainet/research/thor-mec-inference-split/split_inference/results/split_latency_profile/$RUN_ID"
ssh ainet@192.168.0.189 "mkdir -- '$THOR_RUN/edge-transfer'"
scp -r "$EDGE_RUN/server" "ainet@192.168.0.189:$THOR_RUN/edge-transfer/"
```

5. Thor: CPU-only 분석. 출력 디렉터리가 이미 있으면 중단한다.

```bash
cd /home/ainet/research/thor-mec-inference-split
python3 -B -m split_inference.scripts.analyze_efficientnet_v2_s_profile \
  --client "$THOR_RUN/client" --server "$THOR_RUN/edge-transfer/server" --output "$THOR_RUN/analysis"
```
