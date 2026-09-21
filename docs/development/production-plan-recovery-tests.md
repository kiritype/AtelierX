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

## 후속 세션: 서비스 장애 검증

시작 시 `codex/documentation-handoff`의 로컬 HEAD와 원격 HEAD가 모두 `758ef165c71c3a2fb2519b6468c57740e8905166`이고 작업 트리가 깨끗함을 확인했다. 기존 8189/8190/8191 서비스, ComfyUI 8188, LM Studio 1234는 실행 중이었다. 세 서비스의 활성 작업, ComfyUI 큐, Core GPU owner/waiting은 비어 있었다. LM Studio의 모델 목록과 실제 로드 상태를 구분해 native `/api/v1/models`의 `loaded_instances`가 비어 있음을 확인했다. 사전 증거는 `artifacts/service-fault-recovery/preflight.json`이다.

`tests/test_service_fault_recovery.py`의 첫 세 사례는 실제 localhost TCP와 임시 SQLite를 사용한다. Generation은 모의 HTTP 서비스다. 수락 후 503 응답 유실, 수락 후 지연 응답과 Core AppRunner 재구성, 실제 Core OS 프로세스 강제 종료 후 동일 DB/포트 재시작을 각각 검사한다. 세 경우 모두 Generation 접수 POST 1회와 이미지 연결 1개를 확인했다. AppRunner 재구성과 OS 프로세스 재시작을 같은 근거로 세지 않는다.

계획의 묶음 Run 저장 직후 `production_plan_comparisons` 연결 저장 전에 중단되면, 취소가 이미 저장된 Run을 놓칠 수 있었다. 계획/sequence/chunk로 고정한 내부 접수 키를 조회해 연결을 복원하고 기존 Run의 협력 취소를 기다리도록 수정했다. Task 연결 복구와 별개의 회귀 사례다.

Generation은 GPU 권한 취득 뒤 다른 ComfyUI 작업을 발견했을 때 아직 제출하지 않은 자신의 권한을 반납한다. 반대로 `/prompt` 응답의 ID가 저장된 ID와 다르면 실행 여부를 확정할 수 없으므로 `GEN_EXECUTION_UNKNOWN`으로 권한을 보존한다. coordinator의 손상된 성공 응답도 실행 허가로 사용하지 않는다. 이 항목들은 모의 HTTP/단위 검사의 근거이며 실제 GPU 장애 결과를 대신하지 않는다.

### 2026-09-21 재개와 검증 범위

사용량 제한으로 중단됐던 변경을 이어 검토했다. 재개 시 원격 HEAD는 동일했고, 이전 변경은 미커밋 상태로 남아 있었다. 기존 서비스 포트와 관련 프로세스는 모두 종료된 상태여서 ComfyUI와 LM Studio만 기존 설치로 시작했다. 파일럿 DB를 열어 실행하거나 파일럿 서비스를 재시작하지 않았다. 새 사전 증거는 `artifacts/recovery-20260921/preflight.json`이다.

| 장애 경계 | 실행 방식 | 확인 내용 |
| --- | --- | --- |
| Generation 수락 후 TCP 연결 종료 | 실제 Core HTTP + 모의 Generation | 기존 접수 키 조회로 복구, 생성 POST 1회 |
| 단일·묶음 Provider 실행 중 Validation 종료 | 실제 Validation OS 프로세스 kill/restart + 모의 VLM HTTP | `failed/error`, `VAL_PROVIDER_ACCEPTANCE_UNKNOWN`, VLM 호출 각 1회 |
| 단일·묶음 취소 뒤 Provider 늦은 응답 | 실제 Validation OS 프로세스 + 모의 VLM HTTP | 최종 `cancelled`, outcome/result null, 늦은 판정은 `late_result`에만 보존 |
| 묶음 Run 저장과 계획 연결 사이 중단 | 실제 SQLite close/reopen + CoreGroups | 고정 접수 키로 연결 복원, 취소 시 Run과 계획 종료 확인 |

Validation subprocess 사례는 `tests/test_validation_process_fault_recovery.py`, 연결 단절 사례는 `tests/test_service_fault_recovery.py`, SQLite 사례는 `tests/test_production_plan_recovery.py`에 있다. 실제 프로세스·소켓·저장소를 사용했다는 사실과 모의 Provider가 반환한 합격 근거를 구분한다. 이 테스트는 VLM 정확도나 실제 GPU 처리량을 측정하지 않는다.

### 복구 보장 경계

Generation의 노드 정보 조회 중 접수 저장이 늦어지는 경우에는 by-key 조회도 접수와 같은 잠금을 기다린다. 따라서 실제 Generation handler 내부의 저장 전 조회가 일시적 404를 반환하지 않는다. 이 동기화는 신규 생성 POST 재전송이 아니다.

서비스 외부 proxy 또는 요청 본문 전송 지연으로 원래 POST가 handler에 도달하기도 전에 키 조회가 먼저 404를 받는 경우는 여전히 수락 불명 경계다. 현재 계약은 명시적 acceptance-unknown 오류와 자동 재전송 금지를 유지하며, 그 뒤 원격에 도착한 요청까지 자동으로 정리한다고 보장하지 않는다. 이 경우 원격 큐와 접수 키를 운영자가 확인해야 한다. 무인 운영 게이트를 닫으려면 별도의 접수 예약/취소 계약 검토와 장애 시험이 필요하다.

지속적인 서비스 단절에서 상태 조회가 대기하는 동작과 Provider 추론 재시도는 구분한다. 시험은 연결이 복구되는 제한된 장애를 주입했으며, 무기한 단절의 자동 종료 기한을 새 정책으로 도입하지 않았다. 실행 종료가 불명확한 GPU owner는 시간이 지났다는 이유로 강제 해제하지 않는다.

