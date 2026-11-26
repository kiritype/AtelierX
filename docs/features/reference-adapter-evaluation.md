# Anima 참조 어댑터 비교 (#359)

기존 BETA의 Anima Ref Adapter v2와 SnapRef v2a의 인물·그림체 참조를 같은 장면에서 비교했다. 앱의 BETA는 Anima v2 가중치를 사용한다. 앱에 고정한 [ArcAnima 노드 f02d54d](https://github.com/ArcAnima/ComfyUI-Anima-Ref-Adapter/tree/f02d54dd34593b4d4ce27b38de2a996049aeac58)는 가중치 형식으로 두 구현을 구분하므로, 단일 이미지 비교는 같은 노드에서 실행했다.

## 설정의 차이

| 항목 | 기존 Anima v2 | SnapRef v2a |
|---|---|---|
| 가중치 | `anima_ref_adapter_v2_r64.safetensors` | BF16 `snapref_v2a.safetensors` |
| 노드 입력 | 모델, VAE, 이미지 | 모델, VAE, 이미지, Anima CLIP |
| 공식 기본과 비교 값 | 참조 가이던스 4.5, APG, LoRA 강도 1, 적용 끝 1 | `cs`, 참조 가중치 1, 빈 캡션, 추가 참조 가이던스 끔 |
| 통합 노드 입력 | 참조 한 장 | 참조 한 장. 원본 SnapRef의 이미지별 강도·Fidelity는 별도 노드에서 제공 |

SnapRef의 `char`는 인물 중심이며 비교에는 그림체도 참조하는 `cs`를 사용했다. 기존 LoRA 강도 1과 SnapRef 참조 가중치 1은 각 방식의 기본값이다. 각각 LoRA 배율과 참조 attention 가중치라 의미가 다르다. [고정 노드의 SnapRef 예제](https://github.com/ArcAnima/ComfyUI-Anima-Ref-Adapter/blob/f02d54dd34593b4d4ce27b38de2a996049aeac58/workflows/anima_ref_adapter_snapref.json) · [v2a 배포 파일](https://huggingface.co/0ppxnhximxr/snapref-v2a/tree/e6d6a21e4d56faae4454a1cc9bfd065d87358bf2)

## 생성 조건

- RTX 4090, Windows, ComfyUI 0.45.0, PyTorch 2.14.1+cu130. Anima base v1.0, `qwen_3_06b_base.safetensors`, `qwen_image_vae.safetensors`. 출력 832×1216, 30스텝, CFG 4.5, `er_sde/simple`, denoise 1. 별도 LoRA나 후처리 없이 생성했다.
- 참조는 Anima base에서 seed 5520, 640×896, 24스텝으로 생성한 가상 인물이다. 청록색 단발, 노란 눈, 빨간 베레모, 노란 케이프, 감색 블라우스와 초승달 브로치가 보인다. 종횡비를 유지하고 흰색 여백을 넣어 1024×1024로 맞춘 같은 이미지를 두 실행에 사용했다. 참조 옷과 외형을 결과의 프롬프트에는 쓰지 않았다.
- 공통 positive 앞부분은 `masterpiece, best quality, score_7, safe`이며, negative는 `worst quality, low quality, bad anatomy, blurry, watermark, jpeg artifacts`다. 각 장면에서 하나의 시드로 두 어댑터를 실행했다. 장면마다 두 어댑터의 실행 순서를 번갈아 바꾸고 각 제출 전 ComfyUI `/free`로 모델을 내렸다.
- 생성 시간은 ComfyUI history의 `execution_start`부터 `execution_success`까지다. 모델 적재와 디코딩을 포함한다. VRAM은 약 0.25초 간격으로 샘플링한 `nvidia-smi`의 장치 전체 사용량 최댓값이다. Windows 데스크톱과 다른 프로세스가 차지한 메모리도 포함하므로 어댑터 단독 메모리나 VRAM 요구량으로 해석할 수 없다.

| 시드 | 공통 장면 프롬프트 |
|---|---|
| 6201 | `1girl, solo, sitting, reading an open book, indoors, library, bookshelves, rain on the window, warm lamplight, upper body, three-quarter view` |
| 6202 | `1girl, solo, full body, running, looking back, meadow, sunset, wind, action pose, side view` |
| 6203 | `1girl, solo, smiling, holding a white porcelain cup, sitting at a cafe table, outdoors, street, spring, afternoon, cowboy shot` |

## 측정과 관찰

| 시드 | 기존 Anima v2 시간 · 시작→최대 MiB | SnapRef v2a 시간 · 시작→최대 MiB | 육안 관찰 |
|---|---:|---:|---|
| 6201 | 18.37초 · 8,313→15,993 | 12.23초 · 8,377→16,921 | 모두 열린 책·빗창과 외형을 반영. v2a는 초승달과 스탠드가 뚜렷하고, 기존 결과의 장식은 원형 테두리에 가까움 |
| 6202 | 17.64초 · 8,377→15,737 | 11.87초 · 8,377→16,537 | 모두 전신으로 달리고 뒤돌아봄. v2a는 측후면, 기존 결과는 발바닥이 크게 보이는 후면 구도. 두 결과의 브로치는 시점상 가려짐 |
| 6203 | 17.73초 · 8,377→15,897 | 11.94초 · 8,377→16,281 | 모두 야외 테이블에서 찻잔을 들고 원래 머리·눈·옷을 유지. v2a는 초승달 형태를 유지하고 찻잔에 금테 추가, 기존 결과의 브로치는 원형에 가까움 |

세 쌍 모두 머리색, 눈색, 베레모와 케이프를 유지했다. v2a는 기존 대비 중앙값이 약 33% 짧았고 장치 전체 최대 VRAM 사용량은 세 쌍에서 384~928 MiB 높았다. v2a는 브로치 형태를 더 잘 보존한 두 결과가 있었고, 조명이나 의상 채도도 달라졌다. 한 인물, 세 장면에서 나온 육안 관찰이다. 다른 인물·그림체·낮은 VRAM 환경에서도 비교한 뒤 v2a를 별도 선택지로 검토할 수 있다.

## 참조 이미지 여러 장과 두 인물

- [Anima Ref Adapter README의 Two characters](https://github.com/ArcAnima/ComfyUI-Anima-Ref-Adapter/blob/f02d54dd34593b4d4ce27b38de2a996049aeac58/README.md#two-characters)는 경찰관과 메카 캐릭터 등 두 인물을 보여 준다. [연결된 워크플로](https://github.com/ArcAnima/ComfyUI-Anima-Ref-Adapter/blob/f02d54dd34593b4d4ce27b38de2a996049aeac58/workflows/anima_ref_adapter_two_characters.json)에서는 `LoadImage` 두 개를 `ImageStitch`로 가로 합성하고 어댑터의 단일 `image`에 보낸다. 앞뒤 관계나 좌표 대신 장면 프롬프트로 좌우를 지정한다.
- SnapRef의 [v2a 두 인물 예제](https://huggingface.co/0ppxnhximxr/snapref-v2a/blob/e6d6a21e4d56faae4454a1cc9bfd065d87358bf2/workflows/snapref_v2a_two_characters.json)도 두 사진을 가로로 합친다. [다중 참조 강도 예제](https://huggingface.co/0ppxnhximxr/snapref-v2a/blob/e6d6a21e4d56faae4454a1cc9bfd065d87358bf2/workflows/snapref_v2a_multi_reference_weights.json)는 한 캐릭터의 두 사진을 따로 연결하고 이미지별 가중치 1과 0.4를 준다.
- [MossRef v2 README와 예제](https://github.com/Neon3579/MossRef/blob/v2.0.0/README.ko.md)에서는 사진을 따로 받아 양쪽 노드에 동일한 순서로 연결하고 프롬프트에서 `Picture 1`과 `Picture 2`를 쓴다. 참조 인물마다 상자나 마스크를 받는 입력은 제공하지 않는다. AtelierX의 [MOSS Layout](https://github.com/kiritype/AtelierX/issues/307)에는 프롬프트 배치 상자가 있으며, 참조 인물과 상자를 연결하는 조합의 동작은 별도로 검증해야 한다.

### 두 인물 좌우 교환 확인

같은 RTX 4090에서 두 가상 인물로 한 장면을 시험했다. A는 위의 청록 머리 캐릭터, B는 seed 5521로 같은 설정에서 생성한 분홍색 단발·동그란 안경·검은 모자·파란 세일러 재킷의 인물이다. 공원 야외 카페에서 같은 원형 탁자에 앉는 장면과 seed 6301을 고정하고, 좌우를 바꿀 때 참조 순서와 프롬프트의 좌우 묘사를 함께 바꿨다.

| 방식 | A 왼쪽/B 오른쪽 | B 왼쪽/A 오른쪽 |
|---|---|---|
| Anima v2, 합본 입력, 1216×832 | 두 인물과 좌우가 맞고 옷·모자·안경이 각각 유지됨 | 좌우가 바뀌고 인물별 옷·모자·안경이 유지됨 |
| MossRef v2.0.0, 독립 이미지 2장, 1024×768 | 좌우와 머리색이 맞고 양쪽 의상·모자가 섞임 | 좌우가 바뀌지만 두 인물에 노란 케이프·세일러 칼라·빨간 베레모가 섞임 |

MossRef는 SFT·Qwen3.5 9B INT8 convrot, Flux2 VAE, `auto`, `ref_edge=512`, `ref_attn_bias=0.45`, `target_strength=0.85`, 35스텝, CFG 3.5, `euler/sgm_uniform`을 사용했다. 장면·시드 한 쌍이므로 모델별 성공률로 일반화할 수 없다. 참조 순서와 프롬프트를 함께 바꿨기 때문에 위치 정보의 단독 효과도 측정하지 않았다.

다음 기능 범위로는 **인물 A/B에 원본을 각각 등록하고 좌우를 고르는 방식**을 제안한다. Anima v2에서 원본 두 장을 내부 합성하고 각각의 원본과 좌우 설정을 기록하면 현재 단일 참조 그래프를 활용할 수 있다. MossRef의 인물별 의상 구분은 역할 `character`와 의상 설명을 포함한 여러 장면·시드에서 다시 확인한다. 좌표 배치 기능은 참조 순서·문구·시드를 고정하고 Layout 박스만 바꿔서 인물이 따라가는지 별도로 시험한다.
