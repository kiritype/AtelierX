# Architecture Decision Records

[ADR-0023: 전역·캐릭터 Negative 역할](0023-negative-prompt-sources.md) — Accepted, 2026-09-13. ADR-0014·0022의 관련 범위 부분 변경.

개별 ADR은 사용자와 하나씩 논의하고, 확정 직후 저장소 문서에 반영한다. 초기 확정 기준선은 [overview](../overview.md)에 있으며, 이를 임의로 여러 개의 Accepted ADR로 재작성하지 않는다.

## 현재 목록

| ADR | 상태 | 확정일 |
| --- | --- | --- |
| [0001: Contribution 워크플로](0001-contribution-workflow.md) | Proposed — 브랜치 흐름·메시지·기본 브랜치·초기화 확정; 리뷰·보호 유예 | 전체 미확정; 부분 결정 2026-09-11 |
| [0002: 생성 및 후처리 Custom Node 기능 범위](0002-custom-node-functional-scope.md) | Accepted — N-01~N-17 검토: 기능·Preset·출력 분리·후속 로드맵 | 2026-09-11 |
| [0003: Generation 실행 계약과 Core 작업 조정·Queue 동기화](0003-generation-execution-and-queue.md) | Accepted — G-01~G-10·Core 조정·Queue; 자동 기본 5회·수동 무제한·횟수 재부여·실행 기준 차감·종료 및 설정 적용 | 2026-09-11; 추가 2026-09-13 |
| [0004: Validation 판정과 실행 오류·재생성 경계](0004-validation-outcomes-and-errors.md) | Accepted — Prompt 기준 불합격·실행 오류 분리, 오류 에러코드·자동 이미지 재생성 금지·수동 재생성 | 2026-09-12 |
| [0005: Validation 응답 구조와 에러코드](0005-validation-response-contract.md) | Proposed — outcome별 응답·초기 에러코드·HTTP 매핑 설계 | 미확정 |
| [0006: Validation 오류 완료 후 수동 재검증](0006-validation-manual-retry.md) | Accepted — outcome=error 이후 자동 검증 재시도 없음·사용자 재검증/수동 재생성·Core 이력 | 2026-09-13 |
| [0007: 단일 이미지와 묶음 이미지 검증](0007-group-image-validation.md) | Accepted — 단일/묶음 분리·중복 제외·선택 재검증·기준 선정/교체 확인 흐름 | 2026-09-13 |
| [0008: 묶음 검증 기준 선정과 비교 부족 처리](0008-group-reference-selection.md) | Accepted — 대표/보조 선정·비교 부족/충돌·추가/기준 삭제·변경 이력 | 2026-09-13 |
| [0009: 묶음 검증 결과와 그룹 요약·사용자 확인](0009-group-validation-results.md) | Accepted — 이미지별 결과·그룹 집계·기준 유효성·부분 오류·확인 중 기준 변경 | 2026-09-13 |
| [0010: 묶음 검증 시작과 그룹 부분 실패·취소](0010-group-completion-and-partial-failure.md) | Accepted — 대상 고정·시작 조건·부분 실패/취소·생성/일관성 현황 분리 | 2026-09-13 |
| [0011: 단일·묶음 검증 입력 정보와 준비 책임](0011-validation-input-context.md) | Accepted — 공통/단일/묶음 입력·최종 이미지·Core 준비·Provider 최소 Context | 2026-09-13 |
| [0012: 검증 이미지 전달·필수 정보·입력 부족 처리](0012-validation-image-transfer-and-required-input.md) | Accepted — 이미지 조회 API/업로드·필수 정보·고정성·접근 오류·부족 정보 처리·정지 PNG/WebP 한정 | 2026-09-13 |
| [0013: 검증 이미지 접근·업로드 제한·임시 파일 관리](0013-validation-access-and-temporary-files.md) | Accepted — 서비스 인증·요청 범위 접근·업로드 제한·임시 정리/이력 보존 | 2026-09-13 |
| [0014: 검사 상세·Validation Profile](0014-validation-checks-and-profiles.md) | Accepted — 단일/묶음 Profile·검사 기본값/순서·복제/수정·사용자 제어 확장 검토 | 2026-09-13 |
| [0015: Validation Provider 설정·지원 기능·Fallback](0015-validation-providers-and-fallback.md) | Accepted — 복수 Provider·단일/묶음 선택·지원 기능·자동 Fallback 없음·테스트 조정 | 2026-09-13 |
| [0016: Validation 비동기 실행·Queue·GPU 공유](0016-validation-execution-and-gpu-sharing.md) | Accepted — 비동기 Job·Provider Queue/기본 동시성 1·취소/복구·Core GPU 조정 | 2026-09-13 |
| [0017: 재생성 변경값 범위·검사·적용](0017-regeneration-change-validation.md) | Accepted — 허용/제외·의도 보존·최소 변경·일괄 적용·3서비스 검사 책임 | 2026-09-13 |
| [0018: 묶음 검증 변경과 운영 예외](0018-group-validation-change-handling.md) | Accepted — 기준/대상 변경·유효성·불확실성·추적 | 2026-09-13 |
| [0019: Validation 초기 API·저장·운영 설계](0019-validation-contract-and-operational-draft.md) | Proposed — 사용자 위임으로 상세 설계·테스트값 작성 | 미확정 |
| [0020: 검증 접수·변경·취소·결과 보존 예외](0020-job-request-and-result-races.md) | Accepted — 중복/응답 유실·취소 경합·과거 결과/이력 보존 | 2026-09-13 |
| [0021: 작품·캐릭터·외형·의상 관계와 이미지 그룹](0021-core-domain-and-image-groups.md) | Accepted — 작품 > 캐릭터 > 의상; 전역 Positive/Negative·의상 내부 3구분·보관·그룹 고정 | 2026-09-13 |
| [0022: 전역·의상 Prompt 조합](0022-prompt-composition.md) | Accepted — 조합 순서·전역 Negative·내용 보존·충돌 안내·최종 문구 고정 | 2026-09-13 |

