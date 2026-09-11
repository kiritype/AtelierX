# 문서 목차와 관리 범위

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

상세 모듈 문서는 관련 ADR이 확정될 때 필요한 만큼 추가한다. 빈 기술 설계나 구현 구조를 미리 만들지 않는다.

## 상태 표현

- **확정**: 사용자가 명시적으로 확정한 기준선 또는 Accepted ADR의 결론.
- **Proposed**: 구체적인 대안이나 방향이 제안되었으나 승인되지 않은 상태.
- **TODO**: 논의할 질문만 있고 결론이 없는 상태.
- 요구사항의 **지원 후보 / 검토**는 확정된 지원 보장과 구분한다.

초기 기준선의 출처는 2026-09-11 사용자가 제공한 프로젝트 정의다. 이 내용을 저장소에 옮겨 기록했으며, 과거에 개별 ADR 검토가 있었다고 가정하지 않는다. 문서 구조 정리는 제품 아키텍처의 미정 결정을 승인하는 행위가 아니다.
