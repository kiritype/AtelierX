# Frontend 파일럿 실행·검증

2026-09-13 사용자 지시로 Frontend 문서 단계를 넘어 파일럿을 구현했다. Terra 서브에이전트가 제작 화면, 갤러리·작업·설정, REST Client·정적 호스트·CLI를 나누어 작성했고 주 에이전트가 화면 구성·통합·실제 GPU 및 브라우저 검증을 수행했다.

## 실행

- 접속: 로컬은 `http://127.0.0.1:8190/ui/`, Access 운영 주소는 `https://atelier.cftm.net/ui/`.
- 실행 명령: `.venv/Scripts/python.exe -B scripts/run_frontend_pilot.py`
- 기본 Bearer 연결: `.atelierx/pilot/token.txt`의 값을 첫 연결 화면에 입력한다. 브라우저 메모리에만 보관하며 URL·HTML·localStorage에는 넣지 않는다.
- Access 자동 연결: server-private `.atelierx/pilot/frontend-connection.json`이 있고 Core가 Cloudflare Access assertion을 검증하면, 허용된 Access 로그인 사용자는 브라우저에 Core Bearer를 다시 입력하지 않는다. 설정 파일 형식은 [비밀 없는 예시](../../config/frontend-connection.example.json)를 따르며 실제 `core_token`은 Git·Frontend asset·API GET 응답에 넣지 않는다. 미설정·로컬 실행은 기존 Bearer 연결을 유지한다.
- 데이터: `.atelierx/pilot/core.sqlite3`, `.atelierx/pilot/generation`, `.atelierx/pilot/validation`.
- 실제 최종 이미지: `.atelierx/pilot/generation/images/`. ComfyUI 중간 출력과 구분한다.

실행기는 기존 Core/Generation/Validation app을 localhost 8190/8189/8191에 올린다. 각 서비스의 독립 실행 명령도 유지한다. 기존 ComfyUI 8188과 `.atelierx/validation-coordinated-config.json`, `.atelierx/gpu-config.json`을 사용한다. 해당 포트에 서비스가 이미 있다면 중복 실행하지 않는다. 파일럿 초기 작업으로 작품 ‘파일럿 스튜디오’ > 캐릭터 ‘루나’ > 의상 ‘화이트 셔츠’와 ‘파일럿 Anima · 1024’ Preset을 저장했다. 초기 데이터는 기존 작업 DB에서 가져오지 않았다.

빌드 과정 없는 HTML/CSS/JavaScript ES module이다. Core는 `/ui/`의 명시된 정적 파일만 공개하고 REST Bearer 인증을 유지한다. 별도 BFF·SQL 접근·브라우저 오케스트레이션은 없다. Python Client와 브라우저 Client는 같은 REST를 각각 감싼 초기 adapter이며 Schema 기반 공용 코드 생성은 아직 도입하지 않았다.

Access 자동 연결은 Core가 서버에서 JWT signature·issuer·audience·만료·허용 email·public host를 확인하는 경우에만 활성화한다. Frontend가 `Cf-Access-Jwt-Assertion`, JWKS, Access client secret 또는 Core token 원문을 처리하거나 저장하지 않는다. Access assertion이 없거나 만료되면 UI는 Access 로그인 안내를 보이고, 기존 Bearer fallback은 로컬·미설정 환경의 호환 경로다. 이 후속 인증의 실제 브라우저 검증은 별도로 기록한다.

## 네 메뉴의 파일럿 범위

| 메뉴 | 구현 |
| --- | --- |
| 제작 | 작품·캐릭터·의상 생성/편집, 캐릭터 Negative, 외형·상의·하의 원본, 기존/새 고정 그룹, 구도·표정·동작·상황, 생성·후처리 Preset 또는 직접 설정, LoRA +/- 및 가중치, Core preview hash 후 단일 생성 접수·응답 유실 키 복구 |
| 갤러리 | 관계 ID·단일/묶음 판정·형식 필터, PNG/WebP 카드·인증 확대 이미지, 실제 과거 Prompt·후처리·검증 이력, 단일 재검증·수동 재생성, 기준 후보·저장과 선택 묶음 검증/교체 입력 |
| 작업 현황 | Task/Batch 목록·상세·결과 링크·시도/cycle, 취소·cycle 중지·기준 확인, 고급 일괄 접수 JSON, 활성 화면 5초 조회와 실패 backoff |
| 설정 | 좌측 category·우측 세부 섹션, 전역 Prompt·자동 상한, Preset/Profile/Provider JSON 편집·보관/복제(지원 API별), 고급 접기, revision 오류 표시·전역 설정 초안 유지 |

