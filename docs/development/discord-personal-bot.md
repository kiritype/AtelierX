# 개인용 Discord 봇 — 2026-09-21

사용자 확정 범위: 배포 전 개인 사용을 우선하며, Discord 봇은 F/E의 분류·그룹과 독립된 생성 흐름이다. 자연어를 로컬 LLM으로 프롬프트화하거나, 자연어/Positive Prompt를 그대로 Anima에 전달해 이미지를 응답한다. 최초에는 본인/친구 User ID 목록으로 제한했으나, 후속 사용자 지시로 설치는 소유자만 하고 지정한 서버/채널의 모든 멤버가 사용할 수 있는 정책을 추가했다. 실제 활성화 상태는 아래 권한 변경 기록을 따른다. 외부 Generation API 테스트와 Backend 전체 완료는 이 작업의 선행 조건이 아니다.

## 명령과 데이터 흐름

아래 Direct 기본값·선택 Negative는 후속 구현 계약이다. 2026-09-21 이번 변경은 테스트 완료 상태이며 실행 중 프로세스 식별 권한 문제로 파일럿 재시작·Worker 배포·명령 재등록을 보류했다. 기존 운영 명령은 아직 이전 계약이다.

- `/draw prompt:...`: mode 생략 시 Direct. 입력 문자열을 Positive Prompt로 그대로 전달한다. 자연어 문장과 태그형 문구 모두 가능하다.
- `/draw prompt:... mode:natural`: 로컬 LLM이 Positive Prompt만 작성한 뒤 생성한다. 선택 메뉴에서 Direct/Natural을 고르며 API의 mode 문자열은 앞뒤 공백 제거·소문자 정규화 후 검사한다. 실제 운영 반영 상태는 아래 후속 기록을 따른다.
- `/status request_id:...`: 자신의 기존 요청 상태 또는 이미지를 새 응답으로 받는다. 새 생성 요청이 아니다.
- `/draw prompt:... negative:...`: 선택 Negative 입력. 구현 기본 동작은 서버 기본 Negative 뒤에 추가이며, 이는 결합 방식 질문의 답변 전 명시한 권장 가정이다. 생략·빈 문자열·공백만 입력하면 기본값을 유지한다.

```text
Discord Slash command
  → Cloudflare Worker: 서명 검증, 허용 사용자 확인, 지연 응답
  → 인증된 HTTPS Tunnel → 로컬 Bridge (127.0.0.1:8192)
  → Core 독립 생성 API (8190): 저장·Planner·GPU·Generation 실행 조정
  → Generation (8189) → ComfyUI (8188)
  → Bridge가 Core에서 이미지를 조회 → Discord 원래 응답에 첨부
```

Core의 기존 groups/tasks 테이블에 임시 그룹을 만들지 않는다. 별도 `standalone_jobs` 테이블에 입력·설정·실행 상태를 보관한다. Bridge는 SQL·Generation·LLM에 직접 접근하지 않는 전달용 클라이언트다. 이미지 원본은 기존 Generation 저장 영역에 남는다. 독립 생성 결과는 현재 F/E 그룹 갤러리에 자동 편입하지 않는다.

첫 구현은 생성과 이미지 전달이며 단일/묶음 Validation과 자동 재생성을 요청하지 않는다. 응답에는 품질 검증 미요청 상태를 표시한다. 분류가 없는 요청에 캐릭터 외형·캐릭터 Negative를 임의로 붙이지 않는다. direct Positive는 원문을 보존한다. 선택 옵션 `negative`는 Core에 `negative_prompt`로 전달하며 서버 기본 Negative에 추가한다. 생략·빈 값은 기본값을 유지한다. 이 결합은 Core만 수행하고 Planner는 Negative를 재작성하지 않는다. 모델·Seed·생성/업스케일 설정은 서버의 독립 생성 설정을 사용한다. 현재 명령에서 크기·모델·Seed를 개별 override하지 않는다.

## 대기·중복·친구 공개

