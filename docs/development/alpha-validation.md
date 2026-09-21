# 배경 Alpha Custom Node 프로토타입 검증 기록

상태: 개발 프로토타입. 작성일: 2026-09-13.

ADR-0002 N-10의 확정된 요구는 캐릭터를 검출해 마스크를 만들고, 캐릭터 이외 영역의 Alpha를 변경하며 On / Off를 제공하는 것이다. 검출·마스크 모델과 경계 처리는 아직 미정이다. 이 기록은 그 미정 사항을 결정하거나 검출 기반 전체 기능 완료를 선언하지 않는다.

## 설치 환경 확인

- ComfyUI: `C:\StabilityMatrix\Packages\ComfyUI` (0.35.0).
- Shared Models: `C:\StabilityMatrix\Models\BackgroundRemoval`, `Sams`는 비어 있다. `Ultralytics`에는 빈 `bbox`, `segm` 디렉터리만 있다.
- `extra_model_paths.yaml`은 `background_removal`, `sams`, `ultralytics` 경로를 등록하지만, 해당 파일 경로에 가중치는 없다.
- 설치 ComfyUI Python에서 `torch`, `transformers`, `PIL`은 확인했고 `rembg`, `segment_anything`, `ultralytics`, `cv2`는 없다.

그러므로 이 설치 상태에서 검출·분리 추론을 실행할 모델과 런타임은 없다. 이 작업은 모델 다운로드·의존성 설치·ComfyUI 재시작·GPU 추론을 수행하지 않았다.

## 구현한 범위

`AtelierX Detect Character Mask`는 실제 검출·분할 경로를 제공한다. 입력
`IMAGE`와 ComfyUI에 이미 등록된 `ultralytics_segm` 모델을 받아, 로컬
Ultralytics segmentation backend의 COCO `person` class(0) 결과를 모두 합쳐
전경 `MASK`로 반환한다. 모델은 ComfyUI가 제공한 등록 파일명에서만 해석하며,
Ultralytics ndarray 계약에 맞춰 ComfyUI RGB float `IMAGE`를 0--255 BGR `uint8`
으로 변환해 전달하며, `retina_masks=True`의 출력 크기가 입력과 다르면 임의 리사이즈 없이 실패한다.
따라서 출력 `MASK`는 아래 Alpha Node의 `character_mask`에 바로 연결할 수 있다.
`ultralytics` Python runtime 또는 선택 모델이 없으면, 다운로드·설치·원격 요청을
시도하지 않고 누락 항목을 설명하는 오류로 끝낸다.

이 경로는 “모든 애니메이션 캐릭터”를 보장하지 않는다. 현 구현은 COCO 사람
class를 선택하고 복수 검출 결과를 하나의 전경으로 합친다. 검출 없음은 전체
이미지를 투명하게 만드는 대신 명시적 오류로 끝나며 Alpha를 바꾸지 않는다. 한 명 선택, 다른 class, SAM prompt, hair/반투명 edge refinement는
여전히 미결정이다. 이 구현 세부는 N-10의 모델·경계 정책을 확정하지 않는다.

`custom_nodes/atelierx_alpha`의 `AtelierX Apply Character Alpha`는 외부에서 공급한 **전경 캐릭터 MASK**(`1`=캐릭터 유지, `0`=배경 Alpha 제거)를 IMAGE에 적용한다. `enabled=false`면 입력 RGB와 기존 Alpha를 보존한다. 입력 RGBA가 이미 Alpha를 가지면 새 Alpha는 기존 Alpha와 전경 MASK를 곱해 기존 투명도를 보존한다. 출력 MASK는 ComfyUI 관례에 맞춰 `1`이 투명 배경이며, 정확히 `1 - 출력 Alpha`이므로 RGBA 출력과 일치한다.

마스크와 이미지의 batch·pixel 크기는 정확히 같아야 하며, 자동 리사이즈·broadcast는 하지 않는다. 이 규칙은 임시 프로토타입의 안전한 입력 검증일 뿐, 경계 보정 정책을 확정하지 않는다.

`examples/apply-character-alpha.workflow.json`은 LoadImage가 읽은 기존 Alpha를 반전해 전경 MASK로 쓰는 배선 예제다. 사용자가 배경 Alpha가 이미 있는 PNG를 ComfyUI input에서 선택해야 한다. API 템플릿도 실제 입력 파일명을 교체해야 한다. 이는 수동 mask-source 예제다.

`examples/detect-character-alpha.workflow.json`과 동명 API template은
`LoadImage → AtelierXDetectCharacterMask → AtelierXApplyCharacterAlpha → PreviewImage`
배선을 제공한다. 사용 전에는 입력 이미지와 등록된 로컬 segmentation model
placeholder를 교체해야 한다. 현재 설치에는 해당 runtime과 weight가 없어 실제 실행
검증 대상이 아니다.

## 검증

다음 명령으로 텐서 단위 테스트를 실행한다.

```powershell
C:\StabilityMatrix\Packages\ComfyUI\venv\Scripts\python.exe -B -m unittest discover -s custom_nodes\atelierx_alpha\tests -v
```

검증 항목은 전경/배경 Alpha 방향, 기존 Alpha 보존과 출력 MASK 일치, Off 동작, 유한 float 값·잘못된 MASK shape·batch 거절이다. 분할 backend에는 복수 사람 mask 결합·batch 순서·COCO person class 전달, ComfyUI RGB float에서 Ultralytics BGR `uint8` ndarray로의 변환, 결과 mask 크기 불일치와 검출 없음 거절, 유효하지 않은 confidence 거절을 mock backend로 검사한다. 추가로 `scripts/validate_examples.py`로 수동·검출 JSON 배선을 확인한다.

