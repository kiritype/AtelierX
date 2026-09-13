# Frontend 메뉴별 API 대조와 최소 보완 범위

작성일: 2026-09-13
대상 메뉴: **제작 / 갤러리 / 작업 현황 / 설정**. 이 문서는 [Frontend 요구사항 분석](frontend-requirements-analysis.md)의 API 대조를 메뉴 단위로 압축한 것이다. 아래 대조표는 구현 전 분석 기록이다. 사용자 승인 후 P0~P2 조회 API를 구현·검증했다. 최신 계약은 [REST 명세](../api/rest-api.md), 결과는 [탐색 API 보고서](core-browse-api.md)를 따른다. 갤러리의 제안 `state`는 실제 계약에서 `single_outcome`과 `group_status`로 분리했다.

## 최초 분석 당시 공통 전제

- 모든 사용자 동작은 Core REST를 우선 사용한다. Generation/Validation의 직접 API는 상세 상태·등록 노드 같은 service-owned 정보 조회가 필요한 경우에 한정한다. Frontend는 Prompt 조합, 재생성, 검증 순서를 중복 실행하지 않는다.
- 현재 Core에는 `works`, `characters`, `outfits`의 page 목록이 있지만 `groups`와 `images`의 전역 목록은 없다. `GET /v1/groups/{id}`와 `GET /v1/images/{id}`는 식별자를 이미 알고 있을 때만 쓸 수 있다.
- 생성·검증·묶음 요청에는 `Idempotency-Key`가 필요하고, 수정에는 revision 충돌(409)이 있다. 화면은 새 요청을 재전송해 상태를 만들어 내지 않고 기존 key/ID를 조회한다.

## 최초 분석 당시 메뉴 대조 (부족분·제안은 아래 완료 기록으로 갱신)

| 메뉴 | 구현된 API로 가능한 최소 흐름 | 구현 API의 부족분 | 최소 보완 API 제안과 우선순위 |
| --- | --- | --- | --- |
| **제작** | `GET/POST/PATCH /v1/{works,characters,outfits}`와 parent/page query로 트리를 연다. 의상은 `components:{appearance,upper,lower}` 전체를 revision과 함께 저장한다. `POST /v1/groups`가 해당 outfit revision을 고정한 group을 만든다. 이미 알고 있는 group은 `GET /v1/groups/{id}`로 읽고 `POST /v1/prompts/preview` → `POST /v1/tasks`로 생성한다. Task/preset/validation 선택과 output 상세는 기존 API로 가능하다. | outfit 아래의 **재사용할 group 목록**이 없다. 따라서 생성 화면은 새 group을 만들 수 있어도 이전 group을 찾아 재사용하거나, 같은 outfit의 고정 revision이 무엇인지 비교할 수 없다. 표정·상황·동작의 저장 목록도 없다. | **P0: `GET /v1/groups?outfit_id=&limit=&offset=`**. 각 item은 `id,outfit_id,character_id,work_id,outfit_revision,components,created_at,reference?`만 반환한다. 이는 group을 편집하는 API가 아니라 기존 고정 group을 찾는 API다. 표정 등의 catalog API는 별도 결정 전에는 제안하지 않는다. |
| **갤러리** | Task 상세의 `images`, `GET /v1/images/{id}`, `GET /v1/images/{id}/content`으로 한 Task의 최종 PNG/WebP를 preview/lightbox로 볼 수 있다. 단일 validation history와 group consistency 결과도 ID 경유로 연결 가능하다. | 전역 image 목록, page/filter, gallery search가 없다. `/v1/tasks?group_id=`는 group을 아는 경우의 Task 목록일 뿐 work/character/outfit별 결과 탐색이나 image 검색을 대체하지 않는다. EXIF/파일 내 metadata 상세, 삭제, 일반 이미지 import도 계약이 없다. | **P1: `GET /v1/images`의 metadata-only page 조회**. 최소 filter는 `work_id,character_id,outfit_id,group_id,task_id,media_type,state`와 `limit,offset`; 응답은 image ID, 관계 ID, 생성시각, media type, bytes, validation 요약, content URL이다. 자유 Prompt 전문 검색, 로컬 경로 노출, 삭제/import는 이 slice에 넣지 않는다. |
| **작업 현황** | `GET /v1/tasks?group_id=&limit=&offset=`, Task/attempt/cycle 상세, Core/Generation/Validation 각각의 `GET /v1/queue`, `GET /v1/events`, task/validation/job cancel, 그리고 group별 batch 목록·상세·cancel/confirm-reference가 있다. SSE reset 뒤에는 해당 page를 다시 읽을 수 있다. | 전체 Task를 group 외 기준으로 필터링하는 목록, group을 모르는 상태에서 전체 batch를 보는 목록, 세 service queue의 사용자용 통합/관계 표면이 없다. 현재는 Node별 progress와 중간 preview도 없다. | **P2: Core `GET /v1/group-batches?group_id=&state=&limit=&offset=`**와 **`GET /v1/tasks`의 선택 `state,work_id,character_id,outfit_id` filter**. 응답은 기존 Task/Batch public field만 사용하고 관계 ID·상태·시간·오류 요약을 포함한다. 세 service queue를 하나의 새 scheduler API로 합치지 않으며, UI는 기존 `/v1/queue`와 SSE reset 규칙을 사용한다. |
| **설정** | 전역 `GET/PATCH /v1/settings`; generation/postprocess preset collection/detail/revision; validation single/group profile 및 provider의 생성·수정·복제·보관·revision·connection; Generation `GET /v1/nodes`가 구현돼 있다. 기본 1024 생성, UltraSharp 1.5배 기본 후처리, WebP 옵션과 자동 재생성 설정은 기존 contract에서 조작·표시할 수 있다. | Core/Generation/Validation URL·token의 browser 저장/교체 API는 없고, Provider secret은 설계상 조회·이력 응답에 없다. `/v1/nodes`는 등록 Node/schema이지 모델 탐색·다운로드 관리 API가 아니다. 서비스별 설정의 종합 상태 화면도 화면 구현 과제이지 새 backend 설정이 아니다. | **P3: 새 credential 또는 endpoint 편집 API는 제안하지 않는다.** 현 slice는 existing settings/preset/profile/provider/node route를 공용 client로 정규화해 표시하면 된다. 모델 다운로드·AI Draft·비밀 설정 UX는 별도 권한/Backend 계약이 확정된 뒤 검토한다. |

