# ComfyUI Custom Node 구조와 첫 개발 단위

상태: 구조 설계 및 개발 진행 기록. 작성일: 2026-09-12. 사용자 요청으로 주 에이전트가 구조를 설계하고 Terra 서브 에이전트가 구현·테스트 작성을 담당한다. 사용자는 첫 개발·테스트를 설치된 Anima 기반 이미지 생성 Node로 지정하고 구현을 지시했다. 아래 미정 상세나 이전 출력 Node 제안을 일괄 확정하지 않으며 ADR-0005는 계속 Proposed로 유지한다.

## 현재 첫 개발 단위 — 사용자 지정 Anima 이미지 생성

LoRA UI 후속 보완: 사용자는 고정 3슬롯 방식 대신 `+` / `−`로 LoRA 항목을 추가·삭제하고 각 항목의 가중치를 지정하도록 요청했다. Terra에게 동적 목록 UI·저장/재로딩·API 입력 전달·기존 Workflow 호환 검증을 맡겼다. 고정 슬롯 구현의 테스트 통과는 이 후속 요구의 완료를 뜻하지 않는다.

2026-09-13 후속 지시: 설치된 LoRA를 여러 개 선택하고 각각 가중치를 지정할 수 있도록 Anima 생성 Node를 확장한다. 주 에이전트가 Terra에게 구현·테스트를 맡겼으며 사용자는 ADR 논의를 병행한다. ComfyUI 등록 LoRA 목록을 사용하고 적용 순서를 보존하며, 미선택 시 기존 생성과 기존 Workflow 호환성을 유지한다. 설치된 ComfyUI와 예제 Workflow까지 갱신·검증하는 완료 기준을 따른다. 상세 UI 구조·호환 모델 범위와 실제 테스트 결과는 구현 검토 후 기록하며 현재 완료로 간주하지 않는다.

Encode / Save 우선 제안은 사용자가 채택하지 않았다. 첫 구현과 실제 테스트는 **설치된 Anima 모델로 이미지를 생성하는 Node**다. 주 에이전트가 구현 범위를 정리해 Terra에 개발·테스트 작성을 지시했다.

- 위치: Monorepo의 `custom_nodes/atelierx_anima`. ComfyUI에서 로드하는 Python 패키지로 구성한다.
- 첫 Node: `AtelierXAnimaGenerate`. 모델·Text Encoder·VAE, Positive/Negative Prompt, 크기·Seed·Steps·CFG·Sampler·Scheduler를 받아 IMAGE를 반환한다.
- 설치된 ComfyUI의 모델 로딩·텍스트 인코딩·Sampling·VAE Decode를 재사용한다. 모델은 ComfyUI에 등록된 경로에서 선택하고 Anima 계열 여부를 검사한다.
- Node 내부에서 이미지를 저장하지 않는다. 실제 생성 검증용 runner가 결과 PNG를 저장하며 이는 제품 Encode / Save 구현과 다르다.
- 초기 검증 조합은 WAI-ANIMA diffusion model, 대응 이름의 Text Encoder, qwen_image_vae다. 설치 파일과 모델 정보에 근거한 시험 대상이며 실제 호환성은 실행으로 확인한다.
- 첫 단위에는 SDXL·후처리·Preset 영속 저장·REST·전체 Queue를 포함하지 않는다. 다중 LoRA와 모델별 자동 초기값 등 ADR-0002의 나머지 요구는 후속으로 유지하고 첫 Node 구현으로 전체 기능 완료를 주장하지 않는다.
- WAI 모델 정보의 권장 범위 Steps 20~30, CFG 4~5를 바탕으로 시험 기본값 24·4.5 및 Euler ancestral / normal을 사용한다. 모든 Anima 모델에 공통 최적값을 보장하거나 미정 기본값 취득 정책을 확정하는 것은 아니다.
- Terra는 단위 테스트와 실제 ComfyUI 로딩·생성 runner를 작성한다. 주 에이전트가 코드 검토 후 같은 GPU에서 한 번에 한 작업으로 실제 생성 검증을 수행한다. 기존 설치·모델 변경과 다운로드는 필요할 때 별도로 판단한다.

환경 추가 확인: 기존 ComfyUI venv에서 Python 3.12.10, Torch 2.14.0+cu130, CUDA 사용 가능 및 RTX 4090 인식을 확인했다. ComfyUI 소스에 Anima 모델·QWEN3_06B Text Encoder 인식이 있다. [첫 실제 생성 검증](../development/anima-generation-validation.md)에서 WAI 모델 조합의 768×1024 생성 성공과 검증 한계를 기록했다.

