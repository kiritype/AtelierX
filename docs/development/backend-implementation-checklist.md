# Backend 요구사항·구현 대조 체크리스트

> 최신 점검: [2026-09-21 구현 현황](implementation-status-2026-09-21.md). 아래는 9월 13일의 시점별 기록이다. Shared API Client·제품 CLI·Frontend, 전역 조각·제작 계획, Profile/Provider CRUD 및 Upscale은 이후 구현됐다. 아래 미구현 표현을 현재 상태로 사용하지 않는다. 실제 운영 준비도는 [실사용 준비도](practical-readiness.md)를 따른다.

기준일: 2026-09-13. 확정 ADR·요구사항을 현재 `src/atelierx`의 API/worker/store 및 테스트와 대조했다. **현재 구현 범위는 Anima 생성·후처리·단일/묶음 검증·재생성·Preset 및 Core 조정의 초기 기능이다. 세 Backend 전체 완료가 아니다.**

이 문서는 구현 현황이다. 기존 [기능 대조표](../requirements/module-feature-comparison.md)의 문서 반영 여부·사용자 검토 표시를 구현 완료로 바꾸지 않는다. 미정 상세를 Accepted로 전환하거나 새 기능을 승인하지 않는다.

## 현재 진행 현황 — 병렬 작업 시작 시점

아래 역사 표의 개별 미구현 표현보다 이 현황과 연결된 최신 보고서를 우선한다. 진행 중은 구현·검증 완료를 뜻하지 않는다.

| 범위 | 현재 상태 | 다음 검증/남은 기능 |
| --- | --- | --- |
| 단일 생성→검증·GPU 조정·취소·Queue/SSE | 구현/시험 완료 범위 있음 | 다중 자원, 실행 불명 복구, 실제 Node 진행률은 별도 |
| 수동/자동 재생성 | 기본 구현 완료 | 근거 연결된 seed/steps/cfg 변경, 기본 5회; 확장 변경안은 별도 |
| 묶음 비교·명시적 기준 변경·선택 재검증 | 초기 구현 완료 | 실제 여러 이미지 LM Studio 호출 및 Core 이력 보존 확인 |
| 기준 후보·선택 재생성 후 묶음 재검증 | 코드/회귀·실환경 후속 성공 | 가시성 근거·기준/대상 경합·대체 활성 전환. 이전 timeout/busy 이후 재검증에서 선택 이미지 후속 연결 성공 |
| 기존 이미지 독립 후처리 API | 초기 구현·실제 시험 완료 | PNG/WebP 원본 각각 전체 후처리 및 output hash 확인 |
| 생성/후처리 Preset | 초기 구현·REST 시험 완료 | 별도 저장 모듈·revision·실행 snapshot 통합 |
| 장애·복구 추가 회귀 | 추가 시험 완료 | worker 원본 변경·접수키·취소·응답 유실 등 10개 |
| 그룹 일괄 생성·완료 집계 | 초기 구현·회귀/실환경 시험 완료 | 2장 생성→단일 통과→기준 확인→묶음 검증·재시작 보존 확인. 일관성 판정 품질 개선은 남음 |
| 사용자 Profile/Provider 관리 | 초기 구현·회귀/실환경 시험 완료 | 현재 revision 7에서도 접수 당시 revision 6으로 단일/묶음 실제 실행. 모델 capability 실검사는 후속 |
| 신체 이상 검사 | 미구현 | 별도 후속 범위 |
| Upscale 및 기본 1024→1536 | 초기 구현·실환경 시험 완료 | 4x UltraSharp, PNG/WebP 최종1536 및 Validation 기대크기 검증 |
| SDXL·SDK·제품 CLI·F/E | 후속 범위 | 이번 병렬 작업에 포함하지 않음 |

검증 기준점: 일관성 v9 기준 사전 비교 보완 후 `.venv/Scripts/python.exe -B -m unittest discover -s tests -q` 143개 통과(16.944초). 최신 묶음 대조는 [6개 사례 보고서](group-consistency-controls.md)에서 기준 사전 비교 적용 후 7건 중 6건 일치·1건 응답 상한 오류으로 기록했다. 실제 Upscale 검증은 [일관성·기본 Upscale 보고서](consistency-upscale-improvements.md), 이전 이력은 [일괄 실행 보고서](group-batches-live-validation.md)와 [병렬 구현 보고서](parallel-backend-validation.md)에 기록했다.

