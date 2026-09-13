# 전역 프롬프트 조각과 제작 계획 API

2026-09-13 구현 계약. 외형은 항상 포함하며 조각에서 상의·하의만 선택한다. 조각은 작품/캐릭터/의상과 독립된 전역 자원이다. 선택한 조각 하나가 이미지 변형 하나이며 본문의 줄바꿈이나 쉼표를 별도 이미지로 분리하지 않는다.

## 프롬프트 조각

- `GET /v1/prompt-fragments`: `archived`, `limit`(최대 200), `offset`으로 조회한다.
- `POST /v1/prompt-fragments`: `{name, body, include: {upper: true, lower: false}}`.
- `GET /v1/prompt-fragments/{id}`: 현재 문서 조회.
- `PATCH /v1/prompt-fragments/{id}`: 현재 `revision`과 변경 필드로 수정·보관 처리.
- `GET /v1/prompt-fragments/{id}/revisions`: 변경 이력 페이지 조회.

이름은 1–200자, 본문은 1–20,000자다. 생성 요청에는 `fragment: {id, revision}`을 지정한다. 조각 모드는 기존 구도·표정·동작·상황·include 직접 입력과 혼용하지 않는다. 최신 활성 revision만 신규 계획에 사용할 수 있으며 이미 저장된 계획의 스냅샷은 수정되지 않는다.

양성 프롬프트는 전역 퀄리티 + 외형 + 조각에서 선택한 상의/하의 + 조각 본문이다. 음성 프롬프트는 기존 전역 네거티브 + 캐릭터 네거티브 정책을 유지한다.

## 제작 계획

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
