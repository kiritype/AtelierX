# 갤러리 화면 상세 초안

기록일: 2026-09-13. 이 문서는 [Frontend 전체 구성](frontend-structure.md)의 갤러리 영역을 실제 Core 조회·변경 API에 연결하기 위한 **구현 초안**이다. 화면 코드, 새 REST 경로, 삭제·외부 파일 import 정책을 확정하지 않는다. 계약의 기준은 [REST API 명세](../api/rest-api.md)와 [Core 탐색 API](core-browse-api.md)다.

## 목적과 화면 경계

갤러리는 저장된 최종 이미지를 관계별로 찾아 보고, 해당 이미지가 받은 단일 검사와 현재 기준의 묶음 판정을 분리해 검토한다. 여기서 "합격"은 단일 검사와 묶음 검사가 모두 합격했다는 뜻으로 합치지 않는다. 생성 설정·Prompt·검증 이력은 각 이미지가 속한 당시 Task 또는 Run의 읽기 전용 snapshot으로 표시한다.

목록에서 이미지 bytes·로컬 파일 경로·전체 Prompt는 받지 않는다. 인증된 `content_url`로 축소 보기와 확대 보기를 읽고, 상세 진입 후에만 `GET /v1/images/{id}`와 관련 이력을 요청한다. 이 화면은 Generation·Validation 서비스를 직접 호출해 임의 이미지나 재검증 Job을 만들지 않는다.

## 기본 배치

```text
┌───────────────────────────────────────────────────────────────────────────────┐
│ 갤러리   전체 / 현재 작품·캐릭터·의상                         필터 초기화      │
├───────────────┬───────────────────────────────────────────┬───────────────────┤
│ 작품          │ 단일 검사 [전체 ▾]  묶음 검사 [전체 ▾]     │ 이미지 상세       │
│ └ 캐릭터      │ 형식 [PNG/WebP/전체]  정렬: 최신 접수순     │ 최종 이미지       │
│   └ 의상      ├───────────────────────────────────────────┤ Prompt·설정       │
│               │ [카드] [카드] [카드]                       │ 단일 검사 이력    │
│ 전체 결과     │ [카드] [카드] [카드]                       │ 묶음 기준·판정    │
│               │ 이전 / 다음 · 총 N개                       │ 재검증·재생성     │
└───────────────┴───────────────────────────────────────────┴───────────────────┘
```

왼쪽 분류 선택은 `work_id`, `character_id`, `outfit_id` 필터로 변환한다. 여러 조건은 AND이며 보관된 분류의 과거 이미지도 반환될 수 있다. 목록의 `created_at`은 현재 저장 구조에서 이미지 생성 완료 시각이 아니라 **Task 접수 시각**이다. offset 페이지는 새 결과가 생기면 항목이 이동할 수 있으므로, 페이지를 고정 snapshot처럼 표시하지 않는다.

## 목록·필터·카드

목록은 `GET /v1/images`를 사용한다. 선택 가능한 query는 `work_id`, `character_id`, `outfit_id`, `group_id`, `task_id`, `media_type`, `single_outcome`, `group_status`, `limit`, `offset`이다. 공통 페이지 기본값은 limit 50, 허용 범위는 1..200이다. 빈 조건이나 잘못된 UUID는 400이고, 유효하지만 결과가 없는 관계 조합은 빈 목록 200이므로 오류 화면과 빈 결과를 구분한다.

카드에는 다음만 표시한다.

