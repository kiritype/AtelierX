# ComfyUI Custom Node 구조와 첫 개발 단위

상태: 구조 설계 및 개발 진행 기록. 작성일: 2026-09-12. 사용자 요청으로 주 에이전트가 구조를 설계하고 Terra 서브 에이전트가 구현·테스트 작성을 담당한다. 사용자는 첫 개발·테스트를 설치된 Anima 기반 이미지 생성 Node로 지정하고 구현을 지시했다. 아래 미정 상세나 이전 출력 Node 제안을 일괄 확정하지 않으며 ADR-0005는 계속 Proposed로 유지한다.

## 현재 첫 개발 단위 — 사용자 지정 Anima 이미지 생성

LoRA UI 후속 보완: 사용자는 고정 3슬롯 방식 대신 `+` / `−`로 LoRA 항목을 추가·삭제하고 각 항목의 가중치를 지정하도록 요청했다. Terra에게 동적 목록 UI·저장/재로딩·API 입력 전달·기존 Workflow 호환 검증을 맡겼다. 고정 슬롯 구현의 테스트 통과는 이 후속 요구의 완료를 뜻하지 않는다.

2026-09-13 후속 지시: 설치된 LoRA를 여러 개 선택하고 각각 가중치를 지정할 수 있도록 Anima 생성 Node를 확장한다. 주 에이전트가 Terra에게 구현·테스트를 맡겼으며 사용자는 ADR 논의를 병행한다. ComfyUI 등록 LoRA 목록을 사용하고 적용 순서를 보존하며, 미선택 시 기존 생성과 기존 Workflow 호환성을 유지한다. 설치된 ComfyUI와 예제 Workflow까지 갱신·검증하는 완료 기준을 따른다. 상세 UI 구조·호환 모델 범위와 실제 테스트 결과는 구현 검토 후 기록하며 현재 완료로 간주하지 않는다.

Encode / Save 우선 제안은 사용자가 채택하지 않았다. 첫 구현과 실제 테스트는 **설치된 Anima 모델로 이미지를 생성하는 Node**다. 주 에이전트가 구현 범위를 정리해 Terra에 개발·테스트 작성을 지시했다.

- 위치: Monorepo의 `custom_nodes/atelierx_anima`. ComfyUI에서 로드하는 Python 패키지로 구성한다.
- 첫 Node: `AtelierXAnimaGenerate`. 모델·Text Encoder·VAE, Positive/Negative Prompt, 크기·Seed·Steps·CFG·Sampler·Scheduler를 받아 IMAGE를 반환한다.
- 설치된 ComfyUI의 모델 로딩·텍스트 인코딩·Sampling·VAE Decode를 재사용한다. 모델은 ComfyUI에 등록된 경로에서 선택하고 Anima 계열 여부를 검사한다.
- Node 내부에서 이미지를 저장하지 않는다. 실제 생성 검증용 runner가 결과 PNG를 저장하며 이는 제품 Encode / Save 구현과 다르다.
- 초기 검증 조합은 WAI-ANIMA diffusion model, 대응 이름의 Text Encoder, qwen_image_vae다. 설치 파일과 모델 정보에 근거한 시험 대상이며 실제 호환성은 실행으로 확인한다.
- 첫 단위에는 SDXL·후처리·Preset 영속 저장·REST·전체 Queue를 포함하지 않는다. 다중 LoRA와 모델별 자동 초기값 등 ADR-0002의 나머지 요구는 후속으로 유지하고 첫 Node 구현으로 전체 기능 완료를 주장하지 않는다.
- WAI 모델 정보의 권장 범위 Steps 20~30, CFG 4~5를 바탕으로 시험 기본값 24·4.5 및 Euler ancestral / normal을 사용한다. 모든 Anima 모델에 공통 최적값을 보장하거나 미정 기본값 취득 정책을 확정하는 것은 아니다.
- Terra는 단위 테스트와 실제 ComfyUI 로딩·생성 runner를 작성한다. 주 에이전트가 코드 검토 후 같은 GPU에서 한 번에 한 작업으로 실제 생성 검증을 수행한다. 기존 설치·모델 변경과 다운로드는 필요할 때 별도로 판단한다.

환경 추가 확인: 기존 ComfyUI venv에서 Python 3.12.10, Torch 2.14.0+cu130, CUDA 사용 가능 및 RTX 4090 인식을 확인했다. ComfyUI 소스에 Anima 모델·QWEN3_06B Text Encoder 인식이 있다. [첫 실제 생성 검증](custom-nodes-design.md)에서 WAI 모델 조합의 768×1024 생성 성공과 검증 한계를 기록했다.

