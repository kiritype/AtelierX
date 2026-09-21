# 묶음 일관성 대조 검증 — 2026-09-13

## 범위와 고정 기대값

기존 이미지를 재사용하고 추가 생성·편집 없이 로컬 LM Studio의 `qwen3-vl-8b-instruct-abliterated`로 실행했다. 원본 프롬프트와 SHA-256을 보존하고 격리 Validation REST 저장소 및 Core GPU 조정을 사용했다. 비교 기대값은 실행 전에 report의 case_manifest에 저장했다.

| 대조 사례 | 고정 기대값 | v7 실제 |
| --- | --- | --- |
| 같은 이미지, 다른 ref ID | matched | matched |
| bob/긴 머리 | mismatch | mismatch |
| 표정이 다른 두 이미지의 상의만 비교 | matched | 응답 오류 |
| 상반신 이미지의 보이지 않는 검은 부츠 | insufficient | insufficient |
| 흰 티셔츠/파란 재킷 | mismatch | mismatch |
| 서로 다른 상의의 두 기준 | reference_conflict | matched 오판 |

v7은 기대 일치 4/6이며, 상의 비교는 차이 근거가 없는 mismatch를 반환해 `VAL_PROVIDER_RESPONSE_INVALID`로 처리됐다. 기준 충돌 사례는 보조 기준을 누락한 합격 응답이었다. 결과: `artifacts/group-consistency-cases/20260913-145734/report.json`. 이 실행은 GPU owner/waiting/blocked가 비어 종료됐다.

## v8 보완 및 회귀

reference_observed를 기준 ID별 관찰 객체로 분리했다. 합격은 모든 기준에 대한 근거가 있어야 하며 중복 ref, 대상 ID 혼입, 모순된 차이 근거는 오류다. appearance/upper/lower 범주를 독립 평가하고 기준 간 충돌을 대상 평가보다 먼저 확인하도록 지시했다. 판정을 문자열 키워드로 고치거나 특정 이미지의 정답을 코드에 넣지 않았다. 요청 API는 유지하고 응답 evidence 변경은 별도 REST 명세에 기록했다. 과거 완료 이력은 유지하고 구버전 대기 작업은 평가 버전 변경 오류로 종료한다.

첫 v8 실행은 느슨한 응답 Schema로 인해 대상 ID 혼입·중복 ref·필수 범주 누락이 발생해 6건 모두 응답 오류였다. 기록: `artifacts/group-consistency-cases/20260913-150054/report.json`. 이후 Schema에 허용 기준 ID, 필수 관찰 키, 평가 개수 및 참조 최대 개수를 명시했다.

전체 회귀 테스트는 131개 통과(16.519초). 이는 계약/흐름 검증이며 VLM 정확도와 구분한다.

## 해석 제한

상의만 비교한 표정 변화 사례는 전체 외형이 동일한 표정 전용 대조가 아니다. 두 원본의 머리 길이가 다르므로 상의 범주에 한정했다. 가림 사례도 물체에 가린 이미지를 사용한 것이 아니라 화면 밖 하의가 보이지 않는 사례다. 부분 가림, 동일 외형의 다양한 표정, 더 많은 캐릭터와 보조 기준은 후속 검증 범위다. 이 결과만으로 묶음 품질 검증 완료를 선언하지 않는다.

## 최신 실제 실행과 남은 문제

최신 v8 결과: `artifacts/group-consistency-cases/20260913-150217/report.json`. 동일 이미지 matched, 머리 길이 mismatch는 기대와 일치했다. 세 번째 상의 비교는 약 180초 뒤 `failed / outcome=error / VAL_PROVIDER_TIMEOUT`으로 종료됐다. 나머지 세 사례는 실행하지 않았으며 자동 재전송·재생성도 하지 않았다. 따라서 최종 구현의 실제 품질 검증은 **2건 일치, 1건 timeout, 3건 미실행**이다. 앞선 v7의 4/6 결과를 v8 최종 결과로 간주하지 않는다.

