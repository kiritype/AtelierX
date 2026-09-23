# Core·Generation 현행 사양

표기: **[확정]** 사용자 확정·Accepted ADR, **[구현]** 현재 코드 동작(초기 운영값 포함), **[제한]** 미구현·미검증·알려진 한계. 날짜별 검증 기록은 로컬 전용 `docs/history/`에 있다. 후처리 stage·독립 후처리 계약은 [REST API](../api/rest-api.md#후처리-stage와-독립-후처리-상세)에 있다.

### 서비스 실행·저장 소유
- [구현] 저장소 전용 Python 3.12 `.venv`(`pip install -e .`)를 쓰고 ComfyUI venv·의존성은 건드리지 않는다. Generation은 Torch·ComfyUI 모듈·SQLite·AI Provider를 직접 쓰지 않고 ComfyUI REST(`/object_info`, `/prompt`, `/queue`, `/history`, `/view`, `/upload/image`, `/free`)만 호출한다
- [구현] 세 서비스는 loopback 바인딩·Bearer(`ATELIERX_SERVICE_TOKEN`) 인증. Core의 Generation 호출 토큰은 `ATELIERX_GENERATION_TOKEN`으로 따로 지정할 수 있다. 토큰은 문서·공유 파일에 기록하지 않는다
- [구현] 권장 기동 순서: ComfyUI(8188)·LM Studio(1234) → Core `--port 8190 --generation-url … --validation-config … --gpu-config …` / Generation `--port 8189 --coordinator-url http://127.0.0.1:8190` / Validation `--port 8191 --config …`. 로컬 설정은 `.atelierx/validation-coordinated-config.json`, `.atelierx/gpu-config.json`이며 공유 예제는 `config/validation-coordinated.example.json`, `config/gpu.example.json`
- [구현] Core 기본 DB `.atelierx/core/core.sqlite3`(WAL·외래 키·트랜잭션). Generation 기본 data-dir `.atelierx/generation`(`--data-dir`, `--comfy-url`). 세 서비스 모두 data-dir별 ProcessLock으로 한 프로세스만 소유한다 (코드: common.py)
- [구현] Core·Generation HTTP 요청 본문 상한은 2 MiB. 이미지 출력·조회 상한은 128 MiB (코드: core/__init__.py)

### Generation 접수·실행
- [구현] `/v1/nodes`는 ComfyUI `/object_info`로 등록 Node·모델 선택지를 확인한다. 후처리 stage는 `registered: true`일 때만 접수하며 접수 시 `/object_info/<node>`를 다시 읽어 COMBO 선택지까지 검사한다. 나머지 Node는 준비 확인 전 성공 경로로 노출하지 않는다
- [구현] 접수 시 최종 문구·설정·LoRA 순서를 고정한다. API `loras` 배열은 Node의 `lora_stack` JSON 문자열로 변환한다. 등록 모델명·범위·16배수 크기·LoRA 이름/가중치를 검사한다. 모델 기본값 추정은 하지 않는다
- [구현] Job·접수 키는 Generation 전용 JSON에 원자적으로 기록한다. 이 기록은 Core 도메인·SQLite 소유권을 대체하지 않는다. 단일 worker FIFO로 처리하며, ComfyUI에 대기·실행 중 작업이 있으면 새 제출을 기다리고 사용자 작업을 중단·삭제하지 않는다. 확인 직후의 직접 제출 경쟁은 막지 못한다
- [구현] 제출 전에 `submitting`과 prompt_id를 저장하므로 재시작 시 생성 POST를 반복하지 않는다. 재시작하면 queued Job은 실행하고 제출된 Job은 history/queue 조회로 추적한다. 두 곳 모두에 없거나 `/prompt` 응답 ID가 저장값과 다르면 `GEN_EXECUTION_UNKNOWN`으로 끝내고 GPU 권한을 보존한다. ComfyUI가 중단되면 관찰만 계속하고 새 POST는 보내지 않는다 (코드: generation/__init__.py)
- [구현] 오류 코드: 입력 400, 인증 401, Job/이미지 없음 404, 키 충돌 409, Node/ComfyUI 미준비 503. 접수 후 실행 오류는 조회 HTTP 200의 failed Job으로 반환한다
- [구현] 출력: ComfyUI 원본은 `output/AtelierX`(SaveImage·Encode)에 남는다. Generation 사본은 `<data-dir>/images/<job_id>-<index>.png|.webp`이다. 클라이언트는 경로 대신 `images[].url`·`media_type`을 사용한다. ComfyUI 원본의 보존·삭제 정책은 바꾸지 않는다

### Core 오케스트레이션·GPU 조정·취소
- [확정] Client는 시작 옵션만 전달하고 생성 후 검증은 Core가 조정한다(생성만/생성 후 검증 선택). Client가 완료를 polling한 뒤 검증 POST를 할 필요가 없다
- [구현] GPU coordinator: Core SQLite `gpu_state`에 owner·FIFO waiting·blocked를 저장한다. 같은 Job이 다시 요청하면 기존 권한을 돌려준다. 권한은 시간이 지나도 만료되지 않는다. phase는 generation/validation/planner (코드: gpu.py)
- [구현] 준비 절차: ComfyUI queue가 비어 있어야 한다. generation phase에서는 설정 모델이 아닌 LM Studio 모델이 로드돼 있으면 대기하고, 설정 모델은 `lms ps --json`으로 idle·queued=0을 확인한 뒤 native REST로 unload한다. 이어 ComfyUI `/free` 후 `nvidia-smi` 여유 VRAM을 최대 10회×0.5초 확인한다. 기준은 `minimum_free_mib[phase]` 기본 18000이고, validation/planner에서 설정 VLM이 이미 로드돼 있으면 `resident_minimum_free_mib` 기본 128이다. 이 값은 RTX 4090·현재 모델의 초기 운영값이다 (코드: gpu.py)
- [구현] 조정 실패(연결·파싱 오류)는 권한 보류로 처리한다. Generation은 권한을 얻은 뒤 다른 ComfyUI 작업을 발견하고 아직 미제출이면 권한을 반납하고 대기한다 (코드: gpu.py)
- [구현] 취소: 대기 중이면 즉시 취소, 제출·실행 중이면 cancel_requested를 두고 실제 종료를 기다린 뒤 결과를 버리는 협력 취소다. ComfyUI 전체 interrupt는 호출하지 않는다. Core에 취소가 먼저 저장되면 늦게 온 판정으로 덮지 않는다
- [구현] Core Queue kind: generation, validation, standalone, postprocess, group_validation. 제작 계획·그룹 batch는 Queue 목록에 없다 (코드: core/__init__.py `attach_queue_api`)
- [제한] 공유 GPU에 참여하지 않는 서비스나 직접 ComfyUI/LM Studio 실행과의 경쟁은 원자적으로 막지 못한다. 협력 취소는 시작된 GPU 계산을 강제로 멈추지 않는다. 실행 불명 상태의 GPU 권한은 자동으로 풀지 않으므로 운영자 복구가 필요하다(복구 UI는 후속). 과거 이벤트 재생, ComfyUI Node 진행률, 다중 GPU·Provider별 병렬 worker, 전체 실행/대기 기한은 없다

### 그룹 batch (호환 API)
- [구현] `CoreBatches`: 같은 그룹의 item 1..32개를 하나의 durable batch로 고정한다. item마다 `Core.preview()` snapshot, fingerprint, 내부 item key를 저장해 재시작 시 같은 Task만 복구한다. 흐름은 생성 → 단일 검증 → 자동 재생성 cycle 관찰이다. item 종료 상태는 passed, single_failed, generation_failed, cancelled, generation_only이고 batch 종료 상태는 completed, failed, cancelled, insufficient_images다 (코드: core/batches.py)
- [구현] 기준이 없으면 `reference_proposal`만 보관한다. 통과 0/1장이면 `insufficient_images`, 그 외는 `awaiting_reference_confirmation`이다. 기준을 자동 저장·교체하지 않는다. confirm-reference sequence가 group run key에 들어가 이전 key와 충돌하지 않는다. terminal batch의 cancel은 no-op이다. worker는 `groups.tick()` 다음에 `batches.tick()`을 호출한다

### 전역 조각·제작 계획
- [확정] 조각은 작품·캐릭터·의상과 독립된 전역 공유 라이브러리다. 사용자가 작성한 조각을 체크해 가져오며, AI 자동 생성이나 무작위 선택은 하지 않는다. 조각 하나가 이미지 하나이고 줄·쉼표로 나누거나 구도×표정×동작으로 곱하지 않는다. 제품 차원의 생성 개수 상한은 없고 32개 초과를 지원한다. 이미지별 자동 재생성 상한(기본 5)은 생성 수와 별개다. 오류가 나도 자동 재생성하지 않는다
- [확정] 수천 장을 접수해도 Core가 전체 계획과 대기 상태를 영속 표시해야 한다. 실행 직전 일부만 계획처럼 보여 주지 않는다. 대기 항목도 조회·취소·재시작 복구가 되어야 한다. 내부 분할 크기는 처리 단위일 뿐 총수 상한이 아니다. 묶음 검증을 내부 분할할 때 모든 요청이 같은 기준 revision을 쓴다
- [구현] 계획 전체를 한 트랜잭션으로 저장(draft, Task 미생성)하고 `plan_hash` 일치 start 후 실행한다. 실행 창 8개, 묶음 target chunk 32개. 계획 상태는 draft → running → group_validation_pending / awaiting_reference_confirmation → completed / failed / cancelled / insufficient_images(기준 없음 + 통과 2장 미만)이고 중간 상태로 cancellation_pending이 있다. outcome은 passed/failed/incomplete/error/unvalidated다. 항목 상태는 queued, generation_pending, single_validation_pending, passed, single_failed, generation_failed, cancelled, generation_only (코드: core/production_plans.py)
- [구현] 복구: Task를 저장했으나 항목 연결 전에 중단되면 재기동 후 연결하거나 취소한다. 묶음 Run 저장 후 비교 연결 전 중단은 plan/sequence/chunk 고정 키로 복원한다. 단일·묶음 검사 중 취소는 Provider 종료까지 계획을 cancellation_pending으로 두며, 남은 항목 접수나 후속 묶음은 시작하지 않는다
- [구현] 다중 그룹 F/E는 catalog를 200개씩 읽고 그룹별 독립 계획(키·본문 고정)으로 접수한다. 부분 접수 실패를 전체 성공으로 표시하지 않는다
- [확정] ADR-0026: 이미지별 조각 번호는 사용자가 입력·수정하고 중복은 경고 후 허용한다. 공통 적용 조각은 번호가 없다. 의상은 상의·하의·액세서리·손이며 조각의 손 포함 기본값은 true다. 출력은 `AtelierX\<작품>\<캐릭터>\<복장>\<조각번호>`, Discord는 `AtelierX\discord\<날짜>\`다
- [구현] 조각 번호는 TEXT(1–32자, 파일명 안전 문자열)이고 고유 인덱스·자동 순번을 쓰지 않는다. POST/PATCH 응답 `warnings`와 `GET /v1/prompt-fragments/number-check`로 중복을 알린다. 시작 시 INTEGER 번호 표를 재구성해 기존 번호를 문자열로 유지한다 (코드: core/fragments.py)
- [구현] 출력 파일명: Core가 접수 시 `generation_inputs.output_name`을 고정한다(조각 Task·계획 항목은 preview, 조각 없는 Task는 Task 저장 시 `task-<계보 ID 앞 8자>`, 재생성은 원래 이름 재사용, Discord는 `AtelierX/discord/<날짜>/<시각>-<Job ID 앞 6자>`, 독립 후처리는 본문 `output_name`). 이름 요소 정리는 Core 내부 `core/_output_names.py`(공유 모듈과 같은 계약)다. 이미지 문서는 Generation이 보고한 `output_path`를 저장한다
- [구현] ADR-0025 검사 범위: preview snapshot의 `positive_check`(캐릭터 핵심 특징 또는 외형, 포함된 의상 부분, 이미지별 조각/기존 입력)를 단일 검증 요청 `image.positive_check`로 전달한다. 전역 품질·공통 적용 조각은 제외한다. 캐릭터 `check_features`는 0..50개·항목 200자 이하다 (코드: core/__init__.py, core/validation.py)
- [구현] ADR-0025 E 생성당 1회 단일 검증: 자동 검증은 Task 출력 중 대표 이미지 하나(PNG가 있으면 첫 PNG, 없으면 첫 출력)만 Provider에 보낸다(키 `auto:<task>:<대표 image>`). 실행 기록 `shared_image_ids`에 같은 시도의 다른 형식 출력 ID를 남기고, 그 결과를 해당 이미지 문서 `validation`에 `shared_from_image_id`(대표 이미지 ID)와 같은 run `id`로 복사한다. 따라서 갤러리 `single_outcome`, 계획·batch `passed_image_ids`, 묶음 대상·기준 후보가 같은 판정을 쓴다. Task `validation`에는 `representative_image_id`와 image 항목별 `shared_from_image_id`가 붙는다. 수동 `POST /v1/images/{id}/validations`는 기존대로 그 이미지에만 적용하며, 자체 실행 기록이 있는 이미지는 공유 결과로 덮지 않는다. 과거에 형식별로 두 번 검증한 Task는 기존 run들을 그대로 평가한다 (코드: core/validation.py, core/store.py)
- [구현] ADR-0025 F 제안 없는 불합격의 Seed 재생성: 자동 cycle에서 불합격 run에 유효한 변경 제안이 없으면(제안 없음 `proposal_unavailable`, Validation이 버린 제안 `proposal_dropped`, Core `validate_changes` 불통과 `proposal_invalid`) 이전 snapshot을 그대로 두고 Seed만 `0..2^53-1` 무작위 새 값으로 바꿔 자동 재생성한다. 자식 Task `regeneration.change`와 cycle `last_change`에 `{kind: "seed_only", reason, previous_seed, seed}`를 기록하고, 유효 제안이면 `{kind: "proposal", fields}`를 기록한다. 같은 부모에 대한 Seed 선택은 cycle에 먼저 저장해 재시도해도 바뀌지 않는다. 상한(기본 5)·자동 재생성 꺼짐·`error` 판정 비재생성·수동 재생성·묶음 규칙은 그대로다 (코드: core/regeneration.py)
- [제한] Generation·Encode Node의 `output_name` 적용과 Validation의 `positive_check` 해석은 각 서비스 구현에 의존한다. 실제 ComfyUI 출력 폴더 구조·충돌 번호는 이 Core 변경만으로 검증되지 않았다
- [구현] Seed: Core 입력 -1은 snapshot 확정 시 `secrets.randbelow(2**53)`로 한 번 치환한다. 0 이상 지정값은 그대로 모든 항목에 쓰며 index 파생은 없다 (코드: core/store.py)
- [제한] 그룹 목록을 한 화면에 렌더링하므로 대량 그룹에는 검색·페이지가 필요하다. 3,000장 실제 GPU 실행, 장기 무인 운영, 프롬프트에 구체화되지 않은 외형 차이(머리 길이 등)의 일관성 판정 품질은 검증되지 않았다

### 조회 API 구현 특성
- [제한] 갤러리 상태 필터는 SQL로 후보를 좁힌 뒤 검증 상태를 계산하고 그룹별 집계도 호출한다. 따라서 페이지 크기만큼만 읽는 구현이 아니며 대량 성능 측정이 남았다

### 복구·운영 절차(현행 유효)
- [구현] 수락 불명 경계: 외부 proxy나 본문 전송 지연으로 원래 POST가 handler에 닿기 전에 키 조회가 404를 받으면, acceptance-unknown 오류로 두고 재전송하지 않는다. 그 뒤 도착한 원격 요청의 정리는 보장하지 않으며 운영자가 원격 큐·키를 확인해야 한다. 무인 운영 전에는 별도 접수 예약/취소 계약이 필요하다
- [구현] 운영 대응: 작업 현황에서 계획·Task·단일·묶음 상태와 error를 함께 본다(completed는 합격이 아니다). 응답을 잃었으면 새 계획을 만들기 전에 기존 접수를 확인한다(브라우저 메모리 키는 새로고침하면 사라진다). 중단은 계획 취소 후 cancellation_pending 종료로 확인한다. outcome=error는 연결·모델을 고친 뒤 사용자가 재검증하거나 수동 재생성한다. 재시작 전에는 ComfyUI 직접 실행·다른 작업이 없는지 확인한다. 실패 이력·DB·이미지를 지우거나 새 ID로 반복 접수해 복구하지 않는다
- [구현] 실환경 REST 시험 원칙: ComfyUI queue가 비어 있고 LM Studio가 idle일 때만 시작하며, 사용자 작업이 있으면 시험을 중단한다. 임시 포트·별도 data-dir(또는 SQLite backup 복사본)을 쓰고 파일럿 DB·서비스를 건드리지 않는다. 종료 시 GPU owner=null·waiting=[]를 확인하고, 시험 서비스만 끄며 ComfyUI·LM Studio는 유지한다. 주요 스크립트: `test_backend_pipeline_rest.py`(`--cases`, `--real-vlm`, `--automatic`, `--manual-regeneration`, `--group-validation`, `--group-replacement`), `test_group_batches_rest.py --resume <dir>`(새 생성 없이 재개), `test_plan_gpu_recovery_rest.py --confirm-exclusive-gpu`(`--dry-run` 제공), `test_core_independent_postprocess_rest.py`, `test_core_browse_rest.py`, `run_test_suite.py --phase cpu|generation|vision --output <dir>`(GPU 메모리 전환 비자동, 종료 코드 외에 JSON 기대값을 별도 확인). 산출물·`.atelierx/`는 Git 제외 로컬 자원이다

### 알려진 제한(현재도 유효)
- [제한] SDXL/Illustrious 생성 Node·API는 없다(G02). 생성 단계 일관성 기법은 미정이다
- [제한] Censor 재현율·오탐률, Detailer 부위별 개선, Alpha 경계 품질은 평가되지 않았다. Detailer는 입은 얼굴 검출 fallback을 쓴다. 모든 stage를 합친 최신 graph의 품질도 검증되지 않았다
- [제한] 파일 TTL·용량 정리·디스크 부족, Import/Export·Backup, 강제 종료·전원 장애·장시간 부하, 세분화 권한·원격 TLS는 미완료다. 신체 이상 검사(V04)는 미구현이다
- [제한] VLM 묶음 `passed`는 실행 계약의 성공일 뿐 캐릭터 일관성 품질 보장이 아니다
