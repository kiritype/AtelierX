# ADR 논의 후보와 미결정 목록

[ADR-0023](0023-negative-prompt-sources.md)으로 전역/캐릭터 Negative 분리를 확정·구현했다. 기존 미정 범위에서 제외하며 자연어 안내 확장은 후속이다.

이 문서는 승인된 결정이 아니다. **Proposed**는 검토할 방향이 있는 상태이고 **TODO**는 아직 결론이 없는 질문이다. 아래 묶음은 탐색을 위한 분류이며 필요하면 여러 ADR로 나누어 하나씩 논의한다.

## 다음 논의 후보 — 추천 순서이며 미확정

사용자 요청으로 [ADR-0001: Contribution 워크플로](0001-contribution-workflow.md)를 먼저 논의한다. 아래 아키텍처 후보는 그 이후에 진행한다.

현재 우선 작업은 [모듈별 기능 대조표](../../requirements/module-feature-comparison.md)의 사용자 검토다. G-01~G-10과 Core 작업 조정·Queue 동기화는 [ADR-0003](0003-generation-execution-and-queue.md)로 반영했다. 다른 모듈의 기능 검토와 남은 계약을 진행한다. 아래 순서는 확정된 진행 의무가 아니다.

1. **Validation 기능과 오류 정책**: [ADR-0004](0004-validation-outcomes-and-errors.md)에서 Prompt 기준 불합격·실행 오류 분리, 오류 에러코드·자동 이미지 재생성 금지·수동 재생성을 확정했다. 다음은 에러코드·결과 Schema와 남은 검사 범위 검토. Generation 오류별 복구는 별도 미정이며 Core 작업 조정은 ADR-0003을 유지한다.
2. **분산 배치에서 이미지 접근·전달**: 생성 결과와 검증 입력의 이동, 파일 저장 책임, Core의 Metadata 연결.
3. **Entity / Image ID 정책**: 안정적인 ID, 파일 경로와의 분리, Import 시 충돌 처리.
4. **Prompt Canonical Schema와 Version / Snapshot 관계**: 편집 데이터, 생성 입력, 재현 기록의 경계.
5. **Authentication / Authorization와 Agent 권한**: 로컬·원격 배치의 신뢰 경계와 허용 작업.

Commit / PR 메시지 기준은 [ADR-0001](0001-contribution-workflow.md)에서 확정하여 아래 미결정 목록에서 제외했다.

## 전체 미결정 범위

