# AtelierX 아키텍처 개요

2026-09-22 제작 계획 검사 선택 확장: 사용자 승인으로 생성만/단일 검사/단일+묶음 검사를 지원한다. Core가 계획별 검사 범위와 실제 Seed(-1 요청 시 이미지별 난수)를 고정하고 재접수·복구에 재사용한다. 미검사 이미지의 생성 완료를 품질 합격으로 바꾸지 않는다. REST 세부와 검증 상태는 [제작 계획 계약](../api/prompt-fragments-production-plans.md)을 따른다.

2026-09-22 최신 확정: 작품 > 캐릭터 > 의상 계층은 유지하되 외형 소유권은 캐릭터로 이동한다. 의상에는 상의·하의·액세서리를 두고, 조각의 세 요소 포함 여부에 따라 Core가 합성한다(외형 항상 포함). ADR-0021/0022의 해당 과거 의상 외형 배치만 대체하며, 기존 그룹·작업 스냅샷과 revision 이력은 소급 변경하지 않는다.

2026-09-22 사용자 승인: [전역 조각·모바일 제작 UI](../development/frontend-library-ux-review.md)를 구현한다. 조각은 사용자 관리 단일 계층 카테고리와 전체 고유 자동 번호(불변·재사용 없음)를 사용한다. 캐릭터/의상별 검증 통과 결과를 이미지셋으로 조회하고, 파일명 구조는 보류한다. 반응형 탐색·입력·상태 보존을 포함하며 Core의 실행·판정 책임을 유지한다.

2026-09-21 개인용 원격 Frontend 인증 보완: Google OAuth 연결은 후속으로 미루고, Core가 Cloudflare Access의 서명·발급자·대상 애플리케이션·허용 사용자와 요청 출처를 검증한다. 서버 비공개 설정의 Core 연결 토큰을 사용해 브라우저의 반복 입력을 없애며, 기존 서비스 Bearer 인증은 유지한다. Frontend 설정에서는 연결 상태와 저장 토큰 교체만 제공하고 원문을 반환하지 않는다. 별도 BFF는 두지 않는다. [설정과 검증 상태](../development/remote-access.md).

2026-09-21 Discord 서버 추가: 사용자가 지정한 두 번째 서버도 허용 범위에 포함한다. 두 허용 서버의 모든 채널에서 멤버가 사용할 수 있으며 다른 서버와 DM은 차단한다. [운영 반영 상태](../development/discord-personal-bot.md).

2026-09-21 최신 사용자 지시: Discord 봇은 일반 테스트용으로 두고 추가 개발의 순위를 뒤로 미룬다. 본체 Backend/F/E 제작 흐름의 남은 기능을 우선 검토한다. 아래 같은 날짜의 Discord 우선 착수 기록은 당시 범위다. [현재 우선순위 제안](../development/remaining-work-priorities.md).

2026-09-21 Discord 권한 변경: 설치 권한(Discord 앱 소유자 한정)과 사용 권한(지정 서버/채널의 모든 멤버)을 분리한다. Worker는 서명된 서버·채널·멤버 정보를 검사하고 Bridge도 동일 범위를 재검사한다. Core 작업 조정 책임과 요청자별 결과 소유권은 유지한다.

2026-09-21 사용자 지시: 배포 전 개인용 사용과 Discord 봇 구현을 우선한다. Discord는 F/E 분류·그룹과 독립된 자연어/원문 생성 요청이다. Workers는 수신·인증, 로컬 Bridge는 전달, Core는 독립 생성 상태·Planner·GPU·Generation 조정을 담당한다. 기존 그룹을 임의 생성하지 않으며 Core의 별도 `standalone_jobs`에 저장한다. [구현·권한·대기 계약](../development/discord-personal-bot.md).

2026-09-13 최신 사용자 정정: 조각 기반 제작에서는 **외형을 항상 포함**한다. 전역 공유 조각은 본문과 **상의·하의 포함 여부만** 저장하며 appearance 선택 필드는 두지 않는다. 아래 과거 조각별 외형 선택 설명을 대체한다. 전역 Positive + 외형 + 선택한 상의/하의 + 조각 본문, 전역 Negative + 캐릭터 Negative를 사용한다. 구현·테스트를 계속 진행하도록 승인됐다.


