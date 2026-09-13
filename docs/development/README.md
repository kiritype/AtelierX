# 개발 문서 진입점

[대량 제작 flow 재검토](batch-production-flow-review.md): 개수 상한 없는 논리 제작 작업, 사용자 조각 체크 선택, 내부 분할 생성·묶음 검증 및 기존 32개 제약 해소 방향. 구현 전 검토.

[분류 트리·자유 Prompt 입력](frontend-ux-tree-prompts.md): 제작/갤러리 분류 탐색, 랜덤 Seed·Sampler/Scheduler 선택, 여러 줄 구도·표정·동작·상황 및 대량 조각 사전 검토.

[Frontend 배치·접근성·오류 복구](frontend-accessibility-recovery.md): 12개 반응형 배치 표본, 인증 실패 후 재연결, 키보드 상세 열기와 본문 timeout 회귀.

[병렬 Backend 구현·검증](parallel-backend-validation.md): Preset, 독립 후처리, 묶음 선택 재생성 연결 및 장애 회귀. 전체 93개 통과, 실제 전체 후처리 성공. 신규 그룹 후속 실환경 검증은 별도 한계 기록.

[Core 자동 연결·GPU·취소·Queue 검증](core-orchestration-validation.md): 생성 요청의 검증 선택 고정, 공유 GPU 권한, 취소 및 Queue REST/SSE. Backend 50개·실제 연속 생성/검증 4개 확인.

[Negative 출처 분리 검증](negative-sources-validation.md): 캐릭터 필드·Core snapshot·생성 합성·단일 검증 적용, Backend 42개 및 실제 VLM/후처리 통합 확인.

[현재 REST API 명세](../api/rest-api.md)와 [Negative 출처 분리 ADR](../architecture/adr/0023-negative-prompt-sources.md)을 참고한다.

[Backend 구현 체크리스트](backend-implementation-checklist.md): 확정 요구·코드·시험을 대조한 현재 완료/부분/미구현/미검증 범위와 권장 순서. 과거 시점별 개발 기록의 미구현 표현보다 이 현황표를 우선 참고한다.

[새 생성·전체 후처리·실제 VLM 통합](real-vlm-pipeline-2026-09-13.md): WebP Provider 호환성 수정 후 PNG/WebP 실제 검증과 Core 재시작 보존 확인. Backend 회귀 39개 통과.

[2026-09-13 전체 테스트 리포트](full-test-report-2026-09-13.md): 자동 검사 111개, 예제 검사 6개, 실제 생성·후처리 19건, Mock 검증 2건 및 LM Studio 14조건의 일괄 실행 결과와 미검증 범위.

## 현재 구현 착수 — 2026-09-13 후속 지시

[Generation REST 첫 구현·검증](generation-rest.md): Anima 등록 확인 후 기본·다중 LoRA 두 건을 순차 REST 실행해 PNG 결과·해시·중복/충돌 처리를 확인했다. 실행 방법·API·미구현 기능과 다음 Node 준비 조건을 기록한다.

사용자가 Frontend 제외 Backend 3개·Shared API Client·CLI 구현을 승인했다. 아래 과거 ADR 전용/구현 보류 기록보다 이 지시가 우선한다. Generation은 구현·등록·필수 자원을 확인한 Node부터 REST API로 하나씩 실행 검증한다. 첫 대상은 Anima이며 나머지 Node의 준비 상태와 미구현 범위를 분리해 기록한다. 일반적인 상세 계약은 기존 요구에 맞춰 구현하며 제품 방향 변경만 확인한다.

## 개발 순서 — 2026-09-13 사용자 확정

1. Backend 3개(Core / Generation / Validation)의 API·오류·작업 상태 계약 정리.
2. Core 요청 → Generation 생성 → Validation 단일 검증 → Core 결과 저장의 최소 통합 흐름 구현.
3. Backend 재생성·Queue·취소·복구·묶음 검증·설정 기능 확장.
4. Shared API Client를 사용하는 제품 CLI 개발 및 사용자 작업 흐름 확인.
5. 검증된 API 기반 Frontend 개발.

