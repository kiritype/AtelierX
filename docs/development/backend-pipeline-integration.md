# Backend 생성·후처리·단일 검증 연결

2026-09-13 사용자 후속 구현 지시에 따른 초기 실행 경로다. 이전 문서의 ADR 전용/구현 보류 및 보조 노드 미연결 기록보다 이 기록이 우선한다. 확정 ADR의 책임 경계는 변경하지 않았다.

## 구현한 흐름

Core `POST /v1/tasks`에 선택 `postprocess`를 추가했다. Core는 원본 요청을 스냅샷에 저장하고 Generation에 전달한다. Generation이 실제 등록된 노드·모델 선택지를 검사하여 `Anima → Detailer → Censor → Alpha → Encode` 중 지정한 단계만 실행한다. Detailer는 원본 모델·Prompt·순서 있는 LoRA를 유지한다. PNG/WebP를 Core 이미지 API에서 각각 조회할 수 있다. 기존 Anima 단독 요청도 유효하다.

생성 후 `POST /v1/images/{id}/validations`에 `Idempotency-Key`와 아래 선택 값을 전달한다.

```json
{"profile_id":"single-default","provider_id":"local-vision"}
```

Core가 저장된 이미지 ID·SHA-256·실제 생성 Prompt·등록 Profile/Provider 설정으로 Validation 요청을 만든다. 클라이언트가 이미지의 Prompt나 Provider URL을 덮어쓰지 않는다. `GET /v1/validation-runs/{id}`와 `GET /v1/images/{id}/validations`로 결과·이력을 조회한다.

Core SQLite는 schema version 2로 validation_runs를 추가한다. 생성 상태 `generated`와 이미지별 Validation 결과를 분리한다. `passed`/`failed`/`error`를 저장하며 Provider/파싱 오류는 자동 생성이나 재검증을 호출하지 않는다. 새 키를 사용한 수동 재검증은 새 이력이며, 같은 이미지의 진행 중 검증과는 충돌을 반환한다. 접수 응답 유실 시 저장된 키를 조회하고 재POST하지 않는다.

## API 설정 입력

편집할 로컬 파일은 `.atelierx/validation-config.json`이다. 예제 원본은 `config/validation.example.json`이다. Core와 Validation이 같은 파일을 읽으므로 Provider 모델명·revision을 두 군데에 입력하지 않아도 된다.

- `providers.local-vision.url`: `/v1`까지 포함한 OpenAI 호환 API base URL. `/chat/completions`는 서비스가 붙인다.
- `model`: 해당 서버의 실제 모델 ID.
- `api_key`: 로컬 Ollama 예제값은 `ollama`. 외부 API 사용 시 실제 키를 이 로컬 파일에 입력하거나 `api_key` 대신 `api_key_env`로 환경 변수 이름을 지정한다.
- `timeout_seconds`: 초기 시험값 180초. 서비스 실행 중 설정 변경은 반영하지 않으며 재시작 후 새 요청부터 적용한다. URL·모델·Timeout 변경 시 revision도 증가시킨다.
- `profiles.single-default`: 현재 출력 조건, Positive/Negative 검사 On/Off 지원. 최소 한 검사를 켠다. 몸 부위 별도 검사·metadata·묶음 consistency는 아직 지원하지 않으며 요청하면 거절한다.

서비스 토큰을 같은 값으로 지정한 세 터미널에서 실행한다. 토큰은 임의로 정한 충분히 긴 값 또는 환경에 보관한 값을 사용하며 문서/공유 파일에 기록하지 않는다.

```powershell
.venv/Scripts/atelierx-generation.exe --port 8189
.venv/Scripts/atelierx-validation.exe --port 8191 --config .atelierx/validation-config.json
.venv/Scripts/atelierx-core.exe --port 8190 --validation-config .atelierx/validation-config.json
```

각 터미널의 `ATELIERX_SERVICE_TOKEN`이 필요하다. 설정 파일의 `generation_sources.*.token_env`는 이 환경 변수에서 Generation 조회 토큰을 가져온다. 외부 Provider는 선택·설정한 경우에만 호출하며 자동 Fallback은 없다. 실제 AI 서버를 아직 설치·시작하지 않은 상태에서도 위 설정 파일 편집은 가능하다.

## 검증 결과

- Core/Generation/Validation 테스트 31개 통과: Prompt/후처리 스냅샷, 멱등성, 복구, 오류 후 재전송 금지, 무결성, 출력조건 불합격, 검사 Off, 투명도 및 설정 변경을 확인했다.
- 실제 ComfyUI + Core/Generation REST: Encode, Alpha, Censor, Detailer 개별 단계 및 전체 연결 결과를 PNG/WebP로 회수하고 디코딩·크기·SHA-256을 검사했다.
- 전체 연결 결과 이미지로 실제 Validation 서비스까지 호출하고, 로컬 **모의 Vision Provider**의 통과·잘못된 JSON 응답을 각각 처리했다. Core에 오류 이력이 남고 생성 횟수가 증가하지 않음을 확인했다. 실제 VLM 판단 정확도 검증이 아니다.
- 실행 기록: `artifacts/backend-pipeline-rest/20260913-042349/report.json`에서 Encode/Alpha/Censor 성공. 이 실행의 Detailer 접수는 구형 한 원소 COMBO schema 해석 문제로 거절되어 수정했다. 이후 `20260913-042429/report.json`에서 Detailer/전체 흐름/모의 Validation 성공을 확인했다.
- 재현: `scripts/test_backend_pipeline_rest.py`. `--cases detailer,all`처럼 필요한 생성 단계만 선택할 수 있다. GPU 실행은 순차이며 사용자 ComfyUI 작업이 실행 중이면 새 시험을 시작하지 않는다.

## 남은 범위

실제 VLM 연결·정확도 평가, Core의 Provider 설정 CRUD API, 자동 생성 후 검증 실행 정책 및 자동 재생성 적용, 묶음 검증, 서비스 간 GPU 소유권/모델 해제, 취소·보관 정리, 생성 완료 이미지만 재후처리하는 독립 Job, 전체 CLI는 아직 완료하지 않았다. 현재는 사용자가 명시적으로 이미지별 검증을 접수하는 경로다. Local VLM과 ComfyUI가 같은 GPU를 쓰는 실제 실행 시험은 GPU 메모리 해제/직렬 실행을 확인하면서 진행한다.

이미지 위치는 [저장 경로](output-paths.md), 세부 API는 [Generation 후처리](generation-postprocess.md)와 [Validation](validation-rest.md)을 참고한다.