2026-09-13 최신 조각 설계: Core가 작품/캐릭터/의상과 독립된 전역 공유 Prompt 조각을 소유한다. 조각별 외형·상의·하의 포함 여부와 본문을 대상 의상 그룹에 적용하고 실행 snapshot에 고정한다. 기존 캐릭터 연결 조각·별도 공통 Prompt 권고를 대체한다. [확정 반영 flow](../development/batch-production-flow-review.md). 구현 전 계약 정리 단계다.

2026-09-13 UI 후속 지시: 제작·갤러리의 분류 트리와 자유 다중 행 Prompt 입력을 지원한다. Core는 custom 구도와 명시적 영역 포함을 받아 preview/snapshot에 원문을 고정한다. 대량 조각 라이브러리는 기존 Core Batch·검증 흐름과의 [사전 검토](../development/batch-prompt-fragments-review.md) 단계다.

[ADR-0023](adr/0023-negative-prompt-sources.md): 전역 Negative는 생성 전용, 캐릭터 Negative는 생성 및 금지 요소 검증에 사용한다. Core가 합성 문구와 출처를 시도별 고정한다. [현재 API 명세](../api/rest-api.md).

상태: 초기 초안. 아래 **확정 기준선**은 사용자가 확정한 내용을 기록한 것이며, 별도로 표시한 Proposed / TODO는 승인되지 않았다.

기준선 기록일: 2026-09-11. 이후 변경은 [ADR 절차](adr/README.md)를 통해 반영한다.

## 목적과 현재 단계

2026-09-13 사용자 승인한 생성만/생성 후 검증 선택을 Core Task에서 처리한다. Client는 시작 요청·상태 표시, Core는 후속 검증 접수·GPU 조정·취소 전달을 담당한다. [실행 범위 및 한계](../development/core-orchestration-validation.md).

2026-09-13 후속 사용자 지시로 Frontend 제외 Backend·SDK·CLI 구현을 시작했다. 아래 과거 ADR 전용 문구보다 이 지시가 우선한다. 첫 구현은 [Generation Anima REST 경로](../development/generation-rest.md)이며 Node 준비 확인 후 순차 실제 실행을 검증했다. Backend 전체 구현 완료나 미정 정책의 일괄 Accepted 전환을 뜻하지 않는다.

2026-09-13 개발 순서 확정: Backend 3개 최소 통합 흐름·기능 확장 → Shared API Client 기반 CLI → Frontend. Custom Node는 병행한다. 현재는 ADR 검토를 계속하며 [개발 순서](../development/README.md)에 범위를 기록했다. 구현 개시와 구분한다.

AtelierX는 ComfyUI 기반의 로컬 중심 캐릭터 이미지 제작 플랫폼이다. 이미지 생성·관리·후처리·검증과 Agent 자동화를 지원한다. 현재 Backend 설계·요구사항 정리와 ComfyUI Custom Node 개발을 병행한다. 2026-09-12 사용자 지시로 설치된 Anima 이미지 생성 Node부터 구현·테스트하며 [개발 범위](../modules/custom-nodes-design.md)를 따른다. 다른 Backend 구현이나 미정 ADR을 일괄 승인하지 않는다.

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

[ADR-0022](adr/0022-prompt-composition.md) 확정: Core가 전역 퀄리티 → 외형 → 상의 → 하의 → 선택한 구도·표정·동작·상황 순서로 Positive를 조합한다. 상반신에서는 하의와 그 안의 풋웨어·체인을 제외한다. Negative는 전역을 기본으로 사용하고 초기 의상별 Negative 저장 항목은 두지 않는다. 분류명 자동 삽입·일반 조합의 AI 재작성·번역·유사 문구 삭제·후순위 자동 덮어쓰기는 하지 않는다. 확인 가능한 모순은 생성 전 수정하도록 안내하고 최종 문구를 확인 가능하게 제공하며 시도별로 고정한다.

전역 및 의상 Prompt 구성 확정(ADR-0021): 전역 Positive(퀄리티)·Negative를 별도 관리한다. 의상 내부는 외형 / 상의 / 하의(풋웨어 포함)로 구분한다. 실제 조합·구도별 적용 상세는 후속 결정이다.

