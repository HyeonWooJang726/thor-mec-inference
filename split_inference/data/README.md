# ImageNet-1K validation ZIP 조사

## 확인됨: ZIP 목록과 작은 metadata만 읽음

| 항목 | 결과 |
| --- | --- |
| 외부 ZIP 경로 | `/home/ainet/datasets/imagenet1k/imagenet-val.zip` |
| 파일 크기 | 6,669,976,535 bytes |
| 전체 ZIP entry | 50,001 |
| JPEG 파일 | **50,000** |
| 이미지의 parent synset 경로 | **1,000** |
| synset별 개수 | **모든 class 정확히 50장** |
| synset 이름 | 모두 `n` + 8자리 숫자 |
| 명시적 directory entry | 0; 파일 경로의 parent로 class 수 계산 |
| 중복 entry 이름 | 0 |
| 이미지 외 파일 | 루트 `dataset-metadata.json` 1개 |
| 이미지 경로 예 | `n01440764/ILSVRC2012_val_00000293.JPEG` |

[class별 전체 개수 CSV](manifests/synset_counts.csv)에 1,000개 synset별 개수를 보존했다.
[ZIP 구조 JSON](manifests/zip_structure.json)에 요약과 metadata 원문 필드를 보존했다.

사용자가 사전에 확인한 SHA256은 `6079f8e894c194c77264fc336e6e2eb6a831d230abb09c24fe7bf7bdf41918a1`, 전체 무결성 검사 결과는 passed다.
이번 조사에서 SHA256 계산과 전체 무결성 검사를 반복하지 않았다. ZIP을 해제하거나 JPEG 내용을 읽지 않았다.

## dataset-metadata.json — 확인됨

- `title`: `Imagenet-1k Validation set`
- `id`: `titericz/imagenet1k-val`
- `licenses`: `[{"name": "CC0-1.0"}]`

이는 ZIP 안 metadata의 표기 그대로이며 외부 라이선스 또는 제공자 주장에 대한 독립 검증은 아니다.
class index mapping, preprocessing, 원본 label 검증 정보는 이 JSON에 없다.

## ImageFolder 사용 가능성

**확인됨:** ZIP의 논리적 구조는 바로 `root/synset/image.JPEG`이며 중간 wrapper 폴더가 없다.
**제안:** 향후 승인된 해제 후 synset 디렉터리들이 있는 루트를 `ImageFolder`에 전달하는 구성을 사용한다. ZIP 경로 자체를 ImageFolder root로 전달하지 않는다.
**미확인:** TorchVision이 없어 실제 ImageFolder 인스턴스 생성·이미지 decode·`class_to_idx`와 pretrained logits index 대응은 검증하지 못했다.
1,000 class/50장 조건만으로 label 의미까지 검증된 것은 아니다.
원본 synset 순서와 weight category index의 공식 mapping을 대조한 작은 manifest를 향후 생성한다.

실험 전 데이터 순서와 seed를 고정하고 모든 partition에 같은 순서를 사용한다. 이미지 read/decode/전처리는 E2E 구간 밖에서 수행한다.
이번 단계에는 이미지나 ZIP을 프로젝트로 복사하지 않았다.
