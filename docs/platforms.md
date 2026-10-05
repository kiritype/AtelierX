# 플랫폼 프리셋

챗봇을 올릴 플랫폼마다 다른 규칙을 플랫폼 프리셋으로 정리하는 방법. 형식은 [data-model.md 플랫폼 프리셋](data-model.md#플랫폼-프리셋),
편집 화면은 [10-settings](features/10-settings.md).

## 프리셋이 정하는 것

| 묶음 | 정하는 것 | 쓰는 곳 |
|---|---|---|
| `count` | 용량을 세는 단위 | 용량 게이지, 검사, 압축 목표 |
| `limits` | 작성할 때의 용량 제한 | 용량 게이지, 검사, 압축 목표, 내보내기 미리보기 |
| `lorebook` | 키워드 사용 방식과 대화 때 로어북이 들어가는 규칙 | 편집기 키워드 검사, 테스트 화면 맥락 조립 |
| `jsx` | 컴포넌트에서 쓸 수 있는 것과 응답 속 컴포넌트 표기 | JSX 정적 검사·미리보기, 프롬프트용 문구, 테스트 화면 응답 렌더링 |
| 가이드라인 폴더 | 이 플랫폼용 LLM 지침 | 모든 LLM 작업 |

섹션 이름은 작품 언어를 따르므로 프리셋에 두지 않는다.

## `generic` 기본값

앱 기본값이자 기본 제공 프리셋. 읽기 전용이며, 고치려면 복제한다.

```json
{
  "schema_version": 1,
  "name": "범용",
  "count": "utf8_bytes",
  "limits": {
    "main": {"max": null},
    "lorebook_entry": {"max": null},
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
    "hooks": ["useState", "useEffect", "useMemo", "useRef", "useCallback"],
    "response": {"syntax": "element", "attribute_format": "json_lenient", "decode": []}
  }
}
```

| 값 | 기본 | 뜻 |
|---|---|---|
| `count` | `utf8_bytes` | UTF-8 바이트. 한글 한 글자 = 3바이트 |
| `limits.*.max` | 없음 | 제한 없음. 게이지는 숫자만 보여 준다 |
| `lorebook.match` | `substring` | 키워드가 메시지 안 어디든 들어 있으면 활성화 |
| `lorebook.scan.messages` | `2` | 직전 사용자 메시지와 직전 응답에서 찾음 |
| `lorebook.budget.max` | 없음 | 활성화된 항목은 모두 들어감 |
| `jsx.forbid` | `import`, `export` | 컴포넌트는 파일 하나 안에서 끝나야 함 |
| `jsx.hooks` | React 기본 훅 다섯 개 | 그 밖의 훅은 오류 |
| `jsx.response` | `element`, `json_lenient` | 응답에 `<컴포넌트 속성='…' />`로 들어간다. 속성 값은 JSON으로 읽고, JSON 모양이 아닌 값(`C001`)은 쓴 그대로. 따옴표 안 값을 그대로 넘기는 플랫폼은 `text` |

`generic`의 가이드라인 폴더는 비어 있다. 전역 가이드라인을 그대로 쓴다.

## 새 플랫폼 프리셋 만들기

1. 설정 → 플랫폼 프리셋 → "새 프리셋" → 바탕 `generic` → ID(영문, 예: `my-platform`)와 이름.
2. 아래 확인 목록으로 플랫폼 규칙을 조사해 값을 채운다.
3. 플랫폼 전용 가이드라인을 만든다(아래 "프리셋 가이드라인").
4. 작품에 그 ID를 태그로 붙여 연결한다. 자주 쓰면 "새 작품에 기본으로 연결"을 켠다.

### 확인 목록

| 질문 | 넣을 곳 |
|---|---|
| 메인 프롬프트·로어북 항목·전체의 최대 길이는? 바이트인가, 글자인가, 토큰인가? | `count`, `limits` |
| 토큰이면 어떤 토크나이저인가? | `count: "tokens:<이름>"`, `data/tokenizers/` |
| 로어북 키워드는 몇 개까지? 대소문자를 구분하나? 단어 단위인가? | `lorebook.max_keywords`, `case_sensitive`, `match` |
| 키워드를 최근 몇 개 메시지에서 찾나? 사용자 쪽만인가? | `lorebook.scan` |
| 한 턴에 로어북이 얼마나, 몇 개까지 들어가나? | `lorebook.budget`, `max_active` |
| 컴포넌트에서 쓸 수 있는 플랫폼 함수는? 각각 무엇을 하나? | `jsx.globals` |
| 쓸 수 없는 문법·훅은? | `jsx.forbid`, `jsx.hooks` |
| 응답에 컴포넌트를 어떤 모양으로 넣나? 속성 값 안의 특수 문자를 따로 표기하나? | `jsx.response` |
| 시작 상황을 여러 개 둘 수 있나? | 시작 상황 항목을 몇 개 사용으로 둘지(앱 규칙은 여러 개 허용) |

모르는 값은 비워 둔다(`null`). 비운 값은 앞 단계의 값(앱 기본값 또는 앞서 연결된 프리셋)을 쓴다.

### `jsx.globals` 적는 법

```json
"globals": [
  {"name": "sendMessage", "signature": "(text: string) => void", "description": "사용자 메시지로 보냄", "stub": "log"},
  {"name": "getVariable", "signature": "(key: string) => string", "description": "대화 변수 읽기", "stub": "return:\"\""},
  {"name": "rollDice", "signature": "(sides: number) => number", "description": "주사위", "stub": "random"}
]
```

- `stub`: 미리보기에서의 대역 동작. `log`(호출만 기록), `return:<JSON 값>`(그 값을 돌려줌), `random`(무작위 수).
- 정적 검사는 여기 적힌 이름을 "정의된 전역"으로 본다.

### `jsx.response.decode` 적는 법

플랫폼이 응답 속 속성 값에서 따옴표·줄바꿈 같은 문자를 다른 표기로 바꿔 쓰게 하는 경우, 앱이 읽기 전에 되돌릴 표를 적는다.

```json
"decode": [["⟪NL⟫", "\n"], ["⟪Q⟫", "\""]]
```

앞에서부터 차례로 바꾼다.

## 프리셋 가이드라인

`platforms/<ID>/guidelines/`에 같은 이름의 파일을 두면 전역 가이드라인 대신 쓰인다([data-model.md 정해진 이름](data-model.md#정해진-이름)).

| 파일 | 플랫폼마다 달라지는 것 |
|---|---|
| `platform.md` | 챗봇에 들어갈 글을 만드는 LLM 작업(압축, 뼈대 작성, JSX 프롬프트용 문구)에 깔리는 규칙: 응답 형식, 금지 표현, 지원하는 Markdown, 분량 |
| `jsx.md` | 컴포넌트 작성 규칙과 응답에 넣는 방식 — 프롬프트용 문구 만들기에 쓰임 |
| `compression.md` | 이 플랫폼에서 잘 듣는 압축 방식(예: 목록형이 나은지 문장형이 나은지) |

나머지 이름(`image-prompt.md`, `consistency.md`, `authoring/`)은 보통 플랫폼과 관계없어 전역 것을 쓴다.

## 여러 프리셋 함께 쓰기

작품 태그에 프리셋 ID를 여러 개 붙이면 `tags` 순서대로 겹친다(뒤가 앞을 덮음). 예:

- `my-platform` — 플랫폼 공통 규칙
- `my-platform-long` — 같은 플랫폼의 긴 맥락 요금제용으로 `limits`만 바꾼 프리셋

태그를 `["my-platform", "my-platform-long"]` 순서로 붙이면 공통 규칙 위에 제한만 바뀐다. 작품만의 값은 `overrides`에 둔다.

## 공유

- 내보내기: 프리셋 폴더(`preset.json` + `guidelines/`)를 그대로 복사한다. 인증 정보는 들어 있지 않다.
- 가져오기: 받은 폴더를 고르면 `data/platforms/`에 복사한다. 같은 ID가 있으면 새 ID를 고르게 한다.
- 프리셋을 공개 저장소에 올릴 때는 플랫폼 이용 약관상 규칙을 공개해도 되는지 확인한다.
