# EfficientNetV2-S pretrained binary TCP 경로

## 범위

이번 경로는 공식 pretrained model과 실제 선택 이미지로 Thor prefix → TCP → Edge suffix → TCP logits 복원을 검증하기 위한 것이다. `serve_efficientnet_v2_s_tcp`, `run_efficientnet_v2_s_tcp`, `smoke_efficientnet_v2_s_tcp`를 사용한다. 기존 JSON 기반 `tcp_protocol.py`와 dummy E2E 실행기 및 profiling 결과는 변경하지 않는다. 두 protocol은 호환되지 않는다.

이번 실행은 Edge localhost correctness smoke뿐이다. 같은 GPU에서 client/server가 실행되므로 로그의 timing을 Thor–Edge 성능 수치로 해석하지 않는다. 300장 profiling, 실제 LAN 측정, queue/concurrency 실험, 압축, 그림 생성은 수행하지 않는다.

## 모델·입력·그룹

양쪽은 공식 `EfficientNet_V2_S_Weights.IMAGENET1K_V1`을 기존 cache에서 시작 시 한 번 로드한다. 파일명이 `efficientnet_v2_s-dd5fe13b.pth`인 checkpoint SHA-256은 `dd5fe13b1d60ec15317ccc8ca158186e134d3366c3dde9cb9a4e301f2dc66c74`, canonical model SHA-256은 `dcac15dc687d43926f62a7942918dc73d11372abbb612352336b4d5840ca4710`이어야 한다. Canonical hash는 기존 ImageNet profiler 함수를 그대로 사용한다. Cache가 없거나 hash가 다르면 중단하며 다운로드·random weight fallback은 없다.

공통 `efficientnet_v2_s_partitions.py`와 manifest만 그룹 경계의 기준으로 사용한다. 새 protocol의 shape 표도 이 manifest에서 읽으며 별도의 실행 mapping을 만들지 않는다. FP32, batch 1, eval/inference_mode, autocast OFF, TF32 OFF, cuDNN benchmark ON이다. model은 GPU에 상주하고 요청마다 재생성하지 않는다.

Pp prefix=G1…Gp, suffix=G(p+1)…G9. P0 prefix는 identity이며 **전처리된 FP32 tensor**를 보낸다. JPEG를 전송하지 않는다. P9는 전체 local 실행만 하며 network 요청으로 인코딩하거나 서버에서 받아들이지 않는다. P9만 선택한 client는 socket도 생성하지 않는다.

| Split | 요청 shape | 요청 payload bytes |
| --- | --- | ---: |
| P0 | `[1,3,384,384]` | 1,769,472 |
| P1 | `[1,24,192,192]` | 3,538,944 |
| P2 | `[1,24,192,192]` | 3,538,944 |
| P3 | `[1,48,96,96]` | 1,769,472 |
| P4 | `[1,64,48,48]` | 589,824 |
| P5 | `[1,128,24,24]` | 294,912 |
| P6 | `[1,160,24,24]` | 368,640 |
| P7 | `[1,256,12,12]` | 147,456 |
| P8 | `[1,1280]` | 5,120 |
| Response | `[1,1000]` | 4,000 |

G8은 `features[7] → avgpool → flatten(1)` 전체다. P8 activation은 pooling/flatten 이후 5,120 bytes다. G9는 classifier다.

Client는 커밋된 `docs/imagenet_profile/20260915T112015Z/selected_imagenet_members.txt`와 evidence CSV를 사용한다. 선택 SHA-256은 `f198e9fd3da063f0f4ae66dff1d6c76fdb66c7875abae88d462b37f96d338bc2`, evidence SHA-256은 `5706419efb22bd224d7c1b4bac5cceb22d479c3ec1336cc4e9cbb467301bf794`이다. 선택 이미지의 JPEG 및 공식 transform FP32 hash를 확인하고 손상·누락 시 대체하지 않는다. ZIP은 추출하지 않는다.

