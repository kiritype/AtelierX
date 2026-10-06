# 기여 안내

한국어 | [English](CONTRIBUTING.en.md)

AtelierX는 1.0 이전 릴리스(0.x) 단계입니다. 설계 문서는 [docs/](docs/README.md)에 한국어로 있습니다.

## 제보와 작업 흐름

- 오류 제보·기능 제안·질문은 [Discussions](https://github.com/kiritype/AtelierX/discussions)에서 받습니다. Issues는 확인된
  작업 목록입니다(새 이슈 화면은 Discussions로 안내합니다).
- 처리하기로 한 글은 이슈로 옮기고 본문에 `출처: Discussion #n`을 적습니다. 원래 글에는 이슈 번호를 답하고, 릴리스되면 반영된
  버전을 알립니다. 사용법 문제로 끝난 글은 답변으로 마치고 필요하면 설명서를 고칩니다.
- 보안 취약점은 공개 게시판이 아니라 [보안 정책](SECURITY.md)의 비공개 제보로 받습니다.
- 작업은 이슈 하나에 브랜치 하나로 하고, PR 본문에 `Closes #n`을 적습니다. PR은 기본 브랜치가 아닌 `dev`로 합쳐지므로
  이슈가 자동으로 닫히지 않습니다. 합친 뒤 이슈에 반영 내용을 적고 직접 닫습니다.

## 개발 환경

준비물: Python 3.12와 [uv](https://github.com/astral-sh/uv), Node.js 24(npm). Windows에서 개발합니다.

```bash
uv sync
cd web && npm ci && npm run build
```

- 서버 실행: `uv run python -m atelierx --dev --root <시험용 앱 폴더>`. `--root`를 빼면 저장소 자체가 앱 폴더가 되고
  `config/`·`data/`·`state/`·`output/`이 저장소 안에 생깁니다(커밋하지 않음). `--dev`는 기본 포트 8765를 쓰고 Vite 개발
  서버의 출처를 허용합니다.
- 화면 개발: `cd web && npm run dev` 후 `http://localhost:5173`. `/api`는 8765의 서버로 넘어갑니다. 서버만 실행하면
  `web/dist`의 빌드 결과를 보여 줍니다.
- 실제 키·비밀번호를 쓰지 않는 시험용 앱 폴더를 따로 두기를 권합니다. ComfyUI·NovelAI 등 외부 서비스가 필요한 기능은 가짜
  서버로 시험할 수 있게 테스트에 대역이 있습니다(`tests/`).

## 검사

PR은 CI의 `test` 검사를 통과해야 합니다. 같은 내용을 로컬에서 돌립니다.

```bash
uv run pytest -q
cd web && npm test && npm run typecheck && npm run build
```

- Python 코드는 `uv run ruff check`와 `uv run ruff format`을 따릅니다(설정은 `pyproject.toml`).
- 설명서를 고쳤으면 `uv run python tools/build_manual.py dist/manual-check`로 오프라인 설명서의 링크를 확인합니다.
  패키지 빌드도 같은 검사를 하므로 여기서 걸리면 릴리스가 실패합니다.
- 공개 파일 점검: `uv run python tools/audit_public.py`. 일부 자격 증명 패턴과 Git 이력 파일 이름을 점검하며 완전한
  비밀정보 검사는 아닙니다.
- 실제 서비스를 실행하지 않았다면 외부 제공자, ComfyUI, 모델, 학습 도구를 검증했다고 보고하지 마세요.

## 코드 규칙

- **화면 문구(i18n)**: 의미 기반 키를 쓰고 `web/src/locales/ko.json`·`en.json`에 함께 넣습니다. 서버가 사용자에게 보여 줄
  메시지는 `Msg(key, 영어 문장)`으로 만들고, 화면이 키로 번역합니다(키가 없으면 영어 문장을 보여 줌).
- **작업 상태**: 오래 걸리는 작업(LLM, 이미지 대기열, 설치, 학습)은 `core/lifecycle.py`의 공용 상태값(`queued`, `running`,
  `cancelling`, `done`, `failed`, `cancelled`, `interrupted`)을 씁니다.
- **저장 충돌**: 여러 화면이 고치는 JSON은 리비전으로 저장하고, 오래된 내용으로 저장하면 409(`server.save.stale`)로
  거절합니다(`core/revisions.py`).
- **저장하지 않은 변경**: 편집 화면은 `useUnsaved`로 등록해 탭 닫기·나가기·잠금 때 확인을 받습니다.
- **데이터 형식**: 형식은 [docs/data-model.md](docs/data-model.md) 한 곳에서만 정의합니다. 형식을 바꾸면 이 문서와
  `schema_version`을 함께 고치고, 이전 형식을 읽는 변환을 넣습니다.
- **설명서**: 화면 문구나 동작이 바뀌면 `docs/manual/`도 함께 고칩니다. 캡처는 가상 데이터로 찍고, 개인 작품이나 키가
  보이는 화면은 넣지 않습니다. 설명서 안의 링크는 페이지 단위로 겁니다(오프라인 설명서는 제목 앵커가 달라 `#제목` 링크가 깨짐).
- 특정 플랫폼에 종속된 규칙은 문서와 기본 데이터에 넣지 않습니다. 필요하면 플랫폼 프리셋 예시로 다룹니다.

## 설계 문서와 결정

- 기능 설계는 `docs/features/`에 영역별로 씁니다. 형식은 [docs/features/README.md](docs/features/README.md).
- 결정은 [docs/decisions/](docs/decisions/)에 결정 하나당 파일 하나로 기록합니다. 공개된 결정이 바뀌면 기존 기록을 고치지
  않고 "대체함"으로 이어지는 새 기록을 씁니다.

## 커밋과 Pull Request

- 커밋 메시지: `<영역>: <무엇을 왜>` 한 줄, 영어로 씁니다(예: `docs: add chat test design`).
- 한 커밋에는 한 가지 변경만 담습니다. 리팩터링과 동작 변경을 섞지 않습니다.
- 커밋과 PR 메시지에는 변경 내용만 적습니다. 작성 도구 표기, 자동 생성 서명, 공동 작성자 줄은 넣지 않습니다.
- 실행 데이터(`config/`, `state/`, `data/`, `output/`), 개인 메모, 로컬 도구 설정을 커밋하지 않습니다.
- PR에는 무엇을 왜 바꿨는지, 어떻게 확인했는지 적어 주세요. 화면이 바뀌면 캡처를 붙여 주세요.

## 브랜치와 릴리스

이유는 [결정 0020](docs/decisions/0020-branch-flow.md)에 있습니다.

- 작업은 `feat/*`, `fix/*`, `docs/*`, `ci/*` 브랜치에서 합니다. 변경 하나에 브랜치 하나, 작업 폴더도 따로 씁니다
  (`git worktree add ../atelierx-worktrees/<이름> -b feat/<이름> dev`). 동시에 하는 작업끼리 작업 폴더를 같이 쓰지 않습니다.
- PR은 `dev`로 엽니다. `test` 검사를 통과해야 하고 승인은 필수가 아닙니다. 합칠 때는 squash 또는 rebase를 씁니다.
- `staging`과 `main`에는 작업 커밋을 올리지 않습니다. 이미 `test`를 통과한 커밋으로 앞으로 옮기기만 합니다:
  `git push origin <커밋>:staging`, 그다음 `git push origin <커밋>:main`. 옮기는 시점은 관리자가 정합니다.
- `staging`에 push하면 Windows 패키지를 만들어 시험판 `vX.Y.Z-rc.N`으로 올립니다. 후보를 검증하는 동안 `staging`은 움직이지 않습니다.
- 검증이 끝나면 `main`을 후보 커밋으로 옮기고, **Release** 워크플로를 후보 태그로 실행합니다. 후보의 파일을 그대로
  `vX.Y.Z`로 공개합니다.
- 급한 수정: `main`에서 `fix/*` 브랜치를 만들고, 수정 내용을 `main`·`dev`·진행 중인 `staging` 후보에 모두 반영합니다.
  후보가 바뀌면 다시 검증합니다.

## 버전과 마일스톤

이유는 [결정 0022](docs/decisions/0022-versioning.md)에 있습니다.

- 1.0 전에는 새 기능·데이터 형식 변경·결정 기록 변경이 있으면 `0.MINOR.0`, 기존 기능 개선·버그 수정·문서·리팩터링만
  있으면 `0.x.PATCH`를 올립니다.
- 마일스톤은 다음에 낼 버전만 만들고, 그 버전에 넣기로 한 이슈만 답니다. 마일스톤의 이슈가 모두 닫히고 시험판 확인이
  끝나면 정식으로 냅니다.
- 버전은 `pyproject.toml`, `server/atelierx/__init__.py`, `web/package.json`에 함께 적고 잠금 파일(`uv.lock`,
  `web/package-lock.json`)도 갱신합니다. 한 커밋(`build: version X.Y.Z`)으로 올립니다.

## 사용 설명서 빌드

사용자 문서는 `docs/manual/`에서 편집하고, 목차는 `docs/manual/pages.json`입니다. 실제 UI 버튼명, 입력 예시, 성공 상태와
필요한 연결을 함께 설명하세요.

- 웹: `cd docs/manual`, `npm ci`, `npm run build`. 결과는 저장소의 `dist/manual-site/`입니다. 미리보기는 같은 폴더에서
  `npm run preview`.
- 오프라인: 저장소 루트에서 `uv run python tools/build_manual.py`. 같은 Markdown을 `dist/manual/`에 렌더링하며 패키지에
  들어갑니다. `index.html`을 파일로 직접 열어 검색·이동할 수 있습니다.
- `manual-pages.yml`은 `main` 브랜치의 설명서 변경을 [atelierx.cftm.net](https://atelierx.cftm.net/)에 배포하고, PR에서는
  빌드만 합니다. 그래서 `dev`에 합친 설명서 변경은 정식 릴리스와 함께 공개됩니다.

## 라이선스

기여한 내용은 이 저장소와 같은 [MIT 라이선스](LICENSE)로 공개됩니다.