| 주제 | 상태 | 질문 또는 검토 방향 |
| --- | --- | --- |
| Backend 상세 기술 Stack | TODO | 서비스별 언어, Framework, 공용 코드 범위 |
| Frontend Framework | TODO | UI 구현 기반 |
| Local LLM 실행 방식 | TODO | Prompt AI 런타임과 연결 |
| Local VLM 실행 방식 | TODO | 검증 AI 런타임과 연결 |
| OpenAI / Gemini 및 호환 Provider 구현 | TODO | SDK 사용, 요청 변환, 오류 처리 |
| Secret / API Key 저장 | TODO | 저장 위치, 접근, 전달, 갱신 |
| Authentication / Authorization | TODO | Client·Agent·서비스 인증과 권한 |
| AI Prompt 변경 절차 | Proposed | Draft → Review → Apply 기본 사용 검토, 구체적 권한은 미정 |
| SQLite 접근 및 동시성 | TODO | 접근 계층, 트랜잭션, 동시 요청 처리 |
| 서비스 간 상세 계약 | TODO | Core Context·전체 작업 조정과 Generation 실행·Validation 변경값 반환은 ADR-0003 확정. Schema·식별·중복 방지·결과 등록 계약 미정 |
| 분산 파일 접근 및 전달 | TODO | Generation 영역 보관 및 ADR-0012의 조회 API/직접 업로드·검증 이미지 고정성 확정. 전송/인증 세부·Core Metadata 등록·경로 계약 미정 |
| Job Queue 상세 | TODO | 동일 GPU 단일 Generation·FIFO·취소·상태 확인 후 재시작 복구 확정. 저장 방식·접수 경쟁·Batch·중복 방지 미정 |
| Queue SSE 상세 | TODO | REST 페이지 조회 + SSE 변경 알림 확정. 페이지 방식·이벤트 보관·순서·최초 동기화·heartbeat·인증·복구·대량 변경 임계값 미정. 그 밖의 상태 전달은 미정 |
| REST 명세 / Shared SDK / Schemas | TODO | 계약 표현, SDK 언어·생성 방식, 호환성 |
| ComfyUI Custom Node 상세 구조 | TODO | 기능 N-01~N-10은 [ADR-0002](0002-custom-node-functional-scope.md)로 확정. Node 분해·입출력·설정 저장 및 복원·경로 탐색·기본값 취득과 누락 처리는 미정 |
| Encode / Save 상세 계약 | TODO | N-12 별도 기능·Node, Frontend WebP On / Off·품질 확정. Node 수·품질 범위·기본값·파일 관계·저장 계약 미정 |
| Upscale 내부 배율 처리 | TODO | N-13 기본 생성은 1024×1024, 기본 Upscale은 4배 모델과 최종 1.5배(1536×1536)다. 모델 고유 배율과 요청 최종 배율 조정·반올림 방식은 미정 |
| 생성 단계 캐릭터 일관성 | TODO | N-14 현재 목표 확정. Anima 자연어 Prompt·IP-Adapter·Img2Img 등 모델별 기법·입력·평가 미정. Inpaint·ControlNet 및 N-15는 [로드맵](../../requirements/roadmap.md) |
| Model Adapter / Capability | 필수 전제 아님 / 상세 미정 | 별도 생성 Node에 공통 추상화를 필수로 두지 않음. 모델별 설정·Preset 검사는 유지 |
| 생성·후처리 Preset 상세 계약 | TODO | N-16~N-17 Load / Save 및 생성 계열 전환 시 설정 혼합 방지는 확정. 필드·계열 구분·호환성 처리·자동 Load·미저장 변경·덮어쓰기·후처리 개별/전체 단위·저장 API는 미정 |
| Prompt Canonical Schema | TODO | Prompt 구성 요소의 표준 표현 |
| Prompt Compiler | TODO | 조합 및 모델별 변환 규칙 |
| Validation Schema | Proposed / 상세 TODO | [ADR-0005](0005-validation-response-contract.md)에 outcome별 응답·초기 에러코드·HTTP 매핑 초안 작성. ADR-0004 원칙은 확정. 전체 입력·변경값 Schema와 기타 불확실성 표현은 미정 |
| Validation 실행 오류 복구 | 일부 확정 / 상세 TODO | ADR-0006: outcome=error 완료 후 자동 검증 재시도 없음. 사용자가 기존 이미지·생성 Prompt로 재검증 또는 수동 재생성 선택, Core 요청·이력 관리, 재검증은 이미지 재생성 횟수 제외. 통신 오류·Job 상태·중복 방지·Batch 영향·재검증 설정 선택은 미정. Generation 오류별 복구는 별도 |
| 묶음 이미지 검증 | 범위·흐름 확정 / 상세 TODO | ADR-0007: 단일 통과 이미지 비교·중복 제외·선택 재검증. 시스템 기준 선정/사용자 수정, 기준 교체 시 이전 판정 보존·새 기준 검증 필요 표시·그룹 재검증 확인·결과에 따른 선택 재생성 확인. ADR-0008로 대표/보조 선정 원칙·비교 부족/충돌·추가/기준 삭제 처리 확정. ADR-0010으로 대상 고정·종료 후 시작·일부 실패 진행·취소·생성/일관성 분리 확정. 점수/알고리즘·Schema·상태/접수·보조 변경/삭제 영향·동시성 미정 |
| 묶음 결과 상세 계약 | 의미 확정 / 상세 TODO | ADR-0009: 이미지별 판정·그룹 3종 요약·기준 유효성·부분 성공 보존·확인 중 기준 변경 재확인 확정. 필드명/enum·HTTP·Schema·집계 대상/참조 표현·버전 저장·동시성 미정 |
| Validation 입력 상세 | 정보 범주 확정 / 상세 TODO | ADR-0011: 공통/단일/묶음 정보·최종 이미지·Core 준비·Provider 최소 Context 확정. ADR-0012로 조회 API/업로드·필수/선택 의미·부족 정보 처리 확정. 형식·인증·무결성 알고리즘·필드명/Schema 미정 |
| 검증 업로드·접근·임시 보관 | 원칙 확정 / 상세 TODO | ADR-0012: 애니메이션/동영상/다중 프레임 제외, 정지 이미지 묶음 유지. 정지 PNG/WebP만 지원 확정(JPEG 제외). ADR-0013: 서비스 인증·처리 중 접근/파일 보호·재검증 권한 확인·용량/픽셀/개수 제한·종료 후 임시 정리·이력/원본 보존 확정. 기술·한도/기간·디스크 부족·동시성 미정 |
| Validation Job 실행 | 원칙 확정 / 상세 TODO | ADR-0016: 비동기·Provider Queue·초기 동시성 1·REST/SSE·취소/복구·중복 접수 확정. 상태/저장·접수 키 충돌/수명·Timeout·분할·늦은 응답 미정 |
| 재생성 변경값 상세 | 원칙 확정 / 구현 TODO | ADR-0017: 필드 범주·의도 보존·최소 변경·모델 호환·일괄 적용·3서비스 검사 책임 확정. 중첩 Schema·범위/목록 전달·의도 검사·오류 코드·실행 전 환경 경쟁 미정 |
| Validation Profile | 원칙 확정 / 상세 TODO | ADR-0014: 단일/묶음 분리·기본값·복제/수정·초기 상속 없음·요청 시 고정·검사 순서 확정. 세부 기준/기본값 사용자 제어 확장 검토, 구체 필드/UI/범위·판정 구현 미정 |
| Validation Provider abstraction | 책임 확정 / 구현 TODO | ADR-0015: 내부 응답 정규화·지원 기능 처리 확정. 구체 Adapter/SDK·탐지 방식 미정 |
| VLM Provider 설정 | 원칙 확정 / 상세 TODO | ADR-0015: 복수 등록·단일/묶음 선택·연결 확인·요청 고정·자동 Fallback 없음·수동 변경 재검증 확정. 구체 필드/기본값·Secret·런타임·모델·품질 검증 미정 |
| 자동 재생성 상세 | 일부 확정 / 상세 TODO | ADR-0003 추가 확정: 수동 재생성 무제한, 자동 상한은 Core 설정·기본 5회. 최초 생성·수동 재생성은 자동 횟수 제외. 수동 요청마다 자동 사용 횟수를 0으로 초기화하고 설정 상한을 새로 부여하며 기존 이력은 보존. 상한은 0 이상 정수(0은 자동 생성 없음), 실제 자동 실행 시작 시 1회 차감·대기 취소 제외·실행 후 실패/취소 포함. Validation 오류 시 횟수 유지·자동 종료, 상한 도달 시 마지막 결과 보존·종료. 설정 변경은 새 생성/수동 요청부터 적용. Schema·실행 이벤트·중복 방지·복구 계약 미정. ADR-0004·0006의 오류 후 자동 생성·검증 재시도 금지 유지 |
| GPU Scheduling | 원칙 확정 / 구현 TODO | ADR-0016: Core 공유 GPU 권한 조정·추론 중첩 금지·준비 순서·VRAM 확보 확인·독립 자원 병렬. 식별/권한 원자성/복구·unload·직접 ComfyUI 경쟁 미정 |
| Model Manager | TODO | 관리 범위, 탐색, 설치 및 상태 소유권 |
| Civitai / Hugging Face API | TODO | 연동 여부와 범위 |
| 파일 Naming Rule | TODO | 저장 루트, 상대 경로, 이름 생성 |
| Metadata / EXIF | TODO | 기록 형식, 보존 및 제거 정책 |
| Image ID / Entity ID | Proposed | UUID 등 안정적인 ID 검토. 구체적 체계 미정 |
| Import / Export 포맷 | TODO | JSON 등 구체 Schema, 참조와 충돌 처리 |
| 이미지 포함 Export | Proposed | ZIP + manifest 검토 |
| Backup | TODO | DB·파일의 일관성, 복구 범위 및 절차 |
| Migration | TODO | DB / Export Schema 및 버전 간 이전 |
| Branch 세부 정책 | Proposed | [ADR-0001](0001-contribution-workflow.md): 브랜치 흐름·기본 브랜치 develop·최초 초기화는 확정. 명명·갱신 및 기타 Repository 설정은 미정 |
| 리뷰·브랜치 보호 | Proposed — 적용 유예 | 현재 1인 개발. 최초 릴리즈 완료 후 적용 범위 재검토. 현재 설정하거나 자동 활성화하지 않음 |
| CI | TODO | 자동 검사 및 빌드 |
| Test | TODO | 테스트 범위와 통과 기준 |
| Release | TODO | main에서 릴리즈하는 것은 확정. 트리거·태그 및 전체 프로젝트 릴리즈 상세 절차는 미정 |
| Versioning | TODO | 버전 표기 및 서비스·SDK·계약 호환성 |
| Packaging | TODO | 서비스·CLI 독립 패키징 방식 |
| Installer | TODO | 설치·업데이트 경험 |
| Logging / Audit | TODO | Generation 에러코드·작업/단계 연계 로그·API 오류 제공 확정. 코드 목록·형식·보존·Audit·민감정보 정책 미정 |

