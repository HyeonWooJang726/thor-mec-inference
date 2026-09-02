# 저장소 운영 지침

## 저장소 목적과 현재 범위

이 저장소는 NVIDIA Jetson AGX Thor에서 DNN inference system을 재현 가능하게 실험하기 위한 연구 testbed다. 현재 단계는 **Thor-only offline profiling**이다.

최종 연구 질문, system architecture, optimization objective, scheduling formulation은 아직 고정하지 않는다. 따라서 현재 단계의 도구와 데이터 구조는 특정 연구 방향이나 알고리즘을 전제로 설계하지 않는다. RT-DETR inference, H.264 decoding, preprocessing, JPEG encoding/offloading, MEC networking, remote GPU execution, microbatch/queue-aware scheduling, ServeSense 및 최종 최적화·스케줄링 알고리즘은 별도 승인과 단계 전환 전까지 구현하지 않는다.

## 검증된 환경

- Hardware: NVIDIA Jetson AGX Thor
- JetPack: `7.2.1-b49`
- L4T: `R39.2.1`
- Architecture: `aarch64`
- CUDA: `13.2`
- TensorRT: `10.16.2`
- `trtexec`: `/usr/bin/trtexec`
- `tegrastats`: `/usr/bin/tegrastats`
- 현재 관찰된 `nvpmodel`: `120W`

`120W`는 현재 관찰값일 뿐 최종 benchmark 설정이 아니다. 실제 실험에서는 환경 점검 결과와 benchmark별 명시적 설정 기록을 기준으로 한다.

## 환경 보호 규칙

- JetPack, CUDA, TensorRT, NVIDIA driver, Linux kernel을 upgrade하거나 변경하지 않는다.
- `apt upgrade`를 실행하지 않는다.
- 사용자의 명시적 승인 없이 `nvpmodel`을 변경하지 않는다.
- 사용자의 명시적 승인 없이 CPU, GPU 또는 EMC clock을 변경하지 않는다.
- system service, desktop 설정, thermal policy, fan policy 또는 networking 설정을 변경하지 않는다.
- 사용자의 명시적 승인 없이 system package나 Python package를 설치·upgrade·제거하지 않는다.
- 구성 변경을 위해 `sudo`를 사용하지 않는다. 읽기 전용 확인에도 `sudo`가 필요하면 중단하고 먼저 사용자에게 승인을 요청한다.
- 그 밖의 모든 system-level 변경과 dependency 변경에도 사용자의 명시적 승인이 필요하다.
- 성능 결과를 조작하거나 만들어 내지 않으며, 실패한 측정을 숨기지 않는다.
- 누락된 measured value를 estimated 또는 synthetic value로 대체하지 않는다.

Power mode와 CPU/GPU/EMC clock은 잠재적인 **실험 설정 변수**다. Codex는 이를 자율적으로 선택하거나 변경할 수 없다. 향후 승인받아 사용한 값은 각 benchmark 설정에 반드시 기록한다.

## 재현 가능한 benchmark 원칙

- 모든 benchmark는 hardware/software 환경, 입력, 실행 옵션, power mode, clock 상태 등 명시적인 configuration을 기록한다.
- raw measurement는 항상 로컬에 보존하며, Git에서 ignore한다는 이유로 삭제하지 않는다.
- aggregate statistics뿐 아니라 개별 raw latency sample을 저장한다.
- GPU performance 실험은 명시적인 warm-up phase를 포함한다.
- warm-up sample과 measured sample을 명확히 구분하여 저장한다.
- 분석은 최소한 mean, p50, p95, p99 latency를 계산할 수 있어야 한다.
- elapsed time 측정에는 monotonic clock을 사용한다.
- 실패한 run도 누락하지 않고 failure reason과 함께 명시적으로 기록한다.
- outlier나 실패 sample을 조용히 제거하지 않는다. 제외가 필요하면 원본을 보존하고 기준과 결과를 별도로 기록한다.
- measured, estimated, simulated, synthetic value를 섞지 않으며, 필요할 때 각 provenance를 명시적으로 labeling한다.
- 향후 benchmark에서 사용한 모든 power mode와 clock configuration을 기록한다.
- software dependency 변경은 사전에 사용자 승인을 받고 변경 내용과 version을 기록한다.

## 작업 원칙

- 환경 수집과 점검은 원칙적으로 읽기 전용이어야 한다.
- optional 정보가 조회되지 않으면 `unavailable`과 원인을 기록한다. 값을 추정하지 않는다.
- required measurement가 실패하면 눈에 띄게 실패 처리하고 오류를 보존한다.
- benchmark 구현이나 실행은 현재 단계에서 별도 요청 없이 시작하지 않는다.
- `results/`와 `logs/`의 로컬 자료는 보존한다. 공개 저장소에 비밀정보, model artifact, engine 또는 raw 결과를 commit하지 않는다.