저장소 소스 패키지를 실제 ComfyUI 0.35.0 registry에 직접 load하고 작은 CPU tensor로 실행하는 smoke는 통과했다. 설치된 ComfyUI에 패키지를 연결하거나, 그 설치에서 Node 등록·Workflow 실행을 수행하지는 않았다. `scripts/Install-AtelierXAlpha.ps1`은 같은 소스를 `custom_nodes\\atelierx_alpha` junction으로 연결할 준비만 하며, 다른 항목을 덮어쓰지 않는다. 실제 연결·재시작·Workflow 실행은 공유 GPU와 실행 중인 사용자 작업 상태를 주 에이전트가 조율한 뒤 진행한다.

## 검출 통합 전 필요한 선택

후보는 다음 세 가지이나 이 문서는 어느 하나도 채택하지 않는다.

1. Ultralytics segmentation: 현재 사람 class 전체 결합으로 첫 구현했다. 애니메이션 캐릭터 적합성, 한 명 선택 규칙, 가중치·라이선스는 아직 선택하지 않았다.
2. SAM: 별도의 detector box/point prompt와 SAM 가중치·런타임이 필요하다.
3. rembg/BiRefNet 계열: 전경 분리 품질, 애니메이션 캐릭터 적합성, 런타임과 모델 배치가 필요하다.

선택 시 모델 라이선스·다운로드 위치·출력 MASK 의미·복수 캐릭터·hair/반투명 경계 처리와 기존 Alpha 결합 규칙을 별도로 검토해야 한다.


## 2026-09-13 실제 설치·실행 후속 기록

이 문서의 초기 CPU 검증·미설치 기록 이후 ComfyUI 설치와 REST 실행을 완료했다. 현재 모델·실행 결과·사용자 Workflow와 검증 한계는 [보조 노드 실제 검증](postprocess-live-validation.md)을 따른다.

## 2026-09-21 Core 검사 요구 연결

Core가 단일 검사 요청을 만들 때 이미지의 Task snapshot에 고정된 `postprocess.alpha` 존재 여부를 반영한다. Alpha 단계가 있으면 `expected_output.alpha=transparency_required`, 없으면 기존 `not_required`를 유지한다. 현재 Preset이나 전역 설정이 아니라 원래 생성 설정을 사용하며 PNG/WebP 모두 같은 조건을 적용한다.

출력 조건 검사를 활성화한 Profile에서 투명 영역이 없으면 기존 Validation 계약대로 `completed/failed`로 종료하고 AI 검사를 생략한다. Profile의 `output_conditions=false`는 유지한다. 과거 검증 Run을 수정하거나 자동 재검사하지 않으며, 명시적 새 검사부터 새 연결을 사용한다.

이 검사는 Alpha 채널만 존재하는 완전 불투명 이미지도 구분하지만, 투명 픽셀의 최소 면적이나 캐릭터 보존·머리카락 경계 품질을 새 기준으로 도입하지 않는다. 기존 Validation의 투명 픽셀 존재 검사에 생성 요구를 연결하는 수정이다.

### 자동 회귀 검증

- `tests.test_core_validation` + `tests.test_validation`: 21개 통과. 원래 Preset snapshot과 이후 Preset 수정의 분리, 멱등 접수·명시적 재검사, Alpha 미사용, 실제 PNG/WebP decode에 의한 투명/불투명 판정, 출력 검사 비활성화를 확인했다. Provider가 필요한 테스트는 모의 Provider다.
- `tests.test_regeneration` + `tests.test_production_plans`: 15개 통과. 기존 재생성·계획 흐름을 확인했다.
- 실행 중인 파일럿은 재시작하지 않았다. 코드 변경은 별도 테스트 프로세스에서 확인했으며 기존 파일럿 프로세스에 반영됐다고 보고하지 않는다. 운영 반영은 작업이 없는 시점의 정상 재시작이 필요하다.

### 기존 실제 GPU 출력 재검사

`artifacts/backend-pipeline-rest/20260913-053307/alpha.png`와 `alpha.webp`의 원본 바이트를 격리된 Generation HTTP 대역이 제공하고, 실제 Core REST·별도 SQLite·Validation으로 검사했다. 두 요청 모두 Core가 `transparency_required`를 전달했고 `completed/passed`로 종료했다. 동일 이미지에서 메모리 내 변환으로 만든 불투명 대조군 PNG/WebP는 모두 `completed/failed`이며 실행 오류가 아니었다.

출력 조건만 켠 Profile로 검사했고 Provider 호출은 0회다. 새 GPU 생성이나 실제 VLM 추론 검증이 아니라 **기존 GPU 출력 + 모의 Generation 전송 + 실제 Core/Validation의 연결 검증**이다. 파일럿 데이터·실행 중 서비스는 변경하지 않았다. 마스크·경계의 시각적 품질은 이번 판정 범위가 아니다.

로컬 실행 근거: `artifacts/alpha-validation-20260921/report.json`, 재현 스크립트 `artifacts/alpha-validation-20260921/run_real_alpha_files.py`. 실제 이미지·로그와 해당 로컬 재검사 도구는 Git에 포함되지 않으며, 새 clone에서 재현 가능한 회귀 검사는 위 tests 모듈이다.
