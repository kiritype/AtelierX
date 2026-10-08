# 26. 모델

## 목적

모델을 다루는 곳이 흩어져 있었다. 모델 폴더와 계열 지정은 설정 → 이미지에, 필수 모델은 설정 → 설치에, 실제 고르기는 생성 화면에 있었다.
이미지 메뉴의 **모델** 화면 하나로 모으고, Civitai에서 모델 정보를 찾는다(#161).

## 사용 흐름

### 내 모델

1. 이미지 메뉴 → "준비" → 모델. 그림체 프리셋 화면과 같은 탐색 틀(`components/explorer/Explorer`)을 쓴다.
2. 이미지 생성 서버가 가진 체크포인트·디퓨전 모델·LoRA·텍스트 인코더·VAE·업스케일 모델이 카드로 보인다.
   - 카드: Stability Matrix 미리보기(`<파일>.preview.*`, 있으면), 이름(Civitai 이름이 있으면 그것), 종류, 계열, 출처.
   - 거르기: 종류, 계열, 출처(Civitai·학습·모름), 기반 모델. 찾기는 이름·기반 모델·트리거 단어.
3. 카드를 누르면 오른쪽에 파일 위치·크기, 출처, Civitai 이름·판·작성자·주소, 기반 모델, 트리거 단어(눌러 복사), 라이선스가 보인다.
4. **계열**: "자동으로 정함" 또는 Anima·SDXL·IL을 직접 고른다. 판단 근거가 함께 보인다. 계열 판단 순서는
   폴더 이름 → 직접 지정 → 조회한 Civitai 기반 모델 → Stability Matrix `.cm-info.json` → 파일 헤더.
   설정 → 이미지에는 공유 모델 폴더 경로만 남는다.
5. **Civitai 정보 조회**: 파일의 SHA256을 계산해 Civitai(`/api/v1/model-versions/by-hash/…`, 키 없이 됨)에서 찾는다. 찾으면 모델·판
   이름, 기반 모델, 트리거 단어, 작성자, 라이선스를 저장한다. 못 찾으면 "Civitai에 없음"으로 기억한다.
   - 해시는 누른 파일만 계산하고, 파일 크기·수정 시각과 함께 기억해 다시 계산하지 않는다(큰 파일은 GB당 수 초).
   - 저장은 앱 쪽(`data/image/model-info.json`)에만 한다. 모델 폴더에는 아무것도 쓰지 않는다.
6. 학습한 LoRA(`atelierx\…`, [결정 0025](../decisions/0025-lora-folder-link.md))는 출처가 "학습"이다.

### 받기

1. 모델 화면 → **받기** 탭. Civitai API 키가 없으면 위에 안내가 보인다(키는 설정 → 이미지 → 모델 받기, 금고에 저장).
2. Civitai 모델 페이지 주소, 다운로드 주소(`/api/download/models/<판>`) 또는 모델 번호를 붙여 넣고 **읽기**.
   모델 이름·종류·작성자·NSFW 여부·라이선스와 판 목록(기반 모델, 트리거 단어, 파일·크기·종류)이 보인다. 주소에 판이 있으면 그 판을 고른다.
3. 파일의 **받기**를 누르면 받기 목록에 들어간다. 넣을 곳은 그 종류의 이미지 생성 서버 폴더(공유 모델 폴더 우선) 아래 계열 폴더
   (`anima/`, `sdxl/`)다. **하위 폴더**로 바꿀 수 있다. Anima 기반 "Checkpoint"는 디퓨전 모델 폴더로 간다.
4. 받기는 한 번에 하나씩 한다.
   - 받기 전에 남은 디스크 공간을 확인한다(필요한 크기 + 512 MB).
   - `<파일>.part`로 받고, 끊기면 **이어 받기**로 남은 부분만 받는다(HTTP Range). 앱을 다시 켜면 받던 것과 기다리던 것은 "멈춤"이 되고,
     저절로 시작하지 않는다(**이어 받기**로 다시 시작).
   - 넣을 곳에 같은 이름의 파일이 생겼으면(받기 목록에 넣은 뒤 다른 파일을 옮겨 놓은 경우) 덮어쓰지 않고 실패로 남긴다. 다 받은 파일은
     `.part`로 남아, 그 파일을 치운 뒤 **이어 받기**를 누르면 다시 받지 않고 끝난다.
   - 끝나면 Civitai가 준 SHA256과 비교하고, 맞으면 이름을 바꾼다. 틀리면 지우고 실패로 남긴다.
   - 키가 필요한 파일인데 키가 없으면(401·403, 또는 로그인 페이지가 오면) 그렇게 알린다.
   - 받은 파일의 Civitai 정보는 해시와 함께 모델 정보에 저장한다(출처 "Civitai", 트리거 단어 등).
5. 목록에서 취소·이어 받기·목록에서 지우기(받은 파일은 남음)를 한다.

### 직접 받은 파일 넣기

키가 없거나 브라우저로 받았을 때. 받기 탭 아래 **직접 받은 파일 넣기**를 펼친다.

1. 다운로드 폴더(바꿀 수 있음)의 모델 파일(`.safetensors`, `.ckpt`, `.pt` …)이 보인다.
2. **확인**: 해시를 계산해 Civitai에서 찾고, 종류·계열을 제안한다.
3. 종류·하위 폴더를 고르고 **옮기기**. 찾은 Civitai 정보는 모델 정보에 저장한다.

### 찾기

1. 모델 화면 → **찾기** 탭. 검색어, 종류(Checkpoint·LORA·LoCon·DoRA·임베딩·VAE·업스케일러), 기반 모델(Anima·Illustrious·NoobAI·Pony·
   SDXL 1.0·Krea 2), 정렬(평가·받은 수·최신)로 Civitai를 찾는다. 처음에는 LORA·Anima·평가 순이다. 한 번에 24개, **더 보기**로 이어 본다.
2. **NSFW 포함**: 기본 꺼짐, 마지막 선택을 이미지 설정(`downloads.nsfw`)에 기억한다. 끄면 성인 모델을 빼고, 일반 모델의 성인 등급 미리보기
   그림도 숨긴다(`nsfwLevel` 1보다 큰 그림). 주소를 직접 붙여 넣어 받는 경우는 이 체크와 상관없다.
3. 카드: 미리보기 그림(Civitai 주소를 리퍼러 없이 불러옴, 동영상은 표시하지 않음), 이름, 작성자·판, 종류, 기반 모델, 받은 수·좋아요.
   누르면 받기 탭이 열리고 그 판으로 읽는다.

## 데이터

| 파일 | 읽기·쓰기 | 형식 |
|---|---|---|
| `data/image/model-info.json` | 읽기·쓰기 | [모델 정보](../data-model.md#모델-정보-dataimagemodel-infojson) |
| 모델 옆 `<파일>.cm-info.json`, `<파일>.preview.*` | 읽기 | Stability Matrix |
| `config/image/models.json` | 읽기·쓰기 | 공유 모델 폴더, 직접 지정한 계열 |
| `config/image/downloads.json` | 읽기·쓰기 | Civitai 키의 금고 항목(`secret:…`), 찾기의 NSFW 기본값 |
| `state/model-downloads.json` | 읽기·쓰기 | 받기 목록(상태, 받은 크기, 오류). 최근 200개 |

## 규칙

- 모델 폴더에는 받은 파일 말고는 쓰지 않는다. Stability Matrix의 기록은 읽기만 한다.
- 해시와 Civitai 정보는 사용자가 조회를 눌렀을 때만 만든다. 목록을 열 때는 네트워크를 쓰지 않는다.
- 이미지 생성 서버의 폴더 목록은 30초 동안 저장해 두고 쓴다(파일마다 묻지 않음).

## API

| 요청 | 내용 |
|---|---|
| `GET /api/image/models/list` | 내 모델 `{items: [{kind, name, file, path, size, family, family_by, preview, info, source, hashed}]}` |
| `POST /api/image/models/lookup` | `{kind, name}` → 해시 계산 + Civitai 조회 후 그 항목 |
| `GET /api/image/models/preview?kind=&name=` | Stability Matrix 미리보기 그림 |
| `PUT /api/image/models/family` | 계열 직접 지정 `{kind, name, family}` |
| `POST /api/image/models/read` | `{address}` → 모델·판·파일·라이선스 |
| `GET /api/image/models/search?query=&kind=&base=&sort=&nsfw=&cursor=` | Civitai 검색 한 쪽 `{items, next}` |
| `GET·POST /api/image/models/downloads` | 받기 목록 / 넣기 `{model, version, file, subfolder?}` |
| `POST /api/image/models/downloads/{id}/{cancel·resume·remove}` | 받기 항목 다루기 |
| `GET /api/image/models/downloaded?folder=` | 폴더의 모델 파일 |
| `POST /api/image/models/downloaded/inspect·place` | 해시·Civitai 확인 / 옮기기 `{path, kind, subfolder, sha256?, info?}` |
