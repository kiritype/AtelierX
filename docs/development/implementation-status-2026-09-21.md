# 구현 현황과 남은 기능 — 2026-09-21

최신 잔여 작업 분류와 개인 사용 기준 우선순위는 [후속 점검](remaining-work-priorities.md)을 따른다. 아래 과거 표의 Discord 미구현 문구는 현재 상태가 아니다.

> 같은 날 후속 사용자 지시로 [개인용 Discord 봇](discord-personal-bot.md)의 Workers·로컬 전달 서비스·Core 독립 생성/Planner 경로를 추가했다. 아래 표는 해당 착수 전 감사 기준이다. 전체 자연어 도메인 작성 Agent가 완료된 것은 아니며, Discord 실제 배포·앱 연결 상태는 링크된 최신 보고를 따른다.

요구사항·ADR·현재 소스·기존 실행 기록을 대조한 점검이다. 기준은 `codex/documentation-handoff`의 체크포인트 `758ef165c71c3a2fb2519b6468c57740e8905166`에 이번 작업 공간의 후속 복구 수정까지 포함한 상태다. 아직 커밋되지 않은 수정이 있으므로 체크포인트만 checkout한 상태와 같지 않다. 이번 기능 점검에서는 서비스를 재시작하거나 GPU 시험을 추가 실행하지 않았다.

**현재 평가는 사용자가 결과를 확인하는 소규모 개인 제작 가능이다.** Backend 전체 요구 충족이나 무인 대량 운영 준비 완료를 뜻하지 않는다. 아래는 기능 구현 여부이며, 실제 품질·운영 검증은 별도로 구분한다. 미정 상세나 AI 제안을 확정 요구로 바꾸지 않는다.

## 이미 구현된 주요 기능

- Core / Generation / Validation REST, 작업 상태·큐·취소·GPU 조정, 단일/묶음 검사, 재생성 및 기준 revision·결과 이력 보존.
- 작품 > 캐릭터 > 의상, 프롬프트 합성·미리보기, 독립 전역 조각, 여러 고정 그룹의 제작 계획·페이지 조회·내부 실행 창·비교 분할.
- Anima·다중 LoRA, Upscale·Detailer·Censor·Alpha·Encode 파이프라인, Generation의 기존 이미지 독립 후처리 API.
- 생성/후처리 Preset, Validation Profile/Provider 관리, Python API Client·제품 CLI, 제작·갤러리·작업 현황·설정의 Frontend 파일럿.

근거: [REST](../api/rest-api.md), [조각·제작 계획 API](../api/prompt-fragments-production-plans.md), [전역 조각·계획 구현](global-fragments-production-plans.md), [Frontend 개선](frontend-pilot-refinement.md). 과거 문서의 “SDK·CLI·Frontend 미구현”, “재사용 조각 라이브러리 없음”, “Upscale 미구현”은 현재 상태가 아니다.

## 미구현·부분 구현