## 확인한 개발 환경

- ComfyUI 설치: `C:\StabilityMatrix\Packages\ComfyUI`.
- `comfyui_version.py`의 버전: `0.35.0`.
- 해당 설치의 `venv\Scripts\python.exe` 존재 확인. Python·PyTorch 실행과 호환성은 아직 검증하지 않았다.
- nvidia-smi: NVIDIA GeForce RTX 4090, 24564 MiB, 드라이버 591.86.
- Stability Matrix 모델 디렉터리에 Anima 이름의 모델·Text Encoder와 qwen_image_vae 파일이 있다. 파일명 확인이며 모델 조합·정상 로드·생성 성공을 검증한 것은 아니다.
- custom_nodes의 하위 디렉터리 조회 결과는 없었다. 등록 가능한 Node 전체를 확인한 것으로 간주하지 않는다.
- 프로세스 조회는 접근 거부되어 ComfyUI 현재 실행 여부는 확인하지 못했다. 기존 설치·모델·실행 프로세스를 변경하지 않았다.

## 구조 제안

Monorepo 안에 하나의 ComfyUI Custom Node 패키지를 두고 기능별 모듈로 나눈다. 실제 경로·Node 이름과 공개 입출력은 후속 계약에서 정한다. 빈 기능 파일을 미리 만들지 않고 구현하는 기능부터 추가한다.

| 영역 | 역할 | 개발 의존성 |
| --- | --- | --- |
| 등록 진입점 | ComfyUI에 구현된 Node 등록 | 설치 버전의 Node API 확인 |
| Anima 생성 / SDXL 생성 | 계열별 입력과 모델 로딩·생성 | 기본 모델·Encoder·VAE 조합, 설정 기본값·LoRA 계약 |
| Upscale | 모델 고유 배율과 별도로 최종 배율 적용 | 리샘플링·크기 반올림 |
| Detailer | 눈·입·손·얼굴 처리 | 검출 모델·처리 옵션 |
| Censor | 검출 영역 처리 | 검출 대상·마스킹 방식 |
| 배경 Alpha | 캐릭터 마스크와 투명도 처리 | 분리 모델·마스크 의미·경계 처리 |
| Encode / Save | PNG 및 선택적 WebP 출력 | 아래 첫 개발 단위의 입출력·저장 계약 |
| 내부 처리 함수 | 변환·입력 검사 등 Node 실행 로직 | 해당 기능에서 실제 필요한 만큼 분리 |
| 테스트 | 순수 처리 테스트와 ComfyUI 통합 검증 | Terra가 작성, 주 에이전트가 계약 충족 여부 검토 |

위 영역은 소스 책임 구분이며 공개 Node 개수와 일대일 대응을 강제하지 않는다. Anima와 SDXL 공통 Adapter를 필수로 도입하지 않는다. Node는 Prompt 핵심 조합·Core SQLite·AI Provider·전체 작업 Queue를 소유하지 않는다. Preset Load/Save는 확정 요구로 유지하지만 저장 계약이 정해지기 전 Node 내부 임의 DB로 구현하지 않는다.

