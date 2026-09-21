# Core 자동 연결·GPU 조정·취소·Queue 검증

2026-09-13 사용자 승인에 따라 Client는 시작 옵션을 전달하고 Core가 생성 후 검증을 조정하도록 구현했다. **실제 두 생성 요청의 PNG/WebP 4개를 자동 검증했고 모두 합격했다. 종료 후 GPU owner와 대기열도 비어 있음을 확인했다.**

## 이번 구현

- Core Task의 선택 `validation`으로 생성만/생성 후 검증을 구분한다. 선택한 Profile·Provider·endpoint를 요청 시 snapshot에 고정한다.
- Core가 생성 완료 후 각 출력 이미지의 검증 Run을 고정 키로 생성한다. 반복 worker tick·응답 유실·재시작에서 동일 Run을 재사용하며 Client가 별도 완료 polling 후 검증 POST를 수행할 필요가 없다.
- Core 소유 GPU coordinator: SQLite의 추가 `gpu_state` 테이블에 owner·FIFO waiting을 저장한다. 같은 Job의 중복 권한 요청은 기존 권한을 반환한다. 서비스는 REST만 사용하며 Core SQLite에 직접 접근하지 않는다.
- Generation 전 지정 LM Studio 모델 idle·queue 상태를 확인하고 해당 모델만 native REST로 unload한다. ComfyUI busy 대기 및 메모리 해제 후 `nvidia-smi`로 여유 VRAM을 확인한다. Validation은 shared_gpu 설정 시 같은 coordinator에 참여한다.
- 대기 작업은 즉시 취소한다. 제출·실행 중인 작업은 cancel_requested 상태를 보존하고 실제 종료까지 기다린 뒤 결과를 버린다. Core 저장 시에도 취소가 먼저 반영됐으면 늦은 판정으로 덮지 않는다. ComfyUI 전체 interrupt는 호출하지 않는다.
- 세 서비스 Queue 페이지 조회와 SSE reset/changed·heartbeat를 제공한다. 요청 본문·이미지 bytes를 이벤트에 반복 전송하지 않는다.

API 필드와 경로는 [별도 REST 명세](../api/rest-api.md)에 반영했다. 기존 ADR-0003·0016·0020과 사용자 승인한 Core 조정 경계를 따른다. 메모리 수치·초기 endpoint 등은 검증 가능한 구현 기본값이며 별도 Accepted 제품 정책으로 확장하지 않는다.

## 검증

| 항목 | 결과 |
|---|---|
| Backend 회귀 | 50개 통과 |
| 자동 접수·설정 고정·재시작 중복 방지 | 자동 시험 통과 |
| GPU FIFO·다른 owner 해제 방지·재시작 보존·busy 대기 | 자동 시험 통과 |
| Generation 대기/제출 후 취소 | 자동 시험 통과, 사용자 전체 interrupt 없음 |
| Validation 대기/실행 중 취소 | 자동 시험 통과, 늦은 Provider 판정 배제 |
| Core 취소·늦은 결과 저장 방지 | 자동 시험 통과 |
| Queue 페이지·SSE 최초 reset/변경·민감 본문 제외 | 자동 시험 통과 |
| 실제 단일 전체 후처리 → 자동 검증 | PNG/WebP 합격·Core 재시작 보존 |
| 실제 연속 생성 2건 → 자동 검증 | Encode 및 전체 후처리 출력 총 4개 합격 |
| 최종 권한/Queue | GPU owner=null, waiting=[], generation 2건 generated, validation 4건 completed |

[최종 실행 결과](../../artifacts/backend-pipeline-rest/20260913-123154/report.json), [전체 후처리 PNG](../../artifacts/backend-pipeline-rest/20260913-123154/all.png), [WebP](../../artifacts/backend-pipeline-rest/20260913-123154/all.webp). seed 2026091306, 캐릭터 Negative beard, WAI Anima·LM Studio Qwen3 VL 8B를 사용했다. 실제 취소 중 모델 종료 실험은 Mock 기반 취소 시험과 구분하며 이번 GPU 실행에서는 정상 완료 흐름을 확인했다.

