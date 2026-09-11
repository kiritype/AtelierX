# AtelierX 아키텍처 개요

상태: 초기 초안. 아래 **확정 기준선**은 사용자가 확정한 내용을 기록한 것이며, 별도로 표시한 Proposed / TODO는 승인되지 않았다.

기준선 기록일: 2026-09-11. 이후 변경은 [ADR 절차](adr/README.md)를 통해 반영한다.

## 목적과 현재 단계

AtelierX는 ComfyUI 기반의 로컬 중심 캐릭터 이미지 제작 플랫폼이다. 이미지 생성·관리·후처리·검증과 Agent 자동화를 지원한다. 현재는 설계 및 요구사항 확정 단계이며 제품 구현을 시작하지 않는다.

## 확정 기준선

| 영역 | 확정된 내용 |
| --- | --- |
| Repository | 단일 GitHub Monorepo. 서비스별 별도 Repository로 분리하지 않음. 원격: https://github.com/kiritype/AtelierX.git |
| 구성 요소 | Frontend, Core, Generation, Validation, CLI, Shared API Client / SDK, Shared Schemas / Types, Documentation |
| Backend | Core / Generation / Validation의 3개 서비스. 동일 Repository에서 관리하며 독립 프로세스·서비스로 실행 가능 |
| API | 각 Backend가 REST API 제공. REST API First, REST가 canonical contract, 별도 BFF 없음 |
| Client | Frontend·CLI·Internal Tools는 Shared API Client / SDK 사용. 외부 Agent는 SDK 또는 REST 직접 호출 가능 |
| Frontend / CLI | Thin Client 지향. CLI는 Arguments → Shared API Client → REST API의 얇은 Command Adapter |
| Core | SQLite 및 애플리케이션 주요 상태 소유. Prompt AI Provider 연동 가능 |
| Generation | 생성 연동 대상은 ComfyUI. SQLite 및 AI Provider에 직접 접근하지 않음 |
| Validation | Deterministic 및 AI / VLM 검증 담당. 특정 AI 모델에 종속시키지 않음 |
| 배치 | 단일 PC 및 여러 머신 배치 지원. Core / Generation / Validation URL을 각각 설정 가능 |
| 저장 | Runtime DB는 SQLite. 이미지·대형 모델 파일은 Filesystem. DB에는 구조화된 데이터·Metadata·Path 저장 |
| 식별 | 파일명이나 실제 경로를 Primary Key로 사용하지 않음. 구체적 ID 정책은 TODO |
| 이동성 | JSON 등의 Import / Export 지원. JSON은 Runtime Database 대체 수단이 아님 |
| LoRA | 생성 시 사용 지원. Training은 현재 핵심 범위에서 제외 |
| 릴리즈 경계 | AtelierX 전체 버전 기준의 프로젝트 릴리즈. 각 서비스 및 CLI는 독립 패키징 가능해야 함. 세부 정책은 TODO |
| 브랜치 역할 | develop을 별도 개발 통합 브랜치로 운영하고 main에서 릴리즈. 일반 작업은 develop, hotfix는 main에서 분기. [ADR-0001 부분 결정](adr/0001-contribution-workflow.md). 릴리즈 트리거는 미정 |
| 병합 | 일반 작업 → develop 및 hotfix → main은 Squash merge. develop → main 및 main → develop은 Merge commit |
| 개발 운영 | 현재 1인 개발. 리뷰 기준·브랜치 보호는 최초 릴리즈 완료 후 도입 검토. 현재 적용하지 않으며 자동 활성화하지 않음 |
| Git 초기 구성 | GitHub 기본 브랜치는 develop. 최초 문서 커밋을 main에 push하고 동일 커밋에서 develop 생성. [기여 안내](../../CONTRIBUTING.md) |

Commit / PR 메시지는 Conventional Commits의 `type(scope): 요약` 형식으로 확정했다. type·scope는 영문, 요약·본문은 한국어 기본이다. PR 본문은 목적·결과, 관련 결정, 검증, 영향을 기록한다. 상세는 [ADR-0001](adr/0001-contribution-workflow.md)을 따른다.

## 논리적 구성

```text
Frontend / CLI / Internal Tools
              ↓
    Shared API Client / SDK
              ↓
Core REST API / Generation REST API / Validation REST API

외부 Agent → SDK 또는 각 REST API

Core       → SQLite / Prompt AI Provider
Generation → ComfyUI
Validation → Deterministic 검사 / VLM·Multimodal AI Provider
```

