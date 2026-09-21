# 설정 화면 상세 초안

기록일: 2026-09-13. 사용자가 승인한 "좌측 설정 category, 우측 세부 설정" 구성을 현재 REST 계약에 연결한 검토용 초안이다. section 재분류와 접기는 화면 구현에서 조정할 수 있다. 이 문서는 Frontend 코드, 새 설정 API, URL·token 저장 방식, 모델 설치·다운로드 정책을 확정하지 않는다.

## 화면 역할과 원칙

설정은 반복해서 쓰는 전역 값, 생성·후처리 Preset, 검증 Profile·Provider를 관리한다. 작품·캐릭터·의상 원문과 캐릭터 Negative는 제작 화면의 category 편집 영역에 남는다. 과거 Task·이미지·검증 Run은 접수 당시 snapshot을 보존하므로, 현재 설정을 바꾸어도 과거 실행 상세가 바뀐 것처럼 보이지 않게 한다.

기본 핵심 필드는 처음 열고, 드물게 조정하는 값·이력·보관 목록·연결 진단은 접을 수 있다. 접힘은 서버 상태를 생략하거나 기본값을 암묵적으로 바꾸는 동작이 아니다. 모든 변경은 Shared API Client를 통해 Core REST를 호출하며, Generation·Validation의 내부 설정 파일이나 SQLite를 브라우저가 직접 읽지 않는다.

## 기본 배치

```text
┌──────────────────────────────────────────────────────────────────────────────┐
│ 설정                                                                        │
├────────────────────┬─────────────────────────────────────────────────────────┤
│ 전역 Prompt         │ 전역 Prompt                                            │
│ 자동 재생성         │ [핵심] 품질 Positive / 품질 Negative                  │
│ 생성 Preset         │ [저장] [되돌리기]                                     │
│ 후처리 Preset       │ ───────────────────────────────────────────────────── │
│ 단일 검사 Profile   │ [고급 ▸] revision 이력 · 보관 목록 · 연결 진단        │
│ 묶음 검사 Profile   │                                                         │
│ 검사 Provider       │                                                         │
│ 실행 환경 상태      │                                                         │
└────────────────────┴─────────────────────────────────────────────────────────┘
```

좌측 항목은 서로 다른 별도 URL이 아니라 하나의 설정 화면 안의 문맥 전환이다. 작은 화면에서는 navigation을 접고 선택한 category의 제목·저장 상태를 상단에 고정한다. 연결 상태와 서비스 주소를 안내할 수 있으나 token 값은 navigation에 표시하지 않으며, credential 편집·브라우저 저장 UI는 제공하지 않는다. 그 방식은 아직 미정이다.

`Core 연결` 항목은 server-private Frontend connection 설정이 있는 Core에서 Access 자동 연결의 상태만 보여 준다. `configured`, `connected`, 인증 방식, token 저장 여부와 public origin은 표시할 수 있지만 Core token·Access assertion·JWKS는 반환하거나 표시하지 않는다. 최초 연결을 복구할 때만 사용자가 현재 Core token을 입력해 `PUT /v1/frontend-connection`으로 서버 설정의 같은 token을 확인·저장할 수 있다. 이 요청은 서비스 전체 token 회전이 아니며 입력값은 전송 후 즉시 지운다. 설정이 없거나 로컬 실행이면 기존 상단 Bearer 연결을 유지한다.

## category와 실제 API 연결

