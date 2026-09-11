# 기능 요구사항과 범위

이 문서는 사용자가 전달한 기능 요구사항을 기록한다. **요구사항은 구현 완료를 뜻하지 않으며**, 지원 후보와 구체적인 설계는 별도 확정이 필요하다. 아키텍처의 확정 여부는 [overview](../architecture/overview.md), 미정 설계는 [ADR backlog](../architecture/adr/backlog.md)를 참고한다.

원래 공유 대화의 구체 기능 중 이 문서에서 누락·축약된 항목을 [모듈별 기능 대조표](module-feature-comparison.md)에 복원해 사용자 검토 중이다. 이 문서만으로 원문 요구 전체가 보존됐다고 간주하지 않는다. 검토 결과에 따라 본문과 관련 ADR을 갱신한다.

## Core 관리 기능

- 작품, 캐릭터, 캐릭터 외형 관리.
- 의상과 상의 / 하의 / 액세서리 등의 구성 관리.
- Prompt, 전역 Positive / Negative Prompt, 표정 / 상황 / 동작 등의 Prompt 관리.
- Prompt Version 관리.
- 생성 Preset 및 설정, Validation 관련 설정, 애플리케이션 전역 설정 관리.
- 작업 Context 준비와 생성·검증·재생성 흐름 조정. 전체 작업 이력·재생성 상한 관리([ADR-0003](../architecture/adr/0003-generation-execution-and-queue.md)).
- 이미지 Metadata 관리.
- JSON 등의 Import / Export.

Prompt 생성·편집 보조를 위한 Provider 연동을 지원하는 방향이다. 지원 대상으로 Local LLM, OpenAI, Gemini, OpenAI-compatible API 및 향후 추가 Provider를 고려한다. 구체적인 모델·실행 방식·구현 라이브러리는 미정이다.

AI 또는 Agent는 허용된 Core REST API 작업을 사용한다. SQLite나 임의 SQL 실행 권한을 직접 제공하지 않는다. 외부 AI Context는 요청에 필요한 최소 데이터로 제한한다. AI Prompt 변경의 Draft → Review → Apply는 **Proposed**이며 상세 권한과 Secret 관리는 별도 ADR 대상이다.

## Generation 실행 요구 — ADR-0003

[ADR-0003](../architecture/adr/0003-generation-execution-and-queue.md)에 G-01~G-10 검토 결과를 반영했다.

- 각 Node 기능별 REST API와 Node 입력 기준 파라미터를 제공한다. 전체 생성용 Workflow는 Anima 기본·SDXL 보조 두 개이며 단독 기능은 별도 Workflow 또는 부분 실행을 허용한다.
- 생성 → Upscale → Detailing → Censor → 배경 투명화 → Encode 순서로 선택한 후처리를 적용한다.
- Core가 작품·캐릭터·Prompt·생성 및 후처리 설정을 포함한 작업 Context를 준비하고 API로 전달해 생성·검증 흐름을 조정한다. 공유 파일이나 Generation의 DB 직접 접근을 요구하지 않는다.
- Preset Load는 Current Settings 값을 변경한다. 생성 시도 입력은 고정되어 이후 편집의 영향을 받지 않는다. 정확한 Context Schema·접수 계약은 미정이다.
- Validation은 재생성 여부와 해당 이미지의 새 시도에 사용할 변경값을 반환한다. 모든 생성 설정 변경을 허용하되 최소 변경을 기본으로 한다. Core는 상한·이력을 관리하며 원본 Prompt·Preset을 변경하지 않고 새 생성 시도를 요청한다.
- 자동 재생성 설정·변경 가능한 최대 횟수와 수동 재생성을 지원한다. 기본 수치와 오류별 정책은 미정이다.
- 동일 GPU의 Generation 작업은 하나씩 접수 순서대로 실행한다. 대기·실행 취소 및 전체 작업의 후속 단계 중지를 지원한다. 재시작 시 대기를 복원하고 실행 중 작업은 ComfyUI 상태를 확인해 추적하거나 실패 처리한다.
- 현재 실행 Node를 표시한다. 최종 출력 검토를 사용하며 진행 중 이미지 미리보기는 보류다. 결과 파일은 Generation 영역에 보관하고 원격 접근·경로·Metadata 등록 계약은 후속 정의한다.
- Generation은 에러코드·관련 로그·API 오류 정보를 제공한다. Validation의 코드별 예외·복구 정책은 Validation 설계에서 정한다.
- 예상 Queue 2,000~3,000건을 위해 REST 페이지 조회 + SSE 변경 알림을 제공한다. 취소 UI를 즉시 반영하고 실제 중단과 요청 중 상태를 구분한다. 대량 변경 묶음, 필요 페이지 재조회, 누락분 복구 불가 시 재조회를 지원한다. 완료마다 전체 목록 재조회나 전체 목록 반복 SSE 전송은 사용하지 않는다.
- Queue 저장 기술·Batch 묶음·SSE 이벤트 및 복구 계약·Generation과 Validation의 GPU 자원 공유는 미정이다.

## Generation Node 기능

