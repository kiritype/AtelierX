# Upscale Custom Node 검증 기록 — 2026-09-13

## 구현 범위

- [AtelierXUpscale](../../custom_nodes/atelierx_upscale/nodes.py)는 비어 있지 않은 RGB `IMAGE`, ComfyUI에 등록된 upscale 모델, 입력 대비 최종 배율만 받아 `IMAGE`를 반환한다. 일반 RGB 업스케일 모델에 1/4채널을 전달하는 호환성 문제를 피하기 위해 Alpha 보존·단일 채널 처리는 아직 지원하지 않는다.
- 모델 로딩·타일 추론·OOM 시 타일 축소는 설치된 ComfyUI 0.35.0의 `UpscaleModelLoader`와 `ImageUpscaleWithModel`을 호출한다.
- 첫 구현은 모델 결과를 ComfyUI `common_upscale`의 Lanczos 리샘플링으로 목표 크기에 맞춘다. 목표 픽셀은 입력 차원 × 배율을 half-up으로 반올림한다.
- 마지막 두 내부 선택은 ADR-0002 N-13에서 미결정인 리샘플링·반올림의 첫 구현일 뿐, 제품 정책 확정이 아니다.
- Preset·REST·저장·WebP·타일/Overlap 사용자 설정·모델 다운로드는 포함하지 않는다.

## 설치 모델 확인

`C:\StabilityMatrix\Packages\ComfyUI\extra_model_paths.yaml`은 `upscale_models`에 `C:\StabilityMatrix\Models\ESRGAN`, `RealESRGAN`, `SwinIR`을 등록한다. 2026-09-13 확인 시 이 세 디렉터리와 ComfyUI의 기본 `models\upscale_models`에는 실행 가능한 모델 파일이 없고 placeholder만 있었다. 모델을 다운로드하거나 설치 설정을 변경하지 않았다.

따라서 실제 GPU 추론·설치된 ComfyUI 화면 실행·사용자 실행 준비 완료는 아직 검증하지 못했다. 등록 가능한 ESRGAN/RealESRGAN/SwinIR 모델 하나와 테스트 입력 이미지가 준비된 뒤, 실행 중인 ComfyUI 작업이 없는 시점에 주 에이전트가 설치·재시작·실행을 조정해야 한다.

## 현재 검증

다음 단위 테스트는 실제 ComfyUI 모델 추론 대신 등록 모델 검사, 최종 배율 계산, ComfyUI 표준 loader/upscaler 위임, Lanczos 최종 크기, 스키마/등록을 검증한다.

```powershell
& 'C:\StabilityMatrix\Packages\ComfyUI\venv\Scripts\python.exe' -B -m unittest discover -s custom_nodes\atelierx_upscale\tests -v
& 'C:\StabilityMatrix\Packages\ComfyUI\venv\Scripts\python.exe' -B custom_nodes\atelierx_upscale\scripts\validate_examples.py
```

제공한 [Workflow](../../custom_nodes/atelierx_upscale/examples/upscale-preview.workflow.json)와 [API body](../../custom_nodes/atelierx_upscale/examples/upscale-preview.api.json)는 입력 이미지와 등록 모델 이름을 `REPLACE_*` 자리표시에 넣으면 실행한다. 이 템플릿은 현재 설치 모델이 비어 있는 상태에서 실제 실행 성공을 주장하지 않는다.