전체 프로젝트 버전 기준, 서비스·CLI 독립 패키징 가능성, SQLite 채택, REST 계약 및 세 Backend 분리는 이미 확정된 제약이다. 이 표는 그 세부 방식을 열어 둔다.

## Validation 남은 논의 묶음 — 2026-09-13 점검

문서 수의 확정 계획이 아니라 현재 미결정 사항을 모은 진행 추정이다. 같은 주제는 기존 ADR을 보완할 수 있다. 기능/운영 설계는 아래 5묶음으로 검토하고, 구현 착수용 계약은 뒤의 2묶음과 공통 아키텍처 결정을 함께 다룬다.

1. 검사 상세·Profile: Negative Prompt, 신체 이상, 출력/Alpha·Metadata 검사, 활성화·임계값·검사 순서·불확실성. 기존 확정 판정은 재논의하지 않음.
2. Provider 설정·지원 기능: Local/외부 선택, abstraction, Multi-image/structured output, 미지원 처리, 복수 Provider·Fallback 여부, 외부 전달 전처리.
3. 실행·GPU 운영: 동기/비동기, Validation Queue·동시성·Timeout·취소·복구, 같은 GPU의 Generation/VLM 조정. 오류 후 자동 재시도 금지는 유지.
4. 재생성 변경값: 필요한 입력·허용 필드·타입/범위·모델 호환·최소 변경의 검사. Generation 오류별 복구 책임도 연결해 검토.
5. 묶음 운영 예외: 기준 선정 점수/동점·보조 수·보조 변경/삭제·그룹 변경 중 실행·결과 유효성·일관성 불확실성 세부.
6. API/저장 계약: ADR-0005 초안 및 묶음 요청/결과의 필드·ID/버전·에러코드·HTTP·중복 방지·기록/로그.
7. 운영 기술/수치: 서비스 인증/Secret·업로드 한도·보관 기간·디스크 부족·정리/복구·Provider 제한값.

