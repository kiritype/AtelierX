# 기능 요구사항과 범위

이 문서는 사용자가 전달한 기능 요구사항을 기록한다. **요구사항은 구현 완료를 뜻하지 않으며**, 지원 후보와 구체적인 설계는 별도 확정이 필요하다. 아키텍처의 확정 여부는 [overview](../architecture/overview.md), 미정 설계는 [ADR backlog](../architecture/adr/backlog.md)를 참고한다.

## Core 관리 기능

- 작품, 캐릭터, 캐릭터 외형 관리.
- 의상과 상의 / 하의 / 액세서리 등의 구성 관리.
- Prompt, 전역 Positive / Negative Prompt, 표정 / 상황 / 동작 등의 Prompt 관리.
- Prompt Version 관리.
- 생성 Preset 및 설정, Validation 관련 설정, 애플리케이션 전역 설정 관리.
- 이미지 Metadata 관리.
- JSON 등의 Import / Export.

Prompt 생성·편집 보조를 위한 Provider 연동을 지원하는 방향이다. 지원 대상으로 Local LLM, OpenAI, Gemini, OpenAI-compatible API 및 향후 추가 Provider를 고려한다. 구체적인 모델·실행 방식·구현 라이브러리는 미정이다.

AI 또는 Agent는 허용된 Core REST API 작업을 사용한다. SQLite나 임의 SQL 실행 권한을 직접 제공하지 않는다. 외부 AI Context는 요청에 필요한 최소 데이터로 제한한다. AI Prompt 변경의 Draft → Review → Apply는 **Proposed**이며 상세 권한과 Secret 관리는 별도 ADR 대상이다.

## Generation 기능

- ComfyUI 연결 및 Workflow 생성·실행.
- 이미지 생성 및 최종 결과 저장을 위한 Generation 작업.
- Checkpoint, 다중 LoRA 및 개별 Weight, VAE 설정.
- CFG, Steps, Seed, Sampler / Scheduler 등 Advanced 설정.
- Upscale 및 이미지 후처리.
- Generation Job / Progress 제공.

지원 모델 후보에는 최소한 Anima와 SDXL Illustrious 계열 및 향후 추가 모델을 포함해 검토한다. 모델별 지원 수준과 Adapter / Capability 구조는 아직 결정하지 않는다.

LoRA **사용**은 지원하며 LoRA **Training**은 현재 핵심 기능 범위에서 제외한다. Generation은 ComfyUI와만 생성 연동하며 AI Provider나 SQLite에 직접 접근하지 않는다.

## Validation 기능

Deterministic Validation의 검사 후보:

- 파일 손상, Decode 가능 여부.
- 해상도, Aspect Ratio, 이미지 포맷, Alpha Channel.
- Hash, 중복 이미지, Metadata 확인.

AI / VLM Validation의 검사 후보:

- Prompt와 실제 이미지 비교.
- 머리색, 눈 색, 외형, 의상, 액세서리.
- 표정, 동작, 손 / 얼굴 등의 이상.
- 동일 캐릭터 일관성 및 Character Identity.

AI Validation은 특정 모델에 종속시키지 않는다. Provider 지원 대상으로 Local VLM, OpenAI multimodal model, Gemini multimodal model, OpenAI-compatible local/remote endpoint 및 향후 추가 Provider를 고려한다. Backend 내부 Provider abstraction은 **Proposed**다.

VLM Provider 설정 후보는 Provider type, Endpoint, Model, Authentication, Timeout, Temperature, Max tokens, Max concurrency, Batch size, Input image resolution, Structured output 지원 여부, Multi-image 지원 여부, Retry 설정이다. 필수 여부, 기본값, Provider별 지원 및 적용 위치는 **TODO**다.

Generation과 Validation이 같은 GPU를 사용할 경우의 자원 경합 정책은 별도 ADR에서 결정한다. 검사별 판정 기준, 정확도 보장 및 실패 처리는 아직 확정되지 않았다.

## Client 기능

Web Frontend는 UI / UX, Form, Tree Explorer, Gallery, Lightbox, Generation Preview, Validation Result, Generation / Validation Job 상태, Prompt 편집, Model 관리 UI, 설정 UI, API 호출과 로컬 UI State를 담당한다.

AI Prompt Draft 비교 및 승인 UI는 요구 기능으로 기록하되, 구체적 승인 흐름은 Proposed인 Draft → Review → Apply 결정에 맞추어 확정한다. Model 관리 UI의 Backend 책임과 관리 범위도 TODO다.

CLI는 Arguments → Shared API Client → REST API의 얇은 Command Adapter다. Backend 비즈니스 로직을 중복 구현하지 않는다.

Codex 등의 개발 Agent, OpenClaw, Hermes 및 향후 MCP 기반 Agent가 SDK 또는 REST를 통해 작업할 수 있어야 한다. 구체적인 Agent별 연동 및 MCP 제공 방식은 아직 결정하지 않는다.

## 저장 및 이동성

- Runtime DB는 SQLite, 이미지 및 대형 모델 파일은 Filesystem에 저장한다.
- DB에 Image ID, Relative Path, Hash, Generation Metadata, Prompt Snapshot, Model Metadata, Validation Result, Job 정보 등의 Metadata를 저장한다. 상세 Schema는 미정이다.
- 파일명 또는 실제 경로를 Primary Key로 사용하지 않는다.
- JSON 등의 Import / Export는 Backup, Migration, Sharing, Character Export, Work Export, Prompt Preset Export, Settings Export를 위한 용도로 사용한다.
- JSON은 Runtime DB를 대체하지 않는다. 이미지 포함 ZIP + manifest는 검토 후보이며 Backup / Migration의 상세 정책은 미정이다.

## 배치 요구사항

모든 서비스를 한 PC에 배치하거나 여러 머신에 분산할 수 있어야 한다. Core / Generation / Validation Backend URL은 각각 설정 가능해야 하며 AI Provider Endpoint와 별도로 취급한다. 네트워크 인증, 파일 전송 및 GPU 공유 세부 정책은 TODO다.
