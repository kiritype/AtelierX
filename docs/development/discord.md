# 개인용 Discord 봇

F/E의 작품·캐릭터·의상·그룹과 독립된 생성 흐름이다. 현재 위치는 **일반 테스트용·후순위**(2026-09-21 사용자 결정)이며 추가 기능은 필요할 때 진행한다. 구성 요소는 Cloudflare Worker(`integrations/discord-worker`)와 로컬 Discord Bridge(`src/atelierx/discord_bridge.py`)다.

## 명령

| 명령 | 동작 |
| --- | --- |
| `/draw prompt:<필수> [mode] [negative] [checkpoint]` | 이미지 한 장 생성 후 응답에 첨부 |
| `/status request_id:<interaction ID>` | 본인의 기존 요청 상태·결과를 새 비공개 응답으로 받음. 재생성하지 않음 |

- **mode**: 생략 시 `direct`. 선택지는 Direct, Natural 순. 입력은 앞뒤 공백 제거·소문자로 정규화한다.
  - Direct: 입력(자연어·태그 모두 가능)을 Positive Prompt로 그대로 사용한다.
  - Natural: Core가 로컬 LLM(LM Studio)에 Positive Prompt 재작성을 요청한 뒤 생성한다. 간단한 문장 재작성이며 체크포인트별 어휘·태그 최적화는 없다(후속 과제).
- **negative**: Core가 서버 기본 Negative 뒤에 추가한다. 생략·빈 값·공백만 입력하면 기본값 유지. Planner는 Negative를 재작성하지 않는다.
- **checkpoint**: Core 독립 생성 설정 `allowed_checkpoints` 중 하나. 생략 시 `generation_inputs.diffusion_model` 기본값. 선택지는 명령 등록 때 Core `GET /v1/standalone-checkpoints`에서 가져온다(1–25개, 기본 모델 우선). text encoder·VAE·sampler·steps·CFG는 서버 설정을 그대로 쓰며 모델별 최적값은 없다. 목록 등록은 모델별 생성·품질 검증을 뜻하지 않는다.
- **Seed**: `seed_mode=random`이면 신규 접수 때 53비트 안전 정수 범위에서 한 번 고르고 저장한다. 멱등 재접수·재시작·전달 재시도에서 다시 고르지 않는다. `seed_mode` 생략은 `fixed`(호환). 사용한 Seed와 모델을 완료 응답과 `/status`에 표시한다. Discord에서 Seed·크기 직접 지정은 없다.
- 입력 한도: 요청 본문 64 KiB, prompt·negative 각 4,000자, checkpoint 100자.
- 생성 설정(크기·업스케일·인코딩)은 서버의 독립 생성 설정을 따른다. 예시 기본은 Anima 1024 생성 → UltraSharp 1.5배(1536) → PNG + WebP.
- 품질 검증(단일·묶음)과 자동 재생성은 요청하지 않는다. 응답에 검증 미요청을 표시하며 생성 성공을 품질 합격으로 해석하지 않는다. 캐릭터 외형·Negative를 임의로 붙이지 않는다.

## 권한 정책 (확정)

- **설치**: 앱 소유자만. Developer Portal에서 Public Bot OFF(`bot_public=false`).
- **사용**: `guild` 모드. 허용 서버 목록의 모든 멤버가 모든 채널에서 사용한다. 허용 서버 목록은 비공개 설정이다(현재 2개). 채널 제한은 두지 않는다.
- **차단**: DM, 다른 서버, (채널 목록을 지정한 경우) 범위 밖 채널. 소유자도 우회할 수 없다. 비었거나 잘못된 목록은 전체 허용으로 취급하지 않는다.
- **결과 공개**: 새 `/draw`는 초기 지연 응답부터 채널에 공개하고, 같은 메시지를 수정해 진행·결과를 표시한다. 첨부는 `SPOILER_` 파일명으로 스포일러를 기본 적용한다. `DISCORD_PUBLIC_RESULTS=true`는 guild 모드에서만 허용된다.
- **`/status`**: 원래 요청자만 조회 가능, 응답은 비공개(ephemeral). 타인 결과는 조회되지 않는다.
- 검사는 Worker와 Bridge 양쪽에서 한다. Worker는 guild 모드에서 `guild_id`/`channel_id`를 Bridge에 전달한다.
- 관리자·결제·조직 권한 체계는 없다. `users` 모드(사용자 ID 목록)는 코드 기본값으로 남아 있으나 운영은 guild 모드다.

## 흐름

```text
Discord → Worker: Ed25519 서명·±5분 timestamp·앱 ID·권한 검사, 지연 응답(type 5)
  → Access(service token) → Tunnel → Bridge 127.0.0.1:8192 (Bridge Bearer)
  → Core 8190 독립 생성 API: 저장·Planner·GPU·Generation 조정
  → Generation 8189 → ComfyUI 8188
  → Bridge가 Core에서 이미지 조회 → 원래 응답 PATCH로 첨부
```

- Worker는 DB·GPU·Core 접근이 없다. 접수를 Bridge에 한 번 전달만 하고 생성 완료를 기다리지 않는다. Bridge 5xx·전송 불명이면 "접수 불명" 안내를 한 번 남기고 자동 재전송하지 않는다. 4xx는 거절로 안내한다.
- Worker 외부 요청은 redirect를 따라가지 않는다(Access 로그인 redirect로 자격 증명이 새지 않게).
- Bridge는 SQL·Generation·LLM에 직접 접근하지 않는 전달용 클라이언트다. Core Bearer로 loopback Core를 호출한다.
- Core는 `standalone_jobs` 테이블에 입력·설정·상태를 저장한다. 기존 groups/tasks에 임시 그룹을 만들지 않으며 결과는 F/E 갤러리에 자동 편입되지 않는다.

