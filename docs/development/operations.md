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
| `control/settings.json`, `state.json`, `token.txt`, `logs/` | 운영 제어판 설정·관리 프로세스 기록·Core 상태 조회용 읽기 토큰·자식 로그 |
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
| 8180 | 운영 제어판 |
| 8188 | ComfyUI (실행기는 시작·종료하지 않음. 제어판이 시작·종료할 수 있음) |
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

- 직접 실행: `.venv/Scripts/python.exe -B -m atelierx.launcher [--standalone-config ...] [--discord-bridge-config ...] [--launcher-config ...] [--no-generation] [--no-validation]`. 실행기 코드는 `src/atelierx/launcher/`이며 `scripts/run_frontend_pilot.py`는 같은 인자를 받는 호환 wrapper다. Bridge 설정은 standalone 설정을 요구한다.
- `--no-generation`/`--no-validation`(`.bat`에서는 `-NoGeneration`/`-NoValidation`): 로컬 Generation/Validation을 띄우지 않는다. Core는 평소처럼 `127.0.0.1:8189`/`8191`을 가리키며, 포트 검사는 실제로 띄우는 서비스만 한다.
- 시작 전 필요한 포트(8190, 로컬 8189/8191, Bridge 시 8192)를 모두 검사한다. 하나라도 사용 중이면 어떤 서비스도 만들지 않고 사용 중 포트만 표시한 뒤 종료한다.
- `-LauncherConfig`: `mode: local`에서 `generation_url`/`validation_url`을 지정하면 해당 서비스는 원격으로 연결만 하고 시작·종료하지 않는다(원격 측 Core callback 구성과 실제 원격 동작은 미검증). `mode: remote-ui`는 지정한 UI를 브라우저로 열기만 한다.
- 접속: 로컬 `http://127.0.0.1:8190/ui/`. `/`와 `/ui`는 `/ui/`로 리디렉션한다.
- 콘솔은 토큰 값 대신 `pilot/token.txt` 경로를 안내한다.

## 종료

- `Ctrl+C`(또는 `Ctrl+Break`)는 이 실행기가 시작한 서비스만 종료한다. ComfyUI·LM Studio·Tunnel은 건드리지 않는다.
- 종료 전 활성 작업(Core Task·독립 생성·제작 계획·후처리·검증·묶음·GPU owner/waiting, Generation/Validation Job, Bridge 미전달 건, 원격 서비스 큐)을 센다. 하나라도 있으면 종료를 거절하고 개수를 표시한다. 완료 후 다시 `Ctrl+C`를 누른다. 원격 큐를 읽지 못해도 종료를 거절한다.
- 실행 중 5초마다 상태를 확인하고 변화가 있거나 약 1분마다 `[status] active work: ...`를 남긴다.
- 같은 5초 주기에 `.atelierx/control/bundle-stop-request.json`(제어판의 종료 요청)을 읽어 `Ctrl+C`와 같은 기준으로 판단하고, 수락 여부·활성 작업 개수를 `bundle-stop-response.json`에 남긴다. 실행기 시작 시 남아 있던 요청 파일은 지운다.

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

Tunnel 시작·중지·상태 확인(이 PC에는 PowerShell 7(`pwsh`)이 없으므로 Windows PowerShell로 실행한다):

```powershell
powershell -NoProfile -File scripts\start_remote_tunnel.ps1
powershell -NoProfile -File scripts\stop_remote_tunnel.ps1
powershell -NoProfile -File scripts\remote_tunnel_status.ps1
```

- `cloudflare/tunnel-token.txt`가 필요하다. 토큰 값은 읽어 출력하지 않고 `--token-file`로 전달한다.
- 같은 토큰 파일로 실행 중인 connector가 있으면 no-op. PID 파일이 다른 프로세스를 가리키거나 일치 프로세스가 둘 이상이면 시작을 거부한다.
- 시작 전 8190/8192 도달 여부만 표시하며, 서비스가 없어도 Tunnel은 시작한다. 숨김 창 background 프로세스로 뜬다.
- 중지 스크립트는 `tunnel.pid`가 가리키는 프로세스가 실행 파일·`--token-file` 경로까지 일치하는 관리 대상 connector일 때만 종료한다. 일치하지 않으면 종료하지 않고 오류로 거부한다. PID가 이미 종료된 상태면 오래된 PID 파일만 정리한다.
- 상태 스크립트는 cloudflared 버전, PID 파일 상태(실행 중/오래됨/없음), 8190·8192 도달 여부, 최근 로그 파일 위치를 보여 준다.
- cloudflared 버전은 2026.7.3이며 업데이트 권고가 있다(`cloudflared update`). 자동 업데이트는 하지 않으며 필요 시 사용자가 직접 실행한다.