## 확인한 개발 환경

- ComfyUI 설치: `C:\StabilityMatrix\Packages\ComfyUI`.
- `comfyui_version.py`의 버전: `0.35.0`.
- 해당 설치의 `venv\Scripts\python.exe` 존재 확인. Python·PyTorch 실행과 호환성은 아직 검증하지 않았다.
- nvidia-smi: NVIDIA GeForce RTX 4090, 24564 MiB, 드라이버 591.86.
- Stability Matrix 모델 디렉터리에 Anima 이름의 모델·Text Encoder와 qwen_image_vae 파일이 있다. 파일명 확인이며 모델 조합·정상 로드·생성 성공을 검증한 것은 아니다.
- custom_nodes의 하위 디렉터리 조회 결과는 없었다. 등록 가능한 Node 전체를 확인한 것으로 간주하지 않는다.
- 프로세스 조회는 접근 거부되어 ComfyUI 현재 실행 여부는 확인하지 못했다. 기존 설치·모델·실행 프로세스를 변경하지 않았다.

## 구조 제안

Monorepo 안에 하나의 ComfyUI Custom Node 패키지를 두고 기능별 모듈로 나눈다. 실제 경로·Node 이름과 공개 입출력은 후속 계약에서 정한다. 빈 기능 파일을 미리 만들지 않고 구현하는 기능부터 추가한다.

| 영역 | 역할 | 개발 의존성 |
| --- | --- | --- |
| 등록 진입점 | ComfyUI에 구현된 Node 등록 | 설치 버전의 Node API 확인 |
| Anima 생성 / SDXL 생성 | 계열별 입력과 모델 로딩·생성 | 기본 모델·Encoder·VAE 조합, 설정 기본값·LoRA 계약 |
| Upscale | 모델 고유 배율과 별도로 최종 배율 적용 | 리샘플링·크기 반올림 |
| Detailer | 눈·입·손·얼굴 처리 | 검출 모델·처리 옵션 |
| Censor | 검출 영역 처리 | 검출 대상·마스킹 방식 |
| 배경 Alpha | 캐릭터 마스크와 투명도 처리 | 분리 모델·마스크 의미·경계 처리 |
| Encode / Save | PNG 및 선택적 WebP 출력 | 아래 첫 개발 단위의 입출력·저장 계약 |
| 내부 처리 함수 | 변환·입력 검사 등 Node 실행 로직 | 해당 기능에서 실제 필요한 만큼 분리 |
| 테스트 | 순수 처리 테스트와 ComfyUI 통합 검증 | Terra가 작성, 주 에이전트가 계약 충족 여부 검토 |

위 영역은 소스 책임 구분이며 공개 Node 개수와 일대일 대응을 강제하지 않는다. Anima와 SDXL 공통 Adapter를 필수로 도입하지 않는다. Node는 Prompt 핵심 조합·Core SQLite·AI Provider·전체 작업 Queue를 소유하지 않는다. Preset Load/Save는 확정 요구로 유지하지만 저장 계약이 정해지기 전 Node 내부 임의 DB로 구현하지 않는다.