후속 읽기 전용 확인은 `postflight.json`에 보존했다. LM Studio 모델은 idle/queued=0, ComfyUI 실행/대기 Queue는 비어 있었다. 격리 시험 Core DB에는 timeout 당시 validation GPU owner가 유지되어 있다. 실제 provider 종료가 불명확할 때 권한을 자동 해제하지 않는 기존 정책 결과이며, 시험 서버는 종료했다. 이 DB를 다시 사용하는 경우 종료 상태를 진단한 뒤 기존 복구 절차를 적용해야 한다. 현재 사용자 ComfyUI 설정과 원본 Core 데이터는 변경하지 않았다.

Group provider 요청에는 응답 생성 토큰 상한이 없고 frozen timeout=180초만 적용된다. 수신 응답 1MiB 제한은 모델 생성 중 연산량을 제한하지 않는다. 관찰된 timeout의 원인을 토큰 상한 부재만으로 단정할 수 없지만 다음 개선은 Provider의 유한 응답 토큰 설정과 snapshot 반영, 종료/파싱 오류 계약 시험이다. 그 후 동일 6개 고정 대조를 다시 실행해 범위 분리·기준 충돌의 실제 정확도를 확인한다. 현재 v8의 정상 판정 안정성은 미완료다.

## 응답 토큰 상한 후속 — 2026-09-13

Provider에 선택 `max_tokens`를 추가했다. Core 설정 revision·복제·보관·실행 snapshot, Validation registry 및 단일/묶음 HTTP 요청에 값을 전달한다. bool/0/음수/실수와 snapshot/config 값 불일치는 거부한다. 생략한 과거 revision 및 fingerprint는 유지한다. `finish_reason=length`는 내용이 JSON이어도 응답 오류로 처리하고 자동 재시도하지 않는다. 단일 `provider_response`, 묶음 대상별 `provider_responses`에 종료 사유와 숫자 토큰 사용량을 보존한다. 1024는 이번 시험값이며 전역 기본값으로 확정하지 않았다.

전체 회귀 **135개 통과(14.009초)**. 새 설정 고정, 상한 전달, 잘린 응답의 오류 처리, legacy 생략 동작을 포함한다. 정상 사용자 설정 파일을 수정하지 않고 진단 전용 `local-vision-bounded` revision 1을 사용했다.

### json_schema, max_tokens=1024

결과: `artifacts/group-consistency-cases/20260913-151116/report.json`.

| 사례 | 실제 결과 | 소요 시간 | 응답 토큰 |
| --- | --- | --- | --- |
| 동일 이미지 | matched, 기대 일치 | 4.078초 | 277 |
| 머리 길이 차이 | mismatch, 기대 일치 | 4.031초 | 299 |
| 상의만 비교 | 응답 상한 오류, 기대 불일치 | 10.125초 | 1024 |
| 화면 밖 하의 | insufficient, 기대 일치 | 3.063초 | 153 |
| 상의 변경 | mismatch, 기대 일치 | 4.015초 | 236 |
| 기준 간 상의 충돌 | mismatch 오판, 기대는 reference_conflict | 3.016초 | 209 |

이번에는 6건 모두 실행했으며 기대 일치 4, 실행 오류 1, 의미 판정 오류 1이다. 상의 사례가 이전 180초 timeout 대신 `finish_reason=length / VAL_PROVIDER_RESPONSE_INVALID`로 약 10초에 종료됨을 확인했다. 이는 종료 제어 개선이며 상의 일관성 판정 문제의 해결은 아니다. 기준 충돌 사례는 보조 기준을 실제로 관찰했지만 대상 mismatch로 분류해 정책상 잘못된 결과다. 문자열 근거를 보고 서버가 임의로 reference_conflict로 바꾸지 않았다. 완료 후 GPU owner/waiting/blocked는 비어 있었다.

### 명시적 json_object 비교

`--response-format json_object --max-tokens 1024`로 별도 진단 설정을 선택했다. 결과: `artifacts/group-consistency-cases/20260913-151240/report.json`. 6건 모두 현재 LM Studio에서 HTTP 400으로 거부되어 `VAL_PROVIDER_HTTP_ERROR`로 기록됐다. 모델의 이미지 판정 정확도 결과로 집계하지 않는다. 제품의 자동 fallback이 아니라 독립한 시험 요청이며 기존 json_schema 설정은 유지했다. GPU 권한은 정상 해제됐다.

### 현재 결론과 다음 작업

