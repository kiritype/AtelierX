# 재생성 구현 및 검증 — 2026-09-13

ADR-0003/0017의 수동 요청, 자동 상한, 이력, 중단 정책을 Core에 구현했다. 클라이언트는 REST로 요청하고 표시한다. 별도 승인 항목을 추가하지 않았다.

- 수동 재생성은 횟수 제한 없이 새 Task/이미지/cycle을 생성한다. 기본 seed는 변경되며 원본 프롬프트는 유지한다.
- 자동은 초기/수동 시점에 고정한 설정(기본 5회)을 사용한다. 실제 실행이 확인될 때만 사용 횟수를 원자적으로 저장한다.
- provider/파싱 오류, 제안 없음/무효/충돌, 상한 도달 및 중단은 추가 실행을 만들지 않는다.
- SQLite의 regeneration_cycles 및 Task lineage로 재시작 후 이력과 집계 중복 방지를 지원한다.
- 자동 변경은 evidence에 연결된 seed/steps/cfg로 한정한다. 프롬프트/모델/LoRA 변경, 묶음 검증 기반 재생성은 후속 범위다. 제안의 실제 개선 효과는 아직 평가하지 않았다.

## 검증

`python -B -m unittest discover -s tests -q`: 58개 통과. 수동 REST/멱등성/재시작, 자동 실제 실행 응답 집계, 상한, 비활성, 0회, 검증 오류, 제안 검증, 실행 전후 취소 및 실행 후 실패를 확인했다. 자동 실패·상한 시나리오는 결정적인 테스트 fixture를 사용한다.

실제 환경:

```
python -B scripts/test_backend_pipeline_rest.py --cases encode --real-vlm --automatic --manual-regeneration --seed 2026091312 --character-negative beard
```

ComfyUI Anima 최초 생성과 수동 재생성이 성공했고, 각 PNG/WebP 총 4개가 LM Studio 검증에서 passed였다. 새 Task/이미지 ID, 수동 자동사용량 0, Core 재시작 후 검증 Run 보존 및 GPU owner/waiting 해제를 확인했다. 이번 실제 시험은 Encode 경로이며 다른 후처리 전체 재시험은 포함하지 않는다.

결과: `artifacts/backend-pipeline-rest/20260913-125838/report.json`. 앞선 신규 평가 계약 단독 시험: `artifacts/backend-pipeline-rest/20260913-125724/report.json`.

API: [별도 REST 명세](../api/rest-api.md). 다음 구현 대상은 묶음 검증과 문제 이미지의 선택적 후속 요청이다.
