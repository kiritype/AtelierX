# ADR-0015: Validation Provider 설정·지원 기능·Fallback

- 상태: Accepted
- 작성일 / 확정일: 2026-09-13
- Supersedes / Superseded by: 없음
- 관련: [ADR-0006](0006-validation-manual-retry.md), [ADR-0011](0011-validation-input-context.md), [ADR-0014](0014-validation-checks-and-profiles.md)

## 결정

| 항목 | 확정 기준 |
| --- | --- |
| 등록 | Local VLM·외부 AI Provider 복수 등록 |
| 기본 설정 | 이름·종류·Endpoint·모델·인증 정보·Timeout 관리 |
| 책임 | Core가 설정 관리, Validation이 연동·실행. API Key는 결과·로그에 노출하지 않음 |
| 검사별 선택 | 단일·묶음 검증에 서로 다른 Provider 지정 가능 |
| 설정 고정 | 요청 시 Provider·모델·설정 고정, 변경은 새 요청부터 적용 |
| 연결 확인 | 연결·모델 사용 가능 여부 확인 기능 제공. 검사 정확도 보장과 구분 |
| 이미지 지원 | 이미지 입력을 지원하는 모델만 사용 |
| 묶음 지원 | 여러 이미지 비교 가능한 Provider 사용. 미지원 시 요청 전 안내·실행하지 않음 |
| 구조화 응답 | 지원하면 활용. 미지원이면 정해진 응답 형식으로 요청하고 Validation에서 파싱·검사 |
| 정규화 | Provider별 응답을 공통 결과로 변환. Client의 Provider 원문 해석 없음 |
| 설정 차이 | Temperature·출력 토큰 제한 등 지원하는 항목만 적용. 미지원 설정을 조용히 무시하지 않음 |
| 입력 한도 | Provider 이미지 수·해상도·요청 크기 초과 시 사전 오류. 임의 제외·축소 없음 |
| 오류 | 인증·Timeout·거절·파싱 실패를 공통 코드로 반환. 자동 검증 재시도 금지 유지 |
| 자동 Fallback | 초기 사용하지 않음. Local 실패 후 외부 API 자동 호출 없음 |
| 수동 변경 | 오류 이후 사용자가 Provider를 변경해 같은 이미지 재검증 가능 |
| 외부 전송 | 사용자가 선택한 외부 Provider에 필요한 이미지·Context만 전달. 수동 재검증에도 동일 적용 |
| 이력 | 실제 Provider·모델·검사 설정을 결과 이력에 연결 |

Provider 지원 기능 확인 방법·변환 구현은 Validation 내부 책임이다. 등록 가능한 Provider 종류와 특정 제품/모델의 실제 지원 완료는 구분한다. 이번 결정으로 외부 계정 연동·유료 호출·API Key 설치를 실행하지 않는다.

## 테스트와 조정

사용자는 권고안을 현재 기준으로 채택하고 이후 테스트로 조정하기로 했다. 위 표는 현재 확정 기준이다. 테스트에서는 단일/묶음 기능 지원·형식 파싱·오류 분류·입력 한도·설정 적용과 실제 판정 품질을 구분해 확인한다.

조정 기록에는 테스트 환경·Provider/모델·적용 설정·관찰 결과·변경 이유·이전/새 기준과 기존 이력에 미치는 영향을 남긴다. Timeout 등 미정 수치는 테스트용 값으로 명시하고 제품 기본값과 구분한다. 기존 확정 동작 변경은 ADR 절차로 추적한다. 테스트가 자동 Fallback이나 오류 후 자동 재시도를 임의로 허용하는 근거가 되지 않는다.

## 남은 결정

Provider별 SDK/Adapter·지원 기능 탐지·모델 목록·구체 설정 Schema, Secret 저장/전달·로그 마스킹, Timeout·토큰·동시성 기본값, 입력 한도 확인 시점·변경 대응, Local VLM 런타임·실제 모델·품질 평가 데이터는 후속 설계한다. Queue·GPU 공유는 이번 표에 포함되지 않은 별도 결정이다.

[ADR-0016](0016-validation-execution-and-gpu-sharing.md)에서 Validation 비동기 Job·Provider별 Queue/초기 동시성 1·취소/복구·중복 접수·Core GPU 조정을 확정했다. 위 실행 선택·GPU 조정 미정 범위는 구체 저장/상태/원자성/수치 등으로 한정한다. ADR-0005의 동기 HTTP 예시는 비동기 결과 조회에 그대로 적용하지 않는다.

## 충돌 및 대체 확인

ADR-0001~0014의 Core 설정 소유·Validation AI 책임·최소 Context·요청 고정·오류 후 자동 실행 금지를 유지한다. ADR-0006의 수동 재검증에서 Provider 변경을 구체화하며 기존 결정을 대체하지 않는다. ADR-0005 응답 Schema는 Proposed로 유지한다.

## 문서 반영

- [x] ADR 목록·overview·backlog 갱신
- [x] ADR-0006 후속 연결, 요구사항·모듈·기능 대조표 갱신
- [x] 테스트 조정 이력과 미정 구현/수치 구분
- [x] 기존 ADR 상태·충돌·대체 확인
