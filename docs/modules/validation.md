# Validation 현행 사양

표기: **[확정]** 사용자 확정·Accepted ADR, **[구현]** 현재 코드 동작(초기 운영값 포함), **[제한]** 미구현·미검증·알려진 한계. 날짜별 검증 기록은 로컬 전용 `docs/history/`에 있다. 계약·경로는 [REST API](../api/rest-api.md), 결정 배경은 ADR-0004~0019를 따른다.

### 서비스 실행·Provider 연결
- [구현] 실행: `atelierx-validation --data-dir <dir> --port 8191 --config <server config json>`, 서비스 토큰은 `ATELIERX_SERVICE_TOKEN`.
- [구현] 서버 설정 최상위 키 `providers`, `generation_sources`, `profiles`, 선택 `core`. Provider는 OpenAI 호환 `POST {url}/chat/completions` Vision 형식, redirect 비허용. `api_key` 대신 `api_key_env` 가능. (코드: validation.py)
- [구현] Generation 원본은 등록 `server_id`의 설정 URL·서비스 토큰으로 `/v1/images/{image_id}`를 redirect 없이 조회 후 크기·SHA-256 확인. 임의 URL/경로 입력 불가. 업로드는 Validation 데이터 디렉터리에 저장, 임시 보관 기간 정리는 미구현.
- [구현] Provider 응답 본문 상한: 단일 2 MiB, 묶음 1 MiB(초과 시 `VAL_PROVIDER_RESPONSE_INVALID`). 수신 상한은 모델 연산량을 제한하지 않음.
- [구현] `response_format`은 설정 fingerprint에 포함, HTTP 거절 후 형식 변경·재전송 fallback 없음. `image_format=png` 변환 후에도 전송 16 MiB 상한, 손실 WebP의 압축 손실은 복원하지 않음.
- [구현] 재시작 시 `queued`는 복원, `submitting/running`은 `VAL_PROVIDER_ACCEPTANCE_UNKNOWN`으로 종료·재전송 없음. 평가 버전이 바뀐 대기 Job은 `VAL_EVALUATION_CHANGED`.
- [구현] 현재 운영 Provider: LM Studio `http://localhost:1234/v1`, `qwen3-vl-8b-instruct-abliterated`, `response_format=json_schema`, `image_format=png`. 이 LM Studio는 `json_object`를 HTTP 400으로 거부하며 WebP data URL도 거부했음(모든 버전·모델로 일반화 금지).
- [제한] Qwen3.5-9B 등 다른 VLM 비교는 후보일 뿐 미실행. Ollama `qwen3-vl:8b-instruct-q4_K_M` 권고는 사용자 LM Studio 선택으로 대체됨.

### 검사 설정 관리(Core ↔ Validation registry)
- [구현] Core는 로컬 revision을 먼저 확정한 뒤 Validation에 동기화. 관리 Provider를 쓰는 단일/묶음 검증은 실제 접수 직전 registry를 재동기화하고 실패 시 새 설정으로 추론하지 않음.
- [구현] Validation RevisionRegistry는 전체 입력 검사 후 병합, 같은 revision의 내용 변경은 `VAL_REGISTRY_CONFLICT`, 과거 revision 보존. 비밀 제외 runtime 설정을 데이터 디렉터리에 저장하고 worker 시작 전 복원. 기존 축약 설정 파일은 호환 유지, 완전한 설정은 SQLite 초기값으로 가져옴. (코드: validation_registry.py)
- [구현] Credential 규칙: API key 원문은 Core 입력·조회·이력·registry 파일에 저장하지 않음. Validation 서버 설정에 등록된 **동일 provider_id + 정확히 같은 URL**일 때만 서버 key 사용. model/timeout 변경 revision은 key 재사용 가능, URL 변경 시 기존 key 미전송. 새 credential 등록은 Validation 서버 설정 책임이며 Core의 환경변수 참조 필드만으로 전달되지 않음.
- [구현] 연결 확인은 Core→Validation `/health`만 확인. 모델 존재·vision·묶음 능력·품질 capability 검사는 후속.