Backend는 서비스 하나씩 완성한 후 연결하는 방식 대신 최소 통합 흐름부터 확장한다. 개발 중 API 시험 도구와 제품 CLI를 구분한다. ComfyUI Custom Node는 Generation에 필요한 순서로 병행한다. 현재 작업은 ADR 검토이며 이 개발 순서 확정이 Backend·CLI·Frontend 구현 개시 지시는 아니다.

## Custom Node 전달 방식 — 2026-09-13 사용자 요청

앞으로 Custom Node는 개발·테스트를 마친 뒤 설치된 ComfyUI에 연결하고, 사용자가 직접 열어 실행할 수 있는 예제 Workflow까지 준비한다. 설치된 환경의 Node 등록·Workflow 실행을 확인하고 Node 이름·Workflow 위치·접속 또는 실행 방법을 안내한다. 기존 모델·사용자 Workflow와 실행 중인 작업을 보존한다. 상세 운영 기준은 [AGENTS.md](../../AGENTS.md)의 Custom Node 개발 완료 기준을 따른다.

## 현재 진행 방침 — 2026-09-12 사용자 보완

사용자가 이전 환경에서 **Validation Backend 설계와 ComfyUI용 Custom Node 개발을 병행하기로 했다**고 설명했다. 이전 저장소 문서에는 이 병행 방침이 없고 구현을 시작하지 않는다는 기록만 남아 있었으므로, 현재 대화에서 전달된 방침을 여기 기록한다. 과거 대화 원문을 확인한 것으로 취급하지 않는다.

Validation Backend는 설계를 계속하고, ComfyUI Custom Node는 ADR-0002의 확정 기능을 바탕으로 개발을 병행하는 방향이다. 기존 문서의 일괄 구현 보류 표현에는 이 사용자 보완이 적용된다. 다른 제품 구성 요소의 구현·전체 Stack·CI 도입까지 승인한 것은 아니다. Node 상세 구조 등 미결정 설계는 계속 별도로 정리한다.

사용자가 설치된 Anima 모델을 기반으로 이미지 생성 Node를 먼저 구현·테스트하도록 지시했다. 주 에이전트의 범위 정리에 따라 Terra가 첫 Node와 테스트를 작성했고, 단위 테스트 9개 및 WAI 모델 실제 생성 검증을 통과했다. ADR-0005의 Validation 응답 계약은 사용자 요청에 따라 Proposed 초안으로 유지한다.

후속 준비: ComfyUI 경로·버전·Python/PyTorch·CUDA를 확인하고 [Custom Node 구조·첫 개발 단위](../modules/custom-nodes-design.md)를 갱신했다. 사용자 지정에 따라 주 에이전트가 구조 설계·검토를, Terra 서브 에이전트가 개발·테스트 작성을 담당한다. Encode / Save 우선 제안은 채택되지 않았으며 첫 검증 대상은 Anima 생성이다.

[Anima 실제 생성·설치 검증](anima-generation-validation.md): WAI-ANIMA로 768×1024 이미지 생성에 성공했다. 2026-09-13 설치된 ComfyUI에 Node를 연결하고 예제 Workflow를 화면에서 실행해 PreviewImage 출력까지 확인했다. 단위 테스트는 총 11개 통과했으며 설치 위치·사용 방법·검증 한계를 기록했다.

[Anima 동적 LoRA 목록 검증](anima-lora-validation.md): 사용자가 추가·삭제할 수 있는 LoRA 목록 UI와 순서·가중치 API 전달을 구현했다. 설치된 두 Anima LoRA의 실제 API 생성 결과와 화면 검증 범위를 기록한다.

현재 적용되는 문서 작업 규칙은 [AGENTS.md](../../AGENTS.md)와 [ADR 절차](../architecture/adr/README.md)를 따른다.

현재 환경과 작업 재개 지점은 [2026-09-12 인계·문서 검토 기록](handoff-2026-09-12.md)을 참고한다. Stability Matrix 설치 및 RTX 4090 사용 가능 정보와 후속 검증 후보를 기록하며, 실제 실행 검증 결과와 구분한다.