## 제작의 group 고정·재사용 표면

`POST /v1/groups`는 의상 구성과 revision을 group에 고정한다. 이후 의상 편집은 기존 group의 구성이나 과거 Task snapshot을 바꾸지 않는다. 수정된 의상으로 만들려면 새 group을 만들고, 이전 조합으로 재생성하려면 이전 group ID를 사용한다. 같은 조합의 별도 group도 허용된다.

따라서 P0 목록의 수용 기준은 “현재 의상 내용을 group에 덮어쓰기”가 아니라 다음만 충족하는 것이다.

1. outfit ID로 page 조회하고, 고정 `outfit_revision`/components를 포함한다. 현재 group 자체의 archive 필드는 제안하지 않는다.
2. 같은 outfit의 서로 다른 group을 모두 별도 ID로 반환한다.
3. 목록 조회·재시작·page 재조회가 group 또는 Task snapshot을 변경하지 않는다.
4. Frontend는 결과의 group ID를 그대로 preview/Task 입력에 사용한다. 새 group 생성은 명시적 `POST /v1/groups`만 수행한다.

## API 개발을 위한 bounded slice 수용 기준

| Slice | 범위 | 완료 판정 |
| --- | --- | --- |
| P0 group 목록 | Core read-only `GET /v1/groups` | 인증, `outfit_id` filter, limit 1..200/offset, 안정된 page 응답, 존재하지 않는 outfit의 명확한 결과를 검증한다. individual group 응답과 같은 고정 revision/components를 반환하며 생성·수정·reference 확인을 일으키지 않는다. |
| P1 image gallery 목록 | Core read-only `GET /v1/images` | 인증, 명시한 관계/상태 filter와 pagination, metadata-only descriptor, content URL이 동작한다. content bytes·파일 시스템 경로·provider secret을 목록에 넣지 않으며 기존 이미지와 Task history를 변경하지 않는다. |
| P2 task/batch 목록 filter | Core read-only filter 확장 | Task filter와 batch page가 각각 필터·page·상태/오류 요약을 정확히 반환한다. Task/Batch 실행, Core의 FIFO, regeneration cycle, validation 요청을 만들거나 취소하지 않는다. SSE reset이 이 목록을 재조회 가능한 상태로 남긴다. |
| P3 existing settings client | 새 REST 없음 | preset/profile/provider의 revision·archive·pending synchronization·secret redaction, nodes의 등록 상태를 기존 route에서 표시할 수 있다. URL/token/secret을 UI가 새 API로 저장하거나 history에 노출하지 않는다. |

이 순서는 Frontend가 필요한 browse 식별자를 먼저 확보하고, 그 다음 결과·작업 목록을 열도록 제한한다. P0~P2는 조회 전용이라 기존 Core 소유 상태나 GPU 작업에 영향을 주지 않는다.

갤러리 제안의 `state`는 아직 단일 enum 계약이 아니다. 단일 outcome과 묶음 status·기준 revision 유효성을 구분해 필터/요약을 설계해야 하며 stale/미검증을 합격으로 집계하지 않는다. 목록 순서는 같은 생성시각에서도 ID로 안정적으로 결정하고, 페이지 이동 중 신규 데이터 유입에 대한 offset 방식의 한계도 명시한다.


## 2026-09-13 Frontend 탐색 API 구현 반영

그룹·이미지 목록, 작업 관계/state 필터 및 전역 일괄 작업 목록을 구현했다. 앞선 group/image 목록 미구현 표기는 이 기록으로 갱신한다. 전체 155개 테스트와 복사 DB의 HTTP 조회·재시작·DB 무변경 검증을 통과했다. [구현·검증 보고서](core-browse-api.md)와 [REST 명세](../api/rest-api.md)를 따른다. Frontend 화면과 Shared Client 구현 완료를 뜻하지 않는다.
