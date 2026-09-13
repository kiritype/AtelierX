# 작업 현황 화면 상세 초안

기록일: 2026-09-13. 이 문서는 [Frontend 전체 구성](frontend-structure.md)의 작업 현황 영역을 현재 Core Task·Batch·Queue/SSE 계약에 맞춰 정리한 **구현 초안**이다. 화면 코드, 새 scheduler API, Node별 퍼센트 진행률을 추가로 결정하지 않는다. 실제 API는 [REST API 명세](../api/rest-api.md), 탐색 목록은 [Core 탐색 API](core-browse-api.md)를 따른다.

## 화면 목적과 기본 배치

작업 현황은 생성 Task, 단일 검증 Run, 묶음 Batch와 묶음 검증 Run을 서로 다른 실행 단위로 보여 준다. 브라우저가 생성→검증→재생성 순서를 조정하거나 완료 상태를 추정하지 않는다. 현재 ComfyUI 내부 Node별 퍼센트·중간 미리보기는 지원하지 않으므로 숫자 진행률 막대를 만들어 표시하지 않는다.

```text
┌──────────────────────────────────────────────────────────────────────────────┐
│ 작업 현황      작업 [전체/진행/완료/실패/취소]   일괄 [전체/진행/완료]        │
├─────────────────────────────┬────────────────────────────────────────────────┤
│ 최근 Task / Batch 목록       │ 선택 상세                                      │
│ [종류] [상태] [그룹] [시각]  │ Task 또는 Batch 상태·오류·고정 입력             │
│ [종류] [상태] [그룹] [시각]  │ 시도 lineage / 자동 cycle / 이미지·검증 연결     │
│ 이전 / 다음                  │ 취소 · 기준 확인 · 갤러리 결과 보기              │
├─────────────────────────────┴────────────────────────────────────────────────┤
│ 실시간 연결: 연결됨 / 재동기화 중 / 재시도 중 · 마지막 목록 갱신 시각         │
└──────────────────────────────────────────────────────────────────────────────┘
```

목록의 Task는 `GET /v1/tasks`로 읽는다. `group_id`, `work_id`, `character_id`, `outfit_id`, `state`, `limit`, `offset` 필터를 지원한다. Batch는 `GET /v1/group-batches`의 `group_id`, `state`, `limit`, `offset`으로 읽는다. 두 목록은 별도 페이지이고 빈 목록은 정상 200 응답일 수 있다. offset 기반 목록은 새 작업이 접수되면 항목이 이동할 수 있다.

## Task와 단일 검증 상세

Task를 선택하면 `GET /v1/tasks/{id}`로 최신 상태, 고정 snapshot, images, 오류와 취소 요청 여부를 읽는다. Task 상세의 이미지 링크는 갤러리 상세로 연결하고, 이미지별 단일 검증은 `GET /v1/images/{image_id}/validations`와 선택 Run의 `GET /v1/validation-runs/{run_id}`로 연다.

상태 표시는 다음처럼 구분한다.

| 구분 | 화면 의미 |
| --- | --- |
| Task 접수·실행 상태 | `queued`, `generation_pending`, `generating`, `generated`, `failed`, `cancelled` 등 Core가 반환한 상태를 그대로 보인다. `cancel_requested=true`는 취소 완료가 아니라 협력적 취소가 진행 중이라는 표시다. |
| 단일 검증 상태 | image의 최신 `single_outcome` 또는 Run state/outcome을 별도로 표시한다. Task가 generated여도 validation은 pending일 수 있다. |
| 접수 오류 | HTTP 400/401/404/409/422는 요청이 접수되지 않았거나 현재 입력이 거절된 경우다. 입력을 유지하고 오류를 해당 동작에 붙인다. |
| 실행 결과 오류 | 이미 접수한 검증 Run의 `outcome=error`, Generation Task의 `error`, group Run의 `outcome=error`는 조회 HTTP 200 안의 결과다. 새 요청을 자동으로 만들지 않고 코드·메시지·기존 이력을 보인다. |

`POST /v1/tasks/{id}/cancel`은 queued Task를 즉시 cancelled로 만들 수 있지만, 실행 중에는 202와 `cancel_requested=true`를 반환할 수 있다. 생성된 결과는 보존하고 대기/실행 중 검증과 후속 흐름만 취소한다. 종료된 상태는 200이다. 사용자가 취소를 여러 번 눌러도 별도 작업을 만들지 않으며, 최종 state가 바뀔 때까지 취소 중으로 표시한다.