### 자동 검사 결과

- Python 전체: **207개 통과**, 45.145초. 로그 `artifacts/full-suite/recovery-resumed.log`.
- 이후 프로세스 kill 뒤 실제 포트가 닫혔는지 fresh TCP 연결로 확인하는 테스트 단언을 보강했다. 관련 장애 테스트 **8개 재통과**, 7.071초. 제품 코드는 이 재검사에서 변경하지 않았다.
- 프론트엔드: `node --test tests/*.mjs`, **17개 통과**.
- Generation 키 조회·Validation gateway 오류 분류·GPU 응답 검증: `tests/test_late_acceptance_recovery.py`. 명시적 `VAL_*` 503 오류를 bare gateway 503과 구분하며 numeric `released:1`은 반납 확인으로 인정하지 않는다.

재현은 저장소 `.venv/Scripts/python.exe -m unittest discover -s tests -v`를 사용한다. 테스트의 모의 서비스와 임시 DB는 자동 준비된다. 반면 실제 GPU 스크립트의 `.atelierx/` 설정, 설치된 ComfyUI·LM Studio·모델 및 이미지·DB·로그는 로컬 실행 자원이며 새 clone에 포함되지 않는다.

### 실제 GPU: 최초 시험 중단과 같은 작업 복구

첫 실제 시험에서 Generation을 실행 중 종료한 뒤, 시험 스크립트가 coroutine을 boolean과 비교하는 오류로 중단됐다. 제품 서비스 오류와 구분한다. 해당 원본 보고서는 `artifacts/recovery-20260921/gpu-live/report.json`에 실패 그대로 보존했다. 새 접수 없이 같은 DB·Generation 기록·고정 포트를 사용한 복구 결과는 `gpu-live/recovery-report.json`에 별도로 기록했다.

- 계획 `619ab884-472e-479a-88e7-15b0bdeb8a6f`, Generation Job/ComfyUI prompt `486eb1a8-0e8e-4e1f-aaf4-6f66b9af29b9`.
- 실제 ComfyUI `queue_running`에서 해당 prompt를 관찰한 뒤 Generation 프로세스가 종료됐다. Core 재기동 시 동일 GPU owner가 복원됐고, 추가 Core 강제 종료·재시작에서도 소유권이 보존됐다.
- Generation 재기동은 같은 prompt의 history를 회수했다. Generation Job은 1개이며 새 생성 요청을 접수하지 않았다.
- Anima 1024×1024 → UltraSharp 최종 1536×1536. PNG·WebP를 실제 decode하고 각각 SHA-256을 저장값과 비교했다.
- 실제 `qwen3-vl-8b-instruct-abliterated` 단일 검사는 두 출력 모두 `completed/passed`였다. 동일 생성 이미지의 두 포맷이며 서로 다른 두 장의 생성으로 세지 않는다.
- 기준 교체·묶음 검사를 자동 승인하지 않고 시험 계획을 명시적으로 취소했다. 최종 GPU owner=null, waiting=[], 세 서비스 활성 작업 없음으로 정리했다. 기존 파일럿 DB·토큰·이미지를 변경하지 않았다.

스크립트는 같은 종료·포트 확인 helper를 CPU dry-run과 실제 경로에서 재사용하도록 수정했다. ComfyUI·LM Studio 자체는 종료하지 않았으며, timeout/수락 불명 owner의 자동 강제 반납도 하지 않았다.

### 수정한 스크립트의 실제 재검증

```powershell
.venv/Scripts/python.exe -B scripts/test_plan_gpu_recovery_rest.py --confirm-exclusive-gpu --timeout 600 --seed 2026092101 --run-root artifacts/recovery-20260921/gpu-live-confirmed
```

별도의 한 항목 계획 `c07b2727-f5a5-4092-8942-d6a8a2ae0154`로 위 명령을 실행해 **33.112초에 성공**했다. 생성 중 Generation 종료 → Core 종료 → Core 재기동과 owner 보존 확인 → Generation 재기동 순서이며, 두 서비스 모두 종료 후 포트 닫힘과 새 프로세스 PID를 확인한다.

Generation Job/ComfyUI prompt ID는 `4218da7e-1be4-4c41-ba86-20ad6a0e4a14`로 유지됐고 저장된 Generation Job 파일은 1개다. PNG 1536×1536 decode·SHA-256 확인, PNG/WebP 단일 검사의 `completed/passed`, 동일 prompt history 회수, 계획 명시 취소, Core 활성 작업 0개, GPU owner=null/waiting=[]를 확인했다. 원시 증거는 `artifacts/recovery-20260921/gpu-live-confirmed/report.json`과 같은 디렉터리의 서비스별 stdout/stderr 로그다.

두 실제 계획은 각각 한 번만 생성됐으며, 각 PNG/WebP를 별도 생성 이미지로 세지 않는다. 이번 실제 시험에서 묶음 검사는 실행하지 않았다. 단일 검증 통과를 전체 일관성 합격으로 확대하지 않으며, 이전 실제 묶음 `failed` 기록도 유지한다. 실제 VLM 추론 도중 프로세스 종료·ComfyUI 자체 재시작·장기 무인 운영·외부 작업 경합·백업/복원·디스크 부족은 여전히 남은 검증이다.

시험용 Core/Generation/Validation 프로세스는 종료했고 ComfyUI 8188과 LM Studio 1234는 실행 상태로 남겼다. ComfyUI 최종 큐는 비어 있다. 파일럿 8189/8190/8191은 이번에 시작하지 않았다. 이미지와 DB는 각 시험의 `data/generation/images`, `data/core.sqlite3`에 보존되며 기존 `.atelierx/pilot/`과 구분한다.
