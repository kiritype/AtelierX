# 참조 이미지로 생성 BETA

기준 이미지 한 장을 바탕으로 인물의 외형과 그림체를 참조하고, 프롬프트에서 표정·자세·구도·배경을 바꿉니다. ComfyUI에서 **Anima** 또는 **MOSS**를 사용할 수 있습니다.

## 준비

### Anima

**설정 → 설치**에서 **Anima Ref Adapter** 확장 노드와 **Anima 참조 어댑터 v2** 가중치를 각각 설치합니다. 노드를 설치한 뒤 ComfyUI를 다시 시작합니다. 가중치 파일은 ComfyUI에서 읽는 `models/loras`에 둡니다. [외부 구성 요소](external.md)

### MOSS

1. ComfyUI 0.43.0 이상에서 MOSS-Image-SFT, Qwen3.5 9B 텍스트 인코더, Flux2 VAE를 준비합니다. 모델은 ComfyUI에서 인식해야 합니다. [ComfyUI 예제와 모델](https://github.com/OpenMOSS/MOSS-Image/blob/main/comfyui/README.md)
2. [MossRef v2.0.0](https://github.com/Neon3579/MossRef/releases/tag/v2.0.0)의 소스를 받아 `MossRef` 폴더를 `custom_nodes/` 아래에 놓습니다. 같은 릴리스의 `anime_textref_v2_bf16.safetensors`를 `models/moss_ref/` 아래에 넣습니다.
3. [Moss-Image-Edit 배포처](https://huggingface.co/chinoll/Moss-Image-Edit/tree/3be9c40037e1b89b17aa85ff6f8ee805872aa558)에서 `adapter_config.json`과 `adapter_model.safetensors`를 받아 `models/moss_ref/Moss-Image-Edit/` 아래에 넣고 ComfyUI를 다시 시작합니다. 원격 ComfyUI라면 그 서버에 파일을 둡니다. [MossRef 설치 안내](https://github.com/Neon3579/MossRef/blob/v2.0.0/README.ko.md#설치)

## 생성

1. 작품의 **이미지 → 참조 이미지로 생성 BETA**를 열고 PNG·WebP·JPEG 한 장을 고릅니다. 갤러리에서 이미지 한 장을 체크한 뒤 **참조 이미지로 사용**을 누르거나, 이미지 상세에서 **이 이미지를 기준으로 변형**을 누를 수도 있습니다. 썸네일을 누르면 전체 이미지가 열리고 `Esc`로 닫을 수 있습니다.
2. 모델 계열과 모델을 고르고 장면 프롬프트를 적습니다. Anima는 **세부 설정**에서 참조 가이던스(기본 4.5)를 조절할 수 있습니다. MOSS는 프롬프트에서 `Picture 1`의 어떤 요소를 반영할지 설명할 수 있습니다. 예를 들어 `Use Picture 1 for the exact character and outfit. The character is reading a book in a quiet library.`처럼 씁니다. MOSS에서는 참조 한 장과 일반 프롬프트를 사용합니다.
3. **1장 생성**을 누릅니다. 작업과 결과는 [이미지 작업 대기열](generation.md)과 [갤러리](gallery-export.md)에서도 확인할 수 있습니다. 외형과 그림체가 반영되는 정도는 모델과 장면에 따라 달라집니다.

## ComfyUI에서 다시 열기

결과의 **재현용 ZIP**에는 결과 이미지, 실행·편집용 워크플로, 모델과 참조 설정이 들어 있습니다. 원본을 함께 옮길 경우에만 참조 이미지 첨부를 선택합니다.

1. 대상 ComfyUI에 원래 사용한 모델과 참조 어댑터를 설치합니다. Anima는 별도 릴리스 첨부 **Anima Ref Adapter 노드·예제 워크플로 ZIP**을 사용할 수 있습니다. 업스케일·디테일러를 사용한 결과에는 해당 노드와 모델도 필요합니다. [외부 구성 요소](external.md)
2. 참조를 첨부했다면 ZIP의 `input/`에 있는 `atelierx-reference-…` 파일을 대상 ComfyUI의 `input/` 아래에 복사합니다. 원본을 따로 보관했다면 편집기에서 **Load Image**로 직접 고릅니다.
3. `result.png` 또는 `workflow.json`을 ComfyUI에 열고 참조와 모델을 확인한 뒤 실행합니다.
