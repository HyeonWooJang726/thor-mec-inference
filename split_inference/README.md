# EfficientNetV2-S 단말–Edge 분할추론 준비

## 현재 상태: 1단계 구조 검증 BLOCKED

2026-09-15 조사. ZIP 구조 조사와 2단계 측정 설계 문서 작성은 완료했다.
기본 Python 및 발견한 두 기존 가상환경에 PyTorch와 TorchVision이 없어 **설치된 구현 기준 모델 구조·9-group 타당성·중간 activation shape 검증은 BLOCKED**다.
모델 객체 생성 및 CPU 더미 forward는 0회다. 모델 검증이 완료되었다고 해석하지 않는다.

- `확인됨`: 직접 읽은 코드, 환경, ZIP 또는 공식 소스에 근거한다. 사용자 제공 사전 점검 결과는 출처를 별도로 표시한다. 이번 조사에서는 모델 구현 근거를 확보하지 못했다.
- `제안`: 향후 실험을 위해 설계한 내용이다. 사용자 지정 고정 조건은 별도로 표시한다.
- `미확인`: 근거 또는 실행 검증이 없다. 빈 수치를 0으로 해석하지 않는다.

## Worktree와 조사 기준 — 확인됨

| 항목 | 결과 |
| --- | --- |
| 현재 작업 경로 | `/home/ainet/research/thor-mec-inference-split` |
| 현재 브랜치 | `split-inference` |
| 최초 1단계 조사 시작 `git status --short` | 출력 없음, clean |
| 이동·이름 변경 직전 `git status --short` | `?? split_inference/` |
| 조사 기준 commit | `ad9fdbe Add joint structural stage-risk model analysis` |
| 적용 지침 | 저장소 루트 `AGENTS.md`; 상위 경로 및 저장소 하위에서 추가 파일 발견 안 됨 |

기존 main worktree의 가상환경에는 import 탐색만 수행했다(`PYTHONDONTWRITEBYTECODE=1`). 기존 저장소 파일을 수정하지 않았다.
사용자 승인에 따라 Git의 `worktree move`와 `branch -m`으로 현재 경로·브랜치로 변경했다. 이동 전후 기존 산출물 10개 내용의 SHA256은 동일했다.
모델 이름 `EfficientNetV2-S`, constructor와 weight 식별자는 유지한다.

## 사용자 지정 고정 조건

- TorchVision `efficientnet_v2_s`, 향후 weight `EfficientNet_V2_S_Weights.IMAGENET1K_V1`.
- 입력 `[1,3,384,384]`, 기대 logits `[1,1000]`, FP32, batch size 1.
- NVIDIA Jetson Thor ↔ NVIDIA RTX 5070 Ti Edge 서버, 각각 1대. Edge 실물·환경은 미확인.
- 1단계 구조 검증은 `weights=None`, CPU, `eval()`, `torch.inference_mode()`에서 forward 최대 1회만 허용.
- Point 0도 Thor가 전처리하며, 전처리가 완료된 tensor 준비 시점부터 latency를 측정한다.

## 산출물

- [모델 구조와 환경](docs/model_structure.md)
- [환경 점검과 컨테이너 검증 범위](docs/environment_audit.md)
- [분할점 후보와 tensor 계산](docs/partition_candidates.md)
- [측정·통계·정확성·그림 설계](docs/profiling_protocol.md)
- [데이터 조사](data/README.md), [ZIP manifest](data/manifests/zip_structure.json), [class별 개수](data/manifests/synset_counts.csv)
- [Weight 관리](weights/README.md), [결과 관리](results/README.md)

`configs/`, `scripts/`, `src/{common,thor,edge}/`, `tests/`, `results/profiling/{raw,summary}/`, `results/{accuracy,figures}/`는 준비용 빈 디렉터리다.
빈 디렉터리는 Git이 추적하지 않으며 재현용 의미 없는 파일은 넣지 않았다.

## 단계 전환

사용 가능한 기존 Python 실행 경로가 제공되면 먼저 1단계 구조 검증을 마무리해야 한다.
다음 환경 검증 단계는 **Docker runtime 및 PyTorch GPU smoke test**다. 이번 문서 정리 작업에서는 실행하지 않으며, 별도 승인 후 daemon 접근·runtime·컨테이너 실행·CUDA tensor 연산을 확인한다.
패키지 설치가 필요하면 별도 사용자 승인이 필요하며 이번 작업에서 설치하지 않았다.
2단계는 사용자의 명시적 승인 이후에만 수행한다. 현재 client/server 및 profiling 코드도 구현하지 않았다.
ZIP 해제, weight 다운로드, ImageNet 추론, GPU 반복 측정, Edge 접속, 네트워크 실험, ONNX/TensorRT 변환, FP16/INT8 실험은 수행하지 않았다.
최초 1단계 조사에서는 commit/push를 하지 않았다. 후속 정리 작업에서는 사용자가 문서 보완과 `split-inference` 브랜치의 commit 및 origin push를 명시적으로 승인했다. main 수정·merge는 범위에 포함되지 않는다.
