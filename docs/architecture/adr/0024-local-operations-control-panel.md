# ADR-0024: 로컬 운영 제어판과 Frontend 운영 현황

- 상태: Accepted
- 작성일: 2026-09-23
- 확정일: 2026-09-23
- Supersedes: 없음
- Superseded by: 없음
- 관련 요구사항 / ADR: [roadmap 2026-09-23 절](../../requirements/roadmap.md), [현행 정책 §4](../../policies.md), [로컬 실행·운영](../../development/operations.md), [ADR-0003](0003-generation-execution-and-queue.md), [ADR-0016](0016-validation-execution-and-gpu-sharing.md)

## 결정할 질문

개인 PC 한 대에서 AtelierX 서비스와 외부 의존 프로그램(ComfyUI·LM Studio·cloudflared)을 켜고 끄고, 상태·로그·의존성을 확인하는 **로컬 운영 제어판**의 프로세스 구조, 관리 범위, 종료 안전 규칙, Frontend 현황 제공 경로를 정한다.

## 배경과 제약

2026-09-23 사용자 확정 사항(roadmap):

- localhost 전용 웹 제어판. 사용자 권한으로 실행하며 관리자 권한 작업(Windows 서비스 등록·방화벽·예약 작업)은 쓰지 않는다.
- toggle 단위는 서비스 묶음(Core 포함)·Generation·Validation·Discord Bridge·ComfyUI·LM Studio·Tunnel. Backend 개별 on/off가 어려우면 묶음으로 둔다.
- 기존 단일 서비스 프로세스를 유지한다.
- 원격 on/off는 없다. 원격 조작은 Tailscale+RDP로 로컬 제어판을 연다. Frontend는 상태 조회만 한다.
- 제어판이 ComfyUI를 직접 실행할 수 있으며 Stability Matrix 인자를 쓰되 `--listen 127.0.0.1`로 제한하고 동시 실행을 막는다.
- 항목별 "시작 시 자동 켜기" 체크박스, 의존 순서(ComfyUI·LM Studio → 서비스 → Tunnel)로 준비 확인 후 켠다.
- 자신이 시작한 프로세스만 종료하고, 종료 전 활성 작업을 확인한다.

현재 코드 사실:

- `scripts/run_frontend_pilot.py`가 Core(8190)·Generation(8189)·Validation(8191)·선택 Bridge(8192)를 한 프로세스에서 포트별 aiohttp runner로 띄운다. 종료는 SIGINT(Ctrl+C)만 받으며 활성 작업이 있으면 거절한다.
- Windows에서는 숨김 창 자식 프로세스에 Ctrl+C를 보낼 수 없다. 새 프로세스 그룹으로 띄운 자식에는 `CTRL_BREAK_EVENT`를 보낼 수 있다.
- Tunnel은 `scripts/start|stop_remote_tunnel.ps1`이 `.atelierx/cloudflare/tunnel.pid`와 `--token-file` 경로로 관리 대상을 식별한다.
- Stability Matrix의 ComfyUI 실행은 `venv\Scripts\python.exe main.py <인자>`다. LM Studio는 `lms` CLI로 서버를 시작·중지할 수 있다.
- Core는 Frontend를 같은 origin(8190 `/ui/`)에서 제공하며 Frontend는 Core API만 호출한다.

## 검토한 대안

| 대안 | 장점 | 단점 |
| --- | --- | --- |
| A. 제어판을 서비스 묶음 프로세스 안에 둔다 | 추가 프로세스 없음 | 서비스 재시작·장애 때 제어판도 함께 내려감. 코드 갱신 후 재시작 불가 |
| **B. 별도 제어판 프로세스가 서비스 묶음·외부 프로그램을 자식으로 관리** | 서비스 재시작·장애와 독립. 코드 갱신 후 서비스만 재시작 가능. 단일 서비스 프로세스 유지 결정과 양립 | 프로세스 1개 추가. 자식 재인식(PID 파일) 필요 |
| C. 서비스별 별도 프로세스 + 제어판 | 서비스 개별 on/off가 자연스러움 | 사용자가 단일 프로세스 유지를 결정함 |
| D. 네이티브 GUI/트레이 | OS 통합 | 사용자가 웹 방식을 결정함. 설치 배포 단계로 유예 |

Frontend 현황 경로:

| 대안 | 장점 | 단점 |
| --- | --- | --- |
| **F1. Frontend → Core `GET /v1/operations/status` → 제어판 loopback 조회** | Frontend는 Core만 호출한다는 원칙 유지. Access·Core 인증 그대로 적용 | Core에 읽기 전용 경로 1개 추가 |
| F2. 제어판이 파일에 상태를 쓰고 Core가 읽음 | HTTP 호출 없음 | 로컬 파일 형식에 Core가 결합. 오래된 파일 판별 필요 |
| F3. Frontend가 제어판을 직접 호출 | Core 변경 없음 | 원격 브라우저에서 loopback 불가. 원칙 위반 |

