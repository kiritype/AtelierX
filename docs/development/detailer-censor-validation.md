# Detailer·Censor Custom Node 프로토타입 검증 기록

상태: 개발 프로토타입. 작성일: 2026-09-13.

ADR-0002 N-08은 눈·입·손·얼굴 Detailer를, N-09는 NSFW Censor를 요구한다.
ADR-0003의 선택 후처리 순서에서는 Detailer 다음에 Censor가 온다. 검출
모델·검출 대상·처리 방식은 두 ADR에서 미정으로 남아 있다. 이 구현은 그
미정 사항을 결정하거나 검출 기능 전체 완료를 주장하지 않는다.

## 구현 범위

- `custom_nodes/atelierx_detailer`의 `AtelierX Detailer`는 `eyes`, `mouth`,
  `hands`, `face` target과 외부 `region_mask`를 받는다. MASK의 `1`은 다시
  생성할 영역이다. 실제 처리 체인은 설치된 ComfyUI 0.35.0의
  `CLIPTextEncode` → `VAEEncodeForInpaint` → `KSampler` → `VAEDecode`다.
  결과는 원본과 해당 MASK로 합성하므로 영역 밖 픽셀과 입력 RGBA Alpha를
  보존한다. `MODEL`·`CLIP`·`VAE`는 upstream loader에서 연결한다.
- Detailer의 선택적 `AtelierX Detect Detail Region`은 로컬에 등록된
  `ultralytics_bbox` model을 실행해 모든 bounding box를 MASK로 rasterize한다.
  사용자가 target에 맞춰 학습된 모델을 선택해야 하며, target 값으로 class를
  추측하지 않는다. 이 box mask는 초안이며 부위 검출 품질을 보장하지 않는다.
- `custom_nodes/atelierx_censor`의 `AtelierX Censor`는 외부
  `detection_mask`의 `1` 영역에 `mosaic` 또는 `white`를 적용한다. Alpha와
  영역 밖 픽셀을 유지하며 Off에서는 원본 tensor를 그대로 반환한다.
- Censor의 `AtelierX Detect NSFW Mask`는 registered `ultralytics_segm` 모델의
  segmentation mask 중 reference labels `nipples,pussy,penis,anus,testicles,
  x-ray,cross-section`만 합친다. reference model은
  `segm/ntd11_anime_nsfw_segm_v5-variant1.pt`다. Censor는 mosaic, feathered
  white, white_solid과 intensity 기반 dilation을 제공한다.
- 두 노드 모두 모델을 다운로드·설치하지 않고, 검출기를 호출하거나 검출
  결과를 안전하다고 판정하지 않는다. 각각의 Workflow/API 예제는
  `LoadImageMask`의 red channel을 precomputed mask로 사용한다.

## 현재 설치 자원 확인

- ComfyUI: `C:\StabilityMatrix\Packages\ComfyUI` 0.35.0. native inpaint
  API와 `MODEL`/`CLIP`/`VAE` input schema를 확인했다.
- `C:\StabilityMatrix\Models\Ultralytics`의 `bbox`, `segm`는 비어 있고,
  `Sams`, `DeepDanbooru`, `AfterDetailer`에 사용할 detector weight는 없다.
  설치된 `custom_nodes`에도 detector/detailer extension은 없다.
- 따라서 현 설치에서는 얼굴·눈·입·손 또는 NSFW detection을 자동 실행할
  준비가 되어 있지 않다. 필요한 detector 선택, 라이선스, weight 경로,
  복수 영역·mask 의미를 확정하고 준비한 뒤에만 upstream adapter를 추가할
  수 있다. 이번에는 adapter의 local-only 오류 경계만 구현했으며 runtime,
  weight, ONNX inference는 실행하지 않았다.

## 검증 결과

아래는 GPU 실행 없이 완료했다.

```powershell
C:\StabilityMatrix\Packages\ComfyUI\venv\Scripts\python.exe -B -m unittest discover -s custom_nodes\atelierx_detailer\tests -v
C:\StabilityMatrix\Packages\ComfyUI\venv\Scripts\python.exe -B -m unittest discover -s custom_nodes\atelierx_censor\tests -v
C:\StabilityMatrix\Packages\ComfyUI\venv\Scripts\python.exe custom_nodes\atelierx_detailer\scripts\validate_examples.py
C:\StabilityMatrix\Packages\ComfyUI\venv\Scripts\python.exe custom_nodes\atelierx_censor\scripts\validate_examples.py
```

각각 4개 단위 테스트가 통과했다. Detailer는 target/input 검사와 native
inpaint call sequence를, Censor는 white·mosaic 합성, Alpha 보존, Off와 잘못된
입력을 검사한다. ComfyUI Python에서 두 extension registry와 schema를 직접
load하는 smoke도 통과했다.

Junction 설치, ComfyUI 재시작, 실제 Workflow/REST 실행 및 GPU 검증은 실행
중인 사용자 작업을 중단하지 않기 위해 주 에이전트가 조정한다. 이 기록은
그 검증이 완료되었다는 뜻이 아니다.


## 2026-09-13 실제 설치·실행 후속 기록

이 문서의 초기 CPU 검증·미설치 기록 이후 ComfyUI 설치와 REST 실행을 완료했다. 현재 모델·실행 결과·사용자 Workflow와 검증 한계는 [보조 노드 실제 검증](postprocess-live-validation.md)을 따른다.