| 기능 | 현재 상태 | 남은 범위와 근거 |
| --- | --- | --- |
| 자연어 제작·Prompt/도메인 AI 작성 | 미구현·상세 후속 | Validation의 VLM 호출은 존재하지만 제작 요청 해석·도구 호출 Planner는 없다. C-09~12와 [Agent 검토](local-agent-workflow-review.md). Draft/Review/Apply 상세는 Proposed이며 완성된 확정 계약으로 세지 않는다. |
| Discord 봇 | 로드맵 등재·미구현 | Workers 수신/응답, 로컬 LLM adapter, Core 도구 연결, 인증·결과 전달·복구가 필요하다. [요청된 방향과 후속 검토안](../requirements/roadmap.md#discord-자연어-제작-봇--cloudflare-workers). |
| SDXL / Illustrious | 미구현 | 현재 생성 Node/Backend 경로는 Anima 중심이다. SDXL 생성 Node·입력 계약·설치 자원·실제 실행 확인이 필요하다. [Custom Nodes](../../custom_nodes/), [Generation](../../src/atelierx/generation.py). |
| 신체 구조 이상·Metadata 검사 | 미구현 | `body_parts`와 `metadata` 활성 Profile은 거절한다. Prompt에 손/얼굴이 명시된 경우의 일치 검사가 별도 구조 이상 검사를 대신하지 않는다. [Validation 요청 검사](../../src/atelierx/validation.py). |
| Alpha 출력 조건의 Core 자동 연결 | 부분 | Validation 자체에는 채널/투명도 검사가 있지만 Core 검증 요청은 `alpha: not_required`로 고정한다. Alpha 생성 성공과 자동 투명도 요구 검증을 구분해야 한다. [Core 검증 요청](../../src/atelierx/core_validation.py), [Validation](../../src/atelierx/validation.py). |
| Provider별 실행·동시성 | 부분 | 등록/선택과 큐는 존재하나 단일 worker가 전체 후보 중 하나씩 실행한다. Provider별 독립 실행 제어는 남아 있다. 구체 동시성 수치는 미정이며 공유 GPU 직렬화는 유지해야 한다. [worker](../../src/atelierx/validation.py), [ADR-0016](../architecture/adr/0016-validation-execution-and-gpu-sharing.md). |
| Python Client·CLI API 범위 | 부분 | 작업 생성·검증·재생성·취소·그룹 검사·설정 명령은 있다. 제작 계획·전역 조각·분류·Preset·Profile/Provider 관리의 전용 메서드/명령은 없다. Client의 범용 `request`로 REST 호출은 가능하다. [Client](../../src/atelierx/api_client.py), [CLI](../../src/atelierx/cli.py). |
| 독립 후처리의 Core 제작 흐름 편입 | 부분 | Generation API에서 기존 저장 이미지 후처리는 가능하다. Core 접수·결과 카탈로그 등록·외부 이미지 입력을 포함하는 제품 흐름은 별도다. [Generation](../../src/atelierx/generation.py), [Core](../../src/atelierx/core.py). |
| Prompt/설정 이력의 사용자 기능 | 부분·상세 미정 | revision과 실행 snapshot은 존재한다. 전역 설정 전체 이력, Prompt diff·복원 제품 기능은 없다. [Core 저장](../../src/atelierx/core_store.py), [요구 대조표 C-14](../requirements/module-feature-comparison.md). |
| 파일 Metadata·수명주기 | 부분·정책 미정 | DB의 생성 snapshot·이미지 참조·해시 조회는 구현됐다. EXIF/파일 내 Metadata 읽기·보존, 삭제·정리·용량 관리의 전체 흐름은 남아 있다. 보관 정책과 정본 선택은 임의로 확정하지 않는다. [Encode](../../custom_nodes/atelierx_encode/), [저장 경로](output-paths.md). |
| Import/Export·백업/복원 | 미구현·상세 미정 | SQLite 초기화·schema version은 제품 이동/백업 기능이 아니다. DB와 이미지·계획·검증 이력을 함께 복원하는 도구·정책·시험이 필요하다. [Core 저장](../../src/atelierx/core_store.py), [운영 게이트](practical-readiness.md). |
| Frontend 고급 설정·편집 복구 | 부분 | 주요 4개 화면과 기본 폼은 있다. Detailer/Censor/Alpha 고급 설정은 JSON 중심이며 설정 충돌 diff/병합 등 편집 복구 UX는 남아 있다. [설정 화면](../../frontend/settings.js), [파일럿 개선 범위](frontend-pilot-refinement.md). |
| Frontend 모델/파일 관리·실시간 진행 | 부분 | 모델 탐색/다운로드, 일반 이미지 import/삭제, 중간 생성 preview는 파일럿 범위에 없다. 작업 화면은 polling이며 SSE 연결·실제 Node 진행률 표시·모든 초안의 reload 보존은 남아 있다. [파일럿 범위](frontend-pilot.md), [작업 화면](../../frontend/jobs.js). |
| 생성 단계의 캐릭터 동일성 강화 | 부분·기법 미정 | 고정 문구/그룹과 생성 후 일관성 검사는 구현됐다. 참조 이미지 조건부 생성 및 identity 보존 기법·평가 기준은 아직 확정·구현되지 않았다. IP-Adapter/Img2Img를 이미 채택한 의무로 세지 않는다. [로드맵의 현재 목표 구분](../requirements/roadmap.md). |
| 장기 장애 종료·운영 도구 | 부분 | 멱등 접수·재시작·취소 복구를 구현하고 보완했다. 장기 불응답의 종료/사용자 복구 절차, 용량 경고·안전한 정리, 운영 알림·runbook·사용자별 권한은 남아 있다. 실행 불명을 임의 재생성 또는 강제 GPU 해제로 해결하지 않는다. [복구 시험](production-plan-recovery-tests.md), [실사용 준비도](practical-readiness.md). |

## 구현과 별개로 남은 검증

| 범위 | 확보한 근거 | 아직 보장할 수 없는 범위 |
| --- | --- | --- |
| 자동 회귀·격리 장애 | Python 207개·Frontend 17개 통과 기록. 모의 Provider와 실제 SQLite/TCP, Core/Validation 프로세스 중단·재기동 시험 | 이 수치는 실제 GPU 이미지 수나 운영 가용성 수치가 아니다. |
| 실제 생성·GPU 복구 | 한 항목씩 두 격리 계획의 Anima 1024→1536 복구·단일 검사. 첫 시험은 harness 오류 후 수동 복구, 수정본 별도 시험은 성공. 같은 Job과 최종 GPU 반납 확인 | 이번 복구 시험에서 묶음 검사는 수행하지 않았다. ComfyUI 자체 장애, 실제 VLM 실행 중 장애, 장기 GPU 경합은 미검증이다. |
| VLM 품질 | 제한된 실제 이미지의 단일 검사·그룹 비교 수행. 과거 묶음 결과는 외형 차이 등으로 failed | 대표 표본 오탐/미탐·처리량, 전체 품질 합격, 수천 장 무인 운영을 보장하지 않는다. |
| 후처리·외부 Provider | 후처리 실제 실행 및 LM Studio 연동 확인 | Censor 검출률·Alpha 경계·Detailer 개선 품질, 외부 Provider별 고유 기능·실제 호출은 별도다. |
| Frontend 접근성 | 반응형 배치 표본·키보드 상세 열기·인증/timeout 회귀 확인 | 실제 모바일 터치·스크린리더·모든 오류 상태 검증은 완료하지 않았다. |

실행별 근거와 로컬 artifact 위치는 [복구 시험](production-plan-recovery-tests.md), [실사용 준비도](practical-readiness.md), [Frontend 접근성](frontend-accessibility-recovery.md)을 따른다. `.atelierx/`와 `artifacts/`의 DB·모델·이미지·실행 기록은 Git 대상이 아니므로 새 clone에 포함되지 않는다.

## 유예·제외와 다음 순서

Inpaint·ControlNet·Crop·색감·Watermark는 [후속 로드맵](../requirements/roadmap.md) 범위다. LoRA 학습은 현재 범위에서 제외되어 있다. 중복 이미지 검사는 확정적으로 제외됐고 자동 Provider fallback도 도입하지 않는다. 이 항목들을 현재 구현 누락으로 집계하지 않는다.

권장 순서는 운영 준비도 게이트에 맞춰 실제 VLM 장애·GPU 경합·백업/복원과 디스크 부족 대응을 먼저 좁히고, CLI/Client의 제작 계획·조각 지원 및 검사 연결 누락을 보완하는 것이다. Discord 봇은 기존 로컬 Agent 후속 범위와 연결해 Core 도구 계약·Planner GPU 조정·인증된 클라우드 연결부터 구체화한다. 이 순서는 권고이며 미정 제품 정책의 승인이나 봇 즉시 구현 지시로 취급하지 않는다.