현재 category 구조(2026-09-13 추가 정정)는 **작품 > 캐릭터 > 의상(외형 포함)** 이다. 외형·복장 Prompt는 의상 항목 안에서 관리하며 외형을 별도로 선택·조합하는 계층은 두지 않는다. 아래 과거 독립 외형 관계 표현보다 [ADR-0021 현재 확정 구조](adr/0021-core-domain-and-image-groups.md)가 우선한다. 그룹은 해당 의상 항목의 외형·복장 내용을 고정한다.

2026-09-13 사용자 정정: 작품 / 캐릭터 / 의상은 Prompt 편집·저장 category이며 작품은 생성 Prompt에 포함하지 않는다. category 이름의 자동 삽입·category 순서에 따른 조합을 뜻하지 않는다. 아래 ADR-0021의 관계는 승인 이력을 유지하되 독립 도메인 모델이 필수라는 해석을 중단하고 category 관계·재사용 표현을 재검토한다. 상세는 [ADR-0021 정정 기록](adr/0021-core-domain-and-image-groups.md)을 따른다.

[ADR-0021](adr/0021-core-domain-and-image-groups.md) 확정: 캐릭터는 작품과 독립적으로 관리하고 여러 작품에 연결하며, 여러 독립 외형 중 하나를 선택한다. 의상은 캐릭터 간 재사용하고 전용 변형은 복제한다. 그룹은 외형·의상 구성을 고정하며 같은 조합으로 별도 그룹 생성도 가능하다. 기존 그룹 추가는 고정 구성, 수정 구성은 새 그룹을 사용한다. 데이터 수정은 과거 이미지·진행 중 작업에 소급하지 않는다. 기본 정리는 보관이고 참조 중 영구 삭제를 제한하며 작품 보관으로 연쇄 삭제하지 않는다.

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

## 묶음 검증 — ADR-0007 확정

[ADR-0007](adr/0007-group-image-validation.md): 묶음 비교 대상은 단일 검증 통과 이미지이며, 그룹에서 유지할 외형·의상을 비교하고 자세·구도·표정 차이는 허용한다. 중복 검사는 초기 범위에서 제외한다. 문제 이미지만 기준 이미지와 재검증하고 선택 대상 판정만 갱신하며 이력을 보존한다. 시스템이 기준을 선정하고 사용자가 수정할 수 있다. 기준 교체 시 기존 결과는 이전 기준의 기록으로 보존하고 사용자 확인 후 그룹을 재검증한다. 결과를 보고 사용자가 선택 재생성을 확인하며 새 결과는 단일 검증 후 일관성을 검사한다. 자동 선정 알고리즘·Schema는 미정이다.

## Proposed — 승인되지 않은 방향

- [ADR-0005: Validation 응답 구조와 에러코드](adr/0005-validation-response-contract.md): passed / rejected / error 응답 분리, 초기 에러코드·HTTP 매핑·소비자 처리 설계안. ADR-0004의 확정 원칙을 구체화하는 초안이며 아직 승인되지 않았다.

- [ADR-0001: Contribution 워크플로](adr/0001-contribution-workflow.md): 브랜치 역할·주요 흐름·메시지·기본 브랜치·최초 초기화는 확정. 작업 브랜치 관리 및 기타 Repository 설정 세부는 논의 중이다. 리뷰·보호 세부는 최초 릴리즈 이후 재검토한다.
- AI Prompt 변경에 기본적으로 Draft → Review → Apply 사용을 고려한다.
- Validation Backend 내부 Provider abstraction을 고려한다.
- 내부 Entity에 UUID 등의 안정적인 ID 사용을 고려한다. UUID 자체는 미확정이다.
- 이미지 포함 Export에 ZIP + manifest 구조를 검토한다.

## TODO — 후속 ADR에서 결정

Stack, Framework, AI 실행·구현 방식, Secret 및 권한, SQLite 동시성, 서비스 간 통신, Queue·SSE의 상세 계약, Schema·Compiler, 모델 관리, GPU Scheduling, 파일·Metadata·ID 세부 정책, Backup·Migration 및 개발·릴리즈 세부 정책은 미정이다. 아래 ADR-0003의 확정 범위와 구분한다.

