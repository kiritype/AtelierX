# ADR 논의 후보와 미결정 목록

이 문서는 승인된 결정이 아니다. **Proposed**는 검토할 방향이 있는 상태이고 **TODO**는 아직 결론이 없는 질문이다. 아래 묶음은 탐색을 위한 분류이며 필요하면 여러 ADR로 나누어 하나씩 논의한다.

## 다음 논의 후보 — 추천 순서이며 미확정

사용자 요청으로 [ADR-0001: Contribution 워크플로](0001-contribution-workflow.md)를 먼저 논의한다. 아래 아키텍처 후보는 그 이후에 진행한다.

현재 우선 작업은 [모듈별 기능 대조표](../../requirements/module-feature-comparison.md)의 사용자 검토다. G-01~G-10과 Core 작업 조정·Queue 동기화는 [ADR-0003](0003-generation-execution-and-queue.md)로 반영했다. 다른 모듈의 기능 검토와 남은 계약을 진행한다. 아래 순서는 확정된 진행 의무가 아니다.

1. **Validation 기능과 오류 정책**: 검증 결과·재생성 변경값 계약, Generation 에러코드별 예외 처리. Core의 전체 작업 조정은 ADR-0003에서 확정.
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
| 분산 파일 접근 및 전달 | TODO | Generation 영역 보관 확정. 업로드·다운로드·검증 입력·Core Metadata 등록·경로 계약 미정 |
| Job Queue 상세 | TODO | 동일 GPU 단일 Generation·FIFO·취소·상태 확인 후 재시작 복구 확정. 저장 방식·접수 경쟁·Batch·중복 방지 미정 |
| Queue SSE 상세 | TODO | REST 페이지 조회 + SSE 변경 알림 확정. 페이지 방식·이벤트 보관·순서·최초 동기화·heartbeat·인증·복구·대량 변경 임계값 미정. 그 밖의 상태 전달은 미정 |
| REST 명세 / Shared SDK / Schemas | TODO | 계약 표현, SDK 언어·생성 방식, 호환성 |
| ComfyUI Custom Node 상세 구조 | TODO | 기능 N-01~N-10은 [ADR-0002](0002-custom-node-functional-scope.md)로 확정. Node 분해·입출력·설정 저장 및 복원·경로 탐색·기본값 취득과 누락 처리는 미정 |
| Encode / Save 상세 계약 | TODO | N-12 별도 기능·Node, Frontend WebP On / Off·품질 확정. Node 수·품질 범위·기본값·파일 관계·저장 계약 미정 |
| Upscale 내부 배율 처리 | TODO | N-13 설정은 모델·최종 배율만. 모델 고유 배율과 요청 배율 조정·반올림 방식 미정 |
| 생성 단계 캐릭터 일관성 | TODO | N-14 현재 목표 확정. Anima 자연어 Prompt·IP-Adapter·Img2Img 등 모델별 기법·입력·평가 미정. Inpaint·ControlNet 및 N-15는 [로드맵](../../requirements/roadmap.md) |
| Model Adapter / Capability | 필수 전제 아님 / 상세 미정 | 별도 생성 Node에 공통 추상화를 필수로 두지 않음. 모델별 설정·Preset 검사는 유지 |
| 생성·후처리 Preset 상세 계약 | TODO | N-16~N-17 Load / Save 및 생성 계열 전환 시 설정 혼합 방지는 확정. 필드·계열 구분·호환성 처리·자동 Load·미저장 변경·덮어쓰기·후처리 개별/전체 단위·저장 API는 미정 |
| Prompt Canonical Schema | TODO | Prompt 구성 요소의 표준 표현 |
| Prompt Compiler | TODO | 조합 및 모델별 변환 규칙 |
| Validation Schema | TODO | 판정·재생성 여부·시도별 변경값·근거·오류·불확실성 표현. 책임 분리는 ADR-0003 |
| Validation Profile | TODO | 검사 조합, 기준 및 설정 |
| Validation Provider abstraction | Proposed | Backend 내부 추상화와 Capability 처리 |
| VLM Provider 설정 | TODO | 설정 항목, 기본값, 지원 여부 |
| 자동 재생성 상세 | TODO | On / Off·사용자 변경 가능한 최대 횟수·최소 변경 원칙·모든 생성 설정 변경 허용 확정. 기본값·계수 범위·수동 요청 관계·Validation 오류별 정책 미정 |
| GPU Scheduling | TODO | Generation / Validation 동일 GPU 사용 시 자원 경합 정책 |
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