| 좌측 category | 우측 핵심 내용 | 실제 Core API | 접어서 보이는 내용 |
| --- | --- | --- | --- |
| 전역 Prompt | `positive_quality`, `negative` | `GET/PATCH /v1/settings` | revision, 마지막 저장 오류 |
| 자동 재생성 | On/Off, `max_auto_regenerations` | `GET/PATCH /v1/settings` | 적용 시점 설명 |
| 생성 Preset | 이름, generation settings, 현재 revision | `GET/POST /v1/presets/generation`, item PATCH·revisions | 보관·과거 revision |
| 후처리 Preset | stage 설정, 모델명, 최종 배율, Encode | `GET/POST /v1/presets/postprocess`, item PATCH·revisions | 보관·실행 전 자원 검사 설명 |
| 단일 검사 Profile | output conditions, Positive·Negative 검사 등 현재 지원 필드 | `/v1/validation-settings/single-profiles` collection/item/revisions/clone/archive | 보관 목록·동기화 상태 |
| 묶음 검사 Profile | `{profile_id, revision, consistency:true}` | `/v1/validation-settings/group-profiles` collection/item/revisions/clone/archive | 보관 목록·동기화 상태 |
| 검사 Provider | provider ID, model, timeout, 등록 URL·지원 형식 | `/v1/validation-settings/providers` collection/item/revisions/clone/archive 및 `/{id}/connection` | 연결 진단·동기화 상태 |
| 실행 환경 상태 | 등록된 Generation Node/schema 읽기 전용 요약 | `GET Generation /v1/nodes` | Node 미등록/모델 미등록 오류 안내 |

Profile과 Provider의 collection은 `include_archived=true`로 보관 항목까지 조회한다. Preset collection은 `archived=true|false` 또는 생략으로 보관 포함 여부를 선택한다. 목록은 보관 항목을 현재 새 작업에 적용 가능한 항목처럼 표시하지 않는다.

## 전역 Prompt와 자동 재생성

전역 Prompt는 품질 Positive와 품질 Negative만 편집한다. 전역 Negative는 **생성 전용 품질 조건**이며 Validation의 불합격 근거에는 넣지 않는다는 설명을 핵심 필드 가까이에 둔다. 캐릭터 Negative는 이미지에 나타나면 불합격시킬 수 있는 캐릭터별 금지 요소이므로 이 화면으로 옮기지 않고 제작 화면의 캐릭터 편집으로 연결한다.

자동 재생성은 `auto_regeneration_enabled`와 0 이상 정수 `max_auto_regenerations`를 편집한다. 기본 상한은 5회이고 Off 또는 0이면 자동 재생성을 하지 않는다. 수동 재생성은 횟수 제한이 없으며, 수동 요청마다 당시 설정으로 새 cycle의 자동 상한을 받는다. 이미 시작한 cycle은 당시 snapshot을 유지하므로 설정 화면은 "새 최초/수동 요청부터 적용"이라고 표시하고 진행 중 작업의 used/limit을 여기서 바꾸지 않는다.

`PATCH /v1/settings`에는 읽은 `revision`과 바꾼 필드만 보낸다. 응답의 새 revision을 화면 기준으로 갱신한다. 409 revision 충돌이면 현재 값을 다시 읽어 사용자 초안과 나란히 보이고, 자동 덮어쓰기·재시도는 하지 않는다.

## 생성·후처리 Preset

Preset은 현재 settings 전체를 저장하는 재사용 단위이며 generation과 postprocess를 별도 category로 관리한다. 생성 Preset에는 모델·text encoder·VAE·해상도·seed·steps·CFG·sampler·scheduler·LoRA처럼 generation inputs만 넣는다. Positive/Negative Prompt, endpoint, API key, 절대 경로, 임의 graph는 저장하지 않는다.

후처리 Preset은 고정 stage 설정을 편집한다. 기본 설정을 안내할 때는 생성 입력 width/height 생략 시 1024×1024, postprocess와 postprocess Preset을 모두 생략할 때 `4x-UltraSharp.safetensors`와 최종 scale 1.5, WebP 품질 90이 적용되어 1536×1536을 목표로 한다고 표시한다. 모델 고유 4배와 최종 1.5배는 별개다. 사용자가 명시한 postprocess 객체(빈 객체 포함)나 Preset은 이 기본값으로 덮어쓰지 않는다.

