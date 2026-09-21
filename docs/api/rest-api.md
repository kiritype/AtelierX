# AtelierX REST API 명세 — 현재 구현

## 그룹 없는 독립 생성 — 2026-09-21

개인용 Discord 봇을 위한 Core 경로다. 기존 그룹 기반 Task/제작 계획은 변경하지 않는다. `--standalone-config`로 서버 설정을 등록해야 새 접수를 허용하며 미설정은 `CORE_STANDALONE_DISABLED`(503)다. 모든 경로에 기존 Core Bearer 인증이 필요하다.

| Method | 경로 | 계약 |
| --- | --- | --- |
| POST | `/v1/standalone-jobs` | `Idempotency-Key`와 `{prompt,mode?,negative_prompt?,checkpoint?}`. mode 생략은 `direct`, 문자열은 앞뒤 공백 제거·소문자 정규화 후 `natural` 또는 `direct`. 새 요청 202, 같은 키/내용 200, 충돌 409 |
| GET | `/v1/standalone-checkpoints` | Core 설정의 허용 체크포인트 `{items:[{name,value}],default}`. 기존 Core Bearer 인증 필요 |
| GET | `/v1/standalone-jobs/by-key` | `Idempotency-Key`로 기존 접수 조회, 없으면 404 |
| GET | `/v1/standalone-jobs/{id}` | `{id,state,images,error,validation,created_at,seed,checkpoint}`. checkpoint는 저장된 작업의 실제 모델 |
| GET | `/v1/standalone-jobs/{id}/images/{image_id}/content` | 해당 독립 작업에 속한 PNG/WebP bytes. 크기·SHA-256 검증 |

prompt는 공백만 아닌 최대 20,000자 문자열이다(Discord 입력은 별도로 4,000자). direct는 원문을 Positive로 보존한다. natural은 로컬 Chat Completions의 텍스트 결과를 Positive로 사용한다. negative_prompt는 선택 문자열(최대 20,000자, Discord는 4,000자)이며 Core가 서버 기본 Negative에 쉼표와 공백으로 추가해 저장한다. 생략·빈 값·공백만인 값은 서버 기본값을 유지하고, 내용이 있는 입력은 재작성하지 않는다. 모델·Seed·후처리는 서버 설정을 snapshot하며 클라이언트가 arbitrary URL/Workflow/SQL을 전달할 수 없다. 기본 예제는 1024→1536이다. 독립 생성 설정의 선택 필드 `seed_mode`는 `fixed`(생략 시 기존 설정값 유지) 또는 `random`이다. random은 신규 접수 시 Core가 0~2^53−1 범위의 정수를 한 번 선택해 작업 snapshot에 고정한다. 같은 멱등 키·재시작·전달 재시도는 기존 값을 유지한다. 응답 seed는 저장된 작업의 실제 생성 입력에 근거하며 현재 전역 설정으로 과거 값을 추정하지 않는다. 과거 작업 중 seed 공개 필드가 저장되지 않은 경우 해당 필드는 생략될 수 있다. 자동 Validation/재생성은 요청하지 않고 `validation={state:not_requested,outcome:null}`로 표시한다.

선택 `checkpoint`는 Core 서버 설정 `allowed_checkpoints`의 정확한 모델 이름이다. 이 설정을 생략하면 기본 diffusion_model만 허용한다. 신규 요청은 목록을 검사한 뒤 generation_inputs.diffusion_model에 고정하며, 기존 멱등 키의 재조회는 현재 목록이 바뀌어도 원래 작업을 반환한다. 텍스트 인코더·VAE·기타 생성 설정은 서버 기본값을 유지한다. 최종 등록 자원·Anima 호환성 검사는 Generation이 담당한다. 과거 작업의 checkpoint 응답도 저장된 생성 입력 또는 저장된 설정에서 읽으며 현재 설정으로 추정하지 않는다.

상태: `queued → planning(natural만) → planner_completed → ready_to_dispatch → dispatching → generation_pending|running → completed|failed`. direct는 Planner 단계를 생략한다. `/v1/queue`와 SSE에는 `kind=standalone`으로 포함된다. 별도 worker가 실행하여 Planner 호출이 기존 Core 조정 루프를 막지 않는다. GPU acquire/release의 phase에 `planner`가 추가됐으며 기존 validation과 같은 설정 모델을 사용한다.

Generation POST 전 intent를 저장하며, 재시작·통신 단절 후에는 기존 키만 조회한다. `CORE_GENERATION_ACCEPTANCE_UNKNOWN`은 자동 재접수하지 않는다. Planner 실행 중 재시작은 `CORE_PLANNER_ACCEPTANCE_UNKNOWN`이며 추론을 자동 재시도하지 않는다. 본문까지 완료된 응답과 추론 결과 저장 여부를 구분해 GPU를 해제하고, 응답 불명은 권한을 보존한다. 설정 endpoint 변경은 `CORE_GENERATION_ENDPOINT_CHANGED`, 저장된 Planner 모델과 현재 GPU 모델 불일치는 `CORE_PLANNER_MODEL_CHANGED`다. 독립 생성 취소 API와 F/E 그룹 갤러리 편입은 이번 경로에 없다.

Discord 전용 Bridge는 `POST /v1/discord/jobs`, `POST /v1/discord/status`를 제공하며 Core와 다른 Bearer 토큰과 Discord 사용자 허용 목록을 사용한다. 자세한 전달·대기·권한 계약은 [개인용 Discord 봇](../development/discord-personal-bot.md)을 따른다.

전역 조각과 대량 제작 계획은 [별도 API 명세](prompt-fragments-production-plans.md)를 참조한다.

기준일 2026-09-13. Core·Generation·Validation의 **실제로 등록된 API**를 기술한다. 초기 구현 범위와 아직 없는 확장 기능을 구분한다. 초기 구현 계약이며 API 안정 버전 선언은 아니다. ADR-0005 및 `docs/contracts/validation`의 Proposed Schema와 이 런타임 명세는 구분한다.

## Frontend 탐색용 Core 조회 API

| Endpoint | 선택 필터 | 응답 |
| --- | --- | --- |
| `GET /v1/groups` | `work_id`, `character_id`, `outfit_id` | `items,limit,offset,total` |
| `GET /v1/images` | `work_id`, `character_id`, `outfit_id`, `group_id`, `task_id`, `media_type`, `single_outcome`, `group_status` | `items,limit,offset,total` |
| `GET /v1/tasks` | `group_id`, `work_id`, `character_id`, `outfit_id`, `state` | 기존 `items,limit,offset` 유지 |
| `GET /v1/group-batches` | `group_id`, `state` | `items,limit,offset` |

모두 기존 Core Bearer 인증을 사용한다. 조회는 작업 생성·검증·재생성·이미지 파일 읽기·GPU 실행을 유발하지 않는다. 관계 필터는 고정 group의 작품/캐릭터/의상 ID를 따른다. 여러 필터는 AND 조건이며 보관된 분류의 과거 기록도 조회 가능하다. 기존 그룹별 Batch 목록과 개별 상세 API는 유지한다.

공통 페이지는 `limit=50`(1..200), `offset=0`(0..9223372036854775807)이며 시간 내림차순·동일 시각 ID 오름차순이다. 그룹은 group created_at, Task/Batch는 각 created_at을 사용한다. 갤러리의 created_at은 현재 저장 구조상 Task 접수 시각이며 이미지 생성 완료 시각으로 해석하지 않는다. offset 페이지는 고정 스냅샷이 아니므로 동시 추가 시 결과가 이동할 수 있다.

알 수 없는 query key, 중복 key, 빈 값, 잘못된 페이지 값은 `400 CORE_INVALID_INPUT`이다. 그룹/갤러리 관계 필터는 canonical UUID를 요구한다. 존재하지 않는 유효 ID 또는 서로 맞지 않는 관계 조합은 빈 목록 200이다. 기존 Task의 텍스트 group_id 필터 호환성을 유지하며 Task/Batch의 알 수 없는 state 문자열도 빈 목록 200이다.