| 카드 정보 | 실제 목록 필드와 표시 규칙 |
| --- | --- |
| 미리보기 | 인증 헤더를 포함해 `content_url`을 요청한다. 불러오지 못하면 깨진 이미지 대신 "이미지를 불러올 수 없음"과 재시도 동작을 표시한다. |
| 관계 | `work_id`, `character_id`, `outfit_id`, `group_id`를 현재 트리의 이름과 연결해 표시한다. 목록에 이름이 없으므로 필요할 때 기존 category 조회 결과를 재사용한다. |
| 형식·크기 | `media_type`, `bytes`를 표시한다. PNG와 WebP는 별개 결과이며 하나를 다른 하나의 축소본으로 가정하지 않는다. |
| 단일 검사 | `single_outcome`: `unvalidated`, `pending`, `passed`, `failed`, `error`, `cancelled`를 그대로 라벨링한다. 과거 pass 뒤 새 요청이 pending이면 pending을 현재 상태로 표시한다. |
| 묶음 검사 | `group_status`: `reference`, `matched`, `mismatch`, `insufficient`, `reference_conflict`, `error`, `unvalidated`, `stale`, `not_eligible`를 단일 검사와 별도 배지로 표시한다. reference는 기준 역할이지 단일 합격을 뜻하지 않는다. |

`single_validation_run_id`, `group_validation_run_id`, `group_reference_revision`은 상세 진입 연결에 사용한다. 현재 기준 revision은 stale 결과가 만들어졌던 과거 revision이 아니다. 목록만으로 판정 근거를 추론하거나 "전체 합격" 정렬을 만들지 않는다.

## 이미지 상세

카드를 선택하면 `GET /v1/images/{id}`를 읽고, 그림은 `GET /v1/images/{id}/content`로 확대한다. 상세는 다음 순서로 구성한다.

1. 최종 이미지, media type, hash·bytes, Task와 Group 링크를 보인다. `CORE_IMAGE_UNAVAILABLE`, `CORE_IMAGE_INTEGRITY`, endpoint 변경 오류는 콘텐츠 접근 오류로 표시하고 metadata 자체를 지우지 않는다.
2. Task 링크를 따라 `GET /v1/tasks/{task_id}`의 당시 snapshot에서 실제 Prompt·생성/후처리 설정·validation selection을 읽기 전용으로 표시한다. 현재 Preset이나 현재 전역 설정을 과거 입력처럼 덮어쓰지 않는다.
3. `GET /v1/images/{id}/validations`로 단일 검사 이력을 시간순으로 보이고, 선택한 run은 `GET /v1/validation-runs/{run_id}`로 result·outcome·error를 펼친다.
4. Group 링크를 따라 현재 묶음 상태와 기준을 읽고, 아래 그룹 검토 영역을 연다. 이미지 하나의 단일 검증 결과를 그룹 전체 결론으로 바꾸지 않는다.

## 단일 검사와 수동 재생성

단일 검사 재요청은 `POST /v1/images/{id}/validations`에 선택한 `{provider_id,profile_id}`와 새 `Idempotency-Key`를 보낸다. 같은 버튼의 응답이 유실되면 같은 key와 같은 요청만 재시도해 기존 Run을 찾고, 입력을 바꾼 새 요청에는 새 key를 사용한다. 202는 신규 접수, 200은 같은 key의 기존 Run이다. HTTP 상태만으로 완료 여부를 판단하지 않고 Run의 `state`와 `outcome`을 읽어 표시한다. 따라서 200으로 돌아온 기존 Run도 이미 완료됐을 수 있다.

일반 수동 재생성은 이미지의 `task_id`에 대해 `POST /v1/tasks/{task_id}/regenerations`를 사용한다. body는 `{}` 또는 지원되는 generation/postprocess/validation override다. 진행 중 생성·검증·자동 후속이 있으면 `CORE_REGENERATION_ACTIVE`(409)이므로 새 요청을 만들지 않고 해당 시도/작업 화면으로 이동한다. 수동 재생성은 새 Task·새 이미지로 남으며 원본 이미지와 과거 검증 이력을 수정하지 않는다.

## 그룹 검토와 기준 교체

