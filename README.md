# AtelierX

ComfyUI를 기반으로 캐릭터 이미지의 생성, 관리, 후처리, 검증 및 Agent 자동화를 지원하는 로컬 중심 이미지 제작 플랫폼.

현재는 **Core·Generation·Validation, Custom Node, CLI 및 Frontend 파일럿을 구현하고 통합·복구 검증을 진행 중**이다. [실사용 준비도](docs/development/status.md)와 [개발 문서](docs/development/README.md)에서 실제 검증 범위와 남은 작업을 확인한다. 프로젝트의 Source of Truth는 저장소 내부 문서이며, 미정 ADR을 구현 선택만으로 확정하지 않는다.

## 시작하기

Git 브랜치와 Commit / PR 기준은 [기여 안내](CONTRIBUTING.md)를 참고한다. 개발 통합·GitHub 기본 브랜치는 develop이며 릴리즈 기준은 main이다.

1. [프로젝트 작업 규칙](AGENTS.md)
2. [아키텍처 개요 및 확정 기준선](docs/architecture/overview.md)
3. [기능 요구사항과 범위](docs/requirements/scope.md)
4. [모듈 책임](docs/modules/README.md)
5. [ADR 진행 규칙](docs/architecture/adr/README.md) 및 [미결정 목록](docs/architecture/adr/backlog.md)

전체 문서 위치와 역할은 [문서 목차](docs/README.md)를 참고한다. 파일럿 실행은 [Frontend 파일럿](docs/modules/frontend.md), 서비스 계약은 [REST API](docs/api/rest-api.md)에 기록한다.

이 저장소의 체크포인트에는 소스·테스트·문서·예제 설정을 보관한다. 실제 모델, `.atelierx/`의 개인 설정·토큰·DB·이미지, `artifacts/`의 로컬 실행 증거는 포함하지 않는다. 다른 환경에서 실행할 때는 모델과 로컬 설정을 별도로 준비해야 하며, 이 Git 체크포인트는 사용자 데이터 백업을 대신하지 않는다.