## 제안 / 결정

2026-09-23 사용자 확정: 대안 **B + F1**을 채택한다. Generation·Validation·Bridge의 실행 중 개별 on/off 제외, 제어판 실행 ComfyUI가 Stability Matrix 화면에 보이지 않는 점, 실행기 패키지 이동과 종료 신호 처리 추가를 사용자가 확인했다.

### 프로세스 구조

```text
제어판 (atelierx.control, 127.0.0.1:8180, 사용자 권한)
 ├─ 서비스 묶음 = 기존 파일럿 실행기 (Core 8190 + 선택 Generation·Validation·Bridge)
 ├─ ComfyUI (SM venv python main.py, --listen 127.0.0.1)
 ├─ LM Studio 서버 (lms server start/stop)
 └─ cloudflared named tunnel (기존 token-file·PID 파일 규칙 공유)
```

- 제어판은 `src/atelierx/control/` 패키지와 `atelierx-control` 실행 명령으로 추가한다. 의존성은 기존 aiohttp만 쓴다. 화면은 제어판이 직접 제공하는 작은 정적 페이지다.
- 자식 프로세스는 제어판과 분리(새 프로세스 그룹)해 띄우고 PID·실행 파일·명령줄을 `.atelierx/control/state.json`에 기록한다. 제어판을 재시작해도 기록과 실제 프로세스가 일치하면 다시 인식하며, 제어판 종료가 자식을 종료하지 않는다.
- 파일럿 실행기의 서비스·실행 인자·안전 종료 로직은 유지하고, 제어판에서 호출하기 쉽도록 실행기를 패키지 모듈로 옮긴다. 기존 `.bat`/`.ps1` 전경 실행은 계속 지원한다.

### toggle 단위

| 항목 | 방식 |
| --- | --- |
| 서비스 묶음 | 실행기 프로세스 시작·안전 종료·재시작 |
| Generation·Validation·Discord Bridge | 묶음의 **시작 옵션**(체크박스). 변경은 묶음 재시작 시 적용. 실행 중 개별 on/off는 이번 범위에 넣지 않는다 |
| ComfyUI | 제어판 실행·종료. Stability Matrix 등 외부에서 켠 경우 "외부 실행"으로 표시만 하고 종료하지 않으며, 8188이 사용 중이면 새로 켜지 않는다 |
| LM Studio | `lms server start`/`stop`. 제어판이 켠 경우에만 종료. 모델 로드·언로드는 기존 GPU 조정이 맡는다 |
| Tunnel | 기존 스크립트와 같은 PID 파일·식별 규칙으로 시작·종료 |

### 종료 안전 규칙

- 제어판이 시작하고 기록과 일치하는 프로세스만 종료한다. 불일치하면 거부한다.
- 서비스 묶음은 활성 작업(Task·계획·후처리·검증·묶음·GPU owner/waiting·Generation/Validation Job·Bridge 미전달)이 하나라도 있으면 종료를 거절하고 개수를 보여 준다. 강제 종료 버튼은 두지 않는다.
- 제어판의 서비스 묶음 종료 요청은 `.atelierx/control/`의 **종료 요청 파일**로 전달한다. 실행기는 기존 5초 상태 확인 주기에 요청을 읽어 Ctrl+C와 같은 안전 종료 경로로 처리하고, 수락 여부와 활성 작업 개수를 응답 파일에 남긴다. Windows 콘솔 신호는 제어판 재시작 뒤 이미 떠 있는 자식에게 전달되지 않기 때문이다(구현 보완, 2026-09-23).
- 실행기는 SIGBREAK(`Ctrl+Break`)도 SIGINT와 같은 안전 종료 경로로 처리한다. 활성 작업 검사는 실행기 한 곳에서 수행해 기준을 하나로 유지한다.
- ComfyUI 종료 전 `/queue`가 비어 있고 GPU owner가 없어야 한다. LM Studio 종료 전 `lms ps` idle과 GPU owner 없음을 확인한다.
- 제어판은 모델 다운로드·설치, ComfyUI 큐 조작, DB 수정을 하지 않는다.

### 자동 시작

- `.atelierx/control/settings.json`에 항목별 "시작 시 자동 켜기"와 묶음 시작 옵션을 저장한다.
- 제어판 시작 시 체크된 항목만 ComfyUI·LM Studio → 서비스 묶음 → Tunnel 순서로, 앞 단계의 준비 확인(포트·health) 후 켠다. 준비 실패 시 다음 단계로 진행하지 않고 원인을 표시한다.
- Windows 로그인 시 제어판 실행은 사용자 시작프로그램 폴더 바로가기로 한다. 제어판 화면의 명시적 버튼으로 생성·삭제하며 관리자 권한을 쓰지 않는다.