현재 [ADR-0001: Contribution 워크플로](../architecture/adr/0001-contribution-workflow.md)를 Proposed 상태로 논의 중이다. **develop 분리, main 릴리즈 및 주요 분기·병합 흐름은 확정**했다. 일반 작업 → develop / hotfix → main은 Squash merge, develop ↔ main은 Merge commit이다. Commit / PR 메시지는 영문 type·scope와 한국어 요약·본문의 `type(scope): 요약` 형식으로 확정했다. 리뷰·보호 및 작업 브랜치 관리 세부는 아직 미확정이다. 확정된 부분의 운영 기준은 CONTRIBUTING.md에 정리했다.

## 후속 ADR 대상

GitHub 기본 브랜치 develop 및 최초 main 커밋과 동일 커밋의 develop 생성은 확정했다. 확정 운영 기준은 [CONTRIBUTING.md](../../CONTRIBUTING.md)에 정리했다. 나머지 제안은 ADR에서 별도 관리한다.

현재 1인 개발을 전제로 한다. 리뷰 기준과 브랜치 보호는 **최초 릴리즈 완료 후 도입을 검토**하며 지금 적용하지 않는다. 해당 시점에도 1인 개발이면 타인 승인 요구 없이 운영 가능한 구성을 검토한다. 이미 확정된 브랜치·병합 흐름과 ADR 문서화 규칙은 유지한다.

- Backend Stack 및 Frontend Framework.
- Branch / Commit 정책.
- CI / Test 정책.
- Release / Versioning.
- Packaging / Installer.
- Migration / Backup.
- Logging / Audit.

단일 GitHub Monorepo, AtelierX 전체 버전 기준 릴리즈, 각 서비스 및 CLI의 독립 패키징 가능성은 확정된 제약이다. 버전 체계, 도구 및 실행 절차는 미정이다.

각 정책이 확정되면 이 디렉터리에 해당 안내를 작성하고 ADR을 연결한다. 아직 확정되지 않은 설정이나 명령어를 사용 가능한 절차처럼 제공하지 않는다.

## Validation 계약 검증

[2026-09-13 계약 검증](validation-contract-verification.md): 5종 Schema·10개 예제·18개 계약 검사 통과. 실제 Backend·장애 복구와 구분한다. [계약 문서](../contracts/validation/README.md)에서 재현 방법과 남은 구현 조건을 확인한다.

현재 사용자 지침: Validation은 ADR 검토·문서 작성만 진행한다. 앞서 작성한 계약 코드와 자동 검사 이력은 참고 자료이며 추가 확장/실행하지 않는다. 현재 검토 내용은 ADR-0019에서 관리한다.

## Core 및 보조 노드 구현 후속 기록

[Core REST 구현·검증](core-rest.md), [보조 노드 실제 설치·실행 및 사용자 Workflow](postprocess-live-validation.md)를 참고한다. 아래 과거 미설치·ADR 전용 기록보다 2026-09-13 사용자 구현 지시와 이 실행 기록이 우선한다.

## Backend 후처리·단일 검증 통합

[현재 구현과 API 설정](backend-pipeline-integration.md), [이미지 저장 경로](output-paths.md), [로컬 VLM 설치 권고](local-vlm-recommendation.md). 2026-09-13 후속 지시에 따라 구현·실행한 범위를 기록한다.

## LM Studio 실제 실행 후속 기록

사용자가 LM Studio를 선택했다. 로컬 모델 연결, json_schema 호환 수정 및 누락 요소 오판을 [실제 검증 기록](lmstudio-live-validation.md)에 남겼다. 이전 미연결 기록보다 이 실행 결과가 우선한다.

## 항목별 근거 검증 후속 변경

[평가 방식 v2와 실제 재평가](validation-element-evidence.md): Prompt 항목마다 관찰 근거를 반환하고 Validation이 최종 판정을 집계한다. 이전 화면 밖 부츠 오판은 동일 사례 재검증에서 불합격으로 처리됐다. 다른 이미지에서의 일반화는 아직 검증하지 않았다.

## 추가 이미지 평가

[다른 이미지·구도 평가](validation-generalization.md): 신규 평가 이미지 2장, 조건 9건 중 기대 일치 8건·오탐 1건. 복합 항목에서 작은 귀걸이를 놓치는 문제가 남았다.

## 가중치 묶음 분리 후속 변경

[평가 v3와 실제 회귀 결과](validation-weighted-groups.md): 원문·가중치를 보존하며 괄호 묶음을 개별 요구로 분리했다. 기존 귀걸이 오탐을 포함한 동일 9개 조건이 이번 실행에서 모두 기대와 일치했다.


