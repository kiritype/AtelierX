# ADR-0001: Contribution 워크플로

- 상태: Proposed
- 작성일: 2026-09-11
- 확정일: 미확정
- 부분 결정 기록일: 2026-09-11 — develop 분리, main 릴리즈, 작업 분기 및 네 가지 병합 흐름 확정
- Supersedes: 없음
- Superseded by: 없음
- 관련 문서: [overview](../overview.md), [개발 문서](../../development/README.md), [backlog](backlog.md)

## 결정할 질문

AtelierX Monorepo에 변경을 기여할 때 사용할 브랜치 구조, Commit / PR 메시지, 리뷰 및 브랜치 간 병합 기준을 결정한다. 아래 확정된 부분 결정 외의 내용은 제안이다. ADR 전체는 나머지 기준을 논의할 때까지 Proposed로 유지한다.

## 확정된 부분 결정

2026-09-11 사용자가 다음을 확정했다.

- `develop`을 별도 개발 통합 브랜치로 운영한다.
- `main`에서 AtelierX를 릴리즈한다.
- 일반 작업은 develop에서 분기하고, 릴리즈 긴급 수정은 main에서 hotfix/*로 분기한다.
- 일반 작업 브랜치 → develop: Squash merge.
- develop → main: Merge commit.
- hotfix/* → main: Squash merge.
- main → develop: Merge commit으로 릴리즈 통합·긴급 수정 후 동기화한다.
- 현재는 1인 개발이다. 리뷰 기준과 브랜치 보호는 바로 적용하지 않고 최초 릴리즈 완료 후 도입을 검토한다.
- Commit / PR 메시지는 Conventional Commits 형식, 영문 type·scope, 한국어 요약·본문을 기본으로 확정한다.
- GitHub 기본 브랜치는 develop으로 설정한다.
- 최초 문서 기준선을 main에 1회 직접 push하고 동일 커밋에서 develop을 생성한다. 사용자가 이 초기 구성을 실행하도록 승인했다.

### 적용 시점 — 현재와 최초 릴리즈 이후

현재는 필수 리뷰 승인, 리뷰 게이트 및 GitHub 브랜치 보호를 설정하지 않는다. 아래 리뷰·보호 제안은 최초 릴리즈 이후 재검토할 후보로 보존한다. 릴리즈 완료만으로 자동 활성화하지 않으며, 당시에도 1인 개발이면 타인 승인을 요구하지 않는 구성을 우선 검토한다.

이미 확정된 브랜치 역할·분기·병합 방식 및 ADR 문서화 원칙은 유지한다. 보호 유예가 이 결정을 취소하거나 main 직접 작업을 새로 승인하는 것은 아니다. Commit / PR 메시지는 별도 합의로 확정했다. 기타 Repository 설정은 아직 제안이다.

이 결정은 main 병합마다 자동 릴리즈한다는 의미가 아니다. 리뷰·보호 규칙, 작업 브랜치 갱신 방식, 릴리즈 트리거·태그·버전 정책 및 release 브랜치 필요 여부는 미확정이다.

## 배경과 확정된 제약

- 단일 GitHub Monorepo에서 서비스와 문서를 함께 관리한다.
- 현재는 설계 단계이며 제품 구현은 시작하지 않는다.
- 설계는 사용자와 ADR을 하나씩 논의하고 확정 직후 문서에 반영한다.
- 프로젝트 전체 버전 릴리즈와 서비스·CLI 독립 패키징 가능성은 확정되어 있다. 릴리즈 주기와 버전 체계는 미정이다.
- 사용자가 지정한 원격 주소는 `https://github.com/kiritype/AtelierX.git`이다.
- 현재 1인 개발이다. 외부 기여 빈도와 복수 유지보수 버전의 필요성은 아직 확인되지 않았다.

## 검토한 대안

| 대안 | 구조 | 장점 | 비용 / 제약 |
| --- | --- | --- | --- |
| A — 미채택 | main + 짧은 작업 브랜치 | 문서·기능 단위 PR과 단일 통합 이력 관리가 단순함 | main에 통합되는 변경의 완결성을 PR에서 확인해야 함 |
| B — main / develop 분리 채택 | main + develop + 작업 브랜치 | 개발 통합 상태와 릴리즈 기준 상태를 분리 가능 | develop → main 및 역방향 동기화 규칙과 추가 병합 관리 필요 |
| C | main 직접 커밋 중심 | 초기 개인 작업의 절차가 적음 | 변경 검토와 ADR·PR 추적이 약해짐 |

사용자가 B의 main / develop 분리와 위의 분기·병합 흐름을 선택했다. 아래에서는 확정 내용과 나머지 제안을 구분한다.

## 작업 브랜치 — 분기 기준 확정, 명명·관리 세부는 제안

- 일반 작업 브랜치는 최신 develop에서 분기하며 하나의 논리적 변경 또는 하나의 ADR을 다룬다.
- 이름은 `<type>/<short-kebab-case-description>`으로 하고 영문 소문자와 하이픈을 사용한다. Issue가 있으면 `<type>/<issue-number>-<description>`을 사용할 수 있으나 Issue 생성을 필수로 하지 않는다.
- type 후보: `docs`, `feat`, `fix`, `refactor`, `test`, `build`, `ci`, `chore`, `perf`, `revert`.
- 예: `docs/adr-0001-contribution-workflow`, `fix/123-generation-progress`.
- 서비스별 영구 브랜치는 만들지 않는다. 같은 정책을 모든 모듈에 적용한다.
- Squash 병합이 끝난 작업 브랜치는 삭제하고 다음 일반 작업은 최신 develop에서 새로 분기한다.
- 릴리즈된 내용의 긴급 수정은 main에서 `hotfix/*`로 분기한다. 일반 버그 수정은 develop에서 `fix/*`로 분기한다. release 브랜치 도입과 과거 릴리즈 지원은 별도 논의한다.

## 확정 — 브랜치별 병합 방법

| 출발 → 대상 | 방법 | 기준 |
| --- | --- | --- |
| docs/*, feat/*, fix/* 등 → develop | Squash merge | PR 하나를 하나의 논리적 변경으로 기록 |
| develop → main | Merge commit | 릴리즈 통합 시 develop 커밋의 연결 관계 보존 |
| hotfix/* → main | Squash merge | 긴급 수정 PR을 하나의 변경으로 기록 |
| main → develop | Merge commit | 릴리즈 통합 또는 긴급 수정 후 이력을 동기화 |

### Proposed — 작업 브랜치 갱신 및 기타 흐름

| 출발 → 대상 | 제안 방법 | 기준 |
| --- | --- | --- |
| develop → 개인 작업 브랜치 | Rebase | 작성자 단독 소유 브랜치의 기준점을 갱신. 이미 게시된 이력을 바꾸면 `--force-with-lease` 사용 |
| develop → 공동 작업 브랜치 | Merge commit | 공동 작업 중인 커밋 이력을 다시 쓰지 않음 |
| 작업 브랜치 → 다른 작업 브랜치 | 기본적으로 사용하지 않음 | 선행 PR 병합 후 최신 develop에서 후속 작업 |
| release/* 관련 | TODO | 해당 브랜치 도입 여부부터 별도 논의 |

최초 릴리즈 이후 보호 후보로 main과 develop에 직접 push, force push 및 삭제를 금지하는 기준을 제안한다. 현재 이를 보호 설정이나 신규 리뷰 게이트로 적용하지 않는다. 작업 브랜치 갱신·Rebase 세부는 계속 Proposed다.

Squash는 PR 중간 커밋을 대상 브랜치에 개별 보존하지 않는다. 통합 이력이 간결해지는 대신 중간 논의·작업 기록은 PR에서 확인하게 된다. GitHub의 Merge commit / Squash / Rebase 동작은 [공식 문서](https://docs.github.com/en/pull-requests/reference/pull-request-merges)를 참고한다.

장기 유지되는 develop → main과 main → develop은 커밋 연결 관계를 보존하도록 Merge commit으로 확정했다.

## 확정 — Commit 메시지

[Conventional Commits 1.0.0](https://www.conventionalcommits.org/en/v1.0.0/) 형식을 사용한다.

```text
<type>(<optional-scope>)!: <summary>

<필요한 경우 변경 이유와 영향>

<필요한 경우 관련 Issue / ADR 및 BREAKING CHANGE 설명>
```

- `!`는 호환성을 깨는 변경에서만 사용한다. scope는 선택이다.
- type: feat, fix, docs, refactor, perf, test, build, ci, chore, revert.
- scope 후보: core, generation, validation, frontend, cli, sdk, schemas, architecture, repo. 여러 영역의 공통 변경은 scope를 생략할 수 있다.
- type·scope는 영문, 요약과 본문은 **한국어 기본**으로 한다. API 식별자·기술 용어는 원문을 유지한다.
- 요약에는 실제 변경을 쓰며 `update`, `fix things`, `작업 중`처럼 내용이 드러나지 않는 표현을 피한다.
- 직접 작성하는 커밋과 최종 Squash 커밋에 적용한다. Git이 생성하는 Merge commit 메시지는 예외로 둔다. 릴리즈 통합 PR 제목과 본문도 아래 PR 기준을 따른다.
- Breaking change는 `!`와 본문의 `BREAKING CHANGE:` 설명으로 영향과 전환 방법을 기록한다.
- 메시지 형식 채택은 SemVer, 자동 버전 증가 또는 자동 릴리즈 도입을 확정하지 않는다.

예:

```text
docs(architecture): contribution 워크플로 초안 추가
docs(architecture): ADR-0001 contribution 워크플로 확정
```

## 확정 — PR 메시지와 크기

- PR 제목은 Commit과 같은 형식을 사용한다. 최종 Squash 커밋 제목은 최종 PR 제목과 일치시키며 GitHub가 붙이는 PR 번호는 허용한다.
- 일반 작업 PR은 독립적으로 검토·되돌릴 수 있는 하나의 논리적 변경을 담는다. 관련 ADR과 overview의 동시 갱신은 같은 PR에 포함한다. develop → main 릴리즈 통합 PR은 여러 변경을 포함할 수 있으며 포함 PR과 통합 검증 결과를 요약한다.
- PR 본문은 최종 변경을 기준으로 갱신하고 아래 정보를 담는다. 단순 문서 변경은 각 항목을 짧게 작성한다.

```text
변경 목적과 결과:
- 어떤 문제를 해결하며 무엇이 달라지는가

관련 결정:
- 관련 ADR / Issue 링크, Proposed 또는 Accepted 여부

검증:
- 수행한 검증과 결과, 미수행 항목 및 이유

영향:
- 호환성·Migration·운영 영향. 해당 없으면 명시
```

Squash 커밋 본문은 PR 본문의 핵심 이유·검증·관련 ADR을 정리한다. 중간 커밋 메시지 전체를 그대로 나열하지 않는다.

릴리즈 통합 PR 제목은 `chore(release): develop 변경을 main에 통합`, 역방향 동기화 PR은 `chore(repo): main 변경을 develop에 동기화` 형태를 사용한다. 버전이 정해진 이후에는 릴리즈 제목에 그 버전을 포함할 수 있다. Merge commit의 자동 생성 메시지는 허용하며 맥락은 PR 본문에 남긴다.

## 유예된 제안 — 최초 릴리즈 이후 리뷰와 병합 권한

이 절의 신규 리뷰 기준은 현재 적용하지 않는다. 사용자의 ADR 확정과 즉시 문서화 원칙은 기존 규칙으로 계속 적용한다.

- maintainer가 최종 병합을 담당한다. Agent의 문서 작성이나 리뷰 결과만으로 ADR을 Accepted로 변경하지 않는다.
- Proposed ADR도 **제안임을 유지한 채** PR로 병합할 수 있다. PR 병합 자체가 아키텍처 승인을 뜻하지 않는다.
- ADR을 Accepted로 바꾸는 PR에는 사용자가 확정한 결론과 날짜를 기록하고 overview 및 관련 문서를 함께 갱신한다.
- 공동 기여에서는 작성자 외 1인의 리뷰 승인을 기준으로 제안한다. 1인 운영에서는 maintainer의 자기 검토·병합을 허용하는 안을 제안한다. 실제 운영 인원에 따라 이 항목은 확정 시 조정한다.
- 해결되지 않은 리뷰 지적, 미확정 결정을 확정으로 표현한 변경, 문서 간 충돌이 있으면 병합하지 않는다.
- 현재 문서 변경은 링크, 범위 누락, 확정 상태, ADR 충돌을 확인한다. 제품 Test 정책과 필수 CI check는 별도 ADR에서 정한다.
- GitHub 보호 규칙과 merge 옵션의 실제 설정은 확정 후 별도로 적용·확인한다. 현재 강제되고 있다고 가정하지 않는다.

### 제안 — 운영 인원에 따른 리뷰 기준

- 1인 운영: PR은 필수, GitHub 필수 승인 수는 0. maintainer가 diff와 검증 결과를 직접 확인하고 병합한다. 자기 검토를 타인의 Approve로 기록하지 않는다.
- 2인 이상 리뷰 가능한 운영: 작성자 외 1인의 Approve를 필수로 설정한다. 변경으로 기존 승인이 오래된 경우 승인을 무효화하고 다시 리뷰한다.
- Agent 리뷰는 보조 검토이며 사람의 최종 검토를 대체하지 않는다. Agent에게 별도 병합 권한을 부여하지 않는다.
- 작성자는 검증 결과를 PR에 남기고, maintainer는 미해결 지적과 ADR 상태를 확인한다. 단순히 스레드를 닫아 미해결 문제를 숨기지 않는다.
- 현재는 1인 개발이다. 최초 릴리즈 이후에도 1인 개발이면 타인 Approve를 필수로 하지 않는 안을 우선 검토하며, 팀 운영으로 바뀐 경우에만 공동 리뷰 기준을 검토한다.

## 유예된 제안 — 최초 릴리즈 이후 GitHub 보호

아래 보호 표는 향후 검토안이다. 최초 릴리즈 완료 후 실제 운영 상황에 맞게 확정하고 설정한다.

| 항목 | main / develop 공통 제안 |
| --- | --- |
| 변경 경로 | PR 필수. 최초 초기화 예외 외 직접 push 금지 |
| Force push / 브랜치 삭제 | 금지 |
| 관리자 우회 | 정상 작업에서 우회 금지. 관리자에게도 보호 적용 |
| 리뷰 스레드 | 병합 전 해결 필수 |
| 필수 승인 수 | 1인 운영 0, 공동 리뷰 운영 1 |
| 오래된 승인 무효화 | 공동 리뷰 운영에서 활성화 |
| Require linear history | 비활성화. 확정된 양방향 Merge commit을 허용해야 함 |
| 필수 CI check | 현재 없음. CI ADR 이후 실제 존재하는 check만 지정 |
| 서명 커밋 / CODEOWNERS 승인 / Merge queue | 현재 필수로 하지 않음. 필요 시 별도 논의 |

## 제안 — 기타 Repository 설정

다음은 리뷰·보호 유예와 별개의 미확정 제안이다. 이번 변경에서는 적용하지 않는다.

- GitHub 기본 브랜치 develop은 별도로 확정했다. 이하 설정은 여전히 제안이다.
- Merge commit과 Squash merge를 허용하고 GitHub의 Rebase merge 옵션은 끈다. 개인 작업 브랜치의 로컬 Rebase 제안과는 별개다.
- 출발·대상 브랜치별 병합 방법은 확정된 표를 따르며 병합자가 확인한다. 두 옵션을 켜는 것만으로 각 흐름의 방법이 자동 강제된다고 가정하지 않는다. 자동 검증은 CI ADR 대상이다.
- 일반 작업 브랜치만 병합 후 삭제한다. main / develop은 유지한다. Repository 전체 자동 삭제는 우선 끄고 작업 브랜치를 선택적으로 삭제한다.
- Auto-merge는 우선 사용하지 않고 maintainer가 최종 병합한다.
- 보호 기능의 실제 적용 가능 여부는 저장소 공개 범위·GitHub 플랜과 권한을 확인한다. 기능이 지원되지 않으면 적용됐다고 기록하지 않고 운영 규칙과 기술적 강제 여부를 구분한다.

근거: [GitHub 보호 브랜치 문서](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches). Linear history 강제는 Merge commit을 차단하므로 현재 확정된 흐름과 함께 켜지 않는다.

## 확정 — 최초 커밋 예외

아직 커밋이 없는 저장소에서는 PR의 기준 브랜치를 먼저 만들어야 한다. 사용자의 실행 요청에 따라 문서 기준선을 최초 커밋으로 main에 1회 push하고 같은 커밋에서 develop을 생성한다. 이후 변경에는 확정된 분기·병합 흐름을 따른다. 최초 커밋에는 확정된 부분을 정리한 CONTRIBUTING.md도 포함한다.

초기화 승인 범위는 최초 문서 커밋, main / develop 생성·push 및 GitHub 기본 브랜치 develop 설정이다. 리뷰·브랜치 보호나 나머지 미정 Repository 설정의 적용은 포함하지 않는다. 실제 설정 완료 여부는 Git 원격 참조와 GitHub 기본 브랜치 조회로 검증한다.

## 이번에 결정하지 않는 사항

CI 도구 및 필수 check, 제품 Test 기준, 릴리즈 주기, Versioning, 과거 버전 유지보수, Packaging, Installer, CODEOWNERS 상세 및 자동화 도구는 별도 ADR 대상이다. Commit 검증 hook이나 PR 자동화는 이번 초안으로 설치하지 않는다.

## 충돌 및 대체 확인

기존 개별 Accepted ADR은 없다. 초기 기준선과 충돌하지 않는다. 이전 A안은 미승인 제안이므로 supersede 대상이 아니다. main / develop 역할, 작업 분기 기준 및 네 가지 병합 흐름 및 Commit / PR 메시지는 확정 내용으로 반영하고 리뷰·보호 및 나머지 세부 기준은 Proposed로 유지한다.

1인 개발 및 리뷰·보호의 최초 릴리즈 이후 유예를 추가 기록했다. 이전 리뷰·보호안은 미승인 제안이었으므로 Accepted ADR을 대체하는 변경은 아니다. 유예 시점은 정했지만 세부 리뷰·보호 규칙은 여전히 미확정이다.

## 문서 반영

- [x] overview에 Proposed 링크 추가
- [x] ADR 목록 및 backlog에 논의 상태 반영
- [x] 개발 문서에 논의용 초안 연결
- [x] 기존 ADR 및 기준선 충돌 확인
- [x] 미결정 사항과 제안 분리

확정된 부분은 [CONTRIBUTING.md](../../../CONTRIBUTING.md)에 정리하고 AGENTS.md에서 연결했다. 남은 세부 정책은 계속 Proposed로 관리하며 초안만으로 시행하지 않는다.