## 2026-09-13 후속 완료: Negative 출처 분리

[ADR-0023](../architecture/adr/0023-negative-prompt-sources.md) 승인으로 아래 최초 V03 문제를 해결했다. 전역 Negative는 검사에서 제외하고 캐릭터 Negative만 검사한다. 캐릭터 저장/수정·snapshot·실제 생성 합성·Validation 출처 전달 구현, Backend 회귀 42개 및 실제 VLM 출처 대조·새 생성/후처리 전체 흐름 검증을 완료했다. API는 [별도 명세](../api/rest-api.md)에 저장했다. 아래 V03과 권장 순서 1은 발견 당시 이력이며 현재 미완료로 집계하지 않는다. 자연어 안내 확장은 여전히 제한된다.

## 상태 기준

- **완료**: 해당 행에 한정한 동작을 코드와 시험으로 확인. 제품 전체·모든 운영 조건의 완료는 아님.
- **부분**: 기반은 있으나 확정 요구 중 일부가 빠지거나 범위가 제한됨.
- **미구현**: 사용자 기능을 수행하는 API/처리 경로가 없음. enum·설정 필드만 있는 경우도 해당.
- **미검증**: 코드 또는 연결 기반은 있으나 실제 환경·품질 근거가 부족함. 부분 상태와 함께 표시할 수 있음.

행마다 크기가 다르므로 완료율 백분율은 계산하지 않는다. 요구가 확정된 기능과 방법만 검토 중인 후보·로드맵을 구분한다.

## 2026-09-13 후속 구현: 자동 연결·GPU·취소·Queue

[후속 기록](core-orchestration-validation.md)으로 F02의 선택적 자동 연결, F06의 단일 공유 GPU 조정, F07의 대기/협력 취소, F08의 Queue REST·SSE를 구현했다. 아래 표는 최초 점검 시점의 근거를 보존한다. 해당 기능을 더 이상 전부 미구현으로 집계하지 않는다. 다중 자원·Provider별 병렬 Queue, 실제 Node 진행률, 실행 불명 이후 운영 복구·과거 SSE 재생 등은 남아 있다.

## 1. Core–Generation–Validation 실행 흐름

| ID | 요구 및 근거 | 상태 | 확인된 범위 / 남은 범위 |
|---|---|---|---|
| F01 | 3개 독립 REST 서비스·Core 상태 소유 — 아키텍처 기준선 | 완료 | 독립 실행 진입점, Core SQLite, Generation/Validation 로컬 Job 저장. Generation은 ComfyUI REST만 호출 |
| F02 | 생성 → 단일 검증 → Core 결과 보관 — ADR-0003·0004·0006 | 부분 | Core Task의 선택적 생성→단일 검증 자동 접수·결과 저장 구현. 그룹 생성 대상 일괄 접수/완료 감지는 별도 |
| F03 | 동일 접수 키·응답 유실·최종 결과 보호 — ADR-0020 | 부분 | 동일 내용 기존 Job·다른 내용 충돌, 응답 유실 시 조회, 정상 재시작 보존 확인. 취소/기준 변경 경합은 미구현 |
| F04 | 이미지 조회·고정 프롬프트·해시 전달 — ADR-0011·0012 | 완료 | PNG/WebP, 등록 Generation ID 조회 또는 Validation 업로드, 실제 생성 문구·해시 확인. 새 출력의 실제 LM Studio 왕복 성공 |
| F05 | 실행 오류와 불합격 분리 — ADR-0004·0006 | 완료 | `outcome=error`와 코드, 오류 후 자동 재생성·검증 재전송 없음. 수동 재검증은 새 키로 별도 이력 생성 |
| F06 | 서비스 간 공유 GPU 조정 — ADR-0016 | 부분 | Core 단일 GPU 권한·메모리 확보·반납 및 ComfyUI/LM Studio 순차 실행 구현. 다중 자원과 실행 불명 운영 복구는 남음 |
| F07 | 취소 및 완료/취소 경합 — ADR-0003·0016·0020 | 부분 | 세 서비스의 대기/협력 취소 및 늦은 결과 보호 구현. 기능별 확장 경합은 회귀로 보완 |
| F08 | Queue·현재 실행 Node·REST 페이지·SSE — ADR-0003·0016 | 부분 | Queue REST 페이지·SSE 최신 상태 제공. 실제 ComfyUI Node 진행률·과거 이벤트 재생 미구현 |
| F09 | 자동/수동 재생성 — ADR-0003·0006·0017 | 부분 | 수동 무제한·새 cycle, 자동 기본 5회·실행 시작 집계·오류 종료·이력 구현. 변경 제안은 seed/steps/cfg로 한정 |
| F10 | 그룹 생성 완료·부분 실패·대상 고정 — ADR-0010 | 부분 | 의상 구성이 고정된 그룹과 개별 Task 있음. 그룹 실행 대상 접수·완료 집계·부분 실패 상태·검증 시작 조건 없음 |
| F11 | 묶음 일관성·기준 선정/교체·선택 재검증 — ADR-0007~0010·0018 | 부분 | 명시적 기준·다중 이미지 비교·선택 재검증·기준 유효성·요약 구현. 기준 후보·설정 고정·단일 자동 시도 추적·선택 출력 묶음 후속 구현 및 회귀 완료. 사용자 작업 종료 후 신규 전체 실환경 연결도 성공(20260913-133748) |

