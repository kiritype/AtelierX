# Generation REST 첫 구현·검증

2026-09-13 사용자 구현 착수 지시에 따라 준비된 Node부터 하나씩 REST로 검증한다. 이번 구현은 Anima 생성 경로의 첫 단위이며 Backend 전체 완료가 아니다.

## 구현 범위

- Python 3.12 + aiohttp, 저장소 전용 `.venv`를 사용한다. ComfyUI venv·의존성을 변경하지 않는다. Generation 프로세스는 Torch·ComfyUI 모듈·SQLite·AI Provider를 직접 사용하지 않는다.
- `/object_info`에서 Anima·SaveImage 등록과 입력 목록을 확인한다. 모델 계열의 실제 호환성은 Node 실행 검사로 최종 확인한다.
- `POST /prompt`로 Anima → ComfyUI 기본 SaveImage Workflow를 실행한다. SaveImage 사용은 제품 Encode/Save Node 완료를 뜻하지 않는다.
- 접수 시 최종 문구·설정·LoRA 순서를 고정한다. API의 `loras` 배열을 Node의 `lora_stack` JSON 문자열로 변환한다.
- Generation 전용 JSON 파일에 Job과 접수 키를 원자적으로 기록하고 PNG를 Generation 저장 영역으로 가져온다. 이 기록은 Core의 도메인·SQLite 소유권을 대체하지 않는다.
- 단일 worker가 FIFO로 처리하며 ComfyUI 대기/실행이 있으면 새 작업 제출을 기다린다. 기존 사용자 작업을 중단·삭제하지 않는다. 확인 직후 사용자의 직접 제출 경쟁까지 배제하지는 못한다.
- 같은 키·동일 내용은 기존 Job, 다른 내용은 409. ComfyUI 응답 유실 시 미리 저장한 prompt_id로 조회하며 생성 요청을 자동 재전송하지 않는다. 재시작 후 queued는 실행하고 제출된 작업은 조회로 추적한다. queue/history 모두에 없으면 오류로 종료한다.
- 등록 모델명·타입·범위·16배수 크기·LoRA 이름과 가중치를 검사한다. API 요청은 Bearer 인증, 기본 bind는 loopback이다.

## 초기 REST 계약

모든 경로에 `Authorization: Bearer <ATELIERX_SERVICE_TOKEN>`이 필요하다.

| Method / 경로 | 동작 |
| --- | --- |
| GET /health | 서비스 프로세스 상태. Node 준비 상태와 구분 |
| GET /v1/nodes | 현재 Anima 등록·Node 입력 Schema·지원 범위 |
| POST /v1/nodes/anima/jobs | `Idempotency-Key` 필수. body는 `{"inputs": {...}}`. 신규 202, 동일 요청 200 |
| GET /v1/jobs/by-key | `Idempotency-Key`로 응답 유실 요청 조회 |
| GET /v1/jobs/{job_id} | 상태·입력·이미지·오류 조회 |
| GET /v1/images/{image_id} | 해당 서비스가 수집한 PNG 조회. 임의 파일 경로 입력 없음 |

`inputs` 필수 항목: diffusion_model, text_encoder, vae, positive_prompt, negative_prompt, width, height, seed, steps, cfg, sampler, scheduler. 선택 `loras`는 순서 있는 `[{"name":"등록 파일명","strength":0.35}]` 배열이며 기본 빈 배열이다. 음성/이미지 Prompt 조합이나 모델 기본값 추정은 하지 않는다. JavaScript Client는 큰 64비트 seed를 손실 없이 다루는 별도 계약 전까지 안전한 정수 범위로 제출해야 한다.

상태는 queued → submitting → submitted/running → completed/failed다. submitting은 제출 전 저장 상태로, 재시작 시 생성 POST를 반복하지 않는다. completed에는 image_id·SHA-256·byte 수·상대 조회 URL을, failed에는 오류 코드·안내를 반환한다. 입력 오류는 접수 전 400, 인증 401, 미등록 Job/이미지 404, 키 충돌 409, Node/ComfyUI 준비 오류는 503이다. 접수 후 실행 오류는 조회 HTTP 200의 failed Job으로 반환한다. 초기 오류 코드와 저장·API는 구현 계약이며 독립 ADR 승인을 새로 요구하지 않는다.

## 실행

저장소 루트 PowerShell에서:

```powershell
uv --cache-dir .uv-cache venv .venv --python 3.12
uv --cache-dir .uv-cache pip install --python .venv/Scripts/python.exe -e .
$env:ATELIERX_SERVICE_TOKEN = Read-Host 'Generation 서비스 토큰'
.venv/Scripts/python.exe -m atelierx.generation --port 8189
```