Group 상세 패널은 `GET /v1/groups/{id}/consistency`를 기준으로 현재 reference, 대상 목록, 제외 목록, 상태별 count를 보인다. representative와 auxiliary(최대 2장)는 대상과 구분해 표시한다. `reference_conflict`는 대상의 품질 결함이 아니라 기준끼리의 모순이며, `insufficient`은 가림·관찰 부족, `stale`은 현재 기준으로 유효한 완료 판정이 없는 과거 결과다.

기준 후보 보기만은 `GET /v1/groups/{id}/reference-candidate`다. 이 호출은 저장·기준 교체·검증 실행을 하지 않는다. 사용자가 후보 또는 적격 단일 통과 이미지를 대표·보조로 명시적으로 선택한 뒤에만 `PUT /v1/groups/{id}/reference`에 `{revision,representative_id,auxiliary_ids}`를 보낸다. 현재 revision 불일치나 적격성 변경은 409으로 처리하고 consistency·candidate를 다시 읽어 선택을 재확인한다. 기준 변경은 revision만 올리고 자동 묶음 검증·자동 재생성을 시작하지 않는다.

선택 묶음 재검증은 `POST /v1/groups/{id}/validations`에 현재 `reference_revision`, `target_ids`, group 전용 `{profile_id,provider_id}`와 `Idempotency-Key`를 보낸다. 상태와 근거는 `GET /v1/groups/{id}/validations`, `GET /v1/group-validation-runs/{run_id}`에서 읽는다. 활성 대상의 중복 요청(`CORE_GROUP_ACTIVE`), stale 기준(`CORE_GROUP_STALE`), 비적격 이미지(`CORE_GROUP_IMAGE_INELIGIBLE`)는 기존 실행을 숨기거나 강제 대체하지 않고 사유와 새로고침 동작을 보여 준다.

묶음 mismatch인 한 이미지를 교체하려면 일반 수동 재생성 대신 `POST /v1/groups/{id}/replacements`를 사용한다. 이 경로는 선택 이미지의 group·현재 reference revision·단일 통과 상태를 고정하고 새 결과가 단일 검증을 통과했을 때만 현재 기준으로 그 이미지 하나를 묶음 검증한다. 진행 상태·최종 결과는 `GET /v1/groups/{id}/replacements`에서 보인다. 기준 변경, 생성/단일 검사 실패, 취소, PNG/WebP 파생 순번 불일치는 명시 상태로 종료되며 화면이 자동 기준 교체나 자동 재시도를 하지 않는다.

## 수용 시나리오

- 작품·캐릭터·의상과 단일/묶음 상태 필터를 함께 적용하면 API AND 조건에 맞는 카드만 보인다. 잘못된 필터 400과 결과 0개를 같은 빈 화면으로 표시하지 않는다.
- 단일 pass였던 이미지에 재검증을 접수하면 완료 전에는 pending을 보이며, 과거 pass를 현재 pass로 병기하지 않는다.
- 기준 후보를 열기만 해서는 reference revision, 묶음 Run, 재생성 Task가 생기지 않는다.
- 사용자가 기준을 교체하면 기존 묶음 결과는 stale/이력으로 남고 새 기준 결과와 섞이지 않는다.
- mismatch 이미지에서 replacement를 접수하면 원본 이미지는 남고 새 Task와 새 이미지의 단일→묶음 흐름을 추적한다.
- 콘텐츠 요청이 무결성 오류를 받아도 목록 card의 metadata와 검증 이력은 유지하고, 임의 파일 경로나 URL로 대체 이미지를 요청하지 않는다.

## 현재 API 밖의 항목

일반 이미지 import·삭제, 파일 경로 표시, 자유 Prompt 전문 검색, EXIF 편집, 다중 선택 일괄 삭제, 브라우저에 원본 파일을 보관하는 정책은 현재 API 범위에 없다. 카드의 별점·태그·사용자 코멘트도 이 초안에 포함하지 않는다. 이 문서는 그러한 기능을 추가 승인하거나 구현 완료로 기록하지 않는다.
