# Anima 동적 LoRA 목록 검증 — 2026-09-13

사용자가 고정 LoRA 슬롯 대신 항목을 추가·삭제하고 항목별 가중치를 지정하는
Anima Custom Node UI를 지시했다. 이 기록은 해당 구현·실행 검증 범위만 다루며,
전체 LoRA 정책이나 모델별 권장 가중치를 확정하지 않는다.

## 구현 계약

- `AtelierXAnimaGenerate`는 `lora_stack`을 선택 입력으로 받는다. 값은 API에서
  순서 보존 JSON 배열 `[{"name": "등록 파일명", "strength": 숫자}]`다.
- ComfyUI 화면에서는 별도 frontend extension이 이 저장값을 `+ Add LoRA`와 `−`
  버튼, 등록 LoRA 선택 dropdown, model strength number field로 제공한다. 사용자는
  JSON을 직접 입력하지 않는다.
- 항목은 위에서 아래 순서로 model-only LoRA patch를 적용한다. 현재 설치된 Anima
  LoRA safetensors는 diffusion-model adapter key만 포함하므로 text encoder 가중치를
  노출하지 않는다.
- 파일명·유한 가중치·범위·Anima patch 적용 여부를 sampling 전에 확인한다. 파싱이나
  patch 적용 실패는 재시도하지 않고 Node 오류로 전달한다.
- 기존 LoRA 없는 workflow/API는 빈 stack으로 동작한다. 이전 세 슬롯 API 입력은
  backend에서 수용하며, frontend는 이전 19-widget workflow 배열을 새 stack 값으로
  변환해 로드한다.

## 실제 ComfyUI API 실행

설치된 ComfyUI 0.35.0과 RTX 4090에서 registry·frontend extension을 다시 로드한
뒤 다음 API prompt를 한 번 실행했다.

| 항목 | 값 |
| --- | --- |
| 모델 조합 | `waiANIMA_v10Base10.safetensors` / `waiANIMA_v10Base10_txt.safetensors` / `qwen_image_vae.safetensors` |
| LoRA 순서 | `anima-base-1-masterpiece-v51.safetensors` 0.35 → `anima-highres-aesthetic-boost.safetensors` 0.5 |
| 생성 | 768×1024, seed 123456789, 24 steps, CFG 4.5, `euler_ancestral` / `normal` |
| Prompt ID | `fdbfb727-2f85-4b4a-88b5-8eaf131683cb` |
| 결과 | `success`, PreviewImage RGB 768×1024 PNG |

ComfyUI 로그는 Anima에 **448 patches attached**와 전체 실행 시간 7.88초를
기록했다. 이는 두 adapter가 수락되었을 뿐 아니라 model patch로 적용되었음을
확인한다. 임시 출력은
`artifacts/anima-smoke/comfyui-temp/temp/ComfyUI_temp_txqlo_00001_.png`에 있다.

## 자동 검증

- Python unit test 17개: 빈 dynamic stack, 순서와 가중치, JSON 형태·타입 오류,
  비호환 LoRA, 이전 세 슬롯 prompt 호환을 포함한다.
- Node frontend test: 숨긴 `lora_stack` 저장 widget과 DOM 편집기를 분리한 뒤 첫
  가중치 변경과 `+` 추가가 순서 보존 JSON 저장값으로 반영되는지 확인한다.
- `validate_examples.py --comfy-root ...`: 두 예제 JSON, 등록된 LoRA 목록,
  no-LoRA 및 dynamic LoRA API prompt의 ComfyUI validation을 확인한다.
- frontend extension은 서버의
  `/extensions/atelierx_anima/atelierx_lora_stack.js`에서 HTTP 200으로 제공되는 것을
  확인했다.

화면에서 `+`·`−` 조작 후 workflow 저장·재로딩은 설치된 ComfyUI UI에서 별도로
확인한다. 이 검증은 API 실행과 구분한다.
