# 전체 테스트 일괄 실행 결과 — 2026-09-13

현재 구현된 범위의 기존 자동 검사와 로컬 REST 실행 스크립트를 일괄 실행했다. **실행 명령 21개 모두 정상 종료했고, 결과 JSON을 별도로 확인했을 때 실패한 실행이나 기대 판정 불일치는 없었다.** 미구현 기능까지 완료됐다는 의미는 아니다.

실행 시간대는 약 05:31–05:35 KST이며 명령 실행 시간 합계는 176.72초다. 준비·결과 검토 시간은 제외한다. ComfyUI 캐시를 유지했으므로 이 시간은 신규 추론 성능 벤치마크로 사용할 수 없다.

## 결과

| 범위 | 결과 | 확인 내용 |
|---|---:|---|
| Backend 자동 테스트 | 38/38 통과 | Core 9, Core–Validation 5, Generation 6, 후처리 4, Validation 8, 항목별 근거 6 |
| Custom Node 자동 테스트 | 55/55 통과 | Anima 17, Alpha 11, Censor 7, Detailer 8, Encode 7, Upscale 5 |
| 예제 구조 검사 | 6/6 통과 | 각 Node의 예제·템플릿 구조 검사; 실제 UI 실행과 구분 |
| 문서 계약 검사 | 18/18 통과 | Proposed 계약 모델·Schema·예제 일치; 제품 API 전체 구현 검증과 구분 |
| 실제 생성·후처리 REST | 19/19 성공 | 기본·다중 LoRA 생성 2, Core 생성 1, 보조 처리 7, 참조 검출기 4, Backend 파이프라인 5 |
| Mock Vision 통합 | 2/2 기대 동작 | 합격 저장, 파싱 오류 저장 및 자동 재생성 없음 |
| 실제 LM Studio 평가 | 기대 지정 13/13 일치 + 원본 기준 사례 합격 | 기존 이미지 3장에 총 14조건; 평가 방식 v3 |

자동 테스트는 총 111개이며 이 중 18개는 문서 계약 검사다. 단위 테스트의 장애·Provider 시나리오는 Mock을 사용하므로 실제 외부 서비스 장애 실험으로 해석하지 않는다.

## 실제 동작에서 확인한 사항

- Anima 기본·다중 LoRA 생성: 768×1024 PNG 생성, 파일 해시, 동일 키 재접수와 충돌 처리.
- Core: 작품/캐릭터/의상 관리, 프롬프트 고정, upper body에서 하의·풋웨어 제외, 이미지 저장, 재시작 후 상태·중복 접수 유지.
- Alpha: 지정 마스크의 알파 0/128/255 보존 및 실제 인물 검출 연결.
- Censor: 지정 마스크에 mosaic/white/white_solid 처리를 적용했을 때 픽셀 변경 확인. 사용자 제공 검출 모델을 사용하는 자동 처리 3종도 정상 실행.
- Detailer: 얼굴 처리 및 얼굴·눈·입·손 옵션을 활성화한 파이프라인 실행.
- Encode: PNG/WebP 저장·다시 읽기. Backend 파이프라인 5개 조합에서도 두 형식의 크기·해시 확인.
- Core → Generation → ComfyUI 후처리 → 이미지 저장 → Validation → Core 결과 저장 연결. 이 통합의 Vision 응답은 Mock이며 실제 LM Studio 평가는 별도 Validation 실행이다.
- 의도적으로 잘못된 Vision 응답을 주었을 때 `outcome=error`, `VAL_PROVIDER_RESPONSE_INVALID`를 저장했다. 생성 Task는 `generated`, 자동 시도 사용량은 0을 유지했고 Provider 호출도 시나리오당 한 번이었다.
- 모든 후처리를 적용한 최종 PNG를 열어 인물 이미지가 정상 표시되는 것도 확인했다. 경계·검출 정확도의 정량 평가를 대신하지 않는다.

## LM Studio 결과

`http://localhost:1234/v1`, `qwen3-vl-8b-instruct-abliterated`, `json_schema` 설정을 사용했다. API key는 사용자 지정 로컬 값 `lm-studio`다.

| 평가 묶음 | 관측 결과 |
|---|---|
| 원본 생성 프롬프트 1조건 | 합격; 이 스크립트의 기대값 필드는 비어 있어 13건 일치율 집계에서는 제외 |
| 진단 4조건 | 잘못된 머리/눈 색, 보이지 않는 부츠, 없는 우산, 네거티브로 금지한 머리핀 모두 불합격 |
| 추가 이미지 9조건 | 원본 2, 작은 액세서리, 가중치 괄호 묶음은 합격. 없는 모자, 틀린 머리색, 가려진 눈, 화면 밖 부츠, 금지한 파란 의상은 불합격 |

