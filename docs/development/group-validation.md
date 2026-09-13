# 묶음 검증 구현 · 2026-09-13

Core 기준 revision/이미지 자격 검사/고정 요청/선택 재검증/현재 집계와 Validation의 여러 이미지 비교 REST 경로를 구현했다. 묶음 불일치로 자동 재생성하지 않는다. 상세 계약과 아직 없는 자동 연결은 [API 명세](../api/rest-api.md)에 기록했다.

실제 GPU 통합 시험:

```
python -B scripts/test_backend_pipeline_rest.py --cases encode --real-vlm --automatic --manual-regeneration --group-validation --seed 2026091312 --character-negative beard
```

`artifacts/backend-pipeline-rest/20260913-130948/report.json`: 최초/수동 생성의 PNG·WebP 총 4개 단일 검증 passed. 서로 다른 생성 이미지 2장의 묶음 비교는 실행 성공, 결과 mismatch. 상의/장식 차이와 하의 비교 불충분을 evidence에 기록했다. Core 재시작 후 결과 보존, GPU 반환 확인. 이는 provider 판정 정확도의 일반적 보장이 아니다. 실제 이 결과에서 appearance 근거에 상의 관찰도 섞여 있어 feature별 근거 분리 품질은 후속 평가가 필요하다.

앞선 `20260913-130744` 시험은 provider 근거 형식 오류였다. reference_refs JSON Schema에 실제 참조 ID enum을 추가한 뒤 재시험이 성공했다. 잘못된 응답을 합격/비교 불충분으로 변환하지 않았다. 원본 구조화 provider_assessments도 Job에 보관해 계약 오류를 진단할 수 있다.

## 기준 후보와 선택 재생성 연결

`GET /v1/groups/{id}/reference-candidate`는 단일 검증이 passed인 이미지의 실제 evidence에서 빈 관찰·위치를 제외하고, 그룹의 `appearance`/`upper`/`lower` 용어와 겹치는 가시 근거를 계산한다. 후보는 가시 component 수, matched evidence 수, 생성 시각, image ID의 고정 순서로 정렬한다. 대표가 놓친 component만 최대 두 보조로 채운다. 가시 근거가 부족하면 `insufficient_reference_evidence`를 반환하며, 기존 기준은 `existing_reference_retained`로 보존한다. 이 조회는 기준 저장·교체·검증 실행을 하지 않는다. 현재 기준의 reference conflict도 자동 다수결로 해소하지 않는다.

`POST /v1/groups/{id}/replacements`는 사용자가 명시한 target image와 reference revision, 단일 검증 선택, 묶음 검증 선택을 고정한 수동 재생성이다. 접수한 원본은 즉시 과거 대상으로 표시하고, 새 Task의 **같은 출력 순번과 media type**만 새 대상으로 연결한다. 따라서 PNG/WebP 같이 한 Task에서 나온 파생 출력이나 이전 시도를 다른 대상과 바꾸지 않는다. 새 출력이 단일 검증을 통과하고 기준 revision이 아직 같을 때만 새 이미지 하나를 묶음 검증에 접수한다. 기준 변경·출력 불일치·실패·취소는 저장된 오류/상태로 끝나며 묶음 불일치 자체는 재생성을 시작하지 않는다.

각 선택 재생성 record는 요청 key, 기준 snapshot, 원본 sha256·출력 순번·media type, **고정된 regeneration/단일 검증 snapshot과 묶음 profile/provider/endpoint snapshot**, replacement Task/image, 단일 run, group run을 보관한다. record를 먼저 저장한 뒤 내부 멱등 키로 Task를 만들므로 재시작과 같은 key 재시도에서 중복 generation 또는 group provider 호출을 피한다. 접수 뒤 현재 등록 profile/provider가 바뀌어도 record의 고정 snapshot을 사용한다.

단일 검증의 정상 자동 재생성 cycle이 자식 Task를 만들면 record는 cycle의 `active_task_id`를 따라가고 이전 Task/image를 이력에 남긴다. 그 자식의 같은 출력 순번·media type이 단일 통과해야만 묶음 검증 대상이 된다. replacement Task와 그 자동 자식의 선택하지 않은 파생 출력은 현재 대상에서 제외하지만, 원본 Task의 선택하지 않은 PNG/WebP는 독립 대상 상태를 유지한다. Task가 실제로 만들어지기 전 `creating` record는 기준 변경을 다시 확인하며, 시작 거부/기준 stale로 Task가 없으면 원본을 현재 대상으로 되돌린다.

회귀: `tests/test_core_groups.py`는 기준 revision/이미지 자격/멱등성/선택 대상/부분 오류/현재 기준 집계/취소·재시작 외에 evidence 가시성 부족, 고정 tie-break, 기존 기준 자동 교체 금지, 선택 대상만 과거 처리, 기준 변경 경쟁, frozen profile 변경 뒤에도 기존 revision 사용, 새 PNG 대상의 단일 통과 후 묶음 검증 연결, 자동 단일 재생성 자식 추적, 비선택 WebP 제외, 반복 tick/재시작의 중복 요청 방지를 확인한다. 이 변경은 Core/API 회귀이며 실제 GPU·ComfyUI·LM Studio 호출은 수행하지 않았다. 실제 시험에서는 등록된 단일/묶음 profile로 선택 재생성 한 건을 실행하고, 새 image ID만 group run target으로 기록되는지와 기준 변경 시 `stale_reference` 종료를 확인해야 한다.


## 통합 최종 결과

묶음 후속 보완을 포함한 Backend 전체 회귀 93개 통과. 선택 재생성 신규 전체 실환경 시험은 LM Studio timeout 후 다른 ComfyUI 작업 실행으로 완료하지 못했다. 이전 명시적 묶음 검증 성공과 구분하며 [병렬 구현 보고서](parallel-backend-validation.md)에 상세 결과와 재개 명령을 기록했다.


## 후속 실환경 재검증 성공

사용자가 ComfyUI 작업 종료를 알린 뒤 queue가 비어 있고 LM Studio가 idle인 것을 확인해 재개했다. `artifacts/backend-pipeline-rest/20260913-133748/report.json`에서 최초/수동 생성, 명시적 묶음 비교, 선택 이미지 재생성→단일 검증→해당 신규 이미지 하나의 묶음 검사, 멱등 접수, Core 재시작 후 이력 및 GPU 반환을 확인했다. 선택 replacement 상태는 completed다. 비교 결과의 incomplete/mismatch는 일관성 판정이며 실행 오류와 구분한다. 이전 timeout/busy 기록은 당시 이력으로 보존하며 신규 전체 연결의 실환경 미검증 상태는 이 기록으로 해소한다.
