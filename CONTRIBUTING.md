# AtelierX 기여 안내

현재는 1인 개발이며 아키텍처·요구사항 정리와 사용자 지정 ComfyUI Custom Node 개발을 병행한다. 구현 범위는 [개발 문서](docs/development/README.md)를 따른다. 아래는 [ADR-0001](docs/architecture/adr/0001-contribution-workflow.md)의 확정된 부분만 정리한 Git 운영 기준이다.

## 브랜치와 병합

- GitHub 기본 브랜치와 개발 통합 브랜치는 `develop`이다.
- 릴리즈는 `main`을 기준으로 한다. 릴리즈 트리거와 버전 체계는 별도 결정한다.
- 일반 작업은 develop에서, 릴리즈 긴급 수정은 main에서 `hotfix/*`로 분기한다.

| 흐름 | 병합 방법 |
| --- | --- |
| 일반 작업 → develop | Squash merge |
| develop → main | Merge commit |
| hotfix/* → main | Squash merge |
| main → develop | Merge commit으로 릴리즈 통합·긴급 수정 후 동기화 |

최초 초기화에는 문서 기준선을 main에 직접 push하고 동일 커밋에서 develop을 생성하는 1회 예외를 사용한다. 이후 작업에는 위 분기·병합 흐름을 따른다.

## Commit / PR 메시지

`type(scope): 요약` 형식을 사용한다. type·scope는 영문, 요약·본문은 한국어 기본이며 scope는 생략할 수 있다.

```text
docs(architecture): 서비스 책임 경계 확정
chore(release): develop 변경을 main에 통합
chore(repo): main 변경을 develop에 동기화
```

type은 feat, fix, docs, refactor, perf, test, build, ci, chore, revert를 사용한다. scope는 core, generation, validation, frontend, cli, sdk, schemas, architecture, repo 등을 사용한다.

호환성을 깨는 변경에는 `!`와 `BREAKING CHANGE:` 설명으로 영향·전환 방법을 기록한다. Git이 생성하는 Merge commit 메시지는 형식 적용의 예외다.

PR 제목도 동일한 형식을 사용한다. 본문에는 변경 목적·결과, 관련 ADR·Issue, 검증 결과, 영향을 기록한다. 일반 PR은 하나의 논리적 변경을 다루며 릴리즈 통합 PR은 포함 변경과 통합 검증을 요약한다. 최종 Squash 커밋은 PR 제목과 핵심 본문을 사용한다.

## 리뷰와 보호의 적용 시점

리뷰 기준과 브랜치 보호는 최초 릴리즈 완료 후 검토하며 지금 강제하지 않는다. 1인 개발 상황에 맞춰 재검토하고 자동 활성화하지 않는다. ADR은 사용자가 확정하며, 확정 즉시 저장소 문서에 반영한다.

브랜치 명명·갱신 세부, 기타 GitHub 설정과 CI·Test·Release 정책의 미확정 제안은 [ADR-0001](docs/architecture/adr/0001-contribution-workflow.md) 및 [backlog](docs/architecture/adr/backlog.md)를 확인한다.
