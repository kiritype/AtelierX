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

### 받기·찾기

받기(주소나 ID, 이어 받기, 직접 받은 파일 넣기)와 찾기(Civitai 검색)는 이 문서에 이어서 적는다.

## 데이터

| 파일 | 읽기·쓰기 | 형식 |
|---|---|---|
| `data/image/model-info.json` | 읽기·쓰기 | [모델 정보](../data-model.md#모델-정보-dataimagemodel-infojson) |
| 모델 옆 `<파일>.cm-info.json`, `<파일>.preview.*` | 읽기 | Stability Matrix |
| `config/image/models.json` | 읽기·쓰기 | 공유 모델 폴더, 직접 지정한 계열 |

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
