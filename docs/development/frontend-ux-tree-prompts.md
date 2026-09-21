# 분류 트리·자유 Prompt 입력 개선

2026-09-13 사용자 요청 1~7의 구현·사전 검토 기록. 주 에이전트는 Core 계약·통합·브라우저 검증을 조율하고, Terra는 제작·갤러리 모듈 및 조각 기반 대량 제작 검토를 담당했다.

## 반영 범위

| 요청 | 결과 |
| --- | --- |
| 1. 제작 분류 트리 | 작품 > 캐릭터 > 의상, 별도 `>` / `˅` 펼침 버튼과 이름 선택 버튼, 들여쓰기·선택 표시 |
| 2. 랜덤 Seed | 버튼으로 JavaScript 안전 정수 난수를 뽑고 기존 preview 무효화. 실제 값은 사용자가 볼 수 있고 snapshot으로 고정 |
| 3. Sampler/Scheduler | 설치된 ComfyUI 목록을 확인하여 드롭다운 제공. 등록 목록 변경 시 갱신 필요 |
| 4. 갤러리 분류 | 직접 ID 입력 제거, 같은 계층·스타일의 트리로 REST 필터 지정. 상위 선택 시 하위 필터·페이지·선택 상세 초기화 |
| 5. 대량 제작 조각 | [구현 전 검토](batch-prompt-fragments-review.md) 완료. 조각 저장·캐릭터 연결·조합 preview API는 아직 미구현이며 기존 Batch 폼은 작업 현황에 유지 |
| 6. 자유 구도 | 여러 줄 `framing_prompt`, 배경을 포함한 자유 조합. 기존 enum API와 호환하는 custom 경로 추가 |
| 7. 표정·자세/동작·상황 | 여러 줄 편집, 한 필드의 원문 그대로 한 이미지 Prompt에 포함 |

자유 구도에서는 외형·상의·하의 포함 여부를 명시한다. 기본 upper body의 하의는 꺼져 있으며, full body로 바꿔 하의가 필요하면 켠다. Core는 정확한 upper body와 하의 포함 충돌, upper body와 full body 동시 지정처럼 식별 가능한 충돌을 거절한다. 임의 자연어의 구도를 추측하지 않는다. 줄바꿈을 별도 이미지 후보로 자동 변환하지 않는다.

Core custom snapshot은 composition_version 3 및 prompt_inputs에 원문을 보존한다. 기존 enum snapshot은 version 2를 유지한다. 프롬프트·영역·Seed·옵션 변경은 preview/hash에 반영되며, 늦은 preview 응답도 입력 revision과 요청이 달라지면 버린다. 원본 프롬프트 그룹·과거 Task는 바꾸지 않는다. [REST 계약](../api/rest-api.md).

## 검증 결과

- Python 전체 176개 테스트 통과(20.324초). 이후 구도 충돌 검사 보강은 Core 14개 관련 테스트로 재검증(2.068초).
- Node API·작업 현황·갤러리·설정 회귀와 제작 전용 6개 테스트 통과. 제작 회귀는 custom payload·multiline 원문·안전 Seed·stale preview를 포함한다.
- 실제 브라우저: 양쪽 트리 펼치기, 갤러리의 화이트 셔츠 선택 필터, 제작 의상·기존 그룹 선택, 자유 구도/표정/동작/상황 여러 줄 입력과 Core preview 성공을 확인했다.
- Sampler euler / Scheduler karras 선택을 확인했다. 랜덤 Seed를 누른 뒤 실제 안전 정수가 표시되고 Task 접수 버튼이 비활성화됨을 확인했다. 이번 선택 옵션 전체의 GPU 생성 품질 검증은 하지 않았다.
- 실제 생성은 추가로 접수하지 않았다. API 합성→Task→Generation 전달은 테스트 서비스로 확인했다. 실행 작업이 없는 것을 확인한 뒤 파일럿 Backend만 재시작했고, 기존 ComfyUI는 재시작하지 않았다.

전체 로그: `artifacts/full-suite/frontend-ux-tree.log`, 최종 Core 관련 로그: `artifacts/full-suite/custom-framing.log`. 기존 서버 주소는 `http://127.0.0.1:8190/ui/`다.

## 대량 제작의 다음 단계

최신 확정으로 아래 캐릭터 연결 조각 권고도 대체됐다. 조각은 독립된 전역 공유 라이브러리이며, 포함할 외형·상의·하의는 각 조각에 저장한다. [최우선 확정 flow](batch-production-flow-review.md)를 따른다.

후속 사용자 정정으로 아래 초기 권고의 **32개 상한 유지는 폐기**했다. 생성 수에 제품 상한을 두지 않으며, 사용자 작성 조각을 체크하여 가져온다. 최신 [flow 재검토](batch-production-flow-review.md)가 우선한다.

권고 구조는 제작 화면에서 캐릭터와 연결된 조각을 선택하고, Core가 조합 수와 행별 preview를 만든 뒤 현재 Batch 흐름에 접수하는 방식이다. 첫 범위는 명시적 후보 선택, 32개 상한 유지, 접수 전 확정 Seed 표시, 기존 단일 검증·기준 확인·묶음 검증 유지로 잡는다. requires 의존성 강제·암묵적 랜덤 후보·자동 Batch 분할은 첫 구현에서 제외하는 것을 권고한다. 이는 사용자 요청 5의 사전 검토이며 라이브러리 구현 완료를 뜻하지 않는다.
