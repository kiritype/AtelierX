# 모듈 책임과 상세 문서 안내

Core가 요청 시 선택한 검증 설정을 고정하고 생성 완료 후 검증을 접수하도록 구현했다. 공유 GPU·취소·Queue의 현재 범위는 [실행 기록](../development/core-orchestration-validation.md), 경로/필드는 [API 명세](../api/rest-api.md)를 따른다.

[ADR-0023](../architecture/adr/0023-negative-prompt-sources.md): Core가 전역·캐릭터 Negative 저장·합성·출처 고정을 담당한다. Generation은 합성 문구를 실행하고 Validation은 캐릭터 금지 요소만 검사한다.

이 문서는 논리적인 책임 경계를 기록한다. 실제 소스 디렉터리, 언어, 패키지 이름 및 통신 절차는 결정하지 않는다. 모듈별 상세 문서는 관련 ADR 확정 후 여기에 링크한다.

사용자 요청으로 [Custom Node 구조·첫 개발 단위 설계 메모](custom-nodes-design.md)를 Proposed로 작성했다. 주 에이전트가 구조를 정리하고 Terra 서브 에이전트가 구현·테스트를 담당하며, 이 메모의 미정 계약을 확정 요구로 간주하지 않는다.

현재 [모듈별 기능 대조표](../requirements/module-feature-comparison.md)로 원문 요구와 기존 문서의 누락·축약을 검토한다. Custom Node와 Generation Backend를 별도로 분류하며, 모델·파일 관리의 미정 책임을 임의로 배정하지 않는다. 이 대조표는 확정 명세가 아니다.

| 구성 요소 | 책임 | 경계 및 후속 결정 |
| --- | --- | --- |
| Core Backend | SQLite·주요 상태 소유, 도메인 관리, Prompt AI, 설정, Metadata, Import / Export, Context와 생성·검증·재생성 작업 조정 | AI / Agent의 직접 SQL 금지. DB 동시성·권한·Secret은 TODO |
| Generation Backend | Node별 REST, 전체·단독 Workflow 실행, 고정 입력 적용, FIFO Queue·Node 상태·REST 페이지 조회·SSE 변경 알림, 결과 파일 보관·오류 제공 | SQLite·AI Provider 직접 접근 금지. 오류별 복구 판단은 후속 Validation 설계. 파일 전달·Metadata 계약은 TODO |
| ComfyUI Custom Nodes | 생성 파라미터 입력·이미지 출력, Upscale·Detailer·Censor·배경 Alpha·선택적 WebP | [ADR-0002](../architecture/adr/0002-custom-node-functional-scope.md)의 N-01~N-10 확정. 생성 계열별 분리 및 후처리 개별·통합 구성 허용. 저장 형식·Node 구조 미정 |
| Validation Backend | Deterministic 및 AI / VLM 검사, 재생성 여부·시도별 설정 변경값 반환 | 특정 모델 종속 금지. Provider abstraction은 Proposed, Schema·Profile·실행 제어는 TODO |
| Frontend | UI, 편집·조회·승인 화면, Job 표시, API 호출, 로컬 UI State | Backend 핵심 규칙을 포함하지 않음. Framework는 TODO |
| CLI | 인자 해석과 Shared API Client 호출 | Backend 비즈니스 로직 중복 금지. 명령어·출력 계약은 미정 |
| Shared API Client / SDK | Frontend·CLI·도구의 REST 호출 지원 | REST API가 canonical contract. 언어·생성 방식은 TODO |
| Shared Schemas / Types | 공용 API 데이터 계약과 타입 공유 영역 | 실제 Schema, 기술 및 동기화 방식은 TODO |
| Documentation | 확정 요구사항, 현재 구조 및 ADR 이력 관리 | 대화에만 결정을 남기지 않음 |

## Frontend에서 수행하지 않는 핵심 처리

[ADR-0022](../architecture/adr/0022-prompt-composition.md): Core가 전역·의상·선택 표현 Prompt 조합과 확인 가능한 충돌 안내, 최종 Positive/Negative 제공·시도별 고정을 담당한다. Frontend·CLI는 동일한 Core 결과를 표시·제출한다. 일반 조합의 AI 재작성 금지와 ADR-0017의 시도별 재생성 변경 제안은 구분한다.