기존 작은 귀걸이·가중치 묶음 회귀 사례도 이번 실행에서 통과했다. 이미지 3장의 제한된 반복 평가이며 일반적인 정확도나 다른 모델의 결과를 보장하지 않는다. 새로 생성한 모든 출력 이미지에 실제 VLM 검증을 붙인 종단 간 시험은 이번 범위에 포함되지 않았다.

## 미검증·미구현 범위

- **Upscale 실제 추론:** ComfyUI의 `UpscaleModelLoader` 모델 선택지가 비어 있으며 AtelierX Upscale도 설치되어 있지 않다. 단위·템플릿 검사만 통과했다.
- **Censor 검출 정확도:** 옷을 입은 음성 대조 이미지에서 자동 검출 마스크가 3종 모두 0이었다. 실제 검열 대상의 재현율·오탐률은 평가하지 않았다.
- **Detailer 품질:** 입은 얼굴 검출 fallback을 사용한다. 모든 옵션 실행 성공이 각 부위 검출·개선 성공을 의미하지 않는다.
- **제품 기능:** 묶음 일관성 검증, 자동 재생성 전체 루프, 취소·전역 GPU 조정, 독립 이미지 후처리 API, SDXL, 제품 CLI/Shared Client·Frontend는 이번 완료 판정 대상이 아니다.
- **환경/내구성:** 외부 AI API 실제 호출, 장시간 부하, 강제 종료·전원 장애, 설치 초기 상태 재현은 실행하지 않았다. 복구 자동 테스트와 Core 정상 재시작 검증은 위 결과에 포함된다.
- **UI:** 이번에는 ComfyUI REST 실행과 예제 구조를 검사했다. 브라우저에서 버튼을 누르는 UI 회귀는 재실행하지 않았다. 기존 UI 실행 이력은 [보조 노드 실행 기록](postprocess-live-validation.md)에 있다.

## 증거와 출력 위치

종합 JSON과 각 명령의 로그: [이번 배치 폴더](../../artifacts/full-suite/20260913-batch/), [종합 JSON](../../artifacts/full-suite/20260913-batch/summary.json).

- [Generation 결과](../../artifacts/generation-rest/20260913-053203/report.json)
- [Core 결과](../../artifacts/core-rest/20260913-053222/report.json)
- [후처리 결과](../../artifacts/postprocess-rest/20260913-053232/report.json)
- [자동 검출기 결과](../../artifacts/postprocess-rest/20260913-053245/report.json)
- [Backend 파이프라인 결과](../../artifacts/backend-pipeline-rest/20260913-053307/report.json), [전체 후처리 PNG](../../artifacts/backend-pipeline-rest/20260913-053307/all.png)
- [LM Studio 기본·진단 결과](../../artifacts/lmstudio-validation/20260913-053349/report.json)
- [추가 이미지 평가 결과](../../artifacts/validation-generalization/20260913-053430/report.json)

위 artifacts는 로컬 실행 산출물이며 Git에서 제외한다. ComfyUI 영구 출력은 `C:\StabilityMatrix\Packages\ComfyUI\output\AtelierX`, 테스트 복사본은 위 `artifacts` 하위에 있다. 전체 경로 안내는 [이미지 출력 경로](output-paths.md)를 따른다.

## 실행 환경과 재실행

Backend는 저장소 `.venv`, Node·계약 검사는 설치된 ComfyUI의 Python을 사용했다. GPU는 RTX 4090 24GB다. 실행 전 빈 ComfyUI Queue와 IDLE 상태의 VLM을 확인하고 해당 VLM만 내려 GPU 실행을 순차 진행했다. 이후 ComfyUI의 모델 캐시를 해제하고 VLM 평가를 실행했다. 종료 시 ComfyUI Queue는 비어 있고 같은 VLM이 다시 로드되어 IDLE 상태였다. 서버나 기존 Workflow를 교체하지 않았다.

[일괄 실행기](../../scripts/run_test_suite.py)는 `--phase cpu`, `--phase generation`, `--phase vision`을 각각 실행하며 `--output`으로 새 배치 폴더를 지정한다. GPU 메모리 전환은 자동화하지 않았으므로 Queue 확인과 모델 메모리 확보 후 generation → vision 순으로 실행해야 한다. 실행기는 명령 종료 코드를 기록하므로 품질 스크립트의 JSON 기대값도 별도로 확인해야 한다. 이번 보고서는 그 추가 확인까지 수행했다.

다음 권장 작업은 새 생성 출력에 실제 VLM을 연결한 종단 간 검증을 보강하고, Backend의 묶음 검증·재생성·취소 구현으로 이어가는 것이다.
