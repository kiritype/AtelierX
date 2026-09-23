# 모듈별 기능 대조표

2026-09-13 구현 현황은 [Backend 구현 체크리스트](../modules/core-generation.md)에서 별도로 관리한다. 아래 표의 문서 반영·사용자 검토 표시는 구현 완료 표시가 아니다.

상태: **사용자 검토용 초안**. 작성일: 2026-09-11.

목적은 원래 요구한 기능을 복원하고 기존 문서의 누락·축약을 확인하는 것이다. 이 표 작성은 신규 기능, 구현 방식, 모듈 배치 또는 MVP 범위를 승인하는 행위가 아니다. 제품 구현은 시작하지 않는다.

## 읽는 방법과 체크 기준

- **원문 요구**: 공유 대화에서 사용자가 직접 요청한 기능. 기능의 존재와 상세 설계 확정을 구분한다.
- **기준선**: 현재 대화에서 전달·합의한 요구사항 또는 원칙. 구체적인 기술·동작까지 확정됐다는 뜻은 아니다.
- **AI 제안**: 이전 대화 또는 이번 대화의 AI가 추가한 방향. 사용자 채택 여부를 다시 확인해야 한다.
- **미정**: 질문만 있으며 아직 선택된 해법이 없다.
- **반영**: 비교 기준 문서에 기능이 명시됨. 구현 완료나 상세 명세 완료를 뜻하지 않는다.
- **축약**: 상위 기능명만 있어 구체적인 요구가 드러나지 않음.
- **누락**: 비교 기준 문서에 해당 구체 기능이 없음.
- **TODO / Proposed**: 기존 문서에서도 미결정 또는 제안으로 관리 중.

`확인` 열의 `☐`는 사용자가 이 항목의 정리가 맞는지 검토하기 위한 표시다. 기능 구현 완료 표시가 아니다. 모든 행을 미검토 상태로 시작하며 기존 합의를 다시 승인하도록 요구하는 것은 아니다.

응답은 `N-06 유지`, `C-09 수정: ...`, `M-03 보류`, `X-01 채택하지 않음`처럼 ID로 전달할 수 있다. 검토 후 `확인` 열을 `유지 / 수정 / 보류 / 제외`로 갱신하고 이유를 기록한다. AI 제안을 채택하거나 기존 합의를 변경하는 경우 필요한 ADR을 별도로 확정한다.

모듈 이름은 검토를 위한 분류다. 특히 **모델 관리, 파일 관리, 교차 서비스 작업**은 담당 서비스가 미정인 기능 영역이며 새로운 Backend를 추가한다는 뜻이 아니다. 동일 기능이 Node·API·UI 행에 등장하면 서로 다른 계층의 요구를 나타낸다.

## 출처와 비교 기준

