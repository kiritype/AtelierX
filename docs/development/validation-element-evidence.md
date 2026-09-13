# Prompt 항목별 근거 검증 — 평가 방식 v2

2026-09-13 사용자 지시: LM Studio 검증에서 화면 밖 부츠를 잘못 합격시킨 사례를 보완하고 재평가했다. ADR-0004의 합격/불합격/오류 원칙을 구현에 반영한 것으로 기준을 변경하지 않는다.

## 변경

이전에는 모델이 최종 outcome과 findings를 만들었다. 이제 Validation이 요청 Prompt의 모든 항목에 ID를 부여하고, 모델은 각 항목의 상태·관찰 근거·이미지 내 위치를 반환한다. 최종 판정과 재생성 제안 여부는 Validation이 집계한다.

- Positive: `matched`, `not_visible`, `mismatch`, `uncertain`.
- `not_visible`: 누락·가림·화면 밖을 포함한다. 하나라도 있으면 불합격이다.
- Negative: 금지 요소가 없으면 `matched`, 있으면 `mismatch`. Negative의 `not_visible`은 계약 오류다.
- 모델이 `uncertain`을 반환하면 `VAL_PROVIDER_INCONCLUSIVE` 실행 오류로 기록하고 자동 재생성을 요구하지 않는다.
- 요청한 ID가 빠지거나 중복/추가되거나 관찰 근거가 비면 `VAL_PROVIDER_RESPONSE_INVALID`다. 일부 항목만 확인한 결과로 합격시키지 않는다.
- 각 요청은 Provider 호출 한 번으로 처리한다. 오류 후 재전송·자동 Fallback은 없다.

항목 분리는 괄호 밖 쉼표와 줄바꿈을 기준으로 한다. 가중치·괄호 내 표현·순서·중복을 보존하고 원래 생성 Prompt는 변경하지 않는다. 복합 문장은 한 항목으로 유지하며 그 안의 모든 요소를 관찰하도록 지시한다. 이는 완전한 자연어 의미 분해기가 아니며, 복잡한 문장과 가중치 표현은 후속 평가 대상이다. 품질/스타일 표현도 임의로 생략하지 않는다.

`result.evidence`에는 원문 항목, ID, Positive/Negative 구분, 상태, observed, location이 남는다. `result.findings` 및 기존 outcome/regeneration 구조는 유지한다. 새 Job에는 `evaluation_version=2`를 저장한다. 실행 전 평가 버전이 바뀐 과거 대기 Job은 새 방식으로 몰래 실행하지 않고 오류로 종료하며, 완료 이력은 보존한다.

## 실제 LM Studio 재평가

모델: `qwen3-vl-8b-instruct-abliterated`. 입력은 이전과 같은 768×1024 상반신 이미지다. 실제 생성 Prompt 한 건과 인위적으로 만든 진단 Prompt 네 건을 비교했다. 진단 Prompt는 원래 Core 이력을 변경하지 않는다.

| 사례 | 이전 | 변경 후 |
| --- | --- | --- |
| 실제 생성 Prompt | 합격 | 합격 — 14개 항목 근거 반환 |
| 머리색·눈색을 다른 색으로 요구 | 불합격 | 불합격 |
| 화면 밖 검은 부츠 요구 | **오판: 합격** | **불합격: not_visible** |
| 없는 빨간 우산을 들고 있도록 요구 | 미실행 | 불합격: not_visible |
| 실제 보이는 머리핀을 Negative에 추가 | 미실행 | 불합격: negative_prompt_mismatch |

기존 세 사례의 응답 시간은 약 12~14초였다. 이전의 5~6초보다 늘었으며, 항목별 근거를 생성하는 비용이다. 관찰 근거가 추가됐다고 모델의 시각 판단 자체가 정확해지는 것은 아니므로 다른 이미지·구도·복합 Prompt로 일반화 검증이 필요하다. 이번 결과는 동일 이미지의 다섯 조건에 대한 초기 회귀 검증이다.

- 기존 세 사례: `artifacts/lmstudio-validation/20260913-044947/report.json`
- 추가 두 사례: `artifacts/lmstudio-validation/20260913-045106/report.json`
- 스크립트: `scripts/test_lmstudio_validation.py`. 필요한 사례만 `--cases diagnostic-missing-prop,diagnostic-prohibited-hairpin`처럼 선택할 수 있다.
- 백엔드 테스트 36개 통과. 누락 항목 불합격, 근거 ID 누락/중복/추가 오류, 불확실 오류, Negative 위반, 가중치 보존·검사 Off 경계를 추가 검사했다.

새 이미지 생성이나 자동 재생성은 실행하지 않았다. 다음 단계는 서로 다른 이미지에서 가림·구도·작은 장식·복합 문장 등의 정확도와 오탐을 평가하는 것이다.

## 추가 이미지 평가

[다른 이미지·구도 평가](validation-generalization.md): 신규 평가 이미지 2장, 조건 9건 중 기대 일치 8건·오탐 1건. 복합 항목에서 작은 귀걸이를 놓치는 문제가 남았다.

## 가중치 묶음 분리 후속 변경

[평가 v3와 실제 회귀 결과](validation-weighted-groups.md): 원문·가중치를 보존하며 괄호 묶음을 개별 요구로 분리했다. 기존 귀걸이 오탐을 포함한 동일 9개 조건이 이번 실행에서 모두 기대와 일치했다.
