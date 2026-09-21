# Core 기존 이미지 독립 후처리

2026-09-21 사용자 후속 구현 지시. Generation의 기존 저장 이미지 후처리 API를 Core 접수·이력과 Frontend에 연결한다. ADR-0003의 실행 책임과 원본·검사 이력 보존 원칙 안에서 구현하며 별도 ADR을 승인 처리하지 않는다.

## 사용 범위

갤러리의 Core 등록 이미지에서 후처리를 요청한다. 입력은 원래 이미지 ID이며 URL·파일 경로·임의 Workflow를 받지 않는다. Upscale → Detailer → Censor → Alpha → Encode 중 명시한 단계만 기존 Generation 계약으로 실행한다. 직접 설정 또는 저장된 후처리 Preset의 revision을 선택하고 접수 시 고정한다.

새 결과는 후처리 작업에 연결해 원본 상세와 작업 현황에서 조회한다. 원본 파일·생성 Task·검사 결과·그룹 기준을 덮어쓰지 않는다. 파생 결과를 기존 그룹의 검사 대상이나 대체 이미지로 자동 편입하지 않으며, 완료는 후처리 실행 완료를 뜻한다. 품질 합격이나 단일/묶음 검사 통과가 아니다.

외부 이미지 업로드, Discord 독립 결과의 갤러리 편입, 파생 결과의 재후처리·검증·그룹 편입은 이번 범위 밖이다. 이미지 삭제·보관 정책도 변경하지 않는다.

## Core REST 계약

| Method | Path | 용도 |
| --- | --- | --- |
| POST | `/v1/images/{id}/postprocess-jobs` | 원본 Core 이미지에서 후처리 접수 |
| GET | `/v1/postprocess-jobs` | 작업 페이지 조회, `source_image_id` 필터 |
| GET | `/v1/postprocess-jobs/by-key` | 같은 `Idempotency-Key`로 접수 조회 |
| GET | `/v1/postprocess-jobs/{id}` | 상태·고정 설정·결과·오류 조회 |
| POST | `/v1/postprocess-jobs/{id}/cancel` | 실행 종료 확인을 포함한 취소 |
| GET | `/v1/postprocess-jobs/{id}/images/{image_id}/content` | 작업에 속한 파생 PNG/WebP 조회 |

접수 본문은 `{postprocess:{...}}` 또는 `{preset:{id,revision}}` 중 하나다. 하나 이상의 후처리 단계와 `Idempotency-Key`가 필요하다. 동일 키/본문은 기존 작업을 반환하고 다른 본문이나 원본은 충돌이다. 기존 작업 조회는 이후 Preset 변경·보관의 영향을 받지 않는다.

Core는 별도 `postprocess_jobs`에 원본 식별·해시·미디어 형식·생성 입력·Generation endpoint와 후처리 설정을 고정한다. Generation에 한 번 접수하기 전 의도를 저장하고 응답 유실·재시작 시 기존 내부 키로 조회한다. 접수 불명 상태에서 새 생성 POST를 자동 반복하지 않는다. 결과의 원본·설정·Job 식별을 확인한 뒤 파생 메타데이터를 저장하며, 콘텐츠 조회 시 크기와 해시를 확인한다.

상태는 `queued`, `dispatching`, `generation_pending`, `running`, `completed`, `failed`, `cancelled`이며 취소 진행은 `cancel_requested=true`로 구분한다. 취소 응답은 종료 시 200, 진행 중 202다. `/v1/queue`와 SSE에도 `kind=postprocess`가 포함된다. 목록은 `state`, `source_image_id`, `limit`(1..200), `offset`으로 조회한다. 이미지 descriptor의 `image_id`, `media_type`, `bytes`, `sha256`, `content_url`을 사용하며 임의 URL로 대체하지 않는다.

통신 불가가 연속 300초 지속되면 명시 오류로 추적을 종료한다. 정상 상태 조회는 이 관찰 시간을 초기화하므로 긴 정상 작업의 실행 제한이 아니다. 이는 초기 구현의 운영값이며 제품 이미지 수 상한이나 자동 재접수 근거가 아니다. 접수 불명·상태 추적 종료는 원격 실행 중단 확인을 뜻하지 않으므로 Generation 상태를 운영자가 확인해야 한다.