Discord의 초기 응답은 3초 이내여야 하며 interaction token은 15분 동안 유효하다. Worker는 생성 완료를 기다리지 않고 지연 응답(type 5)을 반환한다. 새 `/draw`는 공개 결과 설정을 사용하고 `/status`는 비공개(flags 64)를 유지한다. 로컬 Bridge는 접수 ID와 `/status` 사용법을 먼저 표시하고 결과를 나중에 첨부한다. [Discord 응답 계약](https://docs.discord.com/developers/interactions/receiving-and-responding)

- Worker는 로컬 접수만 짧게 전달한다. GPU 실행을 Worker의 `waitUntil` 안에서 기다리지 않는다.
- Bridge는 토큰 유효기간에 여유를 두어 14분 후 기존 응답 전달을 중단한다. 이미 접수된 Core 작업은 계속 추적하며, 새 `/status`의 토큰으로 결과를 받을 수 있다. 만료 전에 Core에 접수조차 못한 오래된 요청은 새로 생성하지 않는다.
- Discord interaction ID를 로컬 중복 키와 Core의 `discord:<ID>` 키로 사용한다. 전송 응답 유실·프로세스 재시작 후 기존 키를 조회한다. 확인되지 않는 접수는 명시적 오류로 남기고 자동 재접수하지 않는다.
- 이미지 응답은 원래 메시지 PATCH로 전달한다. 전달 재시도는 생성과 분리하며, 실패한 전달 때문에 다시 생성하지 않는다. Discord 429의 대기 시간을 반영한다.
- Discord의 첨부 한도 안에서 PNG 또는 WebP 하나를 전달한다. 로컬 어댑터는 요청당 메모리 사용을 위해 최대 20MiB를 읽는다. 이는 생성 이미지 개수의 제품 상한이 아니다. 전달 가능한 파일이 없으면 로컬 보존 상태를 안내한다.
- `users` 모드는 기존 `DISCORD_ALLOWED_USER_IDS` / `allowed_user_ids`를 사용한다. `guild` 모드는 Worker와 Bridge 양쪽에서 지정한 서버·선택적 채널을 검사하고 해당 범위의 모든 멤버를 허용한다. 서명된 Discord member/guild/channel 정보와 Bridge Bearer 인증을 사용한다. DM·다른 서버·범위 밖 채널은 소유자도 우회할 수 없다.
- `/status`는 원래 요청자만 사용할 수 있고 응답도 비공개다. 새 `/draw`의 진행·결과는 요청한 채널에 공개하며 첨부 이미지에 스포일러를 기본 적용한다. 관리자·결제·조직 권한 체계는 도입하지 않는다.

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


### 설치 권한과 서버/채널 사용 권한 분리

2026-09-21 사용자 지시: 봇 설치는 앱 소유자만, 지정한 서버/채널의 사용은 모든 멤버에게 허용한다. 결과의 비공개 응답과 `/status` 요청자 소유권은 유지한다.

Worker `DISCORD_ACCESS_MODE=guild`, `DISCORD_ALLOWED_GUILD_IDS`(필수), `DISCORD_ALLOWED_CHANNEL_IDS`(선택)를 Bridge `access_mode=guild`, `allowed_guild_ids`, `allowed_channel_ids`와 맞춘다. 채널 목록을 지정하지 않으면 허용 서버 전체이며, 지정하면 정확히 일치하는 채널만 허용한다. 비어 있거나 잘못된 제한 목록은 전체 공개로 취급하지 않는다. Worker는 guild 모드에서만 Bridge 요청에 `guild_id`/`channel_id`를 추가한다. users 모드는 기본값이며 기존 계약을 유지한다.

구현 검증: Worker 11개(실제 workerd 회귀 포함), Bridge 12개 테스트 통과. 모의 요청으로 비소유자의 허용 범위 접근, DM/다른 서버/채널 거절, 타인 상태 조회 거절을 확인했다. 실제 적용 범위(현재 서버 전체 또는 특정 채널)의 사용자 확인과 Discord 관리 화면 로그인은 아직 대기 중이다. 따라서 현재 운영 설정은 users/본인 한정으로 유지하며 Public Bot OFF 변경 완료로 보고하지 않는다. 설치 제한은 Discord Developer Portal의 Bot → Public Bot OFF로 설정하고 API 재조회로 검증한다.


권한 활성화 완료: 사용자가 현재 서버 전체 멤버로 범위를 확정했다. Worker/Bridge 모두 guild 모드와 기존 테스트 Guild 한 개를 설정하고 채널 제한은 두지 않았다. 코드 배포 version `26aa9769-e22a-4e86-868a-b0895ee6bd58` 이후 secrets도 반영했다. Core/Generation/Validation/ComfyUI와 Bridge에 진행 중 작업이 없음을 확인한 뒤 로컬 파일럿만 재시작했고 네 서비스 health 200을 확인했다. 사용자 실행 Tunnel은 유지했다. 외부 Tunnel을 통한 모의 상태 조회에서 허용 서버의 타인 결과는 404, 다른 서버는 403을 확인했다(실제 타인 Discord 계정의 생성 시험과 구분). Discord 앱 API를 재조회해 `bot_public=false`도 확인했으므로 소유자만 서버에 봇을 설치하는 설정이 완료되었다. 기존 서버 설치나 요청 결과를 삭제하지 않았다.


### 공개 생성 결과와 기본 스포일러

2026-09-21 사용자 추가 지시로 새 `/draw` 생성 결과를 채널 구성원에게 공개하고 이미지에 스포일러를 기본 적용한다. `DISCORD_PUBLIC_RESULTS=true`는 guild 접근 모드에서만 허용한다. `/draw`의 초기 지연 응답부터 공개로 설정하고 동일 메시지를 PATCH하므로 진행 안내도 공개되며, 기존 재전송/중복 방지 동작을 유지한다. 별도 공개 followup을 반복 게시하지 않는다. `/status`는 계속 요청자 전용 비공개 응답이다. Bridge는 PNG/WebP 모두 `SPOILER_atelierx.*` 이름으로 첨부한다. 과거 비공개 결과는 다시 게시하지 않는다.

구현 검증: Worker 12개(실제 workerd에서 공개 draw/비공개 status 확인), Bridge 12개 테스트 통과. Worker 코드는 version `502c92c5-0cfa-44ab-a01f-ea24e90e740a`으로 배포했지만 공개 설정은 아직 활성화하지 않았다. 스포일러 적용을 위한 로컬 서비스 재시작이 자동 승인 심사에서 거절되어 운영 Bridge는 이전 코드로 계속 실행 중이다. 사용자가 RDP에서 실행할 수 있도록 Git 제외 로컬 `.atelierx/discord/restart-pilot.ps1`을 준비하고 구문 검사만 완료했다. 재시작 후 health 확인과 Worker 공개 설정 활성화, 실제 Discord 공개/스포일러 표시 확인이 남아 있다. 현재 동작을 공개/스포일러 적용 완료로 보고하지 않는다.

공개·스포일러 활성화: 사용자가 RDP에서 재시작 스크립트를 실행한 후 새 로컬 서비스 프로세스와 Core/Generation/Validation/Bridge health 200, 외부 Tunnel health 200을 확인했다. 스포일러 코드가 포함된 로컬 서비스를 재시작한 뒤 Worker secret `DISCORD_PUBLIC_RESULTS=true`를 반영했다. 이후 새 `/draw`는 공개 응답과 기본 이미지 스포일러를 사용하고 `/status`는 비공개를 유지한다. 실제 Discord 화면에서 공개/스포일러 표시를 확인하는 사용자 시험은 아직 남아 있다.

사용자 실제 화면 확인: 공개·스포일러 설정 활성화 후 새 `/draw`에 대해 사용자가 정상 동작을 확인했다. 공개 결과와 기본 스포일러 표시의 Discord 실제 화면 확인을 완료한 것으로 기록한다. 이 확인은 사용자 관찰에 근거하며, 별도 친구 계정의 권한 시험이나 이미지 품질 검사까지 검증한 것으로 확대하지 않는다.


### 새 draw 무작위 Seed와 사용값 표시

사용자 지시로 Discord 독립 생성은 새 요청마다 무작위 Seed를 사용하고 완료 응답과 `/status`에 실제 사용값을 표시한다. Core 설정 `seed_mode=random`에서 신규 작업 접수 때 53비트 안전 정수 범위의 Seed를 한 번 선택·저장한다. 같은 요청의 멱등 재접수·서비스 재시작·전달 재시도는 Seed를 다시 선택하지 않는다. 기존 설정과의 호환을 위해 seed_mode 생략은 fixed다. Direct/Natural 모두 동일 규칙이며 기존 F/E 그룹 제작의 Seed 정책을 바꾸지 않는다. Discord에서 Seed 직접 지정 옵션은 이번 변경에 포함하지 않는다.

무작위 Seed 구현 검증: Core standalone·Bridge 관련 19개 테스트 통과. 최대 안전 정수, 동일 멱등 키의 난수 재선택 방지, 최종 Generation 입력 일치, 과거 queued 작업의 고정 Seed 복원, Seed 0의 Discord 표시를 확인했다. 로컬 standalone 설정은 random으로 준비했으나 서비스 재시작 전이므로 현재 실행 프로세스는 기존 고정 Seed 설정을 사용한다. 앞선 로컬 재시작 도구 실행 차단 때문에 사용자 RDP 재시작 후 활성화 확인이 필요하다. 실제 GPU/Discord의 무작위 Seed 표시 시험은 아직 남아 있다.

무작위 Seed 후속 확인: 사용자가 동작 확인을 완료했다고 응답했다. 사용자 관찰 기준으로 운영 적용 확인을 기록하며, 별도 대규모 난수/이미지 다양성 평가를 완료한 것으로 확대하지 않는다. 이후 Discord 봇은 일반 테스트용이므로 추가 기능·고정 Tunnel·전용 운영 개선은 후순위로 미룬다.


## 2026-09-21 선택 Negative와 기본 Direct 후속 구현

Worker→Bridge→Core 전 구간에서 mode 생략을 Direct로 처리하고, 문자열은 앞뒤 공백 제거·소문자 정규화한다. Discord 선택 목록은 Direct를 먼저 표시한다. 선택 negative는 negative_prompt로 전달하며 Core만 서버 기본값에 결합하고 신규 작업 생성 입력에 고정한다. 같은 요청 재전달·재시작에서 Negative를 다시 추가하거나 Seed를 다시 고르지 않는다. 기존 lowercase mode와 Negative 미입력 요청의 멱등 fingerprint는 유지한다.

검증: Core standalone/Bridge 22개, Worker 15개(workerd 포함) 통과. Worker dry-run과 등록 스크립트 구문 검사도 통과했다. 실제 Discord Negative 입력→GPU 생성은 미검증이며 이번에 새 이미지 생성이나 타인 메시지 전송을 하지 않았다.

운영 적용은 미완료다. 큐 및 GPU owner/waiting이 비어 있음을 확인한 뒤 기존 restart-pilot.ps1을 실행했으나 Windows가 PID 13104의 명령줄·실행 경로를 반환하지 않아 스크립트가 Unexpected service process로 중단했다. 서비스 종료 전 단계에서 멈췄으며 안전 확인을 제거하거나 강제 종료하지 않았다. 파일럿을 시작한 Windows 권한으로 정상 재시작한 뒤 Core/Bridge 준비를 확인하고 Worker 배포와 Guild 명령 재등록을 이어서 해야 한다. Tunnel은 변경하지 않았다.

체크포인트 선택은 이번에 구현하지 않았다. 현재 Anima Node registry에는 5개 diffusion_model 이름이 노출된다. 작은 목록은 Discord 선택지로 제공하고 Core가 허용된 모델과 생성 설정을 고정하는 방식이 가능하다. 목록 등록은 각 모델의 생성 검증 완료를 뜻하지 않으며 SDXL 등 다른 계열 지원과 구분한다.
