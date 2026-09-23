# ADR-0027: 참조 세트와 생성 일관성 방식

- 상태: Proposed
- 작성일: 2026-09-23
- 확정일: 미확정
- Supersedes: 없음
- Superseded by: 없음
- 관련 요구사항 / ADR: [roadmap 참조 이미지 절·실험 1~4](../../requirements/roadmap.md), [현행 정책 §3](../../policies.md), [ADR-0003](0003-generation-execution-and-queue.md), [ADR-0007](0007-group-image-validation.md), [ADR-0012](0012-validation-image-transfer-and-required-input.md), [ADR-0021](0021-core-domain-and-image-groups.md), [ADR-0022](0022-prompt-composition.md), [ADR-0023](0023-negative-prompt-sources.md), [ADR-0025](0025-validation-check-scope.md)

## 결정할 질문

캐릭터+의상별 **참조 세트**를 어떻게 만들고 확정·보관하며, 제작 생성에 **일관성 방식**(현재 Anima In-Context Character)을 어떤 설정·계약으로 적용할지 정한다.

## 배경과 제약

### 이미 확정된 사용자 결정 (2026-09-23, [policies §3](../../policies.md))

- TO-BE 흐름: 캐릭터·의상 → 조각 → 참조 샘플 생성·사용자 확정 → 제작 생성에 참조 조건 추가 → VLM 검증 → 재생성.
- 샘플은 자동화하지 않는다. 고정 구도 템플릿(흰 배경)에서 사용자가 Seed·Prompt를 바꿔 직접 고른다.
- 참조 세트는 의상 revision과 연계해 수정 시 재확인 필요를 표시하고, 생성 이미지에 사용한 세트를 기록한다. 이력·보관 조회 화면은 UI/UX 리팩토링 때 구현한다.
- 참조 없는 생성은 참조 샘플 생성과 단일 이미지 생성 화면에서만 허용한다. 제작 계획은 확정된 참조 세트가 없으면 Core가 거절한다.
- 참조 조건은 Generation의 교체 가능한 단계로 둔다.
- In-Context가 효과 있으면 제작 시 그룹 일관성 검증은 끈다.
- 사용자 방향(2026-09-23, 이 ADR 논의 중): 생성 설정에서 **일관성 방식**을 선택하고(현재는 `anima-incontext-character` 하나), 선택한 방식의 `strength`·`end_percent`를 지정한다. 참조는 기본 2장(전신·얼굴)이 가장 좋다고 판단했다.

### 실험 근거 (roadmap 실험 1~4, 캐릭터 2~3명·Seed 1~3개 한정)

- 참조를 제작과 **같은 설정**(모델·품질·화가 공통 조각)으로 만들면 그림체가 유지된다. 설정이 다르면 참조 쪽 그림체로 끌린다(실험 1).
- 참조 2장은 의상·액세서리 유지가 가장 좋다. 4장은 테두리 선 결함과 2.3배 시간 비용이 있다(실험 1).
- In-Context LoRA만 적용하고 참조가 없으면 오히려 의상이 흔들린다(실험 2).
- 흰 배경 참조는 결과 배경을 하얗게 끌어당기며, 결과 Negative에 `white background, simple background`를 더하면 해소된다(실험 3·4).
- `end_percent` 0.5는 1.0과 결과가 거의 같고 시간은 약 60%(장당 약 30초, 참조 없음 약 9초). 0.4 이하는 일부 Seed에서 의상 색이 흔들린다(실험 4).
- 현재 VLM 단일 검사는 조건 간 차이를 거의 구분하지 못한다(실험 1).

### 기술 제약

- 현재 `AtelierXAnimaGenerate` Node는 모델 로드·샘플링을 한 Node에서 수행하고 참조 입력이 없다.
- In-Context 방식은 외부 Node 팩(`comfyui-anima-incontext`, 비상업 라이선스 LoRA)에 의존하며 Anima 전용이다.
- 참조 후보 이미지는 Core 이미지이며 실제 파일은 Generation 저장소에 있다. Generation은 이미 저장 이미지 ID·SHA-256으로 `LoadImage`를 구성하는 독립 후처리 경로를 갖고 있다.

## 검토한 대안

### 1. 참조 세트의 소속

| 대안 | 장점 | 단점 |
| --- | --- | --- |
| A. 의상 단위(현재 revision을 기록) | 사용자가 떠올리는 단위와 같음. 의상 수정 시 재확인 판정이 단순 | 같은 의상의 여러 그룹이 같은 세트를 공유 |
| B. 이미지 그룹 단위 | 그룹이 이미 외형·의상 구성을 고정(ADR-0021) | 그룹을 새로 만들 때마다 참조를 다시 확정해야 함 |

### 2. 일관성 방식의 적용 위치(Generation 구현)