Generation이 기존 공유 GPU 조정과 실행·파일 보관을 담당한다. Core와 화면은 임의 GPU 강제 반납이나 재제출로 불확실한 실행을 숨기지 않는다. 취소 요청 중과 실제 종료를 구분하고, 늦게 도착한 완료로 취소 의사를 덮어쓰지 않는다.

## 검증·운영 반영

실제 실행은 `scripts/test_core_independent_postprocess_rest.py`로 과거 시험 자료의 DB·이미지를 별도 디렉터리에 복사해 수행했다. SQLite backup 이후 복사본 Task의 Generation endpoint만 격리 서비스 주소로 바꾸고, 복사한 종료 Job의 GPU 요청 플래그를 초기화했다. 이는 테스트 fixture 준비이며 제품의 import 기능이 아니다. 사용자 파일럿 DB·이미지와 실행 프로세스는 수정하지 않았다. 공유 GPU 조정은 기존 Core를 사용했다.

- **실제 ComfyUI/REST:** 기존 768×1024 PNG 1장에 UltraSharp 1.1배 + Encode를 적용해 845×1126 PNG/WebP를 얻었다. Core 동일 키 재요청은 같은 작업을 반환했고, 결과 콘텐츠 해시·크기·해상도, 원본 bytes와 그룹 불변, GPU 반납을 확인했다. 종료 후 격리 Core/Generation을 다시 시작해 완료 Job 보존도 확인했다. 실행과 재시작 검증을 포함해 약 6.37초였으며 일반 처리량 지표는 아니다.
- **실제 화면:** 격리 Core 갤러리에서 Encode만 추가 접수해 PNG/WebP 완료와 768×1024 미리보기를 확인했다. 원본 상세의 별도 결과 이력, 작업 현황 이동·파생 미리보기, 완료 취소 버튼 비활성화, 원본으로 돌아가기를 확인했다. 브라우저 오류 로그는 없었다. 두 작업 모두 종료·GPU 반납 후 격리 서비스를 정상 종료했다.
- **모의 Generation 회귀:** 접수 응답 유실 후 실제 SQLite close/reopen, 동일 키 조회 복구와 POST 재전송 금지, 접수 도중 취소·늦은 완료, Preset 변경과 snapshot 보존, 연속 통신 불가 종료를 검사한다. 모의 응답은 실제 ComfyUI 장애·중단 시험을 대신하지 않는다.
- **미검증:** 이번 Core 경로의 Detailer/Censor/Alpha 실제 재실행, 후처리 품질 향상·검출 정확도, 실제 실행 중 장애·취소, 장기 경합·디스크 부족 대응. 실제 완료를 품질 합격으로 보고하지 않는다.

현재 작업 브랜치의 Python 전체 241건(48.764초), Frontend 17건이 통과했다. 새 Core 모듈 회귀 4건과 HTTP 경계 4건은 Python 전체에 포함된다. HTTP 경계에서는 큐의 후처리 종류 표시, 동일 크기 파일 변조·크기 초과, endpoint 변경 409, 실제 Preset revision 변경 후 snapshot 보존도 확인했다. 로그는 같은 디렉터리의 `python-suite.log`다. 이 브랜치는 develop에서 독립 분기했으며 별도 신체 검사 PR #4의 테스트를 합산한 수치가 아니다.

로컬 증거는 `artifacts/core-independent-postprocess/20260921-live/report.json`, `browser-check.txt`, `browser-jobs.json`에 있다. 이미지·DB·토큰·실행 로그는 Git 제외이며 새 clone에서는 별도 fixture와 로컬 서비스를 준비해야 한다.

이 작업의 에이전트는 기존 파일럿을 재시작하지 않았다. 작업 중 별도로 파일럿 PID가 13072에서 21928로 변경됐으며, 최종 읽기 전용 확인에서 8190의 새 후처리 목록 API가 200으로 빈 목록을 반환하고 기존 작업 화면도 표시됐다. 운영 API 활성화 확인과 격리 이미지 실행 검증을 구분한다. 구 Core의 신규 경로 404는 해당 기능만 업데이트 안내로 표시하며, 이 호환 처리는 모의 테스트로 확인했다.