Preset 저장은 `POST /v1/presets/{generation|postprocess}`의 `{name,settings}`이고 수정은 `PATCH`의 `{revision,name?,settings?,archived?}`다. 수정은 settings 일부 병합이 아니라 전체 settings 교체이므로, 편집 화면은 저장 전 현재 값을 모두 유지한다. 409 `CORE_REVISION_CONFLICT`이면 최신 revision·settings를 읽고 초안과 비교한다. 보관은 `archived:true` PATCH이며 삭제가 아니므로 이력과 과거 Task snapshot은 남는다. 현재 Preset API에는 clone 경로가 없으므로 화면이 clone을 가장해 원본을 수정하지 않는다. 새 이름의 Preset 생성은 명시적인 POST로만 한다.

실행 환경 상태의 `GET /v1/nodes`는 등록 Node와 schema를 읽는 용도다. Preset 저장이 선택 모델의 실제 설치·호환성을 보장하지 않으며 Generation이 실행 시 최종 검사한다. 모델 미등록은 `GEN_UPSCALE_MODEL_UNAVAILABLE`, Node 미등록은 `GEN_NODE_UNAVAILABLE`로 드러날 수 있다. 이 화면은 모델 검색·다운로드·자동 fallback을 제공하지 않는다.

## 단일·묶음 검사 Profile

단일 Profile은 현재 구현된 검사만 활성화한다. API는 `profile_id`, `revision`, `output_conditions`, `positive_prompt`, `negative_prompt`, `body_parts`, `metadata`, `consistency`를 받으며, 아직 지원하지 않는 body_parts·metadata·consistency를 임의로 On 하는 UI를 만들지 않는다. 묶음 Profile은 dedicated consistency Profile인 `{profile_id,revision,consistency:true}`만 관리한다. 같은 profile ID는 단일·묶음 namespace 전체에서 유일해야 하므로 새 ID 충돌은 사용자에게 이름 변경을 요구한다.

각 Profile은 신규 등록, 현재 revision 수정, revision 이력, clone, archive를 제공한다. clone은 `POST /{id}/clone`에 새 ID를 보내 revision 1의 별도 설정을 만든다. archive는 `POST /{id}/archive`에 현재 revision을 보내 새 선택에서 제외하며, 기존 Task/Run의 고정 snapshot과 이력은 유지한다. 보관된 항목을 선택해 새 작업에 적용하려 하면 서버가 거절하므로 목록에서 읽기 전용·보관 상태를 명확히 보인다.

## 검사 Provider와 비밀 정보

Provider 화면은 provider ID, model, timeout, 등록된 URL과 지원 형식 같은 **비밀이 아닌 설정**만 표시·편집한다. API key 원문은 Core 입력·조회·revision 이력·Validation registry 파일에 포함하지 않으므로 비밀키 입력칸, 마스킹된 기존 값, 복사 버튼을 만들지 않는다. 실행 서버에 어떤 credential이 있는지는 기존 Validation 서버 설정의 책임이며, URL 변경 시 기존 key가 자동 전송되지 않는다.

Provider의 고급 섹션에는 선택 `max_tokens`(양의 정수 응답 상한)를 둔다. 생략과 명시값을 구분하고 임의 기본값을 삽입하지 않는다. 상한 부족으로 응답이 잘리면 검증 오류가 될 수 있으며 화면이 자동으로 상한을 올리거나 재요청하지 않는다. 변경은 새 revision과 후속 요청에 적용하고 과거 snapshot은 유지한다.

Provider도 clone·archive·revision 이력을 제공하며, 저장 응답의 `synchronization`을 각 행과 상세에 보인다.

| synchronization | 화면 의미와 동작 |
| --- | --- |
| `synced` | Core 저장과 Validation registry 반영이 확인됐다. |
| `pending` | Core 저장은 성공했고 Validation 동기화만 대기 중이다. 같은 create를 다시 보내지 않고 해당 ID를 유지해 상태를 다시 읽는다. 실행 전 Core가 동기화를 다시 시도한다. |
| `error` 필드 | 별도 state가 아니라 pending에 포함될 수 있는 동기화 오류 정보다. Core 저장 자체의 실패로 표시하거나 비밀 정보를 노출하지 않는다. |