ADR-0021 추가 확정: Core는 전역 Positive(퀄리티)·Negative 및 의상 내부의 외형 / 상의 / 하의(풋웨어 포함) Prompt를 관리한다. Frontend·CLI는 Core API로 편집하며 구체 API와 조합 규칙은 후속 설계한다.

현재 확정 category 계층은 **작품 > 캐릭터 > 의상(외형 포함)** 이다. Core는 의상 항목 내부의 외형·복장 Prompt를 관리하고 Frontend는 이 계층으로 편집·탐색한다. 기존 별도 외형 선택 표현은 ADR-0021의 2026-09-13 추가 정정으로 대체한다.

2026-09-13 정정: Core가 저장하고 Frontend가 표시하는 작품 / 캐릭터 / 의상은 Prompt category다. 분류 구조와 생성 문구 조합은 구분하며 작품을 생성 Prompt에 삽입하지 않는다. ADR-0021의 관계·재사용을 category로 표현하는 방식은 재검토 중이다.

[ADR-0021](../architecture/adr/0021-core-domain-and-image-groups.md)에 따라 Core는 작품·캐릭터 연결, 캐릭터별 외형, 공유 의상·내부 구성 요소, 사용처 조회, 보관·참조 삭제 제한, 그룹의 외형·의상 구성 고정을 관리한다. Frontend·CLI는 Core API로 편집·조회하며 공유 원본 변경을 과거 기록이나 기존 그룹에 소급 적용하지 않는다. 수정 구성으로 생성할 때는 새 그룹을 사용하고 검증용 대표·보조 교체 절차는 유지한다.

Encode / Save는 생성·Upscale과 별도 기능·Node로 분리하고 Frontend는 WebP On / Off와 품질 설정을 제공한다. 기본 생성 해상도는 1024×1024이다. Upscale 설정은 모델과 최종 배율로 제한하며 기본값은 UltraSharp 4x 등 4배 모델과 최종 1.5배(1536×1536)다. 모델 고유 배율과 최종 배율을 구분하고 사용자 명시 해상도·모델·최종 배율은 기본값보다 우선한다. Generation의 현재 목표에는 캐릭터 일관성 확보가 포함되며 구체 기법은 미정이다. Inpaint·ControlNet과 추가 보정은 [후속 로드맵](../requirements/roadmap.md)을 따른다. 공통 Adapter / Capability 구조는 별도 생성 Node의 필수 전제가 아니다.

- SQLite 직접 접근.
- Prompt 조합 핵심 규칙.
- ComfyUI Workflow 생성.
- AI Provider 직접 호출.
- Validation 판정.
- 파일 저장 경로 핵심 규칙.
- Import / Export 핵심 처리.

이 규칙들은 Backend 책임의 중복을 방지한다. 아직 정하지 않은 Backend 내부 구현이나 서비스 간 조정 책임까지 확정하지 않는다.

## 재생성 설정 — ADR-0003 추가 결정

2026-09-13 확정: Core는 다른 설정과 동일하게 자동 재생성 On / Off·최대 횟수 설정을 관리하며 상한 기본값은 5회다. 사용자 수동 재생성은 횟수 제한이 없다. 최초 생성·수동 재생성은 자동 재생성 횟수에 포함하지 않으며 Client는 Core 설정 API와 요청을 통해 처리한다. Core는 수동 재생성 요청마다 해당 흐름의 자동 사용 횟수를 0으로 초기화하고 설정 상한을 새로 부여하며 기존 이력을 보존한다. 자동 재생성 Off와 오류 후 자동 실행 금지는 유지한다. Core는 실제 자동 생성 실행 시작에 1회를 차감한다. 대기 취소는 제외하고 실행 후 실패·취소는 포함한다. Validation 오류 시 횟수를 유지하고 자동 흐름을 종료하며, 상한 도달 시 마지막 이미지·검증 결과를 보존한다. 상한은 0 이상 정수이고 0이면 자동 재생성하지 않는다. 변경 설정은 새 생성·수동 재생성 요청부터 적용하고 진행 중인 흐름은 기존 설정을 유지한다. 실행 이벤트·중복 방지·복구의 상세 계약은 미정이다.

