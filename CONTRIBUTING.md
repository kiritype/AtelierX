# 기여 안내

한국어 | [English](CONTRIBUTING.en.md)

AtelierX는 스테이징 단계입니다. 현재 Windows x64 포터블 패키지는 개발 PC에서 실행했고 Ollama Cloud의 모델 목록과
합성 응답·스트리밍을 한 차례 확인했습니다. 깨끗한 Windows 설치, Vertex AI, 실제 이미지 생성은 검증하지 않았습니다.
이슈와 의견을 환영합니다.
설계 문서는 [docs/](docs/README.md)에 한국어로 있습니다.

## 설계 문서

- 데이터 형식은 [docs/data-model.md](docs/data-model.md) 한 곳에서만 정의하고, 기능 문서는 링크로 참조합니다.
- 결정은 [docs/decisions/](docs/decisions/)에 결정 하나당 파일 하나로 기록합니다. 공개된 결정이 바뀌면 기존 기록을 고치지 않고
  "대체함"으로 이어지는 새 기록을 씁니다.
- 특정 플랫폼에 종속된 규칙은 문서와 기본 데이터에 넣지 않습니다. 필요하면 플랫폼 프리셋 예시로 다룹니다.

## 커밋과 Pull Request

- 커밋 메시지: `<영역>: <무엇을 왜>` 한 줄, 영어로 씁니다(예: `docs: add chat test design`).
- 한 커밋에는 한 가지 변경만 담습니다. 리팩터링과 동작 변경을 섞지 않습니다.
- 커밋과 PR 메시지에는 변경 내용만 적습니다. 작성 도구 표기, 자동 생성 서명, 공동 작성자 줄은 넣지 않습니다.
- 실행 데이터(`config/`, `state/`, `data/`, `output/`), 개인 메모, 로컬 도구 설정을 커밋하지 않습니다.
- PR에는 무엇을 왜 바꿨는지, 어떻게 확인했는지 적어 주세요. 화면이 바뀌면 캡처를 붙여 주세요.

코드 변경에 맞는 기존 검사와 코드 규칙을 적용해 주세요. 실제 서비스를 실행하지 않았다면 외부 제공자,
ComfyUI, 모델, 학습 도구를 검증했다고 보고하지 마세요.

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

## 라이선스

기여한 내용은 이 저장소와 같은 [MIT 라이선스](LICENSE)로 공개됩니다.

## 사용 설명서 빌드

사용자 문서는 `docs/manual/index.md`와 `docs/manual/guide/*.md`에서 편집합니다. 실제 UI 버튼명,
입력 예시, 성공 상태와 필요한 연결을 함께 설명하세요. 개인 작품·키가 보이는 캡처는 넣지 않습니다.

- 웹: `cd docs/manual`, `npm ci`, `npm run build`. 결과는 저장소의 `dist/manual-site/`입니다.
- 미리보기: 같은 폴더에서 `npm run preview`.
- 오프라인: 저장소 루트에서 웹 앱 의존성을 설치한 뒤 `python tools/build_manual.py`.
  같은 Markdown을 `dist/manual/`에 렌더링합니다. `index.html`을 파일로 직접 열어 검색·이동할 수 있습니다.
- 공개 파일 점검: `python tools/audit_public.py`. 일부 자격 증명 패턴과 Git 이력 파일명을 점검하며 완전한 비밀정보 검사는 아닙니다.

`manual-pages.yml`은 main 브랜치의 문서 변경을 빌드·배포하며 PR에서는 빌드만 합니다.
GitHub 저장소의 Settings → Pages → Source를 GitHub Actions로 설정해야 합니다.
저장소 이름으로 하위 경로를 계산하며 사용자 사이트는 `/`를 사용합니다. 사용자 도메인을 쓰면 저장소 변수
`DOCS_BASE`를 `/`로 설정하세요. 로컬 하위 경로 검증도 `DOCS_BASE=/저장소이름/` 환경변수로 할 수 있습니다.
원격 저장소가 연결되기 전에는 배포 URL과 Actions 실행 결과가 존재하지 않습니다.
