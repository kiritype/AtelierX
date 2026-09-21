# Frontend 파일럿 폼 개선·묶음 회귀

2026-09-13 후속 작업. 기존 [파일럿](frontend-pilot.md)의 고급 JSON 입력을 일반 폼으로 확장하고 실제 묶음 흐름을 확인한다. 제품 정책을 변경하는 새 ADR이 아니라 기존 API의 입력·표시 개선이다.

## 변경 목표와 책임

- 작업 현황: 그룹·생성/후처리 Preset·단일/묶음 검사 설정 선택, 구도·표정·동작·상황 행 추가/삭제, 각 행 Core preview 후 Batch 접수. 기준 후보 조회와 기준 저장·재개를 명시적 동작으로 유지한다.
- 갤러리: 등록된 검사 설정과 적격 기준·대상을 선택하고 단일/묶음 요청을 보낸다. 미검증·오류·이전 기준 결과를 현재 합격처럼 표시하지 않는다.
- 설정: 일반 필드 편집과 고급 JSON을 구분하고, 초안과 해당 원본 revision을 함께 보존한다. 서버 revision이 달라져도 사용자 초안을 최신 revision으로 자동 덮어쓰지 않는다.
- UI는 REST 요청만 작성한다. 자동 재생성·검증·그룹 집계는 Core가 수행한다. 요청 응답 유실 시 같은 키/내용을 유지한다.

## 실환경 시험 범위

기존 파일럿 데이터는 보존하고 별도 비교 그룹을 만들었다. 시험은 PNG 2장, Anima 생성 1024×1024, UltraSharp 최종 1536×1536을 사용한다. 시험 대상 cycle에서 자동 재생성이 반복되지 않도록 접수 시 파일럿 전역 자동 재생성을 잠시 끄고, 접수 snapshot 고정 후 원래 설정으로 복원한다. 설정을 복원해도 시험 cycle에 소급 적용하지 않는다.

진행 중 기록은 `artifacts/frontend-pilot/batch-settings-before.json`, `batch-settings-test.json`, `batch-group.json`에 보존한다. 기존 ComfyUI 작업을 중단하거나 서버를 재시작하지 않는다. 실제 판정은 시험 완료 후 기록하며 통신 오류·미검증을 성공으로 합산하지 않는다.


## 구현·검증 결과

일괄 생성과 갤러리 검사 입력을 일반 선택 폼으로 전환했다. 설정은 생성/후처리 Preset·Profile·Provider 일반 필드를 제공하고 고급 JSON을 보조로 유지한다. 후처리의 미노출 Detailer/Censor/Alpha와 Provider의 기존 비밀 아닌 설정 참조를 보존한다. 요청 경합·중복 클릭·메뉴 이동 초기 상세·Blob URL 해제도 보완했다.

실제 브라우저에서 두 행 접수 → PNG 생성/단일 검증 → 기준 확인 대기 → 대표 이미지 저장 → 별도 Batch 재개 → 묶음 결과까지 실행했다.

- Batch: `511d521f-1895-46cb-b9d6-eefc6db5cf0d`, Group: `a7025e31-a5a9-4611-9ee9-3b5bc4ee7367`.
- 표정: gentle smile / thoughtful expression, 생성 1024 및 후처리 1536 PNG 두 장. **단일 검사 두 장 모두 passed**.
- 기준 저장 후에도 Batch는 `awaiting_reference_confirmation`을 유지했다. 별도 확인 동작 후 Group Run `5a441e6c-94b6-4ba2-af20-d5fa66866d57`를 실행했다.
- Batch 실행 상태는 **completed**, 묶음 outcome은 **incomplete**다. 대상 한 장의 외형·상의는 matched, 하의는 상반신 구도에서 보이지 않아 insufficient다. 묶음 합격으로 보고하지 않는다. 추가 비교 자료 확보 여부는 후속 사용자 검토 사항이다.
- 자동 재생성 Off는 시험 두 cycle에 고정했고 접수 직후 전역 On·상한 5를 복원했다. 새 설정 변경을 과거 cycle에 소급하지 않았다. 추가 재생성·Provider fallback은 실행하지 않았다.
- 설정 초안을 편집한 뒤 서버에 동일 값 revision 갱신을 수행해 충돌을 만들었다. category 이동 후에도 초안의 원래 revision 4가 유지됐고 저장은 409로 거절됐다. 사용자 초안과 서버 값을 보존했으며 명시적 최신값 불러오기로 시험 초안을 해제했다. 실제 품질 Positive는 `masterpiece, best quality` 그대로다.

