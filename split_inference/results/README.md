# 결과 관리

현재 성능·정확성 실측 결과와 그림은 **없다**. 모델 구조 검증은 BLOCKED다.
데이터 manifest는 ZIP 관찰값이며 profiling 결과가 아니다.

| 경로 | 향후 용도 | Git |
| --- | --- | --- |
| `profiling/raw/` | 모든 반복·warm-up·실패·timestamp·환경 정보 | 제외, 로컬 보존 |
| `profiling/summary/` | 작은 group/partition/run 요약 CSV, CI 및 accounting 통계 | 추적 가능 |
| `accuracy/` | 작은 정확성 요약 CSV | 추적 가능; 큰 tensor는 제외 |
| `figures/` | 최종 PNG 300 DPI 및 PDF/SVG, caption·그림 manifest | 추적 가능 |

향후 그림 생성 코드는 `scripts/`에 두고 원시 데이터와 분리한다. 같은 요약 CSV와 설정으로 그림을 재생성한다.
raw → summary → figure 관계, 입력 hash, 분석 코드 revision, 통계 seed와 version을 기록한다.
README·설정·manifest·작은 CSV·최종 그림은 추적 가능하게 유지한다.
실측이 없거나 clock 동기화가 검증되지 않은 경우 값을 만들지 말고 누락 사유를 명시한다.