그룹 item은 `id,outfit_id,character_id,work_id,outfit_revision,components,created_at` 및 존재하는 `reference`를 반환한다. 현재 의상 편집 내용을 과거 group에 합성하거나 목록 조회로 새 group을 만들지 않는다.

갤러리 item은 `id,task_id,group_id,work_id,character_id,outfit_id,created_at,generation_image_id,sha256,bytes,media_type,single_outcome,single_validation_run_id,group_status,group_validation_run_id,group_reference_revision,content_url`이다. `content_url`은 `/v1/images/{id}/content`의 인증된 상대 API 경로다. 목록 자체는 이미지 bytes, 파일 경로, 전체 Prompt/snapshot, Provider secret을 반환하지 않는다. `media_type` 필터는 image/png 또는 image/webp다.

`single_outcome`은 최신 단일 검증 요청 기준 `unvalidated/pending/passed/failed/error/cancelled`이며, 과거 합격 뒤 새 queued 요청이 있으면 pending이다. `group_status`는 `reference/matched/mismatch/insufficient/reference_conflict/error/unvalidated/stale/not_eligible`로 별도 표시한다. reference는 선택된 기준 역할이지 합격 판정이 아니다. stale은 현재 기준으로 유효한 완료 판정이 없는 과거 기준 결과이고, not_eligible은 현재 묶음 비교 대상에서 제외된 상태다. 현재 기준 결과·대상 집합은 기존 Core group consistency의 판정을 재사용한다. 단일/묶음 상태를 하나의 ambiguous state나 종합 합격으로 합치지 않는다. `single_validation_run_id`와 `group_validation_run_id`는 해당 요약의 근거 실행 ID이며 없으면 null이다. `group_reference_revision`은 현재 기준 revision이므로 stale 결과의 과거 revision으로 해석하지 않는다. 전체 이력은 기존 이미지 검증/그룹 상세 API에서 조회한다.

## 기본 이미지 크기·Upscale

2026-09-13 사용자 확정: Core generation_inputs에서 width/height를 생략하면 각각 1024를 적용한다. 명시한 값은 보존한다. postprocess와 후처리 Preset을 모두 생략하면 `{upscale:{upscale_model:"4x-UltraSharp.safetensors",scale:1.5},encode:{webp_enabled:true,webp_quality:90}}`를 고정한다. 명시적 postprocess 객체(빈 객체 포함) 또는 Preset은 기본값으로 덮어쓰지 않는다. 과거 Task snapshot도 변경하지 않는다.

Generation은 `postprocess.upscale={upscale_model,scale}`을 받는다. 모델은 설치된 AtelierXUpscale의 등록 목록에 있어야 하며 자동 다운로드·모델 fallback은 하지 않는다. 모델 미등록은 `GEN_UPSCALE_MODEL_UNAVAILABLE`, 노드 미등록은 `GEN_NODE_UNAVAILABLE`이다. 실행 순서는 생성→Upscale→Detailer→Censor→Alpha→Encode이며 독립 후처리에도 같은 stage를 사용할 수 있다. Core 후처리 Preset과 수동 재생성 override도 upscale을 지원한다.

scale은 모델 고유 배율과 별개인 원본 대비 최종 배율이다. 1024×1024와 scale 1.5는 1536×1536이며 4x UltraSharp 모델 처리 후 최종 크기를 맞춘다. 정수 크기는 half-up 반올림을 사용한다. Validation.expected_output은 원래 생성 크기가 아니라 이 최종 크기를 사용한다.

## 묶음 검증 근거 v9

새 묶음 Job의 evaluation_version은 9이며 단일 검증은 5를 유지한다. evidence는 `feature`, `status`, `reference_observed`, `target_observed`, `differences`, `reference_refs`를 반환한다. differences는 `{attribute,description}` 배열이고 attribute는 hair_length/hair_style/hair_color/eye_color/facial_features/clothing/accessories/body_features 중 하나다. 표정·자세·구도·조명 변화는 관찰 내용에만 기록하며 일관성 불합격 근거 속성으로 받지 않는다.

v8의 reference_observed는 기존 문자열에서 `{reference_id:관찰문}` 객체로 변경됐다. 관찰 키는 제공된 기준 ID만 허용하며 reference_refs는 중복을 허용하지 않는다. reference_refs가 비어 있지 않으면 관찰 키와 일치해야 한다. insufficient는 빈 reference_refs와 보이는 기준의 관찰을 허용한다. matched는 모든 제공 기준 ID의 관찰 근거를 포함하고 differences가 비어 있어야 하며, mismatch는 구체적인 차이가 있어야 한다. 요청 identity에 있는 범주만 평가하고, 기준 간 충돌은 대상 판정보다 먼저 확인한다. 모순된 구조 또는 허용하지 않은 속성은 응답 오류로 처리하고 임의로 합격/불합격으로 보정하지 않는다. 이전 evaluation_version으로 대기 중인 묶음 Job은 `VAL_EVALUATION_CHANGED`로 종료하며 새 기준으로 자동 재실행하지 않는다. 과거 완료 결과는 이력으로 보존한다.

## 기준 이미지 사전 비교 — 묶음 v9

대표·보조 기준이 여러 장이면 모든 기준 쌍을 먼저 비교한다(최대 3장, 3쌍). `phase=reference_precheck`와 `reference_checks`에 쌍 ID·상태·원본 근거·오류를 저장하고, 응답 진단은 `reference_responses`, 원본 구조화 답변은 `reference_assessments`에 분리한다. 외부 요청 전에 실행 상태를 저장하며 재시작 시 불명확한 호출을 자동 재전송하지 않는다. 보조 기준이 없으면 기존 대상 비교 경로를 유지한다.

기준 쌍의 관찰된 mismatch는 해당 feature의 `reference_conflict`로 집계한다. 이는 비교 역할이 두 기준이라는 사실에 따른 집계이며 자연어 근거를 읽어 판정을 바꾸는 처리가 아니다. 충돌이 있으면 대상 파일 접근·무결성은 확인하되 대상 VLM 비교를 건너뛰고 `target_not_compared=true`, `reference_evidence`를 기록한다. evidence는 기존 필드를 유지한다. 충돌하지 않은 나머지 요청 feature는 대상 미비교 사유의 `insufficient`로 표시하고 합격으로 만들지 않는다.

사전 비교의 insufficient만으로 기준 충돌을 추정하지 않으며 정상 대상 비교를 진행한다. 사전 비교 오류는 대상별 `error`와 `reference_precheck_errors`로 보존하고 전체 합격을 막는다. Provider timeout/통신 단절은 후속 기준·대상 호출을 중단하고 GPU 권한을 유지한다. 취소·기준 변경 확인·자동 재생성 정책은 바꾸지 않는다. Core도 기존 evidence 정규화로 이 결과를 수용한다.

## Provider 응답 토큰 상한

Provider 설정은 선택 필드 `max_tokens`(양의 정수, boolean/0/음수 불가)를 지원한다. Core가 설정 revision과 단일/묶음 실행 snapshot에 값을 고정하고 Validation이 `/chat/completions`에 같은 값을 전달한다. 생략한 과거 설정·snapshot에는 상한을 소급 추가하지 않는다. 상한 변경은 새 설정 revision으로 처리한다.

완료 응답의 `finish_reason=length`는 JSON이 파싱되더라도 `VAL_PROVIDER_RESPONSE_INVALID`다. 단일 검증에서는 오류 결과, 묶음에서는 해당 대상의 실행 오류로 기록하며 합격이나 재생성 제안으로 바꾸지 않는다. 응답 생성 상한은 실제 연산 시간 제한을 보장하지 않으므로 timeout을 함께 유지한다. 단일 Job의 `provider_response`, 묶음 Job의 대상 ref별 `provider_responses`에는 finish_reason과 수치형 토큰 사용량을 보존하며 자동 재전송·Provider fallback은 하지 않는다.