전체 질문과 후보 순서는 [ADR backlog](adr/backlog.md)에 관리한다. 확정된 기준선을 변경하려면 변경 사유와 영향을 포함한 ADR을 사용자와 논의한다.

## Validation 판정과 실행 오류 — ADR-0004

[ADR-0004](adr/0004-validation-outcomes-and-errors.md): Validation은 이미지와 해당 생성 시도의 Prompt를 입력받아 Local VLM 또는 외부 AI Vision으로 검증한다. Core는 자세·구도에 맞춰 Prompt를 구성한다. 명시 요소가 보이지 않거나 상이하면 불합격이며, upper body에서 제외한 하의·footwear처럼 Prompt에 없는 요소는 해당 일치 검사 대상이 아니다.

Provider 오류·응답 파싱 실패 등 검증 실행 오류는 불합격과 구분해 에러코드로 반환하고 자동 이미지 재생성으로 연결하지 않는다. [ADR-0006](adr/0006-validation-manual-retry.md)에 따라 완료 응답 `outcome=error` 이후 자동 검증 재시도도 도입하지 않는다. 사용자는 기존 이미지·생성 Prompt로 다시 검증하거나 수동 재생성을 선택하며 Core가 요청·이력을 관리한다. 다시 검증은 이미지 재생성 횟수에 포함하지 않는다. 전체 응답 Schema·에러코드와 Generation 오류별 복구는 미정이다.

## Generation 실행 및 Queue — ADR-0003

[확정 ADR](adr/0003-generation-execution-and-queue.md): Core가 작업 Context를 API로 전달하고 전체 생성·검증 흐름을 조정한다. Preset Load는 Current Settings를 변경하며 생성 시도 입력은 고정된다. Validation은 재생성 여부와 최소 변경 원칙의 설정 변경값을 반환한다. 원본 Prompt·Preset은 유지하고 자동 재생성 On / Off·최대 횟수 설정 및 수동 재생성을 지원한다. 2026-09-13 추가 확정: 수동 재생성은 횟수 제한이 없으며 자동 재생성 상한은 Core 설정으로 지정하고 기본값은 5회다. 최초 생성과 수동 재생성은 자동 재생성 횟수에 포함하지 않는다. 수동 재생성 요청마다 자동 사용 횟수를 0으로 초기화하고 설정 상한을 새로 부여하며 기존 이력은 보존한다. 자동 상한은 0 이상 정수(0이면 자동 생성 없음)이고 실제 실행 시작 시 차감한다. 대기 취소는 제외하고 실행 후 실패·취소는 포함한다. 생성 후 Validation 오류는 횟수 유지·자동 종료, 상한 도달은 마지막 결과 보존·추가 자동 생성 종료로 처리한다. 설정 변경은 새 생성·수동 요청부터 적용하며 진행 중인 흐름은 기존 설정을 유지한다. 자동 재생성 Off와 오류 후 자동 실행 금지는 유지한다.

전체 생성용 Workflow는 Anima(기본)·SDXL(보조) 두 개이며 생성 → Upscale → Detailing → Censor → 배경 투명화 → Encode 순서에서 선택한 후처리를 실행한다. 기본 생성 해상도는 1024×1024이고 기본 Upscale 설정은 UltraSharp 4x 등 4배 모델의 고유 배율과 별도로 최종 1.5배를 요청해 1536×1536을 목표로 한다. 사용자가 명시한 해상도·모델·최종 배율은 기본값보다 우선한다. 단독 API는 별도 Workflow 또는 부분 실행을 허용한다. 최종 출력 검토를 사용하며 진행 중 이미지 미리보기는 보류다.

동일 GPU의 Generation 작업은 하나씩 접수 순서대로 실행한다. 대기·실행·전체 작업 취소를 지원하고 실제 중단 전에는 취소 중 상태를 구분한다. 재시작 시 대기는 복원하고 실행 중 작업은 ComfyUI 상태 확인 후 추적하거나 실패 처리한다. GPU를 공유하는 Validation과의 자원 조정은 미정이다.

