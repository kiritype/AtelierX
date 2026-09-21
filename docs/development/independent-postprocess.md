# 저장 이미지 독립 후처리

`POST /v1/images/{image_id}/postprocess-jobs`는 body의 `postprocess`와
Idempotency-Key를 받는다. 파일 경로·URL·임의 graph는 받지 않는다. Generation이
이미 저장한 image ID와 SHA-256, 원래 Anima node inputs를 읽어 같은 검증 pipeline을
재사용한다. source job에 Anima context가 없으면 `GEN_POSTPROCESS_CONTEXT_MISSING`
으로 거절한다.

worker는 저장된 bytes를 ComfyUI `/upload/image`로 올리고, 고정 graph의 첫 노드를
`LoadImage`로 바꾼 뒤 Detailer → Censor → Alpha → Encode 순서를 유지한다. upload
응답 불명확, ComfyUI 오류, 취소는 기존 Job 처리와 GPU permission 경로를 그대로
사용하며 자동 재제출하지 않는다. 실제 ComfyUI/GPU 검증은 별도 순차 작업이다.


## 통합 검토와 실제 실행

주 에이전트 검토에서 실행 직전 원본 hash 검사가 빠진 것을 보완했다. 고정 source image ID로 재조회하고 SHA-256을 검사하며 PNG/WebP MIME·확장자를 보존한다. LoadImage 등록과 Detailer 자원을 검사한다. 멱등 조회는 파일 검사보다 먼저 수행하여 완료된 요청의 재조회가 원본 파일 정리에 좌우되지 않도록 했다.

실제 테스트 스크립트: `scripts/test_independent_postprocess_rest.py`.

- `artifacts/independent-postprocess-rest/20260913-132237/report.json`: 기존 PNG 및 WebP를 각각 Encode하여 출력 hash/출처 보존 확인.
- `artifacts/independent-postprocess-rest/20260913-132347/report.json`: 각 원본에 Detailer→Censor→Alpha→Encode 실행 성공, 총 4개 최종 PNG/WebP 조회/hash 확인, Core GPU 권한 반환 확인.

이 시험은 파이프라인 실행·결과 전달을 검증하며 Censor 검출률이나 Detailer/Alpha 개선 품질의 일반 평가를 대신하지 않는다. ComfyUI 직접 출력은 `C:/StabilityMatrix/Packages/ComfyUI/output/AtelierX` 아래이며 API 보관본은 위 artifact의 generation/images에 있다.