1024는 이번 로컬 대조 시험의 시작값이며 사용자 확정 전역 기본값이나 모든 모델에 대한 권장 상한을 뜻하지 않는다.

## 사용자 검사 설정 관리

Core의 `/v1/validation-settings/{kind}`에서 kind는 `single-profiles`, `group-profiles`, `providers`다.

| Method | 경로 suffix | 요청/응답 |
| --- | --- | --- |
| GET | collection | `{items:[...]}`, `include_archived=true`로 보관 항목 포함 |
| POST | collection | 설정 객체로 신규 등록 |
| GET | `/{id}` | 현재 revision |
| PATCH | `/{id}` | `{revision,setting:{...}}`, 현재 revision 확인 후 증가 |
| GET | `/{id}/revisions` | 저장된 과거 revision |
| POST | `/{id}/clone` | `{id:"새 ID"}`, revision 1로 복제 |
| POST | `/{id}/archive` | `{revision}`, 신규 선택에서 제외하고 이력 보존 |

저장 응답에는 `synchronization:{state:"synced"|"pending",error}`를 추가한다. pending도 Core 저장 자체는 성공한 201/200이며 Validation 동기화만 대기한다. 같은 create를 반복하는 대신 저장 ID로 조회하고, 실행 전 동기화 재시도를 거친다. 단일/묶음 profile ID는 공통으로 유일해야 한다. `GET /v1/validation-settings/providers/{id}/connection`의 `validation_service_reachable`은 Validation 서비스 연결 여부만 뜻하며 Provider 모델 가용성은 확인하지 않는다.

단일 profile은 `profile_id`, `revision`, `output_conditions`, `positive_prompt`, `negative_prompt`, `body_parts`, `metadata`, `consistency`를 받는다. 아직 구현하지 않은 검사는 활성화할 수 없다. 묶음 profile은 `{profile_id,revision,consistency:true}`다. Provider는 `provider_id`, `revision`, `model`, `timeout_seconds`, 등록된 `url`과 지원 형식 설정을 보관한다. 비밀 API key 원문은 Core 설정 입력·조회·이력에 포함하지 않는다. 접수한 Task와 검증 작업은 선택 당시 revision을 유지한다.

Validation의 `POST /v1/registry/snapshot`은 인증된 서비스 간 설정 동기화용이다. 일반 이미지 검증 요청에는 Provider URL이나 비밀키를 포함하지 않는다. 현재 운영 상태·동기화 및 연결 확인의 구체적인 제한은 [설정 구현 기록](../development/validation-settings.md)에 기록한다.

## 그룹 일괄 생성

| Method | Core 경로 | 요청/응답 |
| --- | --- | --- |
| POST | `/v1/groups/{id}/batches` | `{items:[...],group_validation:{profile_id,provider_id}}`, Idempotency-Key 필수. 신규 202, 같은 요청 200 |
| GET | `/v1/groups/{id}/batches` | 해당 그룹 batch 목록 |
| GET | `/v1/group-batches/{id}` | 고정 항목·Task 추적·상태·요약·group_run_id |
| POST | `/v1/group-batches/{id}/cancel` | 최신 자동 재생성 cycle 및 관련 검증 협력 취소 |
| POST | `/v1/group-batches/{id}/confirm-reference` | `{reference_revision}`, Idempotency-Key 필수. 대기 중 batch의 기준 확인 후 재개 |

items는 1..32개의 Task 입력이며 group_id는 상위 경로에서 상속하고 각 항목에 단일 validation 선택을 요구한다. 접수 시 프롬프트·생성/후처리 설정·검사 revision·자동 재생성 설정을 고정한다. 항목별 최종 자동 재생성 시도를 따라가며 단일 통과 이미지로만 묶음 검사를 요청한다. 생성 실패·단일 불합격·취소는 항목별 summary에 남는다. 묶음 비교 자체의 판정은 group_run_id로 조회한다.

기준이 없으면 후보만 반환하며 자동 저장하지 않는다. `awaiting_reference_confirmation`은 기존 기준 API로 기준을 지정한 후 confirm-reference를 호출해야 재개된다. 기준 없는 통과 이미지 0/1장은 `insufficient_images`로 종료한다. 기존 기준이 있으면 신규 대상 1장도 비교할 수 있다. 기준 변경 후 확인은 새로운 내부 검증 key를 사용하며 기존 결과 이력을 보존한다. 현재 묶음 Validation의 호출당 대상 상한은 32장이고, 여러 출력 형식으로 대상이 이를 넘는 요청의 자동 분할은 지원하지 않는다. 상세 구현·검증 범위는 [일괄 생성 기록](../development/group-batches.md)을 참조한다.

## 공통

기본 로컬 포트: Core **8190**, Generation **8189**, Validation **8191**, ComfyUI **8188**, LM Studio **1234**. 서버 실행 시 port를 변경할 수 있다. 서비스 간 주소는 서버 설정으로 지정한다.

- 모든 경로(health 포함): `Authorization: Bearer <service-token>` 필수. `ATELIERX_SERVICE_TOKEN` 환경변수 사용.
- JSON 요청: `Content-Type: application/json`. `/v1/uploads`만 raw 이미지 bytes.
- Job/Task 생성 및 검증 접수: `Idempotency-Key` 필수, 1~200자. 새 접수 202, 동일 키·내용 200 기존 결과, 다른 내용 409. 일반 category 생성에는 멱등 키 기능 없음.
- Entity 생성은 201, 일반 조회·수정은 200. 접수 후 실패는 조회 HTTP 200의 결과 객체에서 확인한다.
- API 오류 기본 형태: `{"error":{"code":"...","message":"..."}}`. Job 오류는 해당 객체의 `error`에 보관하며 Validation에는 `stage`가 추가된다.
- 요청의 정의되지 않은 필드는 원칙적으로 거절한다. 필수 nullable 필드는 생략과 null을 구분한다.
- 이미지 ID와 서버 등록 ID를 사용한다. 임의 파일 경로·클라이언트 지정 Provider URL/키는 요청으로 받지 않는다.

## Core

### 경로 목록

`{kind}`는 `works`, `characters`, `outfits`만 허용한다.

| Method | 경로 | 입력 / 응답 |
|---|---|---|
| GET | `/health` | 서비스 상태 |
| GET | `/v1/{kind}` | 선택 query `parent_id`, `limit`(기본 50, 1~200), `offset`(기본 0). `{items,limit,offset}` |
| POST | `/v1/{kind}` | 아래 Entity 입력 → 201 Entity |
| GET | `/v1/{kind}/{id}` | Entity |
| PATCH | `/v1/{kind}/{id}` | `revision` 및 변경 필드 → 갱신 Entity |
| GET | `/v1/{kind}/{id}/revisions` | `limit,offset` → `{items,limit,offset}` 변경 이력 |
| GET | `/v1/settings` | 전역 설정 |
| PATCH | `/v1/settings` | `revision` 및 변경 설정 → 전역 설정 |
| POST | `/v1/groups` | `{"outfit_id":"..."}` → 201 고정 구성 그룹 |
| GET | `/v1/groups/{id}` | 그룹 ID·의상/캐릭터/작품 ID·의상 revision·고정 components |
| POST | `/v1/prompts/preview` | Task 입력 → `{snapshot,preview_hash}` |
| POST | `/v1/tasks` | Task 입력 + 멱등 키 → Task |
| GET | `/v1/tasks` | 선택 `group_id,limit,offset` → `{items,limit,offset}` |
| GET | `/v1/tasks/by-key` | 멱등 키 header → Task |
| GET | `/v1/tasks/{id}` | Task |
| GET | `/v1/images/{id}` | 이미지 Metadata·검증 상태 |
| GET | `/v1/images/{id}/content` | 인증된 PNG/WebP bytes |
| POST | `/v1/images/{id}/validations` | `{"provider_id":"local-vision","profile_id":"single-default"}` + 멱등 키 → 검증 Run |
| GET | `/v1/images/{id}/validations` | 해당 이미지 검증 이력 `{items}` |
| GET | `/v1/validation-runs/{id}` | Core가 저장한 검증 Run |

