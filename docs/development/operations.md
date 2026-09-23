# 로컬 실행·운영

개인 PC 한 대에서 AtelierX를 실행·원격 접속하는 현재 기준이다. 제품 설치 패키지나 배포 절차는 아니다. 작업 이력은 `docs/history/`에 둔다.

## 사전 준비

- Windows / PowerShell. 저장소 `.venv`의 Python(없으면 PATH의 `python`).
- ComfyUI `127.0.0.1:8188`: AtelierX Custom Node와 Anima 모델·text encoder·VAE, 기본 업스케일 모델이 준비된 설치.
- LM Studio `localhost:1234`: Validation VLM과 Discord Natural 변환에 쓰는 모델. 두 용도가 같은 GPU 모델을 공유한다.
- 원격 접속 시 `cloudflared`. Discord Worker 작업 시 Node 22 이상.
- 새 clone에는 아래 비공개 파일·모델·DB가 없다. 소스만으로 바로 실행되지 않는다.

## 비공개 로컬 파일 (`.atelierx/`, Git 제외)

값은 문서·로그·URL에 기록하지 않는다.

| 경로 | 용도 |
| --- | --- |
| `gpu-config.json` | 공유 GPU 조정·LM Studio 모델 ([예시](../../config/gpu.example.json)) |
| `validation-coordinated-config.json` | Validation Provider·Profile·Generation 연결 ([예시](../../config/validation-coordinated.example.json)) |
| `pilot/token.txt` | Core·Generation·Validation 공용 서비스 Bearer. 없으면 실행기가 생성 |
| `pilot/frontend-connection.json` | Access JWT 검증 설정과 서버 저장 Core 토큰 ([예시](../../config/frontend-connection.example.json)) |
| `pilot/core.sqlite3`, `pilot/generation/`, `pilot/validation/` | Core DB, 최종 이미지(`generation/images/`), 검증 데이터 |
| `pilot/logs/` | 실행기 로그 |
| `discord/standalone.json`, `discord/bridge.json` | 독립 생성·Bridge 설정 ([예시](../../examples/)) |
| `discord/` 기타 | Bot·Bridge 토큰, 식별값, Worker secret 원본 |
| `discord-bridge/` | Bridge의 요청별 전달 상태 기록 |
| `cloudflare/tunnel-token.txt`, `tunnel.pid`, `tunnel-*.log` | Named Tunnel 토큰, 실행 PID, 로그 |
| `cloudflare/` 기타 | Access service token 등 Cloudflare 구성 자료 |
| `frontend-pilot-launcher.json` (선택) | 원격 Generation/Validation 연결 ([예시](../../config/frontend-pilot-launcher.example.json)) |

환경 변수(값은 비공개): `ATELIERX_PLANNER_API_KEY`(Natural LLM), `ATELIERX_DISCORD_BRIDGE_TOKEN`(Worker `BRIDGE_TOKEN`과 동일), 원격 서비스 토큰 변수(launcher 설정에서 이름 지정), `ATELIERX_CLOUDFLARED`(선택, cloudflared 경로). Bridge를 함께 실행하면 실행기가 `ATELIERX_SERVICE_TOKEN`을 `pilot/token.txt` 값으로 설정한다.

## 포트

모두 `127.0.0.1`에서만 listen한다.

| 포트 | 서비스 |
| --- | --- |
| 8188 | ComfyUI (외부 프로세스, 실행기가 시작·종료하지 않음) |
| 8189 | Generation |
| 8190 | Core + Frontend `/ui/` |
| 8191 | Validation |
| 8192 | Discord Bridge (선택) |

## 시작

전경 실행기가 현재 표준이다. 터미널에 `[core]`·`[generation]`·`[validation]`·`[discord]`·`[launcher]`·`[status]` 태그 로그가 나온다.

```powershell
scripts\start_frontend_pilot.bat
# Discord Bridge 포함
scripts\start_frontend_pilot.bat -StandaloneConfig .atelierx\discord\standalone.json -DiscordBridgeConfig .atelierx\discord\bridge.json
```

- 직접 실행: `.venv/Scripts/python.exe -B scripts/run_frontend_pilot.py [--standalone-config ...] [--discord-bridge-config ...] [--launcher-config ...]`. Bridge 설정은 standalone 설정을 요구한다.
- 시작 전 필요한 포트(8190, 로컬 8189/8191, Bridge 시 8192)를 모두 검사한다. 하나라도 사용 중이면 어떤 서비스도 만들지 않고 사용 중 포트만 표시한 뒤 종료한다.
- `-LauncherConfig`: `mode: local`에서 `generation_url`/`validation_url`을 지정하면 해당 서비스는 원격으로 연결만 하고 시작·종료하지 않는다(원격 측 Core callback 구성과 실제 원격 동작은 미검증). `mode: remote-ui`는 지정한 UI를 브라우저로 열기만 한다.
- 접속: 로컬 `http://127.0.0.1:8190/ui/`. `/`와 `/ui`는 `/ui/`로 리디렉션한다.
- 콘솔은 토큰 값 대신 `pilot/token.txt` 경로를 안내한다.

## 종료

