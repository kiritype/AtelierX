# 후속 확장 로드맵

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

2026-09-21 사용자 요청으로 로드맵에 추가한다. **Discord에서 자연어 명령 → 로컬 LLM 해석 → Generation Backend를 통한 이미지 생성 → Discord 이미지 응답**이 목표이며, Cloudflare Workers를 사용한다. 이번 변경은 로드맵 등재다. 봇 코드·클라우드 자원·Discord 앱 배포 및 모델 교체는 아직 수행하지 않았다.

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