### Entity와 전역 설정

작품 생성: `{"name":"작품 A"}`. 캐릭터 생성: `{"name":"캐릭터 A","parent_id":"작품 ID","negative_prompt":"beard, glasses"}`. 캐릭터 Negative는 선택이며 기본 빈 문자열이다. 기존 저장 캐릭터에서 이 필드가 없을 때도 빈 값으로 해석한다.

의상 생성:

```json
{"name":"제복","parent_id":"캐릭터 ID","components":{"appearance":"silver hair, blue eyes, hairpin","upper":"white shirt, blue jacket, brooch","lower":"black trousers, boots"}}
```

Entity 응답: `id,kind,parent_id,name,revision,archived`, 의상은 `components`, 신규 캐릭터는 `negative_prompt`. PATCH는 현재 `revision`과 `name`/`archived`, 의상 `components`, 캐릭터 `negative_prompt`를 지원한다. `parent_id` 이동은 지원하지 않는다. components는 3개 전체 키를 전달한다. 이름은 비어 있지 않은 문자열, 문자열 최대 20,000자, revision은 1 이상 정수다. revision 불일치는 409. archive는 연쇄 삭제가 아니다.

전역 설정 필드: `revision`, `positive_quality`, `negative`, `auto_regeneration_enabled`, `max_auto_regenerations`. PATCH는 revision 필수, 나머지 변경 필드 선택이다. 자동 상한은 0 이상 정수, 기본 5. 새 최초/수동 시도의 자동 실행 묶음에 적용되며 아래 재생성 절을 참조한다.

### Task 입력·snapshot

필수: `group_id`, `framing`, `generation_inputs`. 선택: `expression`, `action`, `situation`, `include`, `postprocess`, `preview_hash`, `validation`.

```json
{
  "group_id":"그룹 ID",
  "framing":"upper_body",
  "expression":"calm smile",
  "situation":"studio portrait",
  "include":{"appearance":true,"upper":true},
  "generation_inputs":{
    "diffusion_model":"waiANIMA_v10Base10.safetensors",
    "text_encoder":"waiANIMA_v10Base10_txt.safetensors",
    "vae":"qwen_image_vae.safetensors",
    "width":768,"height":1024,"seed":2026091303,
    "steps":24,"cfg":4.5,"sampler":"euler_ancestral","scheduler":"normal",
    "loras":[]
  },
  "postprocess":{"encode":{"webp_enabled":true,"webp_quality":90}}
}
```

framing은 `upper_body|full_body|custom`. 기존 두 값의 include는 `appearance,upper,lower` 선택 bool이며 기본 포함이나 upper_body에서 lower는 제외된다. upper_body에 lower=true는 `CORE_PROMPT_CONFLICT`. 최종 문구는 Core가 만들므로 generation_inputs에 positive/negative를 직접 넣지 않는다.

`custom`은 필수 `framing_prompt`(공백만 아닌 문자열, 최대 20,000자)와 `include`의 세 bool을 모두 받는다. `framing_prompt`에는 `upper body, white background\nsimple background`, `cowboy shot` 등 자유 조합을 입력한다. 개행·쉼표·가중치 문법은 원문을 보존하며 자동 번역·후보 전개를 하지 않는다. 정확한 `upper body` clause와 lower=true는 기존과 같이 충돌로 거절한다. 임의 구도 문구에서 신체 영역을 추측하지 않으므로 include를 명시해야 한다. 기존 framing 값과 framing_prompt를 함께 보내면 입력 오류다.

`expression`, `action`, `situation` 역시 여러 줄 문자열(각 최대 20,000자)을 허용한다. 각 필드의 여러 줄은 하나의 이미지 Prompt를 구성한다. 줄마다 Task를 만들지 않는다. custom snapshot은 `composition_version:3`과 `prompt_inputs`에 구도·표정·동작·상황 원문을 보존한다. preview_hash는 원문·포함 영역 변경 시 달라진다. 이 계약은 단일 preview/Task와 기존 Batch의 각 item에 동일하게 적용된다.

generation_inputs: 모델/encoder/VAE/sampler/scheduler 이름 문자열, width/height 256~1920의 16배수, seed 0~2^64−1 정수, steps 1~100 정수, cfg 0~20 유한수. loras는 선택 배열 `[{"name":"등록 파일명","strength":0.35}]`, strength −100~100 유한수. 실제 등록/지원 범위는 Generation이 추가 검사한다. JavaScript의 정수 정밀도 한계에 유의하며 현재 문자열 seed는 지원하지 않는다.

snapshot에는 `composition_version=2`, `group`, `settings`, `inclusion`, `generation_endpoint`, `generation_inputs`, `character_revision`, `negative_sources` 및 선택 `postprocess`가 저장된다. preview_hash를 보내면 제출 시 최신 preview와 비교해 변경을 감지한다.

Task 주요 응답: `id,group_id,state,created_at,snapshot,generation_job_id,images,error,validation,automatic_attempts_used`. 생성 상태는 `queued → dispatching → generation_pending|generating → generated|failed`. 기본은 생성만 수행한다. 선택 `validation: {"provider_id":"local-vision","profile_id":"single-default"}`를 보내면 Core가 선택의 Profile·Provider·endpoint를 snapshot에 고정하고, 생성된 각 출력 이미지의 단일 검증을 자동 접수한다. Client가 종료되어도 Core가 진행한다. 수동 검증 POST도 유지한다.

검증 Run 주요 응답: `id,image_id,state,request,endpoint,job_id,outcome,result,error,created_at`. `endpoint`는 내부 Validation 주소이며 외부 Provider URL/키가 아니다. 검증 결과는 이미지 Metadata에 연결되며 Task 생성 상태를 덮지 않는다. 같은 이미지에 새 키를 사용하면 명시적 재검증이다.

## Generation

| Method | 경로 | 입력 / 응답 |
|---|---|---|
| GET | `/health` | 서비스 상태 |
| GET | `/v1/nodes` | 등록 Node·입력 schema·후처리 지원 현황 |
| POST | `/v1/nodes/anima/jobs` | `{inputs,postprocess?}` + 멱등 키 → Job |
| GET | `/v1/jobs/by-key` | 멱등 키 header → Job |
| GET | `/v1/jobs/{job_id}` | Job |
| GET | `/v1/images/{image_id}` | PNG/WebP bytes |

`inputs`는 Core generation_inputs의 필드에 **실제 `positive_prompt`, `negative_prompt`를 추가**한다. Generation은 출처를 분류하거나 AI에 검증을 요청하지 않고 전달된 합성 문구를 실행한다.

`postprocess` 지원 키: `upscale,detailer,censor,alpha,encode`. 명시한 객체에서 생략한 단계는 실행하지 않는다. 순서는 Upscale → Detailer → Censor → Alpha → Encode로 고정한다. Core 요청 자체의 postprocess 생략 기본값은 문서 앞의 기본 이미지 크기 절을 따른다. 기타 stage 계약은 [후처리 상세 계약](../development/generation-postprocess.md)을 참조한다. 기존 이미지 독립 후처리는 아래 절의 image-ID API를 사용하며 임의 graph API는 없다.

