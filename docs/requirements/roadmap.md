# 후속 확장 로드맵

2026-09-21 최신 사용자 지시: Discord 봇은 일반 테스트용으로 두고 추가 개발의 순위를 뒤로 미룬다. 본체 Backend/F/E 제작 흐름의 남은 기능을 우선 검토한다. 아래 같은 날짜의 Discord 우선 착수 기록은 당시 범위다. [현재 우선순위 제안](../development/remaining-work-priorities.md).

현재 구현 범위에서 유예한 기능과 사용자가 요청한 후속 확장을 보관한다. 구체적인 릴리즈·일정 및 미확정 구현 방식은 정하지 않는다. 기존 확정 범위의 구현은 계속 진행하며, 제품 정책을 바꾸는 결정은 관련 요구사항·ADR에서 논의한다.

근거: 2026-09-11 [ADR-0002의 N-14~N-15 검토](../architecture/adr/0002-custom-node-functional-scope.md).

| 원래 항목 | 후속 확장 | 상태 |
| --- | --- | --- |
| N-14 | Inpaint | 후속 로드맵으로 이관. 상세 기능·모델 호환성 미정 |
| N-14 | ControlNet | 후속 로드맵으로 이관. 상세 기능·모델 호환성 미정 |
| N-15 | Crop | 후속 로드맵으로 이관. 자르기 규칙·옵션 미정 |
| N-15 | 색감 보정 | 후속 로드맵으로 이관. 보정 항목·옵션 미정 |
| N-15 | Watermark | 후속 로드맵으로 이관. 입력·배치·옵션 미정 |
| G-10 | 별도 LoRA Trainer 또는 외부 Trainer 연동 | 향후 검토 가능. 현재 학습 기능 제외. [ADR-0003](../architecture/adr/0003-generation-execution-and-queue.md) |

캐릭터 일관성을 Generation에서 최대한 확보하는 목표는 현재 요구다. Anima 자연어 Prompt 활용 및 IP-Adapter·Img2Img 등은 그 목표를 위한 기법 검토 대상이며, 위 후속 확장 목록에 일괄 이관하지 않는다. 각 기법의 실제 채택과 모델별 지원은 별도 결정한다.


## 로컬 Agent 제작 흐름·공용 멀티모달 모델 — Backend 완료 후

2026-09-13 사용자 지시로 로드맵에 기록한다. **Backend 3개 완료 후 실제 구현 방식과 모델 운용을 검토**하며, 현재 구현 순서를 Agent/skill 개발로 전환하지 않는다.

- 자연어로 외형·복장·생성 크기·업스케일을 지정하고, 이후 같은 캐릭터의 구도·표정 변형을 요청하는 흐름.
- LM Studio 직접 대화 또는 Hermes/OpenClaw 등의 Agent와 Core REST를 연결하는 도구 adapter 및 제작용 skill 검토.
- 별도 전용 VLM 대신 `qwen3.8-27b-uncensored` 같은 비전 지원 모델 하나를 자연어 요청 처리와 단일/묶음 이미지 검증에 공용으로 사용하는 방향 검토. 역할별 입력/판정 계약은 유지한다.
- 확인된 설치 모델 메타데이터는 vision/tool-use 지원을 표시한다. 실제 도구 호출 정확도, 검증 품질, 처리시간, VRAM 사용은 미검증이므로 최종 모델 선정·상시 로드를 확정하지 않는다.
- 공용 모델 사용과 GPU 상시 상주는 구분한다. RTX 4090에서 Anima 생성과 병행할 때 필요한 unload/reload·실행 순서·Context 보존 방식은 후속 시험으로 결정한다.

확정된 것은 로드맵 등재와 Backend 완료 후 검토 시점이다. Qwen 27B로 현 Validation provider를 교체하거나 skill/MCP를 설치하는 실행 지시는 아니다. 기존 Backend 요구인 Upscale 및 캐릭터 일관성 확보 자체를 이 항목 때문에 유예하지 않는다.

배경·후보 구조: [로컬 Agent 제작 흐름 검토](../development/local-agent-workflow-review.md).