ComfyUI의 [Custom Node 등록 안내](https://docs.comfy.org/custom-nodes/walkthrough)와 [IMAGE·MASK 문서](https://docs.comfy.org/custom-nodes/backend/images_and_masks)를 확인했다. IMAGE는 배치 텐서이며 LoadImage의 MASK는 Alpha 반전값이라는 점을 입출력 설계에 고려한다. 아래는 이 기술 특성에 기반한 AtelierX 제안이다.

## 이전 제안 — Encode / Save 출력 Node, 첫 개발 대상에서 제외

Terra의 독립 요구사항·테스트 준비 검토에서도 N-07/N-12를 첫 단위로 권고했다. 생성 모델 없이 작은 이미지로 실제 출력 동작을 검증할 수 있어 Validation 설계와 병행할 수 있다.

첫 공개 Node는 Encode와 Save를 함께 처리하는 출력 Node 하나로 제안한다. 생성·Upscale 등 이미지 처리 Node와는 분리한다. 내부 인코딩과 저장 함수는 분리해 실패를 검증할 수 있게 한다.

첫 구현 전에 정리할 계약과 권고는 다음과 같다. 모두 제안이며 확정된 요구에 섞지 않는다.

| 결정할 계약 | 권고안 |
| --- | --- |
| 입력 | RGB IMAGE 배치, 선택적 MASK, WebP On/Off·품질. MASK는 1이 투명인 ComfyUI 관례를 따라 Alpha로 변환. 크기·배치가 맞지 않으면 오류, 임의 크기 변경 금지 |
| 품질 | WebP 품질 정수 1~100, 기본 90, 기본 WebP Off. UI에 Lossless 옵션은 추가하지 않음 |
| 저장·파일 관계 | ComfyUI output 아래 전용 하위 폴더. 이미지마다 새 이름을 만들고 PNG·WebP는 같은 stem 사용. 기존 파일 덮어쓰기 금지. 작품·캐릭터별 최종 경로 정책과 Core 등록은 별도 |
| PNG·Alpha | PNG 항상 저장, WebP On일 때 별도 파일 추가. 두 출력의 크기·Alpha 보존. RGB 손실 압축인 WebP에 PNG와의 픽셀 완전 일치를 요구하지 않음 |
| 실패 | 요청한 파일 중 하나라도 저장·인코딩 실패하면 Node 실패. 이미 완성된 PNG를 실패 때문에 삭제하지 않으며 남은 파일을 성공한 전체 결과처럼 반환하지 않음. 자동 재실행 금지 |
| Metadata | 첫 단위는 픽셀·Alpha·파일 출력 검증에 한정. EXIF·Prompt·Workflow·Core Metadata의 보존·등록은 미구현 범위로 명시하고 별도 계약 후 추가 |

임시 파일·완성 파일 공개 시점, 동시 실행의 파일명 충돌 방지, ComfyUI 출력 결과 형식과 디스크 오류 전파는 위 계약을 구현할 때 코드 검토 대상으로 삼는다. 원격 이미지 전달과 프로젝트 전역 저장 정책을 이 임시 개발 단위로 확정하지 않는다.

## 후속 출력 Node를 위한 이전 테스트 제안

공개 계약 정리 후 Terra에 위 출력 Node와 테스트를 맡긴다. 다른 Node·Backend·Preset 저장·모델 다운로드·CI는 이 첫 단위에 포함하지 않는다. 설치 연결은 기존 ComfyUI를 복제하거나 의존성을 일괄 갱신하기 전에 별도 실행 방법을 확인한다.

- PNG 단독 및 PNG+WebP 결과가 실제로 Decode되고 크기가 같은지 확인.
- WebP Off에서 WebP 파일이 생기지 않는지 확인.
- 알려진 RGB·투명/반투명 MASK로 Alpha 방향과 보존 확인.
- 여러 이미지 및 반복 실행에서 파일 쌍·이름 충돌·기존 파일 보존 확인.
- 잘못된 입력·품질·배치/마스크 크기 오류 확인.
- 인코더·쓰기 실패 시 실패 전파, 성공으로 오인하지 않는 결과, 기존/완성 PNG 보존 확인.
- 실제 ComfyUI 등록과 작은 CPU IMAGE 실행 통합 검증. 모델 생성·GPU 추론 성공은 이후 생성 Node의 별도 검증.

테스트 코드 작성·실행은 Terra 담당이며, 이 목록 자체는 테스트 통과 기록이 아니다. 전역 Test·CI 정책도 확정하지 않는다.

## 다음 작업

Terra의 Anima 첫 생성 Node와 테스트 구현을 검토했고 WAI 조합 실제 생성과 단위 테스트 9개가 통과했다. 다음은 ComfyUI Workflow 연결 검증과 다른 Anima 조합·LoRA·Preset 등 후속 요구 검토다. 출력 Node는 그 이후 후보이며 우선순위로 채택된 상태가 아니다. 전체 Backend 설계 완료를 생성 Node 개발의 선행 조건으로 두지 않는다.

## 후속 Node 병렬 개발 — 2026-09-13 사용자 지시

사용자가 다른 Custom Node 개발도 서브 에이전트로 병렬 진행하도록 지시했다. 주 에이전트가 Upscale과 배경 투명화를 독립 Terra 작업으로 배정했다. 구현 prototype은 각각 `custom_nodes/atelierx_upscale`, `custom_nodes/atelierx_alpha`에서 준비하며 설치 모델·의존성 확인 후 실제 가능한 범위를 보고한다. 미정 리샘플링/검출 모델/경계 처리 선택은 제품 정책 확정과 구분한다. 기존 Anima·동적 LoRA와 별도로 코드/테스트를 작성하고 GPU·서버 재시작·설치 통합은 주 에이전트가 조정한다. 모델 없는 기능을 완료로 보고하지 않으며 사용자 직접 실행 가능한 예제·설치 검증 기준을 유지한다.