기본은 생성 1024×1024, 후처리 생략 시 UltraSharp 4x 모델의 최종 1.5배 및 WebP 품질 90이다. 명시적 후처리 없음은 `{}`를 보내며 기본값과 구분한다. 자동 재생성 기본 상한 5와 수동 무제한 정책은 Core가 처리한다.

## 실제 검증 결과

1. 브라우저에서 파일럿 의상·Preset·고정 그룹 선택 → Core preview → Task 접수.
2. Prompt에 상반신에서 제외한 하의가 들어가지 않고 분류명이 삽입되지 않음을 확인.
3. 실제 Anima 생성과 UltraSharp 후처리 완료: PNG/WebP 각각 **1536×1536**. Task `b8294150-d1e9-47dc-b254-e07b722c4dc8`.
4. 갤러리에서 인증된 이미지 두 개를 표시하고 PNG의 단일 검증을 브라우저에서 접수. 로컬 VLM 결과 **completed / passed**, Run `5913df15-7d24-4fe4-ab1f-3ac63dd8e50d`.
5. 설정 category 전환 시 미저장 전역 Positive 유지, 저장 성공, 자동 기본 5, 고급 JSON 펼침·접기와 작업 상세를 확인. 최종 브라우저 오류 로그 없음.
6. Python 전체 **174개 테스트 통과**, 21.694초. Node `tests/test_frontend_api.mjs`와 JS 구문·문서 diff 검사 통과.

산출물: `artifacts/frontend-pilot/report.json`, `artifacts/full-suite/frontend-pilot.log`. 실제 GPU 검증 종료 후 owner와 waiting이 비어 있음을 확인했다. WebP는 이번에 별도로 검증하지 않았다. 한 이미지의 pass를 VLM 품질 전체 완료나 묶음 검증 통과로 확대 해석하지 않는다.

## 파일럿의 한계와 다음 개선

- Preset/Profile/Provider 및 일괄·묶음 요청의 고급 입력은 JSON 편집이다. 전용 폼, 선택 목록과 안내를 개선한다.
- 모델 파일명·갤러리 관계 ID·검증 설정 ID 일부는 직접 입력한다. 모델 탐색·다운로드나 Core의 `/v1/nodes` 경로를 새로 꾸며 제공하지 않는다. 실행 환경 메뉴에 현재 연결 한계를 안내한다.
- 작업 현황은 polling으로 갱신한다. SSE adapter와 세 서비스 전체 상태 통합은 아직 남아 있다. 대량 목록·모바일·접근성 전체 검증은 수행하지 않았다.
- 원본 제작 편집과 전역 설정은 메모리 초안을 유지한다. Preset/Profile JSON 초안의 메뉴 이동·reload 보존과 전체 revision 충돌 비교 UI는 남아 있다. 모든 초안의 영구 저장을 보장하지 않는다.
- 실제 브라우저 GPU 시험은 단일 생성·후처리·PNG 단일 검증이다. 묶음 접수·기준 교체·교체 재생성의 화면 실행은 다음 회귀 범위다. 기존 Backend 테스트와 이번 화면 실행을 구분한다.
- 일반 이미지 import/삭제, 모델 관리, 중간 생성 preview, AI Draft는 이 파일럿 완료 범위에 포함하지 않는다.

다음 작업은 사용자가 파일럿을 직접 사용하며 남기는 피드백을 반영하고, JSON 입력을 전용 폼으로 바꾸면서 묶음 흐름의 브라우저 회귀를 넓히는 것이다.


[파일럿 폼 개선·묶음 회귀](frontend-pilot-refinement.md): 일반 필드·선택 폼, 초안 revision 보호와 실제 PNG 두 장의 묶음 실행을 추가 검증했다. 앞의 JSON 전용/묶음 화면 미시험 표기는 이 보고서의 범위로 갱신한다.