## 묶음 검증 — ADR-0007

[ADR-0007](../architecture/adr/0007-group-image-validation.md)에 단일 검증 통과 이미지의 그룹 일관성 검사·중복 검사 제외를 확정했다. Core가 그룹 상태·요청·기준 연결·이력을 관리하고 Validation이 선택 대상과 기준을 비교한다. 시스템 기준 선정 후 사용자 수정이 가능하다. 기준 교체 시 새 기준의 그룹 재검증 여부를 확인하고, 재검증 결과에 따라 선택 재생성을 별도로 확인한다. 선택 재검증은 대상 판정만 갱신하며 기존 이력을 보존한다. 자동 선정·Schema·동시성 상세 계약은 미정이다.

## 아직 정하지 않은 교차 모듈 흐름

Validation·Core·Client의 응답 처리는 [ADR-0005](../architecture/adr/0005-validation-response-contract.md)에 Proposed 설계로 작성했다. 응답 구조·코드·HTTP 매핑은 승인 전이며 아래 Accepted 책임 경계를 유지한다.

생성 Node 및 후처리 Node / Workflow의 설정 Preset Load / Save는 [ADR-0002](../architecture/adr/0002-custom-node-functional-scope.md)에서 확정했다. 생성은 Anima / SDXL 전환 시 설정 혼합을 방지해야 한다. 이 요구를 구현할 Node·Core·Generation 간 저장·불러오기 계약과 Preset 단위는 미정이며, Generation의 직접 SQLite 접근을 허용하지 않는다.

[ADR-0003](../architecture/adr/0003-generation-execution-and-queue.md)에 따라 Core가 Context와 전체 작업 흐름·재생성 상한을 관리한다. Generation은 실행·Queue와 결과 파일 보관, Validation은 검증·재생성 여부·변경값 반환을 담당한다. 상세 API, Queue 기록 저장, 파일 전달·Core Metadata 등록 및 ADR-0004 이외의 오류별 복구 정책은 미정이다.

[ADR-0004](../architecture/adr/0004-validation-outcomes-and-errors.md)에 따라 Core는 자세·구도에 맞춰 Prompt를 구성하고 Validation은 이미지와 해당 생성 시도의 Prompt로 검증한다. 명시 요소가 보이지 않거나 상이하면 불합격이다. Provider 오류·응답 파싱 실패는 에러코드로 반환하고 자동 이미지 재생성으로 연결하지 않는다. CLI·Frontend는 오류 안내와 해당 이미지의 사용자 수동 재생성 요청을 지원하며 Core가 새 시도를 조정한다. 에러코드·응답 Schema·동일 이미지 검증 재시도 정책은 미정이다.

위 동일 이미지 검증 재시도 미정 범위는 후속 [ADR-0006](../architecture/adr/0006-validation-manual-retry.md)으로 구체화했다. 완료 응답 `outcome=error` 이후 자동 검증 재시도는 도입하지 않으며, 사용자는 기존 이미지·생성 Prompt로 다시 검증하거나 수동 재생성을 선택한다. Core가 요청·이력을 관리하고 재검증은 이미지 재생성 횟수에서 제외한다. 전체 응답 Schema·에러코드는 여전히 초안이다.

[기능 요구사항](../requirements/scope.md) · [아키텍처 개요](../architecture/overview.md) · [ADR backlog](../architecture/adr/backlog.md)

## 묶음 기준 선정·비교 부족 — ADR-0008

[ADR-0008](../architecture/adr/0008-group-reference-selection.md)에서 단일 검증 통과 후보 중 특징이 잘 보이는 대표 1장과 필요한 보조 이미지의 시스템 선정·사용자 수정을 확정했다. 후보 없음은 대기, 그룹 1장은 묶음 검사 미실행, 일부 특징 비교 불가는 명시하고 전체 합격으로 표시하지 않는다. 대표·보조 충돌은 사용자 확인을 요청한다. 새 이미지는 기존 기준으로 개별 검사하며 기준 삭제는 새 선정·사용자 확인·기준 교체 절차를 따른다. 현재 확정 기준이며 향후 변경 날짜·사유·이전/새 기준·기존 판정 영향을 ADR에 기록한다. 점수·구체 알고리즘·묶음 응답 Schema는 미정이다.