첫 자동 시험(`artifacts/backend-pipeline-rest/20260913-122526`)은 PNG 합격 후 WebP가 VRAM 기준으로 대기했다. 기존 256 MiB 여유 기준에 실제 여유 약 251 MiB가 못 미쳐 권한을 주지 않은 것이다. 대기 상태의 시험을 중단하고, 이미 지정 모델이 로드된 경우 기본 여유를 128 MiB로 조정했다. 이후 단일 재실행(`20260913-122742`) 및 위 연속 작업이 통과했다. 새 모델을 올리기 전 기준은 18,000 MiB를 유지한다. 현재 모델·4090의 초기 운영값이며 다른 모델의 안전한 메모리 예측을 보장하지 않는다.

## 로컬 실행 준비

현재 사용자의 수동 설정은 보존하고 `.atelierx/validation-coordinated-config.json` 및 `.atelierx/gpu-config.json`을 별도로 준비했다. 저장소 공유 예제는 [검증 설정](../../config/validation-coordinated.example.json), [GPU 설정](../../config/gpu.example.json)이다. ComfyUI·LM Studio 서버를 실행하고 세 서비스에 동일한 ATELIERX_SERVICE_TOKEN을 설정한 뒤 별도 터미널에서 실행한다.

```powershell
.venv/Scripts/atelierx-core.exe --port 8190 --generation-url http://127.0.0.1:8189 --validation-config .atelierx/validation-coordinated-config.json --gpu-config .atelierx/gpu-config.json
.venv/Scripts/atelierx-generation.exe --port 8189 --coordinator-url http://127.0.0.1:8190
.venv/Scripts/atelierx-validation.exe --port 8191 --config .atelierx/validation-coordinated-config.json
```

실제 시험은 다음과 같이 임시 포트·별도 data-dir에서 실행한다. `--automatic`에서는 시험자가 VLM을 수동 unload하거나 별도 검증을 접수하지 않는다.

```powershell
.venv/Scripts/python.exe -B scripts/test_backend_pipeline_rest.py --cases encode,all --real-vlm --automatic --seed 2026091306 --character-negative beard
```

## 남은 경계

- 공유 GPU 참여 설정을 하지 않은 독립 서비스·직접 ComfyUI/LM Studio 사용까지 원자적으로 통제하지 않는다. busy 확인 직후의 외부 직접 실행 경쟁은 남는다.
- 제출 후 취소는 협력 취소다. 이미 시작된 GPU 계산을 강제 중단하지 않으므로 취소 완료까지 시간이 걸릴 수 있다.
- Provider timeout/수락 불명·Generation 실행 추적 불명에서는 실제 추론 종료를 확인할 수 없어 GPU 권한을 유지한다. 자동 만료/강제 해제는 하지 않으며 운영자 확인 후 복구가 필요하다. 서비스별 인증 세분화·운영 복구 UI는 후속이다.
- Queue/SSE는 현재 상태 재동기화 방식이다. 과거 이벤트 재생, ComfyUI 내부 Node 진행률, Provider별 독립 병렬 worker·다중 GPU, 전체 실행/대기 기한은 아직 없다.
- 자동 재생성·묶음 검증은 이번 변경에 포함하지 않는다. 다음 구현은 단일 결과 기반 재생성 요청·횟수/계보·중단 정책이다.

런타임 참고: [LM Studio 모델 목록](https://lmstudio.ai/docs/developer/rest/list), [모델 unload](https://lmstudio.ai/docs/developer/rest/unload), 설치된 ComfyUI server.py의 queue/free REST 처리. LM Studio CLI는 idle/queued 상태를 읽는 용도로만 사용한다.


## 2026-09-13 재생성 후속 구현

수동/자동 재생성, 시도 이력, 실행 시작 기준 횟수 및 중단 처리를 구현했다. 이전 미구현 표기는 이 후속 기록으로 갱신한다. 지원 변경 범위와 검증 결과는 [재생성 구현 보고서](regeneration-validation.md), 계약은 [REST 명세](../api/rest-api.md)를 참조한다. 묶음 검증 기반 흐름은 남아 있다.
