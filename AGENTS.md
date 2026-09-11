# AtelierX 작업 규칙

## 현재 단계

- 아키텍처 및 기능 요구사항 확정 단계다. 명시적인 후속 구현 지시 전에는 제품 코드, 실행 환경, 의존성 및 CI를 추가하지 않는다.
- 미확정 내용을 임의로 결정하지 않는다. 대안과 권고는 확정된 결정과 구분하여 제시한다.
- ADR은 사용자와 하나씩 논의한다. 사용자가 확정하기 전에는 Accepted로 기록하지 않는다.
- 대화만으로 결정을 보관하지 않는다. 확정된 결정은 즉시 저장소 문서에 반영한다.
- 현재 1인 개발이다. 리뷰 기준과 브랜치 보호는 최초 릴리즈 이후 검토하도록 유예했으므로 지금 강제하거나 설정하지 않는다. 상세 상태는 [ADR-0001](docs/architecture/adr/0001-contribution-workflow.md)을 확인한다.

## 응답 방식

- 최종 응답에는 현재 상태에 맞는 다음 진행 작업 제안을 함께 제공한다.
- 항목 검토 시 설계상 문제가 있는 부분만 지적하고, 문제가 없으면 합의 상태와 필요한 결정만 간결히 답한다. 이미 확정된 내용을 반복 설명하지 않는다. 사용자가 상세 설명을 요청하면 필요한 범위로 설명한다.
- 다음 작업 제안은 미확정 결정의 승인이나 실행 지시로 간주하지 않는다. ADR은 계속 하나씩 논의한다.

## 필수 탐색

Git 작업과 메시지 작성에는 [CONTRIBUTING.md](CONTRIBUTING.md)의 확정 기준을 따른다. 미정 제안을 운영 규칙으로 취급하지 않는다.

작업 전에 [문서 목차](docs/README.md), [아키텍처 개요](docs/architecture/overview.md), [ADR 목록 및 절차](docs/architecture/adr/README.md), [미결정 목록](docs/architecture/adr/backlog.md)을 읽는다. 작업에 해당하는 [요구사항](docs/requirements/scope.md)과 [모듈 책임](docs/modules/README.md)도 확인한다.

## 아키텍처 원칙

- 단일 Monorepo 안에서 Core / Generation / Validation을 관리하며 각 서비스는 독립 실행 가능해야 한다.
- REST API가 canonical contract다. 별도 BFF는 두지 않으며 Shared API Client / SDK를 사용한다.
- Frontend와 CLI는 얇은 클라이언트로 유지한다. Backend 비즈니스 로직을 복제하지 않는다.
- Core가 SQLite 및 애플리케이션 주요 상태를 소유한다. 이미지와 대형 모델 파일은 Filesystem에 저장한다.
- Generation의 생성 연동 대상은 ComfyUI다. Generation은 SQLite 및 AI Provider에 직접 접근하지 않는다.
- AI 및 Agent의 Core 작업은 허용된 Core REST API를 통한다. SQLite 또는 임의 SQL 실행 권한을 직접 제공하지 않는다.
- 외부 AI에는 요청 수행에 필요한 최소 Context만 전달한다.

상세 범위, 예외 및 미결정 사항은 아키텍처·요구사항·ADR 문서를 확인한다. 이 파일에 모든 설계를 복제하지 않는다.

## 결정 반영 절차

ADR 확정 시 해당 파일 작성 또는 갱신 → overview 갱신 → 기존 ADR 충돌 확인 → 변경된 기존 ADR 상태와 supersede 관계 기록 → 관련 요구사항·모듈 문서 및 backlog 갱신을 수행한다.

문서끼리 충돌하면 임의로 결론을 선택하지 말고 충돌 지점과 확인이 필요한 결정을 제시한다. 기존 사용자 변경은 보존한다. Branch, Commit, Test, CI 등의 미정 정책을 이미 확정된 규칙처럼 도입하지 않는다.
