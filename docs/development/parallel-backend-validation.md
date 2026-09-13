# 병렬 Backend 구현·검증 기록 — 2026-09-13

최신 후속: [그룹 일괄 실행·검사 설정 실환경 검증](group-batches-live-validation.md). 아래 미실행 기록 이후 실제 2장 생성·단일/묶음 검증·revision 고정·재시작을 확인했다. 빈 component 후보 계산과 Provider key 정규화 문제를 수정했고 전체 117개 회귀가 통과했다. VLM 일관성 판정의 정확도 제한은 별도로 기록했다.

## 후속: 그룹 일괄 실행·검사 설정 관리

기존 서브에이전트에 일괄 생성과 설정 관리를 분리 위임하고, 나머지 에이전트는 자원 준비 상태·입력 경계만 읽기 검토했다. 주 에이전트는 Core hook·REST 시험·오류 응답을 통합했다. 아래 최초 작업 표와 93개 시험 기록은 당시 이력이다.

- 그룹 batch: 접수 snapshot 고정, 부분 실패 집계, 최종 자동 시도 추적, 기준 확인 후 재개, 최신 cycle 취소, 재시작/접수키 중복 방지. 기준 확인 대기 중 취소 및 stale preview도 회귀에 포함했다.
- 검사 설정: 단일/묶음 profile 및 Provider CRUD·복제·보관·revision 이력, 과거 runtime 보존, 실행 전 registry 동기화. Core 저장 성공과 동기화 대기를 응답에서 구분한다. 비밀키는 runtime registry 파일에 저장하지 않는다.
- 전체 Python 회귀 115개 통과(12.562초). 실제 Core REST 접수→mock Generation 거절→실패 집계 및 재시작 후 중복 없음, 설정 저장 성공/동기화 실패/조회·보관 응답을 포함한다.
- 이번 추가 기능 시험은 로컬 fixture·REST·SQLite를 사용했다. ComfyUI와 LM Studio의 실제 생성/추론은 반복하지 않았다. 앞선 실환경 성공 기록을 새 batch·설정 관리의 GPU 실검증으로 해석하지 않는다.
- Upscale은 등록된 모델이 없고 현재 ComfyUI에 AtelierXUpscale이 로드되지 않았다. SDXL checkpoint/prototype도 없어 실제 실행은 남는다. [준비 상태](generation-next-readiness.md) 참조.

상세: [일괄 생성](group-batches.md), [검사 설정](validation-settings.md), [REST 명세](../api/rest-api.md). 다음 단계는 새 경로의 실환경 확인과 남은 Backend 범위이며 Shared API Client·CLI·Frontend 및 27B 로컬 Agent 연동은 완료로 집계하지 않는다.

사용자 지시로 기존 서브에이전트를 재사용해 역할을 나눴다. 주 에이전트는 통합 검토·문서 정리 및 실제 GPU를 순차 조정했다.

| 담당 | 작업 | 산출물 |
| --- | --- | --- |
| custom_node_terra | 기준 후보·선택 재생성→묶음 검사 연결 | core_groups.py, core_regeneration.py, 그룹 회귀 |
| detailer_censor | 기존 이미지 독립 후처리 및 장애 회귀 | Generation 경로, 독립 후처리/복구 테스트 |
| alpha_complete | Preset 저장·revision·실행 snapshot 및 현황 문서 검토 | core_presets.py, Core 연결, Preset 회귀 |

## 통합 검토에서 보완한 사항

- 독립 후처리 실행 전에 source image SHA-256을 확인한다. WebP 입력 MIME/확장자 및 기존 프롬프트 출처를 보존한다.
- 원본 파일 변경/실행 전 취소는 upload와 prompt 제출을 하지 않는지 worker 수준으로 검사한다. prompt 응답 유실은 동일 ID 조회만 한다.
- Preset은 수정/보관 이후 같은 멱등 요청을 원래 Task로 반환하고 신규 요청만 현재 revision 검사를 한다. Windows 상대 모델 하위폴더 이름을 지원한다.
- 묶음 대체 작업은 접수 설정을 고정하고 단일 자동 재생성 후속 시도 및 선택 출력만 추적한다. 비선택 출력과 과거 시도를 현재 대상에 섞지 않는다.

## 실제 GPU 검증

[독립 후처리 기록](independent-postprocess.md): PNG 및 WebP 원본 각각 Detailer→Censor→Alpha→Encode 성공. 실행 결과와 source/output hash, Core GPU 반환을 확인했다. 모델 품질 일반 평가와는 구분한다.

최종 회귀: `.venv/Scripts/python.exe -B -m unittest discover -s tests -q` — 93/93 통과. 실행 시간 12.241초. `git diff --check` 통과(기존 파일 LF/CRLF 안내 제외).

선택 재생성 전체 실환경 시험 `artifacts/backend-pipeline-rest/20260913-132816/report.json`은 최초 PNG 단일 검증 passed 후 WebP 검증이 180초 `VAL_PROVIDER_TIMEOUT`으로 종료되어 후속 재생성/묶음 검사에 도달하지 못했다. 오류 결과와 자동 흐름 종료를 보존했다. 제품의 자동 재전송은 하지 않았다.

LM Studio `lms ps --json`에서 idle/queued=0을 확인한 뒤 주 에이전트가 별도 새 시험을 시도했지만 ComfyUI queue_running=1을 발견해 `ComfyUI busy: no interference`로 접수를 중단했다. 다른 작업을 중단하거나 GPU 모델을 내리지 않았다. 신규 그룹 선택 재생성의 정상 전체 실환경 완료는 아직 미검증이다. 이전 `20260913-130948`의 명시적 묶음 비교 실환경 성공과 구분한다.

## 다음 작업

ComfyUI가 유휴일 때 `scripts/test_backend_pipeline_rest.py --cases encode --real-vlm --automatic --manual-regeneration --group-validation --group-replacement --seed 2026091306 --character-negative beard`로 전체 연결을 재확인한다. 서비스 timeout을 늘려 오류를 숨기지 않고 provider 응답시간/안정성을 함께 평가한다. 이어 그룹 생성 대상 일괄 접수·완료/부분 실패 집계와 사용자 Profile/Provider 관리가 남아 있다.


## 후속 실환경 재검증 성공

사용자가 ComfyUI 작업 종료를 알린 뒤 queue가 비어 있고 LM Studio가 idle인 것을 확인해 재개했다. `artifacts/backend-pipeline-rest/20260913-133748/report.json`에서 최초/수동 생성, 명시적 묶음 비교, 선택 이미지 재생성→단일 검증→해당 신규 이미지 하나의 묶음 검사, 멱등 접수, Core 재시작 후 이력 및 GPU 반환을 확인했다. 선택 replacement 상태는 completed다. 비교 결과의 incomplete/mismatch는 일관성 판정이며 실행 오류와 구분한다. 이전 timeout/busy 기록은 당시 이력으로 보존하며 신규 전체 연결의 실환경 미검증 상태는 이 기록으로 해소한다.