Job 주요 응답: `job_id,prompt_id,state,inputs,requested_postprocess,postprocess,images,error,created_at,updated_at` 등. `requested_postprocess`는 원요청, `postprocess`는 정규화 설정이다. 내부 node_inputs·멱등 키·fingerprint는 공개하지 않는다.

Generation의 by-key 조회는 진행 중인 접수의 노드 확인·저장 잠금을 기다린다. 접수 handler 내부의 저장 지연을 키 없음으로 오인하지 않으며, 조회 시간 초과는 Core가 기존 키로 다시 확인한다. Validation 연결의 bare HTTP 502/503/504도 접수 결과 재조회 대상으로 취급하되, 구조화된 `VAL_*` 오류 응답은 명시 오류로 보존한다. 완료된 Validation `outcome=error`의 자동 추론 재시도는 허용하지 않는다.

상태: `queued → submitting → submitted|running → completed|failed`. 오류·수락 불명은 임의로 다시 생성하지 않는다. 이미지 목록은 `image_id,sha256,bytes,media_type,url` 등의 메타데이터를 포함한다. 정확한 이미지 descriptor는 실행 결과와 [Generation 소스](../../src/atelierx/generation.py)의 capture/public을 기준으로 한다.

## Validation

| Method | 경로 | 입력 / 응답 |
|---|---|---|
| GET | `/health` | 서비스 상태 |
| POST | `/v1/uploads` | raw PNG/WebP → 201 `upload_id,sha256,bytes,media_type` |
| POST | `/v1/validations/single` | 아래 입력 + 멱등 키 → Job, `Location` header |
| GET | `/v1/validation-jobs/by-key` | 멱등 키 header → Job |
| GET | `/v1/validation-jobs/{job_id}` | Job |

단일 입력(예제 ID는 실제 등록·응답 값으로 교체):

```json
{
  "image":{
    "ref":"Core 이미지 ID",
    "source":{"type":"generation","server_id":"generation-local","image_id":"Generation 이미지 ID","sha256":"64자리 소문자 SHA-256"},
    "positive_prompt":"silver hair, blue eyes, upper body",
    "negative_prompt":"low quality, beard",
    "negative_sources":{"global":"low quality","character":"beard"}
  },
  "generation_attempt_id":"Core Task ID",
  "profile":{"profile_id":"single-default","revision":1,"output_conditions":true,"positive_prompt":true,"negative_prompt":true,"body_parts":[],"metadata":false,"consistency":false},
  "provider":{"provider_id":"local-vision","revision":5,"model":"qwen3-vl-8b-instruct-abliterated","timeout_seconds":180},
  "expected_output":{"width":768,"height":1024,"media_type":"image/png","alpha":"not_required"},
  "generation_settings":null
}
```

- 최상위 `image,generation_attempt_id,profile,provider,expected_output` 필수. generation_attempt_id는 null 허용. generation_settings는 생략/null/object 허용하며 현재 상세 활용은 없음.
- image ref·source·실제 positive/negative 필수. positive는 공백만인 문자열 불가, negative는 빈 문자열 허용.
- 업로드 source는 `{"type":"upload","upload_id":"응답 ID","sha256":"해시"}`로 교체한다. source 필드는 두 종류를 혼합할 수 없다.
- Profile 전체 객체는 등록값과 일치해야 한다. body_parts는 중복 없는 `hands`, `face`, `limbs` 목록이며 기본값은 빈 목록이다. metadata/consistency=true는 단일 adapter에서 `VAL_PROFILE_UNSUPPORTED`로 거절한다.
- 신체 검사는 Prompt 필수 요소 검사와 별개다. 선택한 부위의 명확한 가시적 구조 이상만 `body_structure_anomaly` 불합격으로 기록한다. 가려지거나 화면 밖인 부위는 evidence의 `kind=body`, `status=not_visible`로 남기며 신체 불합격이나 해당 부위 통과로 세지 않는다. 같은 부위가 Positive에 필수 요소로 명시됐다면 별도의 Prompt 검사는 기존 규칙대로 누락 불합격이다.
- 평가 가능한 신체 부위도 다른 수행 검사도 없으면 `VAL_NO_ASSESSABLE_CHECKS`(outcome=error, stage=evaluation)로 종료한다. 출력 조건 또는 다른 요구 검사가 통과한 혼합 요청은 해당 범위에서 통과할 수 있으나 `not_visible` 신체 근거를 보존한다. 불확실한 가시적 근거는 기존 `VAL_PROVIDER_INCONCLUSIVE` 오류다. 오류의 자동 검증 재시도·자동 재생성은 하지 않는다.
- provider의 ID/revision/model/timeout은 서버 등록값과 일치해야 한다. timeout은 1 이상 정수다. 요청에 url/api_key를 넣을 수 없다.
- output_conditions=true이면 expected_output 객체가 필요하다. alpha는 `not_required|channel_required|transparency_required`. 출력 조건은 **원본** PNG/WebP로 검사한다.
- Core는 이미지의 원래 Task snapshot에 `postprocess.alpha`가 있으면 `transparency_required`, 없으면 `not_required`를 전달한다. 현재 Preset/설정 변경으로 과거 이미지의 요구를 바꾸지 않는다. 출력 조건을 끈 Profile은 이 검사를 수행하지 않는다. 실제 투명 픽셀 존재 여부를 검사하며 캐릭터 마스크·경계 품질을 보장하지 않는다. 기존 검증 Run은 그대로 보존하고 명시적 새 검증부터 적용한다.
- 입력은 정지 PNG/WebP, 최대 16 MiB·40MP. animation/multi-frame은 거절한다.

### Negative 출처 계약 — ADR-0023

`image.negative_prompt`는 실제 생성에 사용한 전체 Negative다. `negative_sources`는 정확히 `{global:string,character:string}`다. 공백뿐인 항목을 제외한 전역 → 캐릭터 원문을 `, `로 합친 값이 전체 문구와 일치해야 한다. 다르면 400 `VAL_INVALID_INPUT`이다.

**검사 대상은 character만이다.** global은 실제 생성 기록으로 보존하되 AI 검사에 전달하지 않는다. `profile.negative_prompt=false`이면 character도 검사하지 않는다. 출처 생략은 전체 문구가 global인 것으로 해석하며 금지 요소로 추측하지 않는다. 기존 Core snapshot에도 같은 호환 규칙을 적용한다. 과거 완료 판정은 보존한다.

캐릭터의 `beard`는 이미지에 수염이 있으면 불합격이다. 전역의 `beard`는 검증 불합격 사유가 아니다. 다만 두 경우 모두 생성에는 사용된다. Core는 대표 추상 품질 문구를 `CORE_CHARACTER_NEGATIVE_INVALID`로 안내하고, 정확히 같은 Positive 항목은 `CORE_PROMPT_CONFLICT`로 안내한다. 동의어·문장 전체의 충돌 분석은 아직 제공하지 않는다.

### Job과 판정

주요 응답: `job_id,request_id,kind,state,created_at,request,evaluation_version,outcome,result,error`, 호출했다면 `provider_image`. 현재 kind=single, evaluation_version=5. 기본 상태는 `queued → submitting → running → completed|failed`다.

| 상황 | state | outcome | 후속 |
|---|---|---|---|
| 검사 합격 | completed | passed | result에 근거 |
| 명시 요소 누락·불일치 또는 출력 조건 불합격 | completed | failed | result.findings와 regeneration.required=true |
| Provider·파싱·불확실성·입력 접근 오류 | failed | error | error.code/message/stage, 자동 재전송·재생성 없음 |

`result`는 `findings`, `evidence`, `regeneration`을 제공한다. evidence에는 항목 id/kind/requirement·원문/가중치·관찰 status/observed/location이 들어간다. regeneration은 `required,reason,changes`; 지원 변경안과 자동 실행 정책은 아래 재생성 절을 참조한다. 비활성화/검사 대상 없음은 존재하지 않는 항목의 합격 근거를 생성하지 않는다. 과거 평가 버전의 대기 Job은 새로운 판정 계약으로 조용히 실행하지 않는다.

