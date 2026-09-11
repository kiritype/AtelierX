# ADR-0003: Generation 실행 계약과 Core 작업 조정·Queue 동기화

- 상태: Accepted
- 작성일 / 확정일: 2026-09-11
- Supersedes: 없음. ADR-0002에서 미정으로 남긴 실행 순서·Preset 적용을 구체화한다.
- Superseded by: 없음
- 관련: [ADR-0002](0002-custom-node-functional-scope.md), [기능 대조표 G-01~G-10 및 교차 서비스 항목](../../requirements/module-feature-comparison.md)

## 결정할 질문

Node 제어를 REST로 제공하는 Generation Backend의 실행 범위, Core와 Validation의 작업 책임, Queue와 Client 동기화 방식을 정한다. 대화 중 문서 반영을 유예한 합의를 사용자의 반영 요청에 따라 기록한다. 제품 구현 승인은 아니다.

## 배경과 제약

Core / Generation / Validation은 서로 다른 PC에 배치할 수 있다. Core가 SQLite와 주요 상태를 소유하며 Generation은 DB와 Prompt AI Provider에 직접 접근하지 않는다. Frontend·CLI·Agent에 생성·검증의 업무 흐름을 중복 구현하지 않는다. 예상 Queue는 약 2,000~3,000건까지 고려한다.

## 결정

### 1. Node API와 Workflow — G-01~G-03

- Generation의 기본 역할은 ComfyUI Node 제어다. 각 Node 기능에 대응하는 REST API를 제공하고 파라미터는 해당 Node 입력을 기준으로 한다. 경로·Schema·전송 규격은 미정이다.
- 전체 생성용 Workflow는 Anima와 SDXL 두 개다. Anima가 기본이고 SDXL은 보조다. Workflow 수가 개별 Node 수를 강제하지 않는다.
- 전체 생성은 하나의 Workflow에서 이미지 생성 → Upscale → Detailing → Censor → 배경 투명화 → Encode 순서로 수행한다. 후처리는 선택적으로 적용하고 생략한 단계는 건너뛴다. PNG 보존과 선택적 별도 WebP 출력은 ADR-0002를 유지한다.
- Upscale 등 단독 API는 입력 이미지를 받아 해당 기능만 실행할 수 있어야 한다. 별도 단독 Workflow 또는 전체 Workflow의 일부 실행 모두 허용하며 내부 방식은 미정이다. 전체 생성용 두 개가 Repository 내 모든 Workflow 개수를 제한하지 않는다.
- Encode / Save 분리는 유지한다. Node별 REST API를 제공한다고 Client가 Workflow를 직접 구성해야 하는 것은 아니다.

### 2. Context와 서비스 책임 — G-04·G-08

- Core가 작업 Context를 준비·관리하고 Generation 실행 → Validation 검증 → 필요 시 새 Generation 시도의 흐름을 조정한다. Frontend는 요청·설정·상태 표시·결과 검토에 집중한다.
- Context에는 작업에 필요한 작품·캐릭터 정보, 관련 Prompt와 생성 입력, 모델·LoRA·생성 및 후처리 설정 등이 포함된다. API로 전달한다. 공유 파일이나 SQLite 직접 접근을 실행 전제로 두지 않는다. 정확한 필드·버전·식별자 체계는 미정이다.
- Preset Load는 Current Settings의 값을 변경한다. 실행에는 그 설정을 사용하고, 생성 시도가 시작되면 입력을 고정한다. Queue 대기 중 수정으로 기존 시도가 변하지 않도록 제출되는 시도 입력을 고정하는 원칙을 적용한다. 저장 트랜잭션과 API 접수의 정확한 경계는 후속 계약에서 정의한다.
- Generation은 확정된 입력으로 생성·후처리를 실행한다. 작품·캐릭터 이름을 임의로 추측하거나 원본 Prompt·Preset을 직접 조회·수정하지 않는다.
- Core의 전체 작업 조정과 Generation의 실행 상태·Queue 관리를 구분한다. 직접 Node API 호출에 관한 권한·전체 작업 연결 계약은 미정이며, 해당 API를 제거하거나 BFF를 추가하지 않는다.

### 3. 재생성의 역할 분리 — G-09

