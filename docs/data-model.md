# 데이터 구조

모든 데이터 형식은 이 문서에서만 정의한다. 기능 문서는 여기를 참조한다.

## 원칙

- 사람이 읽고 고칠 수 있는 파일로 저장한다: 본문은 Markdown, 구조 데이터는 JSON(UTF-8, 들여쓰기 2칸).
  예외는 인증 정보뿐이며, 금고에 암호화해 둔다([금고](#금고)).
- 파일마다 `schema_version`을 둔다(Markdown·JSX는 메타데이터 머리에). 형식이 바뀌면 변환 도구를 함께 낸다([버전](#버전)).
- **화면의 파일 트리 = 디스크 = 내보내기.** 작품 폴더 안의 폴더 구조와 파일 이름은 사용자가 정하고, 그 이름이 표시 이름이다.
  권장 구성은 배포에 포함하는 샘플 작품으로 보여 준다.
- **항목의 종류는 위치가 아니라 메타데이터로 정한다**([항목](#항목)). 파일을 어느 폴더로 옮겨도 동작이 바뀌지 않는다.
- **참조는 ID로 한다.** 작품과 항목은 바뀌지 않는 ID를 가진다([ID](#id)). 다른 데이터(관계도, 이미지 데이터,
  JSX 예시 props, 출력 경로)는 파일 경로가 아니라 ID로 가리키므로, 파일 이름을 바꾸거나 옮겨도 연결이 유지된다.
- **사용자 파일과 앱 데이터를 나눈다.** 앱이 관리하는 데이터는 작품마다 `.atelierx/` 폴더 하나에 모은다. 그 밖의 작품 폴더는
  모두 사용자의 트리다.
- 같은 사실은 한 곳에만 적는다. 파일·폴더 이름이 곧 식별자인 경우(플랫폼 프리셋, 스냅샷 등) 파일 안에 같은 값을
  다시 적지 않는다.
- 본문에는 플랫폼에 그대로 붙여 넣을 수 있는 내용만 둔다. 앱이 알아야 할 정보는 메타데이터 머리나 `.atelierx/`에 둔다.
- 이 버전이 모르는 필드는 읽고 다시 쓸 때 지우지 않는다.
- 파생 데이터(캐시, 색인, 토큰 수)는 지워도 다시 만들 수 있는 곳에만 둔다.
- 쓰기는 임시 파일에 쓴 뒤 바꿔 넣는다(쓰다가 끊겨도 원본이 깨지지 않게).
- 앱에서 지우는 것은 모두 휴지통을 거친다([휴지통](#휴지통)). 예외는 금고의 인증 정보뿐이다(평문으로 남기지 않도록 바로 지운다).

## 위치

프로그램, 설정, 데이터, 출력을 모두 **앱 폴더 하나** 안에 둔다. 앱 폴더를 통째로 복사하면 다른 위치나 다른 PC에서도
그대로 쓸 수 있다. 사용자 프로필 폴더(`%APPDATA%`, `문서` 등)에는 아무것도 쓰지 않는다.

```text
<앱 폴더>/
├── app/                          프로그램. 업데이트할 때 이 폴더만 바꾼다
│   ├── defaults/                 기본 가이드라인·이미지 라이브러리 (처음 실행 때 data/로 복사)
│   └── samples/                  샘플 작품 (읽기 전용 원본. "샘플 작품"은 복사본을 data/works/에 만든다)
├── config/
│   ├── settings.json             화면 언어, 창 상태, 기본 플랫폼 프리셋, LoRA 폴더, 이미지 생성·학습 연결
│   └── vault.json                금고: API 키 등 인증 정보 (마스터 비밀번호로 암호화)
├── state/                        작업 대기열, GPU 상태, 화면 상태 (작품 데이터가 아니다)
├── data/                         데이터 루트 (아래 "데이터 루트")
└── output/                       출력 루트: 생성 이미지·학습 로그 같은 큰 파일 ([큰 파일](#큰-파일))
    └── loras/                    LoRA 폴더 기본 위치
```

| 무엇 | 위치 | 비고 |
|---|---|---|
| 프로그램 | `app/` | 업데이트는 `app/`만 교체하고 나머지는 건드리지 않는다 |
| 앱 설정 | `config/settings.json` | 경로는 앱 폴더 기준 상대 경로로 적는다(앱 폴더를 옮겨도 유지) |
| 금고 | `config/vault.json` | API 키 등 인증 정보. 마스터 비밀번호로 암호화하며 OS에 의존하지 않는다([금고](#금고)). `data/`와 분리해 두어 데이터만 공유할 때 키가 섞이지 않게 한다 |
| 앱 상태 | `state/` | 작업 대기열(`queue.json`), GPU 상태, 화면 상태(`ui.json`: 마지막 작품, 열린 탭, 패널 너비, 작품별로 고른 페르소나 `persona_by_work`). 지워도 작품 데이터에는 영향이 없다 |
| 데이터 루트 | `data/` | 개발 중에는 저장소의 `data/`(git 제외) |
| 출력 루트 | `output/` | 큰 파일 |
| LoRA 폴더 | `output/loras/` | 설정에서 이미지 생성 도구의 모델 폴더로 바꿀 수 있다(앱 밖을 가리키는 유일한 경로) |

- 앱 폴더는 쓰기 가능한 위치에 둬야 한다(예: `Program Files` 아래는 쓰기 제한이 있어 맞지 않는다).
- `settings.json`의 `default_platform_preset`: 새 작품에 자동으로 붙일 플랫폼 프리셋 ID. 비어 있으면 새 작품은 어떤 프리셋에도
  연결되지 않는다([플랫폼 프리셋](#플랫폼-프리셋)).

## 금고

마스터 비밀번호 하나로 **앱 실행 인증**과 **인증 정보 암호화**를 함께 한다. 첫 실행 때 비밀번호를 정하고, 이후 실행할
때마다 입력한다. 금고를 열 수 있으면 인증 통과다(비밀번호 해시를 따로 저장하지 않는다).

### 대상

| 암호화한다 (금고 안) | 암호화하지 않는다 |
|---|---|
| LLM API 키, 이미지·모델 서비스 토큰, 원격 서버 인증 정보, 그 밖에 사용자가 등록하는 비밀 값 | 작품 전체, 플랫폼 프리셋, 가이드라인, 이미지 라이브러리, LLM 연결 목록(주소·모델 이름), 테스트 기록, 임시 항목, 앱 설정, 출력 파일 |

- 기준: 그것만 있으면 남이 계정을 쓰거나 비용을 쓸 수 있는 것.
- 실행 인증은 앱 화면과 서버 API 진입을 막는 것이다. `data/`의 파일은 사람이 읽을 수 있는 평문 원칙을 따르므로 앱 밖에서는
  비밀번호 없이 읽힌다. 디스크 보호가 필요하면 OS 기능(BitLocker 등)이나 암호화 폴더 도구로 앱 폴더를 감싼다.

### 형식

위치: `config/vault.json`

```json
{
  "schema_version": 1,
  "kdf": {"name": "scrypt", "n": 131072, "r": 8, "p": 1, "salt": "…"},
  "wrapped_key": {"cipher": "AES-256-GCM", "nonce": "…", "data": "…"},
  "secrets": {"cipher": "AES-256-GCM", "nonce": "…", "data": "…"}
}
```

- 열쇠는 두 겹이다. 무작위 데이터 열쇠(DEK)로 `secrets`를 암호화하고, 비밀번호에서 scrypt로 만든 열쇠(KEK)로 DEK를
  감싸 `wrapped_key`에 둔다. 비밀번호를 바꾸면 `wrapped_key`만 다시 만든다.
- 저장할 때마다 nonce를 새로 만든다. 비밀번호가 틀리면 복호화가 실패한다.
- 복호화한 `secrets`는 이름 → 값 목록이다: `{"openai": {"kind": "llm_api_key", "value": "…", "note": "개인 계정"}}`.
  `kind`는 `llm_api_key`, `service_token`, `server_auth`, `other`.
- scrypt 매개변수는 파일에 함께 적으므로 나중에 강도를 올려도 기존 금고를 읽을 수 있다.

### 다른 파일에서 참조

평문 파일에는 값 대신 금고 항목 이름을 적는다.

```json
{"name": "OpenAI", "base_url": "https://api.openai.com/v1", "key": "secret:openai"}
```

### 규칙

- 복호화한 값은 서버 프로세스 메모리에만 두고, 앱을 끄면(또는 잠그면) 지운다. API 호출은 서버가 한다.
- 화면에는 가린 값(`sk-…abcd`)만 보낸다. 값을 다시 보려면 비밀번호를 다시 입력한다.
- 인증 정보를 로그, 오류 메시지, 테스트 기록, 스냅샷, 내보내기에 남기지 않는다. 요청 헤더는 기록하지 않고,
  응답이나 오류에 키 모양 문자열이 있으면 가린다.
- 연결 주소에 토큰이 들어 있으면(`?api_key=…` 등) 경고하고 금고로 옮기도록 안내한다.
- 비밀번호 입력이 틀리면 다시 시도할 때까지의 간격을 점점 늘린다.
- 일정 시간 쓰지 않으면 잠그는 기능을 둔다(기본은 꺼 둠).
- **비밀번호를 잊으면** 금고는 복구할 수 없다. "금고 초기화"로 새 비밀번호를 정하고 인증 정보를 다시 입력한다. 작품
  데이터는 암호화돼 있지 않으므로 잃는 것이 없다. 비밀번호를 정하는 화면에서 이를 안내한다.
- 개발 모드에서만 환경 변수 `ATELIERX_DEV_PASSWORD`로 자동 인증할 수 있다. 배포판에서는 동작하지 않는다.
- 서버 쪽 인증(세션 토큰, `127.0.0.1`에서만 받기)은 architecture.md에서 정한다.

## 데이터 루트

```text
<데이터 루트>/
├── atelierx.json                 데이터 루트 구조 버전 (layout_version)
├── platforms/<프리셋 ID>/        플랫폼 프리셋 (설정 화면에서 만든다)
│   ├── preset.json               플랫폼 규칙
│   └── guidelines/*.md           프리셋 가이드라인
├── guidelines/                   전역 가이드라인
│   ├── platform.md               (정해진 이름 → [가이드라인](#정해진-이름))
│   ├── compression.md
│   ├── image-prompt.md
│   ├── consistency.md
│   ├── jsx.md
│   └── authoring/<규모>.md       뼈대 작성 템플릿 (single, ensemble, simulation …)
├── providers.json                LLM 연결 목록과 작업별 모델 ([LLM 연결](#llm-연결))
├── personas.json                 테스트의 사용자 페르소나 목록 ([페르소나](#페르소나))
├── tokenizers/<이름>/            토크나이저 파일 (앱 포함분 + 사용자 추가)
├── usage/<연-월>.jsonl           LLM 사용량 기록 (내용 없이 토큰·비용만)
├── image/                        전역 이미지 라이브러리 (compose.json, expressions.json …, presets/)
├── tags/<이름>.csv               태그 사전 (기본 danbooru.csv + 사용자가 더한 것. 양식: defaults/tags/README.md)
├── cache/                        파생 데이터 (지워도 됨)
├── .trash/                       지운 작품·플랫폼 프리셋 ([휴지통](#휴지통))
└── works/<작품 폴더>/            작품 하나 = 챗봇 하나. 폴더 이름은 사용자가 정한다
```

### 페르소나

위치: `<데이터 루트>/personas.json`. 테스트 화면([08-chat-test](features/08-chat-test.md))에서 `{{user}}`가 될 인물의 목록이다.
모든 작품이 함께 쓰고, 작품마다 어느 것을 쓸지는 `state/ui.json`의 `persona_by_work`(작품 ID → 페르소나 ID)에 둔다. 작품 파일이
아니므로 내보내기·스냅샷에 들어가지 않는다.

```json
{
  "schema_version": 1,
  "personas": [
    {"id": "p-3fa2c1d0", "name": "소연", "description": "{{char}}의 대학 후배.\n말이 빠르고 존댓말을 쓴다.", "updated_at": "…"}
  ]
}
```

- `name`은 100자, `description`은 20,000자까지. 목록은 통째로 저장하고, 화면이 읽은 뒤 다른 곳에서 바뀌었으면 저장을 막는다.

## 작품 폴더

작품 폴더는 **사용자 트리**와 **앱 데이터 폴더(`.atelierx/`)**로 나뉜다. `.atelierx/`가 있는 폴더가 작품이다.

```text
works/청원고/
├── 메인.md                       ┐
├── 메인 (압축).md                │
├── 인물/                         │
│   ├── 한서윤.md                 │ 사용자 트리 — 구조·이름 자유
│   └── 김도현.md                 │ 항목 종류는 각 파일의 메타데이터로 정한다
├── 세계관/학교.md                │
├── UI/상태창.jsx                 │
├── 메모/떡밥 정리.md             ┘
└── .atelierx/                    앱 데이터 (트리에 보이지 않음)
    ├── work.json                 작품 정보·설정 (작품 ID 포함)
    ├── relations.json            관계도 (참고용)
    ├── glossary.json             용어집
    ├── consistency.json          모순 검사에서 무시한 문제
    ├── guidelines/*.md           작품별 가이드라인 (전역·플랫폼 프리셋을 덮어씀)
    ├── image/                    이미지 데이터 ([이미지 데이터](#이미지-데이터))
    │   ├── *.json                작품 공용 이미지 라이브러리 (전역을 덮어씀)
    │   └── characters/<캐릭터 ID>/
    ├── jsx/<JSX ID>/props/       JSX 예시(컴포넌트 호출)
    ├── tests/runs/<시각>.jsonl   테스트 화면의 대화 기록
    ├── agent/<대화 ID>.jsonl     에이전트 대화 기록
    ├── drafts/                   검토 대기 중인 임시 항목
    ├── trash/                    작품 안에서 지운 것
    └── history/                  스냅샷 저장소
```

- 화면 왼쪽 파일 트리는 `.atelierx/`를 뺀 작품 폴더 전체를 보여 준다. 관계도, 용어집, 이미지 데이터, 임시 항목, 휴지통은
  각 전용 화면에서 다룬다.
- 트리에서 **항목**은 `.md`와 `.jsx` 파일이다. 그 밖의 파일은 트리에 보이지만 앱이 처리하거나 내보내지 않는다.
- 파일·폴더 이름에는 Windows에서 쓸 수 없는 문자(`\ / : * ? " < > |`)를 쓸 수 없다. 같은 폴더에 같은 이름(대소문자 무시)은
  둘 수 없다. 사용자 트리에 `.atelierx`라는 이름은 쓸 수 없다.
- 스냅샷에 들어가는 것: 사용자 트리의 **항목**(`.md`·`.jsx`)과 `.atelierx/`의 파일(빼는 것: `tests/runs/`, `agent/`, `drafts/`,
  `trash/`, `history/`). 항목이 아닌 파일(이미지, 빌드 결과, 스크립트 등)은 이력에 넣지 않는다.

### work.json

위치: `.atelierx/work.json`

```json
{
  "schema_version": 1,
  "layout_version": 1,
  "id": "W001",
  "tags": ["학원물"],
  "scale": "ensemble",
  "language": "ko",
  "overrides": {},
  "character_sections": {},
  "char": null,
  "llm_consent": ["openrouter"],
  "order": {
    "": ["메인.md", "인물", "세계관", "UI"],
    "인물": ["한서윤.md", "김도현.md"]
  },
  "created_at": "2026-10-02T14:00:00+09:00",
  "updated_at": "2026-10-02T14:00:00+09:00"
}
```

| 필드 | 뜻 |
|---|---|
| `layout_version` | 작품 폴더 구조의 버전([버전](#버전)). |
| `id` | 작품 ID([ID](#id)). 출력 경로, LoRA 파일 이름 등에 쓴다. 작품 이름은 폴더 이름이다. |
| `tags` | 작품 태그. 플랫폼 프리셋 ID와 같은 태그는 그 프리셋을 연결해 설정을 상속받는다([플랫폼 프리셋](#플랫폼-프리셋)). 나머지는 분류용 자유 태그. 새 작품에는 설정의 `default_platform_preset`이 있으면 그 ID가 들어간다. |
| `scale` | 챗봇 규모: `single`(주인공 1명), `ensemble`(고정 인물 여럿), `simulation`(다수 NPC·시스템 중심). 작성 지원과 검사 기준이 달라진다. |
| `language` | 본문 언어. LLM 지시문, 검사 기준, 섹션 이름 기본값에 쓴다. |
| `overrides` | 상속받은 플랫폼 프리셋 값 중 이 작품만 바꿀 값. `preset.json`과 같은 키 구조이고, 비어 있으면 상속값 그대로. |
| `character_sections` | 섹션 이름 중 이 작품만 바꿀 값([섹션](#섹션)). |
| `char` | `{{char}}`가 가리킬 캐릭터 ID([예약 참조](#예약-참조)). 주로 `single` 작품에서 쓴다. |
| `llm_consent` | 이 작품의 내용을 보내도 된다고 동의한 외부 LLM 연결 ID 목록([LLM 연결](#llm-연결)). |
| `order` | 파일 트리의 순서. 키는 작품 폴더 기준 폴더 경로(`""`는 최상위), 값은 그 안의 이름 순서. 없는 폴더나 목록에 없는 이름은 이름순으로 뒤에 둔다. 내보내기 순서에도 쓴다. |

### 항목

사용자 트리의 `.md`·`.jsx` 파일이 항목이다. 파일을 만드는 방법은 하나다(트리에서 "새 파일"). 종류는 만든 뒤 편집기 상단
폼의 **종류** 드롭다운에서 고른다.

| 종류 (`kind`) | 파일 | 내보내기 | ID 권유 형식 | 상단 폼 | 넘어갈 화면 |
|---|---|---|---|---|---|
| `lorebook` (기본) | `.md` | 로어북 항목 | `L001` | ID, 키워드, 우선순위, 항상 넣기, 사용 | — |
| `character` | `.md` | 로어북 항목 | `C001` | 위와 같음 | 이미지 디자인(이미지 프롬프트 변환) |
| `main` | `.md` | 메인 프롬프트 | `M001` | ID, 사용 | — |
| `start` | `.md` | 시작 상황 | `S001` | ID, 사용 | — |
| `jsx` | `.jsx` | 컴포넌트 | `J001` | ID, 기본 예시 props, 사용 | JSX 미리보기·props 테스트 |
| `note` | `.md` | 내보내지 않음 | (선택) | ID(선택) | — |

- 새 `.md` 파일은 `lorebook`으로 시작한다.
- `.md` 종류끼리는 자유롭게 바꾼다. `jsx`로 바꾸거나 `jsx`에서 다른 종류로 바꾸면 확장자도 바뀌며, 본문이 비어 있지 않으면
  확인을 받는다.
- **사용(`enabled`)**: `false`면 내보내기·테스트·용량 합계에서 뺀다. 원본과 압축본을 함께 두는 경우처럼 같은 내용의
  여러 판을 보관할 때 쓴다. 기본은 `true`.
- **메인 프롬프트**는 여러 개 둘 수 있지만 사용 중(`enabled: true`)인 것은 하나여야 한다. 0개이거나 둘 이상이면 규칙 검사에서
  알린다.
- **시작 상황**은 대화가 시작되는 장면으로, 챗봇이 첫 턴에 보내는 글이다. 여러 개를 둘 수 있고 사용 중인 것이 여럿이어도
  된다(플랫폼에서 사용자가 하나를 골라 시작).
  테스트는 사용 중인 시작 상황 중 하나를 골라 봇의 첫 응답으로 쓴다(없으면 사용자가 먼저 말한다).

#### `.md` 항목의 메타데이터

본문 앞에 YAML 메타데이터(front matter)를 둔다. 읽을 때는 표준 YAML로 읽고, 앱이 쓸 때는 문자열·숫자·참/거짓·목록만
쓴다. 다시 쓸 때 키 순서와 모르는 필드를 보존한다. 화면에서는 메타데이터를 편집기 상단 폼으로 보여 주고, 폼에 없는
필드는 "기타" 칸에 원문으로 보여 준다.

```markdown
---
schema_version: 1
id: C001
kind: character
keywords: [서윤, 한서윤, 반장]
priority: 100
always: false
---
## 식별
…
## 외모
…
## 의상
### 평상복
…
### 교복
…
```

| 필드 | 대상 종류 | 뜻 |
|---|---|---|
| `id` | 전부 (`note`는 선택) | 항목 ID([ID](#id)). |
| `kind` | 전부 | 종류. 없으면 `lorebook`. |
| `enabled` | 전부 (`note` 제외) | 사용 여부. 없으면 `true`. |
| `keywords` | `lorebook`, `character` | 활성화 키워드 목록(여러 개). 테스트와 내보내기에서 쓴다. |
| `priority` | `lorebook`, `character` | 활성화된 항목이 예산을 넘을 때 남길 순서(높을수록 먼저). [로어북 활성화](#로어북-활성화) 참조. |
| `always` | `lorebook`, `character` | 키워드와 관계없이 항상 넣을지. |
| `activation` | `lorebook`, `character` | 항목별 활성화 옵션. **예약된 구조이며 아직 쓰지 않는다**. [로어북 활성화 옵션](#로어북-활성화-옵션-예약) 참조. |

- 용량은 **메타데이터를 뺀 본문**으로 센다. 세는 방식은 플랫폼 프리셋이 정한다.
- 로어북의 기본 구성은 **이름(파일 이름)**, **내용(본문, Markdown)**, **활성화 키워드** 세 가지다. 나머지 필드는 선택이다.
- 키워드는 본문이 아니라 상단 폼의 키워드 입력란에서 따로 입력한다. 입력하고 엔터를 누르면 하나가 확정되어 칩으로
  표시되고 다음 키워드를 이어서 입력한다. 저장은 YAML 목록이므로 키워드 안에 쉼표가 있어도 된다. 앞뒤 공백은 지우고,
  같은 키워드(대소문자 구분은 플랫폼 프리셋 `lorebook.case_sensitive`를 따름)는 한 번만 넣는다.

#### `.jsx` 항목의 메타데이터

`.jsx` 파일에는 YAML 머리를 둘 수 없으므로 파일 맨 앞 주석 블록에 같은 형식으로 둔다. 내보낼 때는 이 블록을 뗀다.

```jsx
/*---
schema_version: 1
id: J001
kind: jsx
default_props: basic
---*/
function StatusPanel(props) {
  …
}
```

| 필드 | 뜻 |
|---|---|
| `default_props` | 미리보기에서 처음 열 예시 이름. 대화 테스트는 이 예시의 첫 호출에서 기본 props를 읽는다. |

- 예시 props는 `.atelierx/jsx/<JSX ID>/props/`에 둔다([JSX 예시 props](#jsx-예시-props)). 파일을 옮기거나
  이름을 바꿔도 ID로 따라온다.
- 플랫폼 규칙(가져오기 금지 등)은 플랫폼 프리셋의 `jsx` 항목으로 검사한다. 검사와 미리보기는 [07-jsx](features/07-jsx.md).

### ID

| 대상 | 저장 위치 | 권유 형식 |
|---|---|---|
| 작품 | `.atelierx/work.json`의 `id` | `W001` |
| 항목 | 항목 메타데이터의 `id` | 종류별: `M001`, `S001`, `L001`, `C001`, `J001` ([항목](#항목)) |
| 로어북 없는 인물 | `.atelierx/relations.json`의 `people` | `N01` |

- 편집기 상단 폼에서 입력한다. 입력란에는 종류에 맞는 다음 번호를 placeholder로 보여 주고, 비워 두면 저장할 때 그 값을 쓴다.
  권유 형식과 다른 값을 직접 넣어도 된다. 종류를 바꿔도 이미 정한 ID는 바뀌지 않는다.
- 쓸 수 있는 문자: 영문, 숫자, `_`, `-`, 1~32자. 폴더 이름·출력 파일 이름·LoRA 파일 이름에 쓰이기 때문이다.
- 작품 ID는 데이터 루트 안에서, 항목 ID는 작품 안에서 유일하다. 대소문자만 다른 ID는 같은 것으로 본다.
- **ID 바꾸기**는 연결 갱신 작업이다. 영향받는 곳(관계도, 이미지 데이터, JSX 예시 props, 출력 폴더, 데이터셋·학습
  기록, 임시 항목)을 보여 주고 확인을 받은 뒤, `before_bulk` 스냅샷을 만들고 한꺼번에 바꾼다. 이미 만든 LoRA 파일은 이름을
  바꾸지 않고 참조만 갱신한다.
- **작품 복제**: 새 작품 ID를 정한다(placeholder로 다음 번호 권유). 항목 ID는 작품 안에서만 유일하면 되므로 그대로 둔다.
  `.atelierx/`의 `history/`, `drafts/`, `trash/`, `tests/runs/`는 복사하지 않는다. 출력 루트의 파일은 복사하지 않으며, 복제본의
  이미지 데이터에 있는 큰 파일 참조는 원본 작품의 파일을 그대로 가리킨다.

### 예약 참조

챗봇 플랫폼에서 널리 쓰는 두 이름을 예약 참조로 고정한다. 항목 ID가 아니므로 ID 규칙을 따르지 않고, 사용자가 만들거나 지울 수 없다.

| 참조 | 뜻 |
|---|---|
| `{{user}}` | 챗봇을 쓰는 사람(사용자). 모든 작품에서 쓸 수 있다 |
| `{{char}}` | 1:1 대화(`scale: single`)에서 사용자가 대화하는 상대 캐릭터. `work.json`의 `char`가 가리키는 캐릭터 항목이다 |

- 본문, 시작 상황, 키워드, 관계도(`from`, `to`, `subject`)에서 쓸 수 있다.
- `work.json`의 `char`: `{{char}}`가 가리킬 캐릭터 ID. `single` 작품에서 캐릭터가 하나뿐이면 앱이 그 캐릭터로 채운다. `single`이
  아닌 작품에서 본문에 `{{char}}`가 있으면 규칙 검사가 알린다(누구인지 정할 수 없음).
- 테스트는 맥락을 보낼 때 `{{user}}`를 페르소나 이름으로, `{{char}}`를 그 캐릭터의 이름(파일 이름)으로 바꾼다
  ([08](features/08-chat-test.md)). 내보내기는 바꾸지 않고 그대로 둔다(플랫폼이 바꾼다).
- 압축의 누락 검사와 이름 일괄 변경은 예약 참조를 이름으로 다룬다(지우거나 바꾸지 않는다).
- 예약 참조 바로 뒤에 조사를 붙이면(`{{user}}는`) 바뀔 이름의 받침에 따라 어색해진다. "사용자({{user}})는"처럼 조사가 예약 참조에
  붙지 않게 쓰는 것을 권한다. 규칙 검사는 예약 참조 바로 뒤의 조사를 정보 수준으로 알린다.

### 섹션

캐릭터 본문은 2단계 제목(`##`)으로 섹션을 나눈다. 섹션 안의 3단계 제목(`###`)은 소제목이다(예: 의상 여러 벌).
앱은 섹션을 **키**로 다루고, 키에 맞는 제목 글자는 작품 언어로 정한다.

| 키 | 기본 제목 (`ko`) | 기본 제목 (`en`) | 쓰는 곳 |
|---|---|---|---|
| `identity` | 식별 | Identity | 작성 지원, 모순 검사 |
| `appearance` | 외모 | Appearance | 이미지 프롬프트 변환 |
| `outfit` | 의상 | Outfit | 이미지 프롬프트 변환 |

- 기본 제목은 앱이 언어별로 가진다. `work.json`의 `character_sections`에 바꿀 키만 적으면 그것을 쓴다.
  예: `{"outfit": "복장"}`.
- 앱에 기본값이 없는 언어는 작품 설정에서 정해야 한다. 정하지 않으면 해당 섹션을 찾을 수 없다고 알린다.
- 섹션이 없으면 이미지 프롬프트 변환은 본문 전체를 LLM에 주고 해당 내용을 찾게 하며, 결과에 "섹션 없음"을 표시한다.
- 앱은 새 파일에 섹션 뼈대를 자동으로 넣지 않는다. 권장 구성은 샘플 작품으로 보여 준다.

### JSX 예시 props

위치: `.atelierx/jsx/<JSX ID>/props/<예시>.txt`

예시 이름은 파일 이름이다. 내용은 **응답에 쓰는 그대로의 컴포넌트 호출**이다. props는 작품에 연결된 플랫폼 프리셋의
`jsx.response`로 읽는다(실제 응답과 같은 방식). 호출을 여러 개 쓰거나 응답 문장째 적어도 되며, props가 필요한 곳(대화 테스트의
기본 props, 프롬프트용 문구 만들기)은 첫 번째 호출을 쓴다. 미리보기에서 전환하며 쓰고, 테스트 응답에서 꺼낸 props와 비교할 때
기본 예시(`default_props`)를 기준으로 쓴다.

```text
<StatusPanel data='{"location": "교실", "time": "08:40", "affinity": {"C001": 12}}' />
```

- 이전 형식(`<예시>.json`, props 그대로의 JSON)도 읽는다. 화면에는 호출로 바꿔 보여 주고, 저장하면 `.txt`로 바뀐다.

- 챗봇 응답에 컴포넌트를 넣는 형식은 메인 프롬프트·로어북 본문에 사용자가 쓴 문구가 원본이다. 앱은 컴포넌트별 형식 정보를 따로
  저장하지 않는다. 응답 속 표기를 읽는 규칙은 플랫폼 프리셋의 `jsx.response`([구성](#구성)).

### 관계도

위치: `.atelierx/relations.json`

인물 사이의 관계·호칭과 기준 사실을 모아 보는 **참고용** 데이터다. 관계의 원본은 각 캐릭터 로어북과 메인 프롬프트의 본문이고,
관계도는 내보내기·테스트 맥락에 들어가지 않는다. 화면은 그림(인물 노드와 방향 있는 관계 화살표)과 표 두 가지로 보여 준다.

```json
{
  "schema_version": 1,
  "people": [
    {"id": "N01", "name": "담임 선생님", "note": "로어북 없는 인물"}
  ],
  "relations": [
    {"from": "C001", "to": "C002", "kind": "친구", "calls": "도현아", "note": "초등학교부터"},
    {"from": "C001", "to": "{{user}}", "kind": "반 친구", "calls": "전학생"}
  ],
  "facts": [
    {"subject": "C001", "key": "나이", "value": "17"}
  ],
  "layout": {"C001": {"x": 120, "y": 80}}
}
```

- 인물은 `{{user}}`, 작품의 캐릭터 항목 전부(자동, 이름은 파일 이름), `people`에 적은 로어북 없는 인물(`N##`, 이 경우에만
  `name`을 적음) 순으로 보인다. `{{user}}`와 `{{char}}`는 적지 않아도 쓸 수 있는 예약 참조다([예약 참조](#예약-참조)).
- `relations`는 방향이 있다(`calls`는 from이 to를 부르는 호칭). 서로 다른 관계는 두 줄로 쓴다.
- `facts`는 인물별 기준 사실(나이, 학년, 소속 등)이다. 모순 검사가 본문과 비교하는 기준으로 쓴다.
- `layout`은 그림 보기에서 사용자가 옮긴 노드 위치다. 없으면 원형으로 자동 배치한다.
- 관계·사실이 없는 인물 ID를 가리키면 규칙 검사가 오류로 알린다.

### 용어집

위치: `.atelierx/glossary.json`

```json
{
  "schema_version": 1,
  "terms": [
    {"use": "청원고", "avoid": ["청원고등학교", "청원 고교"], "note": "학교 이름은 줄여 쓴다"}
  ]
}
```

- `use`는 쓸 표기, `avoid`는 피할 표기. 규칙 기반 검사가 본문에서 `avoid`를 찾아 알린다([04-authoring](features/04-authoring.md)).
- 용어집의 `use`와 관계도의 이름·호칭은 압축의 누락 검사에서 "이름"으로 쓰인다.

### 모순 검사 기록

위치: `.atelierx/consistency.json`

```json
{
  "schema_version": 1,
  "ignored": [
    {"hash": "…", "items": ["C001", "L003"], "quote": "열여덟 살", "note": "작중 1년 뒤 시점이라 맞음", "at": "2026-10-03T10:00:00+09:00"}
  ]
}
```

- 사용자가 "무시"한 문제. `hash`는 문제 종류·관련 항목·근거 인용으로 만든다. 다음 검사에서 같은 해시의 문제는 접어서 보여 준다.

### 테스트 기록

위치: `.atelierx/tests/runs/<시각>.jsonl`

테스트 화면([08-chat-test](features/08-chat-test.md))의 대화를 한 줄에 한 턴으로 남긴다: 보낸 맥락 요약(불러온 메인 프롬프트·로어북,
예산 때문에 빠진 항목, 크기), 응답 속 컴포넌트 호출, 모델, 응답, 걸린 시간. 스냅샷에 넣지 않는다. 최근 100개를 남긴다.

### 에이전트 대화

위치: `.atelierx/agent/<대화 ID>.jsonl` (대화 ID는 `<시각>-<무작위 4자>`)

에이전트 패널([11-agent](features/11-agent.md))의 대화 하나가 파일 하나다. 한 줄에 사건 하나를 덧붙여 쓰고, 읽을 때 차례로 적용한다.
스냅샷·내보내기에 넣지 않고 자동으로 지우지 않는다.

```jsonl
{"type": "meta", "mode": "character", "title": "말투 다듬기", "scope": {"kind": "file", "paths": ["인물/한서윤.md"]}, "at": "…"}
{"type": "user", "text": "말투를 조금 더 건조하게", "attachments": [{"path": "인물/한서윤.md", "from": 12, "to": 30}], "at": "…"}
{"type": "assistant", "text": "…<<<file path=\"인물/한서윤.md\">>>…<<<end>>>", "model": {"provider": "local", "name": "…"},
 "finish_reason": "stop", "context": {"files": 1, "tokens": 1820, "omitted": []},
 "proposals": [{"n": 1, "path": "인물/한서윤.md", "new": false, "truncated": false, "base_hash": "…", "warnings": []}], "at": "…"}
{"type": "proposal", "turn": 2, "n": 1, "draft_id": "20261005T142233-agent_file-a1b2"}
{"type": "meta", "title": "한서윤 말투"}
```

| 사건 | 뜻 |
|---|---|
| `meta` | 대화 정보. 첫 줄은 모드·범위·만든 시각, 뒤의 `meta`는 바뀐 필드만(이름·범위 바꾸기). |
| `user` | 사용자 메시지와 첨부(경로, 줄 범위 `from`·`to`; 없으면 파일 전체). |
| `assistant` | 응답 원문, 쓴 모델, 끝난 이유(`stop`·`length` 등), 보낸 맥락 요약, 응답에서 읽은 제안 목록. `base_hash`는 응답을 받은 때의 원본 해시(새 파일이면 없음). |
| `proposal` | 제안을 검토로 보냄. `turn`은 0부터 센 줄 순서가 아니라 `user`·`assistant` 턴 번호(1부터). |

- 제안의 `warnings`: `shrunk`(원본의 60% 미만), `omission`(생략 표시), `id_changed`, `kind_changed`.
- 인증 정보는 남기지 않는다.

### 임시 항목

위치: `.atelierx/drafts/<시각>-<종류>.json`

LLM 결과처럼 사람이 확인하기 전의 임시 항목을 보관한다. 원본에 반영하기 전까지는 여기에만 있다. 작품 폴더 안에 두어
작품과 함께 옮겨지지만, 파일 트리·내보내기·스냅샷에는 넣지 않는다.

```json
{
  "schema_version": 1,
  "kind": "compression",
  "target": {"id": "C001", "path": "인물/한서윤.md", "base_hash": "…"},
  "guidelines": [
    {"name": "platform.md", "from": "preset:cafe-bot", "hash": "…"},
    {"name": "compression.md", "from": "global", "hash": "…"}
  ],
  "model": {"provider": "local", "name": "…"},
  "request": {"target_size": 4275, "keep": [5, 6], "feedback": []},
  "blocks": [{"n": 1, "start": 0, "end": 12, "hash": "…"}],
  "candidates": [
    {"round": 1, "note": "어투 유지, 배경 일화 축약", "size": 3820,
     "blocks": [{"from": 1, "to": 1, "text": "…"}, {"from": 3, "to": 4, "text": "…"}, {"from": 7, "to": 7, "text": null}],
     "checks": {"missing": [{"kind": "number", "value": "17", "block": 2}]}}
  ],
  "composition": null,
  "status": "pending",
  "cost": {"input_tokens": 0, "output_tokens": 0, "usd": 0},
  "created_at": "2026-10-02T15:00:00+09:00"
}
```

| 필드 | 뜻 |
|---|---|
| `kind` | 종류: `compression`(압축 후보), `image_prompt`(이미지 프롬프트 변환), `jsx_prompt`(JSX 프롬프트용 문구), `authoring`(뼈대 작성 초안), `relations`(본문에서 찾은 관계 후보), `consistency`(모순 검사 결과), `agent_file`(에이전트의 파일 전체 교체 제안: `candidates[0].text`가 새 내용 전체, `request`에 대화 ID·턴·경고와 응답 때의 원본 `original`, 새 파일이면 `target.new: true`). 종류마다 검토 화면이 다르다. |
| `target` | 대상. `id`로 찾고 `path`는 표시용. `base_hash`는 만들 때의 대상 본문 해시. |
| `guidelines` | 사용한 가이드라인 목록: 이름, 찾은 위치(`work`, `preset:<ID>`, `global`), 그때의 해시. |
| `model` | 사용한 LLM 연결과 모델. |
| `request` | 작업 설정(종류마다 다름). 압축은 목표 용량, 잠근 블록 번호(`keep`), 다시 만들기 때 덧붙인 요청 목록. |
| `blocks` | 압축에서 원본을 나눈 블록 목록: 번호, 본문 안 시작·끝 위치, 해시. 원본이 바뀌었을 때 그대로인 블록을 알아낸다. |
| `candidates` | 후보 목록. `round`는 몇 번째 만들기에서 나왔는지(다시 만들기도 같은 임시 항목에 쌓임), `size`는 플랫폼 세는 방식의 용량, `blocks`는 원본 블록 범위(`from`~`to`)별 결과(`null`은 삭제), `checks`는 누락 검사 결과. 블록 단위가 아닌 작업은 `text` 하나로 둔다. |
| `composition` | 검토 중인 채택안(블록별 선택과 직접 수정한 내용). 검토 탭을 닫았다 열어도 이어서 할 수 있게 저장한다. |
| `status` | `pending`(검토 대기), `applied`(채택), `discarded`(버림). |
| `cost` | 외부 API를 쓴 경우의 사용량·비용. |

- 채택할 때 대상 본문이 `base_hash`와 다르면 "만든 뒤 원본이 바뀜"을 경고한다.
- 본문 후보(압축 등)는 **원본에 덮어쓰기** 또는 **새 파일로 저장** 중 고른다. 새 파일로 저장하면 같은 종류의 새 항목이 원본
  옆에 생기고, 원본과 새 항목 중 어느 쪽을 사용(`enabled`)할지 고른다.
- 원본에 쓰기 직전에 `before_llm` 스냅샷을 만들고 `status`를 `applied`로 바꾼다.
- `applied`·`discarded`는 30일 뒤 자동으로 지운다. `pending`은 지우지 않는다.

## 이미지 데이터

캐릭터의 정체(ID, 이름)는 캐릭터 항목에만 있다. 이미지 데이터는 "이 캐릭터를 어떻게 그리나"만 담고 캐릭터 ID로
연결한다. 캐릭터 본문 섹션(글)과 이미지 프롬프트(태그)는 같은 내용의 다른 표현이며 출처 해시로 연결한다.

```text
인물/한서윤.md  (id: C001, kind: character)
  ▼ 이미지 프롬프트 변환 (섹션 키 + 본문 해시를 source로 남김) → 임시 항목에서 검토·채택
.atelierx/image/characters/C001/design.json
  ▼ 생성 (의상 × 표정 × 생성 프리셋)
<출력 루트>/W001/C001/images/…  (이미지마다 생성 기록 .json) + <출력 루트>/reviews.json (검수)
  ▼ 검수 통과 이미지 선택
.atelierx/image/characters/C001/datasets/D001.json
  ▼ 학습
.atelierx/image/characters/C001/lora/runs/R001.json  →  <LoRA 폴더>/W001_C001_R001-e40.safetensors
  ▼ 등록
.atelierx/image/characters/C001/lora/models.json  →  다음 생성에 적용
```

```text
.atelierx/image/
├── *.json                        작품 공용 라이브러리 (전역을 덮어씀)
├── board.json                    완성도 보드: 캐릭터별로 필요 없다고 표시한 조합
└── characters/<캐릭터 ID>/
    ├── design.json               캐릭터 디자인: 외모·의상 프롬프트
    ├── datasets/<D###>.json      학습 데이터셋
    └── lora/
        ├── runs/<R###>.json      학습 기록
        └── models.json           쓸 LoRA 목록
```

### 완성도 보드

캐릭터마다 필요한 조합은 디자인의 의상 × 작품에서 쓰는 표정 라이브러리다. 필요 없는 조합만 `board.json`에 적는다.

```json
{"schema_version": 1, "characters": {"C001": {"excluded": ["o02/angry", "o02/sad"]}}}
```

- 조합은 `<의상 ID>/<표정 ID>`. 상태(미생성·생성됨·채택·제외, 대기열 장수)는 갤러리·검수 기록·생성 대기열에서 그때그때 계산하고 저장하지 않는다.
- 제외한 조합은 진행률과 채택 이미지 내보내기의 누락 목록에서 빠진다.

### 범위와 덮어쓰기

이미지 프롬프트 재료는 세 범위에 둘 수 있다. 같은 종류·같은 id면 **캐릭터 → 작품 → 전역** 순서로 먼저 찾은 것을 쓴다
(가이드라인과 같은 규칙).

| 범위 | 위치 |
|---|---|
| 전역 | `<데이터 루트>/image/` |
| 작품 | `<작품 폴더>/.atelierx/image/` |
| 캐릭터 | `<작품 폴더>/.atelierx/image/characters/<캐릭터 ID>/design.json` (외모·의상만) |

### 캐릭터 디자인

위치: `design.json`

```json
{
  "schema_version": 1,
  "trigger": "w001_c001",
  "appearance": {
    "prompt": ["1girl", "black hair", "long hair", "brown eyes"],
    "negative": [],
    "source": {"section": "appearance", "hash": "…"}
  },
  "outfits": {
    "o01": {
      "name": "평상복",
      "slots": {
        "top": {"prompt": ["white blouse"]},
        "bottom": {"prompt": ["black pencil skirt"]},
        "shoes": {"ref": "work:loafers"}
      },
      "negative": ["necklace"],
      "source": {"section": "outfit", "heading": "평상복", "hash": "…"}
    }
  },
  "default_outfit": "o01"
}
```

| 필드 | 뜻 |
|---|---|
| `trigger` | LoRA 학습·생성에 쓰는 캐릭터 고유 단어. 기본 제안값은 `<작품 ID>_<캐릭터 ID>`(소문자), 수정 가능. |
| `appearance` | 외모 태그와 negative. |
| `outfits` | 의상. 키가 의상 id(앱이 `o01`, `o02` …로 제안, 고칠 수 있음). `name`은 표시 이름(보통 본문의 소제목). `slots`의 부위 이름과 순서는 `compose.json`의 `slots`. |
| `slots.<부위>` | 프롬프트를 바로 적거나(`prompt`), 공용 의상 부위를 참조한다(`ref`: `work:<id>` 또는 `global:<id>`). |
| `source` | 바탕이 된 섹션 키, 소제목(`heading`, 선택), 그때의 본문 해시. 해시가 지금 본문과 다르면 "이미지 프롬프트가 오래됨"을 표시한다. 섹션 제목 글자를 바꿔도 키로 연결되므로 끊어지지 않는다. |
| `default_outfit` | 의상을 고르지 않았을 때 쓸 의상. |

- 프롬프트가 특정 모델 계열용이면 해당 항목에 `"model_family": "<이름>"`을 둔다(선택).
- `source.hash`를 알 수 없는 디자인(샘플 등 앱 밖에서 만든 파일, 값이 `"sample"`처럼 해시가 아님)은 샘플 설치·작품 가져오기 때
  앱이 지금 본문으로 다시 계산해 "최신"으로 맞춘다.

### 라이브러리

위치: `image/*.json`, 전역·작품 공통

종류마다 파일 하나다. 항목 id는 `items`의 키다.

| 파일 | 내용 | 항목의 주요 필드 |
|---|---|---|
| `compose.json` | 조합 규칙 (전역만) | `order`(조합 순서), `slots`(의상 부위와 순서), `ratings`(표정 등급과 순서) |
| `expressions.json` | 표정 | `name`, `rating`, `prompt`, `negative`, `composition`(어울리는 구도 id) |
| `compositions.json` | 구도 | `name`, `prompt`, `negative`, `suggest_slots`(이 구도에서 보이는 의상 부위) |
| `styles.json` | 화풍 | `name`, `prompt` |
| `common.json` | 공통 프롬프트 | `name`, `target`(`positive`·`negative`), `prompt` |
| `outfits.json` | 공용 의상 부위 | `name`, `slot`, `prompt`, `negative` |
| `presets/<id>.json` | 생성 프리셋 (전역만) | 모델 이름, 샘플러, 스텝, CFG, 크기, 기본 LoRA, 쓸 공통·화풍 id, 워크플로 틀 이름 |
| `workflows/<이름>.json` | 워크플로 틀 (전역만) | 이미지 생성 서버의 워크플로. 자리표시(프롬프트, negative, 시드, 크기, 모델, LoRA 목록)를 앱이 채운다. 모델 계열마다 하나 |

```json
{
  "schema_version": 1,
  "items": {
    "neutral": {"name": "무표정", "rating": "general", "prompt": ["expressionless", "closed mouth"],
                "negative": [], "composition": "upper_front"}
  }
}
```

`compose.json`은 `items`가 아니라 조합 규칙 자체를 담는다.

```json
{
  "schema_version": 1,
  "order": ["common", "style", "composition", "trigger", "appearance", "expression", "outfit"],
  "slots": [{"id": "full", "name": "전체"}, {"id": "top", "name": "상의"}],
  "ratings": [{"id": "general", "name": "일반"}]
}
```

- `order`: 최종 프롬프트를 합치는 순서. `common`(공통 positive, negative는 negative 쪽으로), `style`, `composition`, `trigger`
  (캐릭터의 트리거 단어), `appearance`, `expression`, `outfit`.
- `slots`: 의상 부위와 그 순서. `ratings`: 표정 등급과 그 순서. 사용자가 더하거나 바꿀 수 있다.

- 모델·LoRA는 **파일 이름**으로 적는다. 실제 경로는 `config/settings.json`의 모델·LoRA 폴더 설정에서 찾는다(데이터 루트에
  절대 경로를 넣지 않음).
- "생성 프리셋"은 이미지 생성 설정 묶음이고, [플랫폼 프리셋](#플랫폼-프리셋)과는 다른 것이다.
- 앱은 최소한의 기본 항목(표정·구도 몇 가지, 조합 규칙)을 `app/` 안에 갖고 있다가 데이터 루트를 처음 만들 때 전역 라이브러리로
  복사한다.

### 이미지 모듈 데이터

위치: `.atelierx/image/characters/<캐릭터 ID>/`, 출력 루트

생성·검수·데이터셋·학습 기능의 데이터다. 동작은 features 20번대([20](features/20-generation.md), [21](features/21-review.md),
[22](features/22-datasets.md), [23](features/23-lora-training.md)).

| 위치 | 내용 | 스냅샷 |
|---|---|---|
| `datasets/<D###>.json` | 학습 데이터셋: 이미지 참조 목록, 항목별 캡션(수정 여부 포함), 의상 | 포함 |
| `lora/runs/<R###>.json` | 학습 기록: 데이터셋, 학습 설정, 상태, 에폭별 결과 참조 | 포함 |
| `lora/models.json` | 쓸 LoRA 목록: 결과 참조, 출처(학습·에폭), 기본 강도, 자동 적용 여부 | 포함 |
| 출력 루트 `images/…/<번호>.json` | 이미지 하나의 생성 기록 | 제외 |
| 출력 루트 `reviews.json` | 검수 결과와 채택 | 제외 |

- 데이터셋과 학습 기록은 사람이 고른 선택과 수정한 캡션이라 다시 만들 수 없으므로 작품 폴더에 두고 스냅샷으로 지킨다.
- 생성 기록과 검수 결과는 이미지에 대한 기록이라 이미지와 함께 출력 루트에 둔다.

#### 생성 기록

위치: `<출력 루트>/<작품 ID>/<캐릭터 ID>/images/<의상>/<표정>/<번호>.json` (이미지 `<번호>.png` 옆)

```json
{
  "schema_version": 1,
  "created_at": "…",
  "job_id": "…",
  "work_id": "W001", "character_id": "C001",
  "outfit_id": "o01", "outfit_name": "근무복",
  "expression_id": "smile", "expression_name": "미소", "rating": "general",
  "composition_id": "upper_front", "outfit_slots": ["top", "full"],
  "common_ids": ["quality"], "style_ids": [], "trigger": "w001_c001", "model_family": "anima",
  "parts": {"common": "…", "style": "", "composition": "…", "trigger": "", "appearance": "…",
            "expression": "…", "outfit": "…", "negative": "…"},
  "positive": "…", "negative": "…",
  "settings": {"family": "anima", "model": "…", "steps": 32, "cfg": 5, "sampler": "er_sde",
               "scheduler": "simple", "width": 1536, "height": 1536, "seed": 471458691,
               "loras": [{"name": "W001_C001_R002-e30.safetensors", "strength": 0.8}]},
  "generation_preset": {"id": "default", "name": "기본"},
  "seed": 471458691,
  "image_size": [1536, 1536],
  "workflow": {"…": "이미지 생성 서버에 보낸 그래프"},
  "postprocessing": {"applied": false, "source_image": null}
}
```

- 같은 이미지를 다시 만들 수 있는 정보를 모두 남긴다. 갤러리의 "새 시드로 다시 생성"은 이 기록에서 시드만 바꿔 대기열에 넣는다.
- PNG에도 같은 정보를 넣는다: `prompt`(서버용 그래프), `workflow`(편집기용 그래프), `atelierx`(이 기록에서 `workflow`를 뺀 것).
- 기록이 없거나 깨진 이미지도 갤러리에는 보인다(다시 생성만 안 됨).

#### 검수 결과 (`<출력 루트>/reviews.json`)

```json
{
  "schema_version": 1,
  "revision": 12,
  "records": {
    "W001/C001/images/o01/smile/002.png\u0000<sha256>": {
      "path": "W001/C001/images/o01/smile/002.png", "sha256": "…",
      "human": "pass", "note": "손", "reviewed_at": "…", "human_revision": 12,
      "auto": "fail", "auto_reason": "…", "auto_at": "…"}
  },
  "adopted": {"[\"W001\",\"C001\",\"o01\",\"smile\"]": {"path": "W001/C001/images/o01/smile/002.png", "sha256": "…"}},
  "history": [{"at": "…", "path": "…", "from": "unreviewed", "to": "pass"}]
}
```

- 검수 결과는 경로와 해시에 묶는다. 같은 경로라도 내용이 바뀌면 미검수로 돌아간다.
- `human`은 사람의 판정(`pass`, `fail`, `unreviewed`), `auto`는 비전 LLM의 판정(`pending`, `pass`, `fail`, `uncertain`, `error`).
  둘은 따로 두고, 채택은 사람의 판정만 따른다.
- `adopted`: 조합(작품, 캐릭터, 의상, 표정)마다 채택 이미지 하나. 사람이 통과시킨 이미지가 채택되고, 같은 조합에서 나중에 통과한
  이미지가 앞의 것을 바꾼다. 채택 이미지를 실패·미검수로 바꾸면 채택이 풀린다.
- `history`는 최근 20,000건만 남긴다. 쓸 때마다 하나 전의 사본을 `reviews.json.bak`으로 남긴다.

#### 데이터셋 (`datasets/<D###>.json`)

```json
{
  "schema_version": 1,
  "name": "근무복",
  "outfits": ["o01"],
  "triggers": {"character": "w001_c001", "outfit": "w001_c001_o01"},
  "items": [
    {"image": {"root": "output", "path": "W001/C001/images/o01/smile/002.png", "sha256": "…", "size": 0},
     "outfit_id": "o01", "expression_id": "smile",
     "caption": "safe, 1girl, w001_c001, w001_c001_o01, solo, upper body, smile",
     "edited": false}
  ]
}
```

- `triggers.outfit`이 비어 있으면 의상 트리거를 쓰지 않는다. `edited`가 true인 캡션은 다시 만들 때 바뀌지 않는다.

#### 학습 기록 (`lora/runs/<R###>.json`)

```json
{
  "schema_version": 1,
  "work_id": "W001",
  "character_id": "C001",
  "dataset": "D001",
  "dataset_name": "근무복",
  "dataset_hash": "…",
  "outfits": ["o01"],
  "triggers": {"character": "w001_c001", "outfit": "w001_c001_o01"},
  "output_name": "W001_C001_R002",
  "base_model": "anima-base-v1.0",
  "settings": {"method": "atelierx_tlora", "base": "official", "preset": "atelierx_base",
               "epochs": 40, "save_every": 10, "learning_rate": "1e-4"},
  "status": "done",
  "created_at": "…",
  "started_at": "…",
  "finished_at": "…",
  "outputs": [{"epoch": 10, "file": {"root": "lora", "path": "W001_C001_R002-e10.safetensors", "sha256": "…", "size": 0}}],
  "log": {"root": "output", "path": "W001/C001/lora/R002/logs/train.log"},
  "error": null
}
```

- `status`: `waiting_gpu`, `preprocessing`, `training`, `done`, `failed`, `cancelled`, `interrupted`(앱이 꺼져 따라갈 수 없게 됨).
- `dataset_hash`는 학습에 쓴 이미지 해시와 캡션으로 만든다. 데이터셋이 그 뒤에 바뀌었는지 알 수 있다.

#### 쓸 LoRA 목록 (`lora/models.json`)

```json
{
  "schema_version": 1,
  "models": [
    {"id": "W001_C001_R002-e30", "name": "근무복 · e30", "file": "anima\\W001_C001_R002-e30.safetensors",
     "sha256": "…", "strength": 0.8, "auto_apply": true, "apply_to": "outfit", "outfit_id": "o01",
     "model_family": "anima", "enabled": true,
     "source": {"run": "R002", "epoch": 30, "dataset": "D001"},
     "triggers": {"character": "w001_c001", "outfit": "w001_c001_o01"}, "base_model": "anima-base-v1.0"}
  ]
}
```

- `file`은 이미지 생성 서버가 부르는 LoRA 이름(LoRA 폴더 안 하위 폴더 포함). 외부 파일은 `source: {"external": true}`.
- `apply_to`: `character`(그 캐릭터 전체) 또는 `outfit`(`outfit_id`의 의상만). `model_family`: `anima`, `sdxl`, `shared`.
- 자동 적용은 (대상, 의상, 계열)마다 하나다. 하나를 켜면 같은 대상의 다른 항목은 꺼진다.
- 쓰는(`enabled`) 항목이 하나라도 있으면 생성 때 이미지 디자인의 트리거 단어가 프롬프트에 들어간다.

### 큰 파일

생성 이미지·학습 로그 같은 큰 파일은 데이터 루트(`data/`) 밖의 **출력 루트**(`output/`)에, LoRA 파일은 **LoRA 출력 폴더**(설정 →
이미지 → LoRA 학습, 보통 이미지 생성 서버의 LoRA 폴더)에 둔다. 작품 데이터(`data/`)만 따로 백업·공유하기 쉽게 하고, 스냅샷이 무거워지지 않게 하기 위해서다.
경로와 파일 이름은 ID로만 만든다.

```text
<출력 루트>/<작품 ID>/<캐릭터 ID>/
├── images/<의상>/<표정>/<번호>.png  이미지 (+ 같은 이름의 .json 생성 기록)
└── lora/<R###>/logs/             학습 로그

<LoRA 폴더>/<작품 ID>_<캐릭터 ID>_<R###>-e<에폭>.safetensors

<출력 루트>/reviews.json          검수 결과·채택
<출력 루트>/_lab/<날짜>/           생성·비교 결과
<출력 루트>/_tools/<날짜>/         이미지 도구 결과(작품 이미지가 아닌 것)
<출력 루트>/.trash/<id>/           지운 이미지와 기록 (+ .trash/index.json: 원래 경로·지운 때)
```

- 이미지 도구의 목록·올린 사본·마스크는 앱 데이터 `data/image/tools/`에 둔다([24](features/24-image-tools.md)). 제외 태그는
  `config/image/tags.json`.

- 작품 폴더에서 큰 파일을 가리킬 때는 참조를 쓴다: `{"root": "output", "path": "…", "sha256": "…", "size": 0}`.
  `root`는 `output`(출력 루트) 또는 `lora`(LoRA 폴더), `path`는 그 루트 기준 상대 경로. 절대 경로는 쓰지 않는다.
- 루트를 옮겨도 상대 경로로 다시 찾고, 해시로 같은 파일인지 확인한다.
- 스냅샷은 참조만 기록한다. 배포 표시된 스냅샷이 참조하는 파일은 자동 정리에서 지우지 않는다.

## 플랫폼 프리셋

위치: `platforms/<프리셋 ID>/preset.json`

플랫폼마다 다른 규칙(용량 제한, 세는 방식, 로어북 활성화, JSX 규칙 등)의 묶음이다. 설정 화면에서 만들고 고친다.
작품은 **태그**로 프리셋에 연결되어 그 값을 상속받는다. 폴더 이름이 프리셋 ID이자 연결 태그다.

### 연결과 상속

- `work.json`의 `tags` 중 플랫폼 프리셋 ID와 같은 태그가 연결 태그다. 나머지 태그는 분류용이다.
- 새 작품에는 `config/settings.json`의 `default_platform_preset`이 지정돼 있으면 그 ID를 태그로 넣는다. 지정돼 있지 않으면
  연결하지 않는다.
- 값은 다음 순서로 겹쳐 정해진다. 뒤의 것이 앞의 것을 덮는다(키 단위로 합침).
  1. 앱 기본값 (`generic`과 같음)
  2. 연결된 플랫폼 프리셋들 — `tags`에 적힌 순서대로
  3. 작품의 `overrides`
- 설정 화면과 작품 설정에서 각 값이 어디서 왔는지(기본값 / 어느 프리셋 / 작품) 표시한다.
- 프리셋을 고치면 그 태그가 붙은 모든 작품에 바로 반영된다. 프리셋을 지우거나 ID를 바꾸면 영향받는 작품 목록을 보여 주고
  확인을 받는다.

### 구성

아래는 제한을 둔 예시 프리셋이다. `generic` 기본값 전체와 프리셋 작성 안내는 [platforms.md](platforms.md).

```json
{
  "schema_version": 1,
  "name": "예시 플랫폼",
  "count": "utf8_bytes",
  "limits": {
    "main": {"max": 16000},
    "lorebook_entry": {"max": 4500},
    "total": {"max": null}
  },
  "lorebook": {
    "keywords": true,
    "max_keywords": null,
    "match": "substring",
    "case_sensitive": false,
    "scan": {"messages": 2, "roles": ["user", "assistant"]},
    "budget": {"max": null},
    "max_active": null
  },
  "jsx": {
    "globals": [],
    "forbid": ["import", "export"],
    "hooks": ["useState", "useEffect", "useMemo", "useRef"],
    "response": {"syntax": "element", "attribute_format": "json_lenient", "decode": []}
  }
}
```

| 묶음 | 내용 |
|---|---|
| `name` | 화면에 보일 이름. |
| `count` | 용량을 세는 방식 — `utf8_bytes`, `chars`, `tokens:<토크나이저>`. |
| `limits` | **작성할 때의** 용량 제한(메인 프롬프트, 로어북 항목, 전체). 사용 중(`enabled`)인 항목만 센다. |
| `lorebook` | 키워드 사용 여부·개수 제한과 [로어북 활성화](#로어북-활성화) 규칙. |
| `jsx` | 플랫폼이 제공하는 함수(`globals`: 이름, 형식 설명, 미리보기 대역 동작 `log`·`return:<값>`·`random`), 금지 문법(`forbid`), 쓸 수 있는 훅(`hooks`), 응답 속 컴포넌트 표기(`response`: 표기 방식 `element`, 속성 값 읽기 `text`(쓴 그대로 문자열)·`json_lenient`(JSON으로 읽되 작은따옴표·끝 쉼표를 허용하고, JSON 모양이 아닌 값은 쓴 그대로)·`json`(엄격한 JSON), 특수 문자 치환 표 `decode`(`[원래, 바꿀 것]` 또는 `{"from", "to"}` 목록)). 기본값은 `json_lenient`. 동작은 [07-jsx](features/07-jsx.md). |
| (가이드라인) | 목록 필드를 두지 않는다. `platforms/<프리셋 ID>/guidelines/` 안의 `.md` 파일이 이 프리셋의 가이드라인이다([가이드라인](#가이드라인)). |

- 기본 제공은 `generic` 하나이며 읽기 전용이다(앱 기본값과 같음). 특정 플랫폼 프리셋은 사용자가 만들거나(기존 프리셋 복제) 가져온다.
- 섹션 이름은 플랫폼이 아니라 작품 언어에 따르므로 플랫폼 프리셋에 두지 않는다([섹션](#섹션)).

### 로어북 활성화

플랫폼마다 다르므로 플랫폼 프리셋의 `lorebook`에서 정한다. 테스트 화면의 맥락 조립과
편집기의 키워드 검사가 이 규칙을 쓴다. 실제 플랫폼의 활성화와 똑같지는 않고, 프리셋 규칙으로 근사한 것이다. 대상은 사용 중인 `lorebook`·`character` 항목이다.

| 필드 | 뜻 | `generic` 기본값 |
|---|---|---|
| `keywords` | 키워드 활성화를 쓰는지 | `true` |
| `max_keywords` | 항목당 키워드 수 제한 | 제한 없음 |
| `match` | 키워드 비교: `substring`(부분 일치), `word`(단어 단위) | `substring` |
| `case_sensitive` | 대소문자 구분 | `false` |
| `scan.messages` | 키워드를 찾을 최근 메시지 수 | `2` |
| `scan.roles` | 볼 메시지 쪽: `user`, `assistant` | 둘 다 |
| `budget.max` | **대화할 때** 한 턴에 넣을 로어북 총량. 단위는 `count` | 제한 없음 |
| `max_active` | 한 턴에 넣을 최대 항목 수 | 제한 없음 |

선택 순서:

1. `always` 항목을 넣는다.
2. 키워드가 맞은 항목을 `priority` 높은 순(같으면 트리 순서)으로 넣는다.
3. `budget.max`나 `max_active`를 넘는 항목은 뺀다. 테스트는 "키워드는 맞았지만 예산 때문에 빠진 항목"을 따로 보여 준다.

- 이 틀로 표현하기 어려운 규칙(여러 키워드 동시 일치, 넣는 위치 등)은 필요해질 때 필드를 추가한다.

#### 로어북 활성화 옵션 (예약)

플랫폼에 따라 로어북 항목마다 활성화 방식을 따로 정할 수 있다. 나중에 이런 설정을 받을 수 있도록 항목 메타데이터의
`activation` 아래 자리만 정해 둔다. **지금은 편집기가 값을 그대로 보존할 뿐이고, 테스트·검사·내보내기는 읽지 않는다.**
상단 폼에도 아직 나오지 않으며 "기타" 칸에 원문으로 보인다.

```yaml
activation:
  in_start: true        # 시작 상황 안의 키워드로도 활성화할지
  scan_depth: 2         # 키워드를 찾을 범위: 최근 0~5턴 또는 all. 0이면 현재 입력만
  mode: on_match        # on_match: 키워드가 있으면 켬 / off_match: 항상 넣기 항목인데 키워드가 있으면 끔
  group: 날씨           # 같은 그룹에서 활성화된 항목 중 priority가 가장 높은 하나만 남김
  requires: [L002]      # 이 ID의 항목들이 활성화돼 있을 때만 활성화
```

| 필드 | 값 | 없을 때 |
|---|---|---|
| `in_start` | 참/거짓 | `true` |
| `scan_depth` | `0`~`5` 또는 `all` | 플랫폼 프리셋의 `lorebook.scan` |
| `mode` | `on_match`, `off_match` | `on_match` |
| `group` | 문자열 | 그룹 없음 |
| `requires` | 항목 ID 목록 | 조건 없음 |

- 모든 필드는 선택이다. 값이 잘못되면 없는 것으로 본다(서버 `core/lorebook.py`의 `activation_of`).
- 적용할 때 정할 것: 플랫폼 프리셋이 어떤 옵션을 지원하는지 적는 방법, 턴 단위와 프리셋 `scan.messages`(메시지 단위)의 관계,
  `group`·`requires`와 예산(`budget.max`)의 적용 순서, 내보내기 표(`_keywords.md`)에 열을 더할지.

## LLM 연결

위치: `<데이터 루트>/providers.json`

**기본은 로컬 LLM이다.** 데이터 루트를 처음 만들 때 로컬 OpenAI 호환 서버 연결 하나(`local`, `http://127.0.0.1:1234/v1`)를
넣고, 모든 작업의 기본 연결로 정한다. 외부 서비스는 사용자가 직접 추가했을 때만 쓰며, 작품 내용을 외부로 보내는 일을 최소화한다.

```json
{
  "schema_version": 1,
  "providers": {
    "local": {
      "name": "로컬 LLM",
      "type": "openai_compatible",
      "base_url": "http://127.0.0.1:1234/v1",
      "key": null,
      "trusted": false,
      "models": {"qwen3-32b": {"context": 32768, "tokenizer": null}}
    },
    "openrouter": {
      "name": "OpenRouter",
      "type": "openai_compatible",
      "base_url": "https://openrouter.ai/api/v1",
      "key": "secret:openrouter",
      "trusted": false,
      "models": {"some-model": {"context": 131072, "price": {"input_per_mtok": 1.0, "output_per_mtok": 4.0}}}
    }
  },
  "tasks": {
    "compression": {"provider": "local", "model": "qwen3-32b", "params": {"temperature": 0.3}},
    "image_prompt": {"provider": "local", "model": "qwen3-32b", "params": {"temperature": 0.2}}
  }
}
```

| 필드 | 뜻 |
|---|---|
| `providers` | 연결 목록. 키가 연결 ID. |
| `type` | 연결 방식. 처음 범위는 `openai_compatible` 하나다(LM Studio·llama.cpp·vLLM 같은 로컬 서버, 그리고 같은 형식을 쓰는 외부 서비스). 다른 방식은 필요해질 때 추가한다. `mock`은 서버 없이 정해진 답을 내는 모의 연결이다(테스트·오프라인 확인용). |
| `default_model` | 이 연결의 기본 모델. 작업에 모델을 정하지 않으면 이것을 쓴다. |
| `key` | 금고 항목 참조(`secret:<이름>`). 필요 없으면 `null`. |
| `local_gpu` | 선택. 이 연결의 모델이 이 PC의 GPU에서 도는지. `true`면 요청이 이미지 작업과 GPU를 번갈아 쓴다. 없으면 주소가 이 PC일 때 `true`로 본다. |
| `trusted` | 같은 네트워크의 "내 서버"로 표시. `true`거나 주소가 이 PC(`127.0.0.1`, `localhost`, `::1`)면 로컬로 보고 외부 전송 확인을 하지 않는다. |
| `models` | 쓸 모델. `context`(맥락 길이, 토큰), `max_output`(선택, 최대 출력 토큰), `context_source`(`manual`·`service`·`table`, 값을 어디서 얻었는지), `tokenizer`(토크나이저 이름, 없으면 추정), `price`(선택, 100만 토큰당 가격. 사용자가 입력하며, 없으면 비용 대신 토큰 수만 보여 준다). 토큰 수는 0보다 큰 정수. |
| `context_cap` | 선택. 에이전트가 한 요청에 쓸 맥락의 상한(토큰). 없으면 131,072. |
| `tasks` | 작업별 기본 연결·모델·생성 설정. 작업: `compression`, `image_prompt`, `jsx_prompt`, `authoring`, `consistency`, `chat_test`, `agent`. 정하지 않은 작업은 `local`의 `default_model`을 쓴다. |

- 사용량 기록(`usage/<연-월>.jsonl`)은 요청 하나에 한 줄: 시각, 연결 ID, 모델, 작업, 작품 ID, 입력·출력 토큰, 비용(가격이 있을 때).
  요청·응답 내용은 남기지 않는다.
- 토크나이저(`tokenizers/<이름>/`)는 Hugging Face 형식 `tokenizer.json` 또는 앱이 아는 형식의 파일을 둔다. 플랫폼 프리셋의
  `count: "tokens:<이름>"`과 모델의 `tokenizer`가 이 이름을 가리킨다. 앱에 함께 넣을 토크나이저는 구현 단계에서 정한다.

## 가이드라인

가이드라인은 세 곳의 `guidelines/` 폴더에 둔다: 전역(`<데이터 루트>/guidelines/`), 플랫폼 프리셋
(`platforms/<프리셋 ID>/guidelines/`), 작품(`<작품 폴더>/.atelierx/guidelines/`). **폴더 안의 `.md` 파일이 곧 목록**이며,
따로 목록을 적지 않는다.

- 같은 이름의 가이드라인은 **작품 → 연결된 플랫폼 프리셋(`tags`의 뒤쪽부터) → 전역** 순서로 먼저 찾은 것을 쓴다.
  덮어쓴 파일이 있으면 화면에서 "작품용으로 바꿈"을 표시하고 원래 것과 비교할 수 있게 한다.
- 기능은 아래 정해진 이름으로 가이드라인을 찾는다. 같은 이름을 전역에 두면 모든 작품의 기본이 되고, 플랫폼 프리셋에 두면
  그 플랫폼용 규칙이, 작품에 두면 그 작품만의 규칙이 된다.
- 정해진 이름이 아닌 파일은 사람이 읽는 참고 문서다. LLM 작업을 할 때 추가 지침으로 골라 넣을 수 있다.
- 앱은 정해진 이름의 기본 가이드라인을 `app/` 안에 갖고 있다가, 데이터 루트를 처음 만들 때 전역 `guidelines/`에 복사한다.
  사용자가 고친 뒤에도 설정 화면에서 기본값으로 되돌릴 수 있다.

### 정해진 이름

| 이름 | 쓰는 곳 | 내용 예 |
|---|---|---|
| `platform.md` | 챗봇에 들어갈 글을 만드는 LLM 작업: 압축(05), 뼈대 작성(04), JSX 프롬프트용 문구(07). 앞부분에 함께 넣음 | 플랫폼 공통 규칙: 형식 제약, 금지 표현, 출력 방식 |
| `compression.md` | 압축(05) | 프롬프트 압축 규칙: 지킬 것, 줄일 것, 문체 |
| `image-prompt.md` | 이미지 프롬프트 변환(06) | 태그 작성 규칙, 모델 계열별 주의점 |
| `authoring/<규모>.md` | 뼈대 작성(04) | 규모별(`single`, `ensemble`, `simulation`) 뼈대 질문(`## 질문` 아래 목록을 앱이 양식으로 씀)과 구성 원칙 |
| `consistency.md` | 모순 검사(04) | 검사할 항목과 판단 기준 |
| `jsx.md` | JSX 프롬프트용 문구 만들기(07)와 JSX 편집 화면의 참고 | 플랫폼 JSX 사용 규칙: 제공 함수, 금지 사항, 권장 패턴, 응답에 넣는 방식 |
| `agent/<모드>.md` | 에이전트 패널(11)의 모드 하나 | 모드 카드 정보(머리 메타데이터)와 대화 방식 |

- 이름은 기능 문서를 쓰면서 늘어날 수 있다. 새 이름은 이 표에 추가한다.

### 에이전트 모드 지침

`agent/` 폴더의 `.md` 파일 하나가 모드 하나다. 파일 이름(확장자 뺌)이 모드 ID다. 같은 ID는 작품 → 플랫폼 프리셋 → 전역 순서로
먼저 찾은 것을 쓰고, 목록은 세 곳을 합친다.

```markdown
---
name: 캐릭터 다듬기
description: 캐릭터 파일의 말투와 설정을 대화로 다듬고 파일 전체를 제안합니다.
scope: file
order: 30
uses: [consistency.md]
---
(대화 방식: 먼저 물을 것, 정리 순서, 끝에 내놓을 것)
```

| 필드 | 뜻 |
|---|---|
| `name` | 카드 이름. 없으면 모드 ID. |
| `description` | 카드 설명 한 줄. |
| `scope` | 기본 범위: `file`(현재 파일), `work`(작품 전체). 없으면 `file`. |
| `order` | 카드 순서(작은 것부터). 없으면 100. |
| `uses` | 선택. 이 모드와 함께 에이전트에 보낼 지침 이름 목록(`[jsx.md, consistency.md]`). 이름마다 작품 → 플랫폼 프리셋 → 전역 → 기본값 순서로 찾은 파일 전체를 모드 지침 뒤에 넣는다. 모드(`agent/…`), `platform.md`(늘 들어감), 잘못된 이름은 무시, 최대 8개. 찾지 못한 이름은 요청 요약에 "없음"으로 남는다. |

- 앱 고정 지시는 파일이 아니라 앱 안에 있고 설정 화면에서 읽기만 할 수 있다.
- 요청 조립 순서와 앱 고정 지시와의 관계는 [03-llm](features/03-llm.md)의 "요청 조립".

## 내보내기

플랫폼에 올릴 파일을 만든다. 사용자 트리와 같은 경로·이름으로 내보내므로 화면에 보이는 그대로 나간다.

```text
<내보낼 폴더>/
├── 메인.md                       사용 중인 메인 프롬프트
├── 인물/
│   ├── 한서윤.md
│   └── 김도현.md
├── 세계관/학교.md
├── UI/상태창.jsx
└── _keywords.md                  로어북·캐릭터 항목별 ID·키워드·우선순위·항상 넣기 표
```

- 내보내는 것: 사용 중(`enabled`)인 `main`·`start`·`lorebook`·`character`·`jsx` 항목. 빼는 것: `note`, 사용하지 않는 항목, 항목이 아닌
  파일, `.atelierx/`.
- 각 파일에는 메타데이터 머리(`.md`의 앞부분 메타데이터, `.jsx`의 머리 주석)를 뗀 본문만 들어간다. 본문은 저장된 그대로다
  (용량 게이지와 내보낸 분량이 같다).
- 키워드처럼 플랫폼에 따로 입력하는 값은 `_keywords.md` 표 하나에 모은다(메타데이터 머리를 떼므로 활성화 설정을 여기로 옮긴다).
  순서는 `work.json`의 `order`를 따른다. `_keywords.md`는 내보내기 최상위의 예약 이름이다. 내보낼 항목 중 최상위에 같은 이름
  (대소문자 무시)이 있으면 검사가 경고하고, 이름을 바꾸기 전에는 내보내지 않는다.
- `_keywords.md`의 표 형식. 열 제목과 `항상 넣기` 값은 작품 언어(`work.json`의 `language`)를 따른다(이후 일반 폴더 가져오기를
  만들면 두 언어 모두 읽는다):

  ```markdown
  | 경로 | ID | 이름 | 키워드 | 우선순위 | 항상 넣기 |
  |---|---|---|---|---|---|
  | 인물/한서윤.md | C001 | 한서윤 | 서윤, 한서윤, 반장 | 100 | 아니요 |
  ```

  영어 작품의 열 제목은 `| Path | ID | Name | Keywords | Priority | Always |`이다.

  `경로`는 내보낸 폴더 기준 상대 경로이고 항목을 찾는 열쇠다. `ID`는 플랫폼에 옮길 때 대조용이며 없으면 빈칸이다. 키워드는
  쉼표와 공백(`, `)으로 나눈다. 키워드 안에 쉼표가 있으면 그 키워드를 큰따옴표로 감싼다. 칸 안의 `|`는 `\|`로 쓴다.
  `항상 넣기`는 `예`/`아니요`(영어 작품은 `yes`/`no`).
- 이미 파일이 있는 폴더로 내보낼 때는 덮어쓰기 전에 확인을 받고, 작품에 없는 항목의 파일이 남아 있으면 목록으로 보여 준다. 내보내기는 그 파일들을 지우지 않는다.
- 내보낼 때 `export` 스냅샷을 만들 수 있다. 배포 표시는 사용자가 붙인다.

## 휴지통

앱에서 지우는 것은 모두 휴지통으로 옮긴다. 휴지통에서 되살리거나 완전 삭제할 수 있다. 자동으로 비우지 않는다.

```text
<작품 폴더>/.atelierx/trash/<시각>-<짧은 id>/   작품 안에서 지운 것 (항목·폴더, 이미지 데이터 …)
├── entry.json
└── <원래 상대 경로 그대로의 파일들>

<데이터 루트>/.trash/<시각>-<작품·프리셋 ID>/   지운 작품 전체, 지운 플랫폼 프리셋
├── entry.json
└── <작품 폴더 전체 (.atelierx 포함) 또는 프리셋 폴더>
```

```json
{
  "schema_version": 1,
  "kind": "item",
  "deleted_at": "2026-10-02T16:00:00+09:00",
  "paths": ["인물/한서윤.md", ".atelierx/image/characters/C001/"],
  "ids": ["C001"],
  "size": 48213
}
```

| 필드 | 뜻 |
|---|---|
| `kind` | 지운 것의 종류: `item`, `folder`, `image`, `work`, `platform_preset` 등. |
| `paths` | 원래 경로(작품 폴더 기준. `work`·`platform_preset`은 데이터 루트 기준). 함께 지운 것은 한 묶음으로 둔다. |
| `ids` | 묶음에 들어 있는 항목 ID. 되살릴 때 충돌 검사에 쓴다. |
| `size` | 차지하는 크기. 휴지통 화면에 보여 준다. |

- 한 번에 지운 것은 한 묶음이다. 캐릭터를 지울 때는 이미지 데이터(`.atelierx/image/characters/<ID>/`)를, JSX를 지울 때는
  예시 props(`.atelierx/jsx/<ID>/`)를 함께 지울지 묻고, 함께 지우면 같은 묶음에 넣는다. 함께 지우지 않은 이미지 데이터는
  이미지 화면에 "항목 없는 이미지 데이터"로 보인다.
- **되살리기**: 묶음 전체를 원래 경로로 옮긴다. 같은 경로에 파일이 있으면 새 이름을, 같은 ID가 이미 있으면 새 ID를
  고르게 한다([ID](#id)의 ID 바꾸기와 같은 절차). 되살리기 전에 `before_bulk` 스냅샷을 만든다.
- **완전 삭제**: 휴지통 화면에서 묶음 하나 또는 전체를 확인을 받은 뒤 지운다. 이것만이 앱에서 데이터를 영구히 지우는
  방법이다. 지우기 전 시점의 스냅샷에 남아 있는 내용은 그대로 둔다(이력의 일부).
- 출력 루트의 파일(생성 이미지·로그)은 앱에서 지우면 **출력 휴지통**(`<출력 루트>/.trash/`)으로 간다. 같은 휴지통 화면에서
  되살리기·완전 삭제를 한다. 캐릭터 이미지 데이터를 완전 삭제할 때 출력 루트의 해당 캐릭터 폴더도 출력 휴지통으로 옮길지 따로 묻는다.
- LoRA 폴더의 파일은 다른 프로그램과 함께 쓰므로 앱이 지우지 않는다.
- 휴지통은 파일 트리·내보내기·스냅샷에 넣지 않는다. 설정 화면에서 전체 크기를 보여 준다.

## 스냅샷

위치: `<작품 폴더>/.atelierx/history/`

```text
history/
├── objects/<해시 앞 2자>/<sha256>     파일 내용 (같은 내용은 한 번만 저장)
└── snapshots/<시각>-<짧은 id>.json    파일 이름(확장자 제외)이 스냅샷 id
```

- `<시각>`은 밀리초까지 쓴다(`20261002T150000123`). 이름 순서가 곧 만든 순서다. 밀리초가 없는 옛 id도 같은 초 안에서는 앞에 온다.

```json
{
  "schema_version": 1,
  "parent": "20261002T143000-9f8e",
  "created_at": "2026-10-02T15:00:00+09:00",
  "reason": "before_llm",
  "label": "압축 후보 채택 전",
  "release": null,
  "files": {"메인.md": "sha256…", "인물/한서윤.md": "sha256…", ".atelierx/work.json": "sha256…"}
}
```

- 대상: 사용자 트리의 항목(`.md`·`.jsx`)과 `.atelierx/`의 파일. 제외: `.atelierx/`의 `history/`, `trash/`, `drafts/`, `tests/runs/`,
  그리고 항목이 아닌 파일(이미지, 빌드 결과, 스크립트 등 — 크고 자주 바뀌어 이력을 부풀림).
- `reason`: `manual`(직접), `save`(저장 묶음), `before_llm`(LLM 결과 채택 직전), `before_restore`(되돌리기 직전),
  `before_bulk`(여러 파일을 한꺼번에 바꾸기 직전: ID 바꾸기, 이름 일괄 변경, 폴더 이동, 휴지통에서 되살리기, 형식 변환 등),
  `import`(가져오기 직후), `export`(내보낼 때, 선택).
- 지우기는 휴지통이 맡으므로 지우기 직전 스냅샷은 따로 만들지 않는다.
- `release`: 배포 표시. 예: `{"note": "1.2 배포", "at": "…"}`. 배포 표시된 스냅샷, `manual`, `before_bulk`는 자동 정리하지 않는다.
- 되돌리기는 파일 하나 또는 작품 전체. 되돌리기 전에 항상 `before_restore` 스냅샷을 만든다.
- 자동 정리: 오래된 `save` 스냅샷만 정리(기본: 최근 200개 + 하루 하나씩 30일). 어느 스냅샷에서도 쓰지 않는 객체를 지운다.
- `save` 스냅샷은 저장할 때마다가 아니라 일정 간격(기본 10분)으로 묶어서 만든다.

## 버전

| 버전 | 위치 | 무엇의 버전 |
|---|---|---|
| `layout_version` | `<데이터 루트>/atelierx.json` | 데이터 루트의 폴더 구조(`platforms/`, `image/`, `guidelines/` 등의 배치) |
| `layout_version` | `.atelierx/work.json` | 작품의 `.atelierx/` 구조. 작품 폴더가 다른 데이터 루트로 옮겨져도 스스로 판단할 수 있게 작품마다 둔다 |
| `schema_version` | 각 파일 | 그 파일 하나의 형식 |

- 앱보다 오래된 버전이면 변환을 제안한다. 변환 전에 작품마다 `before_bulk` 스냅샷을 만들고, 데이터 루트 단위 변환이면
  백업 폴더를 만든다.
- 앱보다 새 버전이면 해당 작품·파일을 읽기 전용으로 연다(새 앱이 만든 데이터를 옛 앱이 망가뜨리지 않게).
