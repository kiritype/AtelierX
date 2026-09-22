# 전역 프롬프트 조각과 제작 계획 API

## 2026-09-22 외형·액세서리 계약 정정

캐릭터의 `appearance_prompt`는 항상 포함하고, 의상 `components`는 `upper/lower/accessories`다. 조각 `include`에 `accessories` boolean을 추가하며 생략한 과거 조각은 합성 시 true로 해석한다. 과거 조각 revision 문서와 저장된 계획 snapshot을 다시 쓰지 않는다. 이전 문서의 상의/하의만 포함 여부를 갖는다는 표현은 이 확장으로 대체한다.

Positive는 전역 품질 → 캐릭터 외형 → 선택한 상의/하의/액세서리 → 조각 본문 순서다. 신규 그룹은 캐릭터 외형·revision을 고정하고 과거 그룹은 원래 의상 외형 snapshot을 유지한다. 캐릭터 외형 이전 충돌이 남으면 신규 그룹 생성을 거절하며, 사용자가 관리 화면에서 명시적으로 해소한다.

2026-09-13 구현 계약. 외형은 항상 포함하며 조각에서 상의·하의만 선택한다. 조각은 작품/캐릭터/의상과 독립된 전역 자원이다. 선택한 조각 하나가 이미지 변형 하나이며 본문의 줄바꿈이나 쉼표를 별도 이미지로 분리하지 않는다.

## 프롬프트 조각

2026-09-22 공통 적용 확장: 조각의 선택적 `common` boolean은 기본 false(이미지별 생성)다. true이면 공통 적용 프롬프트이며 의상 포함 체크를 UI에서 숨긴다. 저장된 `include`는 보존하지만 공통 합성에는 사용하지 않는다. 기존 조각·과거 revision/snapshot은 자동 변환하지 않는다.

Core preview/Task/제작 계획에 선택적 `common_fragments: [{id, revision}]`을 지정한다. 각 참조는 활성 공통 조각이어야 하고 중복을 허용하지 않는다. 이미지별 `fragment` 또는 계획의 `fragments`는 공통 조각을 받을 수 없다. 공통 본문은 지정 순서대로 전역 품질·외형·의상 뒤, 이미지별 조각 본문 앞에 포함되며 revision과 본문을 snapshot에 고정한다. 공통 적용은 장수를 늘리지 않으며 제작 계획에는 이미지별 조각을 적어도 하나 선택해야 한다. 상의/하의/액세서리 포함은 이미지별 조각에서 결정한다. Negative·검사·재생성 정책은 유지한다.

- `GET /v1/prompt-fragment-categories`: 사용자 관리 단일 단계 분류 목록을 `archived`, `limit`(최대 200), `offset`으로 조회한다. 응답은 `{items, total, limit, offset}`이다.
- `POST /v1/prompt-fragment-categories`: `{name}`으로 분류를 만든다. `GET`/`PATCH /v1/prompt-fragment-categories/{id}`는 현재 분류 조회와 revision 기반 이름 변경·보관 처리를 제공한다. 분류는 `{id, name, revision, archived, created_at, updated_at}`이다.
- `GET /v1/prompt-fragments`: `archived`, `category_id`, `q`, `limit`(최대 200), `offset`으로 조회하며 `{items, total, limit, offset}`을 반환한다. `category_id=uncategorized`는 미분류 조각만 뜻한다. `q`는 이름·본문 부분 검색이며 숫자 또는 `#` 뒤 숫자는 표시 번호 정확 검색이다.
- `POST /v1/prompt-fragments`: 기존 `{name, body, include: {upper: true, lower: false}}`에 선택적 `category_id`(또는 `null`)를 더할 수 있다.
- `GET /v1/prompt-fragments/{id}`: 현재 문서 조회.
- `PATCH /v1/prompt-fragments/{id}`: 현재 `revision`과 변경 필드로 수정·보관 처리.
- `GET /v1/prompt-fragments/{id}/revisions`: 변경 이력 페이지 조회.