## 2026-09-13 재생성 후속 구현

수동/자동 재생성, 시도 이력, 실행 시작 기준 횟수 및 중단 처리를 구현했다. 이전 미구현 표기는 이 후속 기록으로 갱신한다. 지원 변경 범위와 검증 결과는 [재생성 구현 보고서](regeneration-validation.md), 계약은 [REST 명세](../api/rest-api.md)를 참조한다. 묶음 검증 기반 흐름은 남아 있다.


## 2026-09-13 묶음 검증 후속

[묶음 검증 구현 및 실제 시험](group-validation.md): 명시적 기준/대상 지정, 선택 재검증, 여러 이미지 provider 호출과 부분 결과 보존을 구현했다. 후속 구현으로 기준 후보 제안 및 선택 재생성 결과의 활성 전환·묶음 재검증을 연결했다. 기준은 자동 확정하지 않는다.

[그룹 일괄 생성](group-batches.md)은 고정한 대상의 생성·단일 검증·자동 재생성 완료를 집계하고 묶음 검증에 연결한다. REST 명세는 [API 문서](../api/rest-api.md), 전체 잔여 범위는 [Backend 체크리스트](backend-implementation-checklist.md), Upscale·SDXL의 현재 자원 제한은 [준비 상태 조사](generation-next-readiness.md)를 참조한다.

[묶음 일관성 대조 검증](group-consistency-controls.md): 고정 6개 사례, v7 오판/오류, v8 근거 보완과 실제 timeout 및 미실행 범위를 기록했다.

[Frontend 기능요구사항 분석](frontend-requirements-analysis.md): 기존 요구·ADR과 실제 REST 지원을 화면별로 대조했다. 구현 전 분석이며, 전역 갤러리·그룹 탐색 API 등 남은 계약과 화면 우선순위를 구분한다.

[Frontend 전체 구성](frontend-structure.md): 사용자 합의한 제작·갤러리·작업 현황·설정의 4개 메뉴와 이동 원칙. [제작 화면 상세](frontend-production-screen.md), [메뉴별 API 대조](frontend-menu-api-map.md)는 상세 설계·후속 API 개발 단위다.


## 2026-09-13 Frontend 탐색 API 구현 반영

그룹·이미지 목록, 작업 관계/state 필터 및 전역 일괄 작업 목록을 구현했다. 앞선 group/image 목록 미구현 표기는 이 기록으로 갱신한다. 전체 155개 테스트와 복사 DB의 HTTP 조회·재시작·DB 무변경 검증을 통과했다. [구현·검증 보고서](core-browse-api.md)와 [REST 명세](../api/rest-api.md)를 따른다. Frontend 화면과 Shared Client 구현 완료를 뜻하지 않는다.


## 2026-09-13 Client·CLI 및 화면 상세 후속

[Shared Client·CLI 첫 구현](shared-client-cli.md)은 Core 조회 연결 범위와 사용법을 기록한다. [갤러리 상세 초안](frontend-gallery-screen.md)과 [작업 현황 상세 초안](frontend-jobs-screen.md)은 사용자 검토용 배치·상태·동작·수용 기준이다. 화면 코드는 아직 구현하지 않았다.


[설정 화면 상세 초안](frontend-settings-screen.md): 사용자 요청한 좌측 카테고리·우측 설정, 핵심 섹션과 고급 접기, 저장·revision 충돌·동기화 상태를 정리했다. 화면 구현 전 검토용이다.


## 2026-09-13 파일럿 구현 반영

사용자 후속 지시로 네 메뉴의 F/E 파일럿을 구현했다. 앞의 화면 코드 미구현 표기는 [현재 실행·검증 범위](frontend-pilot.md)로 갱신한다. 상세 초안 전체가 모두 구현·시험된 것은 아니며 JSON 입력과 후속 검증 범위를 보고서에 구분했다.


[파일럿 폼 개선·묶음 회귀](frontend-pilot-refinement.md): 일반 필드·선택 폼, 초안 revision 보호와 실제 PNG 두 장의 묶음 실행을 추가 검증했다. 앞의 JSON 전용/묶음 화면 미시험 표기는 이 보고서의 범위로 갱신한다.