예상 Queue 2,000~3,000건을 고려해 REST 페이지 조회 + SSE 변경 알림을 사용한다. 전체 목록의 반복 전송은 하지 않는다. 대량 변경은 묶음 알림 또는 관련 목록 재조회로 처리하고 재연결 시 누락분 복구가 불가하면 표시 중인 목록을 재조회한다. 이벤트·페이지·복구 상세 계약은 미정이다.

Generation은 에러코드·작업 및 실패 단계와 연결된 로그·API 오류 정보를 제공한다. 오류별 예외·복구 정책은 Validation 설계에서 정한다. 파일은 Generation 영역에 보관하고 원격 접근·Metadata 등록·경로 규칙은 미정이다.

## Custom Node 기능 확정 — ADR-0002

별도 생성 Node에 공통 Adapter / Capability 구조를 필수 전제로 두지 않는다. 구체 구조는 미선택이며 모델별 설정·Preset 검사는 필요하다.

생성 Node와 후처리 Node / Workflow는 각각 설정 Preset Load / Save를 제공한다(N-16~N-17). 생성 Preset은 Anima / SDXL 전환 시 계열별 설정이 섞이거나 부적합하게 적용되는 것을 방지해야 한다. 자동 Load, 미저장 변경 처리, 후처리 Preset 단위 및 구체적인 저장·호환성 계약은 미정이다.

[ADR-0002](adr/0002-custom-node-functional-scope.md)에서 N-01~N-10을 확정했다. 생성 Node는 모델·다중 LoRA와 가중치·Positive/Negative Prompt·해상도·CFG·Steps·Sampler·Scheduler·Seed 등을 받아 이미지를 출력하며 설정을 저장한다. 저장 형식은 미정이고 SQLite도 허용되지만 Core 소유 원칙은 유지한다.

Anima / SDXL의 Scheduler와 Text Encoder 차이를 처리하며 생성 Node를 분리할 수 있다. 설치 모델·LoRA·Upscale 모델 목록은 ComfyUI / Stability Matrix 기본 폴더 구조와 사용자 지정 경로를 지원한다. 초기값은 기본 모델 제공값을 사용하되 취득·누락 정책은 미정이다.

후처리는 이전 생성 이미지를 입력받는 Upscale, 눈·입·손·얼굴 Detailer, NSFW Censor, 캐릭터 마스크 기반 배경 Alpha 처리를 제공한다. 배경 투명화와 PNG를 유지하는 별도 WebP 생성은 On / Off 가능하다. 후처리는 개별 Node / Workflow 또는 통합 Node로 구성할 수 있다. Encode / Save는 별도 기능·Node로 분리하고 Frontend는 WebP On / Off와 품질 설정을 제공한다. Upscale 사용자 설정은 모델과 입력 대비 최종 배율만 제공한다. 기본값은 4배 모델과 최종 1.5배(1024×1024 입력 시 1536×1536)이며, 모델 고유 4배와 최종 배율은 별도다. 내부 배율 처리·크기 반올림·저장 계약은 미정이다.

N-14의 현재 목표는 Generation에서 캐릭터 일관성을 최대한 확보하는 것이다. Anima 자연어 Prompt 활용과 IP-Adapter·Img2Img 등은 기법 검토 대상이며 일괄 지원은 확정하지 않는다. Inpaint·ControlNet과 N-15의 Crop·색감·Watermark는 [후속 로드맵](../requirements/roadmap.md)으로 이관한다.

## 묶음 기준 선정·비교 부족 — ADR-0008

[ADR-0008](adr/0008-group-reference-selection.md)에서 단일 검증 통과 후보 중 특징이 잘 보이는 대표 1장과 필요한 보조 이미지의 시스템 선정·사용자 수정을 확정했다. 후보 없음은 대기, 그룹 1장은 묶음 검사 미실행, 일부 특징 비교 불가는 명시하고 전체 합격으로 표시하지 않는다. 대표·보조 충돌은 사용자 확인을 요청한다. 새 이미지는 기존 기준으로 개별 검사하며 기준 삭제는 새 선정·사용자 확인·기준 교체 절차를 따른다. 현재 확정 기준이며 향후 변경 날짜·사유·이전/새 기준·기존 판정 영향을 ADR에 기록한다. 점수·구체 알고리즘·묶음 응답 Schema는 미정이다.