## Binary framing v2

고정 header는 `struct.Struct('!4sBBQbBBBHI4IQ')`, **48 bytes**다. 정수는 network byte order(big endian), tensor payload는 **C-contiguous IEEE-754 FP32 little endian**이다. Wire에 JSON, pickle, torch.save/np.save 형식 또는 압축은 사용하지 않는다. Local JSON은 실행 metadata 보존용일 뿐 framing에 사용하지 않는다.

| Offset | 크기 | 필드 |
| ---: | ---: | --- |
| 0 | 4 | magic `ESFP` |
| 4 | 1 | version `2` |
| 5 | 1 | message type |
| 6 | 8 | unsigned request_id, response에서 동일 값 |
| 14 | 1 | signed split point, control은 -1 |
| 15 | 1 | dtype: 1=FP32 little endian, control=0 |
| 16 | 1 | dimension count, 최대 4 |
| 17 | 1 | flags: bit 0=smoke payload SHA-256 trailer |
| 18 | 2 | reserved=0 |
| 20 | 4 | status: 0=success, 1=generic error |
| 24 | 16 | uint32 dimension 4개; 사용하지 않는 차원은 0 |
| 40 | 8 | payload byte length; header/trailer 제외 |

Message type: HELLO=1, READY=2, INFER=3, RESULT=4, CLOSE=5, BYE=6, ERROR=7. HELLO/READY만 identity 96 bytes(canonical model, manifest, partition source의 32-byte digest 각각)를 담는다. INFER/RESULT는 tensor만 담으며 서버 timing/queue/service telemetry 필드는 없다. CLOSE/BYE/ERROR는 payload가 없다. 구현은 잘못된 frame에 대해 연결을 종료하고 로컬 오류를 보존한다; resync/retry는 하지 않는다.

연결 시작 시 HELLO/READY identity가 일치해야 추론한다. Hash 계산은 시작 시 한 번이며 요청 성능 경로에 넣지 않는다. **기본 flags=0은 payload SHA-256을 계산하지 않는다.** 양쪽 `--verify-payload`를 켠 smoke만 32-byte digest를 tensor 뒤에 덧붙여 검증한다. 이번 smoke의 response payload는 4,000 bytes이고 header/trailer 포함 wire frame은 4,080 bytes다. 이 옵션은 암호학적 peer 인증이나 보안 채널을 의미하지 않는다.

TCP_NODELAY를 설정하고 persistent connection 하나에서 한 요청씩 순차 처리한다. Header를 먼저 검증한 후 payload를 읽으며 maximum은 기본/상한 8 MiB이고 `--max-payload-bytes`로 더 줄일 수 있다. `recv_exact`는 partial recv를 처리한다. 유한 socket timeout과 frame 전체 deadline을 사용하며 premature EOF, 잘못된 magic/version/type/dtype/shape/length/status, P9 요청은 오류다. Request ID는 session 내에서 증가해야 하고 client는 RESULT의 ID와 split을 대조한다.

서버는 concurrency 1, 단일 session, FCFS 요청 처리이며 dynamic batching/queue 최적화가 없다. CLOSE/BYE 정상 종료, frame 경계 EOF 또는 SIGINT/SIGTERM으로 종료한다. Client disconnect 뒤 listener/connection/model 소유 프로세스가 계속 남지 않도록 한 session 후 서버도 끝난다. 새 client session에는 서버를 명시적으로 다시 시작해야 한다. 기본 host는 양쪽 `127.0.0.1`; LAN 주소는 이후 승인된 실행에서 `--host`로 명시해야 한다. 시스템 networking 설정은 변경하지 않는다.

## 로컬 timing·correctness 기록

