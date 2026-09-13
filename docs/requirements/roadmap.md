# 후속 확장 로드맵

현재 구현 범위에서 유예한 기능을 보관한다. 구체적인 릴리즈·일정·순서 및 구현 방식은 정하지 않는다. 향후 착수 전 요구사항과 관련 ADR을 논의한다.

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