## 묶음 결과·그룹 요약 — ADR-0009

[ADR-0009](../architecture/adr/0009-group-validation-results.md) 확정: 이미지별 일치/불일치/비교 불충분/실행 오류와 근거, 실제 대표·보조 및 당시 기준, 검증 범위·현재 유효성을 기록한다. 그룹은 전체 일치/불일치 있음/판정 미완료로 집계하며 불충분·오류·미검증 수를 함께 표시한다. 부분 재검증을 전체 완료처럼 표시하지 않고 정상 결과와 이력을 보존한다. 사용자 선택 재검증·불일치 대상 재생성 확인을 지원하며 확인 중 기준 변경은 변경 안내 후 재확인한다. 필드명·enum·HTTP·Schema·집계 대상 ID 및 동시성 상세는 미정이다.

## 그룹 완료·부분 실패 — ADR-0010

[ADR-0010](../architecture/adr/0010-group-completion-and-partial-failure.md) 확정: Core는 생성 요청의 대상 목록을 고정하고 모든 대상의 생성·단일 검증·허용 자동 재생성이 완료 또는 실패/취소/상한으로 종료되면 최종 단일 통과 이미지로 묶음 검증을 요청한다. 통과 2장 이상이면 일부 실패에도 진행하며 실패·오류·불합격 종료·취소의 제외 사유를 표시한다. 전체 취소는 후속 묶음 검증을 막고 개별 취소는 나머지 처리를 유지한다. 사용자 수동 요청을 기다리며 기존 처리를 무기한 대기시키지 않는다. 통과 0장은 묶음 대기, 1장은 미실행으로 표시한다. 나중에 추가된 결과는 기존 기준으로 검사한다. 생성 성공/실패 현황과 실제 비교 범위의 일관성 요약을 분리하며 완료 결과·이력을 보존한다. 구체 상태·접수·동시성은 미정이다.

## 검증 입력 정보 — ADR-0011

[ADR-0011](../architecture/adr/0011-validation-input-context.md) 확정: 공통 입력은 추적·검사 설정·이미지 식별/접근 정보, 단일 입력은 실제 Positive/Negative Prompt·생성/후처리 설정·기대 최종 출력 조건, 묶음 입력은 그룹·이번 대상 목록·대표/보조와 기준 식별·이미지별 Prompt·유지할 외형/의상 정보로 구분한다. 단일 검증은 후처리까지 끝난 최종 이미지를 최종 출력 조건과 비교한다. Core가 필요한 Context를 준비하며 Validation은 DB에서 추가 조합하지 않는다. Validation API의 내부 식별/추적 정보와 AI 입력을 구분하고 외부 AI에는 검사에 필요한 최소 Context만 전달한다. 필수/선택·정보 부족·전송 방식·Schema는 미정이다.

## 이미지 전달·입력 부족 — ADR-0012

[ADR-0012](../architecture/adr/0012-validation-image-transfer-and-required-input.md) 확정: 로컬/분산 모두 Generation 이미지 조회 API를 Validation이 사용하고 직접 요청은 미등록 이미지 업로드를 허용한다. 이미지 식별·무결성을 연결하고 접근 실패/파일 변경은 오류로 처리한다. 단일 입력은 이미지·실제 Positive Prompt·검사 설정 필수, Negative Prompt 미사용은 빈 값 명시. 묶음은 그룹·대상·대표/기준 식별·대상별 Prompt·공통 외형/의상 필수, 보조는 선택하되 비교에 필요하면 제공한다. 필수 누락은 AI 호출 전 오류, 재생성 설정만 부족하면 판정은 반환하되 자동 제안 없이 사유를 제공한다. 보이지 않는 비교 특징은 비교 불충분이며 오류와 구분한다. 파일 접근은 요청 범위로 제한하고 전송/인증 수치·Schema는 미정이다.

