# Prompt 조각과 일괄 생성 검토

2026-09-13 최신 사용자 정정: 조각 기반 제작에서는 **외형을 항상 포함**한다. 전역 공유 조각은 본문과 **상의·하의 포함 여부만** 저장하며 appearance 선택 필드는 두지 않는다. 아래 과거 조각별 외형 선택 설명을 대체한다. 전역 Positive + 외형 + 선택한 상의/하의 + 조각 본문, 전역 Negative + 캐릭터 Negative를 사용한다. 구현·테스트를 계속 진행하도록 승인됐다.


**최우선 후속 확정:** 조각은 캐릭터 소속/연결 방식이 아니라 작품·캐릭터·의상과 독립된 전역 공유 라이브러리다. 외형·상의·하의 포함 여부는 조각마다 지정한다. 아래 이전 연결 모델과 공통 Prompt 권고는 [최신 flow의 최우선 확정](batch-production-flow-review.md)으로 대체한다.

**최신 조합 정정:** 기본 구도 1개와 표정·동작 묶음을 사용하며 단일 조각 모델도 허용됐다. 독립 구도×표정×동작 전개를 기본으로 삼지 않는다. 수천 개 일괄 Queue 접수 요구와 갱신 권고는 [최신 flow](batch-production-flow-review.md)를 따른다.

**후속 정정 — 2026-09-13:** 사용자가 대량 제작의 개수 상한 없음(32개 초과 포함)과 사용자 작성 조각의 체크 선택을 명시했다. 아래 최초 검토의 32개 초과 거절 권고와 이를 제품 결정으로 남긴 항목은 폐기한다. 현재 코드의 32개 제한은 미해결 구현 제약일 뿐이다. 최신 흐름은 [대량 제작 flow 재검토](batch-production-flow-review.md)를 따른다. 아래는 최초 검토 이력이다.

기록일: 2026-09-13. 이 문서는 금일 사용자 요청에 따른 **구현 전 검토**다. 새 API, 저장 모델, 프롬프트 문법, 자동 실행 정책을 확정하거나 구현한 기록이 아니다.

## 검토한 현재 동작

Core는 이미 고정 group을 입력으로 단일 Task를 preview하고 접수한다. `Core.preview()`는 전역 품질, group의 appearance/upper/lower, framing, expression/action/situation을 조합하고, 선택한 preset·검증 selection·negative 출처를 snapshot에 복사한다. `preview_hash`는 그 snapshot의 canonical hash이고, submit은 사용자가 보낸 hash가 현재 preview와 다르면 `CORE_PREVIEW_STALE`로 거절한다. 따라서 대량 모드도 각 실제 조합의 preview/snapshot을 먼저 만든 뒤 그 결과를 고정해야 한다. [core.py](../../src/atelierx/core.py)의 `preview`와 `submit`이 이 경계다.

`CoreBatches.submit()`은 같은 group의 1..32개 item만 받으며, 각 item에 단일 validation을 요구하고 각 item별 preview hash를 다시 확인한다. 생성 → 단일 validation/유한 자동 regeneration cycle → 통과 이미지 집계 뒤에만 group validation을 시작한다. 기준이 없으면 후보만 제시하거나 `awaiting_reference_confirmation`으로 멈추며, 기준을 자동 저장하지 않는다. 기준 변경에는 재확인이 필요하다. 단일 오류·불합격·취소는 item summary에 남고, 묶음 비교 대상이 부족하면 `insufficient_images`로 끝난다. 이 흐름은 [core_batches.py](../../src/atelierx/core_batches.py)와 [group-batches.md](group-batches.md)에 구현·기록돼 있다.

Jobs 화면은 Task, validation run, group batch를 조회·취소·상세 표시하는 thin client다. prompt 조합이나 Cartesian expansion을 자체 수행하지 않는다. 새 대량 제작 화면도 이 원칙을 유지해야 한다.

## 외부 참고의 범위

