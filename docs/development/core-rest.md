# Core REST 첫 구현 및 검증

2026-09-13 사용자 구현 지시에 따라 Core → Generation → ComfyUI 최소 생성 흐름을 구현했다. Frontend 및 Validation 서비스 구현 완료를 의미하지 않는다.

## 실행

저장소 Python 3.12 가상 환경에 `pip install -e .`로 설치한다. 동일한 서비스 토큰을 각 터미널 환경의 `ATELIERX_SERVICE_TOKEN`에 지정한 뒤 실행한다. Core의 별도 Generation 인증 토큰은 `ATELIERX_GENERATION_TOKEN`으로 지정할 수 있다.

```powershell
.venv/Scripts/atelierx-generation.exe --port 8189
.venv/Scripts/atelierx-core.exe --port 8190 --generation-url http://127.0.0.1:8189
```

두 서비스는 localhost에 바인딩하며 Bearer 인증을 사용한다. ComfyUI는 8188에서 먼저 실행한다. Core 기본 DB는 `.atelierx/core/core.sqlite3`이며 SQLite WAL·외래 키·트랜잭션과 데이터 경로별 프로세스 잠금을 사용한다. Generation은 SQLite에 접근하지 않는다.

## 구현 범위

| API | 동작 |
| --- | --- |
| `/v1/works`, `/v1/characters`, `/v1/outfits` | 생성·조회 및 개별 PATCH, revision 충돌 검사, archive |
| `/v1/{종류}/{id}/revisions` | 변경 이력 조회 |
| `/v1/settings` | 전역 품질/Negative Prompt와 자동 재생성 설정 저장 |
| `/v1/groups` | 의상 revision 및 외형·상의·하의 내용을 고정한 그룹 생성 |
| `/v1/prompts/preview` | 실제 Prompt와 preview hash 확인 |
| `/v1/tasks`, `/v1/tasks/by-key`, `/v1/tasks/{id}` | 접수·멱등 키 조회·생성 상태 및 결과 조회 |
| `/v1/images/{id}`, `/v1/images/{id}/content` | 이미지 메타데이터·크기/해시 검증 후 이미지 반환 |

작품·캐릭터·의상 이름은 Prompt에 삽입하지 않는다. 품질 → 외형 → 상의 → 하의 → 구도·표정·행동·상황 순서로 합성하며 현재 구도는 `upper_body`, `full_body`다. Upper body는 하의를 제외한다. 사용자 문자열과 가중치는 보존하며 독립 악세사리 항목은 없다. 그룹의 고정 의상과 작업의 고정 전역 설정을 통해 이후 편집이 기존 작업을 변경하지 않도록 한다.

Core는 Generation에 고정 멱등 키로 한 번 접수한다. 응답 유실·재시작 시 키로 조회하며 불명확한 접수를 다시 POST하지 않는다. 완료 결과의 중복/늦은 갱신은 최종 상태를 덮지 않는다. 생성 완료는 `generated`, Validation은 `not_requested`, outcome은 null이다. 자동 재생성 상한 기본값 5는 저장되지만 재생성 실행은 아직 연결하지 않았다.

## 검증 및 남은 범위

`python -m unittest discover -s tests -v`: Core 9개, Generation 6개 통과. Prompt 제외·스냅샷·멱등성·응답 유실·복구·오류·이미지 무결성·단일 프로세스 소유와 완료 상태 보호를 확인했다.

`scripts/test_core_rest.py`로 실제 Core → Generation → ComfyUI Anima 생성, 768×1024 PNG 회수, 해시 확인, Core 재시작 후 작업/멱등성 보존을 검증했다. 로컬 기록은 `artifacts/core-rest/20260913-034454/report.json`이다.

다음은 Validation 서비스 연결과 Generation 보조 노드 API 확장이다. Queue 전체 제어·취소·GPU 서비스 간 조정·묶음 검증·재생성 실행·전체 import/export·제품 CLI는 아직 구현 완료되지 않았다. API 사용 예제는 `scripts/test_core_rest.py`, 계약 경계 테스트는 `tests/test_core.py`를 참고한다.

## 후속 통합

[후처리·단일 검증 연결](backend-pipeline-integration.md)에서 schema version 2, PNG/WebP, 이미지별 검증 API 및 최신 시험 결과를 확인한다. 이전 미연결 기록에 대한 후속 구현이다.