화살표는 역할과 연동 관계를 나타낸다. [ADR-0003](adr/0003-generation-execution-and-queue.md)에 따라 Core가 Context 준비와 생성 → 검증 → 필요 시 새 생성 시도를 조정한다. Generation은 확정 입력을 실행하며 파일은 Generation 영역에 보관한다. 파일 전송과 구체 API 계약은 미정이다. Shared Schemas / Types의 언어, 생성 방식 및 API 명세 도구도 미정이다.

## 서비스 책임

**Core**는 작품·캐릭터·외형·의상 구성, Prompt 및 Version, Preset, Validation 설정, 이미지 Metadata, 전역 설정, Import / Export를 관리한다. AI나 Agent는 허용된 Core REST API 작업만 수행하며 SQLite 또는 임의 SQL 실행 권한을 직접 받지 않는다. 외부 AI에는 요청 수행에 필요한 최소 Context만 전달한다.

**Generation**은 Node별 REST API, Anima·SDXL 전체 생성용 Workflow, 단독 후처리 실행, Job·Queue·Node 상태와 오류 정보를 제공한다. 결과 파일은 Generation 영역에 보관한다. 파일 전송과 Core Metadata 등록 절차는 미정이다.

**Validation**은 Deterministic 및 AI / VLM 검증과 재생성 여부·해당 시도의 설정 변경값 반환을 담당한다. Core가 재생성 상한과 이력을 관리하며 새 입력을 Generation에 전달한다. Generation 에러코드별 예외·복구 정책과 설정·결과의 상세 계약은 Validation 설계에서 정한다.

상세 기능은 [요구사항](../requirements/scope.md), 책임 경계는 [모듈 문서](../modules/README.md)를 참고한다.

## 배치와 Endpoint

각 서비스의 Endpoint는 독립적으로 설정할 수 있어야 한다. 예를 들어 PC A에는 Generation과 ComfyUI, PC B에는 Validation과 Local VLM, PC C 또는 A에는 Core와 SQLite, Client PC에는 Frontend와 CLI를 배치할 수 있다. 모든 구성 요소를 한 PC에서 실행하는 구성도 지원한다.

Prompt AI 및 Validation AI의 Provider Endpoint는 세 Backend의 서비스 Endpoint와 별도 설정이다. ComfyUI는 Generation의 이미지 생성 연동 대상이다. 분산 배치를 위해 공유 Filesystem이 필수라고 가정하지 않으며 이미지 전송·접근 방식은 TODO다.

## 데이터와 Import / Export

SQLite는 구조화된 데이터를 저장한다. 저장 대상으로 Image ID, Relative Path, Hash, Generation Metadata, Prompt Snapshot, Model Metadata, Validation Result, Job 정보 등을 고려한다. 실제 테이블 구조 및 저장 수명주기는 아직 확정하지 않는다.

JSON 등의 Import / Export는 Backup, Migration, Sharing, Character / Work / Prompt Preset / Settings Export 용도를 지원하는 방향이다. 구체적인 포맷, 호환성 및 Backup 보장 정책은 미정이다.

## Proposed — 승인되지 않은 방향

- [ADR-0001: Contribution 워크플로](adr/0001-contribution-workflow.md): 브랜치 역할·주요 흐름·메시지·기본 브랜치·최초 초기화는 확정. 작업 브랜치 관리 및 기타 Repository 설정 세부는 논의 중이다. 리뷰·보호 세부는 최초 릴리즈 이후 재검토한다.
- AI Prompt 변경에 기본적으로 Draft → Review → Apply 사용을 고려한다.
- Validation Backend 내부 Provider abstraction을 고려한다.
- 내부 Entity에 UUID 등의 안정적인 ID 사용을 고려한다. UUID 자체는 미확정이다.
- 이미지 포함 Export에 ZIP + manifest 구조를 검토한다.

## TODO — 후속 ADR에서 결정

Stack, Framework, AI 실행·구현 방식, Secret 및 권한, SQLite 동시성, 서비스 간 통신, Queue·SSE의 상세 계약, Schema·Compiler, 모델 관리, GPU Scheduling, 파일·Metadata·ID 세부 정책, Backup·Migration 및 개발·릴리즈 세부 정책은 미정이다. 아래 ADR-0003의 확정 범위와 구분한다.

전체 질문과 후보 순서는 [ADR backlog](adr/backlog.md)에 관리한다. 확정된 기준선을 변경하려면 변경 사유와 영향을 포함한 ADR을 사용자와 논의한다.

## Generation 실행 및 Queue — ADR-0003

