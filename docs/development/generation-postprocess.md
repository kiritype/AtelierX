# Generation 보조 후처리 REST 경로

[2026-09-13 실제 VLM까지 연결한 통합 기록](real-vlm-pipeline-2026-09-13.md): Generation의 전체 후처리 출력 PNG/WebP를 실제 LM Studio로 검증하고 Core에 저장·복원했다.

2026-09-13 구현 초안. Generation은 임의 ComfyUI graph, 서버 파일 경로,
업로드 경로를 API로 받지 않는다. Anima 출력에 이미 설치·등록된 노드만 정해진
순서로 덧붙이고, 접수한 설정을 Job JSON에 고정한다.

## 준비 상태 확인

실행 중인 Generation 서비스에서 다음 요청으로 실제 ComfyUI 등록 상태와 각
보조 단계의 API 지원 여부를 확인한다.

```powershell
$headers = @{ Authorization = "Bearer $env:ATELIERX_SERVICE_TOKEN" }
Invoke-RestMethod http://127.0.0.1:8189/v1/nodes -Headers $headers
```

`detailer`, `censor`, `alpha`, `encode`는 `registered: true`일 때만 접수된다. 등록 상태는
ComfyUI의 `/object_info/<node>`를 접수 시 다시 읽어 모델 COMBO 목록까지
검사한다. Detailer는 Anima node가 IMAGE만 반환하므로, 같은 등록 Anima UNET·text
encoder·VAE를 다시 로드하고 original positive/negative 및 순서 있는 model-only
LoRA stack을 재구성해 Impact Pipeline에 연결한다.

## Anima 요청의 선택 `postprocess`

기존 body `{"inputs": {...}}`는 그대로 유효하다. 아래처럼 `postprocess`를
추가할 수 있다. `Idempotency-Key`의 동일성 계산에는 `inputs`와 이 객체가 모두
포함된다. 같은 키에 다른 후처리 설정을 보내면 409이다.

```json
{
  "inputs": { "diffusion_model": "...", "text_encoder": "...", "vae": "...", "positive_prompt": "...", "negative_prompt": "", "width": 768, "height": 1024, "seed": 1, "steps": 24, "cfg": 4.5, "sampler": "euler_ancestral", "scheduler": "normal" },
  "postprocess": {
    "detailer": { "face_enabled": true, "eye_enabled": true, "mouth_enabled": true, "hand_enabled": true, "face_detector_model": "bbox/face_yolov8m.pt", "eye_detector_model": "segm/PitEyeDetailer-v2-seg.pt", "mouth_detector_model": "bbox/face_yolov8m.pt", "hand_detector_model": "bbox/hand_yolov8s.pt", "sam_model": "sam_vit_b_01ec64.pth", "seed": 1, "steps": 10, "cfg": 5.0, "sampler_name": "euler_ancestral", "scheduler": "normal", "denoise": 0.35 },
    "censor": { "segmentation_model": "ntd11_anime_nsfw_segm_v5-variant1.pt", "labels": "nipples,pussy,penis,anus,testicles,x-ray,cross-section", "confidence": 0.35, "treatment": "mosaic", "intensity": 15 },
    "alpha": { "segmentation_model": "REGISTERED_PERSON_SEGMENTATION_MODEL.pt", "confidence": 0.35 },
    "encode": { "webp_enabled": true, "webp_quality": 90 }
  }
}
```

실행 순서는 `Anima → Detailer → Censor detect/apply → Alpha detect/apply → Encode`다. 각
stage는 선택 사항이며 stage 내부의 알 수 없는 필드는 400으로 거절한다. Censor와
Alpha의 model 값은 `/object_info`에 현재 등록된 선택지여야 한다. Encode만 쓰면
PNG와 선택 WebP를 생성하며, Encode를 생략하면 기존 `SaveImage` PNG 경로가
그대로 유지된다. 실행 오류·응답 유실 이후에는 기존 prompt ID를 history/queue로만
추적하며 자동 재제출하지 않는다.

Job 응답의 `requested_postprocess`는 접수 body의 원본 객체(없으면 `{}`)이고,
`postprocess`는 기본값을 채운 검증 후 실행 snapshot이다. Core는 전자로 요청
동일성을 비교하고 후자로 실제 ComfyUI 실행 구성을 기록할 수 있다.

## 출력 위치와 조회

ComfyUI 자체 출력은 다음이다.

- 기존 SaveImage: `C:\StabilityMatrix\Packages\ComfyUI\output\AtelierX`
- Encode 단계: `C:\StabilityMatrix\Packages\ComfyUI\output\AtelierX`

Generation 서비스가 수집한 복사본은 서비스 `--data-dir` 아래
`images\<job_id>-<index>.png` 또는 `.webp`다. 기본 data dir를 썼다면 저장소의
`.atelierx\generation\images`이다. 클라이언트는 디스크 경로 대신 completed job의
`images[].url` (`GET /v1/images/{image_id}`)과 `media_type`을 사용한다. 원본
ComfyUI 출력 보존·삭제 정책은 이 구현이 변경하지 않는다.

## 현재 경계

기존 Generation image ID만 받아 다시 후처리하는 별도 endpoint는 아직 제공하지
않는다. Generation 저장소와 ComfyUI input/output이 분리되어 있어, 이를 안전하게
하려면 ID 검증된 ComfyUI upload와 별도의 durable postprocess Job 복구 계약이
필요하다. 임의 경로나 graph를 받는 우회는 추가하지 않는다.

테스트는 mock ComfyUI HTTP에서 등록 모델 검사, 고정 graph 순서, PNG/WebP 수집과
미디어 타입과 미지정 graph 거절을 확인한다.