## 묶음 결과·그룹 요약 — ADR-0009

[ADR-0009](adr/0009-group-validation-results.md) 확정: 이미지별 일치/불일치/비교 불충분/실행 오류와 근거, 실제 대표·보조 및 당시 기준, 검증 범위·현재 유효성을 기록한다. 그룹은 전체 일치/불일치 있음/판정 미완료로 집계하며 불충분·오류·미검증 수를 함께 표시한다. 부분 재검증을 전체 완료처럼 표시하지 않고 정상 결과와 이력을 보존한다. 사용자 선택 재검증·불일치 대상 재생성 확인을 지원하며 확인 중 기준 변경은 변경 안내 후 재확인한다. 필드명·enum·HTTP·Schema·집계 대상 ID 및 동시성 상세는 미정이다.

## 그룹 완료·부분 실패 — ADR-0010

[ADR-0010](adr/0010-group-completion-and-partial-failure.md) 확정: Core는 생성 요청의 대상 목록을 고정하고 모든 대상의 생성·단일 검증·허용 자동 재생성이 완료 또는 실패/취소/상한으로 종료되면 최종 단일 통과 이미지로 묶음 검증을 요청한다. 통과 2장 이상이면 일부 실패에도 진행하며 실패·오류·불합격 종료·취소의 제외 사유를 표시한다. 전체 취소는 후속 묶음 검증을 막고 개별 취소는 나머지 처리를 유지한다. 사용자 수동 요청을 기다리며 기존 처리를 무기한 대기시키지 않는다. 통과 0장은 묶음 대기, 1장은 미실행으로 표시한다. 나중에 추가된 결과는 기존 기준으로 검사한다. 생성 성공/실패 현황과 실제 비교 범위의 일관성 요약을 분리하며 완료 결과·이력을 보존한다. 구체 상태·접수·동시성은 미정이다.

## 검증 입력 정보 — ADR-0011

[ADR-0011](adr/0011-validation-input-context.md) 확정: 공통 입력은 추적·검사 설정·이미지 식별/접근 정보, 단일 입력은 실제 Positive/Negative Prompt·생성/후처리 설정·기대 최종 출력 조건, 묶음 입력은 그룹·이번 대상 목록·대표/보조와 기준 식별·이미지별 Prompt·유지할 외형/의상 정보로 구분한다. 단일 검증은 후처리까지 끝난 최종 이미지를 최종 출력 조건과 비교한다. Core가 필요한 Context를 준비하며 Validation은 DB에서 추가 조합하지 않는다. Validation API의 내부 식별/추적 정보와 AI 입력을 구분하고 외부 AI에는 검사에 필요한 최소 Context만 전달한다. 필수/선택·정보 부족·전송 방식·Schema는 미정이다.

## 이미지 전달·입력 부족 — ADR-0012

[ADR-0012](adr/0012-validation-image-transfer-and-required-input.md) 확정: 로컬/분산 모두 Generation 이미지 조회 API를 Validation이 사용하고 직접 요청은 미등록 이미지 업로드를 허용한다. 이미지 식별·무결성을 연결하고 접근 실패/파일 변경은 오류로 처리한다. 단일 입력은 이미지·실제 Positive Prompt·검사 설정 필수, Negative Prompt 미사용은 빈 값 명시. 묶음은 그룹·대상·대표/기준 식별·대상별 Prompt·공통 외형/의상 필수, 보조는 선택하되 비교에 필요하면 제공한다. 필수 누락은 AI 호출 전 오류, 재생성 설정만 부족하면 판정은 반환하되 자동 제안 없이 사유를 제공한다. 보이지 않는 비교 특징은 비교 불충분이며 오류와 구분한다. 파일 접근은 요청 범위로 제한하고 전송/인증 수치·Schema는 미정이다.

2026-09-13 [ADR-0012](adr/0012-validation-image-transfer-and-required-input.md) 추가 확정: 초기 검증은 정지 이미지만 지원하며 애니메이션·동영상·다중 프레임은 제외한다. 여러 정지 이미지의 묶음 검증은 유지한다. 후속 합의로 정지 PNG·WebP만 지원하고 JPEG는 제외한다. 접근·업로드 제한·임시 보관 정책은 별도 확정한다.

