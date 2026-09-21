# 개인용 Discord 봇 — 2026-09-21

사용자 확정 범위: 배포 전 개인 사용을 우선하며, Discord 봇은 F/E의 분류·그룹과 독립된 생성 흐름이다. 자연어를 로컬 LLM으로 프롬프트화하거나, 자연어/Positive Prompt를 그대로 Anima에 전달해 이미지를 응답한다. 처음에는 본인만, 이후 명시적으로 추가한 친구만 사용할 수 있게 한다. 외부 Generation API 테스트와 Backend 전체 완료는 이 작업의 선행 조건이 아니다.

## 명령과 데이터 흐름

- `/draw prompt:... mode:natural`: 로컬 LLM이 Positive Prompt만 작성한 뒤 생성한다. 기본 모드다.
- `/draw prompt:... mode:direct`: 입력 문자열을 Positive Prompt로 그대로 전달한다. 자연어 문장과 태그형 문구 모두 가능하다.
- `/status request_id:...`: 자신의 기존 요청 상태 또는 이미지를 새 응답으로 받는다. 새 생성 요청이 아니다.

```text
Discord Slash command
  → Cloudflare Worker: 서명 검증, 허용 사용자 확인, 지연 응답
  → 인증된 HTTPS Tunnel → 로컬 Bridge (127.0.0.1:8192)
  → Core 독립 생성 API (8190): 저장·Planner·GPU·Generation 실행 조정
  → Generation (8189) → ComfyUI (8188)
  → Bridge가 Core에서 이미지를 조회 → Discord 원래 응답에 첨부
```

Core의 기존 groups/tasks 테이블에 임시 그룹을 만들지 않는다. 별도 `standalone_jobs` 테이블에 입력·설정·실행 상태를 보관한다. Bridge는 SQL·Generation·LLM에 직접 접근하지 않는 전달용 클라이언트다. 이미지 원본은 기존 Generation 저장 영역에 남는다. 독립 생성 결과는 현재 F/E 그룹 갤러리에 자동 편입하지 않는다.

첫 구현은 생성과 이미지 전달이며 단일/묶음 Validation과 자동 재생성을 요청하지 않는다. 응답에는 품질 검증 미요청 상태를 표시한다. 분류가 없는 요청에 캐릭터 외형·캐릭터 Negative를 임의로 붙이지 않는다. direct Positive는 원문 보존, Negative·모델·Seed·생성/업스케일 설정은 서버의 독립 생성 설정을 사용한다. 현재 명령에서 크기·모델·Negative·Seed를 개별 override하지 않는다.

## 대기·중복·친구 공개

