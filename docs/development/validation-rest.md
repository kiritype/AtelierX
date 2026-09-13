# Validation REST 초기 구현

[현재 REST API 명세](../api/rest-api.md)와 [Negative 출처 분리 검증](negative-sources-validation.md)이 최신 계약이다. 전역 Negative는 생성 전용, 캐릭터 Negative만 검증한다. 과거 전체 Negative 검사 설명보다 ADR-0023이 우선한다.

`atelierx.validation`은 단일 PNG/WebP 이미지의 비동기 Vision 검증 Job을 제공한다. 묶음 비교 endpoint는 아직 제공하지 않는다.

실행은 다음과 같다.

```powershell
$env:ATELIERX_SERVICE_TOKEN = 'local-service-token'
atelierx-validation --data-dir .atelierx/validation --port 8191 --config .atelierx/validation-config.json
```

`POST /v1/uploads`는 인증된 raw PNG/WebP 바이트를 받고 `upload_id`, SHA-256을 반환한다. `POST /v1/validations/single`은 `Idempotency-Key`와 `image`, `generation_attempt_id`, 고정 `profile`, 고정 `provider`, `expected_output`, `generation_settings`을 받는다. `GET /v1/validation-jobs/{job_id}` 또는 `/by-key`로 상태를 조회한다. 결과는 `passed`, `failed`, `error`를 명시하며 오류에는 `VAL_*` 코드가 있다. 오류는 재검증이나 생성 재시도를 자동으로 실행하지 않는다.

이미지는 arbitrary URL/경로를 받지 않는다. Generation 원본은 요청의 `source.type=generation`, 등록된 `server_id`, 안전한 `image_id`, SHA-256으로만 읽으며, 서버 설정의 URL과 서비스 토큰을 사용해 redirect 없이 `/v1/images/{image_id}`를 인증 조회한 뒤 크기·해시를 확인한다. 업로드는 Validation 데이터 디렉터리 아래에 저장된다. 초기 한도는 16 MiB, Decode 후 40MP이며 Pillow로 실제 정지 PNG/WebP인지 검증한다. 요청한 출력 크기·형식·필수 alpha channel은 Provider 호출 전에 검사한다. 임시 보관 기간 정리는 후속 운영 구현 항목이다.

Provider 설정은 서버 소유 JSON `--config`에만 둔다. 최상위 키는 `providers`, `generation_sources`, `profiles`, 선택 `core`이며 각 provider에는 `url`, `api_key`, `model`, `revision`, `timeout_seconds`가 필요하다. OpenAI 호환 `POST /chat/completions` Vision 형식을 사용한다. `provider_id`, revision, model, timeout과 profile snapshot은 요청과 설정이 일치해야 한다. URL/API key는 Job·응답·로그에 저장하지 않는다. 설정이 없거나 API 응답이 파싱되지 않으면 `outcome=error`이며 가짜 통과 결과를 만들지 않는다. 테스트는 로컬 HTTP 모의 Provider만 사용하며 실제 외부/유료 API를 호출하지 않는다.

재시작 시 `queued` Job은 복원한다. `submitting`/`running` Job은 Provider가 이미 수락했는지 알 수 없으므로 `VAL_PROVIDER_ACCEPTANCE_UNKNOWN` 오류로 끝내고 재전송하지 않는다. 이 초기 어댑터는 전체 Provider를 하나의 worker에서 순차 실행한다. Core 연결과 설정 입력 방법은 [Backend 통합](backend-pipeline-integration.md)에 기록한다.

## LM Studio 실제 실행 후속 기록

로컬 Provider의 `image_format: "png"`는 WebP 입력을 Provider 전송 직전에 PNG로 무손실 재인코딩한다. 저장된 원본과 그 해시·출력 형식 검사는 WebP 기준을 유지한다. 디코딩된 픽셀과 알파를 보존하며, 추가 리사이즈나 생성은 하지 않는다. 생략 시 `original`로 원본을 전송한다. 이 설정은 고정 설정 fingerprint에 포함되고 변환 후에도 전송 크기 16 MiB 상한을 적용한다. Validation Job의 `provider_image`에는 원본/전송 미디어 형식·해시 및 전송 바이트 수를 기록한다. HTTP 거절 후 자동 재전송하는 fallback은 아니다.

사용자가 LM Studio를 선택했다. 로컬 모델 연결, json_schema 호환 수정 및 누락 요소 오판을 [실제 검증 기록](lmstudio-live-validation.md)에 남겼다. 이전 미연결 기록보다 이 실행 결과가 우선한다.

## 항목별 근거 검증 후속 변경

[평가 방식 v2와 실제 재평가](validation-element-evidence.md): Prompt 항목마다 관찰 근거를 반환하고 Validation이 최종 판정을 집계한다. 이전 화면 밖 부츠 오판은 동일 사례 재검증에서 불합격으로 처리됐다. 다른 이미지에서의 일반화는 아직 검증하지 않았다.

## 가중치 묶음 분리 후속 변경

[평가 v3와 실제 회귀 결과](validation-weighted-groups.md): 원문·가중치를 보존하며 괄호 묶음을 개별 요구로 분리했다. 기존 귀걸이 오탐을 포함한 동일 9개 조건이 이번 실행에서 모두 기대와 일치했다.
