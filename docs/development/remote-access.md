# 고정 Cloudflare Tunnel과 Access 점검 — 2026-09-21

## Google 로그인 전환 완료 — 2026-09-22

사용자가 Google OAuth 자격 증명을 Cloudflare 대시보드에 직접 입력해 Google IdP를 등록했다. AtelierX 앱의 허용 공급자를 Google로 변경하고 기존 `kiritype@gmail.com` 단일 이메일 Allow 규칙을 확인했다. 초기 IdP 테스트에서는 Google `400 redirect_uri_mismatch`가 발생했다. 아래의 웹 애플리케이션 유형 교체와 `https://cftmz.cloudflareaccess.com/cdn-cgi/access/callback` 등록 후 해소됐다.

수정 중에는 Google과 기존 One-time PIN을 함께 허용했다. 사용자가 데스크톱 유형 대신 웹 애플리케이션 OAuth 클라이언트를 만들어 자격 증명을 교체했고, Google 로그인 화면 정상 진입을 확인했다. 이후 사용자가 IdP 테스트의 `kiritype@gmail.com` 반환과 `https://atelier.cftm.net/ui/` 접속 성공을 확인했다. 이에 따라 AtelierX 앱의 PIN 선택을 제거하고 Google만 허용하도록 저장했다. Discord Bridge의 service-token 정책과 Tunnel은 변경하지 않았다. Client Secret은 읽거나 저장소에 기록하지 않았다. 아래 OTP 전용 구성은 최초 적용 시점 기록이다.

사용자는 `https://atelier.cftm.net/` 및 `/ui`에서 404, `/ui/`에서는 정상 접속을 보고했다. 이후 사용자가 작업실 수정과 함께 처리하도록 지시하여 두 진입 주소의 GET/HEAD를 고정 상대 경로 `/ui/`로 리디렉션하도록 구현했다. 검증·운영 반영 결과는 [작업실 개선 기록](studio-tree-navigation.md)을 따른다.

## 확정 구성

다음 구성은 사용자 승인에 따라 2026-09-21에 적용했다. Core·Bridge의 기존 loopback 서비스는 재시작하지 않았다.

| 공개 이름 | Tunnel origin | 사용 주체 | Access 정책 |
| --- | --- | --- | --- |
| `https://atelier.cftm.net` | `http://127.0.0.1:8190` (Core와 `/ui/`) | 브라우저 Frontend와 Core REST | `kiritype@gmail.com`만 일회용 PIN(OTP)으로 허용 |
| `https://bridge.cftm.net` | `http://127.0.0.1:8192` (Discord Bridge) | Cloudflare Worker | Worker용 Cloudflare Access service token만 허용 |

Core와 Bridge는 loopback으로만 listen한다. `atelierx-local` 원격 관리 Tunnel은 각 공개 이름의 모든 경로를 해당 loopback origin으로 전달하며, 마지막 ingress는 `http_status:404`다. 각 ingress에는 `required: true`, Zero Trust team `cftmz`, 해당 Access application의 audience tag를 설정했다. Core의 기존 Bearer service token은 그대로 유지하며, Frontend 번들·URL·query string에는 넣지 않는다.

## 코드 점검 결과

### Frontend와 Core

- Core가 `/ui/`와 정적 asset을 같은 8190 origin에서 제공한다. Frontend `ApiClient`는 현재 페이지 origin만 API base로 허용하고, 모든 요청과 이미지 조회를 상대 경로로 보낸다. 따라서 `https://atelier.cftm.net/ui/`에서 API와 이미지 `content_url`은 같은 origin으로 정상 해석된다.
- Core·standalone·postprocess가 응답에 넣는 `content_url`은 모두 `/v1/...` 상대 경로다. 과거의 `localhost`나 임시 Tunnel 이름이 이미지 URL에 고정되지 않는다.
- Browser API 호출은 Access cookie가 같은 origin 요청에 실린다. 아래의 직접 JWT 검증을 적용하기 전, 2026-09-21에 확인한 기존 흐름에서는 사용자가 연결 화면에 입력한 Core Bearer token만 `Authorization`으로 보냈다. 이 token을 저장·번들·URL에 주입하는 코드는 없다.
- Core는 브라우저 CORS 헤더를 설정하지 않고, Frontend도 다른 API origin을 거절한다. 이는 의도된 same-origin 구성에서는 문제가 없으며, UI를 다른 도메인에 배치하는 구성은 지원하지 않는다.
- 현재 운영 Core는 Cloudflare Access JWT를 직접 검사하지 않고 기존 Bearer token만 검사한다. 따라서 Tunnel이 loopback 8190의 유일한 외부 경로여야 하고, `atelier` Access Application은 전체 공개 host를 보호해야 한다. `/ui/` GET은 Core의 Bearer middleware 예외이므로 Access 정책이 UI 공개 방지 경계다.