### 서버 설정

[설정 예제](../../config/validation.example.json): providers/profiles/generation_sources 및 선택 core 연결 설정. Provider는 url, api_key 또는 환경변수 설정, model, revision, timeout_seconds, 선택 response_format(`json_object|text|json_schema`), image_format(`original|png`)을 사용한다.

LM Studio는 현재 `json_schema`와 `image_format=png`를 사용한다. WebP는 Provider 전송 직전에 PNG로 재인코딩하며 원본 검사는 WebP를 기준으로 한다. 전송 이미지도 16 MiB 상한을 적용한다. provider_image는 원본/전송 형식·해시·전송 bytes를 기록한다. 이 동작은 HTTP 실패 후 재시도 fallback이 아니다.

## 주요 오류

| HTTP/결과 | 대표 코드 | 의미 |
|---|---|---|
| 400 | CORE_INVALID_INPUT / CORE_CHARACTER_NEGATIVE_INVALID / CORE_PROMPT_CONFLICT / VAL_INVALID_INPUT | 입력·문구·출처 오류 |
| 401 | 인증 오류 | 토큰 누락·불일치 |
| 404 | CORE_NOT_FOUND / GEN_JOB_NOT_FOUND / VAL_JOB_NOT_FOUND | 리소스 없음 |
| 409 | CORE_IDEMPOTENCY_CONFLICT / VAL_IDEMPOTENCY_CONFLICT / CORE_PREVIEW_STALE | 키 충돌·변경된 미리보기; Entity revision도 409 |
| 422 | VAL_PROFILE_UNSUPPORTED / VAL_PROVIDER_UNCONFIGURED / VAL_PROFILE_MISMATCH | 지원하지 않거나 등록과 다른 검증 선택 |
| Job outcome=error | VAL_IMAGE_INTEGRITY / VAL_IMAGE_INVALID / VAL_IMAGE_TOO_LARGE | 원본 접근·무결성·입력 한도 |
| Job outcome=error | VAL_PROVIDER_REJECTED / VAL_PROVIDER_TIMEOUT / VAL_PROVIDER_UNAVAILABLE | Provider 거절·시간 초과·통신 실패 |
| Job outcome=error | VAL_PROVIDER_RESPONSE_INVALID / VAL_PROVIDER_INCONCLUSIVE | 잘못된/빠진 근거·판정 불확실 |
| Job outcome=error | VAL_PROVIDER_CONFIG_CHANGED / VAL_EVALUATION_CHANGED / VAL_PROVIDER_ACCEPTANCE_UNKNOWN | 고정 설정/평가 변경·재시작 수락 불명 |
| Generation failed | GEN_EXECUTION_UNKNOWN / GEN_COMFY_UNAVAILABLE / GEN_PROTOCOL_ERROR 등 | 실행 추적·ComfyUI 연결 오류 |

이 표는 대표 코드이며 모든 내부 오류의 폐쇄 enum이 아니다. 실제 HTTP 접수 오류와 비동기 Job 결과를 혼동하지 않는다. Provider의 HTTP 400도 이미 접수한 Job 조회에서는 HTTP 200 + outcome=error로 반환된다.

## 재현·변경 관리

[Backend 시험](../../tests/), [실제 전체 흐름 스크립트](../../scripts/test_backend_pipeline_rest.py), [구현 체크리스트](../development/backend-implementation-checklist.md)를 참조한다. 이 문서와 실제 route·필드·판정이 달라지면 같은 변경에서 갱신한다. 묶음 API는 아래 구현 범위와 제한을 따르며 문서만으로 전체 기능을 완료 처리하지 않는다.


## Core 후속 검증·GPU 조정·취소·Queue — 2026-09-13 추가

자동 검증 선택 예: 기존 Task JSON에 `"validation":{"provider_id":"local-vision","profile_id":"single-default"}` 추가. 생략/null이면 생성만 한다. 설정 미등록은 생성 접수 전에 거절한다. snapshot.validation에는 `selection,profile,provider,endpoint`가 고정된다. 자동 접수 키는 이미지별 `auto:<task-id>:<image-id>`이며 재시작·중복 tick에서도 같은 Run을 유지한다. PNG와 선택 WebP 각각 검증한다. 실패·취소된 생성에는 후속 검증을 만들지 않는다. Task 생성 상태와 이미지별 검증 결과는 분리되며 자동 접수 오류는 `automatic_validation_error`에 기록한다.

| 서비스 | Method / 경로 | 계약 |
|---|---|---|
| Core | POST `/v1/tasks/{id}/cancel` | queued는 cancelled. 실행 중은 cancel_requested=true를 저장하고 Generation에 취소 전달. 생성 완료 Task는 생성 결과를 유지하며 대기/실행 검증과 미접수 후속 흐름만 취소 |
| Core | POST `/v1/validation-runs/{id}/cancel` | 대기 Run 즉시 취소, 접수된 Job에는 취소 전달 |
| Generation | POST `/v1/jobs/{job_id}/cancel` | queued 즉시 cancelled, 제출/실행 중 cancel_requested=true 후 실제 종료를 기다려 결과 배제 |
| Validation | POST `/v1/validation-jobs/{job_id}/cancel` | queued 즉시 cancelled, Provider 실행 중은 결과를 기다린 후 판정에 반영하지 않음 |
| 세 서비스 | GET `/v1/queue` | 선택 limit(기본50,1~200),offset(기본0),state. `{items,limit,offset,total}`; 완료 기록도 포함하며 state로 필터 |
| 세 서비스 | GET `/v1/events` | 인증된 SSE. 최초/재연결 reset, 이후 changed, 15초 heartbeat |
| Core 내부 서비스용 | GET `/v1/gpu` | `{owner,waiting,blocked}` 권한·FIFO 대기 상태 |
| Core 내부 서비스용 | POST `/v1/gpu/acquire` | `{phase:"generation"|"validation",job_id:"..."}` → `{granted,reason?}` |
| Core 내부 서비스용 | POST `/v1/gpu/release` | 같은 identity로 권한/대기 요청 반납 → `{released:true}` |

취소 API의 요청 body는 필요 없다. 종료된 상태는 200, 취소 요청만 반영되고 실행 종료 대기 중이면 202다. 취소 완료는 `state=cancelled`; Validation outcome/result는 null이다. `cancel_requested=true`가 실행 중 취소 표시이며 ComfyUI 전체 interrupt로 사용자 작업을 끊지 않는다. Provider가 실제로 끝나기 전 GPU 권한을 반납하지 않는다. 완료가 먼저 저장된 Job은 뒤늦은 취소로 바뀌지 않는다.

Queue/SSE는 작은 상태 필드 `id|job_id,kind?,state,created_at,updated_at?,outcome?,cancel_requested?`만 전달한다. Core Queue는 generation Task와 validation Run을 함께 보여준다. SSE payload는 `{items,removed}`이고 changed는 바뀐 항목만 포함한다. id는 상태 digest다. 현재 과거 이벤트 재생은 없으며 Last-Event-ID를 보내도 reset으로 최신 상태를 재동기화한다. 현재 실행 ComfyUI 내부 Node별 진행률은 별도 미구현이다.

### 공유 GPU 실행 설정