2026-09-13 [ADR-0012](../architecture/adr/0012-validation-image-transfer-and-required-input.md) 추가 확정: 초기 검증은 정지 이미지만 지원하며 애니메이션·동영상·다중 프레임은 제외한다. 여러 정지 이미지의 묶음 검증은 유지한다. 후속 합의로 정지 PNG·WebP만 지원하고 JPEG는 제외한다. 접근·업로드 제한·임시 보관 정책은 별도 확정한다.

## 접근·업로드·임시 파일 — ADR-0013

[ADR-0013](../architecture/adr/0013-validation-access-and-temporary-files.md)로 원칙을 확정했다. 로컬/분산 모두 서비스 인증을 사용해 설정된 Generation의 요청 이미지에만 접근한다. 대기/실행 중 접근을 유지하고 재검증에서 권한을 재확인한다. 용량·Decode 픽셀·요청당 개수를 각각 제한하고 초과 시 AI 호출 전 오류로 반환하며 임의 축소하지 않는다. Validation이 업로드 임시 파일을 관리하고 처리 중 보호·종료 후 일정 기간 보관·정리한다. 정리 후 재검증은 재업로드를 안내하고 이력과 Generation 원본은 보존한다. 인증 기술·한도·기간·동시성 세부는 미정이다.

## 검사·Profile — ADR-0014

[ADR-0014](../architecture/adr/0014-validation-checks-and-profiles.md) 확정: 단일/묶음 Profile 분리, 기본 제공·사용자 복제/수정, 초기 상속 없음. Core가 관리하고 검증 요청 시 설정을 고정한다. 입력 유효성은 항상 검사하고 출력 조건·Positive/구체 Negative·묶음 일관성은 기본 On, 신체 이상·Metadata는 기본 Off다. 신체 이상은 부위별 On/Off와 보이는 구조만 검사한다. 입력→출력→AI 순서이며 입력 오류/출력 불합격 시 AI를 생략한다. 불합격을 종합 반영하고 오류/미완료를 합격으로 표시하지 않으며 Confidence만으로 판정하지 않는다. 사용자 세부 검사 기준·기본값 제어는 확장 검토하고 필수 검사 비활성화는 허용하지 않는다. 구체 설정 UI/범위·판정 구현·Schema는 미정이다.

## Provider 설정·Fallback — ADR-0015

[ADR-0015](../architecture/adr/0015-validation-providers-and-fallback.md) 확정: Core가 복수 Local/외부 Provider 설정을 관리하고 Validation이 지원 기능 확인·실행·응답 정규화를 담당한다. 단일/묶음별 선택과 연결 확인을 제공하고 요청 시 설정을 고정한다. 미지원 입력/설정은 안내·오류로 처리하고 임의 축소·무시하지 않는다. 구조화 출력 미지원은 형식 요청 후 파싱/검사한다. 자동 Fallback·검증 재시도는 도입하지 않고 오류 후 사용자 Provider 변경 재검증을 지원한다. 실제 Provider/모델/검사 설정을 기록하고 외부에는 필요한 Context만 전달한다. 테스트 후 조정 사유·이전/새 기준·영향을 기록하며 구체 런타임·SDK·수치·Secret 계약은 미정이다.

## Validation 실행·GPU — ADR-0016

[ADR-0016](../architecture/adr/0016-validation-execution-and-gpu-sharing.md) 확정: 단일/묶음 비동기 Job, Provider별 Queue·초기 동시성 1, 실행 가능 요청의 접수 순서, REST 조회/SSE 변경 알림을 제공한다. Validation은 실행 Queue, Core는 전체 흐름과 공유 GPU 권한을 관리한다. 대기/실행 Timeout을 구분하고 오류 자동 재전송은 하지 않는다. 대기 취소·실행 취소 중 표시·복구 시 실제 상태 확인·동일 접수 키의 기존 Job 반환을 적용한다. 묶음은 하나의 Job으로 추적하면서 비교 기준/대상을 유지해 분할한다. 같은 GPU의 Generation/Local Validation 추론은 겹치지 않도록 조정하고 실행 전 메모리 확보를 확인한다. 외부 Provider와 독립 GPU는 병렬 가능하다. ComfyUI 직접 실행은 상태 확인 후 대기하되 확인 직후 경쟁을 완전히 통제한다고 보장하지 않는다. 구체 저장/상태/권한 원자성/메모리/Timeout은 후속 설계한다.

