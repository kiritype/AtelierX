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
