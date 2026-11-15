# 기본 콘텐츠 배포 준비

앱 릴리스와 별도로 공개 HTTPS 저장소(R2 등)에 기본 그림체 ZIP, 감정 프롬프트 JSON, 카탈로그를 게시한다.
앱에 포함된 기본 배포원을 사용하며, 로컬 설정으로 다른 배포원을 지정할 수 있다. 계정·버킷 생성이나 업로드를 자동 실행하지 않는다.

## 현재 배포원

기본 카탈로그는 [cftm.net/atelierx/default-content/catalog.json](https://cftm.net/atelierx/default-content/catalog.json)이다.
R2의 `atelierx/default-content/` 전용 경로에 게시하며, 팩과 해당 버전의 카탈로그는
`atelierx/default-content/<콘텐츠 버전>/` 아래에 보관한다. 프리셋 ZIP에는 연결된 WebP 미리보기도 포함한다.

버전별 파일은 장기 캐시를 허용한다. 고정 카탈로그는 `Cache-Control: no-cache, must-revalidate`로 게시하고,
새 버전 파일의 공개 다운로드와 해시를 확인한 뒤 마지막에 갱신한다. 기존 버전 파일은 덮어쓰지 않는다.

## 파일 생성

저장소의 개발 환경에서 실행한다. 원본 앱 폴더는 읽기만 하고, 출력은 원본 밖의 새 폴더에 만든다.

```powershell
uv run python tools/build_content_pack.py --source-root C:/MyAtelierX --output C:/content-review/2026.11 --version 2026.11 --base-url https://content.example.com/2026.11 --author "배포자" --license "콘텐츠 이용 조건"
```

`--presets <UUID...>`와 `--expressions <UUID...>`로 범위를 정할 수 있다. 생략하면 전역 항목 전체를 사용한다.
배포 주소가 아직 없으면 `--base-url`을 생략해 `.invalid` 예시 주소를 담은 검토본을 만들고, 주소 확정 후 새 출력 폴더로 다시 생성한다.
이 예시 주소를 실제 앱 설정에 연결하지 않는다. 기존 출력 파일은 덮어쓰지 않는다.

생성 결과는 다음 세 파일이다.

- `presets-<콘텐츠 버전>.zip`: 프리셋·미리보기·연결 공통 프롬프트·알려진 모델 출처. 모델 바이너리는 포함하지 않는다.
- `expressions-<콘텐츠 버전>.json`: 표정 프롬프트와 연결 구도.
- `catalog.json`: 두 팩의 버전·크기·SHA256·최소 앱 버전·작성자·이용 조건·HTTPS URL.

출처는 프리셋 자체 정보, 검증된 앱 모델 조회/다운로드 기록, 설정된 공유 모델 폴더의 정보 파일에서 모은다.
파일명으로 Civitai의 다른 파일을 추측하지 않는다. 알려진 해시나 정확한 버전/파일 식별 정보가 없는 항목은 받는 앱에서 수동 연결 대상으로 표시한다.
작성자와 이용 조건은 콘텐츠에 맞게 입력하고, 팩에 포함된 항목과 미리보기를 검토한다. 원본 설정·금고·작품 전체를 복사하는 방식은 사용하지 않는다.

## 게시와 연결

1. 버전별 폴더의 ZIP과 JSON을 공개 HTTPS 주소에 먼저 올린다. 브라우저에서 내려받은 파일의 해시가 카탈로그와 일치하는지 확인한다.
2. 해당 파일을 가리키는 `catalog.json`을 마지막에 게시한다. 새 콘텐츠는 새 버전·새 파일명으로 만들며 자동 덮어쓰기 업데이트를 사용하지 않는다.
3. 앱의 `config/image/content-source.json`에 다음을 저장한다. 정식 앱에 공통 배포원을 넣을 때는 `defaults/content-source.json`을 갱신한다.

```json
{"schema_version": 1, "catalog_url": "https://content.example.com/2026.11/catalog.json"}
```

4. 설정 → 이미지에서 두 가져오기 흐름을 시험한다. 한 항목을 수정한 뒤 다시 조회해 **내가 수정함**과 **기존 내용 유지**를 확인한다.
5. 실제 로컬 ComfyUI에서 모델 확인·선택 다운로드·재시작 이어받기·파일 인식·이미지 생성을 확인한다. 대역 테스트와 구분해 결과를 이슈에 기록한다.

카탈로그와 팩은 같은 HTTPS 출처에 있어야 하며 다른 출처로 리디렉션하지 않는다. 앱은 여기에 금고의 Civitai 키나 다른 인증 정보를 보내지 않는다.
카탈로그가 가리키는 최소 앱 버전은 현재 기능의 첫 목표 버전인 0.8.1이다. 정식 배포 전 앱 버전과 함께 확인한다.

형식의 원본은 [데이터 모델](data-model.md), 사용 흐름은 [이미지 환경 준비](manual/guide/image-setup.md)에 있다.
