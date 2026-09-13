# Generation 다음 구현 준비 상태

읽기 전용 확인일: 2026-09-13. 이 기록은 설치·다운로드·GPU 실행·재시작을 하지
않았으며 다음 구현 순서를 위한 현재 증거만 정리한다.

## Upscale

- **코드 준비**: `custom_nodes/atelierx_upscale`에 `AtelierXUpscale`, 예제,
  설치 junction script, 단위 테스트가 있다. 입력은 RGB IMAGE, 등록 upscale
  model, 최종 scale이며 ComfyUI native loader/upscaler를 사용한다.
- **설치 registry**: 실행 중인 ComfyUI `GET /object_info/UpscaleModelLoader`
  는 등록되어 있으나 model options는 빈 배열이다. `AtelierXUpscale` registry는
  빈 응답으로 현재 설치에 연결·재시작되지 않았음을 확인했다.
- **모델 준비**: `Models/ESRGAN`, `RealESRGAN`, `SwinIR`에 실행 가능한 model
  file이 없다. 따라서 source code와 template만 준비됐고 실제 추론은 준비되지
  않았다.
- **독립 구현 가능 범위**: Generation REST의 등록 확인·image-ID 입력·고정
  upscale graph·출력 수집 mock 테스트. 실제 GPU 검증에는 등록된 upscale model
  하나와 설치된 node junction/restart가 먼저 필요하다.

## SDXL / Illustrious

- **코드 준비**: `custom_nodes`에 SDXL/Illustrious generation node 또는 example
  workflow는 없다.
- **모델 준비**: `Models/StableDiffusion` checkpoint file은 없고, active
  `CheckpointLoaderSimple` option도 빈 배열이다. 따라서 checkpoint-based SDXL
  입력 조합의 실제 node/API 준비 상태는 미준비다.
- **공통 자원**: active `UNETLoader`에는 Anima diffusion model 4개가 등록되어
  있고 TextEncoders에는 Anima encoder 2개, VAE에는 `qwen_image_vae`가 있다.
  이는 SDXL 자원·호환성 증거가 아니다.
- **독립 구현 가능 범위**: SDXL node contract·registered-name validation·mock
  ComfyUI REST 테스트를 Anima와 분리해 작성할 수 있다. 실제 실행은 SDXL
  checkpoint, compatible text encoder/VAE, node registry 확인 후에만 가능하다.

## 확정 범위와 다음 작업

ADR-0002 N-03은 Anima와 SDXL Illustrious 계열 지원을 요구하고, N-06은 이전
이미지 단독 Upscale을 요구한다. ADR-0003은 전체 순서를 generation → upscale
→ detailer → censor → alpha → encode로 정하고 단독 API/부분 실행도 허용한다.
내부 resampling 정책, SDXL 모델별 compatibility와 presets는 계속 미정이다.

다음 bounded task는 **Upscale Generation REST의 mock-only fixed graph와
registered-model validation**이다. 실제 node install/model 준비 및 GPU 실행은
주 에이전트가 사용자 작업 상태를 확인한 뒤 순차로 진행해야 한다.