## Discord 자연어 제작 봇 — Cloudflare Workers

2026-09-21 후속 지시로 **개인용 Discord 봇을 우선 구현**한다. 그룹 선택은 필요하지 않다. 자연어→로컬 LLM 프롬프트 변환과 자연어/Positive Prompt 원문 전달의 두 모드를 제공한다. F/E의 기존 분류·그룹 제작은 별도 흐름으로 유지한다. 아래 최초 검토안의 Backend 전체 완료 후 착수·그룹 기반 도구 활용은 봇의 선행 조건이 아니다. 구현 계약과 실제 연결 준비 상태는 [Discord 개인용 봇](../development/discord-personal-bot.md)을 따른다.

최초 로드맵 요청은 **Discord에서 자연어 명령 → 로컬 LLM 해석 → Generation Backend를 통한 이미지 생성 → Discord 이미지 응답**이며, Cloudflare Workers를 사용한다. 다음 구성·검토안은 최초 등재 시점의 기록으로, 위 후속 지시와 현재 구현 계약을 우선한다.

### 구성과 책임

```text
Discord → Cloudflare Workers → 로컬 LLM / 도구 adapter
                              → Core REST → Generation → ComfyUI
Discord ← Workers ← Core 작업 상태·이미지 조회
```

- **Workers**: Discord 요청 인증, 접수 응답, 사용자/채널과 Core 작업 ID 연결, 완료 알림 및 이미지 첨부를 담당한다. 로컬 LLM·GPU 추론은 로컬 PC에서 실행한다.
- **로컬 LLM / adapter**: 자연어를 허용된 제작 입력으로 해석한다. 기존 작품·캐릭터·의상·전역 조각 조회와 제작 요청은 Core REST 도구로 수행한다. 임의 SQL·파일 접근·임의 ComfyUI Workflow 실행을 도구로 노출하지 않는다. 정보가 부족한 요청은 사용자에게 필요한 입력을 묻는다.
- **Core**: 입력 검증, 프롬프트 조합, 설정 snapshot, 작업/제작 계획 상태, GPU 실행 조정을 계속 소유한다. Generation Backend 사용은 Core를 통해 연결하며 Discord 쪽에 업무 규칙을 복제하지 않는다.
- **Generation / ComfyUI**: 기존 생성·업스케일 계약을 실행한다. 봇 응답은 Core에 저장된 결과와 검증 상태를 사용하며, 생성 성공과 품질 합격을 구분한다.

### 구현 검토안과 선행 조건

다음은 기존 정책에 맞춘 구현 검토안이며 세부 제품 정책의 확정은 아니다.

