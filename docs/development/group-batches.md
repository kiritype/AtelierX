# 그룹 생성 일괄 실행 초안 구현 · 2026-09-13

후속 실환경 검증 완료: [2장 생성·단일/묶음 검증·revision 고정·재시작 보고서](group-batches-live-validation.md). 아래 초기 시험의 GPU 미실행 설명은 당시 범위다. VLM 판정 품질 제한은 후속 보고서를 따른다.

`CoreBatches`는 같은 그룹의 구도·표정별 Task 요청을 하나의 durable batch로 고정한다. 각 항목은 접수 시 `Core.preview()`로 만든 snapshot과 Task fingerprint를 저장한다. 이후 설정·검증 등록값이 바뀌거나 Core가 재시작해도 저장한 snapshot과 내부 item key로 같은 Task만 복구한다.

Batch는 기존 Core worker의 generation → single validation → normal automatic regeneration cycle을 관찰한다. 항목별로 final active Task의 단일 통과 이미지, 생성 실패, 취소, 단일 검증 실패를 구분해 요약한다. 일부 실패·취소가 있어도 다른 항목이 끝난 뒤 무한 대기하지 않는다. 기준이 없고 통과 이미지가 0/1장이면 `insufficient_images`로 종료해 후보를 반복 조회하지 않는다. 기존 기준이 있으면 새 통과 target 1장은 기준과 비교할 수 있으므로 정상 group validation을 접수한다.

현재 기준이 있으면 batch가 단일 통과 output만 대상으로 기존 `CoreGroups.submit()`을 한 번 호출한다. 이 호출도 접수 시 고정한 group profile/provider/endpoint를 쓴다. 기준이 없으면 `reference_candidate()` 결과만 `reference_proposal`에 보관하고 `awaiting_reference_confirmation` 또는 `insufficient_images`로 둔다. 기준을 자동 저장·교체하거나 기준 변경만으로 재생성하지 않는다. `POST /v1/group-batches/{id}/confirm-reference`는 `{reference_revision}`과 Idempotency-Key로 사용자가 현재 기준을 명시 확인한 뒤에만 대기 batch를 재개한다. 확인 sequence가 group run key에 들어가므로 이전 run key와 충돌하지 않는다. 실행 중 기준이 바뀌면 `CoreGroups`의 frozen run 이력과 `current_reference=false`가 유지되며 batch가 새 run을 자동 제출하지 않는다.

제안 API는 `POST/GET /v1/groups/{id}/batches`, `GET /v1/group-batches/{id}`, `POST /v1/group-batches/{id}/cancel`이다. 요청은 `{items:[Task 입력에서 group_id를 뺀 항목...],group_validation:{profile_id,provider_id}}`이며 item은 1~32개와 단일 validation을 요구한다. 취소는 각 cycle의 최신 active Task에 `Regeneration.stop()`을 적용해 이후 automatic child 생성을 막고, 이미 접수한 group run에는 협력적 취소를 전달하며, 기존 Task/이미지 이력을 삭제하지 않는다.

Core 통합은 완료했다. `create_app()`이 `core.batches = CoreBatches(core)`와 route 등록을 수행하고 worker는 `await core.groups.tick()` 뒤에 `await core.batches.tick()`을 호출한다. `awaiting_reference_confirmation`은 `confirm-reference` 전에는 tick으로 재개되지 않으며, terminal batch의 cancel은 결과·group run을 바꾸지 않는 no-op이다. Queue 목록 노출은 별도 UI/API 범위다.

`tests/test_core_batches.py`는 SQLite에서 snapshot 고정·같은 키/재시작 중복 방지, partial generation failure/cancel 뒤 통과 이미지 하나만 group request에 넣는 동작, 기준 없는 0/1 통과의 비교 미실행, revision 확인 재개와 key sequence, 최신 cycle 취소, 한 batch ApiError 격리·실패 보존을 검증한다. 실제 GPU·ComfyUI·LM Studio는 호출하지 않았다.
