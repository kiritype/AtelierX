# ADR-0005: Validation 응답 구조와 에러코드

- 상태: Proposed
- 작성일: 2026-09-12
- 확정일: 미확정
- Supersedes / Superseded by: 없음
- 관련: [ADR-0003](0003-generation-execution-and-queue.md), [ADR-0004](0004-validation-outcomes-and-errors.md)

## 결정할 질문

Validation 결과와 오류를 Core·CLI·Frontend가 동일하게 해석할 수 있도록 응답 필드, 에러코드 및 HTTP 매핑을 설계한다. 사용자가 설계를 요청한 초안이며 승인 전까지 구현 기준으로 사용하지 않는다.

## 배경과 제약

ADR-0004에 따라 Prompt 명시 요소 누락·불일치는 불합격이고, Provider 오류·파싱 실패는 에러코드를 반환하며 자동 이미지 재생성을 유발하지 않는다. 사용자의 수동 재생성은 허용한다. Core가 전체 흐름과 상한을 관리한다.

## 제안

2026-09-13 후속 [ADR-0006](0006-validation-manual-retry.md)에서 완료 응답의 `outcome=error` 이후 자동 검증 재시도를 도입하지 않고 사용자 재검증 또는 수동 재생성을 지원하도록 확정했다. 재검증은 기존 이미지·생성 Prompt를 사용하며 이미지 재생성 횟수에서 제외하고 Core가 요청·이력을 관리한다. 본문의 재시도 정책 미정 표현은 이 범위에서 ADR-0006으로 구체화되며, 전체 응답 구조·코드·HTTP 매핑은 계속 Proposed다.

### 1. 완료 결과는 세 가지로 구분

공통 JSON envelope와 `outcome`을 사용한다. `passed`, `rejected`, `error` 세 값만 두고, `result`와 `error` 중 정확히 하나만 객체로 반환한다. 나머지는 명시적으로 `null`이다. 아래 표와 필드 의미는 본 ADR의 제안이다.

| outcome | result | error | 자동 이미지 재생성 |
| --- | --- | --- | --- |
| passed | 합격 결과 | null | 요청하지 않음 |
| rejected | 불합격 결과·재생성 제안 | null | Core가 제안·설정·상한을 확인한 경우에만 |
| error | null | 에러코드·안내 | 금지 |

대기·실행 중·취소는 이 세 가지 완료 판정에 섞지 않는다. 비동기 Job 도입과 상태 계약은 별도 결정한다.

### 2. 공통 필드

| 필드 | 타입·필수 여부 | 의미 |
| --- | --- | --- |
| request_id | string, 필수 | Validation이 발급하는 해당 호출의 추적값. 로그 연결용이며 중복 실행 방지 키가 아님 |
| subject | object 또는 null, 필수 | 검증 대상 연결. 대상이 해석되기 전 입력 오류이면 null |
| subject.image_id | string 또는 null, 필수 | 요청에 제공된 이미지 ID. 등록 ID 없는 직접 호출이면 null |
| subject.generation_attempt_id | string 또는 null, 필수 | 요청에 제공된 생성 시도 ID. 직접 호출에서 제공되지 않으면 null |
| outcome | enum, 필수 | passed / rejected / error |
| result | object 또는 null, 필수 | 정상 완료된 검증의 판정·근거·재생성 제안 |
| error | object 또는 null, 필수 | 요청 또는 실행 오류 |

Core의 전체 흐름에서는 이미지·생성 시도 연결값을 제공하고 응답과 대조한다. 직접 호출에서 ID가 없더라도 이미지와 생성 Prompt는 ADR-0004에 따라 필요하다. `subject`는 ID를 새로 등록하거나 소유권을 증명하지 않는다. ID 생성 체계·영속 Validation ID·요청 중복 방지는 별도 계약이다.

### 3. 정상 결과

| 필드 | 타입 | 의미 |
| --- | --- | --- |
| result.findings | array | 불합격 근거. 합격이면 빈 배열, 불합격이면 한 개 이상 |
| findings[].code | enum | 초기 값 ELEMENT_NOT_VISIBLE / ELEMENT_MISMATCH |
| findings[].prompt_excerpt | string | 해당 시도 Prompt의 검사 대상 구절 |
| findings[].expected | string | 이미지에서 기대하는 요소 |
| findings[].observed | string | 보이지 않음 또는 실제로 관찰한 차이 |
| result.regeneration.required | boolean | Validation의 새 이미지 생성 필요 판단. 실행 명령이나 사용자 허가가 아님 |
| result.regeneration.reason | string | 재생성 필요 여부의 설명 |
| result.regeneration.changes | array | 기존 시도 입력에 적용할 최소 설정 변경 목록 |