| 대안 | 장점 | 단점 |
| --- | --- | --- |
| A. `AtelierXAnimaGenerate`에 선택 입력(참조 이미지·방식·설정) 추가, 방식별 처리 함수를 내부에서 호출 | 기존 Node·REST 계약 확장만으로 해결. 모델 1회 로드 | 외부 Node 팩 모듈을 import하는 결합 |
| B. Node를 로더/샘플러로 분해해 Graph에 방식별 Node 체인 삽입 | 방식 교체가 Graph 수준에서 명확 | 기존 Node·Preset·Workflow 계약 전면 변경 |

## 제안

### P1. 참조 세트 구성과 확정

- 참조 세트는 **의상 단위**로 두고(대안 1-A), 확정 당시 캐릭터·의상 revision을 기록한다.
- 구성: **전신 1장 + 얼굴 1장(필수)**. 옆·뒷모습은 이번 범위에 두지 않는다(실험상 이점 없음, 뒷모습 템플릿 품질 낮음).
- 샘플 생성은 Core의 참조 샘플 전용 Task로 수행한다. 고정 구도 템플릿(전신: `full body, standing, straight-on, front view, looking at viewer, arms at sides, white background, simple background` / 얼굴: `portrait, close-up, face focus, straight-on, looking at viewer, white background, simple background`)과 사용자가 고른 생성 설정·공통 조각을 쓴다. 같은 Seed로 전신·얼굴 **쌍**을 생성한다. 템플릿 문구는 설정에서 바꿀 수 있게 한다.
- 사용자가 후보 중 전신·얼굴을 골라 확정하면 세트 revision이 올라가고 이전 확정 세트는 보관된다(삭제 없음).
- 세트에는 샘플을 만든 생성 설정 요약(모델·인코더·공통 조각 revision)을 기록한다. 제작 계획 설정과 다르면 **경고**한다(그림체 끌림 근거, 차단하지 않음).

### P2. 재확인 필요 판정

- 세트의 기록 revision과 현재 캐릭터·의상 revision이 다르면 `needs_review`로 표시한다.
- 사용자는 이미지를 다시 만들지 않고 "변경 확인 후 유지"로 현재 revision에 다시 확정하거나, 새 샘플로 교체할 수 있다.
- `needs_review` 세트로는 새 제작 계획을 접수하지 않는다(확정 세트 없음과 같게 취급).

### P3. 일관성 방식과 설정

- 생성 설정에 `consistency: {method, params}`를 둔다. 방식 목록은 Generation 자원 조회가 `{id, 지원 모델 계열, params 형식·범위·기본값}`으로 제공하고 Frontend는 이를 폼으로 그린다.
- 현재 방식 `anima-incontext-character`의 params:

| param | 기본 | 허용 범위 | 비고 |
| --- | --- | --- | --- |
| `strength` | 1.0 | 0.5~1.5 | Node 허용 0~10 중 의미 있는 범위 |
| `end_percent` | 0.5 | 0.3~1.0 | 0.5 미만 선택 시 의상 색 흔들림 경고 |
| `suppress_reference_background` | true | bool | 결과 Negative에 `white background, simple background` 추가 |

- 고정값(노출하지 않음): `start_percent` 0, In-Context LoRA 강도 1.0, `cond_only` true, `fit_mode` pad. 참조 이미지는 생성 해상도에 흰 여백으로 맞춘다.
- 제작 계획의 생성 설정과 Preset에 저장한다. 선택 방식·params·참조 세트 ID/revision·참조 이미지 ID/SHA-256을 Task snapshot에 고정하며 재생성은 snapshot 값을 그대로 쓴다.
- Generation은 모델 계열과 방식 호환성, 필요 Node·LoRA 등록을 검사하고 불일치를 오류로 거절한다.

### P4. 배경 억제 Negative의 출처

- `suppress_reference_background`로 추가되는 문구는 `negative_sources`에 새 출처(예: `consistency`)로 기록한다. 생성에는 사용하고 Validation의 캐릭터 Negative 검사 대상에는 넣지 않는다(ADR-0023의 global과 같은 취급).

### P5. 제작 계획 강제와 예외

- 새 제작 계획은 대상 의상 전부에 유효한 확정 세트가 있어야 한다. 없거나 `needs_review`면 Core가 해당 의상 목록과 함께 거절한다.
- 예외: 참조 샘플 Task, 단일 이미지 생성(후속 화면), 참조 도입 이전 snapshot의 재생성(원래 snapshot 유지).
- 기존 개별 Task API(`POST /v1/tasks`, 조각 Task)의 신규 생성도 같은 규칙을 적용한다.

### P6. 그룹 일관성(묶음) 검증

- 제작 계획의 검사 선택 기본값을 **단일 검사**로 바꾼다. 묶음 검사(`single_group`) 옵션은 제거하지 않고 선택으로 남긴다(참조와의 비교 검사로 대체하는 설계는 후속).