## 시도 lineage와 자동 재생성 cycle

Task 상세에서 `GET /v1/tasks/{id}/attempts`를 사용해 같은 lineage의 최초·수동·자동 시도를 시간순으로 표시한다. 각 새 시도는 새 Task와 새 이미지 ID를 가지며 원본 Task·Prompt·카테고리를 수정하지 않는다. 선택된 시도의 `regeneration.cycle_id`가 있으면 `GET /v1/regeneration-cycles/{id}`를 읽어 `enabled`, `limit`, `used`, `active_task_id`, `state`, `reason`을 보인다.

전역 `GET /v1/settings`의 `auto_regeneration_enabled`, `max_auto_regenerations`는 새 최초/수동 흐름에 적용되는 현재 기본 설정이다. 기본 상한은 5회이며 `0` 또는 Off는 자동 재생성을 하지 않는다. 이미 시작한 cycle의 상한은 그 cycle에 고정되어 있으므로 작업 상세는 현재 설정의 5회를 과거 cycle에 소급해 표시하지 않는다. Task 응답의 `automatic_attempts_used`와 cycle의 `used`는 실제 실행이 시작된 자동 시도 수다. 실행 전 취소는 차감하지 않고 실행 후 실패·취소는 차감된 상태로 남는다.

수동 재생성은 횟수 상한이 없다. 사용자가 `POST /v1/tasks/{id}/regenerations`를 요청하면 새 Task와 새 cycle이 생기며 그 새 cycle은 당시 설정으로 자동 상한을 다시 부여받는다. 활성 생성·검증·자동 후속이 있을 때 `CORE_REGENERATION_ACTIVE`(409)이면 화면은 중단/완료 확인을 안내하고 중복 수동 재생성을 접수하지 않는다. cycle을 중지하는 동작은 `POST /v1/regeneration-cycles/{id}/stop`이며, 실행 중 작업의 실제 종료와 별개로 중단 의사를 저장하는 협력적 동작이다.

## Batch와 기준 확인

Batch 목록에서는 `GET /v1/group-batches/{id}`의 고정 `items`, item별 `task_id`/`active_task_id`, state, `passed_image_ids`, summary, `group_run_id`, error를 펼친다. Batch는 한 group의 1..32개 항목이며 각 항목은 단일 validation 선택과 접수 당시 Prompt·생성/후처리·검사·자동 재생성 설정을 고정한다. 화면은 항목별 자동 시도가 새 active Task로 바뀌는 것을 따라 보여 주되, 생성 실패·단일 불합격·취소를 다른 항목까지 실패로 집계하지 않는다.

`awaiting_reference_confirmation`은 오류가 아니라 사용자 확인 경계다. 화면은 Batch가 보관한 candidate/현재 기준 및 `GET /v1/groups/{group_id}/consistency`를 함께 보여 준다. 사용자가 기준을 `PUT /v1/groups/{id}/reference`로 명시적으로 저장한 뒤, 현재 기준 revision을 확인하고 `POST /v1/group-batches/{id}/confirm-reference`에 `{reference_revision}`과 새 `Idempotency-Key`를 보낸다. 기준이 다시 바뀌어 `CORE_GROUP_STALE`(409)이면 Batch를 임의로 재개하지 않고 최신 기준을 다시 읽는다.

Batch 취소는 `POST /v1/group-batches/{id}/cancel`이다. 최신 automatic cycle과 관련 검증에 협력 취소를 요청하며, 실행 중이면 `cancellation_pending`이 될 수 있다. 기준 확인 대기 상태에서도 취소할 수 있고, terminal 상태의 과거 결과는 삭제하지 않는다. Batch의 `group_run_id`가 있으면 `GET /v1/group-validation-runs/{id}`로 묶음 비교의 상태·결과·현재 기준 유효성을 보여 준다.

## Queue와 SSE 재동기화

