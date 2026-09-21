# Shared Client·CLI 첫 구현

작성일: 2026-09-13. Frontend 탐색 API에 이어 CLI와 내부 도구용 Python REST adapter를 연결한다. 기존 Python/aiohttp 환경을 재사용한 첫 구현이며, 브라우저용 SDK 언어·배포·Schema 생성 방식을 확정하거나 모든 CLI 기능을 완료한 것은 아니다.

## 사용 범위

`atelierx.api_client.CoreClient`는 Core REST의 인증·Timeout·JSON 응답·오류 처리를 공통화한다. CLI는 인자를 Client에 전달하고 결과를 JSON으로 출력한다. Prompt 구성, 판정, 재생성 횟수와 작업 순서는 Core가 담당한다. 첫 구현은 조회 전용이었으며, 후속 구현으로 아래 생성 접수·단일 검증·수동 재생성·취소 명령을 추가했다. 후속 파일럿에서 settings update와 group-batch create/cancel/confirm-reference를 추가했다.

| 명령 | 용도 |
| --- | --- |
| `groups list`, `groups get ID` | 고정 그룹과 기준 조회 |
| `images list`, `images get ID` | 갤러리 metadata와 이미지 상세 조회 |
| `tasks list`, `tasks get ID` | 작업 목록·상세 조회 |
| `group-batches list`, `group-batches get ID` | 일괄 작업 목록·상세 조회 |
| `health`, `queue`, `settings get` | Core 상태·대기열·전역 설정 조회 |

저장소 가상환경에서 `.venv/Scripts/python.exe -m atelierx.cli --help`로 시작한다. `atelierx` console entry도 제공하며 설치된 패키지의 entry 갱신 전에는 모듈 실행을 사용할 수 있다. 토큰은 `ATELIERX_CORE_TOKEN` 환경변수로 전달한다. URL은 `--core-url` 또는 `ATELIERX_CORE_URL`로 주입하고 기본값은 `http://127.0.0.1:8190`이다. 실제 Backend에 설정한 토큰을 사용하며 문서에 비밀값을 저장하지 않는다.

```powershell
.venv/Scripts/python.exe -m atelierx.cli groups list --limit 20
.venv/Scripts/python.exe -m atelierx.cli images list --single-outcome passed --group-status stale
.venv/Scripts/python.exe -m atelierx.cli tasks list --state completed
.venv/Scripts/python.exe -m atelierx.cli group-batches list --limit 10
```

성공 JSON은 stdout, 오류는 stderr로 분리한다. 서비스 오류 코드를 유지하며 통신 실패와 응답 형식 오류를 구분한다. 실패를 빈 목록으로 바꾸거나 작업을 자동 재전송하지 않는다. CLI 종료 성공은 조회 성공을 뜻하며 조회된 작업의 합격을 뜻하지 않는다. 개별 명령과 필터는 `--help` 및 [REST 명세](../api/rest-api.md)를 따른다.

## 후속 범위

Generation/Validation 직접 조회, 묶음 검증·기준 관리의 전체 명령, SSE 구독, 이미지 content 다운로드와 브라우저용 Client는 아직 포함하지 않는다. 일반 입력·표시 상세는 검토 가능한 초안으로 유지하고 Backend 정책을 Client에서 복제하지 않는다.

## 검증 결과

- 실제 Core HTTP 서버와 CLI subprocess를 연결하여 목록·상세·health·queue·settings 조회 11개, 인증 거부와 잘못된 limit 오류 2개를 각각 재시작 전후 검증했다(총 26회). 모든 조회·오류 전달과 종료 코드가 기대와 일치했다.
- 실행: `.venv/Scripts/python.exe -B scripts/test_core_browse_rest.py --with-cli`. 산출물: `artifacts/core-browse-rest/20260913-155949/report.json`. CLI 목록과 직접 REST 응답이 같으며 원본 및 사본 DB의 조회 전후 내용도 같았다.
- 작업 실행기를 대기시킨 SQLite 사본 기반 시험이다. GPU·VLM 및 생성·검증 후속 실행을 시험한 것은 아니다.
- 종료 코드는 조회 성공 0, 입력/설정/서비스/통신 오류 1이다. 실제 Core 401은 `CORE_UNAUTHORIZED`, limit 0은 `CORE_INVALID_INPUT`을 stderr로 반환했다.
- 첫 전체 테스트에서 Windows 연결 거부보다 짧은 Timeout을 설정한 통신 오류 fixture가 실패했다. 통신 오류 fixture의 네트워크 환경 의존성을 제거한 뒤 **전체 164개 테스트가 17.528초에 통과**했다. 실제 HTTP 기반 인증·응답·Timeout 검증은 유지했다. 최종 로그는 위 산출물 폴더의 `unit-tests.log`다.