`changes` 항목은 `{ "field": "seed", "value": 482917 }`처럼 등록된 생성 입력 필드의 값을 교체하는 형태를 제안한다. 임의 DB 필드·파일 경로·SQL을 수정하는 범용 Patch가 아니다. 입력 계약에 허용된 모든 생성 설정을 대상으로 하되, 모델별 타입·범위·호환성을 확인해야 한다. 필드 목록, 중첩 설정·Prompt 교체 표현과 입력에 필요한 생성 설정 전달은 Generation 입력 Schema와 함께 후속 확정한다.

합격이면 `required=false`, `changes=[]`다. 불합격에서 `required=true`이면 검사를 통과한 유효한 변경 목록이 있어야 한다. Provider가 변경값을 만들지 못하거나 유효하지 않은 값을 반환하면 RESPONSE_SCHEMA_INVALID 실행 오류로 처리한다. 유효한 불합격 결과지만 자동 변경을 권하지 않는 경우에는 `required=false`, `changes=[]`와 사유를 반환하고 사용자 검토로 넘긴다. 불합격만으로 반드시 생성하도록 강제하지 않는다.

```json
{
  "request_id": "req-example-01",
  "subject": {
    "image_id": "image-example-01",
    "generation_attempt_id": "attempt-example-01"
  },
  "outcome": "rejected",
  "result": {
    "findings": [
      {
        "code": "ELEMENT_MISMATCH",
        "prompt_excerpt": "blue eyes",
        "expected": "파란 눈",
        "observed": "갈색 눈으로 관찰됨"
      }
    ],
    "regeneration": {
      "required": true,
      "reason": "눈 색상 불일치로 새 생성 시도를 제안합니다.",
      "changes": [{ "field": "seed", "value": 482917 }]
    }
  },
  "error": null
}
```

예시 Seed 변경은 형식 예시이며 모든 불합격에 Seed만 바꾸라는 정책이 아니다. Negative Prompt·검사별 판정 기준은 별도로 정한다.

### 4. 오류 객체

| 필드 | 타입·필수 여부 | 의미 |
| --- | --- | --- |
| error.code | string, 필수 | 아래 목록의 안정적인 코드. Client 분기는 이 값으로 수행 |
| error.message | string, 필수 | 사람이 읽는 오류 설명. 문구를 파싱해 분기하지 않음 |
| error.stage | enum, 필수 | input / provider / response / internal |
| error.field | string, 선택 | 잘못된 입력 필드. 값 자체는 포함하지 않음 |

초기 계약에는 `critical`, `retryable`, `next_action`을 넣지 않는다. 오류 심각도와 자동 복구 허가는 다르며, 이러한 값이 재생성이나 재시도를 암묵적으로 승인하지 않게 한다. 동일 이미지 검증 재시도 정책이 확정되면 필요한 정보만 별도로 확장한다.

```json
{
  "request_id": "req-example-02",
  "subject": {
    "image_id": "image-example-01",
    "generation_attempt_id": "attempt-example-01"
  },
  "outcome": "error",
  "result": null,
  "error": {
    "code": "VAL_RESPONSE_PARSE_FAILED",
    "message": "AI 응답을 검증 결과로 해석하지 못했습니다.",
    "stage": "response"
  }
}
```

오류에는 `regeneration` 자체가 없다. `required=false`인 합격 결과와도 명확히 구분된다. API Key, Provider 원문 응답·예외 Stack·내부 경로를 공개 오류 메시지에 그대로 넣지 않는다. 상세 진단은 request_id로 로그와 연결하며 로그 보존·마스킹의 상세 정책은 별도다.

### 5. 초기 에러코드와 HTTP 매핑

다음 상태는 검증 실행을 직접 요청하고 완료 응답을 받는 경우의 제안이다. 합격·불합격은 모두 HTTP 200이다. HTTP 요청이 정상 처리됐는지와 이미지가 요구에 맞는지는 다르다. 비동기 방식을 도입하면 결과 조회 자체는 HTTP 200일 수 있으므로 아래 실패 매핑을 결과 조회에 그대로 적용하지 않는다.