- Core: `--gpu-config .atelierx/gpu-config.json` ([예제](../../config/gpu.example.json)). Core가 SQLite에 권한/대기 순서를 저장한다.
- Generation: `--coordinator-url http://127.0.0.1:8190`.
- Validation: 서버 config의 `coordinator_url`과 해당 로컬 Provider의 `shared_gpu:true` ([통합 예제](../../config/validation-coordinated.example.json)). 외부/독립 Provider는 shared_gpu를 사용하지 않는다.
- 초기 서비스 내부 API는 동일 service token을 사용한다. 다른 data-dir의 동일 GPU 서비스도 같은 Core coordinator에 참여해야 한다. coordinator를 사용하지 않는 독립 서비스/직접 ComfyUI 호출의 경쟁을 원자적으로 막는 기능은 아니다.

Core는 ComfyUI busy 여부를 확인하고, 생성 전 지정 LM Studio 모델이 idle인지 CLI 조회 후 native REST로 unload한다. 다른 모델이 로드됐거나 실행 중이면 대기한다. ComfyUI `/free` 후 GPU 메모리를 확인한다. 새 모델용 기본 여유는 18,000 MiB, 이미 선택 VLM이 로드된 경우 128 MiB의 초기값을 사용한다. 이는 이번 RTX4090·선택 모델에서 확인한 값이며 모델마다 설정 조정이 필요하다. 권한 부여가 임의 모델의 추론 성공을 보장하지 않는다.

권한은 시간만으로 만료시키지 않는다. Provider timeout/수락 불명 등 실제 종료를 확인할 수 없으면 권한을 보수적으로 유지한다. 해당 runtime 작업 종료 확인 및 운영자 복구가 필요하며 자동 강제 해제는 없다. Core 재시작 시 저장된 owner를 유지하고 같은 Job이 재요청하면 기존 권한을 반환한다. 내부 release API는 서비스의 실제 종료 확인 후 호출하는 신뢰 경계이며 사용자별 세부 권한 분리는 후속이다.

Generation이 권한 취득 후 ComfyUI의 다른 작업을 발견하고 아직 자신의 `/prompt`를 제출하지 않았다면 권한을 반납하고 대기한다. 제출 응답의 `prompt_id`가 저장된 ID와 다르면 `GEN_EXECUTION_UNKNOWN`으로 종료하며 권한을 보존한다. coordinator 응답의 `granted`/`released`는 JSON boolean `true`만 성공으로 인정한다. 손상된 JSON이나 다른 자료형의 응답은 허가·반납 확인으로 사용하지 않는다.

[구현·실행 기록](../development/core-orchestration-validation.md)을 참고한다.


## 재생성 및 시도 이력 (2026-09-13 구현)

Core가 생성→검증→재생성 정책을 실행한다. CLI/F/E는 아래 REST API를 호출하고 상태를 표시한다.

| Method | 경로 | 응답 |
| --- | --- | --- |
| POST | `/v1/tasks/{id}/regenerations` | 수동 재생성 Task. 신규 202, 동일 멱등 요청 200 |
| GET | `/v1/tasks/{id}/attempts?limit=50&offset=0` | 같은 lineage의 `items`, `total`, `limit`, `offset` |
| GET | `/v1/regeneration-cycles/{id}` | 실행 묶음 상태 및 횟수 |
| POST | `/v1/regeneration-cycles/{id}/stop` | 중단을 저장한 cycle, 200. 실행 중 작업 취소는 협력적으로 완료 |

수동 요청에는 `Idempotency-Key`가 필요하다. body는 `{}` 또는 `generation_inputs`, `postprocess`, `validation`이다. generation_inputs는 기존 설정의 부분 덮어쓰기이며 literal positive/negative prompt 변경은 허용하지 않는다. postprocess는 전체 교체한다. validation 생략은 기존 선택을 현재 등록 설정으로 다시 고정하고, null은 검증을 제외한다. seed 생략 시 새 seed를 부여한다. 원본 Task, 프롬프트 및 카테고리는 변경하지 않는다.

진행 중 생성/검증 또는 활성 자동 후속 시도가 있으면 `CORE_REGENERATION_ACTIVE`(409)다. 실행을 중단하고 종료를 확인한 뒤 요청한다. 키 재사용 내용 충돌은 `CORE_IDEMPOTENCY_CONFLICT`(409), 잘못된 override는 400이다.

Task의 `regeneration`에는 `kind`(initial/manual/automatic), `parent_task_id`, `lineage_id`, `cycle_id`가 있다. 자동 시도에는 `source_run_ids`도 저장한다. 모든 새 시도는 새 Task 및 이미지 ID를 사용한다. cycle은 `id`, `lineage_id`, `active_task_id`, `enabled`, `limit`, `used`, `state`, `reason`을 반환한다. 설정 기본값은 자동 활성화, 최대 5회다. 최초/수동 생성은 사용 횟수에서 제외하고 수동 요청마다 현재 설정으로 새 cycle을 만든다. 기존 cycle의 상한은 고정된다.

자동 사용 횟수는 Generation의 실제 실행 확인 시 한 번만 증가하며 DB 재시작 후에도 유지한다. Generation Job의 `execution_started: true`가 실행 시작을 나타낸다. 실행 시작 후 오류/취소도 포함하고, 실행 전 취소는 제외한다.

cycle 상태: `active`, `passed`, `generation_only`, `automatic_disabled`, `limit_reached`, `proposal_unavailable`, `error`, `cancelled`, `stopped`, `manual_restart`. 완료 상태에서는 후속 자동 Task를 만들지 않는다. outcome=error는 자동 재검증/재생성을 실행하지 않는다.

Validation 평가 버전은 5다. Core는 실제 `generation_settings.seed/steps/cfg`를 전달하며 provider는 `regeneration_changes`에 `{field,value,reason,evidence_ids}`를 제안한다. 실패 evidence ID에 연결된 seed/steps/cfg의 유효한 변경만 허용한다. 제안 없음은 기존 불합격 결과를 보존하고 cycle을 `proposal_unavailable`로 끝낸다. 잘못된 제안은 `VAL_REGENERATION_PROPOSAL_INVALID`; 여러 출력의 제안 충돌은 `CORE_REGENERATION_CONFLICT`다. 자동 프롬프트/모델/LoRA 변경 및 묶음 검증 기반 재생성은 이번 구현 범위에 포함하지 않는다.


## 묶음 일관성 검증 — 2026-09-13 초기 구현

| 서비스 | Method | 경로 | 의미 |
| --- | --- | --- | --- |
| Core | GET | `/v1/groups/{id}/reference-candidate` | 단일 통과 evidence 기반의 결정적 기준 후보. 저장·기준 교체·검증 실행 없음 |
| Core | PUT | `/v1/groups/{id}/reference` | `{revision,representative_id,auxiliary_ids}`. 최초 revision=0, 현재 버전 일치 필수 |
| Core | GET | `/v1/groups/{id}/consistency` | 현재 기준의 대상별 최신 결과, 판정 수, 미검증/제외 목록 |
| Core | POST | `/v1/groups/{id}/validations` | `{reference_revision,target_ids,validation:{profile_id,provider_id}}`, Idempotency-Key 필수. 신규 202/기존 200 |
| Core | GET | `/v1/groups/{id}/validations` | 그룹 Run 이력 |
| Core | POST | `/v1/groups/{id}/replacements` | 선택 이미지 수동 재생성 후 단일 검증·현재 기준 묶음 검증 연결. Idempotency-Key 필수 |
| Core | GET | `/v1/groups/{id}/replacements` | 선택 재생성 이력과 현재 단계 |
| Core | GET | `/v1/group-validation-runs/{id}` | frozen request, 결과, current_reference |
| Core | POST | `/v1/group-validation-runs/{id}/cancel` | 협력적 취소 요청 |
| Validation | POST | `/v1/validations/group` | 묶음 Job 접수. 기존 Job 조회/키 조회/취소/Queue/SSE 공용 |