[ComfyUI-AssetManager README](https://github.com/kiritype/ComfyUI-AssetManager)는 작품 > 그룹 > 조각 라이브러리, 다중 선택한 태그의 Cartesian queue, `requires`에 따른 표시 제어를 소개한다. 이는 선택 UI와 사전 조합 수 표시의 참고가 된다. 그러나 이 프로젝트는 ComfyUI 플러그인의 JSON 자동 저장·파일 기반 라이브러리와 직접 연결하지 않으며, AtelierX Core SQLite 또는 Core REST를 우회하지 않는다.

[sd-dynamic-prompts README](https://github.com/adieyal/sd-dynamic-prompts)는 조합 모드가 가능한 모든 prompt를 생성한다는 점, max generation 제한, 동일 조합 반복의 fixed seed를 설명한다. 무한 조합 방지와 seed 표시의 참고일 뿐, wildcard 문법·파일 탐색·랜덤 확장을 AtelierX에 도입한다는 뜻은 아니다.

## 권고하는 첫 구현 경계

1. **Core 소유 조각**: character에 연결한 prompt fragment CRUD를 Core REST로 제공한다. 조각은 이름, 본문, 선택적으로 `requires` 참조, revision/archived metadata를 가진다. category 이름처럼 자동 prompt 삽입하지 않는다. 조각 자체와 `requires`가 해석된 선택 결과를 preview 및 Task/batch snapshot에 deep copy한다. 현재 category/그룹과 마찬가지로 이후 수정·보관은 과거 Task에 소급하지 않는다.
2. **제작 화면의 두 모드**: 단일 모드는 현행 expression/action/situation과 명시 선택 조각을 한 preview로 보낸다. 대량 모드는 사용자가 각 축의 후보 조각을 명시적으로 선택하고, Core preview endpoint가 조합 목록·각 snapshot hash·조합 수를 반환한다. 줄바꿈 여러 줄은 하나의 조각 본문이며 후보 목록으로 암묵 분할하지 않는다. 후보 분리는 UI의 명시적 add/remove 또는 별도 조각 생성만 사용한다.
3. **Cartesian 수량과 접수**: UI는 접수 전 축별 수와 곱을 보인다. Core가 최종 개수를 계산·검증하고 현재 batch 상한 32를 넘으면 접수를 거절한다. UI가 32개를 임의로 잘라내거나 background queue로 분할하지 않는다. 32보다 큰 실행, pagination된 여러 batch, queued expansion은 후속 결정이다.
4. **검증 연결**: 대량 item마다 현재처럼 단일 validation selection과 preview_hash가 필수다. group validation selection은 batch 전체에 하나를 명시한다. group reference가 없거나 변경된 경우에는 기존 reference 후보/확인 절차를 그대로 사용한다. fragment 조합이 기준 저장·재검증·replacement를 자동 실행하지 않는다.
5. **seed 기록**: 각 조합의 최종 `generation_inputs.seed`를 snapshot에 저장해 재현 가능하게 한다. 사용자 입력 seed를 모든 조합에 고정할지, index별 결정적 파생 seed를 Core가 만들지, random seed를 허용할지는 접수 전 명시해야 한다. UI나 Generation이 암묵적으로 seed를 증가시키지 않는다.
6. **재생성 경계**: 조합 batch는 기존 자동 regeneration cycle의 상한과 오류 분리를 따른다. single validation error는 불합격으로 바꾸지 않으며 자동 재시도하지 않는다. `insufficient_images`, reference confirmation 대기, 단일 실패는 추가 조합 생성으로 보정하지 않는다.

## 단계별 검증 제안

| 단계 | 범위 | 필요한 검증 |
| --- | --- | --- |
| 1 | Core fragment revision CRUD와 character 연결 | 권한/관계 검증, revision 충돌, 보관, 재시작, 과거 snapshot 불변 |
| 2 | 단일 preview에서 명시 조각 선택 | 본문 보존, 줄바꿈 비분할, requires 표시만/해석 경계, preview hash stale |
| 3 | Core의 Cartesian preview | 조합 수, 중복/빈 축, 32 초과 거절, 결정적 순서, 각 snapshot/hash/seed 표시 |
| 4 | 기존 batch 접수 연결 | 202/동일 key 200, item별 single validation, reference confirmation, insufficient 종료, 기존 batch 회귀 |
| 5 | 화면 | 단일/대량 전환, 사전 수량·hash 검토, 중복 접수 방지, 작업 상태는 Jobs API에서 조회 |

## 구현 전에 필요한 제품 결정

다음은 기존 계약만으로 결정할 수 없다.

- `requires`를 단지 UI 표시 조건으로 둘지, 선택 유효성까지 강제할지. 강제하면 조각의 의미와 preview 결과가 달라진다.
- 대량 mode의 seed 정책: 모든 조합 고정, 조합 index에서 결정적으로 파생, 또는 사용자가 조합별 값 제공 중 어느 방식을 지원할지.
- 32개 초과 요청을 현행처럼 명시 거절할지, 사용자가 확인한 여러 batch로 나눌지를 결정할지. 첫 구현 권고는 거절이며 자동 분할은 하지 않는 것이다.

그 외 CRUD 세부 필드, REST pagination, 화면 배치는 위 경계를 지키는 구현 선택으로 진행할 수 있다.