| code | stage | HTTP | 조건·사용자 안내 방향 |
| --- | --- | --- | --- |
| VAL_REQUEST_INVALID | input | 400 | JSON·요청 구조 해석 불가. 호출 형식 확인 |
| VAL_PROMPT_REQUIRED | input | 422 | 생성 Prompt 누락·공백. 해당 시도 Prompt 필요 |
| VAL_IMAGE_REQUIRED | input | 422 | 이미지 입력 누락 |
| VAL_INPUT_INVALID | input | 422 | 그 밖의 필수 필드·타입·허용 범위 오류. field 제공 |
| VAL_IMAGE_UNREADABLE | input | 422 | 전달받은 이미지 바이트 Decode 불가. 입력 확인 |
| VAL_INPUT_TOO_LARGE | input | 413 | 요청 크기 제한 초과. 구체 한도는 미정 |
| VAL_INPUT_MEDIA_UNSUPPORTED | input | 415 | 지원하지 않는 입력 미디어 형식 |
| VAL_PROVIDER_CONFIG_INVALID | provider | 503 | 서버 측 Provider·Endpoint·모델 설정 누락 또는 사용 불가 |
| VAL_PROVIDER_AUTH_FAILED | provider | 503 | 서버가 사용하는 Provider 인증·권한 실패. Provider 설정 확인 |
| VAL_PROVIDER_QUOTA_EXCEEDED | provider | 503 | Provider가 명시한 할당량·잔액 소진. 계정 설정 확인 |
| VAL_PROVIDER_RATE_LIMITED | provider | 503 | Provider가 명시한 일시 요청 제한 |
| VAL_PROVIDER_UNAVAILABLE | provider | 503 | 연결 실패·Provider 5xx 등 일시 사용 불가 |
| VAL_PROVIDER_TIMEOUT | provider | 504 | Provider 응답 제한 시간 초과 |
| VAL_PROVIDER_REQUEST_REJECTED | provider | 502 | 그 밖의 Provider 요청 거절. Provider의 4xx를 그대로 전달하지 않음 |
| VAL_PROVIDER_REFUSED | response | 502 | 검증 판정 대신 명시적인 처리 거절 응답. 이미지 불합격으로 간주하지 않음 |
| VAL_RESPONSE_PARSE_FAILED | response | 502 | 응답을 기대한 구조로 파싱할 수 없음 |
| VAL_RESPONSE_SCHEMA_INVALID | response | 502 | 필수 판정 누락·모순·유효하지 않은 변경값 등 |
| VAL_INTERNAL_ERROR | internal | 500 | Validation 내부 예외 또는 원인 분류 불가 |

VAL_IMAGE_UNREADABLE은 AI 검증을 시작할 수 없는 입력 오류다. 별도 Deterministic 이미지 품질 검사의 불합격 계약을 확정하는 것은 아니다. 원격 이미지 다운로드·접근 오류는 파일 전달 계약에서 추가한다.

Provider 응답에서 원인이 확인된 경우에만 세부 코드를 사용한다. 예를 들어 단순 429만으로 잔액 소진을 추측하지 않는다. Provider별 분류는 Validation 내부에서 정규화하며, Client가 Provider 원문을 해석하지 않는다.

Provider 인증 실패를 HTTP 401로 반환해 AtelierX 사용자 재로그인을 유발하지 않는다. 위 503은 Validation이 설정된 검증 기능을 제공할 수 없다는 뜻이며 자동 재시도 허가가 아니다. Validation 자체의 인증·권한·요청 제한 오류는 별도 공통 API 계약에서 정한다.

