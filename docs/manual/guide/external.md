# 외부 구성 요소

AtelierX는 아래 프로그램과 모델을 **함께 배포하지 않습니다.** 필요한 사람만 **설정 → 설치**에서 받거나 직접 설치합니다(이미지 기능에만 필요하고, 글 작성·테스트에는 필요 없습니다). 앱이 받는 판은 앱 버전마다 정해져 있고, 받을 때 원래 배포처에서 바로 받습니다. 각 구성 요소의 라이선스는 그 배포처의 조건을 따르며, 특히 **모델은 비상업 조건이 있는 것이 많으니** 쓰기 전에 직접 확인하세요.

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
| [Skimmed_CFG](https://github.com/Extraltodeus/Skimmed_CFG) | 1.0.0 (`d830058`) | Apache-2.0 | 그림체 레시피의 모델 패치(CFG 스키밍) |
| [ComfyUI-Spectrum-KSampler](https://github.com/sorryhyun/ComfyUI-Spectrum-KSampler) | 2.9.3 (`1925664`) | MIT | 그림체 레시피의 모델 패치(Spectrum, CFG 패치). 이 팩의 샘플러 노드는 쓰지 않음 |
| `atelierx_nodes` | 앱과 같은 판 | MIT | 배경·감지·업스케일·디테일러 보조. 앱에 들어 있는 노드 묶음을 복사합니다 |

앱이 설치하지 않는 노드 팩도 직접 설치했다면 생성에 쓸 수 있습니다. 라이선스가 분명하지 않거나 제한이 있어 설치 목록에 넣지 않은 것들입니다.

| 이름 | 라이선스 | 어디에 쓰나 |
|---|---|---|
| [RES4LYF](https://github.com/ClownsharkBatwing/RES4LYF) | 자체 라이선스(상업 서비스 제공 금지, OSI 아님) | `res_3m` 등 샘플러, `beta57` 등 스케줄러. `beta57`은 없어도 앱이 기본 노드로 만듦 |
| ComfyUI-DCW | 라이선스 파일 없음 | 모델 패치 `DCWModelPatch` |

## 모델

설정 → 설치 → **모델**이 공개된 SHA256을 확인하며 받아 ComfyUI의 모델 폴더에 넣습니다. 계정이 필요한 곳의 모델은 받는 곳 링크와 넣을 폴더만 안내합니다.

| 묶음 | 파일 | 라이선스 |
|---|---|---|
| LoRA 학습용 Anima 기본 모델 | `anima-base-v1.0.safetensors`, `qwen_3_06b_base.safetensors`, `qwen_image_vae.safetensors` ([Anima](https://huggingface.co/circlestone-labs/Anima)) | CircleStone Labs Non-Commercial License (+ NVIDIA Open Model License) |
| 감지 모델 | `face_yolov8m.pt`, `hand_yolov8s.pt`, `person_yolov8m-seg.pt`, `person_yolov8n-seg.pt` ([adetailer](https://huggingface.co/Bingsu/adetailer)), `sam_vit_b_01ec64.pth` ([Segment Anything](https://github.com/facebookresearch/segment-anything)) | Apache-2.0 |
| 감지 모델(직접 받기) | `PitEyeDetailer-v2-seg.pt`, `ntd11_anime_nsfw_segm_v5-variant1.pt` (Civitai에서 검색해 `ultralytics/segm`에 넣기) | 각 모델 페이지의 조건 |
| 업스케일 모델 | `2x-AnimeSharpV4_Fast_RCAN_PU.safetensors`, `2x-AnimeSharpV4_RCAN.safetensors` ([2x-AnimeSharpV4](https://huggingface.co/Kim2091/2x-AnimeSharpV4)), `4x-UltraSharp.safetensors` ([UltraSharp](https://huggingface.co/Kim2091/UltraSharp)) | CC BY-NC-SA 4.0 (비상업) |

## LoRA 학습 도구

설정 → 이미지 → LoRA 학습의 **자동 준비**(또는 `tools/install_trainer.py`)가 아래 판을 앱 폴더 `vendor/`에 받고, 그 Python 환경을 만듭니다.

| 이름 | 판 | 라이선스 |
|---|---|---|
| [anima_lora](https://github.com/sorryhyun/anima_lora) | `69ff962` | MIT (일부 Apache-2.0) |
| [anime_tools](https://github.com/sorryhyun/anime_tools) | `v0.7.5` | MIT |

## 보조 도구

PC에 이미 있으면 그것을 쓰고, 없으면 설정 → 설치 → **보조 도구**가 앱 폴더 `bin/`에 휴대용으로 받습니다. 확장 노드·학습 도구를 설치할 때 없으면 그때 함께 받습니다(설치 화면에 미리 표시). 받는 판은 아래로 고정돼 있고, 크기와 sha256을 확인합니다. Git은 확장 노드와 학습 도구 설치에만 쓰며, 작품 편집·기록 등 나머지 기능은 Git 없이 동작합니다.

| 이름 | 판 | 라이선스 | 어디에 쓰나 |
|---|---|---|---|
| [uv](https://github.com/astral-sh/uv) | `0.12.23` | MIT 또는 Apache-2.0 | 학습 도구의 Python 환경 |
| [Git for Windows](https://github.com/git-for-windows/git) (MinGit) | `2.56.0.2` | GPL-2.0 | 확장 노드·학습 도구 받기 |

앱 자체에 들어 있는 라이브러리의 라이선스는 앱 폴더의 `THIRD_PARTY_NOTICES.md`와 **도움말 → AtelierX 정보 → 제3자 라이선스**에서 볼 수 있습니다.