[backlog](backlog.md)는 논의 후보 목록이며 ADR 승인 기록이 아니다. [template](template.md)을 사용해 논의할 ADR의 초안을 작성할 수 있다.

## 기록 규칙

scaffold의 문서 관리 관례로 `NNNN-short-title.md` 형식을 사용한다. 번호는 ADR 초안을 실제로 작성할 때 부여하며 backlog 순서는 승인 순서를 뜻하지 않는다.

| 상태 | 의미 |
| --- | --- |
| Proposed | 논의 중인 초안. 구현 근거로 사용하지 않음 |
| Accepted | 사용자가 명시적으로 확정한 결정 |
| Rejected | 검토 후 채택하지 않은 제안. 사유 보존 |
| Superseded | 후속 Accepted ADR에 의해 대체된 결정. 대체 관계 보존 |

TODO 질문은 backlog에 둔다. Accepted에는 확정일과 결론을 기록한다. 승인되지 않은 세부 사항을 한 ADR에 묶어 승인된 것으로 취급하지 않는다.

## 확정 시 수행할 작업

1. 해당 ADR 파일의 상태, 확정일, 결정 및 영향을 기록한다.
2. [overview](../overview.md)에 현재 결론과 ADR 링크를 반영한다.
3. 기존 ADR과 초기 확정 기준선의 충돌 여부를 확인하고 해당 ADR에 결과를 기록한다.
4. 기존 결정을 대체하면 이전 ADR을 Superseded로 표시하고 양쪽에 `Supersedes` / `Superseded by` 링크를 기록한다. 일부만 바꾸면 대체 범위와 유지되는 결정을 명시한다.
5. 이 목록에 ADR 링크와 상태를 추가하고, backlog 및 관련 요구사항·모듈 문서를 갱신한다.
6. 미결정 사항은 Proposed / TODO로 유지한다. ADR 확정만으로 제품 구현을 시작하지 않는다.

기존 ADR이 없는 초기 기준선을 변경하는 경우에는 어떤 기준선을 변경했는지 기록한다. 존재하지 않는 이전 ADR을 만들어 대체 관계를 꾸미지 않는다.