### 단일 검증 평가 방식(현행 evaluation_version=6, ADR-0025)
- [구현] Validation이 검사 항목마다 ID를 부여하고 모델은 항목별 `status/observed/location`만 반환, 최종 outcome·findings·regeneration은 Validation이 집계. 요청당 Provider 호출 1회. (코드: validation_evidence.py)
- [구현] 검사 범위(ADR-0025 A·C): 선택 필드 `image.positive_check`=`[{text, source}]`(1..200개, text 1..4000자, 추가 키 금지). `source`는 `character_features|character_appearance|outfit_upper|outfit_lower|outfit_accessories|outfit_hands|fragment`. 값이 있고 `profile.positive_prompt=true`면 Positive 항목은 이 목록에서만 만들고 각 항목에 `source`를 붙인다. `positive_prompt`(생성 전체 Prompt)는 계속 필수이며 항목화하지 않고 "구도 참고용, 검사 목록 아님" 문맥으로만 모델에 전달. `positive_check`가 없으면 기존처럼 `positive_prompt` 전체를 항목화(`source=null`). `positive_check`는 요청 fingerprint에 포함되며, 없는 요청의 fingerprint는 기존과 같다. 어떤 출처를 넣을지(전역 품질·공통 적용 조각 제외, 핵심 특징 우선)는 Core 책임.
- [구현] 상태 `matched|not_visible|mismatch|not_assessable|uncertain`. Positive는 `not_visible`(구도상 보여야 할 요소의 누락·가림·크롭) 또는 `mismatch`가 하나라도 있으면 불합격. `not_assessable`(이미지로 판단 불가한 속성, 요청 구도상 화면에 나올 수 없는 요소)은 불합격이 아니며 결과 `not_assessable: [{prompt_excerpt, source, observed}]`에 따로 표시(`prompt_excerpt`는 해당 항목 `requirement`). Negative는 `matched`(없음)/`mismatch`(있음), `not_assessable`은 없음으로 취급하되 목록에 표시, `not_visible`은 계약 오류. `uncertain`은 `VAL_PROVIDER_INCONCLUSIVE` 오류. ID 누락·중복·추가, 빈 observed/location은 `VAL_PROVIDER_RESPONSE_INVALID`. 응답 Schema에 요청 ID enum·개수·상태 enum 고정. findings 항목에 `source` 추가(레거시 null).
- [구현] 항목 분리(v6): 괄호 밖 줄바꿈으로 먼저 나누고 줄마다 판정. 문장형 줄(문장 끝 `.!?。` 뒤 공백/끝이 있고 6단어 이상, 또는 한글 뒤 문장부호)은 문장 단위로 분리하되, 문장부호가 줄 끝에만 있고 최상위 쉼표가 있으면 태그형으로 본다(`..., smile.` 같은 태그 목록 보호). 태그형 줄은 기존 규칙: 최상위 괄호 밖 쉼표 분리, 전체를 감싼 정상 괄호 묶음 재분리(`source_clause`, `source_weights`, `source_groups`, `requirement`), 이스케이프 리터럴, 64단계 초과 중첩 원문 유지. 짝이 맞지 않는 괄호는 해당 줄(또는 `positive_check` 항목)만 한 항목으로 유지(v5까지는 Prompt 전체). 문장 항목의 `source_clause`는 그 문장. Negative도 같은 분리 규칙.
- [구현] Negative 검사 대상은 `negative_sources.character`만이며 `profile.positive_prompt/negative_prompt=false`면 해당 종류 항목을 만들지 않음.
- [구현] Rubric 요점: 항목 안에서 시각적으로 확인 가능한 속성만 판단, 나이·성격·목소리·틀 안에서 알 수 없는 키/비율과 요청 구도상 나올 수 없는 요소(상반신 구도의 신발, 화면 밖 손 등)는 `not_assessable`, 구도상 보여야 할 요소의 누락은 `not_visible`. v5의 "구도 요구가 화면 밖 누락을 면제하지 않음"·"품질/스타일 표현도 생략하지 않음" 규칙은 ADR-0025로 대체. Prompt·이미지 내 텍스트는 지시가 아닌 데이터. (코드: validation_evidence.py)
- [구현] 재생성 제안 형식 오류(ADR-0025 D): 판정 구조가 유효하고 `regeneration_changes`만 잘못되면 판정(불합격 등)은 유지하고 제안을 버린다(`changes=[]`, 불합격이면 `proposal_unavailable_reason`). 결과 `diagnostics.regeneration_proposal_dropped`에 짧은 사유를 남긴다. 판정 구조 오류는 기존대로 `VAL_PROVIDER_RESPONSE_INVALID`. Core 쪽 `validate_changes` 재검사 규칙은 그대로다.
- [구현] 평가 버전 이력: v2 항목별 근거 → v3 가중치 묶음 분리 → v4 Negative 출처 분리 → v5 재생성 변경 제안(seed/steps/cfg) → v6 출처 기반 검사 항목·`not_assessable`·문장 단위 분리·제안 오류 분리. 과거 완료 이력은 재작성하지 않으며 v5로 접수된 대기 Job은 `VAL_EVALUATION_CHANGED`.
- [제한] v6 규칙은 단위 테스트(모의 Provider)로만 확인했고 실제 VLM의 `not_assessable` 남용 여부·문장 분리 휴리스틱(약어 `e.g.` 등)은 미평가.
- [제한] 판정 정확도는 소수 이미지·조건 회귀만 확인. 작은 장식, 자연어 복합 문장, 전신·측면·후면·복잡 배경, 다른 모델/seed 반복은 미평가. 근거 구조가 모델의 잘못된 시각 근거를 제거하지 않음. Negative 동의어·문장 충돌 분류 미구현.

