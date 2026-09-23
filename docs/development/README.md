# 개발 문서 진입점

현재 유효한 개발·운영 문서만 둔다. 날짜별 구현·검증 기록은 로컬 전용 `docs/history/`(Git 제외)에 있다.

| 문서 | 내용 |
| --- | --- |
| [현재 상태와 남은 작업](status.md) | 구현·확인·미검증 구분, 남은 작업 ID(F/R/Q/O)와 순서 |
| [로컬 실행·운영](operations.md) | 비공개 로컬 파일, 포트, 실행·종료, 로그, Cloudflare Tunnel·Access 구성 |
| [Discord 봇](discord.md) | 명령·권한·흐름·멱등성·설정 절차·알려진 한계 |
| [Shared Client·CLI](shared-client-cli.md) | Python Client와 CLI 사용법 |
| [이미지 저장 경로](output-paths.md) | 생성·후처리 결과 파일 위치 |
| [Preset](presets.md) | 생성·후처리 Preset 저장·적용 규칙 |

모듈별 현행 사양은 [모듈 문서](../modules/README.md), 경로·필드 계약은 [REST API](../api/rest-api.md)를 따른다. Git 운영은 [CONTRIBUTING](../../CONTRIBUTING.md)을 따른다.

## 테스트 실행

```powershell
.venv\Scripts\python.exe -B scripts\run_test_suite.py --phase cpu --output artifacts\<폴더>
node --test (Get-ChildItem tests -Filter *.mjs).FullName
cd integrations\discord-worker; npm test
```

- `--phase generation|vision`은 실제 ComfyUI·LM Studio를 사용한다. ComfyUI 큐가 비어 있고 LM Studio가 idle일 때만 실행하며, 임시 포트와 별도 data-dir을 사용해 파일럿 DB·서비스를 건드리지 않는다. GPU 메모리 전환은 자동으로 하지 않는다.
- 실제 REST 시험 스크립트(`scripts/test_*_rest.py` 등)의 원칙과 옵션은 [Core·Generation 현행 사양](../modules/core-generation.md)의 복구·운영 절차를 따른다.

## 확정된 제약과 후속 ADR 대상

- 확정: 단일 GitHub Monorepo, AtelierX 전체 버전 기준 릴리즈, 각 서비스와 CLI의 독립 패키징 가능성. 버전 체계·도구·실행 절차는 미정이다.
- 후속 ADR 대상: Backend Stack 및 Frontend Framework, CI / Test 정책, Release / Versioning, Packaging / Installer, Migration / Backup, Logging / Audit.
- 정책이 확정되면 이 디렉터리에 안내를 작성하고 ADR을 연결한다. 확정되지 않은 설정·명령을 사용 가능한 절차처럼 제공하지 않는다.
