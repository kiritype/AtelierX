# 외부 구성 요소

ComfyUI, 외부 확장 노드, 모델과 LoRA 학습 도구는 필요할 때 원래 배포처에서 받습니다. 표에는 0.5.1에서 시험한 ComfyUI와 앱이 내려받는 버전을 적었습니다. 글 작성과 대화 테스트에는 아래 이미지 구성 요소가 필요하지 않습니다.

1. 로컬 이미지 생성부터 시작하려면 ComfyUI를 설치하고 사용할 모델을 연결합니다. [이미지 환경 준비](image-setup.md)
2. 후처리나 태깅 도구를 쓰려면 **설정 → 설치**에서 필요한 확장 노드와 모델 묶음의 용량과 라이선스를 확인합니다. **직접 받기** 항목은 표시된 배포처와 폴더를 따릅니다.
3. 학습은 **설정 → 이미지 → LoRA 학습 → 학습 환경 자동 준비**에서 필요한 도구와 모델을 준비합니다. [LoRA 데이터셋과 학습](lora.md)

각 구성 요소의 이용 조건은 원 배포처에서 확인합니다. 일부 모델에는 비상업 이용 조건이 있습니다.

## 이미지 생성 서버

| 이름 | 판 | 라이선스 | 어디에 쓰나 |
|---|---|---|---|
| [ComfyUI](https://github.com/comfyanonymous/ComfyUI) | 0.38.0에서 시험 | GPL-3.0 | 이미지 생성 전체. 사용자가 설치한 것에 연결합니다(Stability Matrix 등으로 설치해도 됨) |

## ComfyUI 확장 노드

설정 → 설치 → **이미지 생성 서버 확장 노드**가 아래 판(커밋)으로 받아 ComfyUI의 `custom_nodes`에 넣습니다.

| 이름 | 판 | 라이선스 | 어디에 쓰나 |
|---|---|---|---|
| [ComfyUI-WD14-Tagger](https://github.com/pythongosssss/ComfyUI-WD14-Tagger) | 1.0.1 (`9e0a6e7`) | MIT | 태깅 |
| [ComfyUI_essentials](https://github.com/cubiq/ComfyUI_essentials) | 1.1.0 (`9d9f4be`) | MIT | 배경 제거 |
| [ComfyUI-Impact-Pack](https://github.com/ltdrdata/ComfyUI-Impact-Pack) | 8.28.3 (`429d015`) | GPL-3.0 | 디테일러 |
| [ComfyUI-Impact-Subpack](https://github.com/ltdrdata/ComfyUI-Impact-Subpack) | 1.3.5 (`50c7b71`) | AGPL-3.0 | 디테일러, 감지 |
| `atelierx_nodes` | 앱과 같은 판 | MIT | 배경·감지·업스케일·디테일러 보조. 앱에 들어 있는 노드 묶음을 복사합니다 |

## 모델

설정 → 설치 → **모델**이 공개된 SHA256을 확인하며 받아 ComfyUI의 모델 폴더에 넣습니다. 계정이 필요한 곳의 모델은 받는 곳 링크와 넣을 폴더만 안내합니다.

| 묶음 | 파일 | 라이선스 |
|---|---|---|
| LoRA 학습용 Anima 기본 모델 | `anima-base-v1.0.safetensors`, `qwen_3_06b_base.safetensors`, `qwen_image_vae.safetensors` ([Anima](https://huggingface.co/circlestone-labs/Anima)) | CircleStone Labs Non-Commercial License (+ NVIDIA Open Model License) |
| 감지 모델 | `face_yolov8m.pt`, `hand_yolov8s.pt`, `person_yolov8m-seg.pt`, `person_yolov8n-seg.pt` ([adetailer](https://huggingface.co/Bingsu/adetailer)), `sam_vit_b_01ec64.pth` ([Segment Anything](https://github.com/facebookresearch/segment-anything)) | Apache-2.0 |
| 감지 모델(직접 받기) | `PitEyeDetailer-v2-seg.pt`, `ntd11_anime_nsfw_segm_v5-variant1.pt` (Civitai에서 검색해 `ultralytics/segm`에 넣기) | 각 모델 페이지의 조건 |
| 업스케일 모델 | `2x-AnimeSharpV4_Fast_RCAN_PU.safetensors`, `2x-AnimeSharpV4_RCAN.safetensors` ([2x-AnimeSharpV4](https://huggingface.co/Kim2091/2x-AnimeSharpV4)), `4x-UltraSharp.safetensors` ([UltraSharp](https://huggingface.co/Kim2091/UltraSharp)) | CC BY-NC-SA 4.0 (비상업) |

## LoRA 학습 도구

**설정 → 이미지 → LoRA 학습 → 학습 환경 자동 준비**가 아래 판을 앱 폴더의 `vendor/`에 받고 학습 전용 Python 환경을 만듭니다. 소스에서 실행한다면 `tools/install_trainer.py`로도 도구를 설치할 수 있습니다.

| 이름 | 판 | 라이선스 |
|---|---|---|
| [anima_lora](https://github.com/sorryhyun/anima_lora) | `69ff962` | MIT (일부 Apache-2.0) |
| [anime_tools](https://github.com/sorryhyun/anime_tools/releases/tag/v0.7.5) | `v0.7.5` (`74aa014`) | MIT |

## 보조 도구

PC에 이미 있으면 그것을 쓰고, 없으면 설정 → 설치 → **보조 도구**가 앱 폴더 `bin/`에 휴대용으로 받습니다. 확장 노드·학습 도구를 설치할 때 없으면 그때 함께 받습니다(설치 화면에 미리 표시). 받는 판은 아래로 고정돼 있고, 크기와 sha256을 확인합니다. Git은 확장 노드와 학습 도구 설치에만 쓰며, 작품 편집·기록 등 나머지 기능은 Git 없이 동작합니다.

| 이름 | 판 | 라이선스 | 어디에 쓰나 |
|---|---|---|---|
| [uv](https://github.com/astral-sh/uv) | `0.12.23` | MIT 또는 Apache-2.0 | 학습 도구의 Python 환경 |
| [Git for Windows](https://github.com/git-for-windows/git) (MinGit) | `2.56.0.2` | GPL-2.0 | 확장 노드·학습 도구 받기 |

앱 자체에 들어 있는 라이브러리의 라이선스는 앱 폴더의 `THIRD_PARTY_NOTICES.md`와 **도움말 → AtelierX 정보 → 제3자 라이선스**에서 볼 수 있습니다.