분류는 태그가 아니며 조각당 하나 또는 미분류만 허용한다. 조각에는 생성 순서의 전역 양의 정수 `number`가 자동으로 한 번만 부여된다. 번호는 보관 여부와 무관하게 재사용하지 않으며 UUID `id`·revision 이력은 유지한다. 과거 데이터는 생성 시각, UUID 순으로 번호를 채우고 기존 revision 문서는 변경하지 않는다. 보관된 분류는 새 조각 또는 분류 변경 대상으로 지정할 수 없지만, 이미 그 분류를 가리키는 조각은 조회·이력·기존 계획 스냅샷에서 계속 읽을 수 있다.

이름은 1–200자, 본문은 1–20,000자다. 생성 요청에는 `fragment: {id, revision}`을 지정한다. 조각 모드는 기존 구도·표정·동작·상황·include 직접 입력과 혼용하지 않는다. 최신 활성 revision만 신규 계획에 사용할 수 있으며 이미 저장된 계획의 스냅샷은 수정되지 않는다. 기존 스냅샷의 `{id, revision, body, include}` 모양은 호환을 위해 유지한다.

양성 프롬프트는 전역 퀄리티 + 외형 + 조각에서 선택한 상의/하의 + 조각 본문이다. 음성 프롬프트는 기존 전역 네거티브 + 캐릭터 네거티브 정책을 유지한다.

## 제작 계획

2026-09-22 확장: `validation`과 `group_validation`은 선택이다. 둘 다 생략하면 생성만, `validation`만 있으면 단일 검사, 둘 다 있으면 단일+묶음 검사다. `group_validation`만 전달하는 요청은 거절한다. 검사하지 않은 결과는 품질 합격으로 표시하지 않으며 기존 이미지 검사 API로 나중에 검사할 수 있다. 이전 문서의 모든 제작 계획에 검사를 필수로 요구하는 설명은 이 확장으로 대체한다.

Seed `-1`은 무작위 요청을 뜻한다. Core가 각 이미지 실행에 사용할 실제 Seed를 고정해 저장하고 동일 접수 키 재요청·DB 재시작에서 재사용한다. 0 이상의 지정 Seed는 그대로 사용한다. Generation에는 확정된 실제 Seed만 전달한다. UI의 예상 해상도는 생성 크기 × 최종 배율이며 모델 파일명의 고유 배율로 최종 크기를 계산하지 않는다.

신규 계획은 `validation_mode: none | single | single_group`을 반환한다. 생성만 성공하면 항목 `generation_only`, 계획 `completed/unvalidated`로 종료한다. 단일 검사는 묶음 기준을 기다리지 않으며, 모든 항목의 단일 검사 통과 시 `completed/passed`다(묶음 통과 의미 아님). 검사 없는 계획의 생성 실패는 해당 항목의 오류를 보존하고 `failed/error`로 마감한다. 과거 mode 없는 계획은 기존 단일+묶음 검사로 해석한다. `null` 검사 선택은 허용하지 않고 생략으로 검사 제외를 표현한다.

일반 preview의 Seed -1은 해시를 안정적으로 유지하기 위한 요청값이며 Task 저장 시 실제 값으로 치환한다. 제작 계획은 draft 저장 시 항목별 실제 Seed와 해시를 고정한다. 자동 무작위 값은 브라우저에서도 정확하게 표시·재사용하도록 0~2^53−1 범위를 사용한다.

`POST /v1/production-plans`에는 `Idempotency-Key` 헤더와 다음 본문을 전달한다.

```json
{
  "group_id": "고정 그룹 ID",
  "fragments": [{"id": "조각 ID", "revision": 1}],
  "generation_inputs": {},
  "postprocess": {},
  "validation": {"profile_id": "single-default", "provider_id": "local-vision"},
  "group_validation": {"profile_id": "group-pilot", "provider_id": "local-vision"}
}
```

