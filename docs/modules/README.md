# 모듈 책임과 상세 문서 안내

이 문서는 논리적인 책임 경계를 기록한다. 실제 소스 디렉터리, 언어, 패키지 이름 및 통신 절차는 결정하지 않는다. 모듈별 상세 문서는 관련 ADR 확정 후 여기에 링크한다.

| 구성 요소 | 책임 | 경계 및 후속 결정 |
| --- | --- | --- |
| Core Backend | SQLite·주요 상태 소유, 도메인 관리, Prompt AI, 설정, Metadata, Import / Export | AI / Agent의 직접 SQL 금지. DB 동시성·권한·Secret은 TODO |
| Generation Backend | ComfyUI Workflow 생성·실행, 생성 설정, LoRA 사용, Upscale·후처리, Job / Progress | SQLite·AI Provider 직접 접근 금지. 결과 등록·파일 전달·Adapter는 TODO |
| Validation Backend | Deterministic 및 AI / VLM 검사 | 특정 모델 종속 금지. Provider abstraction은 Proposed, Schema·Profile·실행 제어는 TODO |
| Frontend | UI, 편집·조회·승인 화면, Job 표시, API 호출, 로컬 UI State | Backend 핵심 규칙을 포함하지 않음. Framework는 TODO |
| CLI | 인자 해석과 Shared API Client 호출 | Backend 비즈니스 로직 중복 금지. 명령어·출력 계약은 미정 |
| Shared API Client / SDK | Frontend·CLI·도구의 REST 호출 지원 | REST API가 canonical contract. 언어·생성 방식은 TODO |
| Shared Schemas / Types | 공용 API 데이터 계약과 타입 공유 영역 | 실제 Schema, 기술 및 동기화 방식은 TODO |
| Documentation | 확정 요구사항, 현재 구조 및 ADR 이력 관리 | 대화에만 결정을 남기지 않음 |

## Frontend에서 수행하지 않는 핵심 처리

- SQLite 직접 접근.
- Prompt 조합 핵심 규칙.
- ComfyUI Workflow 생성.
- AI Provider 직접 호출.
- Validation 판정.
- 파일 저장 경로 핵심 규칙.
- Import / Export 핵심 처리.

이 규칙들은 Backend 책임의 중복을 방지한다. 아직 정하지 않은 Backend 내부 구현이나 서비스 간 조정 책임까지 확정하지 않는다.

## 아직 정하지 않은 교차 모듈 흐름

생성 요청부터 결과 파일 저장, Core Metadata 등록, Validation 실행, 결과 보관까지의 호출 순서와 Job 상태 소유권은 TODO다. 독립 실행과 분산 배치 요구를 만족하도록 ADR에서 논의한다.

[기능 요구사항](../requirements/scope.md) · [아키텍처 개요](../architecture/overview.md) · [ADR backlog](../architecture/adr/backlog.md)