## 2. Core 제작 데이터와 설정

| ID | 요구 및 근거 | 상태 | 확인된 범위 / 남은 범위 |
|---|---|---|---|
| C01 | 작품 > 캐릭터 > 의상, 외형/상의/하의 — ADR-0021 | 완료 | REST 생성·조회·수정·revision·archive, 그룹 의상 구성 고정. 독립 액세서리와 category 이름의 생성 문구 삽입 없음 |
| C02 | 전역 품질/Negative·순서·포함 제어·미리보기 — ADR-0022 | 부분 | 순서·원문/가중치 보존, include 플래그, upper_body 하의 제외, full_body, preview hash. 모순 탐지는 upper_body+lower 강제 포함 충돌 등 구조 검사에 한정. 자유 문구 모순 및 추가 구도는 미완성/상세 미정 |
| C03 | 표정·행동·상황 Prompt 관리 — 요구 C-05~08 | 부분 | 요청 문자열 합성 지원. 재사용 라이브러리·복수 선택 저장·모델별 변환은 미구현이며 세부 계약 미정 |
| C04 | 변경 이력·Prompt Version — 요구 C-14·ADR-0022 | 부분 | Entity revisions와 실행 snapshot 존재. 전역 설정 전체 이력·Prompt diff/복원 제품 기능 없음. 정확한 버전 관리 계약은 미정 |
| C05 | 생성·후처리 Preset Load/Save — ADR-0002 N-16~17 | 완료(초기 범위) | generation/postprocess Preset CRUD·보관·revision 이력·Task/preview 적용·설정 출처 고정, REST 회귀 확인 |
| C06 | Validation Profile·Provider 사용자 관리 — ADR-0014·0015 | 부분 | 서버 JSON 등록·선택·요청 고정, 일부 검사 On/Off. Core CRUD·복제/수정·연결 확인·자격증명 관리 기능 없음 |
| C07 | Prompt AI·도메인 AI 작성 — 요구 C-09~12 | 미구현 | Core LLM 호출·작성 지원 API 없음. Validation VLM 연결과 별개. Draft/Review/Apply 상세는 Proposed |
| C08 | 이미지 Metadata·도메인 연결 — 요구 C-17 | 부분 | ID·Task/그룹·Generation 참조·해시·형식·판정·프롬프트 snapshot 조회. 파일 Metadata/EXIF 정책·수명주기·삭제·검색 확장은 별도 |
| C09 | Import/Export·Backup/Migration — 요구 C-19 및 저장 기준선 | 미구현 | 제품 이동/복원 기능 없음. 초기 SQLite schema version과 테이블 생성이 전체 migration/backup 구현은 아님. 형식·충돌 상세 미정 |

## 3. Generation 기능

