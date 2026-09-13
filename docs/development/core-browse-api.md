# Core 탐색 API 구현 및 검증

작성일: 2026-09-13. 사용자 승인한 Frontend 구성 초안에 필요한 조회 API를 Terra 서브에이전트가 구현하고 주 에이전트가 연결·검토·통합 검증했다. Frontend 화면 구현 완료를 의미하지 않는다.

## 구현 범위

- `GET /v1/groups`: 작품/캐릭터/의상 필터, 고정 의상 revision과 구성, 기준 정보, 페이지 및 total.
- `GET /v1/images`: 관계·미디어·단일 검증 outcome·묶음 status 필터, 제한된 이미지 metadata와 인증된 content URL, 페이지 및 total.
- `GET /v1/tasks`: 기존 응답을 유지하며 작품/캐릭터/의상/state 필터 추가.
- `GET /v1/group-batches`: 전체 또는 그룹/state별 일괄 작업 페이지.

모두 기존 Core 인증을 사용하며 조회 중 생성·검증·재생성을 실행하지 않는다. 관계 필터는 그룹에 고정된 ID를 사용하므로 원본 보관 이후에도 과거 결과를 찾을 수 있다. 상세 필드·오류·페이지 규칙은 [REST 명세](../api/rest-api.md)의 Frontend 탐색 절을 따른다.

갤러리는 최신 단일 검증 요청을 우선하므로 재검증 접수 후 과거 cached pass를 현재 합격으로 표시하지 않는다. 묶음 기준 이미지, 현재 판정, 이전 기준 판정(stale), 비대상(not_eligible), 미검증을 구분한다. `group_reference_revision`은 현재 기준 revision이고, 과거 결과는 run ID로 추적한다.

## 검증 결과

- 전체 단위·통합 테스트: **155개 통과**, 19.498초. 명령: `.venv/Scripts/python.exe -B -m unittest discover -s tests -q`.
- 새 catalog 6개와 task/batch query 6개: 필터, 페이지/정렬, 입력 오류, 인증, 읽기 전용 동작, 보관된 분류, 실제 Store의 재검증 접수 및 CoreGroups의 기준 변경 회귀 포함.
- HTTP 시험: `.venv/Scripts/python.exe -B scripts/test_core_browse_rest.py` 통과. 기존 실환경 시험 DB를 SQLite backup으로 복사한 뒤 로컬 Core HTTP 서버를 두 번 실행했다. 네 목록의 페이지·관계 필터·잘못된 페이지 입력·인증 거부를 확인했다.
- 두 실행 모두 조회 전후 DB 내용이 동일했고, 재시작 전후 페이지 응답과 원본 DB 내용도 동일했다.

실행 산출물: `artifacts/core-browse-rest/20260913-155004/report.json`, `unit-tests.log`. 원본: `artifacts/group-batches-rest/20260913-142529/core.sqlite3`. HTTP 시험에서는 작업 실행기를 대기시켰으며 GPU·VLM·생성·검증 후속 실행은 하지 않았다. 이미지 content 다운로드 시험도 이번 범위에 포함하지 않았다.

## 남은 한계와 다음 작업

갤러리 상태 필터는 SQL로 관계/미디어 후보를 좁힌 뒤 후보의 검증 상태를 계산한다. 그룹별 기존 집계도 호출하므로 대규모 갤러리에서 페이지 크기만큼만 읽는 구현은 아니다. 대량 데이터 성능 측정과 필요 시 조회 최적화가 남아 있다. offset 페이지는 동시 생성 중 snapshot 일관성을 보장하지 않는다. 이미지 `created_at`은 현재 저장 구조상 Task 접수 시각이다.

Shared API Client와 CLI에서 확정 계약을 연결하고, 갤러리·작업 현황 화면의 상태 표시와 복구 흐름을 상세화한다. 일반 이미지 import/삭제, 전문 검색, 모델 관리 등 별도 계약이 필요한 기능은 이 조회 보완으로 구현된 것이 아니다.
