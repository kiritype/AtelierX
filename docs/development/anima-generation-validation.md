# Anima 생성 Node 첫 실제 실행 검증 — 2026-09-12

사용자가 설치된 Anima 모델을 첫 개발·테스트 대상으로 지정했다. Terra 서브 에이전트가 생성 Node·테스트·실행 스크립트를 작성했고 주 에이전트가 코드를 검토하고 GPU 생성을 실행했다. 전체 ADR-0002 기능 완료를 뜻하지 않는다.

## 구현 범위

- [AtelierXAnimaGenerate](../../custom_nodes/atelierx_anima/nodes.py): ComfyUI 등록 모델·Text Encoder·VAE와 Prompt·생성 설정을 받아 단일 IMAGE를 반환한다.
- ComfyUI V3 extension 등록, 기존 모델 로더·조건 인코딩·Sampler·VAE Decode를 사용한다.
- Anima 모델·Text Encoder 및 VAE latent channel 검사, 입력 크기·설정 검사를 포함한다.
- LoRA·Preset 영속 저장·모델별 자동 기본값·SDXL·후처리는 후속 기능이다. 모델은 현재 diffusion_models 등록 목록에서 선택하며 checkpoints에만 등록된 모델은 이 첫 목록에 포함되지 않는다.
- 출력 저장은 [검증 스크립트](../../custom_nodes/atelierx_anima/scripts/smoke_anima.py)가 수행한다. 제품 Encode / Save Node는 구현하지 않았다.

## 실제 검증 환경과 입력

| 항목 | 값 |
| --- | --- |
| OS / GPU | Windows / NVIDIA RTX 4090, 드라이버 591.86 |
| ComfyUI | `C:\StabilityMatrix\Packages\ComfyUI`, 버전 파일 0.35.0 |
| Python / PyTorch | 기존 venv Python 3.12.10 / Torch 2.14.0+cu130 |
| 모델 | waiANIMA_v10Base10.safetensors |
| Text Encoder | waiANIMA_v10Base10_txt.safetensors |
| VAE | qwen_image_vae.safetensors |
| 크기 / Seed | 768 × 1024 / 123456789 |
| Steps / CFG | 24 / 4.5 |
| Sampler / Scheduler | euler_ancestral / normal |

Positive: `A fully clothed adult woman, calm expression, detailed anime illustration, studio portrait`

Negative: `child, minor, nude, nsfw, blurry, low quality`

실행 명령은 저장소 루트를 기준으로 한다.

```powershell
& 'C:\StabilityMatrix\Packages\ComfyUI\venv\Scripts\python.exe' -B -u custom_nodes/atelierx_anima/scripts/smoke_anima.py --comfy-root C:\StabilityMatrix\Packages\ComfyUI --width 768 --height 1024
```

## 확인한 결과

- 기존 ComfyUI의 `nodes.load_custom_node`를 통해 저장소 패키지를 실제 registry에 등록했다.
- registry에서 조회한 Node의 실행 메서드를 추론 모드로 호출해 모델 로딩부터 Sampling·Decode까지 완료했다. 프로세스 종료 코드 0.
- 출력 배치·크기가 요청과 일치하고 NaN·무한대가 없는지 스크립트에서 확인했다.
- 주 에이전트가 생성 PNG를 열어 실제 인물 일러스트가 생성된 것을 확인했다. 이는 시각 확인이며 Validation Backend의 Prompt 판정이나 품질 평가를 수행한 것은 아니다.
- 로컬 결과: `artifacts/anima-smoke/anima-20260912T144010Z.png`, 동일 이름 JSON, `smoke-run.log`. 결과·실행 설정은 로컬 보존하고 생성 산출물은 Git에서 제외한다.
- 로그의 24-step Sampling 구간은 약 5초였다. 모델 로딩·Decode를 포함한 전체 응답 시간 측정은 아니다.
- 기존 ComfyUI·모델을 변경하거나 의존성을 설치하지 않았다. 검증 스크립트는 Hugging Face·Transformers offline 모드로 실행했다.

## 검증 한계와 다음 작업

첫 실행의 실제 추론 검증은 WAI 모델 조합 한 개다. 다른 설치 모델·해상도·Sampler의 호환성을 보장하지 않는다. 2026-09-12 검증은 ComfyUI registry 등록 후 Node 직접 호출이며, 아래 후속 검증에서 설치 및 화면 Workflow 실행을 완료했다.

Terra가 작성한 단위 테스트 9개가 기존 ComfyUI Python 환경에서 통과했다. 입력 타입·범위, 경로 선택, 모델·Encoder·VAE 검사, Prompt·Seed·latent·Sampling 연결, Node schema·등록을 검증한다. CPU 테스트는 ComfyUI 의존성을 대체한 단위 테스트이며 위 실제 GPU 검증과 구분한다. 구문 컴파일과 diff 공백 검사도 통과했다.

## 설치 및 ComfyUI 화면 실행 — 2026-09-13

- 설치 위치: `C:\StabilityMatrix\Packages\ComfyUI\custom_nodes\atelierx_anima`. 저장소의 `custom_nodes/atelierx_anima`를 가리키는 Junction으로 연결했다. Python 코드 변경은 ComfyUI 재시작 후 적용한다. 기존 모델·다른 Custom Node는 변경하지 않았다.
- 예제 위치: `C:\StabilityMatrix\Packages\ComfyUI\user\default\workflows\AtelierX\Anima - Generate and Preview.json`. 원본은 [화면 Workflow](../../custom_nodes/atelierx_anima/examples/anima-preview.workflow.json)다. 예제 변경 시 이 복사본도 갱신하되 사용자 수정본을 덮어쓰지 않는다.
- 당시 실행 중인 ComfyUI 작업이 없음을 확인하고 기존 venv로 로컬 서버를 시작했다. 접속 주소는 `http://127.0.0.1:8188`이다. 이번 실행은 offline 환경 변수와 API Node 비활성화 옵션을 사용했으며 설치 설정을 바꾸지 않았다.
- 화면에서 **워크플로 → AtelierX → Anima - Generate and Preview**를 열고 **실행**을 눌렀다. `AtelierX Anima Generate → PreviewImage` 전체 실행이 성공했으며 위 WAI 조합과 768 × 1024 설정을 사용했다.
- 실행 ID `119dd036-d75b-4527-896b-78296c355969`: ComfyUI history의 `status_str=success`, `completed=true`, PreviewImage 이미지 출력 확인. 생성 결과는 `artifacts/anima-smoke/comfyui-temp/ComfyUI_temp_cskqu_00001_.png`에 있다. PreviewImage 결과는 임시 파일이므로 영구 저장 기능과 구분한다.
- 화면 검증에서 Seed 뒤에 자동 삽입되는 `control_after_generate` Widget으로 인해 예제 설정값이 밀리는 문제를 발견하고 `fixed` 값을 추가했다. 수정된 Workflow가 24 Steps / CFG 4.5를 실제 요청으로 전달한 것을 확인했다.
- Terra가 작성한 단위 테스트 총 11개와 예제 JSON·설치된 Node registry·모델 선택 검증이 통과했다. 화면 Workflow의 Widget 배열과 API 입력 구조를 각각 검증한다.

다음은 사용자가 Prompt·Seed를 바꾸어 직접 실행해 보는 것이다. 다른 설치 Anima 모델 조합·다중 LoRA·Preset은 후속 검토 대상으로 유지한다.