Python 전체 174개 테스트가 24.122초에 통과했다. Node의 API·묶음 입력·갤러리 선택·설정 변환 테스트와 구문 검사를 통과했다. 결과 파일은 `artifacts/frontend-pilot/batch-report.json`, 전체 로그는 `artifacts/full-suite/frontend-refinement.log`다. GPU owner/waiting이 빈 상태로 종료된 것을 확인했다.

## 남은 범위

후속 배치·접근성·오류 복구 결과와 남은 한계는 [검증 기록](frontend-accessibility-recovery.md)을 참고한다.

모바일 전체 화면·접근성 점검, 모델 목록과 분류 ID의 사용자용 이름 탐색, 설정 충돌의 차이 비교 UI는 남아 있다. 고급 JSON에서의 초안 복구와 모든 오류 조합을 검증했다고 보장하지 않는다. 이번 완료는 일반 폼 및 실제 묶음 흐름의 회귀이며, VLM 일관성 품질 전체 완료를 뜻하지 않는다.

## 선택 이미지 교체 실환경 검증 — 2026-09-13

갤러리의 일반 선택 폼에서 교체 재생성을 접수하고 Generation → 단일 Validation → 묶음 Validation의 완료를 확인했다. 기존 이미지와 기준 revision 1은 보존했다.

- Replacement `ec377f52-5091-4468-bc47-51379a32b3a1`: completed, 시도 Task는 1개다.
- Task `5df9216a-89ba-44bf-bc74-be99e30ba329`: generated. 1024 생성 후 UltraSharp 1.5배 후처리로 PNG 1536×1536을 저장했다.
- 단일 Run `347596b7-7c95-459f-8059-8c5180d2a62e`: passed.
- 새 이미지 `4a41d1e6-1419-409f-9514-a0c5d765efe9`가 현재 target으로 전환됐고, 이전 `9a84e8f0-f0a7-4d0e-91c7-7cbdea5b3c10`은 보존되며 not_eligible로 표시된다.
- 묶음 Run `6a049225-ed72-4f43-869b-d71e5e374893`: completed / incomplete. 외형·상의 matched, 대상의 하의가 보이지 않아 insufficient다. 교체 완료와 묶음 합격을 구분한다. Provider 관찰 문구의 사실성까지 검증한 결과는 아니다.
- 시험 snapshot에만 자동 재생성 Off를 고정했다. 전역 설정은 접수 직후 On·상한 5로 복원했고, GPU owner/waiting은 완료 후 비었다.

교체 선택을 Core의 현재 target_ids로 제한하고, 교체 진행 패널에 원본·새 이미지·Task 및 Run ID와 결과 이미지/작업 열기를 추가했다. 작업 상세 응답 경합, 취소·기준 확인 중복 클릭 방지, 오류와 부분 결과 표시도 보완했다.

Python 전체 174개 테스트가 23.377초에 통과했다. Node API·작업 현황·갤러리·설정 회귀 테스트 및 diff 검사가 통과했다. 원본 결과는 `artifacts/frontend-pilot/replacement-report.json`, 로그는 `artifacts/full-suite/frontend-replacement.log`에 보관한다. 출력 파일은 `.atelierx/pilot/generation/images/93f257f7-bb7c-4683-a920-b692f96b9723-0.png`다.
