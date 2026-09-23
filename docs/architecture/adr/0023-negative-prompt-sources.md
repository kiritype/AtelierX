# ADR-0023: 전역·캐릭터 Negative 역할

- 상태: Accepted
- 확정일: 2026-09-13
- 근거: 사용자의 전역 품질/캐릭터 금지 요소 분리 제안과 권고안 진행 승인.
- 부분 변경: ADR-0014 검사 범위·ADR-0022 조합. 두 ADR은 Accepted 유지, 전체 supersede 없음.
- 2026-09-23 [ADR-0027](0027-reference-sets-and-consistency-methods.md): 일관성 방식의 배경 억제 문구를 `consistency` 출처로 추가한다. 생성에 사용하고 검사하지 않는다(global과 같은 취급). global·character 규칙은 유지.

전역 Negative는 생성 전용이며 내용에 관계없이 불합격 근거에서 제외한다. 캐릭터별 Negative는 모든 의상에 공통인 관찰 가능한 금지 요소로, 생성에 사용하며 이미지에 나타나면 불합격이다. 추상 품질 문구는 전역으로 안내하고 Positive와 확인 가능한 충돌은 생성 전에 안내한다. 자연어 전체의 의미/동의어/모순 탐지를 보장하지 않는다.

Core가 전역 → 캐릭터 순으로 합성하고 실제 문구·출처별 원문·캐릭터 revision을 시도에 고정한다. 편집은 새 요청부터 적용하고 이전 결과는 보존한다. 기존 그룹의 의상 고정은 유지하며 캐릭터 Negative는 새 생성 시점의 설정을 별도 고정한다. Validation은 합성 일치를 확인하고 캐릭터 Negative만 AI에 검사 대상으로 전달한다. 전역 Positive 규칙은 변경하지 않는다.

초기 계약은 캐릭터 `negative_prompt`, snapshot `negative_sources: {global, character}`, `composition_version=2`, `evaluation_version=4`다. 기존 캐릭터 필드 누락은 빈 문자열, 기존 생성 snapshot은 전체 Negative가 전역이었던 기록으로 해석한다. 직접 Validation 요청에서 출처 생략 시 전체를 전역으로 취급한다. 기존 판정은 재작성하지 않는다. 초기 입력 안내는 대표 추상 품질 용어 목록과 정확한 항목 일치 충돌 검사이며 의미 분석 확장은 후속이다.

ADR-0004·0006·0017·0020의 판정·오류 후 자동 재시도 금지·원본 보존·중복 요청 보호와 대조하여 충돌 없음. [API 명세](../../api/rest-api.md) 및 overview·ADR 목록/backlog·요구사항·모듈에 반영한다.