`generation_inputs`에는 기존 생성 입력 계약을 사용하며 대신 `presets`를 사용할 수 있다. 동일 조각 ID 중복은 허용하지 않는다. 신규 계획은 201, 같은 키·본문 재요청은 200이며 다른 본문은 충돌이다. 모든 항목의 프롬프트·설정·조각 revision을 트랜잭션으로 저장하고 `draft` 상태를 반환한다. 이 시점에는 생성 Task를 실행하지 않는다.

| 경로 | 동작 |
| --- | --- |
| `GET /v1/production-plans` | 계획 목록 및 상태별 항목 수; limit/offset |
| `GET /v1/production-plans/by-key` | Idempotency-Key로 접수 결과 복구 |
| `GET /v1/production-plans/{id}` | 상태·전체 수·counts·plan_hash |
| `GET /v1/production-plans/{id}/items` | 고정된 항목과 프롬프트 페이지 조회 |
| `POST /v1/production-plans/{id}/start` | `{plan_hash}`가 일치하면 실행 |
| `POST /v1/production-plans/{id}/cancel` | 미실행 항목 취소 및 진행 중 작업 취소 요청 |
| `GET /v1/production-plans/{id}/comparisons` | 현재 검증 sequence의 묶음 검사 기록 |
| `POST /v1/production-plans/{id}/confirm-reference` | Idempotency-Key와 `{reference_revision}`으로 현재 기준 확인 후 재개 |

계획의 전체 이미지 수에는 제품 상한이 없다. 현재 HTTP 본문 제한 2 MiB는 별도 전송 제약이며 업로드 분할 API는 아직 없다. 저장된 계획은 실행 창 8개로 순차 전달하고 묶음 검증은 같은 기준으로 대상 32개씩 분할한다. 기존 호환 batch API의 32개 제한과 신규 계획 전체 수를 혼동하지 않는다.

기준이 바뀌면 `awaiting_reference_confirmation`에서 사용자의 명시적 확인을 기다린다. 완료 상태와 검증 outcome은 별도다. 일부 실패·오류·검사 불충분을 전체 합격으로 처리하지 않는다. 취소는 즉각 완료를 보장하지 않으며 상태 조회로 종료를 확인한다.

## 다중 그룹 클라이언트와 오류 종료 보완

여러 그룹 선택 시 F/E는 그룹별로 위 API를 호출한다. 각 요청은 독립된 멱등성 키·고정 본문·계획 ID를 가지며 일부 접수 실패를 전체 성공으로 표시하지 않는다. 계획마다 프롬프트를 확인한 뒤 시작한다. 한 조각을 여러 그룹에 적용할 수도 있다. 그룹 간 일관성 비교나 전역 원자적 일괄 접수는 하지 않는다. 브라우저 메모리에 보관한 접수 키는 새로고침 후 유지되지 않으므로 이미 접수된 계획은 작업 현황에서 확인한다.

계획 처리의 ApiError는 `cancellation_pending`, `cancel_requested=true`, `outcome=error` 및 최초 error를 먼저 저장한다. 새 Task 접수를 중단하고 기존 작업을 취소·관찰한 뒤 `failed/error`로 마감한다. 취소 의도 저장 또는 Task 저장 직후 중단되어도 재기동 시 항목 연결과 미실행 항목 취소를 복구한다. 정리 중 오류가 계속되면 최초 오류와 대기 상태를 보존하며 완료라고 표시하지 않는다.

묶음 검사 Run을 저장한 뒤 계획의 비교 항목 연결 전에 중단된 경우에도 현재 sequence의 고정 접수 키로 연결을 복원한다. 계획 취소는 이 Run의 종료까지 기다리며 동일 비교 요청을 새 키로 접수하지 않는다. 이는 Task 연결 복구와 별개의 저장 경계다.
