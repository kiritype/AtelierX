# 설계 문서

| 문서 | 내용 | 상태 |
|---|---|---|
| [overview.md](overview.md) | 목적, 범위, 하지 않을 것, 용어, 개발 단계 | 초안 |
| [data-model.md](data-model.md) | 데이터 루트, 폴더 구조, 파일 형식, ID 규칙, 내보내기 | 초안 |
| [features/](features/README.md) | 기능 설계 (기능별 문서로 나눔) | 작성 중 |
| [platforms.md](platforms.md) | 플랫폼 프리셋·가이드라인 형식 상세 | 초안 |
| [architecture.md](architecture.md) | 코어/모듈 구조, 기술 선택, 서버 인증, 스탠드얼론·포터블 배포, 이미지 모듈 | 초안 |
| [decisions/](decisions/) | 결정 기록 (한 결정에 한 파일) | 진행 중 |

## 작성 규칙

- 설계 문서는 한국어로 쓴다. 공개 전에 README만 영어·한국어 두 가지로 준비한다.
- 데이터 형식은 [data-model.md](data-model.md) 한 곳에서만 정의하고, 기능 문서는 링크로 참조한다.
- 공개된 결정이 바뀌면 기존 결정 기록을 지우지 않고 새 기록에서 "대체함"으로 이어 쓴다.
- 특정 플랫폼에 종속된 규칙은 문서 본문에 넣지 않는다. 필요하면 플랫폼 프리셋 예시로만 다룬다.

## 사용 설명서

[한국어 사용 설명서](manual/index.md)는 기능별 Markdown으로 관리합니다.
`docs/manual`에서 `npm ci` 후 `npm run build`로 GitHub Pages용 `dist/manual-site/`를 만들고,
저장소 루트의 `python tools/build_manual.py`로 같은 문서의 오프라인판 `dist/manual/`를 만듭니다.
캡처는 `docs/manual/screenshots/`에 둡니다. 배포 설정은 [기여 안내](../CONTRIBUTING.ko.md)를 참고하세요.
