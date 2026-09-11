# 개발 문서 진입점

현재는 설계 및 기능 요구사항 확정 단계다. 제품 코드, 의존성 설치, 실행용 scaffold 및 CI를 추가하지 않는다.

현재 적용되는 문서 작업 규칙은 [AGENTS.md](../../AGENTS.md)와 [ADR 절차](../architecture/adr/README.md)를 따른다.

현재 [ADR-0001: Contribution 워크플로](../architecture/adr/0001-contribution-workflow.md)를 Proposed 상태로 논의 중이다. **develop 분리, main 릴리즈 및 주요 분기·병합 흐름은 확정**했다. 일반 작업 → develop / hotfix → main은 Squash merge, develop ↔ main은 Merge commit이다. Commit / PR 메시지는 영문 type·scope와 한국어 요약·본문의 `type(scope): 요약` 형식으로 확정했다. 리뷰·보호 및 작업 브랜치 관리 세부는 아직 미확정이다. 확정된 부분의 운영 기준은 CONTRIBUTING.md에 정리했다.

## 후속 ADR 대상

GitHub 기본 브랜치 develop 및 최초 main 커밋과 동일 커밋의 develop 생성은 확정했다. 확정 운영 기준은 [CONTRIBUTING.md](../../CONTRIBUTING.md)에 정리했다. 나머지 제안은 ADR에서 별도 관리한다.

현재 1인 개발을 전제로 한다. 리뷰 기준과 브랜치 보호는 **최초 릴리즈 완료 후 도입을 검토**하며 지금 적용하지 않는다. 해당 시점에도 1인 개발이면 타인 승인 요구 없이 운영 가능한 구성을 검토한다. 이미 확정된 브랜치·병합 흐름과 ADR 문서화 규칙은 유지한다.

- Backend Stack 및 Frontend Framework.
- Branch / Commit 정책.
- CI / Test 정책.
- Release / Versioning.
- Packaging / Installer.
- Migration / Backup.
- Logging / Audit.

단일 GitHub Monorepo, AtelierX 전체 버전 기준 릴리즈, 각 서비스 및 CLI의 독립 패키징 가능성은 확정된 제약이다. 버전 체계, 도구 및 실행 절차는 미정이다.

각 정책이 확정되면 이 디렉터리에 해당 안내를 작성하고 ADR을 연결한다. 아직 확정되지 않은 설정이나 명령어를 사용 가능한 절차처럼 제공하지 않는다.