Python 3.12가 이미 설치되어 있으면 `--python`에 해당 실행 파일을 지정할 수 있다. 현재 환경에서는 ComfyUI Python 실행 파일을 interpreter로 지정해 독립 venv를 만들었다. 서비스 데이터는 기본 `.atelierx/generation`이며 `--data-dir`, ComfyUI 주소는 `--comfy-url`로 지정한다. 한 데이터 디렉터리/GPU에는 Generation 한 프로세스만 실행한다. 현재 다중 프로세스 소유권 잠금은 미구현이다.

```powershell
.venv/Scripts/python.exe -m unittest discover -s tests -v
.venv/Scripts/python.exe scripts/test_generation_rest.py
```

두 번째 명령은 실제 GPU 작업 두 건을 순차 실행하는 개발용 검사다. ComfyUI가 비어 있는지 확인하고 임시 Generation HTTP 서버를 시작한다. 종료 시 Generation 검사 서버만 종료하며 ComfyUI는 유지한다. 제품 CLI가 아니다.

## 실제 검증 기록

- Node 사전 점검: Terra가 Anima Python 17개·frontend widget 1개·설치 registry/API 예제 검사 통과를 확인했다. Alpha 5개·Upscale 5개 단위 검사와 각 예제 JSON 검사는 통과했으나 전체 기능 완료가 아니다.
- Generation 통합 자동 검사 6개 통과: 인증/잘못된 입력/Node 미등록, 동시 중복 접수·충돌·재시작, 사용자 queue 대기·LoRA 변환, 접수 응답 유실·재시작 추적·이미지 조회, 실행 오류, 접수 거절·작업 유실 후 재전송 금지.
- 실제 REST → ComfyUI → Generation 결과 수집: Anima 기본 → 다중 LoRA 순서로 성공. WAI-ANIMA, 대응 Text Encoder, qwen_image_vae, 768×1024, 24 steps, CFG 4.5, euler_ancestral / normal.
- 기본 Job: `857bf086-fa6d-44e4-a096-b984269ca9f2`, seed 3256118108.
- 다중 LoRA Job: `76181196-5066-4ae8-bdf2-3bd22086c016`, seed 894260189. masterpiece-v51 0.35 → highres-aesthetic-boost 0.5.
- 두 결과 모두 API 다운로드 PNG signature·크기·SHA-256 일치, 동일 요청 키 재접수는 기존 Job, 다른 내용은 409 확인. 다중 LoRA PNG를 시각적으로 열어 출력도 확인했다. Validation 판정 품질 검증은 아니다.
- 실행 자료: `artifacts/generation-rest/20260913-033051/report.json`, `anima-base.png`, `anima-multi-lora.png`. 생성 자료는 Git에서 제외한다. ComfyUI에는 `output/AtelierX` 아래 SaveImage 결과가 남는다.

## Node별 준비 상태와 다음 단계

| Node | 현재 상태 | REST 확장 전 필요한 작업 |
| --- | --- | --- |
| Anima | 생성·순서 있는 다중 LoRA·설치·이번 REST 실생성 확인 | Preset 등 잔여 기능, UI 최신 저장/재로딩 최종 확인은 별도 |
| Upscale | 모델 기반 처리 prototype·단위 검사만 완료 | Upscale weight 준비·설치·실제 Node 실행 확인 |
| Alpha | 제공된 마스크 적용 prototype·단위 검사만 완료 | 캐릭터 검출 부분·필수 모델·설치·실제 실행 확인 |
| SDXL / Detailer / Censor / 제품 Encode·Save | 이번 준비 완료 대상 아님 | 구현·자원·설치 확인 후 순차 REST 검증 |

Core·Validation·제품 CLI는 이번 변경에서 구현하지 않았다. 다음은 이 Generation 경로에 Core 요청·결과 기록을 연결하는 최소 통합이다. Generation도 아직 취소·SSE·페이지 목록·공유 GPU 권한·실행/대기 Timeout·분산 TLS·보관 정리·다중 프로세스 잠금이 없다. ComfyUI 중단 시 관찰을 계속하며 새 generation POST를 보내지 않는다. 제출 중 또는 실행 중 불명 상태의 운영 복구는 후속 확장한다. 나머지 Node는 준비 확인 전 성공 경로로 노출하지 않는다.

기술 참고: [aiohttp 공식 서버 문서](https://docs.aiohttp.org/en/stable/web_quickstart.html), 설치된 ComfyUI `server.py`의 object_info/prompt/queue/history/view 처리. 변경값은 실행 검증 결과에 따라 이 문서와 계약을 함께 갱신한다.

## 후속 구현

[후처리 API](generation-postprocess.md), [Backend 통합](backend-pipeline-integration.md)에서 실제 설치된 Detailer/Censor/Alpha/Encode와 Core/Validation 연결 결과를 확인한다. 위 초기 준비 상태에 대한 후속 기록이다.
