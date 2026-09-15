# EfficientNetV2-S 단말–Edge 분할추론 준비

## 현재 상태: 공식 P0–P9 CUDA 정확성 검증 완료

2026-09-15, 사용자 확정 G1–G9 정의를 manifest와 코드에 반영했다. 동일한 `weights=None` 모델과 seed 0 입력으로 P0–P9의 shape 및 재결합 logits 비교를 모두 통과했다. 각 point의 max absolute/relative difference는 0이다. 성능 측정은 수행하지 않았다.

- [공식 분할 manifest](manifests/efficientnet_v2_s_p0_p9.json)
- [분할 구현](src/common/efficientnet_v2_s_partitions.py)
- [CUDA 검증 스크립트](scripts/verify_efficientnet_v2_s_partitions.py)
- 실행 명령·환경·검증 한계: [모델 구조 문서](docs/model_structure.md)

아래 worktree 조사 기록은 최초 조사 당시의 provenance다.

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
- 현재 승인된 검증은 `weights=None`, CUDA FP32, `eval()`, `torch.inference_mode()`에서 원본 및 P0–P9 재결합 정확성 확인이다.
- Point 0도 Thor가 전처리하며, 전처리가 완료된 tensor 준비 시점부터 latency를 측정한다.

## 산출물

- [모델 구조와 환경](docs/model_structure.md)
- [환경 점검과 컨테이너 검증 범위](docs/environment_audit.md)
- [분할점 후보와 tensor 계산](docs/partition_candidates.md)
- [측정·통계·정확성·그림 설계](docs/profiling_protocol.md)
- [데이터 조사](data/README.md), [ZIP manifest](data/manifests/zip_structure.json), [class별 개수](data/manifests/synset_counts.csv)
- [Weight 관리](weights/README.md), [결과 관리](results/README.md)

`scripts/`와 `src/common/`에는 분할 검증 및 구현 코드가 있다. `configs/`, `src/{thor,edge}/`, `tests/`, `results/profiling/{raw,summary}/`, `results/{accuracy,figures}/`는 준비용 디렉터리다.
빈 디렉터리는 Git이 추적하지 않으며 재현용 의미 없는 파일은 넣지 않았다.

## 단계 전환

Docker GPU smoke test와 공식 P0–P9 동일 장치 CUDA 정확성 검증을 완료했다. 후속 latency/throughput profiling, pretrained weights, ImageNet accuracy, Edge·네트워크 검증은 별도 승인 범위다. 이번에는 재pull·package 설치·환경 설정 변경·성능 측정을 하지 않았다.