### 상태·로그·의존성 점검

- 상태: 항목별 실행/외부 실행/중지/준비 중/오류, PID, 시작 시각, 포트, 최근 오류 요약.
- 로그: 자식의 stdout/stderr를 `.atelierx/control/logs/<항목>-<시각>.log`에 기록하고 화면에서 최근 줄을 본다. 서비스 묶음 로그는 기존 실행기의 비밀값·프롬프트 가림 규칙을 따른다. 로그는 제어판 화면에서만 보이며 Frontend로 전달하지 않는다.
- 의존성 점검(읽기 전용): ComfyUI 도달·AtelierX Node 등록(`/object_info`), Generation 자원 목록의 필수 모델, LM Studio 설치·설정 모델 존재, cloudflared 실행 파일·token 파일 존재, 포트 사용 주체.

### 보안

- 제어판은 `127.0.0.1`에만 바인딩한다.
- 변경 요청(시작·종료·설정)은 Host가 `127.0.0.1:8180`/`localhost:8180`이고, Origin이 같고, 사용자 지정 헤더가 있을 때만 받는다. 다른 사이트의 브라우저 요청(CSRF)과 DNS rebinding을 막기 위해서다.
- Core → 제어판 상태 조회는 `.atelierx/control/token.txt`의 읽기 전용 토큰을 쓴다. 이 토큰으로는 상태만 읽을 수 있다.

### Frontend 운영 현황 (F1)

- Core에 `GET /v1/operations/status`(기존 Core 인증)를 추가한다. Core가 제어판 `GET /status`를 짧은 timeout으로 조회해 항목 상태·의존성 점검 요약만 반환한다. 제어판이 없으면 `control_panel: unavailable`을 반환한다.
- Frontend는 설정의 "실행 환경 상태" 영역에 이 정보를 읽기 전용으로 표시한다. 조작 버튼과 로그는 두지 않는다.
- 서비스 묶음이 꺼지면 Frontend 자체가 열리지 않으므로, Frontend 현황은 서비스가 켜져 있는 동안의 외부 프로그램·Tunnel 상태 확인 용도다.

## 영향과 트레이드오프

- 서비스 경계: Core에 읽기 전용 운영 경로 1개와 제어판 조회 클라이언트가 추가된다. Core는 제어판을 조작하지 않는다. Generation·Validation은 변경 없음.
- 실행기: 패키지 모듈 이동과 SIGBREAK 처리 추가. 기존 전경 실행 방식은 유지된다.
- Generation·Validation 개별 on/off는 묶음 재시작으로만 바뀐다. 실행 중 개별 전환은 후속으로 둔다.
- 제어판이 직접 띄운 ComfyUI는 Stability Matrix 화면에 실행 중으로 보이지 않는다. 사용자는 한쪽 방식으로만 실행해야 하며, 제어판은 포트 점유로 중복을 막는다.
- ComfyUI를 Stability Matrix 밖에서 띄우면 SM이 넣는 환경 변수·모델 경로 설정과 달라질 수 있다. 첫 실행에서 Node·모델 목록이 SM 실행과 같은지 확인해야 한다.
- 로그인 전(재부팅 직후)에는 아무것도 실행되지 않는다. RDP 로그인 후 시작프로그램으로 제어판이 뜬다.

## 이번에 결정하지 않는 사항

- 실행 중 Generation·Validation·Bridge의 개별 on/off.
- 작업 완료 후 종료 예약, 강제 종료.
- EXE·트레이·다른 OS 지원(설치 배포 단계).
- 로그 보존 기간·자동 정리(O3).
- LM Studio 모델 선택·사전 로드 정책.

## 충돌 및 대체 확인

- ADR-0003(Generation 실행·큐), ADR-0016(Validation 실행·GPU 공유): 제어판은 큐·GPU 권한을 조작하지 않고 조회만 하므로 충돌 없음.
- 현행 정책 §4(원격 on/off 없음, Frontend 상태 조회만): 일치.
- "Frontend는 Core만 호출": F1로 유지.
- 대체하는 ADR 없음.

## 문서 반영

- [x] overview 갱신
- [x] ADR 목록 및 backlog 갱신
- [x] 관련 요구사항 / 모듈 / 개발 문서 갱신 또는 해당 없음 기록
- [x] 기존 ADR 상태 및 supersede 관계 확인
- [x] 미결정 사항이 확정 내용에 섞이지 않았는지 확인