### P7. Generation 구현과 이미지 전달

- 대안 2-A: `AtelierXAnimaGenerate`에 선택 입력을 추가하고, 방식별 처리는 Generation 내부 레지스트리로 분리한다. 방식이 늘면 레지스트리 항목과 Node 처리 함수를 추가한다.
- Core는 참조 이미지의 **Generation 이미지 ID와 SHA-256**을 생성 입력으로 보내고, Generation은 저장 파일을 무결성 확인 후 ComfyUI 입력으로 올린다(독립 후처리와 같은 방식). 참조가 다른 Generation 서버의 이미지면 오류로 거절한다(분산 참조 전달은 후속).
- 제작 계획 화면의 예상 시간은 방식별 계수(현재 약 3.3배, 실측 갱신)로 표시한다.

## 영향과 트레이드오프

- 제작 생성 시간이 장당 약 9초에서 약 30초로 늘어난다(1,000장 기준 약 2.5시간 → 약 8.3시간).
- VRAM이 약 1.5GB 늘어난다(실측 최대 약 9.4GB).
- 외부 Node 팩과 비상업 라이선스 LoRA에 의존한다. 설치 안내·의존성 점검에 포함해야 하며 모델 재배포는 하지 않는다.
- 캐릭터·의상 수정마다 참조 재확인 부담이 생긴다(P2의 "변경 확인 후 유지"로 완화).
- 근거는 캐릭터 2~3명·Seed 1~3개다. 구현 후 첫 실제 제작 계획은 작게 시작해 확인한다.
- 몸을 가리는 포즈·크롭탑 길이 등은 참조로 해결되지 않았다. Prompt·조각 Negative 쪽 과제다.

## 이번에 결정하지 않는 사항

- 참조 세트와의 비교를 이용한 Validation 검사(묶음 검사 대체).
- 옆·뒷모습 참조, IP-Adapter 등 다른 방식, Illustrious 계열 지원.
- 분산 Generation 서버 간 참조 이미지 전달.
- 참조 세트 이력·보관 조회 화면(UI/UX 리팩토링 때).
- 단일 이미지 생성 화면(F15, 별도 진행).

## 충돌 및 대체 확인

- ADR-0021: 그룹의 외형·의상 고정 원칙은 유지한다. 참조 세트는 의상 단위이며 그룹 구성을 바꾸지 않는다.
- ADR-0003: 실행 입력 고정 원칙에 따라 방식·params·참조를 snapshot에 고정한다. 충돌 없음.
- ADR-0007·0010: 묶음 검증 자체는 유지하며 제작 계획의 기본 선택만 바꾼다(P6). 확정 시 해당 ADR에 기본값 변경을 기록한다.
- ADR-0012: 서비스 간 이미지 전달은 조회 API 원칙을 따르되, 이번 범위는 같은 Generation 저장 이미지로 한정한다.
- ADR-0023: Negative 출처에 `consistency`를 추가한다(P4). global·character 규칙은 유지한다.
- ADR-0025: 검사 범위 변경 없음.

## 확인 요청 (한 번에 확인)

| # | 항목 | 제안 |
| --- | --- | --- |
| 1 | 참조 세트 소속 | 의상 단위(P1) |
| 2 | 세트 구성 | 전신+얼굴 필수, 옆·뒷모습 제외 |
| 3 | 샘플 생성 | 같은 Seed 전신·얼굴 쌍, 템플릿 문구 설정 변경 가능 |
| 4 | 생성 설정 불일치 | 경고만(차단 안 함) |
| 5 | 재확인 필요 | revision 변경 시 `needs_review`, "변경 확인 후 유지" 허용, 제작 계획 거절 |
| 6 | 방식 params | strength 1.0(0.5~1.5), end_percent 0.5(0.3~1.0, 0.5 미만 경고), 배경 억제 기본 켬 |
| 7 | 배경 억제 출처 | `consistency` 출처, 검사 제외 |
| 8 | 강제 범위 | 제작 계획 + 신규 개별 Task. 샘플·단일 생성·과거 snapshot 재생성은 예외 |
| 9 | 묶음 검사 | 기본값을 단일 검사로, 옵션은 유지 |
| 10 | Generation 구현 | 기존 Node 확장 + 방식 레지스트리(2-A), 같은 Generation 서버 이미지 한정 |

## 문서 반영

- [ ] overview 갱신
- [ ] ADR 목록 및 backlog 갱신
- [ ] 관련 요구사항 / 모듈 / 개발 문서 갱신 또는 해당 없음 기록
- [ ] 기존 ADR 상태 및 supersede 관계 확인
- [ ] 미결정 사항이 확정 내용에 섞이지 않았는지 확인
