# 문서 목차

저장소 내부 문서가 AtelierX의 Source of Truth다. 이 목차에는 현재 유효한 문서만 둔다. 날짜별 작업 이력은 로컬 전용 `docs/history/`(Git 제외)에 있으며 필요할 때만 참조한다.

| 영역 | 문서 | 역할 |
| --- | --- | --- |
| 정책 | [현행 정책](policies.md) | 사용자가 확정한 작업 방식·제품 결정의 현재 유효본 |
| 아키텍처 | [overview](architecture/overview.md) | 현재 아키텍처 결론과 확정 여부 |
| | [ADR](architecture/adr/README.md) · [backlog](architecture/adr/backlog.md) · [template](architecture/adr/template.md) | 개별 결정 기록, 미결정 질문 |
| 요구사항 | [scope](requirements/scope.md) | 제공 기능·지원 후보·범위 제외 |
| | [roadmap](requirements/roadmap.md) | 후속 확장과 최신 진행 결정 |
| | [모듈별 기능 대조표](requirements/module-feature-comparison.md) | 원문 요구와 문서의 누락·축약 검토 |
| 모듈 | [모듈 책임](modules/README.md) | 구성 요소별 책임과 경계 |
| | [Core·Generation](modules/core-generation.md) · [Validation](modules/validation.md) · [Frontend](modules/frontend.md) · [Custom Node](modules/custom-nodes-design.md) | 모듈별 현행 사양 |
| API | [REST API](api/rest-api.md) · [전역 조각·제작 계획 API](api/prompt-fragments-production-plans.md) | 구현된 경로·입력·응답·오류 계약 |
| 계약 초안 | [Validation 계약 초안](contracts/validation/README.md) | 구현 전 작성된 Schema·예제(현행 구현과 차이 있음) |
| 개발·운영 | [개발 문서](development/README.md) | 현재 상태, 실행·운영, Discord, CLI, 저장 경로, Preset, 테스트 실행 |

## 상태 표현

- **확정**: 사용자가 명시적으로 확정한 기준선 또는 Accepted ADR의 결론.
- **Proposed**: 구체적인 대안이나 방향이 제안되었으나 승인되지 않은 상태.
- **TODO**: 논의할 질문만 있고 결론이 없는 상태.
- 요구사항의 **지원 후보 / 검토**는 확정된 지원 보장과 구분한다.
- 모듈 사양의 **[확정] / [구현] / [제한]**은 사용자 확정, 현재 코드 동작, 미구현·미검증·알려진 한계를 뜻한다.

초기 기준선의 출처는 2026-09-11 사용자가 제공한 프로젝트 정의다. 문서 구조 정리는 제품 아키텍처의 미정 결정을 승인하는 행위가 아니다.