## Access JWT 자동 연결

- 구현: `pilot/frontend-connection.json`이 있으면 실행기가 Core에 전달한다. Core가 `Cf-Access-Jwt-Assertion`의 RS256 서명·issuer·audience·만료·허용 email·요청 host(변경 요청은 Origin도)를 검증하면 브라우저는 Core 토큰 입력 없이 연결된다. JWKS는 서버에서 제한 캐시로 조회한다.
- Frontend는 JWT·JWKS·토큰 원문을 다루지 않는다. `GET /v1/frontend-connection`은 상태만, `PUT`은 현재 Core 토큰과 같은 값의 저장만 허용한다(토큰 회전 아님).
- 파일이 없거나 로컬 접속이면 기존 Bearer 연결: `설정 → Core 연결`에 `pilot/token.txt` 값을 입력하며 현재 탭 메모리에만 보관한다.
- 상태: 코드·격리 검증 완료, 로컬 설정 파일 존재. **외부 브라우저에서 토큰 없이 자동 연결되는 흐름의 명시적 확인 기록은 없다**(확인 필요).

## 운영 제어판 ([ADR-0024](../architecture/adr/0024-local-operations-control-panel.md))

이 PC에서만 여는 웹 화면(`http://127.0.0.1:8180/`)으로 서비스 묶음·ComfyUI·LM Studio 서버·Tunnel을 켜고 끄며 상태·로그·의존성을 본다. 원격에서는 Tailscale+RDP로 이 PC에 접속해 연다. Frontend에는 Core를 거친 읽기 전용 상태만 표시된다.

```powershell
scripts\start_control_panel.bat          # 제어판 실행 후 기본 브라우저로 열기
.venv\Scripts\python.exe -B -m atelierx.control [--port 8180] [--no-autostart] [--open-browser]
```

- 한 번에 하나만 실행된다(`.atelierx/control/control.lock`). 이미 실행 중이면 `--open-browser`는 브라우저만 연다.
- 제어판을 닫아도(`Ctrl+C`/창 닫기) 제어판이 띄운 프로그램은 계속 실행된다. 다시 켜면 `state.json`의 PID·실행 파일·명령줄이 실제 프로세스와 일치하는 항목만 다시 관리 대상으로 인식하고 나머지 기록은 버린다.

| 항목 | 시작 | 종료 조건 | 준비 확인 |
| --- | --- | --- | --- |
| AtelierX 서비스 | `python -m atelierx.launcher` + 시작 옵션(Generation·Validation·Discord Bridge). 옵션 변경은 재시작 시 적용 | 종료 요청 파일로 실행기에 요청. 활성 작업이 있으면 실행기가 거절하고 화면에 개수를 표시. 강제 종료 없음 | `GET 127.0.0.1:8190/health`가 5xx가 아닌 HTTP 응답(인증 설정에 따라 200·401·403) |
| ComfyUI | Stability Matrix 설정(`C:\StabilityMatrix\settings.json`)의 ComfyUI 실행 인자로 `venv\Scripts\python.exe main.py`. `--listen 127.0.0.1 --port 8188`은 항상 강제 | 제어판이 띄운 경우만. `/queue` 비어 있음 + Core GPU owner/waiting 없음(Core 미응답이면 이 검사 생략) → 프로세스 트리 종료 | `GET /system_stats` 200 (최대 180초) |
| LM Studio 서버 | `lms server start` | 제어판이 켠 경우만. `lms ps --json` idle + Core GPU owner 없음 → `lms server stop`. 모델 로드·언로드는 하지 않음 | 1234 포트 listen |
| Cloudflare Tunnel | `cloudflared tunnel run --token-file .atelierx/cloudflare/tunnel-token.txt`, 로그·`tunnel.pid`는 기존 스크립트와 같은 위치 | `tunnel.pid` 프로세스가 실행 파일·`--token-file` 경로까지 일치할 때만(스크립트로 켠 Tunnel도 관리 대상으로 인식) | 식별 규칙에 맞는 프로세스 실행 중 |