### Discord Worker와 Bridge

- Worker의 `BRIDGE_URL` 검증은 HTTPS URL과 정확히 `/v1/discord/jobs` 경로를 요구한다. 운영 값은 `https://bridge.cftm.net/v1/discord/jobs`가 맞다.
- Worker는 항상 기존 `Authorization: Bearer <BRIDGE_TOKEN>`을 Bridge에 보낸다. `CF_ACCESS_CLIENT_ID`와 `CF_ACCESS_CLIENT_SECRET`이 둘 다 Worker secret으로 설정되면 `CF-Access-Client-Id`와 `CF-Access-Client-Secret`도 함께 보낸다. 둘 중 하나만 있으면 Worker는 misconfigured로 요청을 접수하지 않는다.
- Bridge는 Cloudflare Access 헤더를 직접 검사하지 않고 Bridge Bearer token을 계속 검사한다. 따라서 bridge Access Application은 service-token identity를 허용해야 하며, Bridge Bearer는 별도 방어층으로 유지된다.
- Worker의 bridge 요청은 redirect를 수동 처리한다. Access 또는 Tunnel이 로그인 redirect를 반환하면 Worker는 자격 증명을 다른 주소로 전달하지 않고 실패로 기록한다. service-token 정책이 실제로 허용되어야 한다.
- Bridge의 `core_url`은 service origin만 허용하고, Bridge가 Core에 보낼 때 기존 Core Bearer를 사용한다. 두 서비스가 같은 PC에서 loopback으로 통신하므로 Bridge가 `atelier.cftm.net`을 경유하거나 Cloudflare Access browser 정책을 통과할 필요는 없다.

## 적용 기록

- 기존 One-time PIN identity provider를 재사용해 `atelierx-atelier-browser` Access application에만 허용했다. API 재조회에서 application은 reusable Allow 정책 하나만 연결했고, 그 정책은 `kiritype@gmail.com` 한 주소만 포함하며 OTP IdP 하나만 허용함을 확인했다.
- `atelierx-bridge-worker` Access application에는 새 service token 하나만 매치하는 reusable `non_identity` 정책을 연결했다. API 재조회에서 application의 연결 정책은 하나이고, 그 정책의 include rule도 지정한 service token 하나임을 확인했다. token은 enabled이며 API 조회 기준 만료 시각은 `2027-09-21T14:12:44Z`(기간 `8760h`)다. client ID·secret은 Worker remote secret과 Git 제외 로컬 secret 파일에만 보관하고, Tunnel token은 Git 제외 로컬 파일에만 보관한다. 어느 값도 이 문서와 상태 파일에는 기록하지 않는다.
- `atelierx-local` named remote tunnel을 만들고 `atelier.cftm.net`과 `bridge.cftm.net`의 proxied CNAME을 그 Tunnel로 생성했다. API 재조회에서 status는 healthy였고, `pwsh -NoProfile -File scripts/start_remote_tunnel.ps1`는 같은 tunnel connector를 QUIC으로 healthy 상태까지 연결한다. 재실행은 같은 process를 유지하는 no-op임을 확인했다. Windows 로그인 자동 시작과 재부팅 복구는 아직 설정하지 않았다.
- Discord Worker remote secrets와 로컬 Worker secret 자료에 `BRIDGE_URL=https://bridge.cftm.net/v1/discord/jobs`, Access client ID, Access client secret을 반영했다. 기존 Bridge Bearer token은 유지한다. secret 값은 출력하거나 문서화하지 않았다.
- Cloudflare의 기존 named `comfyui-tunnel`은 down 상태로 그대로 두었다. 전환 확인 뒤 별도의 Quick Tunnel process(`--url http://127.0.0.1:8192`)는 종료했고, named `atelierx-local` connector는 유지한다. Core·Generation·Validation·Bridge 실행 서비스는 재시작하지 않았다.