Backend Stack·공용 ID/파일·인증 등은 프로젝트 공통 ADR과 겹치므로 Validation에서 중복 결정하지 않는다. 기본 흐름과 책임은 확정됐지만 위 기술/검사 상세까지 구현 준비가 끝난 상태는 아니다.

2026-09-13 진행 갱신: 위 남은 1번 검사·Profile 묶음의 기본 운영/기준은 ADR-0014로 확정했다. 세부 알고리즘·사용자 제어 필드는 구현 계약으로 남기며 다음 기능 논의는 Provider 설정·지원 기능이다.

2026-09-13 진행 갱신: 위 2번 Provider 설정·지원 기능은 ADR-0015로 확정. 테스트로 동작/품질을 확인하며 조정 이력을 남긴다. 다음 기능 논의는 실행·GPU 운영이다.

2026-09-13 진행 갱신: 3번 실행·GPU 운영 묶음은 ADR-0016으로 확정했다. 다음 기능 논의는 재생성 변경값의 허용 필드·범위·호환성·최소 변경 검사다.

2026-09-13 진행 갱신: 4번 재생성 변경값 묶음은 ADR-0017로 확정. 다음은 5번 묶음 운영 예외다.

## 현재 재개 지점 — 상세 설계 위임 반영

2026-09-13: 위 5번 묶음 운영 예외는 ADR-0018로 확정해 기능·운영 원칙 5묶음을 마쳤다. 6~7번 API/저장·운영값은 ADR-0019 초안으로 구체화했다. 위 표의 구현 TODO는 질문 대기 목록이 아니다. 사용자 위임에 따라 기존 요구 안에서 개별 승인 질문 없이 Schema·구현 검토·테스트로 해결하며 제품 경계 변경이나 요구 충돌만 질문한다.

ADR-0005는 이전 요청대로 Proposed 이력을 유지하고 신규 비동기 계약은 ADR-0019에서 통합 검토한다. 다음 실제 작업은 기계 검증 Schema·상태 전이·Provider 평가와 저장 복구 테스트 준비이며, Validation Backend 구현 시작은 별도 지시 범위다.

2026-09-13 계약 구체화: docs/contracts/validation에 5종 Schema·예제 10개·상태 전이·18개 계약 검사를 작성/실행했다. 실제 저장 복구·전체 OpenAPI·권한·Provider 판정 품질은 남은 검증이다. ADR-0019 Proposed를 유지한다.

## 현재 작업 범위 재확인

