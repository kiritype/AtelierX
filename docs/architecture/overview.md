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

화살표는 역할과 연동 관계를 나타낸다. 서비스 간 요청 순서, Job orchestration, 결과 전달 및 파일 전송 프로토콜은 아직 정의하지 않는다. Shared Schemas / Types의 언어, 생성 방식 및 API 명세 도구도 미정이다.

## 서비스 책임

**Core**는 작품·캐릭터·외형·의상 구성, Prompt 및 Version, Preset, Validation 설정, 이미지 Metadata, 전역 설정, Import / Export를 관리한다. AI나 Agent는 허용된 Core REST API 작업만 수행하며 SQLite 또는 임의 SQL 실행 권한을 직접 받지 않는다. 외부 AI에는 요청 수행에 필요한 최소 Context만 전달한다.

**Generation**은 ComfyUI 연결, Workflow 생성·실행, 이미지 생성 및 후처리, 생성 설정과 Job / Progress를 담당한다. 최종 결과 저장을 위한 생성 작업을 수행하되 파일 저장 책임, 전송, Core Metadata 등록의 구체적인 절차는 후속 ADR에서 정한다.

**Validation**은 파일·이미지 특성에 대한 Deterministic 검증과 Prompt 일치·외형·Character Identity 등에 대한 AI / VLM 검증을 담당한다. 설정·결과의 지속 저장 흐름 및 서비스 간 전달 방식은 미정이다.

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
- 모델 차이를 처리하는 Adapter / Capability 구조를 논의한다.
- 내부 Entity에 UUID 등의 안정적인 ID 사용을 고려한다. UUID 자체는 미확정이다.
- 이미지 포함 Export에 ZIP + manifest 구조를 검토한다.

## TODO — 후속 ADR에서 결정

Stack, Framework, AI 실행·구현 방식, Secret 및 권한, SQLite 동시성, 서비스 간 통신, Queue·진행 이벤트, Schema·Compiler, 모델 관리, GPU Scheduling, 파일·Metadata·ID 정책, Backup·Migration 및 개발·릴리즈 정책은 모두 미정이다.

전체 질문과 후보 순서는 [ADR backlog](adr/backlog.md)에 관리한다. 현재 개별 Accepted ADR은 없다. 확정된 기준선을 변경하려면 변경 사유와 영향을 포함한 ADR을 사용자와 논의한다.