## 생성·검증·재생성·취소 후속 명령

| 명령 | 입력과 결과 |
| --- | --- |
| `prompts preview --input FILE` | Core가 조합한 snapshot과 preview_hash 확인 |
| `tasks create --input FILE --idempotency-key KEY` | 생성 접수; 완료를 기다리지 않음 |
| `tasks by-key --idempotency-key KEY` | 응답 유실 뒤 기존 Task 확인 |
| `tasks regenerate ID --input FILE --idempotency-key KEY` | 지원 override 또는 빈 객체로 새 수동 시도 접수 |
| `tasks cancel ID` | 기존 Task 취소 요청 |
| `tasks attempts ID` | 같은 lineage의 시도 이력 조회 |
| `images validate ID --input FILE --idempotency-key KEY` | 저장 이미지의 단일 검증 접수 |
| `validations get ID`, `validations cancel ID` | 검증 Run 조회·취소 |
| `cycles get ID`, `cycles stop ID` | 자동 재생성 cycle 조회·중지 |

`--input FILE`은 UTF-8 JSON 객체 파일이며 `--input -`는 stdin이다. preview/create 입력은 Core Task 계약이고, regenerate 입력은 `{}` 또는 허용 override, validate 입력은 `{"profile_id":"등록 ID","provider_id":"등록 ID"}`다. `tasks get ID`로 생성/검증 상태와 결과를 추적한다. CLI exit 0은 요청 성공일 뿐 생성 완료·검증 합격을 의미하지 않는다.

생성 전 `prompts preview` 결과를 검토하고 원래 Task 입력에 반환된 `preview_hash`를 추가해 `tasks create`로 보낸다. preview 응답 전체를 create 입력으로 보내지 않는다. CLI는 Prompt를 자체 조합하거나 미리보기를 자동 승인하지 않는다. 모델·그룹 ID는 현재 환경에서 선택한 실제 값을 사용한다.

멱등 키는 사용자가 요청마다 명시한다. 같은 요청의 응답 유실은 같은 키로 조회하거나 같은 내용/키로 재접수하고, 명시적인 새 요청에만 새 키를 쓴다. 같은 키에 다른 내용은 Core 409 오류다. CLI는 재접수·검증·재생성을 자동 반복하지 않는다. `cycle stop`은 자동 후속 중지 의사이며 실행 중 GPU 작업의 즉시 종료를 보장하지 않는다.

취소·재생성 명령은 저장 상태를 변경한다. 아래 통합 시험은 임시 DB와 대기 중인 Core worker에서 수행해 사용자 작업을 실행하거나 취소하지 않았다.

### 후속 검증

실제 CLI subprocess → Python Client → Core HTTP → 임시 SQLite 경로를 검증했다. preview의 upper_body 하의 제외, 기본 1024 해상도, 접수 후 Core 재시작·키 조회, 동일 키 중복 방지·다른 내용 409, Task 취소, 수동 새 Task/cycle, 기본 상한 5, attempts/cycle stop, 단일 검증 접수·동일 키 반환·취소를 포함한다. 검증용 완료 이미지는 fixture이며 GPU·Generation·VLM 추론은 실행하지 않았다.

최종 전체 회귀 테스트: **171개 통과**, 20.044초. 명령은 `.venv/Scripts/python.exe -B -m unittest discover -s tests -q`, 로그는 `artifacts/full-suite/cli-mutations.log`다. Client 5개·CLI 9개·CLI→Core 통합 2개를 포함한다. 설정 화면은 [상세 초안](frontend-settings-screen.md)이며 UI 실행 검증은 하지 않았다.


## F/E 파일럿 병행 확장

`settings update --input FILE`, `group-batches create GROUP_ID --input FILE --idempotency-key KEY`, `group-batches cancel ID`, `group-batches confirm-reference ID --input FILE --idempotency-key KEY`를 추가했다. 설정 수정은 revision을 포함한 변경 객체, 일괄 생성은 기존 `{items,group_validation}`, 기준 확인은 `{reference_revision}`이다. CLI는 입력을 한 번 전달하며 실행 순서를 조정하지 않는다. 최신 전체 174개 테스트와 화면 실환경 결과는 [Frontend 파일럿](frontend-pilot.md)을 따른다.
