# 검사 설정 관리 구현 — 2026-09-13

후속: [실환경 검증 보고서](group-batches-live-validation.md)에서 LM Studio 실제 단일/묶음 실행과 접수 당시 revision 보존을 확인했다. 아래 최초 테스트의 실환경 미실행 설명은 후속 검증으로 보완한다.

Core SQLite에 단일 profile·묶음 profile·Provider의 생성, 조건부 수정, 복제, 보관, 조회, revision 이력을 구현했다. 단일/묶음 profile ID는 공통 namespace에서 유일하다. 보관한 설정은 새 작업에서 선택할 수 없고 기존 Task는 접수 당시 snapshot을 유지한다. 미구현 신체 이상·metadata 검사는 활성화할 수 없다.

Core create_app에 설정 API를 연결했다. 요청 계약은 [REST 명세](../api/rest-api.md)를 참조한다. 저장 요청은 로컬 revision을 먼저 확정하고 Validation에 동기화한다. 응답은 저장 성공 201/200과 synchronization의 state(synced 또는 pending), error를 함께 반환한다. pending은 저장 실패가 아니므로 동일 create를 다시 제출하지 않는다. 관리하는 Provider가 있는 단일/묶음 검증은 실제 접수 직전에 registry를 다시 동기화한다. 동기화 실패 상태로 새 설정의 추론을 진행하지 않는다.

Validation의 RevisionRegistry는 전체 입력을 검사한 뒤 같은 revision의 변경을 거부하고 과거 revision을 보존한다. 비밀정보를 제외한 runtime 설정은 Validation 데이터 디렉터리에 저장하고 worker 시작 전에 복원한다. 기존 축약 설정 파일은 호환 경로를 유지하고 완전한 설정은 SQLite 초기 값으로 가져온다.

API key 원문은 Core 입력·조회·이력 및 registry 파일에 저장하지 않는다. Validation 서버 설정에 등록된 동일 Provider ID와 정확히 같은 URL에 대해서만 서버 key를 사용한다. 모델/timeout revision 변경은 같은 endpoint의 credential을 사용할 수 있지만 URL 변경 시 기존 key를 자동 전송하지 않는다. 새 credential 등록은 기존 Validation 서버 설정의 책임이다. Core의 환경변수 참조 필드만으로 새 비밀키가 실행 서버에 전달되지는 않는다.

GET /v1/validation-settings/providers/{id}/connection은 등록 ID를 확인하고 Validation /health를 조회한다. validation_service_reachable은 Core→Validation 연결 여부만 뜻한다. Provider 모델 존재·vision·묶음 비교 능력·추론 품질을 확인하지 않으며 외부 유료 추론을 실행하지 않는다. 해당 capability 검사는 후속 범위다.

시험은 revision/복제/보관, namespace 충돌, 잘못된 입력, immutable registry 충돌, 비밀정보 없는 저장·재시작 복원, 다른 endpoint에 credential 미전달, REST 저장 성공/동기화 대기 구분을 포함한다. 통합 결과는 [병렬 작업 보고서](parallel-backend-validation.md)에 기록했다. 새 관리 API를 통한 실제 LM Studio 추론은 이번에 실행하지 않았다.
