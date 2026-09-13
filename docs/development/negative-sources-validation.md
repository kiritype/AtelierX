# Negative 출처 분리 구현·검증 — 2026-09-13

[ADR-0023](../architecture/adr/0023-negative-prompt-sources.md) 및 [REST API 명세](../api/rest-api.md)를 구현했다. 전역 Negative는 생성 전용이고 캐릭터 Negative만 금지 요소 판정에 사용한다. Core 캐릭터 생성/PATCH·revision·시도 snapshot·실제 생성 문구·Validation 출처 전달을 연결했다.

기존 저장 문서는 JSON 필드를 추가하는 방식으로 호환하며 DB 테이블 변경은 없다. 기존 캐릭터는 Negative 빈 값, 기존 Task Negative는 전역으로 취급한다. 이미 완료된 결과를 다시 쓰지 않고 새 검증은 평가 v4로 실행한다. 캐릭터 변경 후 이전 preview hash 제출은 충돌, 이미 제출된 Task는 과거 원문 유지다.

## 결과

- Backend 자동 테스트 **42/42 통과**. 출처 합성 불일치 거절, 전역 문구 Provider 전달 제외, 캐릭터 금지 요소 불합격, 캐릭터 편집/기존 snapshot/preview 충돌, WebP 변환 등 확인.
- [실제 VLM 출처 대조](../../artifacts/lmstudio-validation/20260913-055543/report.json): 동일 이미지의 hairpin을 character에 넣으면 **failed**, global에 넣으면 **passed**. 직접 Validation 진단 입력이므로 Core의 Positive 충돌 차단을 우회해 평가 동작만 확인한 사례다.
- [새 전체 흐름](../../artifacts/backend-pipeline-rest/20260913-055624/report.json): seed 2026091303, 캐릭터 Negative `beard`, 전역 `blurry, low quality`. 생성 → Detailer → Censor → Alpha → Encode → 실제 LM Studio → Core 저장/재시작. PNG/WebP 모두 **passed**, 해시·실제 Prompt 일치, 멱등 키·결과 유지, 자동 시도 사용량 0.
- [최종 PNG](../../artifacts/backend-pipeline-rest/20260913-055624/all.png), [최종 WebP](../../artifacts/backend-pipeline-rest/20260913-055624/all.webp).

이전 진단/일반화 스크립트도 캐릭터 검사 대상 출처를 명시하도록 변경했다. 전체 9조건 일반화는 이번 변경에서 재실행하지 않았으며 위 결과로 대체 주장하지 않는다. 현재 안내는 대표 추상 용어·정확한 항목 충돌만 다룬다. 자연어의 모든 금지 문구를 분류하거나 모든 동의어 충돌을 탐지하는 기능은 미완료다.

이번 작업은 Negative 정책 구현과 별도 API 문서화 범위다. 다음 순서는 체크리스트의 생성→검증 자동 연결·GPU 조정·취소/Queue 관측이며, 묶음·재생성 API는 아직 없다.
