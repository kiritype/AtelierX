# 새 생성·전체 후처리·실제 VLM 통합 검증

2026-09-13 사용자 후속 요청으로 Core → Generation → ComfyUI → Validation → LM Studio → Core 저장을 실제 실행했다. **최종 실행에서 PNG와 WebP 모두 합격했고 Core 재시작 후 결과·동일 접수 키도 유지됐다.**

## Generation 후처리 확인 범위

Generation B/E의 `postprocess`를 통해 **Detailer → Censor → Alpha → Encode**를 실행했다. Core의 요청 snapshot과 Generation의 정규화된 설정을 저장하며, 결과 PNG/WebP를 Core REST로 다시 받아 크기와 SHA-256을 확인했다. Detailer의 얼굴·눈·입·손 옵션은 모두 활성화했다.

직전 [일괄 테스트](full-test-report-2026-09-13.md)에서도 각 후처리 및 전체 조합 5건이 이 Backend 경로로 실행됐다. 그때 Vision 부분은 Mock이었으며, 이번 실행이 새 생성·후처리 결과와 실제 LM Studio를 연결한 후속 확인이다.

## 첫 실행에서 발견한 문제와 수정

- seed `2026091301`: 전체 후처리 생성과 PNG 실제 검증 성공. WebP 요청은 Provider HTTP 400, `VAL_PROVIDER_REJECTED`, `outcome=error`로 Core에 기록됐다.
- 별도 로컬 진단 요청에서 LM Studio가 WebP 데이터 URL에 `"'url' field must be a base64 encoded image."`를 반환하는 것을 확인했다. 모든 버전·모델의 WebP 지원 여부로 일반화하지 않는다.
- Validation Provider 설정에 `image_format: "png"`를 추가했다. 원본 WebP를 검사한 뒤 Provider 전송용 데이터만 PNG로 재인코딩한다. 원본 파일·해시·출력 형식·프롬프트는 유지하며, 디코딩된 픽셀·알파를 보존한다. 손실 WebP의 원래 압축 손실을 복원하는 변환은 아니다.
- 변환 후 16 MiB 전송 제한, 설정 변경 fingerprint, 원본/전송 해시 기록을 적용했다. 생략 시 기존 `original` 전달 동작을 유지한다.
- 로컬 설정은 revision 5로 갱신했다. 실패한 작업은 그대로 보존하고 별도 테스트 작업을 명시적으로 실행했다. 오류 후 자동 재전송·재생성은 도입하지 않았다.

## 최종 재실행 결과

seed `2026091302`, WAI Anima, 768×1024, 전체 후처리 활성화. LM Studio는 `http://localhost:1234/v1`, `qwen3-vl-8b-instruct-abliterated`, `json_schema`, `image_format=png`를 사용했다.

| 확인 항목 | 결과 |
|---|---|
| Core → Generation 전체 후처리 생성 | 성공 |
| Core REST PNG/WebP 읽기·크기·해시 | 두 형식 모두 통과 |
| 저장된 실제 positive/negative와 검증 요청 일치 | 두 형식 모두 통과 |
| Generation 이미지 ID·해시 기반 Validation 입력 | 두 형식 모두 통과 |
| 실제 VLM 판정 | PNG passed, WebP passed |
| Core 이미지별 판정 저장 | 통과 |
| 동일 키 재접수 | 기존 검증 반환 |
| Core 재시작 후 결과·동일 키 유지 | 통과 |
| 생성 상태·자동 시도 사용량 | generated / 0 |
| 수정 후 Backend 회귀 검사 | 39/39 통과 |

추가 자동 테스트는 WebP → PNG의 실제 데이터 URL·픽셀·반투명 알파 보존, 원본 WebP 출력 조건 유지, 설정 변경 시 대기 Job의 재전송 방지를 확인한다.

## 증거 및 재현

- [첫 실행 결과](../../artifacts/backend-pipeline-rest/20260913-054016/report.json), [Provider 진단](../../artifacts/backend-pipeline-rest/20260913-054016/webp-provider-diagnostic.txt)
- [최종 실행 결과](../../artifacts/backend-pipeline-rest/20260913-054231/report.json)
- [최종 PNG](../../artifacts/backend-pipeline-rest/20260913-054231/all.png), [최종 WebP](../../artifacts/backend-pipeline-rest/20260913-054231/all.webp)
- 최종 배치 `validation/jobs`의 `provider_image`에서 WebP 원본 해시와 Provider에 전달한 PNG 해시를 구분한다. 세부 증거는 로컬 artifacts이며 Git에서는 제외한다.

```powershell
.venv/Scripts/python.exe -B scripts/test_backend_pipeline_rest.py --cases all --real-vlm --seed 2026091302
```

실행 전에 ComfyUI Queue가 비어 있고 해당 VLM이 IDLE인지 확인한 뒤 VLM을 내려 Generation용 GPU 메모리를 확보했다. 테스트는 생성 종료 후 빈 Queue를 다시 확인해 ComfyUI 메모리를 해제하고 VLM을 호출한다. 이 절차는 시험 도구의 수동 순서 조정이며 제품의 전역 GPU 스케줄러 구현을 의미하지 않는다. 원래 서버·모델 파일·사용자 Workflow는 교체하지 않았다.

이 성공은 샘플 한 장의 두 인코딩에 대한 통합 확인이다. Censor 양성 검출 정확도, 각 Detailer 부위 개선 품질, 묶음 검증·자동 재생성 루프는 별도 범위다. 다음 Backend 작업은 확정된 묶음 검증·재생성·취소 흐름 구현이다.
