# LM Studio 실제 Vision 검증

2026-09-13 사용자 실행 지시에 따라 실제 로컬 모델에 이미지와 Prompt를 전송했다. 모의 Provider 시험과 구분한다.

- API base: `http://localhost:1234/v1`
- 서버 모델 ID: `qwen3-vl-8b-instruct-abliterated`
- 인증: 사용자가 지정한 로컬 키. `.atelierx/validation-config.json`에 설정.
- 입력: 이전 Core 생성·Detailer 결과 `artifacts/backend-pipeline-rest/20260913-042429/detailer.png`, 768×1024. 은색 머리·파란 눈·흰 상의·파란 재킷·브로치가 보이는 상반신 이미지.
- 실제 생성 Prompt는 기존 작업 스냅샷에서 읽었다. 진단용으로 바꾼 Prompt는 별도 Validation 테스트 요청에만 사용했으며 Core의 생성 이력을 수정하지 않았다.

## API 호환 수정

첫 요청은 HTTP 400으로 거절됐다. LM Studio 응답은 `response_format.type`으로 `json_schema` 또는 `text`를 요구했다. 기존 `json_object`는 해당 서버에서 사용할 수 없었다.

Provider 설정에 `response_format` 선택을 추가하고 이 로컬 Provider는 `json_schema`로 변경했다. Schema로 outcome·findings·regeneration 구조를 지정하고 서버 결과를 다시 엄격하게 검사한다. 응답 형식은 설정 fingerprint에 포함하며 요청 실패 후 자동 Fallback/재전송은 하지 않는다. 수정 후에는 별도의 새 테스트 실행을 접수했다.

참고: [LM Studio 공식 Structured Output 문서](https://lmstudio.ai/docs/developer/openai-compat/structured-output).

## 관찰 결과

| 입력 Prompt | 모델 결과 | 평가 |
| --- | --- | --- |
| 실제 생성 Prompt | passed | 확인한 외형·의상에 부합하는 기준 사례 |
| 은색 머리 → 빨간 머리, 파란 눈 → 초록 눈으로 바꾼 진단 Prompt | failed | 머리색·눈색 불일치를 각각 올바르게 지적 |
| 실제 Prompt 끝에 `clearly visible black boots` 추가 | passed | **오판**. 신발이 보이지 않으므로 ADR-0004에 따라 불합격이어야 함 |

출력 JSON과 오류 정규화는 동작했지만, 이 세 사례만으로 모델 품질을 보장할 수 없다. 특히 Prompt 내 명시 요소의 화면 밖 누락을 합격시키는 문제가 남았다. 현재 시스템 지침에 누락·가림·화면 밖 요소를 불합격으로 처리하도록 명시했는데도 이 사례를 놓쳤다. 이 결과를 자동 재생성 또는 이미지 채택 정확도가 검증된 상태로 보고하지 않는다.

초기 거절 기록: `artifacts/lmstudio-validation/20260913-044343/report.json`.
호환 수정 후 세 사례: `artifacts/lmstudio-validation/20260913-044519/report.json`.
재현 스크립트: `scripts/test_lmstudio_validation.py`.

회귀 테스트는 총 32개 통과했다. LM Studio용 schema 요청과 HTTP 거절 시 자동 형식 변경/재전송 금지를 추가 확인했다. 단위 테스트 통과와 실제 VLM 판정 품질은 별개다.

GPU 사용량은 실행 전 7,959MiB, 모델 로드 후 관찰 시 23,873MiB / 24,564MiB였다. 이는 전체 GPU 점유량이며 특정 모델 단독 사용량은 아니다. ComfyUI 작업이 없는 상태에서 순차 실행했고 새 이미지 생성·자동 재생성은 수행하지 않았다.

다음 검토는 요소별 관찰 근거를 구조화해 누락을 판정에 반영하는 방식과 추가 평가 이미지 세트다. 단일 성공 사례에 맞춘 Prompt 조정만으로 해결 완료를 선언하지 않는다.

## 항목별 근거 검증 후속 변경

[평가 방식 v2와 실제 재평가](validation-element-evidence.md): Prompt 항목마다 관찰 근거를 반환하고 Validation이 최종 판정을 집계한다. 이전 화면 밖 부츠 오판은 동일 사례 재검증에서 불합격으로 처리됐다. 다른 이미지에서의 일반화는 아직 검증하지 않았다.