## 멱등성·시간 제한

- Discord 초기 응답 3초, interaction token 15분.
- Discord interaction ID를 Bridge 중복 키와 Core 멱등 키 `discord:<ID>`로 쓴다. 응답 유실·재시작 후 기존 키를 조회하며, 확인되지 않은 접수는 명시적 오류로 남기고 자동 재접수하지 않는다.
- Bridge는 접수 후 14분이 지나면 원래 응답 전달을 멈춘다. Core 작업은 계속 추적하며 `/status`의 새 토큰으로 결과를 받는다. 14분 안에 Core 접수조차 못 한 요청은 새로 생성하지 않는다.
- 전달 재시도는 생성과 분리한다(전달 실패로 재생성하지 않음). Discord 429 대기 시간을 따른다.
- 첨부는 PNG 또는 WebP 한 장, Discord 첨부 한도 안에서 요청당 최대 20 MiB만 읽는다. 전달할 파일이 없으면 로컬 보존 상태를 안내한다.
- LLM 추론 중 응답 유실·Core 종료 시 자동 재추론하지 않고 실행 불명 오류로 남긴다. 종료 불명 GPU 권한을 시간 경과로 해제하지 않는다.

## 설정 절차

1. `examples/standalone-generation.example.json`, `examples/discord-bridge.example.json`을 `.atelierx/discord/standalone.json`, `bridge.json`으로 복사해 채운다. LLM 모델은 `.atelierx/gpu-config.json`의 공유 GPU 모델과 같아야 한다. Bridge는 `access_mode: guild`, `allowed_guild_ids`(선택 `allowed_channel_ids`)를 Worker와 맞춘다.
2. 환경 변수: `ATELIERX_PLANNER_API_KEY`(LM Studio), `ATELIERX_DISCORD_BRIDGE_TOKEN`(새 랜덤값, Worker `BRIDGE_TOKEN`과 동일).
3. Bridge 포함으로 파일럿 실행: [로컬 실행·운영](operations.md) 참고. Bridge 단독은 `python -m atelierx.discord_bridge --config .atelierx/discord/bridge.json`과 `ATELIERX_SERVICE_TOKEN`.
4. Worker(`integrations/discord-worker`, Node 22+): `npm ci` → `npm test` → `npx wrangler deploy --dry-run` → `npx wrangler whoami`로 계정 확인 → `npx wrangler deploy`. Secret은 `npx wrangler secret put`: `DISCORD_PUBLIC_KEY`, `DISCORD_APPLICATION_ID`, `DISCORD_ACCESS_MODE`, `DISCORD_ALLOWED_GUILD_IDS`, (선택) `DISCORD_ALLOWED_CHANNEL_IDS`, `DISCORD_PUBLIC_RESULTS`, `BRIDGE_URL`(`https://<bridge-host>/v1/discord/jobs`), `BRIDGE_TOKEN`, `CF_ACCESS_CLIENT_ID`, `CF_ACCESS_CLIENT_SECRET`(둘 다 있거나 둘 다 없어야 함). 설정이 불완전하면 Worker는 `misconfigured`로 거절한다. 로컬 `.dev.vars`는 원격 secret으로 올라가지 않는다. Bot Token은 Worker에 넣지 않는다.
5. Developer Portal에서 Interactions Endpoint URL을 배포된 Worker 주소로 설정하고, Public Bot OFF.
6. 명령 등록: Core가 실행 중일 때 `npm run register-commands`(환경 변수 `DISCORD_APPLICATION_ID`, `DISCORD_BOT_TOKEN`, `ATELIERX_CORE_URL`, `ATELIERX_CORE_TOKEN`, 서버별 등록 시 `DISCORD_GUILD_ID`). `/draw`·`/status`만 등록하고 앱의 다른 명령은 보존한다. 허용 서버마다 실행한다. checkpoint 목록이나 명령 옵션이 바뀌면 재등록한다.
7. 설정·코드 변경은 로컬 파일럿 재시작 후 적용된다. 파일만 바꾸고 재시작하지 않으면 실행 중 Bridge의 허용 목록은 그대로다.

## 확인 상태

- 사용자 확인 완료: Direct 생성→업스케일→Discord 이미지 응답, 공개 결과·기본 스포일러, 무작위 Seed·사용값 표시, 선택 Negative·기본 Direct.
- 등록·연결 확인만: checkpoint 선택 메뉴(5개). 기본 외 모델의 실제 생성·Discord 응답은 사용자 확인 전.
- 두 번째 허용 서버: 설정·명령 등록 완료. 이후 파일럿 재시작으로 적용됐을 것으로 보이나 **새 서버의 권한 확인과 실제 `/draw` 응답 기록은 없다**(확인 필요).
- 미검증: Natural 모드의 Discord 전체 경로, 다른 멤버 실제 계정의 요청, 로컬 오프라인·Tunnel 단절·15분 초과·첨부 한도·동시 요청의 실제 환경 시험(R1), 장기 운영.

## 알려진 한계

- 독립 작업의 취소·수동 재생성 없음(F1). 크기·고정 Seed 입력 없음(F2).
- Natural은 단순 재작성(F3/Q1). Planner 모델은 Validation VLM과 같은 공유 GPU 모델이며 별도 모델 교체 관리는 없다.
- 결과를 F/E에서 보는 전용 화면 없음.
- 로컬 PC·파일럿·Tunnel이 꺼져 있으면 접수 불명/실패로 끝난다. 자동 시작은 아직 없다.
