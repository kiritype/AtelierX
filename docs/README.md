# 문서 목차와 관리 범위

[2026-09-21 구현·미구현 기능 점검](development/implementation-status-2026-09-21.md) · [후속 로드맵 — Discord 자연어 제작 봇 포함](requirements/roadmap.md)

[장기 큐·복구 검증 및 오류 대응](development/production-plan-recovery-tests.md)

[실사용 준비도와 남은 검증](development/practical-readiness.md)

[전역 조각·제작 계획 구현 및 검증](development/global-fragments-production-plans.md) · [관련 API](api/prompt-fragments-production-plans.md)

[현재 REST API 명세](api/rest-api.md): Core·Generation·Validation의 구현된 경로, 입력·응답·오류 및 Negative 출처 계약.

저장소 내부 문서가 AtelierX의 Source of Truth다. 아래 구조는 문서를 탐색하고 결정을 기록하기 위한 scaffold이며 기술 Stack이나 런타임 패키지 디렉터리를 결정하지 않는다.

```text
AGENTS.md
README.md
docs/
├─ README.md
├─ architecture/
│  ├─ overview.md
│  └─ adr/
│     ├─ README.md
│     ├─ template.md
│     └─ backlog.md
├─ requirements/
│  ├─ scope.md
│  ├─ module-feature-comparison.md
│  └─ roadmap.md
├─ modules/
│  └─ README.md
└─ development/
   └─ README.md
```

## 구조 개선 취지

제안된 architecture / requirements / modules / development 구분을 유지한다. 문서 목차를 추가하여 진입점을 제공하고, ADR 목록·템플릿·미결정 목록을 분리하여 아직 논의하지 않은 항목이 승인된 결정처럼 보이지 않도록 한다.

| 문서 | 역할 |
| --- | --- |
| [overview](architecture/overview.md) | 현재 아키텍처 결론과 확정 여부를 빠르게 확인 |
| [ADR](architecture/adr/README.md) | 개별 결정의 배경, 대안, 결과, 변경 이력 기록 |
| [ADR backlog](architecture/adr/backlog.md) | 아직 확정되지 않은 질문과 향후 논의 후보 관리 |
| [요구사항](requirements/scope.md) | 제품이 제공해야 할 기능, 지원 후보, 범위 제외 항목 관리 |
| [모듈별 기능 대조표](requirements/module-feature-comparison.md) | 원문 요구·합의·AI 제안과 기존 문서의 누락·축약을 항목 ID로 검토 |
| [모듈](modules/README.md) | 구성 요소별 책임과 경계 탐색 |
| [후속 확장 로드맵](requirements/roadmap.md) | 현재 범위에서 유예한 기능 관리. 도입 시점·릴리즈는 미정 |
| [개발 문서](development/README.md) | 향후 확정할 개발·검증·배포 정책의 진입점 |
| [Validation 계약 초안](contracts/validation/README.md) | 입력/응답 JSON Schema·예제·상태 전이·복구 검증 자료 |
| [환경 이전·문서 검토 기록](development/handoff-2026-09-12.md) | 2026-09-12 환경 정보, 검토 상태 및 다음 논의·검증 후보 |

상세 모듈 문서는 관련 ADR이 확정될 때 필요한 만큼 추가한다. 빈 기술 설계나 구현 구조를 미리 만들지 않는다.

## 상태 표현

- **확정**: 사용자가 명시적으로 확정한 기준선 또는 Accepted ADR의 결론.
- **Proposed**: 구체적인 대안이나 방향이 제안되었으나 승인되지 않은 상태.
- **TODO**: 논의할 질문만 있고 결론이 없는 상태.
- 요구사항의 **지원 후보 / 검토**는 확정된 지원 보장과 구분한다.

초기 기준선의 출처는 2026-09-11 사용자가 제공한 프로젝트 정의다. 이 내용을 저장소에 옮겨 기록했으며, 과거에 개별 ADR 검토가 있었다고 가정하지 않는다. 문서 구조 정리는 제품 아키텍처의 미정 결정을 승인하는 행위가 아니다.

- [Core REST 구현·실행](development/core-rest.md)
- [보조 노드 실제 설치·실행](development/postprocess-live-validation.md)

- [Backend 생성·검증 통합과 API 설정](development/backend-pipeline-integration.md)
- [이미지 저장 경로](development/output-paths.md)

- [Frontend 기능요구사항 분석](development/frontend-requirements-analysis.md)

- [Frontend 전체 구성과 제작 화면](development/frontend-structure.md)

- [Core 탐색 API 구현·검증](development/core-browse-api.md): 그룹/이미지 목록 및 작업/일괄 작업 필터, 전체 155개 테스트와 HTTP 조회 검증.


## 2026-09-13 Client·CLI 및 화면 상세 후속

[Shared Client·CLI 첫 구현](development/shared-client-cli.md)은 Core 조회 연결 범위와 사용법을 기록한다. [갤러리 상세 초안](development/frontend-gallery-screen.md)과 [작업 현황 상세 초안](development/frontend-jobs-screen.md)은 사용자 검토용 배치·상태·동작·수용 기준이다. 화면 코드는 아직 구현하지 않았다.


[설정 화면 상세 초안](development/frontend-settings-screen.md): 사용자 요청한 좌측 카테고리·우측 설정, 핵심 섹션과 고급 접기, 저장·revision 충돌·동기화 상태를 정리했다. 화면 구현 전 검토용이다.


## 2026-09-13 파일럿 구현 반영

사용자 후속 지시로 네 메뉴의 F/E 파일럿을 구현했다. 앞의 화면 코드 미구현 표기는 [현재 실행·검증 범위](development/frontend-pilot.md)로 갱신한다. 상세 초안 전체가 모두 구현·시험된 것은 아니며 JSON 입력과 후속 검증 범위를 보고서에 구분했다.