Discord의 초기 응답은 3초 이내여야 하며 interaction token은 15분 동안 유효하다. Worker는 생성 완료를 기다리지 않고 비공개 지연 응답(type 5, flags 64)을 반환한다. 로컬 Bridge는 접수 ID와 `/status` 사용법을 먼저 표시하고 결과를 나중에 첨부한다. [Discord 응답 계약](https://docs.discord.com/developers/interactions/receiving-and-responding)

- Worker는 로컬 접수만 짧게 전달한다. GPU 실행을 Worker의 `waitUntil` 안에서 기다리지 않는다.
- Bridge는 토큰 유효기간에 여유를 두어 14분 후 기존 응답 전달을 중단한다. 이미 접수된 Core 작업은 계속 추적하며, 새 `/status`의 토큰으로 결과를 받을 수 있다. 만료 전에 Core에 접수조차 못한 오래된 요청은 새로 생성하지 않는다.
- Discord interaction ID를 로컬 중복 키와 Core의 `discord:<ID>` 키로 사용한다. 전송 응답 유실·프로세스 재시작 후 기존 키를 조회한다. 확인되지 않는 접수는 명시적 오류로 남기고 자동 재접수하지 않는다.
- 이미지 응답은 원래 메시지 PATCH로 전달한다. 전달 재시도는 생성과 분리하며, 실패한 전달 때문에 다시 생성하지 않는다. Discord 429의 대기 시간을 반영한다.
- Discord의 첨부 한도 안에서 PNG 또는 WebP 하나를 전달한다. 로컬 어댑터는 요청당 메모리 사용을 위해 최대 20MiB를 읽는다. 이는 생성 이미지 개수의 제품 상한이 아니다. 전달 가능한 파일이 없으면 로컬 보존 상태를 안내한다.
- Worker의 `DISCORD_ALLOWED_USER_IDS`와 Bridge의 `allowed_user_ids`에 본인 ID만 넣는다. 친구 공개 때 두 목록에 해당 ID를 추가한다. 서버 구성원이라는 이유만으로 생성 권한을 부여하지 않는다.
- `/status`는 원래 요청자만 사용할 수 있다. 초기 응답·이미지는 ephemeral이며 같은 서버의 다른 사람에게 자동 공유하지 않는다. 관리자·결제·조직 권한 체계는 도입하지 않는다.

LLM 추론 중 응답이 유실되거나 Core가 종료되면 자동 추론 재시도하지 않고 실행 불명 오류를 남긴다. 실행 종료가 불명인 GPU 권한은 임의 시간 만료로 해제하지 않는다. 실제 종료 여부 확인과 수동 복구가 필요한 경우가 있으며, 장기 무인 복구 완료로 보고하지 않는다.

## 설정과 로컬 실행

예제는 [독립 생성 설정](../../examples/standalone-generation.example.json), [Bridge 설정](../../examples/discord-bridge.example.json), [Worker 설정 예제](../../integrations/discord-worker/.dev.vars.example)다. 실제 값은 `.atelierx/`와 Worker의 무시된 `.dev.vars`에 보관한다. 토큰·DB·이미지를 커밋하지 않는다.

1. 예제 두 JSON을 `.atelierx/discord/`로 복사하고 앱 ID·본인 ID·등록 모델 이름을 채운다. LLM model은 기존 `.atelierx/gpu-config.json`의 공유 GPU model과 같아야 한다. 첫 구현은 서로 다른 Planner/VLM 모델 교체 관리까지 확장하지 않는다.
2. `ATELIERX_PLANNER_API_KEY`에 로컬 LM Studio API 키, `ATELIERX_DISCORD_BRIDGE_TOKEN`에 새 랜덤 비밀값을 설정한다. Bridge Token은 Worker의 `BRIDGE_TOKEN`과 같아야 한다. Core 토큰은 파일럿 실행 스크립트가 기존 로컬 토큰을 사용한다.
3. ComfyUI·LM Studio와 기존 큐 상태를 확인한다. 동일 포트/데이터를 사용하는 실행 중인 파일럿을 중복 시작하지 않는다.

저장소 루트에서 기존 파일럿에 옵션을 추가해 같은 Core/GPU 조정을 사용한다.

```powershell
.venv/Scripts/python.exe scripts/run_frontend_pilot.py `
  --standalone-config .atelierx/discord/standalone.json `
  --discord-bridge-config .atelierx/discord/bridge.json
```

F/E는 기존 `http://127.0.0.1:8190/ui/`를 사용한다. Bridge만 별도 실행할 경우 다음 명령과 `ATELIERX_SERVICE_TOKEN` 환경변수를 사용한다.

```powershell
.venv/Scripts/python.exe -m atelierx.discord_bridge `
  --config .atelierx/discord/bridge.json
```

이 실행 스크립트는 이 PC의 기존 `.atelierx/gpu-config.json`과 Validation 설정을 참조한다. 새 clone에는 해당 파일·모델·토큰이 없으므로 소스만 clone해서 바로 실행되는 배포 패키지는 아니다.

## Cloudflare·Discord 연결

Worker 이름은 `atelierx-discord-worker`다. 기존 다른 Worker는 변경하지 않는다. 로컬 Bridge만 Tunnel에 연결하며 Core·ComfyUI·LM Studio 포트를 공개하지 않는다. 첫 연결 시험은 Quick Tunnel을 사용할 수 있고, 계속 사용할 때는 고정 hostname의 Named Tunnel로 바꾼다. Quick Tunnel은 개발용이며 주소가 고정되지 않는다. [공식 Quick Tunnel 안내](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/do-more-with-tunnels/trycloudflare/)

2026-09-21 새 Worker 배포 완료: `https://atelierx-discord-worker.kiritype.workers.dev`, version `51095047-ae6d-4c86-8689-b8f6e0a4873b`. 앱 Public Key·ID·허용 사용자 ID·Bridge 연결 설정은 아직 입력하지 않았다. 따라서 현재 GET은 405, POST는 `misconfigured`로 거절하며 생성 요청을 전달하지 않는다. 실제 Discord 연결 완료를 뜻하지 않는다. Tunnel·명령 등록은 아직 실행하지 않았다.

후속 연결 작업: 사용자 제공 Application ID·Public Key·본인 User ID를 Worker secrets에 반영했고, Bridge 토큰을 로컬에서 생성해 별도 secret으로 등록했다. 실제 식별값과 토큰은 `.atelierx/discord/`의 Git 제외 설정에만 보관한다. 미서명 POST는 현재 401로 거절된다. 로컬 파일럿 Core/Generation/Validation과 Bridge를 시작해 각 health 200, 기존 Core 활성 작업 없음(전체 15개)을 확인했다. 공개 Tunnel 시작은 자동 승인 심사에서 거절되어 확인 대기 중이며, Discord endpoint 설정·Bot Token을 사용하는 테스트 Guild 명령 등록·실제 Discord 수신은 아직 남아 있다. 새 Worker secret 등록 이후 버전은 최초 코드 배포 version과 구분한다.

추가 연결 확인: 로컬 Git 제외 파일에 저장한 Bot Token으로 앱 ID를 검증했고 Discord Interaction Endpoint를 배포된 Worker 주소로 설정한 뒤 재조회했다. Discord의 endpoint 검증은 통과했다. 테스트 Guild 명령 등록은 HTTP 403 / 50001 Missing Access로 거절되었으며, Bot의 Guild 목록에 대상 서버가 없는 것을 확인했다. 이후 사용자의 서버 설치 작업 후 Bot의 대상 Guild 소속과 명령 API 접근 성공을 확인했다. `/draw`·`/status`를 개별 등록하고 GET 재조회로 두 명령을 검증했다. 설치 화면의 “잘못된 양식 본문” 표시 원인은 확인되지 않았지만 실제 서버 설치와 명령 등록은 완료되었다. 공개 Tunnel과 Discord 실제 이미지 응답 검증은 아직 남아 있다.

```powershell
cloudflared tunnel --url http://127.0.0.1:8192
```

생성된 HTTPS 주소에 `/v1/discord/jobs`를 붙여 Worker의 `BRIDGE_URL`로 설정한다. Bridge Bearer 인증은 필수다. Cloudflare Access를 추가하는 경우 Worker의 Access service token 설정도 같이 입력한다. 영구 Tunnel·DNS·Access 자원은 사용할 계정/hostname을 확인한 뒤 만든다.

Worker 설치·검증·등록 방법은 [Worker README](../../integrations/discord-worker/README.md)를 따른다. Bot Token은 명령 등록 스크립트에서만 사용하고 Workers 런타임에는 전달하지 않는다. 앱의 Interaction Endpoint URL에는 배포된 Worker 주소를 설정한다. 앱 ID·Public Key는 [Developer Portal](https://discord.com/developers/applications)의 General Information, 사용자·서버 ID는 Discord 개발자 모드를 켠 뒤 우클릭 메뉴에서 복사한다. [공식 ID 확인 안내](https://support.discord.com/hc/en-us/articles/206346498-Where-can-I-find-my-User-Server-Message-ID)

기존 Discord 앱을 사용하므로 명령 등록 시 다른 명령을 일괄 삭제하지 않는다. 테스트 Guild에 `/draw`, `/status`를 먼저 등록하고, 승인된 사용자 요청에서만 실제 GPU 생성과 첨부를 확인한다.

## 검증 상태

2026-09-21 검증 결과:

- Python 전체 **222개 통과**(46.417초), Frontend **17개**, Worker Node **7개** 통과. Python 로그는 `artifacts/full-suite/discord-bot.log`다. 새 Core/Bridge 테스트는 15개이며 모의 LLM·Generation·Discord와 실제 Core REST/SQLite를 구분해 사용한다.
- 로컬 workerd 런타임에서 유효한 Ed25519 서명 PING은 200 PONG, 변조 서명은 401을 확인했다. `wrangler deploy --dry-run`도 통과했다. 이 결과는 클라우드 배포나 Discord 실제 연결과 구분한다.
- **실제 GPU/LLM 실행:** 격리 Core/Generation에서 direct 12.079초, natural 18.281초에 각각 이미지 한 장을 생성했다. 자연어 변환은 실제 로컬 `qwen3-vl-8b-instruct-abliterated`, 생성은 실제 Anima→UltraSharp 1536×1536이다. 각 이미지의 PNG/WebP 두 포맷을 decode·크기·SHA-256 검증했으며 이를 생성 4장으로 세지 않는다. 새 그룹은 0개, 최종 GPU owner=null/waiting=[]였다. Validation 및 Discord 전송은 이 실제 시험에 포함하지 않았다.
- 실제 생성 근거: `artifacts/discord-standalone-20260921/report.json`, `direct.png`, `natural.png`. 재현 스크립트는 [test_standalone_generation_rest.py](../../scripts/test_standalone_generation_rest.py)다. 실행 전 사용자 큐·모델 사용 상태를 확인하며 동일 GPU의 다른 작업과 겹치지 않는다.
- Discord 앱 연결 및 Discord에서 시작한 실제 생성→이미지 첨부는 앱 식별값·설정 연결 후 확인해야 한다. 비공개 응답의 사용자 경험과 친구 실제 계정의 권한 시험도 아직 남아 있다.
- 전체 회귀 이후 초기 진행 메시지의 지연 응답 경쟁을 보완하고 Bridge 10개 테스트를 다시 통과했다. 실제 시험의 임시 Core/Generation 서버는 종료했고 기존 ComfyUI·LM Studio 프로세스는 유지했다. 파일럿 DB는 이번 실제 시험에서 사용하지 않았다.


### 사용자 직접 실행 후 Tunnel 연결 확인

2026-09-21 사용자가 RDP에서 Quick Tunnel을 직접 실행했다. 제공한 임시 주소를 대상으로 `/health` 인증 없음 401, 올바른 Bridge 인증 200을 확인했다. Worker `atelierx-discord-worker`의 `BRIDGE_URL`을 해당 Tunnel의 `/v1/discord/jobs`로 반영했고 secrets 갱신 성공을 확인했다. 실제 주소는 Git 제외 로컬 설정에 저장한다. Quick Tunnel은 실행 창 종료 시 끊기고 재실행 시 주소가 바뀌므로 새 주소 반영이 필요하다. Discord에서 시작한 `/draw`의 실제 이미지 응답은 아직 미검증이다. `cftm.net` 기반 고정 Tunnel은 아직 구성하지 않았다.


### 첫 Discord 요청 장애 진단

실제 `/draw` 요청은 Discord에서 비공개 대기 응답을 받았지만 로컬 Bridge 접수 기록은 없었다. Cloudflare 로그에서 `bridge_dispatch_failed`(unknown), `discord_original_response_edit_failed`를 확인했다. 실제 workerd를 사용하는 격리 Miniflare 실행으로 `fetch(..., {redirect: "error"})`가 전송 전에 TypeError를 발생시키는 것을 재현했다. 해당 런타임은 follow/manual만 지원한다. 따라서 Node의 모의 fetch 테스트와 서명 PING만으로 외부 요청 경로를 검증한 이전 시험에는 공백이 있었다. 실제 이미지 생성이나 Discord 전달 성공으로 집계하지 않는다.

수정: 외부 fetch를 `redirect: "manual"`로 전환해 리디렉션을 따라가지 않고 비정상 상태로 처리한다. 실패 로그에는 정해진 사유 코드와 HTTP 상태만 추가하며 토큰·웹훅 URL은 기록하지 않는다. 수정 후 실제 workerd의 서명된 draw 요청이 모의 Bridge에 정확히 한 번 도착했고 배포 dry-run도 통과했다. Worker version `91fd9a21-0ed1-4149-a9d2-679bd43d4816`으로 배포했다. 원래 요청의 Core by-key 조회는 404였으며 자동 재접수하지 않았다. 사용자에게 새 요청 한 번으로 실제 Discord 경로를 재검증하도록 안내했다.


### 수정 후 실제 Discord 이미지 응답 성공

사용자가 테스트 Guild에서 `/draw prompt:1 girl mode:Direct`를 새로 요청했다. 접수 ID 안내 후 Core `completed`, Bridge `delivered`, error=null, delivery_attempts=0을 확인했다. 실제 생성 이미지 한 장의 PNG/WebP는 각각 1536×1536이며 Core content API로 읽어 decode·SHA-256·바이트 수를 검증했다. 로컬 근거는 `artifacts/discord-first-live-result.json`이다. Validation은 `not_requested`이므로 품질 합격으로 해석하지 않는다. Discord에서 시작한 direct 생성→업스케일→이미지 전달 경로를 실제 검증한 결과이며, natural 모드의 Discord 전체 경로·친구 권한·장기 운영·고정 Tunnel은 아직 미검증이다.

회귀 검증: Worker 테스트 9개 통과(실제 Miniflare/workerd→모의 Bridge 전송 및 3xx 리디렉션 미추적 포함). 기존 Node 모의 테스트와 실제 런타임 테스트를 구분한다. 오류 응답에 본문이 없어도 HTTP 상태 분류를 보존하는 보완을 포함한 최종 Worker version은 `06a15e20-b2f4-4e2f-a210-299ab14126ad`이며 배포 완료했다. 실제 Discord 성공은 앞선 redirect 수정 version에서 확인한 결과다.
