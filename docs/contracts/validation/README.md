# Validation 실행 가능한 계약 초안 0.1

상태: 현재 ADR 검토 범위를 앞서 작성된 참고 산출물. 사용자 재확인에 따라 확정 명세나 구현 기준으로 채택하지 않으며 추가 코드/Schema 생성·자동 검사는 보류한다. **Backend 구현·Provider 품질 검증·실제 장애 복구 시험은 아니다.** 기존 Accepted ADR은 유지하며 ADR-0005·0019는 Proposed 상태다. Python/Pydantic은 문서 계약 검증에 기존 ComfyUI 환경을 활용한 도구 선택이고 Backend Stack 결정이 아니다. 의존성을 설치하거나 ComfyUI 서버를 변경하지 않았다.

## 산출물

| 파일 | 역할 |
| --- | --- |
| [contract_models.py](contract_models.py) | 엄격한 입력/결과 모델과 객체 간 참조·집계·오류 경계 검사 |
| [schemas](schemas/single-request.schema.json) | 단일/묶음 요청·단일/묶음 결과·Job의 JSON Schema 2020-12 5종 |
| [examples/manifest.json](examples/manifest.json) | 검증한 예제 10개의 적용 모델 목록 |
| [job-transitions.json](job-transitions.json) | 검토용 상태 전이 표 |
| [check_contract.py](check_contract.py) | 정상/거부 예제·연결 불변식·상태 전이 시나리오 검사 |
| [recovery-scenarios.md](recovery-scenarios.md) | 영속 저장·복구·중복 접수 구현 검증 조건 |

JSON Schema는 필드·타입·범위·알 수 없는 속성을 검사한다. **합계, ID 연결, 필드별 변경값 타입, 상태/결과 조합 등은 모델의 추가 검사도 필요하다.** JSON Schema만 통과했다고 유효한 실행 요청으로 승인하지 않는다. 모델이 반환한 판정의 시각적 정확성·Prompt 의도 보존·모델 호환성은 이 자료로 보장하지 않는다.

## 이번에 정리한 계약 경계

- profile/provider snapshot에는 서버 ID·revision을 연결한다. Secret·Endpoint·임의 파일 경로는 받지 않는다. Core가 준비한 snapshot도 Validation이 권한·등록 revision·Provider 지원 기능과 대조해야 한다.
- 이미지 참조는 등록 Generation source 또는 upload source 중 하나다. SHA-256의 형식은 검사하지만 실제 바이트와 일치는 아직 실행 검사 대상이다. 이미지 하나를 다른 별칭으로 중복 입력해 비교 수를 부풀리지 않는다. digest 일치만으로 서로 다른 파일을 중복 검증·삭제하지 않는다.
- 단일 요청은 negative_prompt 미사용도 빈 문자열로 명시한다. 출력 검사를 켰다면 expected_output을 요구하고 생성 설정이 없으면 변경 제안을 허용하지 않는다.
- 묶음은 판정 targets와 대표/보조 roles를 분리한다. 자기 자신과의 비교만으로 합격시키지 않는다. 대표가 판정 대상이기도 하면 다른 비교 자료가 있어야 한다. 이는 묶음의 통과 이미지를 재검토하는 방식과 기준 이미지 선정의 정당성 검증을 구분한 초안이다.
- 묶음에서 `scope=partial, summary=all_match`는 이번 부분 대상만 모두 일치라는 뜻이다. Core는 현재 전체 대상의 미검증·기준 변경·기존 판정을 함께 집계해야 한다.
- `GroupResult`의 error item은 다른 정상 item과 공존한다. 그룹 전체 수행 불가인 failed Job에는 이 정상 결과 형태를 쓰지 않고 Job.error를 반환한다. 부분 진단 이력의 API는 후속 보완한다.
- 단일 error는 result=null이며 자동 재생성 정보가 없다. 그룹 결과에는 자동 재생성 필드를 두지 않는다. Core의 On/Off·상한과 Generation의 실제 환경 검사는 별도다.
- 모든 result는 저장된 request 및 Job과 `validate_exchange`로 대조한다. 현재 그룹 revision 유효성은 이 request 대조와 별개로 Core가 확인한다.

## 아직 고정하지 않은 생성 상세

변경값 필드는 알려진 범주로 제한한다. LoRA는 순서 있는 전체 목록 교체이고 후처리는 준비된 설정 snapshot 참조를 사용하는 초기안이다. 구체 후처리 Node Schema가 정해지면 세부 변경 경로를 추가한다. 임의 dict/SQL/파일 경로 수정은 받지 않는다. Generation capability가 허용한 범위·실제 설치 조합과 제작 의도 검사는 여전히 필요하다.

`alpha=channel_required`와 `transparency_required`는 형식/픽셀 조건의 구분이며 캐릭터 배경 제거의 품질 판정과 다르다. 필요 검사 누락/생략, 전체 입력 연결값, Job-level 오류·접수 응답·SSE의 전체 OpenAPI 표현은 후속 보완 대상이다. 이번 자료는 전체 제품 Schema의 완성본이 아니다.

## 상태 전이

| 상황 | 상태 처리 |
| --- | --- |
| 접수 후 실행 권한 대기 | queued, wait_reason=provider/gpu/memory |
| 실제 dispatch | running |
| 정상 판정 처리 종료 | completed; 불합격도 처리 완료 |
| 실행 실패/Timeout | failed, 자동 queued 전이 없음 |
| 대기 취소 | cancelled |
| 실행 취소 요청 | cancelling, 아직 완료로 표시하지 않음 |
| 취소 확인 또는 취소 요청 후 외부 응답 도착 | cancelled, 후속 생성에 결과 적용 금지 |
| 재시작·대기 | queued 복원 |
| 재시작·실행 추적 가능 | 기존 running/cancelling 유지 |
| 재시작·추적 불가 | failed, 이전 실행을 자동 재제출하지 않음 |

재시작으로 failed가 된 취소 요청도 사용자 취소 의도를 이력에서 유지한다. 늦은 응답은 terminal 상태를 되돌리지 않는다. 현재 전이 검사는 선언된 정책을 순서대로 적용하는 문서 시뮬레이션이며 영속 저장이나 프로세스 중단을 실제로 시험하지 않는다.

## 재현

저장소 루트에서 기존 설치 Python을 사용한다.

```powershell
& 'C:\StabilityMatrix\Packages\ComfyUI\venv\Scripts\python.exe' -B docs/contracts/validation/build_artifacts.py
& 'C:\StabilityMatrix\Packages\ComfyUI\venv\Scripts\python.exe' -B docs/contracts/validation/check_contract.py
```

build는 문서 하위의 Schema/예제만 갱신한다. Pydantic v2가 필요하며 이 프로젝트의 런타임 의존성·CI 정책으로 설치하거나 선언하지 않았다. 다음 단계는 이 계약을 기반으로 실제 접수/저장 프로토타입을 구현할 때 아래 복구 조건을 시험하는 것이다.