- 자동 재생성은 설정 가능하며 최대 횟수도 기본값을 두고 사용자가 변경할 수 있다. 수치 자체는 미정이다. 사용자는 AI 검증이 걸러내지 못한 결과를 수동으로 재생성할 수 있다.
- Validation이 재생성 필요 여부와 해당 이미지의 새 시도에 적용할 설정 변경값을 반환한다. Seed·Prompt뿐 아니라 CFG·Steps 등 최초 생성에서 허용한 모든 생성 설정을 변경할 수 있다. 기본 원칙은 최소 변경이다.
- Core가 횟수 제한과 작업 이력을 관리하고 기존 시도 입력에 변경값을 반영한 새 Context를 Generation에 전달한다. 재생성은 새로운 생성 시도이며 기존 결과·검증 기록과 연결한다.
- 변경값은 해당 이미지의 새 생성 시도에 적용한다. 원본 작품·캐릭터 Prompt나 저장된 Preset을 변경하지 않는다. Generation이 검증 결과를 분석해 변경값을 작성하지 않는다.
- Validation의 판정·변경값 작성 방식, 설정 검사 Schema, 기본 횟수·계수 범위·수동 요청과 상한의 관계는 별도 정의한다. 이미지 불합격과 실행 오류별 복구 정책을 이번 ADR에서 동일시하지 않는다.

### 4. 결과·진행·오류 — G-05~G-07·G-10

- 현재 실행 중인 Node를 확인할 수 있어야 한다. 진행 상태 API·이벤트 필드는 미정이다.
- 최종 출력 이미지를 Validation과 사용자가 검토하는 방향을 사용한다. 단계별 사용자 검토용 이미지 출력은 현재 요구로 채택하지 않는다. 진행 중 이미지 미리보기는 보류하며 Node 상태 표시는 제공한다. 내부 중간 결과 보존 여부는 별개로 미정이다.
- 결과 이미지 파일은 Generation 영역에 보관한다. 다른 Backend와 Client가 필요한 이미지·Metadata에 접근할 수 있어야 한다. 경로·다운로드·전송·Core Metadata 등록의 구체 계약은 미정이다. Generation PC의 로컬 경로를 원격 PC가 그대로 읽는다고 가정하지 않는다.
- Generation 오류에 원인을 구분하는 에러코드를 정의하고 작업·생성 시도·실패 단계와 연결된 로그를 남긴다. Validation과 사용자가 확인할 수 있도록 API로 오류 정보를 제공한다.
- 오류별 예외 처리·재실행·재생성·중단 정책은 Validation 설계에서 논의한다. 에러코드 목록·응답 Schema·로그 형식·보존 기간은 아직 정하지 않는다.
- LoRA 사용은 지원하고 학습은 제외한다. 향후 별도 LoRA Trainer 또는 외부 Trainer 연동을 검토할 수 있으나 현재 구현 범위는 아니다.

### 5. Queue·취소·재시작 복구

- 동일 GPU에서는 한 번에 하나의 Generation 작업을 실행한다. Queue는 접수 순서다. Frontend·CLI·Agent의 요청에 공통 적용한다.
- Generation과 Validation이 같은 GPU를 사용할 때의 VRAM·GPU 자원 조정은 후속 결정이다. 작은 Local VLM만으로 영향이 없다고 보장하지 않는다.
- 대기 작업 취소는 실행 대기열에서 제거한다. 실행 중 취소는 중단 요청 후 실제 종료를 확인한다. 전체 작업 취소는 Core가 후속 검증·자동 재생성을 중지한다.
- Frontend는 취소 동작을 즉시 표시하되 실제 중단 전 실행 작업을 완료된 취소로 표시하지 않는다. 대기 목록의 낙관적 제거에 실패하거나 응답이 불명확하면 서버 상태로 동기화한다. 작업 이력은 보존한다.
- 재시작 시 대기 작업을 복원한다. 실행 중이던 작업은 ComfyUI 상태를 확인해 추적하거나 실패 처리한다. 무조건 재제출하지 않는다.
- Queue 저장 기술·복구 기록·ComfyUI Queue와의 대응·취소 경쟁 처리·다중 요청의 접수 순서 확정 방식은 미정이다. 복구 요구가 Generation의 직접 SQLite 접근을 허용하지 않는다.
- 다중 Prompt 선택으로 많은 작업이 생길 수 있으나 Batch의 묶음·조합·부분 실패 계약 자체는 미정이다.

### 6. 대규모 Queue의 REST + SSE 동기화