## 접근·업로드·임시 파일 — ADR-0013

[ADR-0013](adr/0013-validation-access-and-temporary-files.md)로 원칙을 확정했다. 로컬/분산 모두 서비스 인증을 사용해 설정된 Generation의 요청 이미지에만 접근한다. 대기/실행 중 접근을 유지하고 재검증에서 권한을 재확인한다. 용량·Decode 픽셀·요청당 개수를 각각 제한하고 초과 시 AI 호출 전 오류로 반환하며 임의 축소하지 않는다. Validation이 업로드 임시 파일을 관리하고 처리 중 보호·종료 후 일정 기간 보관·정리한다. 정리 후 재검증은 재업로드를 안내하고 이력과 Generation 원본은 보존한다. 인증 기술·한도·기간·동시성 세부는 미정이다.

## 검사·Profile — ADR-0014

[ADR-0014](adr/0014-validation-checks-and-profiles.md) 확정: 단일/묶음 Profile 분리, 기본 제공·사용자 복제/수정, 초기 상속 없음. Core가 관리하고 검증 요청 시 설정을 고정한다. 입력 유효성은 항상 검사하고 출력 조건·Positive/구체 Negative·묶음 일관성은 기본 On, 신체 이상·Metadata는 기본 Off다. 신체 이상은 부위별 On/Off와 보이는 구조만 검사한다. 입력→출력→AI 순서이며 입력 오류/출력 불합격 시 AI를 생략한다. 불합격을 종합 반영하고 오류/미완료를 합격으로 표시하지 않으며 Confidence만으로 판정하지 않는다. 사용자 세부 검사 기준·기본값 제어는 확장 검토하고 필수 검사 비활성화는 허용하지 않는다. 구체 설정 UI/범위·판정 구현·Schema는 미정이다.

## Provider 설정·Fallback — ADR-0015

[ADR-0015](adr/0015-validation-providers-and-fallback.md) 확정: Core가 복수 Local/외부 Provider 설정을 관리하고 Validation이 지원 기능 확인·실행·응답 정규화를 담당한다. 단일/묶음별 선택과 연결 확인을 제공하고 요청 시 설정을 고정한다. 미지원 입력/설정은 안내·오류로 처리하고 임의 축소·무시하지 않는다. 구조화 출력 미지원은 형식 요청 후 파싱/검사한다. 자동 Fallback·검증 재시도는 도입하지 않고 오류 후 사용자 Provider 변경 재검증을 지원한다. 실제 Provider/모델/검사 설정을 기록하고 외부에는 필요한 Context만 전달한다. 테스트 후 조정 사유·이전/새 기준·영향을 기록하며 구체 런타임·SDK·수치·Secret 계약은 미정이다.

## Validation 실행·GPU — ADR-0016

[ADR-0016](adr/0016-validation-execution-and-gpu-sharing.md) 확정: 단일/묶음 비동기 Job, Provider별 Queue·초기 동시성 1, 실행 가능 요청의 접수 순서, REST 조회/SSE 변경 알림을 제공한다. Validation은 실행 Queue, Core는 전체 흐름과 공유 GPU 권한을 관리한다. 대기/실행 Timeout을 구분하고 오류 자동 재전송은 하지 않는다. 대기 취소·실행 취소 중 표시·복구 시 실제 상태 확인·동일 접수 키의 기존 Job 반환을 적용한다. 묶음은 하나의 Job으로 추적하면서 비교 기준/대상을 유지해 분할한다. 같은 GPU의 Generation/Local Validation 추론은 겹치지 않도록 조정하고 실행 전 메모리 확보를 확인한다. 외부 Provider와 독립 GPU는 병렬 가능하다. ComfyUI 직접 실행은 상태 확인 후 대기하되 확인 직후 경쟁을 완전히 통제한다고 보장하지 않는다. 구체 저장/상태/권한 원자성/메모리/Timeout은 후속 설계한다.

## 재생성 변경값 — ADR-0017