`GET /v1/validation-settings/providers/{id}/connection`의 `validation_service_reachable`은 Core에서 Validation 서비스까지 도달 가능한지만 뜻한다. Provider 모델 존재, vision/묶음 검사 능력, 추론 품질, 외부 유료 호출 성공을 확인한 결과로 표시하지 않는다.

## 공통 저장·초안·오류 처리

각 category는 서버에서 읽은 revision과 분리된 편집 초안을 가진다. category 전환·접기·필터 변경은 초안을 자동 저장하지 않는다. 미저장 변경이 있으면 다른 category로 이동할 때 유지/버리기를 선택하게 하되, API 실패 뒤에는 초안을 유지한다.

| 상황 | 화면 동작 |
| --- | --- |
| 저장 중 | 같은 항목의 저장 버튼을 잠시 막되 다른 읽기 전용 탐색은 유지한다. |
| 201/200 | 서버 응답 전체와 새 revision으로 초안을 교체한다. validation settings는 synchronization도 함께 표시한다. |
| 400/422 | 지원하지 않는 필드·형식 오류를 해당 입력에 연결하고 초안을 보존한다. |
| 409 | revision·보관·ID/멱등 충돌의 코드와 현재 서버 값을 표시한다. 무조건 overwrite하거나 새 요청 key를 만들지 않는다. |
| 보관 | 신규 선택에서 제거되었음을 표시하되, 과거 revision·Task/Run snapshot은 삭제하지 않는다. |

과거 Task·이미지·검증 상세에서는 현재 이 화면의 설정이 아니라 `snapshot`, `preset_sources`, 고정 Profile/Provider revision을 읽기 전용으로 보여 준다. 설정 화면의 수정·보관·동기화 재시도가 과거 실행의 결과나 입력을 바꾸지 않는다.

## 수용 시나리오

- 전역 Negative를 바꿔도 캐릭터 Negative 편집값이 이 화면에 나타나거나 Validation 불합격 규칙으로 설명되지 않는다.
- 자동 상한을 5에서 3으로 바꾼 뒤 이미 시작한 cycle은 기존 limit을 유지하고, 다음 최초/수동 요청부터 3을 사용한다.
- 후처리 없음으로 명시적 빈 객체를 선택한 경우 기본 UltraSharp 1.5 설정이 다시 주입되지 않는다.
- 보관한 Preset/Profile/Provider는 이력에서 볼 수 있지만 새 Task 선택 후보에는 나오지 않는다.
- Profile 또는 Provider 저장이 pending이면 Core 저장 성공을 보이고 동일 create를 반복하지 않는다.
- Provider 상세·이력·연결 진단 어디에도 API key 원문이나 브라우저 저장 token이 나타나지 않는다.
- 409 뒤 사용자가 최신 설정과 초안을 비교해 다시 저장하기 전에는 서버 값을 자동으로 덮어쓰지 않는다.

## 현재 범위 밖

서비스 URL·token을 브라우저에 저장·교체하는 방식, credential 등록, Provider capability/비용 검사, 모델 파일 검색·다운로드·업데이트, Node 설치·ComfyUI 재시작, AI가 자동으로 Preset을 작성하는 기능은 현재 계약 밖이다. 실행 환경 status가 이 category에 있어도 이러한 기능이 준비됐다는 뜻은 아니다.


## 2026-09-13 파일럿 구현 반영

사용자 후속 지시로 네 메뉴의 F/E 파일럿을 구현했다. 앞의 화면 코드 미구현 표기는 [현재 실행·검증 범위](frontend-pilot.md)로 갱신한다. 상세 초안 전체가 모두 구현·시험된 것은 아니며 JSON 입력과 후속 검증 범위를 보고서에 구분했다.


[파일럿 폼 개선·묶음 회귀](frontend-pilot-refinement.md): 일반 필드·선택 폼, 초안 revision 보호와 실제 PNG 두 장의 묶음 실행을 추가 검증했다. 앞의 JSON 전용/묶음 화면 미시험 표기는 이 보고서의 범위로 갱신한다.
