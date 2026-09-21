# Frontend 요구사항 분석 (Backend 계약 기준)

작성일: 2026-09-13
범위: 현재 REST 구현과 확정 ADR을 Frontend 작업 단위로 대응한다. 이 문서는 화면 구현이나 새로운 제품 정책을 승인하지 않는다. 현재 Web Frontend는 구현되어 있지 않으며, 이후에도 [공용 API Client](../requirements/module-feature-comparison.md#7-shared-api-client--sdk-%EB%B0%8F-shared-schemas--types)를 통해 REST만 호출하는 얇은 클라이언트여야 한다.

## 판독 기준

- **구현 REST**는 현재 [REST API](../api/rest-api.md)에 명시되고 Core/Generation/Validation이 제공하는 요청이다. API가 있다는 사실은 해당 화면이 이미 구현되었다는 뜻이 아니다.
- **확정 정책**은 Accepted ADR 또는 사용자가 확정한 요구다. 화면은 이를 표시하고 입력할 수 있어야 하지만, 이를 브라우저에서 재구현해서는 안 된다.
- **제안**은 이번 분석의 우선순위 및 화면 배치 권고다. 미정 기능을 확정된 것처럼 표시하지 않는다.

## 화면과 작업 흐름

| 화면 / 사용자 흐름 | 요구사항·정책 | 현재 REST 지원 | Frontend 처리와 실제 공백 |
| --- | --- | --- | --- |
| 작업 탐색과 Prompt 편집 | C-01~C-03, F-01, ADR-0021 | `GET/POST/PATCH /v1/{works,characters,outfits}`의 parent/page 조회, 각 revision 이력, `POST /v1/groups` | 탐색은 **작품 > 캐릭터 > 의상**이다. `appearance`는 독립 category가 아니라 의상 `components.appearance`이며 `upper`, `lower`와 함께 한 의상 편집 화면에서 전부 전송한다. 보관과 revision 409을 표시한다. work/character/outfit의 page 조회는 있으나 전체 group 목록 API는 없으므로, tree에서 group browser를 완료했다고 볼 수 없다. 트리 정렬·필터·다중 선택 UX도 아직 정해지지 않았다. |
| 전역·캐릭터 Prompt | C-04~C-08, F-02~F-03, ADR-0022/0023 | `GET/PATCH /v1/settings`, 캐릭터 `negative_prompt`, `POST /v1/prompts/preview` | 전역 Positive/Negative와 캐릭터 Negative를 구분해 편집·설명한다. 전역 Negative는 생성 전용이고 캐릭터 Negative만 검증 대상이다. `framing`, `expression`, `action`, `situation`, `include`는 Task 입력으로 보낸다. 최종 Positive/Negative 조합·상충 판정은 preview/Core의 책임이다. 표정·상황·동작을 재사용 가능한 카탈로그로 저장하는 API는 없다. |
| 생성 설정과 Preset | C-15, G-04, N-16~N-17, F-04 | `GET/POST/PATCH /v1/presets/{generation,postprocess}`, revision/history; Task preview/submit의 `presets` | 생성·후처리 Preset의 생성, 복제/수정, 보관, revision 선택을 제공할 수 있다. preset kind와 직접 `generation_inputs`/`postprocess`의 동시 지정은 400이므로 UI는 한 방식만 고르게 한다. Task snapshot과 `preset_sources`를 결과 상세에 보여 과거 실행이 이후 편집으로 변하지 않음을 드러낸다. 계열 전환 시 미저장 변경·자동 load UX는 아직 계약화되지 않았다. |
| Validation profile/provider 설정 | C-16, V-07~V-10, F-05 | `GET/POST/PATCH /v1/validation-settings/{single-profiles,group-profiles,providers}`, revision/history/clone/archive, provider connection | profile/provider의 revision과 보관 상태, 설정 동기화 `synced`/`pending`을 표시한다. secret은 어떤 목록·이력·오류 화면에도 표시하거나 재구성하지 않는다. 연결 확인은 등록 provider의 모델 존재까지 보장하지 않는 서비스 도달성 확인이다. 지원하지 않는 profile 검사 항목을 UI가 사용 가능하다고 보이면 안 된다. |
| 생성 전 확인과 접수 | F-04, G-01~G-04, ADR-0003/0022 | `POST /v1/prompts/preview`, `POST /v1/tasks`, `GET /v1/tasks/by-key` | 그룹·구도·포함 요소·생성/후처리·선택 검증을 입력하고 preview hash가 붙은 snapshot을 확인한 뒤 접수한다. `upper_body`에서 lower 포함은 명시 오류로 보여 준다. 멱등 키는 제출 중복을 막기 위해 client가 요청 단위로 보존한다. Prompt 조합·Workflow·Validation orchestration을 browser에서 수행하는 공백 보완은 금지다. |
| Task, Job, 출력 미리보기 | F-04~F-08, C-17, G-09 | Core `GET /v1/tasks`(선택 group/page), `/v1/tasks/{id}`, `/v1/images/{id}`, `/v1/images/{id}/content`; Generation Job/image 조회; 세 서비스 `/v1/queue`, `/v1/events` | Task에서 연결된 image metadata와 인증된 content로 결과 preview/lightbox를 만들 수 있다. 그러나 전체 image gallery 목록/검색 API는 없으므로 F-07 gallery의 전역 browse·filter는 아직 지원되지 않는다. Queue는 페이지 조회와 SSE changed/reset으로 갱신하며 reset 시 재조회한다. 현재 Node별 진행률과 진행 중 이미지 preview는 **미구현/보류**이고 최종 출력만 preview한다. EXIF/파일 내 Metadata 표시의 상세 계약은 남아 있다. |
| 단일 검증, 오류, 수동 재생성 | F-05~F-06, V-01~V-05, ADR-0004/0006/0017 | `POST/GET /v1/images/{id}/validations`, `GET /v1/validation-runs/{id}`, `POST /v1/tasks/{id}/regenerations`, attempts/cycle/cancel | `passed`/`failed`와 provider·파싱 등의 `error`를 구분하고 evidence, error code, 고정 snapshot을 표시한다. 오류 후 자동 재시도는 하지 않으며 사용자가 재검증 또는 수동 재생성을 선택한다. 자동 재생성은 Core가 조정하므로 UI는 상태와 상한만 표시한다. |
| 그룹 Batch 생성 | G-09, ADR-0007/0009, F-04~F-06 | `POST/GET /v1/groups/{id}/batches`, `GET /v1/group-batches/{id}`, cancel/confirm-reference | Batch item별 Task/검증 결과와 Batch 상태를 보여 준다. 생성·단일 검증·후속 흐름은 Core가 연결하며 UI가 개별 service에 직접 순서를 지시하지 않는다. batch 입력 편집, 대량 목록 UX의 세부는 아직 화면 정책이다. |
| 기준 후보 확인과 그룹 재검증 | ADR-0007/0008/0018/0020, V-05 | `GET /v1/groups/{id}/reference-candidate`, `PUT /v1/groups/{id}/reference`, consistency, group validations/runs | 기준 후보와 부족 component, 현재 기준 revision을 먼저 보여 주고 사용자가 대표·보조를 확정한다. 기준 변경은 자동 검증하지 않으며 재검증은 별도 확인 동작이다. 구조화된 참조별 관찰과 typed identity differences를 그대로 표시한다. pose/expression/framing은 허용 변화이므로 불일치 근거로 요약하지 않는다. 그룹 판정 정확도는 현재 실환경 재검증·후속 계약 보완 중이므로 UI가 `matched`를 인간 검토 불필요라는 보증으로 표시하면 안 된다. |
| 선택 수동 재생성 | ADR-0007/0018, G-05~G-10 | `POST/GET /v1/groups/{id}/replacements` | 사용자가 mismatch 대상을 선택하고 reference revision을 확인한 뒤 재생성을 요청한다. 새 결과의 단일 검증과 그룹 검증은 Core가 연결하며 원본·과거 시도는 이력으로 유지한다. UI가 기준 자동 교체·자동 재검증·자동 대상 삭제를 추가하면 안 된다. |

## 생성·후처리와 실행 제어의 화면 입력 계약

다음은 이미 확정됐고 현재 REST 입력으로 전달할 수 있는 제어다. 값은 preview/Task snapshot 또는 preset revision에 고정되므로, 화면은 실행 후 현재 설정으로 과거 결과를 다시 해석하면 안 된다.

| 제어 | 현재 입력·기본값 | 화면에서 지킬 경계 |
| --- | --- | --- |
| 해상도와 Upscale | `generation_inputs.width,height` 생략 시 각각 **1024**. postprocess까지 생략하면 `upscale:{upscale_model:"4x-UltraSharp.safetensors",scale:1.5}`와 `encode:{webp_enabled:true,webp_quality:90}`. 따라서 기본 최종 출력은 **1536×1536**이다. | 4x는 모델 고유 배율이고 `scale`은 원본 대비 최종 배율이다. 사용자가 해상도·모델·scale을 명시하면 그대로 보존한다. 빈 `postprocess:{}` 또는 postprocess preset도 기본값으로 덮어쓰지 않으므로, UI는 “기본 후처리 사용”과 “stage 없음”을 구별한다. 등록되지 않은 upscale 모델은 `GEN_UPSCALE_MODEL_UNAVAILABLE`로 표시한다. |
| 기본 생성 및 LoRA | `diffusion_model`, `text_encoder`, `vae`, width/height, seed, steps, cfg, sampler, scheduler, 선택 `loras:[{name,strength}]`. LoRA마다 strength는 **-100..100**이다. | 여러 LoRA를 순서대로 추가·제거하고 각 가중치를 편집할 수 있다. positive/negative는 `generation_inputs`에 넣지 않고 Core preview가 조합한다. 실제 등록 모델·LoRA 호환성은 Generation이 최종 검사하므로 UI가 임의 파일명이나 자동 fallback을 만들지 않는다. |
| 후처리 stage | `postprocess`의 선택 키는 `upscale`, `detailer`, `censor`, `alpha`, `encode`; 실행 순서는 고정이다. stage를 객체에 넣는 것이 enable이며 누락은 disable이다. | Detailer는 face/eye/mouth/hand enable과 detector·SAM·seed/steps/cfg/sampler/scheduler/denoise, Censor는 segmentation model/labels/confidence/treatment/intensity, Alpha는 segmentation model/confidence를 각각 현재 등록 선택지에서 설정한다. 임의 graph·경로·다운로드 UI는 제공하지 않는다. 노드/모델 미등록 오류를 stage별로 보여 준다. |
| PNG/WebP | `encode.webp_enabled`와 `encode.webp_quality`(1..100)가 현재 API 필드다. | PNG는 저장 결과의 기본 형식이며 WebP는 선택 파생 출력이다. 따라서 현재 계약에는 PNG off 또는 별도 PNG quality control이 없다. UI는 WebP toggle/quality만 제공하고 결과별 media type을 표시한다. |
| 자동·수동 재생성 | 전역 설정 `auto_regeneration_enabled`와 `max_auto_regenerations`(0 이상 정수, 기본 **5**). | 사용자는 자동 흐름 on/off와 상한을 바꿀 수 있다. 최초/수동 요청은 자동 횟수에 포함되지 않고, **수동 재생성은 횟수 제한이 없으며** 새 자동 cycle을 만든다. Core가 횟수·취소·후속 검증을 조정하므로 UI는 남은 횟수/state를 표시할 뿐 자동 재시도 규칙을 자체 구현하지 않는다. |
| Validation 응답 상한 | provider setting의 선택 `max_tokens`(양의 정수) | 이 값은 Provider revision에만 저장하고 단일/묶음 snapshot에 고정한다. **1024는 최근 로컬 시험값일 뿐 전역 기본값이나 모든 모델 권장값이 아니다.** 생략은 별도 의미를 가지므로 UI가 임의 기본값을 주입하지 않는다. `finish_reason=length`는 합격이 아니라 Validation 오류로 표시한다. |

## 구현된 Backend와 아직 없는 표면의 경계

현재 구현 REST로 위의 기본 편집·생성·검증·그룹 흐름을 구성할 수 있다. 그러나 다음은 Frontend 자체 또는 필요한 API가 아직 없거나 계약이 미정이다.

1. **Frontend와 Shared API Client 구현물**: Web application, 인증 설정 화면/저장 방식, routing·상태 관리·SSE reconnect UX는 아직 없다. F-14/F-15와 S-01~S-06의 원칙은 확정이지만 framework와 SDK schema 원본은 미정이다.
2. **Prompt 편집 보조의 데이터 모델**: C-05~C-08의 표정·상황·동작 재사용 목록, 복수 선택, 자연어 변환, 포함 조합 상세는 구현 REST가 아니다. 초기 화면은 Task의 자유 문자열과 `include`를 사용하되 새 조합 규칙을 browser에 넣지 않는다.
3. **탐색·미디어 관리 확장**: 후속 구현으로 group/image 목록과 관계·검증 상태 필터를 제공한다([검증 보고서](core-browse-api.md)). Prompt 전문 검색은 지원하지 않는다. 최종 이미지 content와 metadata 조회는 가능하지만 F-08~F-11의 EXIF 상세 열람, 저장 경로 편집, 삭제, Import/Export의 REST 계약도 없다. 외부 파일 업로드는 Validation 전용 upload와 일반 gallery import를 혼동하면 안 된다.
4. **모델 관리와 AI Draft**: F-12 및 C-09~C-13은 화면만 먼저 만들 수 있는 기능이 아니다. 모델 탐색·다운로드와 AI Draft → Review → Apply의 권한/실행 계약은 미정이며, 현재 생성 Node 목록 조회를 모델 관리 API로 해석할 수 없다.
5. **진행 표시 한계**: Queue/SSE는 상태 변경을 제공하지만 ComfyUI 내부 노드 progress와 중간 이미지 preview는 없다. polling으로 이를 추정하거나 로컬 경로를 읽는 UI는 REST-first 원칙을 위반한다.
6. **지원되지 않은 generation knob**: 타일·overlap·목표 크기·lossless upscale, PNG off/quality, 임의 ComfyUI graph·경로·모델 다운로드는 현재 입력 계약이 아니다. 화면에서 이들을 숨은 기본값이나 임의 JSON으로 보내면 안 된다.

## 권장 구현 순서 (제안)

1. **P0 — 공용 API Client와 App shell**: 토큰·세 service URL 주입, 공통 오류 모델, 페이지 query, SSE reset 재조회만 구현한다. Client는 REST 호출을 감싸되 orchestration을 복제하지 않는다.
2. **P1 — 편집·preview·Task 결과**: work/character/outfit tree, global/character prompt, group 생성, task preview/submit, task/job/image/validation 상세와 최종 output lightbox를 연결한다. 이 단계가 F-01~F-06의 최소 실행 흐름이다.
3. **P2 — 설정·Preset**: generation/postprocess preset revision UX와 validation profile/provider 설정을 추가하고, archived/revision conflict/pending synchronization을 명확히 처리한다.
4. **P3 — batch와 그룹 검토**: Batch 현황, reference candidate의 사용자 확인, group result evidence, 수동 replacement를 추가한다. 자동 기준 교체·자동 재생성 UI는 추가하지 않는다.
5. **P4 — 별도 결정 뒤 확장**: prompt catalog/AI Draft, 모델 다운로드, Import/Export, 경로·삭제·EXIF 상세, 중간 preview는 각각 Backend 계약과 정책이 확정된 뒤 다룬다.

이 순서는 기존 확정 계약만 사용하므로 추가 ADR 승인 질문 없이 P0~P3의 화면 설계를 시작할 수 있다. P4 항목은 실제 API·권한·데이터 보존 경계를 결정하기 전까지 완료 기능으로 표시하지 않는다.

## 묶음 v9 표시 보완

기준 사전 비교가 충돌하면 `reference_conflict`와 `target_not_compared=true`를 표시한다. `reference_evidence`는 두 기준 사이의 근거이므로 원문의 target은 두 번째 기준이며, 실제 대상 이미지의 결함으로 요약하지 않는다. 기준 수정/확인과 사용자 선택 재검증을 연결한다. 대상 미비교 feature는 insufficient이고 사전 비교 오류는 error다. 이 분석 시점의 최신 실환경 결과는 [대조 검증 보고서](group-consistency-controls.md)의 7건 중 6건 기대 일치/1건 응답 상한 오류이며 품질 검증 완료가 아니다.

## 후속 화면 구성 합의

사용자가 상단 4개 메뉴와 기본 배치를 승인했다. 최신 [전체 구성](frontend-structure.md), [제작 상세](frontend-production-screen.md), [메뉴별 API 대조](frontend-menu-api-map.md)를 따른다. 앞의 구현 우선순위는 분석 당시 제안이며 화면 구성 합의 또는 API 구현 완료와 구분한다.


## 2026-09-13 Frontend 탐색 API 구현 반영

그룹·이미지 목록, 작업 관계/state 필터 및 전역 일괄 작업 목록을 구현했다. 앞선 group/image 목록 미구현 표기는 이 기록으로 갱신한다. 전체 155개 테스트와 복사 DB의 HTTP 조회·재시작·DB 무변경 검증을 통과했다. [구현·검증 보고서](core-browse-api.md)와 [REST 명세](../api/rest-api.md)를 따른다. Frontend 화면과 Shared Client 구현 완료를 뜻하지 않는다.


## Client·CLI 후속 상태

Core 탐색 API를 호출하는 Python Client와 읽기 전용 CLI의 첫 구현을 추가했다([사용법·검증](shared-client-cli.md)). 앞의 Shared Client 없음 표기는 이 범위에 한해 갱신한다. 브라우저용 SDK와 생성·검증 명령, 세 서비스 전체 Client는 아직 남아 있다. [갤러리](frontend-gallery-screen.md)·[작업 현황](frontend-jobs-screen.md)은 검토용 상세 초안이다.


## 2026-09-13 파일럿 구현 반영

사용자 후속 지시로 네 메뉴의 F/E 파일럿을 구현했다. 앞의 화면 코드 미구현 표기는 [현재 실행·검증 범위](frontend-pilot.md)로 갱신한다. 상세 초안 전체가 모두 구현·시험된 것은 아니며 JSON 입력과 후속 검증 범위를 보고서에 구분했다.
