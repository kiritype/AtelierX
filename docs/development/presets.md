# Core Preset 저장·적용 초기 구현

상태: 구현 준비. 작성일: 2026-09-13.

ADR-0002 N-16/N-17은 생성 및 후처리 설정의 Preset Save/Load를 요구한다.
Core가 SQLite를 소유하고 Generation이 직접 DB를 열지 않는 경계를 유지하기 위해,
`src/atelierx/core_presets.py`의 `CorePresets`가 기존 Core SQLite 연결에
`presets`, `preset_revisions` 테이블을 만든다. `core.py`는 Core 생성 직후 이 모듈을
초기화하고 `attach(app)`하므로 아래 경로는 기존 Core Bearer middleware 아래에서 동작한다.

```text
GET, POST  /v1/presets/{generation|postprocess}
GET, PATCH /v1/presets/{kind}/{id}
GET        /v1/presets/{kind}/{id}/revisions
```

생성 요청은 `{name, settings}`이고 수정에는 현재 `revision`과 하나 이상의
`name`, `settings`, `archived`를 보낸다. 수정은 전체 settings 교체이며, stale revision은
`CORE_REVISION_CONFLICT`(409)이다. archive는 삭제가 아니므로 조회·revision 이력은
보존하고 `snapshot()` 적용만 `CORE_PRESET_ARCHIVED`로 거절한다.

## 설정 경계와 검사

생성 Preset은 Core의 기존 `generation_settings` 검사를 재사용한다. 따라서 모델,
Text Encoder, VAE, 크기, Seed, Steps, CFG, Sampler, Scheduler, LoRA만 저장하며
Positive/Negative Prompt, endpoint, 파일 경로, API key, 권한 또는 정의되지 않은 필드는
저장할 수 없다.

후처리 Preset은 고정 stage `detailer`, `censor`, `alpha`, `encode`와 Generation의
allow-list field만 받는다. 모델 설정은 상대적인 ComfyUI 등록 모델명만 허용한다. 하위
폴더의 `/`·`\` 구분자는 등록 이름으로 보존하지만 절대 경로·drive 경로·상위 경로는 거절한다. Alpha/Censor는 모델명을 필수로 하며 Censor는
labels도 필수다. 수치·boolean 범위도 Core에서 검사한다. 실제 등록 여부와 모델 조합은
Generation이 실행 시 설치된 Node/model 정보로 최종 검사한다. 이는 생성 환경의 변경을
Core가 추측하거나 다운로드하지 않게 하는 초기 구현 경계다.

세부 기본값과 선택적 detailer field, 단일/복수 인물·경계 처리 정책은 새 제품 정책으로
확정하지 않았다. 저장된 설정은 사용자가 제공한 값만 보관하며 Generation의 현재 기본값
선택을 덮어쓰지 않는다.

## Task snapshot 연결

Task/preview 입력은 선택적으로
`presets:{generation:{id,revision},postprocess:{id,revision}}`를 받는다. Core는 선택한
현재 revision과 다르면 409으로 거절하고, active preset의 deep-copy settings를 기존
`Core.preview()`에 넣는다. 결과 Task snapshot에는 `preset_sources`에 id·kind·name·revision이
고정된다. 해당 kind의 직접 `generation_inputs`/`postprocess`와 preset을 동시에 보내면
우선순위를 추측하지 않고 400으로 거절한다. generation preset이 없으면 기존처럼
`generation_inputs`가 필수다.

Task의 fingerprint는 preset을 해석하기 전 원래 요청(JSON의 id·revision 포함)으로 계산한다.
따라서 같은 멱등 key·같은 요청은 나중에 preset이 수정·보관되어도 기존 Task를 반환한다.
새 Task에는 최신 preset revision을 명시해 새 요청 key와 함께 제출해야 한다. 이후 Preset
수정·보관은 기존 Task, 이미지, 재생성 이력에 소급되지 않는다.

## 검증

다음 독립 파일 기반 검사가 통과했다.

```powershell
.\.venv\Scripts\python.exe -X utf8 -m unittest tests.test_core_presets -v
```

revision 충돌, 과거 snapshot/revision 불변성, 보관 후 적용 거절·이력 보존, Prompt/secret/
경로/미지원 field와 잘못된 postprocess 값 거절, SQLite 재시작 후 데이터·이력 복원을
확인한다. REST 인증·preset 선택 preview/Task snapshot·preset 변경 후 동일 멱등 key의 기존
Task 반환·stale revision 거절도 검사한다. ComfyUI, GPU, Generation, LM Studio 호출은 수행하지 않는다.