- `Ctrl+C`는 이 실행기가 시작한 서비스만 종료한다. ComfyUI·LM Studio·Tunnel은 건드리지 않는다.
- 종료 전 활성 작업(Core Task·독립 생성·제작 계획·후처리·검증·묶음·GPU owner/waiting, Generation/Validation Job, Bridge 미전달 건, 원격 서비스 큐)을 센다. 하나라도 있으면 종료를 거절하고 개수를 표시한다. 완료 후 다시 `Ctrl+C`를 누른다. 원격 큐를 읽지 못해도 종료를 거절한다.
- 실행 중 5초마다 상태를 확인하고 변화가 있거나 약 1분마다 `[status] active work: ...`를 남긴다.

## 로그

- 실행기: `.atelierx/pilot/logs/frontend-pilot-<UTC시각>.log`(터미널과 같은 내용).
- 토큰·Authorization·Prompt 포함 메시지·URL query는 가려서 기록한다.
- Tunnel: `.atelierx/cloudflare/tunnel-<시각>.stdout.log` / `.stderr.log`.

## 원격 접속: Cloudflare Tunnel + Access

```text
브라우저 → Access(Google 로그인, 허용 이메일 1개) → https://<atelier-host> → Tunnel → 127.0.0.1:8190
Discord Worker → Access(service token) → https://<bridge-host> → Tunnel → 127.0.0.1:8192
Bridge → Core: 같은 PC loopback, Core Bearer
```

- 원격 관리 Named Tunnel 하나가 두 공개 이름을 각 loopback origin으로 전달한다. 마지막 ingress는 404이며 ingress마다 Access 필수 검사를 설정했다. Core·Generation·Validation·ComfyUI·LM Studio 포트는 직접 공개하지 않는다.
- `<atelier-host>`: Access 앱이 host 전체를 보호한다. `/ui/` GET은 Bearer 예외이므로 Access가 UI 공개 방지 경계다. Access 로그인 방식은 Google IdP만 허용한다(앱 자체의 Google OAuth와는 별개이며, 그 기능은 후속).
- `<bridge-host>`: Worker 전용 service token 정책만 허용. Bridge는 Access 헤더를 직접 검사하지 않고 자체 Bearer를 계속 검사한다(두 겹).
- Frontend는 same-origin 전용이다. API·이미지 `content_url`은 상대 경로이며 CORS를 두지 않는다. UI를 다른 도메인에 두는 구성은 지원하지 않는다.
- service token에는 만료일이 있다(1년). 만료 전 교체가 필요하다.

Tunnel 시작:

```powershell
pwsh -NoProfile -File scripts/start_remote_tunnel.ps1
```

- `cloudflare/tunnel-token.txt`가 필요하다. 토큰 값은 읽어 출력하지 않고 `--token-file`로 전달한다.
- 같은 토큰 파일로 실행 중인 connector가 있으면 no-op. PID 파일이 다른 프로세스를 가리키거나 일치 프로세스가 둘 이상이면 시작을 거부한다.
- 시작 전 8190/8192 도달 여부만 표시하며, 서비스가 없어도 Tunnel은 시작한다. 숨김 창 background 프로세스로 뜬다.
- 종료 스크립트는 없다. `tunnel.pid`의 프로세스를 사용자가 직접 종료한다.

## Access JWT 자동 연결

- 구현: `pilot/frontend-connection.json`이 있으면 실행기가 Core에 전달한다. Core가 `Cf-Access-Jwt-Assertion`의 RS256 서명·issuer·audience·만료·허용 email·요청 host(변경 요청은 Origin도)를 검증하면 브라우저는 Core 토큰 입력 없이 연결된다. JWKS는 서버에서 제한 캐시로 조회한다.
- Frontend는 JWT·JWKS·토큰 원문을 다루지 않는다. `GET /v1/frontend-connection`은 상태만, `PUT`은 현재 Core 토큰과 같은 값의 저장만 허용한다(토큰 회전 아님).
- 파일이 없거나 로컬 접속이면 기존 Bearer 연결: `설정 → Core 연결`에 `pilot/token.txt` 값을 입력하며 현재 탭 메모리에만 보관한다.
- 상태: 코드·격리 검증 완료, 로컬 설정 파일 존재. **외부 브라우저에서 토큰 없이 자동 연결되는 흐름의 명시적 확인 기록은 없다**(확인 필요).

## 아직 없는 것

- Windows 로그인 자동 시작·재부팅 후 복구(서비스·Tunnel 모두). 2026-09-23 결정으로 localhost 운영 제어판의 항목별 "시작 시 자동 켜기"로 구현 예정.
- 실행기의 ComfyUI·LM Studio·Tunnel 시작/종료, 재시작 명령, 서비스 상태 통합 화면.
- 백업·복원, 디스크 부족 대응, 로그 보존 정책, 운영 알림.
- EXE 실행기·Bash/타 OS 지원·깨끗한 PC 설치(설치 배포 단계).
- 참고: `.atelierx/discord/restart-pilot.ps1`은 과거 background 재시작용 로컬 도구다. 실행 중 프로세스의 명령줄을 읽지 못하면 안전 검사로 중단한다. 표준 시작·종료는 위 전경 실행기다.
