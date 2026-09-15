# EfficientNetV2-S Thor–Edge TCP 실행 준비

현재는 **RTX 5070 Ti 서버 내부 `127.0.0.1` loopback 기능 검증만 완료**했다. 실제 Thor–Edge LAN 측정은 수행하지 않았다. 아래 코드는 후속 연결을 위한 준비이며, 이번 smoke의 시간을 장치 간 성능 결과로 사용하지 않는다.

## 구성과 모델 조건

- 공통 프로토콜: [`src/common/tcp_protocol.py`](../src/common/tcp_protocol.py)
- 공통 모델 로더·hash·CUDA timer: [`src/common/efficientnet_v2_s_runtime.py`](../src/common/efficientnet_v2_s_runtime.py)
- 서버: [`scripts/serve_efficientnet_v2_s_edge.py`](../scripts/serve_efficientnet_v2_s_edge.py)
- 클라이언트: [`scripts/run_efficientnet_v2_s_e2e.py`](../scripts/run_efficientnet_v2_s_e2e.py)
- 자동 loopback 검증: [`scripts/smoke_efficientnet_v2_s_loopback.py`](../scripts/smoke_efficientnet_v2_s_loopback.py)
- CPU protocol tests: [`tests/test_tcp_protocol.py`](../tests/test_tcp_protocol.py)

양쪽은 기존 [`EfficientNetV2SPartitions`](../src/common/efficientnet_v2_s_partitions.py)를 사용한다. P0는 입력 tensor를 서버로 보내 G1–G9 전체를 실행한다. P1–P8은 클라이언트에서 `prefix(x, point)`를 실행하고 그 activation을 서버의 `suffix(activation, point)`에 전달한다. P9는 local-only이며 요청을 보내지 않는다. **P9만 선택하면 socket 자체를 만들지 않는다.** 정확한 그룹 및 shape/bytes 표는 [Edge 프로파일 문서](edge_processing_profile.md)에 있다.

모델은 각 프로세스 시작 시 한 번만 생성하고, `--state-dict`로 지정한 로컬 파일을 `torch.load(..., weights_only=True)`로 CPU에 읽어 strict하게 검증·로드한 뒤 GPU에 상주시킨다. 파일은 bare state_dict여야 하며 key·shape·dtype·유한값을 검사한다. `weights=None`은 모델 구조 생성 옵션이며, 실제 추론 파라미터는 제공한 파일에서 로드한다. pretrained weight나 ImageNet은 다운로드하지 않는다.

FP32, batch 1, 입력 `[1,3,384,384]`, `eval()`, `torch.inference_mode()`, TF32 비활성화, cuDNN benchmark=True를 사용한다. 현재 클라이언트 입력은 `--input-seed`(기본 0)의 CUDA `torch.randn`이며 실제 카메라·데이터셋 입력 경로는 없다. 입력 생성과 monolithic reference 생성은 요청 타이밍 밖이다.

## 연결 전 동일성 확인

TCP handshake에서 양쪽의 **state_dict SHA-256, manifest SHA-256, 공통 분할 모듈 SHA-256**을 대조한다. 불일치하면 연결을 거절하고 클라이언트 reference/prefix 및 서버 suffix 추론에 진입하지 않는다. 요청·응답에서도 identity, request ID, partition을 검사한다.

state_dict hash는 Edge 프로파일과 같은 규칙으로 parameter와 buffer 모두를 포함한다: key 정렬, compact JSON `[name,dtype,shape]` + LF, contiguous CPU C-order tensor bytes. tensor byte order는 little-endian으로 정규화한다. 모델 파일 자체의 직렬화 hash와는 다르다. 실행 metadata에 hash를 보존한다.

**이번 hash 일치는 같은 RTX 5070 Ti 호스트의 두 프로세스 사이에서만 검증됐다. 실제 Thor와 Edge의 hash를 비교한 것은 아니다.** Thor의 PyTorch 2.14 개발판/TorchVision 0.29 개발판과 Edge의 2.13.0/0.28.0 런타임 차이도 유지된다. 실제 연결 전에 같은 state_dict 파일을 양쪽에 배포하고 identity 및 P0–P9 재결합 출력을 다시 검증해야 한다. 비교 tolerance는 기존 `rtol=1e-5`, `atol=1e-6`, relative denominator floor `1e-8`이며 임의로 완화하지 않는다.

## 최소 실행 방법

모든 명령은 worktree 최상위에서 실행한다. 기존 Edge 전용 Python 환경을 사용하며 추가 설치는 필요 없다.

### 자동 loopback smoke

```bash
/home/ainet/venvs/efficientnet-v2-s-cu132/bin/python -B -m split_inference.scripts.smoke_efficientnet_v2_s_loopback
```

