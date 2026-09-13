# 제작 계획 장기 큐·복구 검증

2026-09-13 후속 검증. `tests/test_production_plan_recovery.py`는 실제 파일 SQLite를 사용하고 생성·검증 Provider는 대체 구현으로 제어한다. 기존 파일럿, ComfyUI 및 사용자의 작업은 중단하지 않았다.

## 확인한 경계

- 1,024개 항목을 8개 실행 창으로 처리하는 동안 SQLite를 네 차례 close/reopen한다. 총 Task가 정확히 1,024개이며 전 항목 passed, 계획 completed/passed로 수렴한다.
- 묶음 요청 32회가 각각 동일 reference revision을 사용한다. Provider 실행 결과는 테스트가 공급하므로 추론 성능·품질 측정이 아니다.
- 생성 Task를 저장했지만 계획 항목 연결 전 중단된 상황에서 DB를 다시 열고 취소하면 그 Task까지 찾아 취소한다.
- 묶음 검사 실행 중 취소 후에는 Provider가 cancellation_pending인 동안 계획도 대기한다. Provider 종료 후에만 계획 cancelled가 된다.
- 단일 검사 중 취소에도 검사 종료를 기다리며 남은 항목을 새로 접수하지 않고 후속 묶음 검사를 시작하지 않는다.

이전 `test_production_plans.py`의 접수 오류 정리·3,000개 저장·트랜잭션 롤백 검증과 함께 사용한다. 이번 테스트는 OS 프로세스 강제 종료나 실제 GPU 서비스 장애 실험을 대체하지 않는다. 대체 Provider 상태는 메모리에 유지하고 Core 소유 SQLite만 재연결한다.

실행 명령: `.venv/Scripts/python.exe -m unittest discover -s tests`

로그: `artifacts/full-suite/plan-recovery-extended.log`.

결과: 신규 4개를 포함한 Python 전체 191개 통과, 34.794초. 이번 변경은 테스트·문서이며 제품 실행 코드는 변경하지 않았다.

## 현재 파일럿의 오류 대응

1. 작업 현황에서 계획과 개별 Task, 단일 검사 및 묶음 검사의 상태·error를 함께 확인한다. completed는 품질 합격을 뜻하지 않는다.
2. 응답 유실 때 새 계획을 만들기 전에 작업 현황에서 기존 접수를 확인한다. 현재 브라우저 메모리의 요청 키는 새로고침 후 유지되지 않는다.
3. 중단할 때 계획 취소 후 cancellation_pending의 종료를 확인한다. 오류가 계속되면 error와 계획 ID를 보존하고 서비스 연결 상태를 먼저 확인한다.
4. Validation outcome=error는 자동 재생성으로 해결하지 않는다. 연결/모델 문제를 해결한 뒤 사용자가 기존 이미지 재검증 또는 수동 재생성을 선택한다.
5. 서비스 재시작 전 사용자의 ComfyUI 직접 실행과 다른 작업이 없는지 확인한다. 계획 실패 이력·DB·이미지를 삭제하거나 새 ID로 반복 접수하여 복구하지 않는다.

## 다음 실환경 검증

격리된 서비스·복사 데이터로 통신 중단, 재시작, 늦은 응답을 시험하고 그다음 작은 실제 이미지 계획에서 GPU 권한 회수와 복구를 확인한다. 실제 GPU 수천 장 실행에 앞서 이 결과, 대표 이미지의 VLM 오판률, 백업/복원 근거를 확보한다.