| ID | 요구 및 근거 | 상태 | 확인된 범위 / 남은 범위 |
|---|---|---|---|
| G01 | Anima·다중 LoRA·가중치 — ADR-0002 N-02~05 | 완료 | 등록 자원 확인·고정 입력·순서 있는 LoRA·실제 생성. 이 행은 Preset·모든 모델 버전의 호환성을 포함하지 않음 |
| G02 | SDXL Illustrious — ADR-0002 N-03 | 미구현 | 생성 Node/API 없음 |
| G03 | Detailer/Censor/Alpha/Encode 파이프라인 — ADR-0002·0003 | 부분 | **Generation B/E에서 실제 4단계 처리 및 PNG/WebP 저장 성공**. Censor 양성 검출률·Alpha 경계 품질·각 Detailer 개선 품질은 미검증. 입은 얼굴 검출 fallback |
| G04 | 기존 이미지의 독립 후처리 API — ADR-0002 N-06·ADR-0003 G-01~03 | 완료(초기 범위) | Generation 저장 image ID 입력의 독립 후처리 API 구현. PNG/WebP 각각 Detailer/Censor/Alpha/Encode 실제 실행. 외부 업로드/Core 자동 편입은 별도 |
| G05 | Upscale 모델·최종 배율 — ADR-0002 N-06·13 | 초기 구현·실검증 | Node 연결·4x UltraSharp 설치·Generation 파이프라인·1024→1536 PNG/WebP 실제 실행 확인 |
| G06 | 생성 단계 일관성 확보 — ADR-0002 N-14 | 부분·미검증 | 고정 문구/설정 사용. Identity 보존 기법·평가 기준 미정. IP-Adapter/Img2Img는 채택 확정된 미구현 의무로 세지 않음 |

현재 고정 순서는 생성 → Upscale → Detailer → Censor → Alpha → Encode다. Upscale→Encode와 기존 나머지 보조 stage 흐름은 각각 실제 실행을 검증했다. 모든 stage를 합친 최신 graph의 동시 품질 검증은 별도다. 로드맵의 Inpaint·ControlNet·Crop·색감·Watermark와 LoRA 학습 제외는 현재 구현 누락으로 계산하지 않는다.

## 4. Validation 기능과 발견한 설계 불일치

| ID | 요구 및 근거 | 상태 | 확인된 범위 / 남은 범위 |
|---|---|---|---|
| V01 | 필수 입력·Decode·형식·출력 조건 — ADR-0012~0014 | 완료 | 정지 PNG/WebP, 해시, 크기/픽셀 제한, 요청 크기·형식·alpha 검사. 실패 시 Provider 생략 |
| V02 | Positive 요소 누락/불일치 — ADR-0004·0014 | 부분 | 항목별 근거→서버 집계, 가중치 묶음 원문 보존/분리 및 실제 회귀 확인. 자연어 복합 의미·다양한 이미지의 일반 정확도는 미검증 |
| V03 | Negative의 관찰 가능한 금지 요소 — ADR-0014 | 부분 | ADR-0023 반영: 전역 Negative는 생성 전용, 캐릭터 Negative만 금지요소 검사. 출처 회귀·실제 검증 완료, 자연어 전반의 정확도는 별도 |
| V04 | 손·얼굴·사지 구조 이상, Metadata — ADR-0014 | 미구현 | 해당 Profile 설정 활성화 시 거절. 손/표정이 Prompt에 명시됐을 때 일치 검사가 된다는 사실은 별도 신체 이상 검사 완료를 뜻하지 않음 |
| V05 | Local/외부 Provider·지원 기능·선택 — ADR-0015 | 부분·미검증 | 호환 Chat Completions adapter·구조화 응답·Timeout·오류 정규화. LM Studio 실측, PNG 전송 호환 보완. 외부 OpenAI/Gemini 실제 호출·고유 adapter·Capability 확인 미완료 |
| V06 | 수동 재검증·결과 이력 — ADR-0006·0020 | 완료 | 새 키로 기존 이미지/실제 Prompt 재검증, 결과 이력·중복 접수·Core 재시작 보존. 기준 이미지 교체에 따른 묶음 이력은 F11 범위 |
| V07 | 검증 순서·검사 범위와 설정 고정 — ADR-0014 | 부분 | 필수→출력→AI 순서, snapshot, 비활성 Prompt 제외, Provider 설정 변경 감지. Profile 사용자 관리와 명시적 실행/미실행 요약 계약은 확장 필요 |
| V08 | 중복 이미지 검사 — ADR-0007 | 제외 | 그룹 내 중복 검증은 확정적으로 제외. hash 무결성 검사를 중복 판정으로 부르지 않음 |

V03의 과거 출처 분리 문제는 ADR-0023 구현으로 해결했다. 실제 표본 통과가 자연어 검증의 일반 정확도를 보장하지는 않는다.

## 5. 복구·운영의 완료 경계