Core `GET /v1/queue`는 생성 Task·단일 validation Run·group validation Run의 작은 상태 행을 반환한다. 각 행은 `id` 또는 `job_id`, `kind`, `state`, 시간, `outcome`, `cancel_requested`만 포함할 수 있다. 이것은 Task/Batch 상세의 대체물이 아니라 목록 갱신 신호다. 현재 세 서비스는 모두 `/v1/queue`와 `/v1/events`를 제공하지만, 이 화면의 시작 범위는 Core queue와 Core Task/Batch 상세 연결이다. Generation/Validation의 독립 queue 행을 Core의 Task에 확실히 연결하는 추가 UI 계약은 아직 없다.

Core `GET /v1/events` SSE를 구독한다. 최초 연결, 재연결, Last-Event-ID가 있는 재연결 모두 `reset`을 받을 수 있으며 과거 event replay는 없다. `changed`는 변경된 작은 행만, heartbeat는 15초마다 올 수 있다. Core SSE에는 Batch 자체 행이 없으므로 기준 확인 대기처럼 Batch만 바뀌는 상태를 SSE만으로 항상 감지한다고 가정하지 않는다. 따라서 화면이 활성인 동안 현재 목록과 선택 Batch 상세를 초안 기준 5초 간격으로 읽고, 수동 새로고침도 제공한다. 같은 목록·상세 요청이 아직 진행 중이면 다음 poll을 시작하지 않으며, 화면이 숨겨지면 poll을 중지한다. 요청 실패 시 간격을 늘려 재시도하고 다음 성공 뒤 기본 간격으로 되돌린다. 따라서 화면은 다음 규칙을 사용한다.

1. `reset`을 받으면 현재 필터의 `GET /v1/tasks`, `GET /v1/group-batches`, 선택된 Task/Batch 상세, 필요한 `/v1/queue`를 다시 읽는다.
2. `changed`는 보이는 행의 상태 힌트만 갱신하고, 선택 상세·목록 필터의 실제 데이터는 해당 REST 조회로 다시 확인한다.
3. 연결 오류나 heartbeat 지연은 "실시간 연결 재시도 중"으로 표시한다. 이전 상태를 완료라고 단정하거나 임의로 취소 처리하지 않는다.
4. Batch만 바뀔 수 있는 상태는 활성 화면 poll 또는 수동 새로고침으로 `GET /v1/group-batches`와 선택 `GET /v1/group-batches/{id}`를 갱신한다. SSE changed만으로 Batch summary를 재구성하지 않는다.

## 수용 시나리오

- `state=failed` Task와 `outcome=error` Validation Run은 각각 실행 상태와 결과 오류로 분리돼 보인다.
- Task가 generated이고 validation pending이면 생성 완료와 검증 진행 중을 동시에 표시한다.
- 자동 cycle의 used=2, limit=5를 볼 때 현재 전역 상한을 3으로 바꿔도 이미 시작한 cycle이 3으로 줄었다고 표시하지 않는다.
- 수동 재생성 버튼은 automatic limit 도달 뒤에도 열려 있으며, 기존 자동 시도 수에 더하지 않는다.
- Batch의 기준 변경 대기에서 후보 조회나 기준 PUT만으로 재개하지 않고 confirm-reference 성공 후에만 재개 상태를 표시한다.
- SSE reset 뒤에는 화면의 현재 필터와 선택 상세를 다시 읽는다. changed payload만으로 Task snapshot이나 Batch summary를 재구성하지 않는다.
- 기준 확인 대기 Batch는 Core SSE에 Batch 행이 없어도, 활성 화면의 중복 없는 5초 poll 또는 수동 새로고침으로 최신 `awaiting_reference_confirmation`/취소/완료 상태를 확인한다. 숨김 화면은 poll하지 않고 다음 활성화 때 다시 읽는다.
- 취소 요청 뒤 늦은 결과가 도착해도 서버가 반환한 terminal state와 이력을 표시하며 브라우저가 결과를 삭제하거나 새 실행을 만들지 않는다.

## 현재 API 밖의 항목

세 service queue를 하나의 사용자용 scheduler 화면으로 병합하는 계약, ComfyUI 내부 Node별 퍼센트/미리보기, Batch 항목의 드래그 재정렬, 완료 작업 삭제·보관, 브라우저 종료 후 SSE cursor 보존은 현재 구현 범위에 없다. 이 초안은 그런 API·정책을 승인하거나 화면 구현이 끝났다고 주장하지 않는다.