## 외부 경계 검증

새 Tunnel과 Access 적용 뒤 전용 검증으로 다음 8개 경계를 확인했다.

| 요청 조건 | 확인 결과 |
| --- | --- |
| 익명 `atelier`의 `/ui/`, `/v1/queue`, `/health` | Access login으로 302 |
| Bridge service-token identity로 `atelier` 접근 | `atelier`의 browser 정책으로 302 |
| 익명 Bridge 접근 | 403 |
| Bridge Bearer만 | 403 |
| Access service token만 | Bridge 자체 Bearer 검사에서 401 |
| Access service token과 Bridge Bearer 둘 다 | 200 |

초기 DNS cache는 Windows DNS cache를 갱신한 뒤 정상화했고, 공개 resolver에서도 두 이름을 확인했다. 기본 Python user agent는 edge에서 403이었으나 명시적인 연결 점검 user agent에서는 정상 응답했다. 이 차이는 위 Access 경계 결과와 별도로 기록한다.

## 사용자 흐름 확인 완료

- `kiritype@gmail.com`으로 `atelier.cftm.net` Access OTP 로그인 후 Frontend를 열고, 기존 Core Bearer를 연결 화면에 입력하는 **이전 인증 흐름**을 확인했다.
- Discord `/draw` 한 건이 Worker → Access → Bridge → Core를 거쳐 접수되고 결과가 전달되는 것을 확인했다.

## Frontend Access JWT 직접 인증 — 구현 완료, 운영 적용 대기

Cloudflare Access JWT를 Core가 검증해 Frontend의 반복 Bearer 입력을 없애는 후속 구현을 완료했다. server-private `frontend-connection.json`에는 public origin, issuer, audience, 허용 이메일 및 기존 Core token을 두고, Frontend에는 token 원문을 반환하지 않는다. Core는 RS256 서명·issuer·audience·만료·허용 email·요청 host를 확인하며, 기존 Bearer 인증도 호환 경로로 유지한다. Google identity provider는 이번 범위에 포함하지 않는다.

현재 실행 중인 Core에는 아직 이 구현을 적용하기 위한 재시작을 하지 않았고, Access 로그인 뒤 Bearer 없이 자동 연결되는 외부 브라우저 흐름도 아직 검증하지 않았다. 따라서 위에서 확인한 OTP 및 Discord 결과는 기존 Bearer 흐름의 검증 기록이며, 새 자동 연결의 운영 적용 결과가 아니다.

### 후속 구현 검증 결과

- Python 전체 248개 통과: `artifacts/full-suite/frontend-connection-python.log`. Frontend Node 테스트 실행 18개 통과: `artifacts/full-suite/frontend-connection-node.log`.
- 격리 테스트에서는 서명 위조, issuer/audience/email/만료, Host/Origin, 잘못된 Bearer의 인증 전환 금지, 저장 토큰 불일치 후 복구, JWKS 크기 제한 및 갱신 실패 시 오래된 키 거부를 검증했다. 실제 사용자 JWT 검증과는 구분한다.
- 실제 Cloudflare JWKS에서 공개 키 2개를 수신했고, 비공개 로컬 연결 설정의 토큰이 현재 파일럿 토큰과 일치함을 확인했다. 비밀 값은 출력하지 않았다.
- 기존 재시작 스크립트는 서비스·ComfyUI·Discord 대기 작업 검사를 통과했지만 실행 중 프로세스의 명령줄을 확인할 수 없어 `Unexpected service process. Restart skipped.`로 중단했다. 서비스를 종료하거나 Tunnel을 변경하지 않았다. 운영 반영과 실제 외부 브라우저의 무토큰 자동 연결 검증은 사용자 재시작·Access 로그인 후 진행해야 한다.
