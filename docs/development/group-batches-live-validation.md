# 그룹 일괄 실행·검사 설정 실환경 검증 — 2026-09-13

## 결과

설치된 ComfyUI와 LM Studio의 Qwen3 VL 8B를 사용했다. Core·Generation·Validation은 실행별 데이터 디렉터리와 로컬 포트로 격리했다. 초기 실패를 수정한 뒤 **이미 생성한 2장을 재사용해 후속 검증을 완료**했다. 새 생성은 총 2회, 단일 추론 2회, 묶음 추론 1회다. 외부 API와 27B 모델은 사용하지 않았다.

| 확인 항목 | 결과 |
| --- | --- |
| Anima 생성 및 PNG 저장 | 768×1024 이미지 2장 생성, 저장 SHA-256 일치 |
| Core batch 자동 후속 단일 검증 | 2장 모두 passed |
| 설정 revision 고정 | 접수 당시 Provider revision 6, 현재 설정은 7. 단일 2건·묶음 1건 모두 6으로 실행 |
| 기준 후보→명시 지정→confirm-reference | 수정 후 정상 재개, 같은 확인 key는 기존 결과 반환 |
| 묶음 검증 | 기준 1장·대상 1장, 실행 오류 없이 completed / passed |
| 재시작·중복 방지 | Generation·Validation 저장 상태 재사용 및 Core 재시작 후 batch/group 결과 보존. Generation Job 총 2개 유지 |
| GPU/Queue | owner 없음, waiting 빈 목록, blocked 없음. 처리 대상 모두 종료 |
| 회귀 | 전체 117개 통과, 13.500초 |

테스트용 Core에서는 자동 재생성 Off/상한 0을 명시했다. 제품 기본 상한 5회나 사용자 일반 설정을 변경하지 않았다. revision 변경 시험은 동일 Provider 런타임 값을 새 revision으로 저장하는 방식이며 모델 자체 교체의 품질 시험은 아니다.

## 발견·수정

1. 실제 Provider 설정은 map key에 ID가 있고 값에는 provider_id가 없었다. Validation registry bootstrap에서 key를 정규화해 credential과 과거 revision을 올바르게 연결하도록 수정했다.
2. 그룹 lower가 빈 값인데도 기준 후보 계산이 lower를 필수 coverage로 요구했다. 실제 묶음 identity와 동일하게 비어 있는 항목을 제외하고 회귀를 추가했다. 비어 있지 않은데 가려진 항목은 여전히 비교 부족으로 처리한다.

첫 실행은 두 이미지가 단일 검증을 통과한 뒤 후보 단계에서 중단했다. 실패 기록은 report.json에 보존했고, 수정 후 --resume으로 기존 endpoint·DB·이미지·registry를 복원해 묶음 단계만 실행했다. 재개 성공은 resumes의 completed로 구분한다.

## 판정 품질의 제한

이번 passed는 실행·응답 계약의 성공을 확인한 결과다. 두 이미지의 머리 길이가 달랐고 VLM도 이를 관찰 문구에 적었지만 appearance를 matched로 판정했다. 테스트의 공통 외형 문구는 adult woman, silver hair, blue eyes로 단순화되어 있었다. 이 결과를 캐릭터 일관성 품질 보장으로 해석하지 않는다. 다음 품질 검증에서는 기준 이미지에서 유지해야 하는 시각적 특징과 허용되는 자세·구도·표정 변화의 경계를 기존 요구사항과 대조하고, 동일 입력으로 판정 근거와 결과의 일치 여부를 평가해야 한다.

## 재현·산출물

스크립트: `scripts/test_group_batches_rest.py`. 새 시험은 기본 실행, 기준 확인 대기 상태의 중단 시험만 `--resume <기존 artifact 디렉터리>`로 재개한다. 재개는 새 이미지를 생성하지 않는다.

- 결과: `artifacts/group-batches-rest/20260913-142529/report.json`
- 이미지: `artifacts/group-batches-rest/20260913-142529/generation/images/`
- 첫 이미지: `136acdaf-30ac-4325-83f4-ac0dc931a5d4-0.png`
- 둘째 이미지: `259c38b6-71b3-4dc3-a622-a8cd2a3aa979-0.png`

ComfyUI 원본 출력은 기존 `C:\StabilityMatrix\Packages\ComfyUI\output\AtelierX`에 보존된다. 테스트용 API 프로세스는 검증 후 종료했으며 ComfyUI와 LM Studio는 종료하지 않았다.