공유 대화: [원본 요구사항 및 설계 논의](https://chatgpt.com/share/6aa36c3b-0518-83ee-9e9b-fbb4f1c8a3f6).

| 출처 코드 | 위치와 성격 |
| --- | --- |
| U1 | 첫 사용자 메시지 「이런 걸 만들고 싶어」: Node 3종, Prompt·이미지·모델 관리, CLI·Agent, 검증 요구 |
| U2–U3 | 사용자 메시지: 검증도 Web에서 REST로 접근, 생성·검증 각각 API 제공, SQLite와 Import / Export |
| U4 | 사용자 메시지: Local VLM 연동 설정을 명확히 고려할 것 |
| U8–U9 | 사용자 메시지: BFF 필요성 재검토, Frontend·CLI 공용 API Client, 분산 배치 및 외부 Validation AI |
| U10–U11 | 사용자 메시지: Generation은 ComfyUI 연동, Prompt AI와 DB 권한, Core 추가 및 3개 Backend 합의 |
| A1 | U1에 대한 AI 답변: Adapter, Reference 기법, Compiler, Encode/Save 분리, 자동 재생성 등 제안 |
| A4 | U4에 대한 AI 답변: VLM 설정·Schema·GPU 정책 등 Proposed ADR 묶음 |
| A8–A11 | BFF·SDK·Provider·Core 분리 논의의 AI 답변. 사용자 합의와 대안을 구분 |
| B | 현재 대화 최초 AtelierX 정의. [overview](../architecture/overview.md), [scope](scope.md), [modules](../modules/README.md)에 기록된 기준선 |
| C | 현재 대화에서 추가 합의한 Git 운영·메시지·1인 개발·보호 유예. [ADR-0001](../architecture/adr/0001-contribution-workflow.md) |
| A현재 | 최초 대조 시 Core 중앙 접수·Job 조정은 AI 제안이었다. 이후 사용자가 채택하여 ADR-0003으로 확정 |
| G검토 | Generation 기능·Context·Core 조정·Queue·SSE의 사용자 합의. [ADR-0003](../architecture/adr/0003-generation-execution-and-queue.md) |

**문서 반영 상태의 비교 시점은 최초 커밋 `ab7365c`**다. 아래 문서 약칭을 사용한다. 이 대조표를 추가했다고 기존 누락 상태를 곧바로 ‘반영’으로 바꾸지 않는다.

- R: [기능 요구사항 scope](scope.md)
- O: [아키텍처 overview](../architecture/overview.md)
- M: [모듈 책임](../modules/README.md)
- Bk: [ADR backlog](../architecture/adr/backlog.md)
- D: [Contribution ADR](../architecture/adr/0001-contribution-workflow.md) 및 [기여 안내](../../CONTRIBUTING.md)

## 1. ComfyUI Custom Nodes

**원래 제작 대상으로 요청된 실행 구성 요소**다. Generation REST 서비스와 동일한 프로세스·역할이라고 가정하지 않는다. N-01~N-10은 [ADR-0002](../architecture/adr/0002-custom-node-functional-scope.md)로 기능 요구를 확정했다. N-01~N-05는 생성, N-06~N-10은 후처리이며 실제 Node 수와 내부 분해 방식은 미정이다. 아래 기존 문서 대조 열은 최초 커밋 기준을 유지한다.

| ID | 기능·요구 내용 | 근거 / 상태 | 기존 문서 대조 | 남은 정의·책임 확인 | 확인 |
| --- | --- | --- | --- | --- | --- |
| N-01 | 생성·후처리 Custom Node 세트. 생성 계열별 분리와 후처리 개별·통합 구성 허용 | 사용자 검토 확정 | Bk: TODO만 있음; R/M: 제작 대상 축약·누락 | 정확한 Node 수, 이름, 패키징, 재사용 범위 | 유지 |
| N-02 | 모델·다중 LoRA와 가중치·Positive/Negative Prompt·Resolution·CFG·Steps·Sampler·Scheduler·Seed 등 입력 → 이미지 출력. 설정 저장 | 사용자 검토 확정 | R: 설정 목록 반영, 단일 Node UX 누락 | 저장 형식·단위·복원 API. SQLite 허용, Core 소유권 유지 | 유지 |
| N-03 | Anima·SDXL Illustrious 지원. Scheduler·Text Encoder 차이 처리, 생성 Node 분리 허용 | 사용자 검토 확정 | R: 반영 | 구체 버전별 호환성·검증 및 Text Encoder 선택 방식 | 유지 |
| N-04 | ComfyUI / Stability Matrix 설치 기본 모델·LoRA 폴더 기반 목록과 사용자 경로. 다중 LoRA·개별 Weight | 사용자 검토 확정 | R: 다중 LoRA·Weight 반영; 설치 목록 선택 축약 | 탐색 주체·우선순위·호환성 오류 처리 | 유지 |
| N-05 | Checkpoint·VAE·CFG·Steps·Seed·Sampler·Scheduler. 기본 모델 제공값으로 초기화, 설정 저장 | 사용자 검토 확정 | R: 반영 | 기본값 출처·취득·누락 처리 및 값 범위 | 유지 |
| N-06 | 이전 생성 이미지를 Generation Backend가 입력하여 Upscale. 모델·배율 선택, 기본 폴더와 사용자 경로 지원 | 사용자 검토 확정 | R: Upscale로 축약 | 이미지 전달·배율·최종 크기 규칙 | 유지 |
| N-07 | 생성 완료 후 PNG와 별도로 WebP 생성. On / Off 가능 | 사용자 검토 확정 | R: 누락 | Encode 마지막 순서는 ADR-0003 확정. 파일 관계·Metadata 보존 미정 | 유지 |
| N-08 | 눈·입·손·얼굴 Detailer. 검출·적용은 ComfyUI-AssetManager 참고 가능 | 사용자 검토 확정 | R: 후처리로 축약 | 검출 모델·개별 옵션·순서. 참고 코드 옵션 채택은 미정 | 유지 |
| N-09 | NSFW Censor. 검출·적용은 N-08과 같은 저장소 참고 가능 | 사용자 검토 확정 | R: 후처리로 축약 | 검출 대상·모델·마스킹 방식·사용자 설정 | 유지 |
| N-10 | 캐릭터 검출 → 마스크 → 이외 영역 Alpha 변경. On / Off 가능 | 사용자 검토 확정 | R: 후처리로 축약 | 검출·분리 모델·경계 처리·Alpha 보존 | 유지 |
| N-11 | 통합 생성 Node 및 별도 Node의 공통 Adapter / Capability를 필수 전제로 두지 않음 | 사용자 검토: 필수 전제 해제 | O/Bk: Proposed | 구체 구조 미선택. 모델별 설정·Preset 검사는 유지 | 수정 |
| N-12 | Encode / Save 별도 기능·Node. Frontend WebP On / Off 및 품질 설정 | 사용자 검토 확정 | R: 누락; 파일 정책은 Bk TODO | Encode와 Save 자체의 Node 수·품질 범위·기본값·저장 계약 | 수정 |
| N-13 | Upscale 설정은 모델과 입력 대비 최종 배율만. 예: UltraSharp 4x + 1.5배 | 사용자 검토 확정 | R: 누락 | 내부 배율 조정·반올림 미정. 타일·Overlap·목표 크기·Lossless 옵션 제외, WebP 품질은 N-12로 이동 | 수정 |
| N-14 | Generation에서 캐릭터 일관성 최대 확보. Anima 자연어 Prompt·IP-Adapter·Img2Img 등 검토. Inpaint·ControlNet 후속 로드맵 | 사용자 검토: 목표 확정 / 기법 미정 | R: 누락 | 모델별 채택 기법·호환성·입력·일관성 평가 기준 | 수정 |
| N-15 | Crop·색감·Watermark는 현재 범위에서 유예하고 후속 로드맵으로 이관 | 사용자 검토: 로드맵 이관 | R: 누락 | 도입 시점·릴리즈·상세 옵션 미정 | 보류 |
| N-16 | 생성 Node 입력 설정의 Preset Load / Save. Anima / SDXL 전환 시 계열별 설정 혼합·부적합한 적용 방지 | 사용자 추가 요구 확정 | R: 생성 Preset으로 축약; 계열 전환 조건 누락 | 필드·계열 구분·호환성 처리·자동 Load·미저장 변경·저장 API | 유지 |
| N-17 | 후처리 Node 또는 Workflow 설정의 Preset Load / Save | 사용자 추가 요구 확정 | R: 후처리 Preset 명시 누락 | 개별 단계/전체 Workflow 지원 단위·필드·덮어쓰기·저장 API | 유지 |

N-16~N-17은 2026-09-11 추가 확정 요구로 [ADR-0002](../architecture/adr/0002-custom-node-functional-scope.md)에 반영했다. N-11~N-15도 후속 사용자 검토를 반영했으며 목표·채택 범위·미정 설계·[로드맵](roadmap.md)을 구분한다.

## 2. Generation Backend

**ComfyUI Node 제어와 생성·후처리를 REST로 제공하는 서비스**다. G-01~G-10 검토는 [ADR-0003](../architecture/adr/0003-generation-execution-and-queue.md)에 반영했다. 기존 문서 대조 열은 최초 커밋 기준이며 현재 확정 상태는 근거·확인 열을 따른다.

| ID | 기능·요구 내용 | 근거 / 상태 | 기존 문서 대조 | 남은 정의·책임 확인 | 확인 |
| --- | --- | --- | --- | --- | --- |
| G-01 | 각 Node 기능별 REST API, Node 입력 기준 파라미터 | 사용자 합의 / ADR-0003 | O/M: 반영 | API 경로·Schema·직접 실행과 Core 전체 작업의 연결 계약 | 수정 |
| G-02 | Anima 기본·SDXL 보조 전체 생성용 Workflow 두 개. 단독 기능은 별도 Workflow 또는 부분 실행 허용 | 사용자 합의 / ADR-0003 | R: 반영 | 단독 기능 내부 구성·ComfyUI 실행 계약 | 수정 |
| G-03 | 생성 → Upscale → Detailing → Censor → 배경 투명화 → Encode. 후처리 선택 적용 | 사용자 합의 / ADR-0003 | R: 개별 작업만 반영, 연속 실행은 축약 | 중간 결과 보존·내부 실행 세부 | 수정 |
| G-04 | Preset Load가 Current Settings 변경. 생성 시도 입력 고정 및 전달된 모델·LoRA·설정 적용 | 사용자 합의 / ADR-0003 | R: 반영 | Preset 저장 계약·접수/고정 경계·Schema | 수정 |
| G-05 | 현재 실행 Node·작업 상태 제공. Queue REST 페이지 조회 + SSE 변경 알림 | 사용자 합의 / ADR-0003 | R/O: 반영 | 상태·이벤트 필드·복구·페이지 일관성 | 수정 |
| G-06 | 최종 출력 이미지 검증·사용자 검토. 진행 중 이미지 Preview 보류 | 사용자 방향 / ADR-0003 | R: Preview UI로 축약 | 파일 접근·반환 계약. 단계별 사용자 검토 이미지는 현재 미채택 | 수정 |
| G-07 | 결과 파일 Generation 영역 보관. 에러코드·실패 단계 연계 로그·API 오류 제공 | 사용자 합의 / ADR-0003 | R/O: 반영 | 경로·원격 파일 전달·Core Metadata 등록·에러코드 목록 | 수정 |
| G-08 | Core가 Context와 전체 작업 조정, Generation은 API 입력으로 ComfyUI 실행. SQLite·AI Provider 직접 접근 금지 유지 | 사용자 합의 / ADR-0003 | O/M/R: 반영 | Context 필드·서비스 간 상세 계약 | 수정 |
| G-09 | 동일 GPU 단일 Generation·FIFO·취소·재시작 상태 확인 복구. Validation 재생성 여부/변경값 → Core 새 시도 요청 | 사용자 합의 / ADR-0003 | Bk: Queue 등 TODO; R: Job으로 축약 | Queue 저장·Batch 세부·Generation 오류별 복구·GPU 공유. 재생성 상한·횟수 계산·설정 적용은 ADR-0003 추가 결정, Validation 오류는 ADR-0004·0006 참조 | 수정 |
| G-10 | LoRA 사용 포함·학습 제외. 별도/외부 Trainer는 향후 검토 | 사용자 합의 / ADR-0003 | R/O: 반영 | 향후 Trainer 도입 여부·시점 | 유지 |

## 3. Core Backend

**제작 데이터·설정·SQLite 및 작성용 AI 연동**을 담당한다. 이후 사용자가 Core의 Context·전체 작업 조정을 채택했다([ADR-0003](../architecture/adr/0003-generation-execution-and-queue.md)). 아래 도메인 기능의 개별 검토까지 완료된 것은 아니다.

| ID | 기능·요구 내용 | 근거 / 상태 | 기존 문서 대조 | 남은 정의·책임 확인 | 확인 |
| --- | --- | --- | --- | --- | --- |
| C-01 | 작품 관리 REST 기능 | U1/U11 / B; ADR-0021 및 사용자 정정 | R: 반영 | Prompt category로 관리하며 작품은 생성 문구에서 제외. 관계 표현 재검토, 필드·API·상세 삭제 절차 미정 | 의미 정정 |
| C-02 | 캐릭터 및 외형 관리 | U1/U11 / B; ADR-0021 사용자 정정 | R: 반영 | 작품 > 캐릭터 > 의상(외형 포함). 별도 외형 선택 표현 대체, 속성·API 상세 미정 | 의미 정정 |
| C-03 | 의상·상의·하의·액세서리 구성 관리 | U1 / B; ADR-0021 사용자 정정 | R: 반영 | 의상 내부 외형 / 상의 / 하의(풋웨어 포함) 확정. 참조·조합·중첩 충돌 상세 미정 | 의미 정정 |
| C-04 | 전역 Positive(퀄리티) / Negative Prompt 관리 | U1 / B; ADR-0021·0022 확정 | R: 반영 | 전역 퀄리티 우선 조합·전역 Negative 기본·초기 의상별 Negative 저장 없음. 상세 충돌 탐지 미정 | 유지 |
| C-05 | 표정·상황·동작 Prompt 관리 | U1 / B | R: 반영 | 분류, 재사용, 조합 규칙 | ☐ |
| C-06 | 조합 시 상의·하의·의상 포함 여부 선택 | U1 원문 요구 | R: 누락 | 포함 플래그의 위치와 충돌 처리; 실행 위치 미정 | ☐ |
| C-07 | 여러 Prompt 구성 요소를 조합하는 기능 | U1 원문 요구 | M: Frontend 금지만 명시; Bk: Compiler TODO | 저장·조합·모델별 변환을 분리해서 정의 | ☐ |
| C-08 | 자연어 Prompt 활용 및 모델별 표현 | U1 요구 / Renderer는 A1 제안 | R: 자연어 누락; Bk: Schema·Compiler TODO | 자연어 직접 편집과 자동 변환 구별, 처리 모듈 미정 | ☐ |
| C-09 | Prompt AI 생성·편집 지원 | U10 / B | R: 반영 | 생성·Rewrite·Optimize 등 기능별 범위 | ☐ |
| C-10 | AI로 작품·캐릭터·의상 데이터 작성 지원 | U11 및 A11 / 사용자 재제시 | R: Prompt AI로 축약 | CRUD와 AI 초안 작성 분리, 지원 Entity 범위 | ☐ |
| C-11 | Local LLM·OpenAI·Gemini·호환 API 연동 | U10 / B 지원 대상 | R: 반영 | Provider 구현·실행 방식·모델·Endpoint | ☐ |
| C-12 | AI 직접 SQL 금지, 허용된 Core 작업·최소 Context 사용 | U10 / B 합의 | O/R/M: 반영 | 권한·Context 구성의 상세 규칙 | ☐ |
| C-13 | AI Draft → Review → Apply | A10 제안 / B 검토 | O/R/Bk: Proposed | 기본 적용 여부, 자동화 권한 예외 | ☐ |
| C-14 | Prompt Version 관리 | B 기준선 | R: 반영 | 복원·Diff·Snapshot 및 실행 기록과의 관계 | ☐ |
| C-15 | 생성 Preset 및 설정 저장·편집 | U1 / B | R: 반영 | 실행 시 적용 G-04와 구분, override 규칙 | ☐ |
| C-16 | Validation 설정과 앱 전역 설정 관리 | B 기준선 | R: 반영 | 저장·배포·실행 시 적용 책임 | ☐ |
| C-17 | 이미지 Metadata 및 도메인 연결 관리 | U11 / B | R/O: 반영 | 이미지 등록·조회·삭제 시 관계 보존 | ☐ |
| C-18 | SQLite 소유 및 데이터 접근 관리 | U10–U11 / B 합의 | O: 반영 | 동시성·트랜잭션·Migration 미정 | ☐ |
| C-19 | Prompt·설정·작품·캐릭터 Import / Export | U1/U3 / B | R: 반영 | 포맷·참조·충돌·이식성; JSON은 Runtime DB 대체 아님 | ☐ |

## 4. Validation Backend

**검증 기능을 독립 REST로 제공**한다. 원래 Local VLM 요구와 이후 외부 multimodal Provider 지원 방향을 함께 보존한다.

2026-09-12 [ADR-0004](../architecture/adr/0004-validation-outcomes-and-errors.md)에서 V-01·V-04·V-07·V-13 관련 입력·판정·오류 경계를 부분 확정했다. 이미지와 실제 생성 Prompt로 검증하고, 명시 요소가 보이지 않거나 상이하면 불합격이다. Core는 자세·구도에 맞게 Prompt를 구성하므로 upper body에서 제외된 하의·footwear는 해당 일치 검사 대상이 아니다. Provider 오류·파싱 실패는 에러코드로 반환하며 자동 이미지 재생성을 유발하지 않는다. 사용자는 CLI·Frontend에서 해당 이미지의 수동 재생성을 요청할 수 있고 Core가 새 시도를 조정한다. 각 행의 나머지 기능·Schema·Provider 설정·검증 재시도는 일괄 확정하지 않는다.

| ID | 기능·요구 내용 | 근거 / 상태 | 기존 문서 대조 | 남은 정의·책임 확인 | 확인 |
| --- | --- | --- | --- | --- | --- |
| V-01 | Web·CLI·Agent에서 검증 요청·결과 접근 | U2–U3/U11 / B | R/O: 반영 | 검증 API와 이미지 연결 계약 | ☐ |
| V-02 | 파일 손상·Decode 및 해상도 오류 검사 | U1 원문 요구 | R: 반영 | 실패 기준·오류 코드 | ☐ |
| V-03 | Aspect Ratio·포맷·Alpha·Hash·중복·Metadata 검사 | A1/A4 / B 검사 후보 | R: 반영 | 각 검사 활성화·판정 기준, 비교 범위 | ☐ |
| V-04 | Prompt와 이미지 비교, 머리색·눈색·외형·의상 등 검사 | U1 요구 / B 검사 후보 | R: 반영 | 기대 속성 입력, 보이지 않는 속성 처리 | ☐ |
| V-05 | 동일 캐릭터 외형 일관성 / Identity 검증 | U1 원문 요구 | R: 반영 | 비교 기준 이미지, 복수 이미지 입력·판정 | ☐ |
| V-06 | 표정·동작·손·얼굴 이상 검사 | A1/A4 / B 검사 후보 | R: 반영 | 검사별 범위, 불확실성·오탐 처리 | ☐ |
| V-07 | Local VLM 및 외부 multimodal Provider 연동 | U4/U9 / B | R: 반영 | Provider abstraction Proposed, 구체 모델 미정 | ☐ |
| V-08 | Provider type·Endpoint·Model·Authentication·Timeout 설정 | U4 요구 / A4·B 항목 후보 | R: 반영 | 필수 항목·연결 확인·Secret 처리 | ☐ |
| V-09 | Temperature·Max tokens·Concurrency·Batch·Retry 설정 | A4 / B 항목 후보 | R: 반영 | 기본값·지원 여부·제한 주체 | ☐ |
| V-10 | 입력 해상도·Multi-image·Structured output 지원 설정 | A4 / B 항목 후보 | R: 반영 | 실제 Capability 확인·미지원 처리 | ☐ |
| V-11 | Resize·JPEG/PNG·품질·Seed·최대 이미지 수 등 추가 설정 | A4 AI 제안 | R: 일부 축약·누락 | 후보별 채택 여부와 Provider 차이 | ☐ |
| V-12 | 기존 이미지 재검증·여러 검증 결과 비교 | A2/A4 AI 제안 | R: 누락; 결과 저장만 반영 | 재검증 요구 범위, 결과 이력·덮어쓰기 | ☐ |
| V-13 | 구조화 결과·Score·Severity·Confidence·원본 응답 기록 | A1/A4 AI 제안 | Bk: Validation Schema TODO | Schema·보존 범위·판정 기준 | ☐ |
| V-14 | Validation Profile별 검사·임계값·상속 | A4 AI 제안 | Bk: Profile TODO | Profile 계층과 override 채택 여부 | ☐ |
| V-15 | Provider 복수 등록·Fallback·Local 후 외부 재검증 | A9 AI 제안 | R: 복수 종류만 반영; 흐름 누락 | 적용 조건·비용·외부 전송 동의 | ☐ |
| V-16 | Deterministic 실패 시 VLM 검사 생략 | A4 AI 제안 | R: 누락 | 치명적 실패 기준과 단계 실행 정책 | ☐ |

## 5. Web Frontend

사용자 화면과 입력·표시 책임을 정리한다. 아래 UI가 필요하다는 사실만으로 대응 Backend의 저장·판정·조정 책임이 정해지지는 않는다.

| ID | 기능·요구 내용 | 근거 / 상태 | 기존 문서 대조 | 남은 정의·책임 확인 | 확인 |
| --- | --- | --- | --- | --- | --- |
| F-01 | 작품·캐릭터·외형·의상 Prompt 관리 화면 | U1 / B | R: Prompt 편집으로 축약 | 탐색 계층·편집 단위·참조 선택 | ☐ |
| F-02 | 전역 Positive / Negative 관리 화면 | U1 원문 요구 | R: Backend 기능 반영; 화면 축약 | 전역·개별 값 표시, 적용 범위 안내 | ☐ |
| F-03 | 표정·상황·동작 및 의상 포함 선택 화면 | U1 원문 요구 | R: 선택 UI 누락 | C-05~C-08을 조작하는 UI, 조합 규칙은 Backend | ☐ |
| F-04 | 생성 설정·Prompt 조합 → 생성·후처리·최종 결과 화면 | U1 / B 및 ADR-0003 | R: Preview만 명시, 전체 흐름 축약 | 진행 중 이미지 Preview 보류. Node 상태·Queue 동기화는 ADR-0003, UI 상세 미검토 | ☐ |
| F-05 | 생성·검증 Job 상태 표시 | B 기준선 | R: 반영 | 상태·진행률·오류 표시, 전송 방식 미정 | ☐ |
| F-06 | 생성 결과와 검증 결과를 한 UI에서 확인 | U2 요구 / B | R: 결과 표시로 축약 | 이미지 상세 화면 연결, 검증 요청 조작 | ☐ |
| F-07 | Tree Explorer·Gallery·Lightbox | U1 / B | R: 반영 | 필터·정렬·선택 범위는 별도 정의 | ☐ |
| F-08 | EXIF / Generation Metadata 확인 | U1 원문 요구 | R: Metadata 저장만 명시, 열람 UI 누락 | DB Metadata와 파일 내 Metadata 구분 표시 | ☐ |
| F-09 | 저장 경로 설정 화면 | U1 원문 요구 | R: 설정 UI로 축약; Bk: Naming TODO | 경로 템플릿 UX, 실제 경로 결정은 Backend | ☐ |
| F-10 | 이미지·폴더 삭제 UI | U1 원문 요구 | R: 누락 | 삭제 범위·결과 표시; 실제 파일·DB 처리 A-03 | ☐ |
| F-11 | Prompt·설정 Import / Export UI | U1 원문 요구 | R: Core 기능 반영, 화면 축약 | 파일 선택·실행·결과 표시 | ☐ |
| F-12 | 모델 탐색·다운로드·관리 화면 | U1 원문 요구 | R: Model UI로 축약 | 로컬·원격 목록과 다운로드 상태 | ☐ |
| F-13 | AI Prompt Draft 비교·승인 화면 | A10 / B UI 요구 | R: 반영 | Draft 정책 C-13 미확정과 연계 | ☐ |
| F-14 | Core·Generation·Validation 공용 API Client 사용, UI State 관리 | U8–U11 / B 합의 | R/O/M: 반영 | Frontend Framework·상태 관리 기술 미정 | ☐ |
| F-15 | SQLite·Prompt 핵심 조합·Workflow·AI 호출·판정·경로·Import 처리 배제 | U11/A11 / B 원칙 | M: 반영 | 서버별 담당은 개별 결정, UI에 핵심 로직 중복 금지 | ☐ |

## 6. CLI 및 외부 Agent 인터페이스

외부 Agent 자체를 AtelierX가 새로 구현한다는 의미가 아니다. 제공할 API·CLI와 자동화 사용 경험을 구분한다.

| ID | 기능·요구 내용 | 근거 / 상태 | 기존 문서 대조 | 남은 정의·책임 확인 | 확인 |
| --- | --- | --- | --- | --- | --- |
| L-01 | Web에서 하던 생성 기능을 CLI로 제어 | U1 원문 요구 | R: Thin CLI만 반영, 기능 동등성 축약 | 생성·Upscale·후처리 옵션 대응 범위 | ☐ |
| L-02 | CLI는 인자 → Shared Client → REST, 결과를 터미널에 표시 | U9 / B 합의 | R/O: 반영 | 명령 이름·출력·Exit code·비동기 추적 | ☐ |
| L-03 | Codex·OpenClaw·Hermes에서 생성 제어 | U1 / B | R: 반영 | 각 도구 사용법·설정 안내, 별도 연동 필요 여부 | ☐ |
| L-04 | Agent에 작품·캐릭터·외형·복장을 설명해 자동 생성 | U1 최종 목표 | R: Agent API 접근으로 축약 | 자연어 → 구조화 요청 책임, 작업 범위·사용자 개입 | ☐ |
| L-05 | 외부 Agent가 SDK 또는 REST 직접 사용 | U9–U11 / B 합의 | R/O: 반영 | 공개 계약, 허용 작업·권한·인증 | ☐ |
| L-06 | 검증 기능도 CLI·Agent에서 접근 | U3 / B | R/O: 반영 | 별도 validate 명령 등 구체 CLI 표면 | ☐ |
| L-07 | MCP 기반 Agent 지원 | A9 / B 향후 고려 | R: 반영 | MCP 서버 제공 여부·도구 범위; 구현 확정 아님 | ☐ |
| L-08 | 실패 분석·Prompt 수정·재생성 자동 반복 | 관련 책임은 ADR-0003 확정 | R: 누락; Bk: orchestration TODO | Validation 변경값·Core 반복 조정. CLI·Agent 명령 계약은 후속 검토 | ☐ |

## 7. Shared API Client / SDK 및 Shared Schemas / Types

| ID | 기능·요구 내용 | 근거 / 상태 | 기존 문서 대조 | 남은 정의·책임 확인 | 확인 |
| --- | --- | --- | --- | --- | --- |
| S-01 | Monorepo 공용 SDK로 세 Backend 호출 제공 | U9/U11 / B 합의 | O/M: 반영 | 언어·패키지 배포·호환성 정책 | ☐ |
| S-02 | Frontend·CLI·Internal Tools가 동일 Client 사용 | U9 / B 합의 | O: 반영 | 공용 범위, UI·CLI 전용 표현 분리 | ☐ |
| S-03 | REST API를 canonical contract로 유지 | U9 / B 합의 | O: 반영 | OpenAPI·생성 도구는 미정 | ☐ |
| S-04 | 요청·응답의 Shared Schemas / Types | B 구성 요소 | M: 반영; Bk: TODO | Schema 원본·생성·변경·호환성 | ☐ |
| S-05 | Core·Generation·Validation URL 각각 설정 | U9/U11 / B 합의 | O/R: 반영 | 설정 주입·검증·저장 위치 | ☐ |
| S-06 | 공통 오류·Timeout·인증·재시도 처리 | A8–A9 및 기술 검토 | R: 누락; Bk: 통신·인증 TODO | SDK 편의 기능과 작업 재실행 정책 구분 | ☐ |
| S-07 | 생성→검증 업무 흐름 조정은 Core 담당, SDK는 API 사용 지원 | ADR-0003 관련 결정 | R/M: 미확정 | SDK의 구체 편의 기능·구현은 후속 검토 | 수정 |

## 8. 모델 관리 — 담당 서비스 미정

외부 모델 탐색·다운로드 요구를 보존한다. Generation이 모델을 **사용**하는 책임과 모델을 **탐색·설치·관리**하는 책임을 같다고 가정하지 않는다.

| ID | 기능·요구 내용 | 근거 / 상태 | 기존 문서 대조 | 남은 정의·책임 확인 | 확인 |
| --- | --- | --- | --- | --- | --- |
| M-01 | 설치된 모델·LoRA 목록에서 사용 대상 선택 | U1 원문 요구 | R: 설정으로 축약 | ComfyUI 설치 목록 탐색과 Core Metadata의 관계 | ☐ |
| M-02 | Civitai 모델 탐색·다운로드·관리 | U1 원문 요구 | Bk: 연동 여부 TODO로만 기록 | 요구 복원 필요. API 방식·대상·설치 경로는 미정 | ☐ |
| M-03 | Hugging Face 모델 탐색·다운로드·관리 | U1 원문 요구 | Bk: 연동 여부 TODO로만 기록 | 요구 복원 필요. revision·파일 선택 등 상세 미정 | ☐ |
| M-04 | 모델 Hash·Version·출처·License 등 Metadata | A1 제안 / B Metadata 방향 | R: Model Metadata로 축약 | 기록 필드·갱신·검증·UI 노출 범위 | ☐ |
| M-05 | 모델·LoRA·VAE·기법의 호환성 확인 | A1/A11 AI 제안 | Bk: Adapter·Manager 검토 | 판단 주체, 지원 데이터, 경고·차단 조건 | ☐ |
| M-06 | 다운로드 진행·취소·재개·중복 및 실패 처리 | A1 관리 확장 / 세부 미정 | R: 누락 | 각 기능 채택 여부, 담당 서비스·저장 머신 | ☐ |

## 9. 이미지·파일·저장 관리 — Core Metadata와 파일 작업 구분

| ID | 기능·요구 내용 | 근거 / 상태 | 기존 문서 대조 | 남은 정의·책임 확인 | 확인 |
| --- | --- | --- | --- | --- | --- |
| A-01 | 이미지·대형 모델은 Filesystem, Metadata는 SQLite | U3 / B 합의 | R/O: 반영 | 파일 저장 책임·루트·접근 권한 | ☐ |
| A-02 | 작품·캐릭터·의상·표정 등을 이용한 저장 경로 설정 | U1 기능 요구·경로는 예시 | Bk: Naming TODO; R: Path만 반영 | 설정 기능과 특정 경로 규칙 확정을 구별 | ☐ |
| A-03 | 이미지·폴더 삭제 및 관련 데이터 처리 | U1 원문 요구 | R: 누락 | 파일과 DB 일관성, 복구·참조 처리 | ☐ |
| A-04 | 이미지 ID와 파일명·실제 경로 분리 | B 합의 / UUID는 제안 | O/R: 반영; Bk: ID Proposed | ID 체계·경로 변경·Import 충돌 | ☐ |
| A-05 | Generation Metadata·Prompt Snapshot·Model 정보 저장 | B 기준선 | R/O: 반영 | 확정 시점·포맷·수집 서비스·재현 범위 | ☐ |
| A-06 | EXIF / 파일 내 Metadata 읽기·보존 | U1 열람 요구 / A1 보존 제안 | R: Metadata로 축약; Bk: TODO | 읽기와 기록 분리, PNG/WebP 변환 시 유지 범위 | ☐ |
| A-07 | Sidecar JSON 또는 DB를 Metadata 정본으로 사용 | A1 AI 제안 | Bk: Metadata TODO | DB·파일·Sidecar 간 우선순위; 아직 선택하지 않음 | ☐ |
| A-08 | 이미지 포함 ZIP + manifest Export | A1/A4 제안 / B 검토 | R/O: Proposed | 이미지 포함 범위·참조·이식성 | ☐ |
| A-09 | Backup·Migration·복구 | B 용도·정책 TODO | R/Bk: 반영 | 단순 Export와 일관된 복구 보장 구별 | ☐ |

## 10. 교차 서비스 흐름·배치 — 담당 및 방식 미정

이 영역의 결론을 먼저 정해 개별 기능을 거기에 맞추지 않는다. 위 기능 검토 후 입력·출력·지속 상태를 바탕으로 논의한다.

| ID | 기능·요구 내용 | 근거 / 상태 | 기존 문서 대조 | 남은 정의·책임 확인 | 확인 |
| --- | --- | --- | --- | --- | --- |
| X-01 | Core가 Context 준비와 생성·검증·재생성 전체 작업을 접수·조정 | 사용자 채택 / ADR-0003 | O/M/Bk: TODO, 확정 반영 없음 | Node별 REST는 유지. 직접 호출과 전체 작업 연결 세부 미정 | 수정 |
| X-02 | Core가 작업 Context 준비·시도 입력 고정·Generation API 전달 | 사용자 합의 / ADR-0003 | Bk: Compiler·통신 TODO | Schema·식별·정확한 접수 계약 | 수정 |
| X-03 | Generation 영역 결과 보관과 Core Metadata 연결 | 보관 영역 확정 / ADR-0003 | O/M/Bk: TODO | 파일 전달·등록·실패 복구 상세 미정 | 수정 |
| X-04 | Core가 생성 → Validation 검증 → 필요 시 새 생성 시도 조정 | 사용자 합의 / ADR-0003 | Bk: orchestration TODO | 검증 정책·Schema·세부 호출 계약 | 수정 |
| X-05 | Core 전체 작업·상한·이력 관리, Generation 실행 상태·Queue 관리 | 역할 확정 / ADR-0003 | O/M/Bk: TODO | 저장 기술·상태 대응·중복 방지·복구 상세 | 수정 |
| X-06 | 각 Backend 독립 프로세스, 단일 PC·다중 머신 배치 | U9–U11 / B 합의 | O/R: 반영 | 프로세스 독립과 타 서비스 무의존을 구별 | ☐ |
| X-07 | Prompt AI / Validation AI와 서비스 Endpoint 설정 분리 | U9–U11 / B 합의 | O/R: 반영 | 설정 저장·실행 시 전달, Secret 위치 | ☐ |
| X-08 | 동일 GPU 사용 시 Generation·VLM 자원 경합 처리 | A4 / B 논의 대상 | Bk: GPU Scheduling TODO | 배타·동시·외부 GPU 정책은 미정 | ☐ |
| X-09 | Queue는 REST 페이지 조회 + SSE 변경 알림. 대량 변경 묶음·필요 목록 재조회 | 사용자 합의 / ADR-0003 | Bk: TODO | 이벤트 보관·번호·순서·복구·페이지 일관성. 다른 상태 전달은 미정 | 수정 |
| X-10 | 별도 BFF 없음; Client가 공통 REST API 사용 | U8–U11 / B 합의 | O: 반영 | 복합 작업 조정 주체는 별도 결정 | ☐ |
| X-11 | Reverse Proxy로 단일 주소 제공 | A8 AI 제안 | R: 누락 | 도입 여부·배포 방식. BFF 부활 의미 아님 | ☐ |

## 11. Documentation 및 개발·배포 지원

| ID | 기능·요구 내용 | 근거 / 상태 | 기존 문서 대조 | 남은 정의·책임 확인 | 확인 |
| --- | --- | --- | --- | --- | --- |
| D-01 | 단일 Monorepo, 서비스·CLI 독립 패키징 가능 | 사용자 기존 합의 / B | O: 반영 | 실제 패키지·Installer·산출물 방식 | ☐ |
| D-02 | AtelierX 전체 버전 기준 릴리즈 | B 합의 | O: 반영 | Versioning·API/Node 호환성·Release 절차 | ☐ |
| D-03 | ADR 단위 논의, 확정 즉시 repo 문서 반영 | B/C 합의 | AGENTS/O/D: 반영 | 이번 대조표의 검토 결과를 ADR·요구사항에 연결 | ☐ |
| D-04 | develop 개발 통합, main 릴리즈 및 병합 방식 | C 확정 | D/O: 반영 | 명명·갱신 등 미확정 세부만 후속 논의 | ☐ |
| D-05 | Commit / PR 메시지 형식·한국어 요약 | C 확정 | D: 반영 | 새 기능 검토로 재승인할 필요 없음 | ☐ |
| D-06 | 1인 개발, 리뷰·보호는 최초 릴리즈 후 검토 | C 확정 | AGENTS/D/O: 반영 | 현재 강제하지 않음 | ☐ |
| D-07 | CI·Test·Logging·Audit·Secret·인증·권한 | B 논의 대상 | Bk: TODO | 구체 정책·도구를 자동 확정하지 않음 | ☐ |

## 우선 확인할 문서 차이

1. **Custom Node 제작 대상**이 기존 문서에서 단순 TODO가 되었고 Generation Backend와 별도 구분되지 않았다: N-01~N-10.
2. **후처리·포맷 변환**이 상위 기능명으로 축약되었다: N-07~N-10.
3. **Prompt 포함 옵션·조합·자연어**가 구체 기능으로 보존되지 않았다: C-06~C-08, F-03.
4. **AI 작품·캐릭터 작성**이 Prompt 편집으로 좁아졌다: C-10.
5. **모델 탐색·다운로드**라는 원문 요구와 **구현 방식 미정**이 섞였다: M-02~M-03.
6. **경로 설정·Metadata 열람·이미지/폴더 삭제**가 누락·축약되었다: F-08~F-10, A-02~A-03.
7. **Core 중앙 orchestration**은 최초 대조 시 AI 제안이었다. 이후 사용자가 채택하여 [ADR-0003](../architecture/adr/0003-generation-execution-and-queue.md)에 확정했다: X-01.

## 검토 기록

2026-09-12: [ADR-0004](../architecture/adr/0004-validation-outcomes-and-errors.md)에 이미지·생성 Prompt 입력, 명시 요소 누락·불일치 불합격, 실행 오류 에러코드 반환·자동 이미지 재생성 금지·수동 재생성 지원을 기록했다. C-06~C-08의 구도별 Prompt 구성 전제 및 G-09·L-08·X-04의 반복 흐름과 연결한다. Validation 전체 항목이나 관련 Client 상세 계약을 검토 완료한 것은 아니다.

N-01~N-10은 유지·보완 확정했고 N-16~N-17은 추가 확정했다. N-11~N-15도 검토 완료했으며 상세 기법·구조는 미정으로 남겼다. 이후 G-01~G-10 및 관련 X 항목을 ADR-0003으로 반영했다. 다른 모듈은 관련 책임 변경을 주석으로 연결했으며 미검토 기능을 일괄 승인하지 않았다.

| 일자 | 항목 ID | 검토 결과 | 변경 내용 / 근거 | 반영 문서·ADR |
| --- | --- | --- | --- | --- |
| 2026-09-11 | N-01~N-05 | 유지 | 생성 입력·출력·설정 저장, 모델별 Node 분리 허용, 설치 경로·모델 제공 초기값 | [ADR-0002](../architecture/adr/0002-custom-node-functional-scope.md) |
| 2026-09-11 | N-06~N-10 | 유지 | 이미지 입력 Upscale, PNG와 별도 선택적 WebP, Detailer·Censor 참고 저장소, 선택적 캐릭터 마스크 기반 Alpha | [ADR-0002](../architecture/adr/0002-custom-node-functional-scope.md) |
| 2026-09-11 | N-16~N-17 | 유지 — 추가 요구 | 생성·후처리 Preset Load / Save. 생성 계열 전환 시 설정 혼합 방지. 자동 전환 및 Preset 단위 등 상세 미정 | [ADR-0002](../architecture/adr/0002-custom-node-functional-scope.md) |
| 2026-09-11 | N-11 | 수정 | 통합 Node 및 공통 Adapter / Capability를 필수 전제로 두지 않음. 설정·Preset 검사는 유지 | [ADR-0002](../architecture/adr/0002-custom-node-functional-scope.md) |
| 2026-09-11 | N-12 | 수정 | Encode / Save 별도 기능·Node, Frontend WebP On / Off·품질 설정 | [ADR-0002](../architecture/adr/0002-custom-node-functional-scope.md) |
| 2026-09-11 | N-13 | 수정 | 모델·최종 배율만 사용자 설정. WebP 품질은 N-12로 이동 | [ADR-0002](../architecture/adr/0002-custom-node-functional-scope.md) |
| 2026-09-11 | N-14 | 수정 | 생성 시 캐릭터 일관성 확보가 현재 목표. Inpaint·ControlNet은 후속 로드맵 | [ADR-0002](../architecture/adr/0002-custom-node-functional-scope.md) |
| 2026-09-11 | N-15 | 보류 | Crop·색감·Watermark를 후속 로드맵으로 이관 | [로드맵](roadmap.md) |

| 2026-09-11 | G-01 | 수정 | 각 Node 기능별 REST API, Node 입력 기준 파라미터 | [ADR-0003](../architecture/adr/0003-generation-execution-and-queue.md) |
| 2026-09-11 | G-02 | 수정 | Anima 기본·SDXL 보조 전체 생성용 Workflow 두 개. 단독 기능은 별도 Workflow 또는 부분 실행 허용 | [ADR-0003](../architecture/adr/0003-generation-execution-and-queue.md) |
| 2026-09-11 | G-03 | 수정 | 생성 → Upscale → Detailing → Censor → 배경 투명화 → Encode. 후처리 선택 적용 | [ADR-0003](../architecture/adr/0003-generation-execution-and-queue.md) |
| 2026-09-11 | G-04 | 수정 | Preset Load가 Current Settings 변경. 생성 시도 입력 고정 및 전달된 모델·LoRA·설정 적용 | [ADR-0003](../architecture/adr/0003-generation-execution-and-queue.md) |
| 2026-09-11 | G-05 | 수정 | 현재 실행 Node·작업 상태 제공. Queue REST 페이지 조회 + SSE 변경 알림 | [ADR-0003](../architecture/adr/0003-generation-execution-and-queue.md) |
| 2026-09-11 | G-06 | 수정 | 최종 출력 이미지 검증·사용자 검토. 진행 중 이미지 Preview 보류 | [ADR-0003](../architecture/adr/0003-generation-execution-and-queue.md) |
| 2026-09-11 | G-07 | 수정 | 결과 파일 Generation 영역 보관. 에러코드·실패 단계 연계 로그·API 오류 제공 | [ADR-0003](../architecture/adr/0003-generation-execution-and-queue.md) |
| 2026-09-11 | G-08 | 수정 | Core가 Context와 전체 작업 조정, Generation은 API 입력으로 ComfyUI 실행. SQLite·AI Provider 직접 접근 금지 유지 | [ADR-0003](../architecture/adr/0003-generation-execution-and-queue.md) |
| 2026-09-11 | G-09 | 수정 | 동일 GPU 단일 Generation·FIFO·취소·재시작 상태 확인 복구. Validation 재생성 여부/변경값 → Core 새 시도 요청 | [ADR-0003](../architecture/adr/0003-generation-execution-and-queue.md) |
| 2026-09-11 | G-10 | 유지 | LoRA 사용 포함·학습 제외. 별도/외부 Trainer는 향후 검토 | [ADR-0003](../architecture/adr/0003-generation-execution-and-queue.md) |
| 2026-09-11 | X-01 | 수정 | Core가 Context 준비와 생성·검증·재생성 전체 작업을 접수·조정 | [ADR-0003](../architecture/adr/0003-generation-execution-and-queue.md) |
| 2026-09-11 | X-02 | 수정 | Core가 작업 Context 준비·시도 입력 고정·Generation API 전달 | [ADR-0003](../architecture/adr/0003-generation-execution-and-queue.md) |
| 2026-09-11 | X-03 | 수정 | Generation 영역 결과 보관과 Core Metadata 연결 | [ADR-0003](../architecture/adr/0003-generation-execution-and-queue.md) |
| 2026-09-11 | X-04 | 수정 | Core가 생성 → Validation 검증 → 필요 시 새 생성 시도 조정 | [ADR-0003](../architecture/adr/0003-generation-execution-and-queue.md) |
| 2026-09-11 | X-05 | 수정 | Core 전체 작업·상한·이력 관리, Generation 실행 상태·Queue 관리 | [ADR-0003](../architecture/adr/0003-generation-execution-and-queue.md) |
| 2026-09-11 | X-09 | 수정 | Queue는 REST 페이지 조회 + SSE 변경 알림. 대량 변경 묶음·필요 목록 재조회 | [ADR-0003](../architecture/adr/0003-generation-execution-and-queue.md) |

권장 검토 순서: **Custom Nodes → Generation Backend → Core → Validation → Frontend·CLI·SDK → 모델·파일 관리 → 교차 서비스 흐름**. 첫 검토에서는 기능의 존재·뜻·누락을 확인하고, 책임 배정과 상세 기술 선택은 그 다음에 수행한다.

2026-09-13: [ADR-0007](../architecture/adr/0007-group-image-validation.md)로 V-03의 중복 검사를 초기 범위에서 제외하고, V-05·V-12의 그룹 일관성·선택 재검증·기준 시스템 선정/사용자 수정·기준 교체 후 확인 흐름을 확정했다. 나머지 검사 후보와 전체 Schema는 미정이다.

2026-09-13: [ADR-0008](../architecture/adr/0008-group-reference-selection.md)로 V-05·V-12 관련 기준 선정·비교 부족·충돌·이미지 추가·기준 삭제 처리와 변경 이력 보존을 확정했다. 구체 점수·알고리즘·응답 Schema는 미정이다.

2026-09-13: [ADR-0009](../architecture/adr/0009-group-validation-results.md)로 V-12·V-13 관련 묶음 결과 정보·그룹 요약·부분 결과 보존·사용자 확인을 확정했다. Score·Confidence 등 다른 후보와 기계 검증 Schema는 일괄 승인하지 않는다.

2026-09-13: [ADR-0010](../architecture/adr/0010-group-completion-and-partial-failure.md)로 그룹 고정 대상·묶음 시작 조건·부분 실패/취소·생성 현황과 일관성 요약 분리를 확정했다. 구체 Batch/Job 접수·상태·동시성은 후속 계약이다.

2026-09-13: [ADR-0011](../architecture/adr/0011-validation-input-context.md)로 V-01·V-04·V-05 및 교차 서비스의 검증 입력 정보·최종 출력 검사·Core 준비·외부 AI 최소 Context를 확정했다. 필수/선택·전송·Schema는 미정이다.

2026-09-13: [ADR-0012](../architecture/adr/0012-validation-image-transfer-and-required-input.md)로 검증 이미지 조회 API/업로드·필수 입력·접근 오류·선택 정보 부족 처리 확정. 전송/인증 구현·Schema는 후속이다.

2026-09-13: [ADR-0013](../architecture/adr/0013-validation-access-and-temporary-files.md)로 검증 이미지 접근·업로드 제한·임시 파일 수명 원칙을 확정했다. 인증 기술·제한/기간 값은 미정이다.

2026-09-13: [ADR-0014](../architecture/adr/0014-validation-checks-and-profiles.md)로 V-02~V-06·V-13·V-14·V-16의 검사 운영·기본 On/Off·Profile·검사 순서 원칙을 확정했다. 구체 알고리즘·Metadata 영향·사용자 세부 제어는 후속이다.

2026-09-13: [ADR-0015](../architecture/adr/0015-validation-providers-and-fallback.md)로 V-07~V-11·V-15의 Provider 등록/설정·지원 기능 처리·자동 Fallback 제외·수동 변경 재검증을 확정했다. 구체 Provider 구현/모델·수치·품질 보장은 테스트/후속 설계 대상이다.

2026-09-13: [ADR-0016](../architecture/adr/0016-validation-execution-and-gpu-sharing.md)로 Validation 비동기 실행·Provider Queue/동시성·취소/복구·Core 공유 GPU 조정을 확정했다. 구체 런타임·저장·원자성·수치는 후속이다.

2026-09-13: [ADR-0017](../architecture/adr/0017-regeneration-change-validation.md)로 재생성 변경 범위·제작 의도 보존·일괄 적용·Validation/Core/Generation 검사 책임을 확정했다. 구체 Schema·검사 알고리즘·Generation 오류 복구는 후속이다.

2026-09-13: ADR-0018로 묶음 운영 예외 확정. ADR-0019는 사용자 위임에 따른 API/저장/운영값 초안이며 각 세부를 사용자 승인 완료로 표시하지 않는다.

2026-09-13: ADR-0020으로 검증 접수/응답 유실·취소 경합·과거 결과·Core 중복 저장 방지를 확정했다. Core 도메인·Prompt·Preset·Import/Export 등의 개별 요구는 별도 검토 대상이다.