이 명령은 새 timestamp 결과 디렉터리에 `weights=None`, seed 0의 임시 state_dict를 저장하고 `127.0.0.1`의 OS 할당 port에서 서버를 실행한다. hash 불일치 거절, 모든 P0–P9 warm-up 1회 + 확인 요청 1회, 서버 종료, 서버 없는 P9 검증을 수행한다. 성공·실패 모두 로컬 자료를 보존하며 `finally`에서 자신이 시작한 서버를 종료하고 회수한다. 이 반복 수는 기능 검증용이며 characterization 설정이 아니다.

### 서버와 클라이언트를 따로 실행

아래 `--state-dict`는 같은 실제 파일 경로로 바꾼다. 서버와 클라이언트 모두 실행 가능한 기존 CUDA 환경이 필요하다.

```bash
# 터미널 1: 기본 bind도 127.0.0.1이다.
/home/ainet/venvs/efficientnet-v2-s-cu132/bin/python -B -m split_inference.scripts.serve_efficientnet_v2_s_edge --state-dict /absolute/path/shared_state_dict.pt --bind 127.0.0.1 --port 50051

# 터미널 2: 기본 partitions는 0,1,2,3,4,5,6,7,8,9이다.
/home/ainet/venvs/efficientnet-v2-s-cu132/bin/python -B -m split_inference.scripts.run_efficientnet_v2_s_e2e --state-dict /absolute/path/shared_state_dict.pt --host 127.0.0.1 --port 50051 --warmup 1 --requests-per-point 1
```

서버는 Ctrl-C 또는 SIGTERM으로 종료한다. `--port 0`은 OS가 비어 있는 port를 선택하며 실제 주소는 stdout의 `READY`와 선택적 `--ready-file`에 기록된다. ready 파일은 기존 파일을 덮어쓰지 않는다. 두 실행기 모두 `--timeout`(기본 30초), `--max-payload-bytes`(기본 8 MiB), `--output-root`를 받는다.

현재는 loopback만 사용한다. 코드가 방화벽·포트포워딩·시스템 네트워크 설정을 변경하지 않는다. 외부 bind는 자동 적용하지 않으며, 향후 LAN 실행은 별도 승인과 명시적 주소 지정이 필요하다. 이 준비용 프로토콜에는 인증·암호화가 없고 hash 대조는 모델 동일성 확인이다.

## 프레이밍 및 거절 조건

wire format은 **4-byte unsigned big-endian JSON header 길이 → UTF-8 JSON header → contiguous little-endian FP32 raw bytes**다. 네트워크 payload에 pickle을 사용하지 않는다.

모든 header에는 `protocol_version`, `kind`, `request_id`, `partition_point`, `dtype`, `byte_order`, `shape`, `payload_bytes`가 있다. 모델 관련 메시지에는 identity hash도 포함된다. `hello/ready/error`의 partition은 제어 메시지용 `-1`, 추론 메시지는 P0–P8만 허용된다. 요청 phase는 `warmup` 또는 `measurement`다.

- Header 상한 16 KiB, payload 기본 상한 8 MiB. CLI payload 상한은 최대 64 MiB까지만 허용한다.
- payload를 읽기 전에 partition·dtype·shape·정확한 byte 수와 상한을 검사한다. P9 네트워크 요청, 잘못된 크기, 중복 JSON key, NaN JSON, 잘린 frame, 잘못된 identity와 중복 request ID를 거절한다. tensor payload의 nonfinite 값도 추론 전에 거절한다.
- 첫 byte 대기에는 socket timeout을 적용하고, 첫 byte 이후에는 frame 전체에 별도의 동일 길이 deadline을 적용한다. 부분 read마다 deadline을 연장하지 않는다. sendall에도 socket timeout을 적용한다.
- 서버는 한 연결의 요청을 순차 실행하며 single-request in-flight를 전제로 한다. 동시 요청 scheduling·queue characterization은 구현하지 않는다.
- 서버는 logits `result` frame을 먼저 전송한 뒤, 전송 완료 후 알 수 있는 `server_response_send_ms`를 포함한 `timings` frame을 보낸다. 클라이언트는 두 frame의 identity와 request ID를 검증한다.

## CSV 시간 항목과 해석

클라이언트 `requests.csv`는 phase·sample·partition·request ID와 다음 값을 요청별로 기록한다. CUDA Event는 같은 stream의 GPU 구간을, CPU·socket 구간은 해당 호스트의 monotonic clock을 사용한다.