- 생성 Node의 입력 설정을 Preset으로 Save / Load할 수 있어야 한다. Anima / SDXL 전환 시 모델 계열별 설정 혼합과 부적합한 적용을 방지한다(N-16).
- 후처리 Node 또는 Workflow의 설정도 Preset Save / Load를 지원한다(N-17). 개별 단계와 전체 Workflow의 Preset 지원 단위는 미정이다.
- 위 Preset 기능은 [ADR-0002](../architecture/adr/0002-custom-node-functional-scope.md)의 추가 확정 요구다. 자동 Load, 미저장 변경·덮어쓰기 처리, 필드·저장 형식·API는 후속 정의한다.

- ComfyUI 연결 및 Workflow 생성·실행.
- 이미지 생성 및 최종 결과 저장을 위한 Generation 작업.
- Checkpoint, 다중 LoRA 및 개별 Weight, VAE 설정.
- CFG, Steps, Seed, Sampler / Scheduler 등 Advanced 설정.
- Upscale 및 이미지 후처리.
- Generation Job / Progress 제공.

Anima와 SDXL Illustrious 계열 지원은 N-03 검토로 확정했다. 향후 추가 모델은 검토 대상이다. 구체적인 모델 버전별 지원 수준은 미정이다. 별도 생성 Node에 공통 Adapter / Capability 구조를 필수로 요구하지 않는다. 모델별 설정·Preset 검사 세부는 후속 정의한다.

Custom Node의 N-01~N-10 기능은 [ADR-0002](../architecture/adr/0002-custom-node-functional-scope.md)에 확정 기록했다. 생성 입력은 모델, 다중 LoRA·가중치, Positive/Negative Prompt, Resolution, CFG, Steps, Sampler, Scheduler, Seed 등이며 이미지가 출력된다. 설정을 저장하고 기본 모델 제공값으로 초기화한다. SQLite 저장도 허용되나 저장 형식·단위·복원과 기본값 취득·누락 정책은 미정이다.

설치 모델·LoRA 및 Upscale 모델은 ComfyUI 또는 Stability Matrix 설치의 기본 폴더 구조와 사용자 지정 경로를 지원한다. Anima / SDXL의 Scheduler·Text Encoder 차이를 처리하며 생성 Node를 계열별로 분리할 수 있다.

Upscale은 이미지·모델·배율을 입력받으며 Generation Backend에서 이전 생성 이미지를 입력할 수 있다. PNG를 유지하며 별도 WebP를 생성하는 옵션을 제공한다. 눈·입·손·얼굴 Detailer와 NSFW Censor는 ComfyUI-AssetManager의 검출·적용 흐름을 참고할 수 있다. 배경 투명화는 캐릭터를 검출·마스킹하고 이외 영역의 Alpha를 변경한다. WebP 생성 및 배경 투명화는 On / Off 가능하다.

N-01~N-05는 생성, N-06~N-10은 후처리 기능이다. 후처리는 개별 Node / Workflow 또는 통합 Node 구성이 가능하다. Encode / Save는 별도 기능·Node로 분리하고 Frontend는 WebP On / Off와 품질 설정을 제공한다(N-12). Encode는 선택한 후처리의 마지막 단계다(ADR-0003). Encode와 Save 자체의 Node 수·저장 계약은 미정이다.

Upscale 사용자 설정은 모델과 입력 대비 최종 가로·세로 배율만 제공한다(N-13). 예: UltraSharp 4x 모델을 선택하고 최종 배율 1.5 지정. 타일·Overlap·목표 크기·Lossless 옵션은 현재 요구에서 제외하고 WebP 품질은 N-12로 이동한다. 내부 배율 조정·반올림은 미정이다.

Generation에서 캐릭터 일관성을 최대한 확보하는 것이 N-14의 현재 목표다. Anima 자연어 Prompt 활용과 IP-Adapter·Img2Img 등을 수단으로 검토하며 특정 기법의 일괄 지원이나 모델 간 공통 호환성은 확정하지 않는다. Inpaint·ControlNet과 N-15의 Crop·색감·Watermark는 [후속 로드맵](roadmap.md)으로 이관한다.

LoRA **사용**은 지원하며 LoRA **Training**은 현재 핵심 기능 범위에서 제외한다. Generation은 ComfyUI와만 생성 연동하며 AI Provider나 SQLite에 직접 접근하지 않는다.

## Validation 기능

재생성 여부와 해당 이미지에 적용할 설정 변경값을 반환하는 책임은 [ADR-0003](../architecture/adr/0003-generation-execution-and-queue.md)에서 확정했다. Generation 에러코드에 따른 예외·복구 정책, 판정 기준과 반환 Schema는 후속 Validation 설계에서 정한다.

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

Web Frontend는 UI / UX, Form, Tree Explorer, Gallery, Lightbox, 최종 생성 결과 표시(진행 중 이미지 Preview는 보류), Validation Result, Generation / Validation Job 상태, Prompt 편집, Model 관리 UI, 설정 UI, API 호출과 로컬 UI State를 담당한다.

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