- 안전 규칙: 제어판이 시작했고 기록과 일치하는 프로세스만 종료한다. 8188/8190 등을 이미 다른 프로세스가 쓰고 있으면 "외부 실행"으로 표시만 하고 새로 켜지도 끄지도 않는다(Stability Matrix로 켠 ComfyUI 포함). 제어판이 띄운 ComfyUI는 Stability Matrix 화면에 실행 중으로 보이지 않으므로 한쪽 방식만 쓴다.
- 자동 켜기: 항목별 "시작 시 자동 켜기"를 체크하면 제어판 시작 시 ComfyUI·LM Studio → 서비스 → Tunnel 순서로 앞 단계 준비를 확인한 뒤 켠다. 이미 실행 중이고 준비 확인을 통과하면 켠 것으로 본다. 한 단계라도 실패하면 이후 단계는 진행하지 않고 원인을 표시한다.
- 로그인 시 실행: 화면의 "바로가기 만들기"가 `%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\AtelierX Control Panel.lnk`(대상 `scripts\start_control_panel.bat`)를 만든다. 삭제도 같은 화면에서 한다. 관리자 권한은 쓰지 않는다.
- 로그: 서비스·ComfyUI·LM Studio는 `.atelierx/control/logs/<항목>-<UTC시각>.log`, Tunnel은 기존 `.atelierx/cloudflare/tunnel-*.log`. 화면에서 최근 200줄을 본다. 로그는 제어판 화면에만 보이며 Frontend로 전달하지 않는다.
- 의존성 점검(읽기 전용, 약 30초 캐시): ComfyUI 응답, AtelierX Node 등록(`/object_info`), Anima Node 선택 목록, `lms` 설치와 `gpu-config.json`의 모델 존재(`lms ls`는 앱·서버를 깨우므로 LM Studio 서버가 이미 켜져 있을 때만 확인), cloudflared·Tunnel token 파일 존재(내용은 읽지 않음), Validation·GPU 설정 파일 존재, 8180–8192·1234 포트 사용 주체.
- 보안: `127.0.0.1`에만 바인딩한다. 모든 `/api/*`는 Host가 `127.0.0.1:<포트>`/`localhost:<포트>`여야 하고, 변경 요청은 `X-AtelierX-Control: 1` 헤더와 같은 origin(Origin이 있을 때)을 요구한다. Core용 `GET /status`는 `control/token.txt` Bearer가 필요하며 상태·의존성 요약만 반환한다(로그·명령줄·비밀값 없음).
- 설정 파일 `control/settings.json`의 경로 값(`comfyui.stability_matrix_settings`, `comfyui.root`, `lmstudio.lms`, `tunnel.cloudflared`, `services.python`, Bridge 설정 경로)은 직접 편집할 수 있다. 화면에서는 자동 켜기와 서비스 시작 옵션만 바꾼다.
- 실제 확인(2026-09-23): 제어판으로 ComfyUI를 켜면 약 25초 후 준비되며, AtelierX Node 9개·Impact Pack이 등록되고 Anima·Upscale 모델 목록이 `C:\StabilityMatrix\Models` 파일과 일치했다(모델 경로는 ComfyUI 폴더의 `extra_model_paths.yaml`을 ComfyUI가 직접 읽으므로 실행 방식과 무관). 서비스 묶음 시작, Core 경유 운영 현황, 제어판 재시작 후 ComfyUI·서비스 재인식, 외부 실행 LM Studio 종료 거부, 서비스 안전 종료(활성 작업 0 확인)·ComfyUI 종료를 확인했다. 제어판을 통한 Tunnel·LM Studio 켜기/끄기와 자동 켜기·로그인 바로가기는 실제 환경에서 아직 확인하지 않았다.

## 아직 없는 것

- 재부팅 직후 로그인 전 자동 복구(로그인 후 시작프로그램으로 제어판이 뜬다).
- 실행 중 Generation·Validation·Bridge 개별 on/off, 작업 완료 후 종료 예약, 강제 종료.
- 백업·복원, 디스크 부족 대응, 로그 보존 정책, 운영 알림.
- EXE 실행기·Bash/타 OS 지원·깨끗한 PC 설치(설치 배포 단계).
- 참고: `.atelierx/discord/restart-pilot.ps1`은 과거 background 재시작용 로컬 도구다. 실행 중 프로세스의 명령줄을 읽지 못하면 안전 검사로 중단한다. 표준 시작·종료는 위 전경 실행기다.