사용자가 현재는 ADR 검토 단계임을 재확인했다. Validation 코딩·기계 Schema·자동 검사는 진행하지 않는다. ADR-0019에 요청/작업/결과 분리와 검사 실행/생략 보고를 문서로 보완했다. 기존 생성된 계약 검사 자료는 참고로만 보존하며 확정 근거가 아니다. 다음은 접수/취소/기준 변경 경쟁·결과 보존의 문서 검토다. 별도 승인된 Custom Node 개발은 유지한다.

## Core 다음 검토 묶음 — 현재 남은 범위

최신 진행: [ADR-0022](0022-prompt-composition.md)로 전역·의상 Prompt 조합 기본을 확정했다. 아래 실제 조합 검토 예정 표현은 이 결정으로 진행 완료다. 다음 검토는 표정·동작·상황 Prompt 저장과 복수 선택에 따른 생성 조합이다. 세부 구도 사례·모델별 문법·충돌 탐지·편집 버전·요청 덮어쓰기 범위는 미정으로 유지한다.

전역 Positive(퀄리티)·Negative와 의상 내부 외형 / 상의 / 하의(풋웨어 포함)는 ADR-0021로 추가 확정했다. 다음 검토는 실제 조합과 구도별 포함·제외다.

최신 정정: category 계층은 **작품 > 캐릭터 > 의상(외형 포함)** 으로 확정했다. 외형 별도 선택 제안은 대체되었다. 다음은 의상 항목 내부 Prompt 구성과 구도별 포함·조합 규칙이며 공유·참조의 상세 방식은 미정이다.

2026-09-13 사용자 정정 반영: 작품 / 캐릭터 / 의상은 Prompt 편집·저장 category이고 작품은 생성 Prompt에 포함하지 않는다. ADR-0021의 독립 데이터 관계를 category 관계·재사용으로 표현하는 방식을 먼저 재검토한다. 복수 작품 연결·공유 규칙을 일괄 폐기하거나 특정 category 계층을 새로 확정하지 않는다. 이후 실제 문구 조합을 별도로 검토한다.

Core의 DB 소유·Context 준비·생성/검증 조정·상한/이력·설정 소유는 기존 ADR에서 확정했다. 아래는 새로 전부 시작하는 목록이 아니라 남은 도메인·운영 계약의 묶음이다. 순서와 ADR 개수는 권고다.

1. 작품·캐릭터·외형·의상: 관계/소속·공유/재사용·삭제/보관·그룹 구성.
   - 2026-09-13 ADR-0021로 원칙 확정. 구체 필드·API·보관/복원 및 영구 삭제 절차는 후속 계약으로 남긴다. 다음 검토는 2번 Prompt 조합이다.
2. Prompt: 전역/작품/캐릭터/의상/표정/동작 조합·우선순위·구도별 포함·Version/실행 Snapshot.
3. Preset·설정: 생성/후처리/검증 설정 범위·복제/수정·모델 계열 전환·기본값/덮어쓰기.
4. 이미지·작업 기록: 그룹/시도 연결·대표/보조 변경 이력·Metadata·파일 누락/삭제와 기록 수명.
5. Prompt AI·Agent: 허용 Core API 작업·Draft/검토/적용·권한·사용자 확인 경계.
6. Import/Export·Backup: 참조 충돌·호환성·이미지 포함 범위·DB/파일 일관성·복구.

공통 Backend Stack·ID·인증·SQLite 동시성은 별도 공통 설계와 연결하며 Core에서 중복 확정하지 않는다. 다음 권고는 1번 도메인 관계다. Validation의 남은 API/수치 상세는 ADR-0019로 보존한다.

## Frontend 전체 구성 후속 — 2026-09-13

상단 제작·갤러리·작업 현황·설정과 기본 배치는 사용자 승인으로 [화면 구성 문서](../../development/frontend-structure.md)에 보존했다. 메뉴 구성을 다시 미정 질문으로 올리지 않는다. 제작 상세와 기존 API 대조를 진행하며 일반 조회 API·UI 상세를 별도 ADR 승인 질문으로 쪼개지 않는다. Framework·브라우저 재시작 후 초안 저장·삭제/Import/Export 정책 등은 기존 경계에 맞춰 별도로 구분한다.

2026-09-22 사용자 정정: 외형은 캐릭터, 상의·하의·액세서리는 의상에 저장하고 조각에 accessories 포함 체크를 추가한다. ADR-0021/0022 후속 정정으로 확정했으며 이 배치를 미결정으로 다시 취급하지 않는다. 릴리즈 후보 브랜치·설치 패키지·매뉴얼 준비는 roadmap의 단계 계획으로 구분한다.