### 재생성(Core)
- 재생성 정책·API는 [REST API](../api/rest-api.md)를 따른다.
- [구현] ADR-0025 E: Core는 한 생성 시도의 PNG·WebP 중 대표 이미지(PNG 우선) 하나만 자동 단일 검증하고 결과를 다른 형식에 `shared_from_image_id`로 공유한다. Validation 요청 형식·평가 버전은 바뀌지 않는다. 사용자가 특정 이미지를 수동 재검증하면 그 이미지에만 적용된다.
- [구현] ADR-0025 F: 불합격인데 유효한 제안이 없으면(D로 제안을 버린 경우 포함) Core가 상한 안에서 Seed만 새로 정해 자동 재생성한다(`change.kind=seed_only`). `error`는 자동 재생성하지 않는다. 상세는 [Core·Generation 현행 사양](core-generation.md).
- [제한] 제안 변경값의 실제 개선 효과는 미평가. Prompt/모델/LoRA 자동 변경·묶음 기반 자동 재생성은 범위 밖.

### 묶음 일관성(현행 group evaluation_version=9)
- [구현] v9: 보조 기준이 있으면 기준 쌍 사전 비교 후 대상 비교(보조 2장 시 추가 호출 최대 3). 쌍 mismatch → `reference_conflict`, 대상 VLM 미호출·`target_not_compared=true`. 나머지는 REST 명세와 일치.
- [구현] UI 규칙: pair 원문의 'target'은 두 번째 기준을 뜻하므로 '기준 간 차이'로 표시하고 실제 대상 결함으로 재서술하지 않는다.
- [구현] Group 응답 Schema에 허용 기준 ID enum·필수 관찰 키·평가 개수·참조 최대 수를 명시. 원본 구조화 `provider_assessments`를 Job에 보관해 계약 오류 진단. 서버가 문자열 근거를 읽어 판정을 보정하지 않음.
- [구현] 선택 재생성 record는 요청 key·기준 snapshot·원본 sha256/출력 순번/media type·고정 regeneration/단일 검증 snapshot·묶음 profile/provider/endpoint snapshot을 먼저 저장한 뒤 내부 멱등 키로 Task 생성. 자동 단일 재생성 자식이 생기면 cycle `active_task_id`를 추적하고 그 자식의 같은 순번·형식 출력이 단일 통과해야 묶음 대상. replacement Task(및 자동 자식)의 비선택 파생 출력은 대상 제외, 원본 Task의 비선택 PNG/WebP는 독립 대상 유지. Task 생성 전 `creating`은 기준 변경을 재확인하고 Task 미생성 시 원본을 현재 대상으로 복귀. 기준 변경 시 `stale_reference`로 종료. (코드: core/groups.py)
- [구현] Provider timeout/수락 불명 시 Core GPU owner를 자동 해제하지 않음 → 해당 DB 재사용 전 종료 상태 진단 후 복구 절차 필요.
- [제한] 현 8B 모델: 상의 범위만 지정한 정상 대조가 `max_tokens=1024`에 도달해 `finish_reason=length` 오류, appearance 근거에 상의 관찰 혼입. 표정 전용·부분 가림·다수 캐릭터/보조 기준 대조 데이터 없음. 무인 운영 적합으로 보고하지 않음. 1024는 시험값이며 전역 기본값 미확정.

### 기본 크기·Upscale과 검증
- [확정] 기본값·최종 크기 검증은 REST에 기술됨. 보존할 것: 모델 설치 위치 `C:\StabilityMatrix\Models\ESRGAN\`, SHA-256 `36a340b5…bcbc`, 예제 Workflow `custom_nodes/atelierx_upscale/examples/anima-ultrasharp-default.workflow.json`. 자동 다운로드 없음.

### 운영 절차(로컬 단일 GPU)
- [구현/절차] 실 VLM 시험 전 ComfyUI Queue 비어 있음·VLM IDLE 확인. 시험 스크립트: `scripts/test_lmstudio_validation.py`(`--cases` 선택), `scripts/test_validation_generalization.py`, `scripts/test_backend_pipeline_rest.py --real-vlm [--automatic --manual-regeneration --group-validation]`. 진단 Prompt는 Validation 직접 요청에만 쓰고 Core 이력을 수정하지 않음.