| 범위 | 상태 | 경계 |
|---|---|---|
| 데이터 디렉터리 단일 소유·저장 | 부분 | 세 서비스에 ProcessLock, Core WAL/트랜잭션, Job 원자 저장 존재. Core broker를 공유하는 프로세스의 GPU 실행은 조정함. 별도 broker/직접 사용자 실행과의 경쟁은 완전히 통제하지 못함 |
| 응답 유실·정상 재시작 | 부분 | Mock 장애 경로와 Core 실제 재시작 확인. Validation 진행 중 수락 불명은 오류 종료·재전송 금지. 강제 종료·전원 장애·장시간 부하 미검증 |
| Timeout·복구 종료 조건 | 부분 | HTTP/Provider timeout 존재. Generation 전체 대기/실행 기한과 무한 관찰 종료·사용자 복구는 미완료 |
| 파일 보관·정리 — ADR-0013 | 부분 | 작업 파일/이력 저장·입력 제한 존재. TTL·용량 정리·디스크 부족·진행 중 파일 보호와 정리의 경합 시험 미완료 |
| 인증·분산 운영 | 부분·미검증 | Bearer·등록 source URL·경로 제한·환경변수 키 지원. 세분화된 사용자/Agent 권한·Secret 운영·원격 TLS·분산 배포 시험 미완료; 세부 정책 미정 |

## 근거 파일·검증 기록

- 구현: [Core API](../../src/atelierx/core.py), [Core 저장](../../src/atelierx/core_store.py), [Core 검증 연결](../../src/atelierx/core_validation.py), [Generation](../../src/atelierx/generation.py), [후처리 그래프](../../src/atelierx/generation_pipeline.py), [Validation](../../src/atelierx/validation.py), [항목별 판정](../../src/atelierx/validation_evidence.py).
- 시험: [tests](../../tests/), [전체 테스트 리포트](full-test-report-2026-09-13.md), [실제 VLM 전체 흐름·WebP 수정](real-vlm-pipeline-2026-09-13.md). 과거 보고서의 테스트 수는 해당 시점 기록이다. 최신 통합 수치는 상단 기준점을 참조하며 미검증 품질을 대표하지 않는다.
- 공개 경로: [실제 REST 명세](../api/rest-api.md)에 Core·Generation·Validation의 등록 경로와 제한을 함께 기록한다.
- 당시 제품 Shared API Client·CLI·Frontend는 미구현이었다. 이후 구현된 제품 기능과 잔여 범위는 상단의 2026-09-21 점검을 따른다.

## 다음 작업 순서

1. 그룹 선택 재생성 전체 실환경 시험은 20260913-133748에서 성공. 다음은 아래 잔여 Backend 범위다.
2. 그룹 실행 대상 고정·생성 완료 및 부분 실패 집계, 사용자 Profile/Provider 관리와 검사 확장.
3. 자원 준비에 맞춘 Upscale·SDXL 잔여 범위.
4. 안정된 Backend API를 기반으로 Shared API Client → 제품 CLI → Frontend.

통상 상세는 기존 위임대로 진행하고 제품 의미 변경만 별도 확인한다.


## 2026-09-13 재생성 후속 구현

수동/자동 재생성, 시도 이력, 실행 시작 기준 횟수 및 중단 처리를 구현했다. 이전 미구현 표기는 이 후속 기록으로 갱신한다. 지원 변경 범위와 검증 결과는 [재생성 구현 보고서](regeneration-validation.md), 계약은 [REST 명세](../api/rest-api.md)를 참조한다. 묶음 검증 기반 흐름은 남아 있다.


## 2026-09-13 묶음 검증 후속

[묶음 검증 구현 및 실제 시험](group-validation.md): 명시적 기준/대상 지정, 선택 재검증, 여러 이미지 provider 호출과 부분 결과 보존을 구현했다. 시스템 기준 자동 선정·생성 완료 자동 감지·대체 이미지 활성 전환/묶음 후속 실행은 아직 남아 있다.


## 2026-09-13 Frontend 탐색 API 구현 반영

그룹·이미지 목록, 작업 관계/state 필터 및 전역 일괄 작업 목록을 구현했다. 앞선 group/image 목록 미구현 표기는 이 기록으로 갱신한다. 전체 155개 테스트와 복사 DB의 HTTP 조회·재시작·DB 무변경 검증을 통과했다. [구현·검증 보고서](core-browse-api.md)와 [REST 명세](../api/rest-api.md)를 따른다. Frontend 화면과 Shared Client 구현 완료를 뜻하지 않는다.