`reference-candidate`는 `matched` 단일 evidence 중 비어 있지 않은 관찰·위치와 그룹의 appearance/upper/lower 용어가 겹치는 범위를 사용한다. 더 많은 visible component, 더 많은 matched evidence, 저장된 생성 시각, image ID 순서로 정렬한다. 대표가 못 보이는 component만 최대 두 보조로 채우며 부족하면 `insufficient_reference_evidence`와 component 목록을 반환한다. 기준이 이미 있으면 `existing_reference_retained`만 반환하며 자동 교체하지 않는다. 현재 기준의 `reference_conflict`도 명시한다.

Core는 같은 그룹의 최신 단일 검증 통과 이미지만 허용한다. 대표/보조와 판정 대상은 별도 ID 목록이다. reference를 바꾸면 revision이 증가하며 자동 검증·재생성은 실행하지 않는다. 실행 중 요청은 원래 기준으로 완료하고 `current_reference=false`로 보존한다. 선택한 대상만 재검증할 수 있다. 기준 충돌은 `CORE_GROUP_STALE`, 활성 대상 중복은 `CORE_GROUP_ACTIVE`, 비적격 이미지는 `CORE_GROUP_IMAGE_INELIGIBLE`(각 409)다.

Validation body: `group_id`, `reference_revision`, `representative`, `auxiliaries`, `targets`, `identity`, `profile`, `provider`. 각 이미지는 단일 입력과 같은 ref/source/positive_prompt/negative_prompt/negative_sources 구조다. identity는 비어 있지 않은 appearance/upper/lower의 고정 의상 문구다. 전용 profile은 `{profile_id,revision,consistency:true}`이며 서버 등록과 일치해야 한다. Provider 계약은 단일과 같다. 초기 제한은 대표 1장, 보조 최대 2장, 대상 1..32장이다. 한 provider 요청에 대표·보조·대상 1장을 전송하고 대상별로 순차 실행한다. 자동 축소·특징 생략은 하지 않는다.

대상별 `status`: matched/mismatch/insufficient/reference_conflict/error. 현재 evidence 필드는 문서 앞의 묶음 검증 근거 v9을 따르며 실제 참조 ID에 연결한다. 불확실성/가림은 insufficient, 참조 모순은 reference_conflict이며 다수결로 해결하지 않는다. 그룹 Job outcome은 passed/failed/incomplete/error다. 일부 대상의 파싱·접근 오류는 `result.items`에 보존하고 나머지 비교를 진행한다. timeout/통신 단절처럼 provider 실행 종료가 불명확하면 후속 호출을 중단하고 partial_results를 보존하며 GPU 권한을 유지한다. 취소·재시작은 자동 provider 재전송을 하지 않는다.

선택 재생성 body는 다음과 같다.

```json
{
  "reference_revision": 3,
  "target_image_id":"이미지 ID",
  "regeneration":{"generation_inputs":{"seed":2026091314},"validation":{"provider_id":"local-vision","profile_id":"single-default"}},
  "group_validation":{"provider_id":"local-vision","profile_id":"group-default"}
}
```

Core는 접수 시 reference revision·선택 이미지의 group/단일 통과 상태·현재 대상 여부와 PNG/WebP 파생 출력 순번을 고정한다. 새 Task가 동일 순번·동일 media type의 출력을 만들고 단일 검증을 통과했을 때만 고정된 기준으로 그 새 image 하나를 group validation에 보낸다. 원본 이미지와 과거 시도는 이력으로 남고 현재 집계에서 제외된다. 기준 변경, 생성/단일 검증 실패, 취소, 파생 출력 불일치는 명시 상태/오류로 끝나며 자동 재생성·자동 기준 교체·자동 재검증을 하지 않는다. 같은 key의 재시도와 프로세스 재시작은 저장된 internal key를 재사용하므로 추가 generation/group 요청을 만들지 않는다.


## 저장 이미지 독립 후처리

Generation `POST /v1/images/{image_id}/postprocess-jobs`는 `Idempotency-Key`와 `{postprocess:{...}}`를 받는다. 신규 202/동일 입력 기존 Job 200이며 일반 Job 조회·취소·Queue·SSE를 사용한다. 지원 stage/설정은 기존 Anima 후처리와 같다. 하나 이상 stage를 지정한다.

입력은 Generation에 저장된 image ID만 허용한다. Job에는 `kind=postprocess`, `source_image_id`, `source_sha256`, `source_media_type`과 원래 generation inputs를 보관한다. 원본 파일·기존 결과를 수정하지 않고 새 Job/이미지를 만든다. 실행 직전 SHA-256을 검사하고 `LoadImage`→선택 stage의 고정 graph를 실행한다. 업로드 파일명은 Job별로 고정하며 arbitrary graph·URL·파일경로는 받지 않는다.

원본 Anima context 없음은 `GEN_POSTPROCESS_CONTEXT_MISSING`(409), 미등록 image ID는 `GEN_IMAGE_NOT_FOUND`(404), 파일 누락은 `GEN_OUTPUT_MISSING`, 실행 전 원본 변경은 Job 오류 `GEN_IMAGE_INTEGRITY`다. Detailer 모델은 실제 등록 자원으로 다시 검사한다. 실행 오류의 자동 재제출은 하지 않는다. 현재 원본 context를 가진 Generation 저장 이미지에 한정하며 외부 이미지 직접 업로드·Core 이미지 목록으로의 독립 후처리 결과 자동 편입은 후속 범위다.


## 생성·후처리 Preset

Core `kind`는 `generation` 또는 `postprocess`다.

| Method | 경로 | 요청/응답 |
| --- | --- | --- |
| POST | `/v1/presets/{kind}` | `{name,settings}`, 201 |
| GET | `/v1/presets/{kind}?limit=50&offset=0&archived=false` | 페이지 목록. archived 생략은 전체 |
| GET | `/v1/presets/{kind}/{id}` | 현재 revision 설정 |
| PATCH | `/v1/presets/{kind}/{id}` | `{revision,name?,settings?,archived?}`, 조건부 수정 |
| GET | `/v1/presets/{kind}/{id}/revisions` | 과거 revision, limit/offset 지원 |

settings는 generation_inputs 또는 postprocess 객체다. 실제 모델/노드 존재 여부는 실행 시 Generation이 최종 검사한다. Core는 설정의 형식·범위·허용 필드만 검사하며 프롬프트·secret·임의 graph·절대경로를 저장하지 않는다. 상대 모델 하위폴더 이름은 원문 보존한다.

Task/preview는 `presets:{generation:{id,revision},postprocess:{id,revision}}`를 받는다. 선택한 kind의 직접 generation_inputs/postprocess를 함께 보내면 400이다. generation preset을 쓰지 않으면 generation_inputs가 필요하다. 선택 시 active 현재 revision과 비교하고 불일치는 `CORE_REVISION_CONFLICT`, 보관된 preset은 `CORE_PRESET_ARCHIVED`(409). 적용 설정은 Task snapshot으로 복사하며 `preset_sources`에 id/kind/name/revision을 기록한다. 같은 키와 같은 원래 요청은 preset 수정/보관 후에도 기존 Task를 반환한다. 새 요청은 최신 revision을 명시해야 한다. 이후 preset 변경은 이전 Task에 소급하지 않는다.


선택 재생성의 보완: 접수 당시 실제 생성 snapshot과 단일/묶음 profile·provider·endpoint를 record에 고정한다. 일반 단일 검증의 자동 재생성 cycle이 후속 Task를 만들면 그 최종 시도를 추적하며, cycle이 끝난 뒤 선택한 순번·형식의 단일 통과 출력만 묶음 검사에 연결한다. 이는 묶음 불일치에 의한 자동 재생성을 허용하는 것이 아니다. 대체 작업의 비선택 PNG/WebP 출력 및 과거 자동 시도는 현재 그룹 대상에서 제외하고 원래 Task의 비선택 형제 이미지는 유지한다. 실제 Task를 만들지 못한 접수 실패는 기존 대상을 유지한다.