Client는 ZIP read/JPEG decode/공식 transforms 및 초기 입력 H2D를 완료하고 GPU를 synchronize한 **inference-ready tensor**에서 E2E monotonic clock을 시작한다. 별도 full local reference forward도 E2E 밖에서 수행한다. Prefix CUDA Event → activation D2H/materialization → request send/response receive → CPU FP32 logits deserialize까지 단일 client clock으로 직접 기록한다. P9는 local full forward와 CPU logits materialization까지이며 network 구간은 정의상 0이다.

`request_response_wall_ms`는 encoded request의 sendall 시작부터 전체 response frame 수신/선택적 integrity 검증 완료까지다. 서버 연산과 왕복 통신을 포함하며 one-way latency가 아니다. Deserialize 후 E2E clock을 끝내고 correctness를 검사한다. 단계 평균을 합쳐 E2E를 만들거나 서로 다른 장치 timestamp를 빼지 않는다. Smoke의 digest/validation overhead와 동일 GPU 공유 때문에 이 값은 성능 결과가 아니다.

Server CSV에는 request ID/split, expected/actual payload bytes, receive 완료 monotonic timestamp, deserialize/H2D wall time, suffix CUDA Event, logits D2H/serialization, response payload/wire bytes와 성공/실패가 있다. 이 내부 timing은 **서버 로컬 CSV에만** 남는다. Client CSV에는 sample ID/member, ID/split, shape/bytes, prefix Event, D2H/materialization, 왕복 wall time, deserialize, E2E, P9 local D2H, response bytes 및 성공/실패가 있다.

Correctness는 같은 이미지의 full local forward와 비교한다. `[1,1000]`, finite, top-1/reference top-1, max/mean absolute error, max relative error(floor=1e-8), `torch.testing.assert_close(rtol=1e-4, atol=1e-5)`를 기록한다. Top-1만 같다고 PASS하지 않으며 tolerance를 자동 완화하지 않는다. P9도 별도로 full reference와 비교한다.

## 실행

CPU-only protocol unit tests:

```bash
python -B -m unittest -v split_inference.tests.test_split_tensor_protocol
```

이번 범위의 자동 smoke(내부에서 unit test를 먼저 실행하고 성공한 경우에만 server/client 시작):

```bash
cd /home/ainet/research/thor-mec-inference-edge-profile
/home/ainet/venvs/efficientnet-v2-s-cu132/bin/python -B -m split_inference.scripts.smoke_efficientnet_v2_s_tcp \
  --cache /home/ainet/research/thor-mec-inference-edge-profile/split_inference/results/edge_processing_profile/imagenet_validation/20260915T122814_764707Z/torch_cache \
  --zip /mnt/c/Users/gusdn/Downloads/imagenet-val.zip
```

이는 ID **0,149,299**에 대해 P0–P8 **27 network requests**, P9 **3 local executions**만 수행한다. Port는 localhost ephemeral port이며 client/server에 `--verify-payload`를 켠다. 테스트 실패 시 추론하지 않는다. 실행 오류 시 재시도하지 않고 실패와 subprocess 정리 결과를 보존한다. Spawn한 두 프로세스는 반드시 wait/reap한다.

수동 실행은 동일 cache를 `--cache`, 별도의 새 디렉터리를 `--output`으로 지정해 `python -B -m split_inference.scripts.serve_efficientnet_v2_s_tcp --host 127.0.0.1 --port 50051 ...` 및 `python -B -m split_inference.scripts.run_efficientnet_v2_s_tcp --host 127.0.0.1 --port 50051 --zip ... --sample-ids 0,149,299 ...`를 사용한다. 양쪽 verify-payload 설정을 같게 해야 한다. Client의 `--partitions 9`는 서버 없이 사용할 수 있다.

결과는 새 ignored `split_inference/results/split_e2e_loopback_smoke/<UTC timestamp>/`에 client/server raw CSV, correctness CSV, model/data/environment/protocol manifest, exact invocation, stdout/stderr, unit test 출력, artifact SHA-256을 보존한다. 기존 profile artifact는 변경하지 않는다. 원시 결과·모델·ImageNet·로그는 Git에 포함하지 않는다.
