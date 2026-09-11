# 모듈 책임과 상세 문서 안내

이 문서는 논리적인 책임 경계를 기록한다. 실제 소스 디렉터리, 언어, 패키지 이름 및 통신 절차는 결정하지 않는다. 모듈별 상세 문서는 관련 ADR 확정 후 여기에 링크한다.

현재 [모듈별 기능 대조표](../requirements/module-feature-comparison.md)로 원문 요구와 기존 문서의 누락·축약을 검토한다. Custom Node와 Generation Backend를 별도로 분류하며, 모델·파일 관리의 미정 책임을 임의로 배정하지 않는다. 이 대조표는 확정 명세가 아니다.

| 구성 요소 | 책임 | 경계 및 후속 결정 |
| --- | --- | --- |
| Core Backend | SQLite·주요 상태 소유, 도메인 관리, Prompt AI, 설정, Metadata, Import / Export, Context와 생성·검증·재생성 작업 조정 | AI / Agent의 직접 SQL 금지. DB 동시성·권한·Secret은 TODO |
| Generation Backend | Node별 REST, 전체·단독 Workflow 실행, 고정 입력 적용, FIFO Queue·Node 상태·REST 페이지 조회·SSE 변경 알림, 결과 파일 보관·오류 제공 | SQLite·AI Provider 직접 접근 금지. 오류별 복구 판단은 후속 Validation 설계. 파일 전달·Metadata 계약은 TODO |
| ComfyUI Custom Nodes | 생성 파라미터 입력·이미지 출력, Upscale·Detailer·Censor·배경 Alpha·선택적 WebP | [ADR-0002](../architecture/adr/0002-custom-node-functional-scope.md)의 N-01~N-10 확정. 생성 계열별 분리 및 후처리 개별·통합 구성 허용. 저장 형식·Node 구조 미정 |
| Validation Backend | Deterministic 및 AI / VLM 검사, 재생성 여부·시도별 설정 변경값 반환 | 특정 모델 종속 금지. Provider abstraction은 Proposed, Schema·Profile·실행 제어는 TODO |
| Frontend | UI, 편집·조회·승인 화면, Job 표시, API 호출, 로컬 UI State | Backend 핵심 규칙을 포함하지 않음. Framework는 TODO |
| CLI | 인자 해석과 Shared API Client 호출 | Backend 비즈니스 로직 중복 금지. 명령어·출력 계약은 미정 |
| Shared API Client / SDK | Frontend·CLI·도구의 REST 호출 지원 | REST API가 canonical contract. 언어·생성 방식은 TODO |
| Shared Schemas / Types | 공용 API 데이터 계약과 타입 공유 영역 | 실제 Schema, 기술 및 동기화 방식은 TODO |
| Documentation | 확정 요구사항, 현재 구조 및 ADR 이력 관리 | 대화에만 결정을 남기지 않음 |

## Frontend에서 수행하지 않는 핵심 처리

Encode / Save는 생성·Upscale과 별도 기능·Node로 분리하고 Frontend는 WebP On / Off와 품질 설정을 제공한다. Upscale 설정은 모델과 최종 배율로 제한한다. Generation의 현재 목표에는 캐릭터 일관성 확보가 포함되며 구체 기법은 미정이다. Inpaint·ControlNet과 추가 보정은 [후속 로드맵](../requirements/roadmap.md)을 따른다. 공통 Adapter / Capability 구조는 별도 생성 Node의 필수 전제가 아니다.

- SQLite 직접 접근.
- Prompt 조합 핵심 규칙.
- ComfyUI Workflow 생성.
- AI Provider 직접 호출.
- Validation 판정.
- 파일 저장 경로 핵심 규칙.
- Import / Export 핵심 처리.

이 규칙들은 Backend 책임의 중복을 방지한다. 아직 정하지 않은 Backend 내부 구현이나 서비스 간 조정 책임까지 확정하지 않는다.

## 아직 정하지 않은 교차 모듈 흐름

생성 Node 및 후처리 Node / Workflow의 설정 Preset Load / Save는 [ADR-0002](../architecture/adr/0002-custom-node-functional-scope.md)에서 확정했다. 생성은 Anima / SDXL 전환 시 설정 혼합을 방지해야 한다. 이 요구를 구현할 Node·Core·Generation 간 저장·불러오기 계약과 Preset 단위는 미정이며, Generation의 직접 SQLite 접근을 허용하지 않는다.

[ADR-0003](../architecture/adr/0003-generation-execution-and-queue.md)에 따라 Core가 Context와 전체 작업 흐름·재생성 상한을 관리한다. Generation은 실행·Queue와 결과 파일 보관, Validation은 검증·재생성 여부·변경값 반환을 담당한다. 상세 API, Queue 기록 저장, 파일 전달·Core Metadata 등록 및 Validation 오류 정책은 미정이다.

[기능 요구사항](../requirements/scope.md) · [아키텍처 개요](../architecture/overview.md) · [ADR backlog](../architecture/adr/backlog.md)