[확정 ADR](adr/0003-generation-execution-and-queue.md): Core가 작업 Context를 API로 전달하고 전체 생성·검증 흐름을 조정한다. Preset Load는 Current Settings를 변경하며 생성 시도 입력은 고정된다. Validation은 재생성 여부와 최소 변경 원칙의 설정 변경값을 반환한다. 원본 Prompt·Preset은 유지하고 자동 재생성 On / Off·최대 횟수 설정 및 수동 재생성을 지원한다. 기본 횟수는 미정이다.

전체 생성용 Workflow는 Anima(기본)·SDXL(보조) 두 개이며 생성 → Upscale → Detailing → Censor → 배경 투명화 → Encode 순서에서 선택한 후처리를 실행한다. 단독 API는 별도 Workflow 또는 부분 실행을 허용한다. 최종 출력 검토를 사용하며 진행 중 이미지 미리보기는 보류다.

동일 GPU의 Generation 작업은 하나씩 접수 순서대로 실행한다. 대기·실행·전체 작업 취소를 지원하고 실제 중단 전에는 취소 중 상태를 구분한다. 재시작 시 대기는 복원하고 실행 중 작업은 ComfyUI 상태 확인 후 추적하거나 실패 처리한다. GPU를 공유하는 Validation과의 자원 조정은 미정이다.

예상 Queue 2,000~3,000건을 고려해 REST 페이지 조회 + SSE 변경 알림을 사용한다. 전체 목록의 반복 전송은 하지 않는다. 대량 변경은 묶음 알림 또는 관련 목록 재조회로 처리하고 재연결 시 누락분 복구가 불가하면 표시 중인 목록을 재조회한다. 이벤트·페이지·복구 상세 계약은 미정이다.

Generation은 에러코드·작업 및 실패 단계와 연결된 로그·API 오류 정보를 제공한다. 오류별 예외·복구 정책은 Validation 설계에서 정한다. 파일은 Generation 영역에 보관하고 원격 접근·Metadata 등록·경로 규칙은 미정이다.

## Custom Node 기능 확정 — ADR-0002

별도 생성 Node에 공통 Adapter / Capability 구조를 필수 전제로 두지 않는다. 구체 구조는 미선택이며 모델별 설정·Preset 검사는 필요하다.

생성 Node와 후처리 Node / Workflow는 각각 설정 Preset Load / Save를 제공한다(N-16~N-17). 생성 Preset은 Anima / SDXL 전환 시 계열별 설정이 섞이거나 부적합하게 적용되는 것을 방지해야 한다. 자동 Load, 미저장 변경 처리, 후처리 Preset 단위 및 구체적인 저장·호환성 계약은 미정이다.

[ADR-0002](adr/0002-custom-node-functional-scope.md)에서 N-01~N-10을 확정했다. 생성 Node는 모델·다중 LoRA와 가중치·Positive/Negative Prompt·해상도·CFG·Steps·Sampler·Scheduler·Seed 등을 받아 이미지를 출력하며 설정을 저장한다. 저장 형식은 미정이고 SQLite도 허용되지만 Core 소유 원칙은 유지한다.

Anima / SDXL의 Scheduler와 Text Encoder 차이를 처리하며 생성 Node를 분리할 수 있다. 설치 모델·LoRA·Upscale 모델 목록은 ComfyUI / Stability Matrix 기본 폴더 구조와 사용자 지정 경로를 지원한다. 초기값은 기본 모델 제공값을 사용하되 취득·누락 정책은 미정이다.

후처리는 이전 생성 이미지를 입력받는 Upscale, 눈·입·손·얼굴 Detailer, NSFW Censor, 캐릭터 마스크 기반 배경 Alpha 처리를 제공한다. 배경 투명화와 PNG를 유지하는 별도 WebP 생성은 On / Off 가능하다. 후처리는 개별 Node / Workflow 또는 통합 Node로 구성할 수 있다. Encode / Save는 별도 기능·Node로 분리하고 Frontend는 WebP On / Off와 품질 설정을 제공한다. Upscale 사용자 설정은 모델과 입력 대비 최종 배율만 제공한다. 예: UltraSharp 4x + 1.5배. 내부 배율 처리·크기 반올림·저장 계약은 미정이다.

N-14의 현재 목표는 Generation에서 캐릭터 일관성을 최대한 확보하는 것이다. Anima 자연어 Prompt 활용과 IP-Adapter·Img2Img 등은 기법 검토 대상이며 일괄 지원은 확정하지 않는다. Inpaint·ControlNet과 N-15의 Crop·색감·Watermark는 [후속 로드맵](../requirements/roadmap.md)으로 이관한다.
