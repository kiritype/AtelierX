# 기본 데이터

앱이 데이터 루트를 처음 만들 때 복사해 주는 기본 파일이다. 배포 묶음에서는 `app/defaults/`에 들어간다
([docs/architecture.md](../docs/architecture.md)). 사용자는 복사된 파일을 고쳐 쓰고, 설정 화면에서 기본값으로 되돌릴 수 있다.

| 폴더 | 복사되는 곳 | 내용 |
|---|---|---|
| `guidelines/` | `data/guidelines/` | 정해진 이름의 기본 가이드라인([docs/data-model.md](../docs/data-model.md#정해진-이름)) |
| `image/` | `data/image/` | 기본 이미지 라이브러리(조합 규칙, 표정, 구도) |
| `tags/` | `data/tags/` | 기본 태그 사전(Danbooru 태그 목록). 위치·양식은 [tags/README.md](tags/README.md) |

- 가이드라인은 한국어로 쓴다. LLM에게 주는 지침이라 작품 언어가 달라도 쓸 수 있다.
- 특정 플랫폼을 가정하지 않는다. 플랫폼별 규칙은 플랫폼 프리셋의 가이드라인으로 둔다([docs/platforms.md](../docs/platforms.md)).