토큰 상한·snapshot·잘린 응답 처리 구현은 검증됐다. 현재 8B 모델의 상의 범위 한정 및 기준 충돌 판정은 여전히 미완료다. 현 설정의 묶음 판정을 무인 운영에 적합하다고 보고하지 않는다. 다음 검증 후보는 기준끼리의 비교를 대상 비교와 분리한 평가 방식과 동일 고정 사례에 대한 다른 VLM의 비교다. 이는 이번에 구현하거나 모델을 다운로드한 기능이 아니며, 모델 교체 없이 현재 결과를 합격으로 보정하지 않는다. 기존 표정 전용/부분 가림 평가의 제한도 유지한다.

## 기준 간 비교 분리 v9 — 2026-09-13

대표·보조의 모든 기준 쌍을 먼저 비교하도록 구현했다. 쌍별 실제 mismatch feature를 기준 충돌로 집계하며, 대상 판정을 재해석하지 않는다. 요청 전 실행 단계를 저장하고 원본 pair evidence/진단을 따로 보존한다. 충돌 시 대상 bytes/hash/access는 확인하되 대상 VLM 호출은 하지 않는다. 사전 비교 오류는 대상별 오류로 표시하며 합격으로 진행하지 않는다. 보조가 없는 기존 경로와 timeout/취소/이력 보존 정책은 유지한다. 기준 자료를 더 요청하므로 보조가 2장일 때 최대 3개의 추가 비교 호출이 생긴다.

Core의 기존 evidence 정규화와 호환되도록 feature/status/관찰/차이/ref 필드를 유지했다. 대상 미비교는 `target_not_compared=true`로 명시하며 충돌하지 않은 나머지 feature도 비교하지 않았다면 insufficient다. pair 원문의 'target'은 두 번째 기준을 뜻한다. UI는 이를 '기준 간 차이'로 표시하고 실제 대상의 결함으로 재서술하면 안 된다.

전체 회귀 **143개 통과(16.944초)**. 기준 쌍 전체 검사, 불충분·오류·timeout·대상 파일 실패, 재시작 이력, Core 결과 수용을 포함한다.

실제 결과: `artifacts/group-consistency-cases/20260913-152322/report.json`, group evaluation 9, local 8B, json_schema, max_tokens=1024. 기존 6건은 5건 기대 일치/1건 오류이고, 추가 정상 기준 대조 1건도 통과해 **총 7건 중 6건 기대 일치, 1건 실행 오류, 의미 판정 오판 0건**이다.

| 사례 | v9 결과 | 시간 | 기준/대상 VLM 호출 수 |
| --- | --- | --- | --- |
| 동일 이미지 | matched | 4.031초 | 0 / 1 |
| 머리 길이 차이 | mismatch | 3.032초 | 0 / 1 |
| 상의만 비교 | 토큰 상한 오류 | 10.093초 | 0 / 1 |
| 화면 밖 하의 | insufficient | 2.016초 | 0 / 1 |
| 상의 변경 | mismatch | 3.016초 | 0 / 1 |
| 기준 간 상의 충돌 | reference_conflict | 3.000초 | 1 / 0 |
| 정상 기준 사전 비교 후 대상 비교 | matched | 7.062초 | 1 / 1 |

추가 정상 대조는 같은 원본 bytes에 서로 다른 ref ID를 준 진단용 양성 대조이며, 서로 다른 정상 캐릭터 이미지 여러 장에 대한 정확도를 뜻하지 않는다. 실환경은 Validation REST와 Core GPU 조정을 실행했고, Core 묶음 결과 수용은 회귀 시험으로 확인했다. 전체 Core 생성→실제 VLM 묶음 실행을 이번 7건에서 다시 생성한 것은 아니다. 종료 시 GPU owner/waiting/blocked는 비어 있었다. 원본 생성 이미지·과거 결과와 사용자 설정을 보존했다.

현재 남은 검증 문제는 상의 범위만 지정한 정상 대조에서 모델 응답이 1024토큰 상한에 도달하는 현상이다. 합격으로 보정하거나 상한을 무제한 늘리지 않았다. 다음은 이 사례의 범위별 입력/응답을 분리해 검사하고, 독립적인 표정·부분 가림 대조 데이터를 확보하는 작업이다. 기존 한정 데이터의 성공률을 전체 품질 보장으로 확대하지 않는다.