1. 최초 진입점은 자연어 인수를 받는 Slash command와 HTTP interaction을 후보로 한다. 멘션·DM 지원 여부는 별도로 정한다. Discord는 HTTP interaction 수신을 지원하며, Workers 배포 예제를 제공한다. [Discord 공식 Workers 안내](https://docs.discord.com/developers/tutorials/hosting-on-cloudflare-workers)
2. 생성 완료를 초기 HTTP 응답 안에서 기다리지 않는다. Discord의 초기 응답 제한은 3초, interaction token 유효기간은 15분이므로 먼저 지연 응답을 보내고 작업 상태를 추적한다. 15분을 넘는 작업은 별도 완료 메시지 또는 상태 조회 경로가 필요하다. 구체적인 전달 방식은 봇 권한·공개 범위와 함께 정한다. [Discord 응답 계약](https://docs.discord.com/developers/interactions/receiving-and-responding)
3. Workers에서 로컬 서비스로 접근할 인증된 연결이 필요하다. 로컬 origin의 outbound 연결을 사용하는 Cloudflare Tunnel을 후보로 검토한다. Core·Generation·LM Studio의 포트를 그대로 공개하지 않으며, 최소 도구/API 경계와 접근 인증을 설계한다. [Cloudflare Tunnel](https://developers.cloudflare.com/tunnel/)
4. Discord 요청 ID와 Core의 멱등 접수 키·작업/계획 ID를 연결해 중복 전달에도 한 번만 생성한다. 완료 알림 재전송은 이미지 재생성으로 연결하지 않는다. Workers 재시작·로컬 PC 오프라인·응답 유실 시에도 접수 여부를 조회해 복구한다. 클라우드에 필요한 전달 상태 저장 방식은 후속 설계 대상으로 두고 Core의 제작 상태를 복제하지 않는다.
5. 로컬 Planner의 GPU 사용을 기존 Generation/Validation GPU 조정에 연결해야 한다. 모델 선택, unload/reload 비용, 자연어 해석 정확도는 실제 시험으로 결정한다. 공용 멀티모달 모델 채택은 선행 확정 사항이 아니다.
6. 기존 자동 재생성 상한·검증 오류 처리·묶음 검사 후 사용자 확인·기준 revision 정책을 그대로 적용한다. 자연어 명령으로 정책상 필요한 확인을 우회하지 않는다.

착수 시 정할 제품 사항은 허용 사용자/서버, 기존 파일럿 인증과의 연결, Slash command·멘션·DM 범위, 결과 공개/비공개, 장시간 작업 알림 및 이미지 보관 범위다. 첨부 크기 초과 시 전달 방식도 정해야 한다. R2·Queues·Durable Objects·Workflows의 채택은 필요한 전달/복구 요구를 확인한 뒤 판단한다.

### 완료 확인 기준

- 자연어 요청 하나가 의도한 Core 제작 입력으로 변환되어 실제 생성·업스케일 이미지와 상태를 Discord에 반환한다.
- 모호한 입력·권한 없는 요청·중복 interaction·알림 재시도·로컬 서비스 중단·늦은 응답·15분 초과·첨부 제한을 나눠 시험한다.
- 같은 요청으로 중복 생성하지 않고, 로컬 복구 후 기존 작업 조회 또는 명시적 실패로 종료한다.
- Planner와 생성/검증의 GPU 경합을 시험하고, 실제 실행·모의 서비스 시험·미검증 범위를 분리해 기록한다.

현재 기능과 남은 구현은 [2026-09-21 구현 현황 점검](../development/implementation-status-2026-09-21.md)을 참고한다.


## 체크포인트별 Natural 변환 보완 — 후속 과제

2026-09-21 사용자 지적: 현재 Core Natural은 간단한 Positive 문장 재작성이며 체크포인트가 이해하는 어휘·태그·자연어 조합을 고려하지 않는다. 모델별 작성 규칙, 사용자 의도 보존, Direct 대비 실제 이미지 평가를 포함해 나중에 보완한다. Discord/F/E에 변환 로직을 복제하지 않고 Core가 담당한다. 구현된 기본 경로를 모델별 프롬프트 최적화 완료로 보고하지 않는다. 구체 우선순위는 [남은 작업 제안](../development/remaining-work-priorities.md)에서 사용자와 결정한다.


## 개인 사용 UI 안정화 이후 설치 배포 준비 — 2026-09-22 요청

현재 구현과 이후 준비를 구분한다. UI 개편의 실제 흐름 검증 전에 릴리즈 준비 완료로 표시하지 않는다.

| 순서 | 범위 | 완료 기준 |
| --- | --- | --- |
| 현재 | 캐릭터/생성, 검토/갤러리 분리 및 설정 UI | 안전한 외형 이전, 액세서리 포함, 생성 체크 트리, 자원 드롭다운, 작은 체크박스와 모바일 배치 |
| 다음 | 사용자 실제 흐름 테스트 | 대상/조각 선택부터 생성·단일/묶음 검사·검토·갤러리까지 소규모 실제 실행. 자동/모의/실행/미검증 구분 |
| 다음 | 문서 정비·README·웹 매뉴얼 | 현행 기준과 역사 실행 기록 분리, 링크 유지, README는 짧은 소개+설치/실행/첫 생성/매뉴얼 진입점, 안정된 화면의 단계별 캡처 |
| 다음 | 전체 소스 검토 | 결함·책임 혼재·중복을 먼저 목록화하고 위험/효과 순으로 작은 리팩토링. 검토를 전면 재작성으로 취급하지 않음 |
| 릴리즈 후보 | 설치·배포 | 깨끗한 Windows 환경에서 설치/연결/자원 진단/실행/업데이트/사용자 데이터 보존을 검증. 패키지에 모델·토큰·DB·개인 이미지를 포함하지 않음 |

### GitHub About

현재 description/homepage는 비어 있다(2026-09-22 조회). 문구 초안: `ComfyUI 기반 캐릭터 이미지 제작 도구 — 프롬프트 조각을 조합한 일괄 생성, 로컬 VLM 검증, 결과 관리.` 릴리즈 준비 과정에서 저장소 About에 반영한다. 개인 Access 보호 앱 주소를 공개 홈페이지로 자동 지정하지 않으며 웹 매뉴얼 공개 범위와 주소가 확정된 뒤 링크한다.

### 릴리즈 브랜치와 설치 경험

사용자는 UI/UX 완료와 실제 테스트를 마친 버전을 릴리즈 브랜치로 옮기고 설치 배포 기능을 만들도록 후속 요청했다. 기존 CONTRIBUTING의 `develop → main` merge commit / `main` 릴리즈 기준은 유지한다. `release/<version>` 후보 브랜치에서 검증·수정한 뒤 main으로 통합하는 구체 흐름, 버전/태그/설치 형식은 릴리즈 착수 때 확정한다. 현재 후보 브랜치·태그·릴리즈를 만들지 않는다.

첫 설치는 기존 ComfyUI 경로 또는 URL을 지정하고 AtelierX 노드 등록·Generation 연결·Validation Provider·모델 목록을 검사하는 경험이 필요하다. 기존 ComfyUI 설치/워크플로/모델을 덮어쓰지 않으며 실행 중인 큐를 중단하지 않는다. 소스 실행만 성공한 것을 설치 배포 완료로 간주하지 않는다.

### 모델·의존성 안내에 반드시 포함할 내용

- 현재 제품 생성 경로는 `AtelierXAnimaGenerate` 기반 Anima다. SDXL/Illustrious는 요구/로드맵과 현재 구현 지원을 구분하며 일반 checkpoint 파일을 Anima로 사용 가능하다고 안내하지 않는다. 파일 목록 등록은 실제 모델 호환성 검증과 다르다.
- 기본 생성 필수: 호환 Anima diffusion model, text encoder, VAE 및 ComfyUI/AtelierX Anima 노드. 기본 업스케일을 사용하면 해당 upscale 모델도 필요하다. 검증을 켜면 별도 VLM Provider와 모델이 필요하다.
- 선택 기능: LoRA, Detailer 검출 모델·노드, 검열 segmentation 모델·라벨/런타임, Alpha segmentation 모델. 기능별로 없을 때 비활성/오류를 설명하고 모든 모델을 기본 설치 필수로 묶지 않는다.
- 표준 폴더 예시는 ComfyUI의 `models/diffusion_models`, `models/text_encoders`, `models/vae`, `models/loras`, `models/upscale_models`로 안내하되 Stability Matrix 공유 경로/extra_model_paths 사용을 함께 설명한다. 검열·Alpha의 `ultralytics_segm`은 등록된 검색 경로를 확인해야 하며 임의의 물리 경로 하나로 고정하지 않는다. Detailer의 bbox/segm은 설치된 detector 노드 설정을 따른다.
- 모델의 출처·버전/해시·호환성·라이선스·용량을 기능별 지원 표에 기록한다. 다운로드 링크는 작성 시 공식 원문을 확인하며, 재배포나 자동 다운로드 동의는 별개다. 이번 작업에서 모델 다운로드·재배포는 하지 않는다.
- ComfyUI 연결은 Generation이 REST로 담당한다. F/E는 Core 주소만 사용하고, Core/Generation/Validation/ComfyUI의 연결 설정과 정상 확인 방법을 매뉴얼에 포함한다. 현재 PC에 남은 로컬 파일과 새 clone에 없는 파일을 명시한다.