ComfyUI의 [Custom Node 등록 안내](https://docs.comfy.org/custom-nodes/walkthrough)와 [IMAGE·MASK 문서](https://docs.comfy.org/custom-nodes/backend/images_and_masks)를 확인했다. IMAGE는 배치 텐서이며 LoadImage의 MASK는 Alpha 반전값이라는 점을 입출력 설계에 고려한다. 아래는 이 기술 특성에 기반한 AtelierX 제안이다.

## 이전 제안 — Encode / Save 출력 Node, 첫 개발 대상에서 제외

Terra의 독립 요구사항·테스트 준비 검토에서도 N-07/N-12를 첫 단위로 권고했다. 생성 모델 없이 작은 이미지로 실제 출력 동작을 검증할 수 있어 Validation 설계와 병행할 수 있다.

첫 공개 Node는 Encode와 Save를 함께 처리하는 출력 Node 하나로 제안한다. 생성·Upscale 등 이미지 처리 Node와는 분리한다. 내부 인코딩과 저장 함수는 분리해 실패를 검증할 수 있게 한다.

첫 구현 전에 정리할 계약과 권고는 다음과 같다. 모두 제안이며 확정된 요구에 섞지 않는다.

| 결정할 계약 | 권고안 |
| --- | --- |
| 입력 | RGB IMAGE 배치, 선택적 MASK, WebP On/Off·품질. MASK는 1이 투명인 ComfyUI 관례를 따라 Alpha로 변환. 크기·배치가 맞지 않으면 오류, 임의 크기 변경 금지 |
| 품질 | WebP 품질 정수 1~100, 기본 90, 기본 WebP Off. UI에 Lossless 옵션은 추가하지 않음 |
| 저장·파일 관계 | ComfyUI output 아래 전용 하위 폴더. 이미지마다 새 이름을 만들고 PNG·WebP는 같은 stem 사용. 기존 파일 덮어쓰기 금지. 작품·캐릭터별 최종 경로 정책과 Core 등록은 별도 |
| PNG·Alpha | PNG 항상 저장, WebP On일 때 별도 파일 추가. 두 출력의 크기·Alpha 보존. RGB 손실 압축인 WebP에 PNG와의 픽셀 완전 일치를 요구하지 않음 |
| 실패 | 요청한 파일 중 하나라도 저장·인코딩 실패하면 Node 실패. 이미 완성된 PNG를 실패 때문에 삭제하지 않으며 남은 파일을 성공한 전체 결과처럼 반환하지 않음. 자동 재실행 금지 |
| Metadata | 첫 단위는 픽셀·Alpha·파일 출력 검증에 한정. EXIF·Prompt·Workflow·Core Metadata의 보존·등록은 미구현 범위로 명시하고 별도 계약 후 추가 |

임시 파일·완성 파일 공개 시점, 동시 실행의 파일명 충돌 방지, ComfyUI 출력 결과 형식과 디스크 오류 전파는 위 계약을 구현할 때 코드 검토 대상으로 삼는다. 원격 이미지 전달과 프로젝트 전역 저장 정책을 이 임시 개발 단위로 확정하지 않는다.

## 후속 출력 Node를 위한 이전 테스트 제안

공개 계약 정리 후 Terra에 위 출력 Node와 테스트를 맡긴다. 다른 Node·Backend·Preset 저장·모델 다운로드·CI는 이 첫 단위에 포함하지 않는다. 설치 연결은 기존 ComfyUI를 복제하거나 의존성을 일괄 갱신하기 전에 별도 실행 방법을 확인한다.

- PNG 단독 및 PNG+WebP 결과가 실제로 Decode되고 크기가 같은지 확인.
- WebP Off에서 WebP 파일이 생기지 않는지 확인.
- 알려진 RGB·투명/반투명 MASK로 Alpha 방향과 보존 확인.
- 여러 이미지 및 반복 실행에서 파일 쌍·이름 충돌·기존 파일 보존 확인.
- 잘못된 입력·품질·배치/마스크 크기 오류 확인.
- 인코더·쓰기 실패 시 실패 전파, 성공으로 오인하지 않는 결과, 기존/완성 PNG 보존 확인.
- 실제 ComfyUI 등록과 작은 CPU IMAGE 실행 통합 검증. 모델 생성·GPU 추론 성공은 이후 생성 Node의 별도 검증.

테스트 코드 작성·실행은 Terra 담당이며, 이 목록 자체는 테스트 통과 기록이 아니다. 전역 Test·CI 정책도 확정하지 않는다.

## 다음 작업

Terra의 Anima 첫 생성 Node와 테스트 구현을 검토했고 WAI 조합 실제 생성과 단위 테스트 9개가 통과했다. 다음은 ComfyUI Workflow 연결 검증과 다른 Anima 조합·LoRA·Preset 등 후속 요구 검토다. 출력 Node는 그 이후 후보이며 우선순위로 채택된 상태가 아니다. 전체 Backend 설계 완료를 생성 Node 개발의 선행 조건으로 두지 않는다.

## 후속 Node 병렬 개발 — 2026-09-13 사용자 지시

사용자가 다른 Custom Node 개발도 서브 에이전트로 병렬 진행하도록 지시했다. 주 에이전트가 Upscale과 배경 투명화를 독립 Terra 작업으로 배정했다. 구현 prototype은 각각 `custom_nodes/atelierx_upscale`, `custom_nodes/atelierx_alpha`에서 준비하며 설치 모델·의존성 확인 후 실제 가능한 범위를 보고한다. 미정 리샘플링/검출 모델/경계 처리 선택은 제품 정책 확정과 구분한다. 기존 Anima·동적 LoRA와 별도로 코드/테스트를 작성하고 GPU·서버 재시작·설치 통합은 주 에이전트가 조정한다. 모델 없는 기능을 완료로 보고하지 않으며 사용자 직접 실행 가능한 예제·설치 검증 기준을 유지한다.

## 현행 노드 사양과 설치 상태

표기: **[확정]** 사용자 확정·Accepted ADR, **[구현]** 현재 코드 동작(초기 운영값 포함), **[제한]** 미구현·미검증·알려진 한계. 날짜별 검증 기록은 로컬 전용 `docs/history/`에 있다.

#### 공통 설치
- [구현] 설치 ComfyUI 0.35.0 `C:\StabilityMatrix\Packages\ComfyUI`의 `custom_nodes\atelierx_*` 6개는 저장소 `custom_nodes/atelierx_*`를 가리키는 Junction. 각 `scripts/Install-AtelierX*.ps1 -ComfyRoot ...`는 기존 디렉터리/다른 대상 Junction을 덮어쓰지 않음. Python 변경은 ComfyUI 재시작 후 반영.
- [구현] 사용자 실행용 Workflow는 `...\ComfyUI\user\default\workflows\AtelierX\`에 복사본으로 설치. 예제 변경 시 복사본 갱신하되 사용자 수정본은 덮어쓰지 않음.
- [구현] Impact Pack/Subpack은 `.atelierx/reference/ComfyUI-Impact-Pack`, `-Subpack`(gitignore 대상) Junction으로 설치됨. ComfyUI venv에 `ultralytics`, `segment-anything` 설치(기존 PyTorch 교체 없음).
- [구현] Alpha/Censor 검출기 입력은 ComfyUI RGB float → BGR uint8 ndarray로 변환(Ultralytics 규격).

#### AtelierXAnimaGenerate (atelierx_anima)
- [구현] 입력: `diffusion_model`(diffusion_models), `text_encoder`(text_encoders), `vae`(vae), positive/negative prompt, width/height 기본 1024(256~1920, step 16), seed 0, steps 24(≤100), cfg 4.5(≤20), sampler `euler_ancestral`, scheduler `normal`, 선택 `lora_stack`. 출력 IMAGE 1개. Anima 모델 타입·VAE 16 latent channel 검사. 저장 안 함.
- [구현] checkpoints에만 있는 모델은 목록에 없음.
- [구현] `lora_stack`: 순서 보존 JSON `[{"name","strength"}]`, 위→아래 model-only patch, strength -100~100, patch 0개면 오류, 재시도 없음. 빈 배열=기존 동작. 이전 3슬롯 API 입력과 19-widget Workflow는 호환 변환. 화면은 `web/atelierx_lora_stack.js`의 `+ Add LoRA`/`−` UI.
- [구현] ADR-0027 P3/P7 일관성 방식: 선택 입력 `reference_full`(IMAGE), `reference_face`(IMAGE), `consistency`(STRING JSON, 기본 `""`=미사용, 미사용 시 이전과 완전히 같은 graph). `anima-incontext-character` 하나이며 `AnimaRefEncode/AnimaRefLatentBatch/AnimaInContextApply`를 ComfyUI `NODE_CLASS_MAPPINGS`에서 실행 시점에 찾고(경로 import 없음), 고정 LoRA `anima-incontext-character.safetensors`(강도 1.0)를 적용한다. `strength`(0.5~1.5)·`end_percent`(0.3~1.0)만 노출하고 `start_percent`0·`cond_only` true·`fit_mode` pad·`ref_timestep`0은 고정이다. 단위 테스트는 `tests/test_nodes.py`, 예제는 `examples/anima-incontext-character.{workflow,api}.json`(README 참조, `validate_examples.py` 자동 검사 대상 아님).
- [미검증] 위 일관성 방식의 실제 ComfyUI/GPU 실행. `comfyui-anima-incontext` 설치·LoRA 파일 존재는 로컬에서 확인했으나(경로 `C:\StabilityMatrix\Packages\ComfyUI\custom_nodes\comfyui-anima-incontext`) 실제 생성 실행 검증은 별도다.
- [구현] Generation 서비스(`src/atelierx/generation/consistency.py`, `__init__.py`, `pipeline.py`): Job `inputs.consistency:{method,params:{strength,end_percent,suppress_reference_background},references:[{role,image_id,sha256}]}`, `GET /v1/resources`의 `consistency_methods`. 상세는 [REST API 문서](../api/rest-api.md#일관성-방식inputsconsistency--adr-0027-p3p7)를 따른다. Core(참조 세트/확정/강제, Negative 합성)와 Frontend는 아직 구현하지 않았다.
- [제한] 실제 GPU 검증 조합은 WAI(`waiANIMA_v10Base10` + `_txt` + `qwen_image_vae`) 하나. 다른 Anima 모델 미보장. 24/4.5는 WAI 모델카드 기반 시험값이며 전역 기본값 정책 아님. LoRA 0.35/0.5는 예제값.

#### AtelierXUpscale (atelierx_upscale)
- [구현] 입력·Lanczos half-up·기본 1.5·4x-UltraSharp 기본: 패키지 README 참조. 추가: RGB만 허용(Alpha·1채널 미지원), 타일/Overlap 사용자 설정 없음.
- [제한] 리샘플링·반올림은 N-13 미결정의 첫 구현.

#### AtelierXDetailer / AtelierXImpactDetailerPipeline (atelierx_detailer)
- [구현] `AtelierX Detailer Pipeline (Impact)`: Face→Eye→Mouth→Hand 순서, pass별 enabled + detector 문자열. 기본 `bbox/face_yolov8m.pt`(Face·Mouth), `segm/PitEyeDetailer-v2-seg.pt`, `bbox/hand_yolov8s.pt`, SAM `sam_vit_b_01ec64.pth`. 입력 MODEL/CLIP/VAE, positive/negative CONDITIONING, seed 0, steps 10, cfg 5.0, `euler_ancestral`/`normal`, denoise 0.5. 필요 Impact class `UltralyticsDetectorProvider`, `SAMLoader`, `ToDetailerPipe`, `FaceDetailerPipe`; 누락 시 enabled pass 실행 때 class 이름 포함 오류. disabled pass는 로드 안 함, 전부 off면 입력 그대로.
- [구현] `AtelierX Detailer`(보조, 외부 mask): 패키지 README 참조. 코드 기본 steps 20, cfg 5.0, `euler`, denoise 0.35, grow_mask_by 6.
- [제한] Mouth는 전용 detector가 아니라 얼굴 detector fallback(참고 Workflow와 동일). 사용자는 원본 이미지의 생성 Prompt·모델을 맞춰야 함.
- 참고 구현: kiritype/ComfyUI-AssetManager.

#### AtelierXDetectNsfwMask / AtelierXCensor (atelierx_censor)
- [구현] Detect: `segmentation_model`(ultralytics_segm), `labels` 기본 `nipples,pussy,penis,anus,testicles,x-ray,cross-section`, confidence 0.35. 해당 라벨 mask 합성. 검출 0은 정상(이미지 유지), 모델 오류·잘못된 라벨은 오류.
- [구현] Censor: `treatment` mosaic(기본)/white(feathered)/white_solid, `intensity` 15(1~128, dilation=intensity 기반), enabled. 영역 밖·Alpha 보존, off면 원본.
- [제한] 검열 대상 검출률 미평가(의상 착용 이미지 검출 0만 확인).

#### AtelierXDetectCharacterMask / AtelierXApplyCharacterAlpha (atelierx_alpha)
- [구현] Detect: `segmentation_model`(ultralytics_segm), confidence 0.35, COCO person(0) 전체 결합, `retina_masks` 크기 불일치·검출 없음은 오류(Alpha 불변).
- [구현] Apply: 패키지 README 참조(enabled 기본 true).
- [구현] Core 연결: Task snapshot에 `postprocess.alpha`가 있으면 검사 요청 `expected_output.alpha=transparency_required`, 없으면 `not_required`(원래 생성 설정 기준, PNG/WebP 동일). 투명 영역 없으면 `completed/failed`, AI 검사 생략. `output_conditions=false` Profile은 검사 안 함. 최소 면적·경계 품질 기준 없음.
- [제한] 한 명 선택·SAM·BiRefNet/rembg·머리카락 경계는 N-10 미결정. 분리 품질 미평가.

#### AtelierXEncodeSave (atelierx_encode)
- [구현] 입력·기본값·저장 규칙은 패키지 README 참조.
- [구현] 선택 입력 `output_name`(ADR-0026): 비어 있지 않으면 `<ComfyUI output>/<output_name>.png`(+`.webp`)로 저장하고, PNG·WebP 중 하나라도 있으면 두 확장자가 모두 없는 첫 ` (n)` 번호를 함께 쓴다. 이름 규칙은 공용 `src/atelierx/output_names.py`와 같다(Node 쪽 복제, 일치 테스트). 비어 있으면 기존 UUID 이름 저장과 같다.
- [구현] Generation 연결: `inputs.output_name`(선택)은 Job 입력·멱등 식별에 포함된다. 지정되면 반드시 Encode Node로 저장하며, `encode` 단계가 없으면 `webp_enabled=false`로 추가한다(SaveImage 경로 미사용). 등록된 Encode Node에 `output_name` 입력이 없으면 503으로 거부한다. 독립 후처리(`POST /v1/images/{id}/postprocess-jobs`) 본문도 같은 규칙의 `output_name`을 받는다. 결과 `images[]`에는 ComfyUI history의 `subfolder`/`filename`에서 만든 출력 폴더 기준 상대 경로 `output_path`(모를 때 null)를 기록한다. `<data-dir>/images/` 내부 사본은 그대로다.
- [미검증] 설치된 ComfyUI에서 `output_name` 저장·충돌 번호 실제 실행은 아직 확인하지 않았다.

### 의존성·모델 목록

| 이름 | 필수/선택 | 폴더(ComfyUI 등록명 → 설치 경로) | 사용 노드 |
| --- | --- | --- | --- |
| Anima diffusion model (검증: `waiANIMA_v10Base10.safetensors`) | 필수 | diffusion_models → `Models\DiffusionModels` | AnimaGenerate, Detailer 예제 |
| 대응 Qwen3 0.6B Text Encoder (`waiANIMA_v10Base10_txt.safetensors`) | 필수 | text_encoders(clip) → `Models\TextEncoders` | AnimaGenerate |
| `qwen_image_vae.safetensors` | 필수 | vae → `Models\VAE` | AnimaGenerate |
| Anima LoRA (예: `anima-base-1-masterpiece-v51`, `anima-highres-aesthetic-boost`) | 선택 | loras → `Models\Lora` | AnimaGenerate |
| `4x-UltraSharp.safetensors` | Upscale 사용 시 필수(기본) | upscale_models → `Models\ESRGAN`(또는 RealESRGAN/SwinIR) | Upscale |
| ComfyUI-Impact-Pack + Impact-Subpack | Impact Detailer 필수 | `ComfyUI\custom_nodes` | ImpactDetailerPipeline |
| `bbox/face_yolov8m.pt` | Face·Mouth pass 필수 | ultralytics_bbox → `Models\Ultralytics\bbox` | ImpactDetailerPipeline |
| `segm/PitEyeDetailer-v2-seg.pt` | Eye pass 필수 | ultralytics_segm → `Models\Ultralytics\segm` | ImpactDetailerPipeline |
| `bbox/hand_yolov8s.pt` | Hand pass 필수 | ultralytics_bbox | ImpactDetailerPipeline |
| `sam_vit_b_01ec64.pth` | Impact Detailer 필수 | sams → `Models\Sams` | ImpactDetailerPipeline |
| `ntd11_anime_nsfw_segm_v5-variant1.pt` (사용자 제공 `animeNSFWDetection_v50Variant1.zip`, SHA-256 `d04eec2d…0cc900`) | 자동 Censor 필수 | ultralytics_segm | DetectNsfwMask |
| `person_yolov8n-seg.pt` (설치 Workflow 선택값, 로그 미기재) | 자동 Alpha 필수 | ultralytics_segm | DetectCharacterMask |
| Python `ultralytics`(검증 8.4.150) | Detect 노드·Impact 필수 | ComfyUI venv | Alpha/Censor Detect, Impact |
| Python `segment-anything`(1.0) | Impact SAM 필수 | ComfyUI venv | ImpactDetailerPipeline |

### 패키지 README 불일치 (리팩토링 단계에서 정비)

코드 기준이 우선한다.

- `atelierx_censor`: README는 NudeNet ONNX 어댑터(`model_path`, `block_size`)로 설명하지만 코드는 ultralytics_segm YOLO + `labels`, treatment `white_solid`, `intensity`를 사용한다.
- `atelierx_anima`: README의 임시 기본 512×512와 달리 코드 기본은 1024×1024다.
- Detailer·Alpha·Censor README의 "모델·runtime 없음" 서술은 구식이다. 현재 설치 환경에는 Ultralytics·SAM·Impact Pack과 기본 weight가 있다.
- 설치된 사용자 Workflow 일부(Censor·Detailer 자동 검출, Dynamic LoRA)는 저장소 examples와 다르며, Impact Pack 소스는 Git 제외 경로에 있어 새 clone에서 재현 경로가 없다. 원본 추적 위치와 설치 안내가 필요하다.
