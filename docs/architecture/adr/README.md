# Architecture Decision Records

개별 ADR은 사용자와 하나씩 논의하고, 확정 직후 저장소 문서에 반영한다. 초기 확정 기준선은 [overview](../overview.md)에 있으며, 이를 임의로 여러 개의 Accepted ADR로 재작성하지 않는다.

## 현재 목록

| ADR | 상태 | 확정일 |
| --- | --- | --- |
| [0001: Contribution 워크플로](0001-contribution-workflow.md) | Proposed — 브랜치 흐름·메시지·기본 브랜치·초기화 확정; 리뷰·보호 유예 | 전체 미확정; 부분 결정 2026-09-11 |

[backlog](backlog.md)는 논의 후보 목록이며 ADR 승인 기록이 아니다. [template](template.md)을 사용해 논의할 ADR의 초안을 작성할 수 있다.

## 기록 규칙

scaffold의 문서 관리 관례로 `NNNN-short-title.md` 형식을 사용한다. 번호는 ADR 초안을 실제로 작성할 때 부여하며 backlog 순서는 승인 순서를 뜻하지 않는다.

| 상태 | 의미 |
| --- | --- |
| Proposed | 논의 중인 초안. 구현 근거로 사용하지 않음 |
| Accepted | 사용자가 명시적으로 확정한 결정 |
| Rejected | 검토 후 채택하지 않은 제안. 사유 보존 |
| Superseded | 후속 Accepted ADR에 의해 대체된 결정. 대체 관계 보존 |

TODO 질문은 backlog에 둔다. Accepted에는 확정일과 결론을 기록한다. 승인되지 않은 세부 사항을 한 ADR에 묶어 승인된 것으로 취급하지 않는다.

## 확정 시 수행할 작업

1. 해당 ADR 파일의 상태, 확정일, 결정 및 영향을 기록한다.
2. [overview](../overview.md)에 현재 결론과 ADR 링크를 반영한다.
3. 기존 ADR과 초기 확정 기준선의 충돌 여부를 확인하고 해당 ADR에 결과를 기록한다.
4. 기존 결정을 대체하면 이전 ADR을 Superseded로 표시하고 양쪽에 `Supersedes` / `Superseded by` 링크를 기록한다. 일부만 바꾸면 대체 범위와 유지되는 결정을 명시한다.
5. 이 목록에 ADR 링크와 상태를 추가하고, backlog 및 관련 요구사항·모듈 문서를 갱신한다.
6. 미결정 사항은 Proposed / TODO로 유지한다. ADR 확정만으로 제품 구현을 시작하지 않는다.

기존 ADR이 없는 초기 기준선을 변경하는 경우에는 어떤 기준선을 변경했는지 기록한다. 존재하지 않는 이전 ADR을 만들어 대체 관계를 꾸미지 않는다.
