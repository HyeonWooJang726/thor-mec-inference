# Weight 관리

사용자 지정 2단계 weight는 `EfficientNet_V2_S_Weights.IMAGENET1K_V1`이다.
현재 다운로드·저장한 weight는 없다. 1단계 구조 확인은 `weights=None`만 사용하며 이번에는 package 부재로 모델 생성도 미실행이다.

사용자 승인 이후 공식 weight의 식별자, 원본 URL, 파일 SHA256, TorchVision 버전, 전처리 설정을 기록한다.
동일 weight를 두 장치와 원본·분할 모델 모두에 사용한다. weights/checkpoint/ONNX/TensorRT artifact는 Git에서 제외한다.
FP32 baseline에서 autocast, activation dtype 변환, 양자화 및 압축을 사용하지 않는다.