## 재생성 변경값 — ADR-0017

[ADR-0017](../architecture/adr/0017-regeneration-change-validation.md) 확정: 지원되는 생성/후처리 설정만 다음 시도에 변경하며 원본·Preset·경로·권한·상한은 변경하지 않는다. 불합격 근거별 최소 변경과 제작 의도 보존을 적용하고 검사 요소 삭제로 합격을 유도하지 않는다. 사용 가능한 모델과 호환 조합을 사용하며 자동 설치·범위 보정·제안 부분 적용은 하지 않는다. Validation은 분석/제안 형식, Core는 다음 입력/상한, Generation은 실제 환경의 최종 유효성 검사를 담당한다. 잘못된 제안은 오류·자동 생성 없음, 정보만 부족하면 가능한 판정과 제안 불가 이유를 제공한다. 자동 Off이면 사용자 선택을 기다리며 묶음 자동 재생성을 새로 허용하지 않는다. Schema·구체 검사/코드는 미정이다.

## Validation 원칙 정리와 상세 설계 위임

[ADR-0018](../architecture/adr/0018-group-validation-change-handling.md)로 기준 동점·보조 최소 선정·참조/대상 변경·과거 결과 보존·불확실성과 접근 오류 분리·사용자 재확인을 확정했다. [ADR-0019](../architecture/adr/0019-validation-contract-and-operational-draft.md)는 사용자 위임으로 작성한 API/상태/저장/인증·초기 운영값 초안이다. 일상적인 상세는 개별 승인 질문 없이 기존 요구 안에서 설계·테스트하며 제품 의도나 확정 경계 변경만 확인한다. 이 초안과 Backend 구현/테스트 완료를 혼동하지 않는다.

## 접수·취소·결과 경합 — ADR-0020

[ADR-0020](../architecture/adr/0020-job-request-and-result-races.md) 확정: 동일 키/내용은 기존 Job, 다른 내용은 충돌. 응답 유실은 키 조회, 명시 재검증은 새 Job으로 연결한다. 설정 고정·기준 변경 재확인을 유지한다. 완료/취소는 서버 반영 순서로 처리하며 취소 후 늦은 결과는 진단 이력만 보존한다. 과거 기준 결과는 현재 판정을 덮지 않고 Core는 Job별 중복 결과 등록을 방지한다. 임시 이미지 정리 시 결과/기준/설정/오류 이력은 유지한다. 구체 원자성·API·저장 기술은 미정이다.

## 구현 진척 — 2026-09-13

Core의 SQLite 도메인·Prompt 고정·Generation 접수/복구·이미지 저장 흐름은 [Core REST](../development/core-rest.md), 보조 노드의 ComfyUI 설치 및 실행 범위는 [실행 기록](../development/postprocess-live-validation.md)에 기록한다. Validation 연결과 Generation 보조 노드 API 확장은 남아 있다.

[Backend 후처리·단일 검증 통합](../development/backend-pipeline-integration.md): Core가 이미지별 검증 이력을 소유하고 Validation이 AI Provider 요청 및 오류를 정규화한다. 실제 VLM 연결과 전체 기능 완료 여부는 실행 기록의 남은 범위를 따른다.

## Frontend 구성 합의 — 2026-09-13

[전체 화면 구성](../development/frontend-structure.md)에 제작·갤러리·작업 현황·설정의 역할과 이동을 기록했다. [제작 화면 상세](../development/frontend-production-screen.md)는 원본 저장, 이번 생성 입력, 과거 결과를 분리한다. [메뉴별 API 대조](../development/frontend-menu-api-map.md)는 구현 API와 제안 조회 API를 구분하며 UI의 Backend 책임 복제를 허용하지 않는다.