[ADR-0017](adr/0017-regeneration-change-validation.md) 확정: 지원되는 생성/후처리 설정만 다음 시도에 변경하며 원본·Preset·경로·권한·상한은 변경하지 않는다. 불합격 근거별 최소 변경과 제작 의도 보존을 적용하고 검사 요소 삭제로 합격을 유도하지 않는다. 사용 가능한 모델과 호환 조합을 사용하며 자동 설치·범위 보정·제안 부분 적용은 하지 않는다. Validation은 분석/제안 형식, Core는 다음 입력/상한, Generation은 실제 환경의 최종 유효성 검사를 담당한다. 잘못된 제안은 오류·자동 생성 없음, 정보만 부족하면 가능한 판정과 제안 불가 이유를 제공한다. 자동 Off이면 사용자 선택을 기다리며 묶음 자동 재생성을 새로 허용하지 않는다. Schema·구체 검사/코드는 미정이다.

## Validation 원칙 정리와 상세 설계 위임

[ADR-0018](adr/0018-group-validation-change-handling.md)로 기준 동점·보조 최소 선정·참조/대상 변경·과거 결과 보존·불확실성과 접근 오류 분리·사용자 재확인을 확정했다. [ADR-0019](adr/0019-validation-contract-and-operational-draft.md)는 사용자 위임으로 작성한 API/상태/저장/인증·초기 운영값 초안이다. 일상적인 상세는 개별 승인 질문 없이 기존 요구 안에서 설계·테스트하며 제품 의도나 확정 경계 변경만 확인한다. 이 초안과 Backend 구현/테스트 완료를 혼동하지 않는다.

## 접수·취소·결과 경합 — ADR-0020

[ADR-0020](adr/0020-job-request-and-result-races.md) 확정: 동일 키/내용은 기존 Job, 다른 내용은 충돌. 응답 유실은 키 조회, 명시 재검증은 새 Job으로 연결한다. 설정 고정·기준 변경 재확인을 유지한다. 완료/취소는 서버 반영 순서로 처리하며 취소 후 늦은 결과는 진단 이력만 보존한다. 과거 기준 결과는 현재 판정을 덮지 않고 Core는 Job별 중복 결과 등록을 방지한다. 임시 이미지 정리 시 결과/기준/설정/오류 이력은 유지한다. 구체 원자성·API·저장 기술은 미정이다.

## 2026-09-13 Core 최소 생성 흐름 구현

[Core REST](../development/core-rest.md)의 SQLite 도메인·Prompt 스냅샷·Generation 접수/복구·이미지 메타데이터 저장과 실제 생성 통합을 검증했다. [보조 노드](../development/postprocess-live-validation.md)는 설치된 ComfyUI REST 직접 실행까지 확인했으며 Generation 보조 API와 Validation 연결은 후속 작업이다.

## Backend 초기 통합 확장

[후처리·단일 검증 통합](../development/backend-pipeline-integration.md)을 구현했다. 생성 완료와 검증 outcome을 분리하고 오류 후 자동 재생성을 실행하지 않는다. 실제 VLM 품질, 자동 재생성 적용 및 묶음 검증은 후속 범위다.

## Frontend 화면 구성 합의 — 2026-09-13

사용자는 제작 / 갤러리 / 작업 현황 / 설정의 상단 4개 메뉴, 제작의 분류 트리·편집·생성 설정 배치, 결과·작업·설정 간 이동 원칙을 승인했다. [전체 구성](../development/frontend-structure.md)에 보존했다. 이는 화면 구성 결정이며 Framework, 누락 API 구현 완료, Frontend 구현 착수를 뜻하지 않는다. Core 조정·REST canonical·Shared Client·별도 BFF 없음과 Backend→CLI→Frontend 개발 순서는 유지한다. 제작 상세와 메뉴별 API 공백은 일반 상세 초안으로 병행 정리한다.


## Frontend 파일럿 구현 — 2026-09-13

사용자의 파일럿 완성 지시에 따라 Core의 allowlist 정적 파일 제공과 same-origin 브라우저 REST Client를 구현했다. 네 메뉴를 연결하고 실제 생성·후처리·단일 검증을 브라우저에서 확인했다. 새 BFF 없이 Backend 책임을 유지하며 브라우저 token은 메모리에만 둔다. [파일럿 범위·제한](../development/frontend-pilot.md)을 따른다. 프레임워크·배포 정책의 새 ADR 일괄 승인을 의미하지 않는다.