| CSV 열 | 측정 범위 |
| --- | --- |
| `prefix_gpu_ms` | CUDA Event로 직접 실행한 client prefix. P0는 정의상 0 |
| `activation_serialize_d2h_ms` | activation GPU→CPU 복사, contiguous FP32 raw bytes 생성 |
| `request_send_ms` | client request frame의 `sendall` 호출 시간. 수신 완료나 편도 전송시간이 아님 |
| `server_receive_ms` | 첫 byte를 읽은 뒤 남은 header/payload 수신·header 검증. 연결 유휴 대기와 첫 byte read 시간 제외 |
| `server_deserialize_h2d_ms` | raw bytes→CPU tensor·유효값 검사·H2D·synchronize |
| `server_suffix_gpu_ms` | CUDA Event로 직접 실행한 server suffix |
| `server_response_serialize_d2h_ms` | logits 검사·D2H·FP32 bytes 생성 |
| `server_response_send_ms` | logits result frame `sendall` 호출 시간. 후속 timing frame 전송 제외 |
| `response_wait_receive_ms` | client 요청 전송 후 validated logits frame을 받을 때까지. **서버 처리 대기도 포함** |
| `response_active_receive_ms` | 첫 response byte 이후 남은 frame 수신·header 검증 |
| `response_deserialize_ms` | 수신된 logits bytes를 CPU tensor로 변환·검증 |
| `e2e_wall_ms` | **client의 단일 monotonic clock**으로 GPU 입력 준비 완료부터 validated logits frame 수신까지 직접 측정 |
| `max_abs_diff`, `max_rel_diff` | client의 동일 모델 full forward와 logits 비교 |
| `success`, `error`, `failure_elapsed_ms` | 성공 여부와 오류. 실패 시 완료하지 못한 시간은 빈 필드로 보존 |

서버 내부 시간은 응답 metadata로 전달된다. host clock끼리 timestamp를 빼거나 각 구간 평균을 합해 E2E를 만들지 않는다. 요청 송수신·서버 처리·응답 대기는 서로 겹치며, 이 열은 가산 가능한 분해가 아니다. header encode/검증과 런타임 overhead가 전체 E2E에 포함될 수 있고 eager CUDA Event에는 kernel launch 사이 GPU idle gap이 포함될 수 있다.

P9는 입력 준비 완료부터 **로컬 GPU logits 준비 완료**까지 재고 network/server 관련 열을 정의상 0으로 기록한다. P9 결과의 CPU 복사·정확성 비교는 타이밍 밖이다. P0–P8의 response tensor decode, 후속 timing frame 대기, 정확성 비교, CSV 기록은 E2E interval 밖이다. 초기 connection/handshake, 모델 로드, 입력 및 reference 생성도 타이밍 밖이다.

## 이번 검증 결과와 보존

2026-09-15, 기존 Edge 전용 CUDA 환경에서 다음을 확인했다.

- CPU protocol test **8개 통과**: fragmentation/coalescing, invalid schema, oversized header/payload, JSON 오류, truncation, timeout, identity mismatch, response 규칙. 최초 샌드박스 실행은 socket 전송이 차단됐고, 샌드박스 밖 로컬 socketpair 재실행은 통과했다.
- loopback P0–P9 각각 warm-up 1회 + 확인 요청 1회 통과. 모든 출력 `[1,1000]`, 모든 `max_abs_diff=0`, `max_rel_diff=0`.
- 서버는 P0–P8에 대해 warm-up 9개 + 확인 요청 9개만 처리했다. hash 불일치 handshake는 첫 suffix 실행 전에 거절됐다.
- 서버 종료 후 P9-only도 통과했고 metadata에서 socket 미생성을 확인했다. 서버 PID 8771은 exit 0으로 회수됐으며 추가 프로세스 조회에서도 해당 서버·클라이언트가 없었다.
- 서버와 두 클라이언트 stderr 로그는 모두 0 bytes였다. 실제 Thor–Edge LAN 측정, pretrained weight·ImageNet 다운로드, 환경 설정 변경은 하지 않았다.

로컬 결과: `split_inference/results/e2e_loopback/20260915T110930_685727Z/`

임시 `seed0_state_dict.pt`, `ready.json`, smoke metadata, endpoint별 환경·identity metadata, client CSV, server 요청 JSONL, stdout/stderr를 보존한다. 같은 호스트의 두 endpoint가 확인한 state_dict hash는 `436cd0fd18cc91ead9ba89df52c49a0b5e7f7b2bcc2c25ba0bbe1fe02336ab4d`다. 이는 실제 Thor의 hash 확인을 대체하지 않는다.

기본 실행 결과는 `split_inference/results/e2e_requests/<server_or_client_timestamp>/`, 자동 smoke는 `split_inference/results/e2e_loopback/<timestamp>/`에 매번 새로 저장한다. 두 경로를 정확히 ignore하며 모델 파일·원시 결과·로그는 커밋하지 않는다. 실제 성능 characterization의 반복 수·부하·측정 조건은 이번 기능 smoke로 확정하지 않는다.