HTTP 의미는 [RFC 9110의 상태 코드 정의](https://www.rfc-editor.org/rfc/rfc9110.html#name-status-codes)를 참고했다. 개별 VAL 코드와 매핑은 AtelierX 설계 제안이다.

### 6. 소비자 처리와 반복 방지

1. Shared SDK는 HTTP 상태·본문 구조를 함께 확인한다. 누락된 본문, HTML 오류 페이지, 알 수 없는 outcome, 상호 모순되는 result/error는 정상 판정으로 변환하지 않는다.
2. Core는 요청과 대상 연결이 일치하고 유효한 `outcome=rejected`이며 `regeneration.required=true`일 때만 자동 생성 후보로 취급한다. 이어서 자동 재생성 설정·상한과 변경값을 확인한다. 불일치나 잘못된 응답으로 새 생성을 진행하지 않는다.
3. `outcome=error`이면 에러코드를 기록하고 해당 이미지의 자동 재생성 경로를 종료한다. 이미 확인한 일부 불합격 근거가 있어도 필수 검증·결과 처리가 실패하면 result=null로 반환하고 부분 결과로 자동 재생성하지 않는다.
4. CLI·Frontend는 오류를 표시하고 해당 이미지의 명시적인 사용자 수동 재생성 요청을 Core에 전달한다. 오류 수신 또는 화면 재접속 자체로 새 생성을 요청하지 않는다.
5. 알 수 없는 error.code는 message와 request_id를 표시하는 일반 오류로 처리하고 자동 이미지 재생성을 하지 않는다. HTTP 5xx라는 이유만으로 SDK가 검증 요청을 자동 재전송하지 않는다. 검증 재시도는 후속 정책의 범위다.
6. 응답을 받지 못한 통신 오류는 Validation이 반환한 에러코드인 것처럼 꾸미지 않는다. SDK가 전송 실패로 보고하며, Core·Client는 이를 이미지 불합격으로 처리하지 않는다. 완료 여부가 불명확한 요청의 재조회·중복 방지는 후속 접수 계약에서 정한다.

## 검토한 대안

| 대안 | 평가 |
| --- | --- |
| passed boolean + 재생성 boolean + 선택적 오류 | false의 의미가 불합격과 실행 실패로 섞여 제외 |
| 공통 envelope + outcome별 result/error 분리 | 권고. 세 결과를 같은 소비자 분기로 처리하고 오류에는 재생성 필드가 없음 |
| 성공 JSON + RFC 9457 Problem Details 오류 | 유효한 대안. 현재는 동일 envelope를 권고하며 RFC 9457 호환이라고 표기하지 않음 |

[RFC 9457](https://www.rfc-editor.org/rfc/rfc9457.html)은 HTTP 오류 정보를 위한 별도 표준 형식을 정의한다. 추후 프로젝트 공통 오류 계약으로 채택한다면 이 ADR의 envelope와 SDK 처리에 대한 변경 영향을 함께 검토한다.

## 영향과 트레이드오프

불합격 근거와 에러코드를 분리해 Client는 이미지 문제와 실행 문제를 다르게 표시할 수 있다. Provider 차이는 Validation 내부에 모인다. 재생성 필드를 오류에서 제거해도 Core의 응답 검사·상한 적용은 계속 필요하다. 구조가 유효하다는 사실이 AI 판정 정확도를 보장하지는 않는다.

이 문서는 응답 envelope·초기 에러코드 설계다. 실제 기계 검증 가능한 전체 Schema는 Generation 입력·Prompt·ID 계약과 함께 완성해야 한다. 제품 코드·의존성·실행 환경·CI는 추가하지 않는다.

## 이번에 결정하지 않는 사항

Endpoint 경로, 동기·비동기 실행 선택, Job 상태·Batch 영향·취소, 요청 및 이미지 전송 구조, Prompt/Generation 입력 필드와 변경값 상세 Schema, ID·중복 방지·응답 버전 정책, Provider별 구현, 검증 재시도·Fallback, 판정 정확도·검사 Profile, CLI Exit code, 공통 인증·권한은 후속 결정이다.

[ADR-0012](0012-validation-image-transfer-and-required-input.md)에서 조회 API/업로드·필수 정보·입력 부족 처리를 확정했다. 검증은 가능하지만 재생성 설정 정보가 부족하면 판정을 제공하고 자동 재생성 제안은 하지 않는다. 충분한 정보에 대해 Provider가 잘못된 변경값을 반환한 실행 오류와 구분한다. 전체 Schema·필드명·전송/인증 세부는 계속 미정이다.

[ADR-0016](0016-validation-execution-and-gpu-sharing.md)에서 Validation 비동기 Job·Provider별 Queue/초기 동시성 1·취소/복구·중복 접수·Core GPU 조정을 확정했다. 위 실행 선택·GPU 조정 미정 범위는 구체 저장/상태/원자성/수치 등으로 한정한다. ADR-0005의 동기 HTTP 예시는 비동기 결과 조회에 그대로 적용하지 않는다.

[ADR-0017](0017-regeneration-change-validation.md)에서 변경 대상/제외·의도 보존·최소 변경·형식/상한/환경 검사 책임과 제안 일괄 적용을 확정했다. 구체 변경 Schema·오류 코드·검사 구현은 미정이다.

## 충돌 및 대체 확인

ADR-0001·0002의 운영·Node 결정과 충돌하지 않는다. ADR-0003의 Core 조정·상한·시도별 변경값과 ADR-0004의 불합격/실행 오류 분리·수동 재생성을 유지한다. Proposed 초안이므로 기존 Accepted ADR을 수정하거나 supersede하지 않는다.

## 문서 반영

- [x] ADR 목록·overview에 Proposed로 연결
- [x] backlog의 응답 구조·에러코드 초안 연결
- [x] 요구사항·모듈 문서는 Accepted 기준 유지, 초안 링크만 추가
- [x] 기존 ADR 충돌·대체 여부 확인
- [x] 확정 원칙과 이번 제안·미정 상세 구분