- 최초 목록은 REST로 페이지 단위 조회한다. 매 변경마다 2,000~3,000건 전체 목록을 SSE로 보내지 않는다.
- SSE는 추가·상태 변경·제거된 작업의 ID와 필요한 정보 등 변경 알림을 전달한다. Frontend·CLI·Agent에서 발생한 변경을 반영한다.
- 대량 등록·취소는 변경 알림을 묶어 보내며 너무 큰 경우 관련 목록을 다시 조회하도록 알릴 수 있다. 임계값은 미정이다.
- 연결 복구는 이벤트 식별·순서를 기준으로 누락분을 복구하는 방향이다. 복구할 수 없으면 현재 표시 중인 목록을 REST로 재조회한다. 이벤트 보관 범위·번호·중복·순서 처리·최초 조회와 구독 사이 일관성 계약은 후속 설계한다.
- Frontend는 표시 중인 목록과 대기·실행 건수를 관리한다. 페이지 구성이 바뀌면 필요한 페이지를 재조회할 수 있다. 매 작업 완료마다 전체 Queue를 재조회하는 방식은 사용하지 않는다.
- 취소는 REST 요청으로 보내고 실제 상태는 API 응답과 SSE 변경 알림으로 동기화한다. 수동 새로고침은 보조 수단으로 제공한다. 주기적 전체 목록 전송이나 2초 Polling은 채택하지 않는다.
- Queue 조회·변경 알림은 Generation의 실행 상태를 제공한다. Core의 전체 작업 상태 이벤트까지 같은 계약으로 확정하지 않는다. SSE 연결·인증·heartbeat·갱신 지연 기준은 미정이다.

## 검토한 대안과 영향

| 대안 | 결론과 영향 |
| --- | --- |
| Client가 Context를 받아 Generation·Validation에 전달 | 전체 작업은 Core가 조정하도록 선택. Client 역할이 작아지고 Core에 작업 이력·흐름 관리 책임 추가 |
| 세 Backend의 SQLite 직접 접근 또는 공유 Context 파일 | 분산 배치를 유지하기 위해 실행 전제로 채택하지 않음. 필요한 Context를 API로 전달 |
| 단계마다 실행을 제출하는 전체 생성 | 전체 생성은 단일 Workflow 선택. 단독 기능은 별도·부분 실행 허용 |
| Queue 전체 SSE 전송·완료마다 전체 재조회·주기적 Polling | 예상 Queue 크기를 고려해 REST 페이지 조회 + SSE 변경 알림 선택. 이벤트 일관성·복구 계약이 필요 |
| Generation에서 오류별 자동 복구 판단 | 에러코드·로그·API 제공까지만 확정. Validation의 예외 정책은 후속 논의 |

## 이번에 결정하지 않는 사항

기술 Stack·API 경로와 Schema, Queue 저장 방식·ID·중복 방지, 파일 경로와 전송·Metadata, SSE 이벤트 보관·순서·페이지 방식, 재생성 기본값·Validation 오류 정책, GPU 공유, Preset 저장 단위와 Prompt Compiler는 미정이다. 진행 중 미리보기는 보류다. [backlog](backlog.md)에 유지한다.

## 충돌 및 대체 확인

- ADR-0001의 개발 운영 결정과 충돌하지 않는다.
- ADR-0002의 Node 기능·설정 저장·Encode 분리는 유지한다. 미정이던 후처리 순서, 전체 생성용 Workflow 수, Preset Load 적용, 결과 보관 영역을 구체화한다. ADR-0002는 Accepted로 유지하고 후속 결정 링크를 추가한다. 이전 Accepted 결정을 폐기하는 supersede 관계는 없다.
- 초기 문서의 Core 조정 책임·SSE 선택 미정은 이번 합의로 확정한다. 초기에 AI 제안이었던 Core 조정은 사용자 선택으로 채택되었음을 대조표에 기록한다.
- SQLite 소유권, 서비스 분리·분산 배치, REST First·Shared SDK·BFF 없음은 유지한다. SSE는 상태 전달 수단이며 REST 업무 계약을 대체하지 않는다.

## 문서 반영

- [x] overview 및 ADR 목록·backlog 갱신
- [x] 요구사항·모듈·기능 대조표 갱신
- [x] ADR-0002의 후속 구체화 관계 기록
- [x] Validation 상세와 미정 구현을 확정 내용에서 분리
