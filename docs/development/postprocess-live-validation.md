# 보조 노드 실제 설치·REST 검증

2026-09-13. 이전 개별 문서의 CPU 검증/모델 미설치 상태에 대한 후속 실행 기록이다.

## 참고 구현과 설치

사용자가 제공한 [ComfyUI-AssetManager](https://github.com/kiritype/ComfyUI-AssetManager)의 commit `38f689fc5f93da5e159e5948ee9aa24eb15707e6`, `pipeline_detailer.js`, `pipeline_censor.js`, 기본 Workflow를 확인했다. Detailer는 Impact Pack/Subpack의 얼굴 → 눈 → 입 → 손 흐름, Censor는 Ultralytics segmentation 검출과 3종 처리를 따른다.

설치된 ComfyUI `C:\StabilityMatrix\Packages\ComfyUI`에 AtelierX Detailer/Censor/Alpha/Encode와 Impact Pack/Subpack을 연결했다. ComfyUI Python에 Ultralytics 8.4.150, segment-anything 1.0 및 필요한 의존성을 설치했으며 기존 PyTorch를 교체하지 않았다. RTX 4090 환경에서 실행했다.

사용자 첨부 `animeNSFWDetection_v50Variant1.zip`의 단일 모델을 확인하여 설치했다.

- 파일: `C:\StabilityMatrix\Models\Ultralytics\segm\ntd11_anime_nsfw_segm_v5-variant1.pt`
- 크기: 20,585,444 bytes
- SHA-256: `d04eec2d5b657410c90bc06895634a4d9a67f8fc710852fdc67086f30e0cc900`
- 검출 라벨: `nipples,pussy,penis,anus,testicles,x-ray,cross-section`
- 실행 시 외부 모델 다운로드 없이 로컬 등록 모델을 선택한다.

## 실제 결과

| 기능 | 확인한 결과 | 검증 한계 |
| --- | --- | --- |
| Encode | PNG와 WebP 저장·실제 디코딩·파일 descriptor 반환 | PNG 필수, WebP 선택 |
| Alpha | 지정 마스크의 0/128/255 Alpha 보존, person segmentation → RGBA 저장 | 전체 캐릭터 분리 품질은 추가 이미지 평가 필요 |
| Censor | 첨부 모델 자동 검출 → mosaic/white/white_solid 실행 성공, 지정 마스크에서 실제 픽셀 변경 | 옷을 입은 이미지에서 검출 0 확인. 검열 대상의 검출률은 아직 평가하지 않음 |
| Detailer | Anima와 원본 Positive/Negative로 얼굴 → 눈 → 입 → 손 실행 및 저장 성공 | 입은 참고 Workflow와 같은 얼굴 detector fallback, 전용 입 detector 품질 검증 아님 |

Alpha/Censor 검출기에 전달하는 이미지는 YOLO numpy 입력 규격인 BGR uint8로 변환한다. Censor의 검출 0은 정상 결과로 이미지를 유지하며, 모델 오류와 잘못된 라벨 설정은 오류로 반환한다.

실행 기록은 `artifacts/postprocess-rest/20260913-035648`(Encode/Alpha/지정 마스크 Censor/얼굴 Detailer), `20260913-035844`(자동 Censor 3종), `20260913-040004`(원본 Prompt를 보존한 전체 Detailer)에 있다. 재현 스크립트는 `scripts/test_postprocess_rest.py`, `scripts/test_reference_detectors_rest.py`다. 이 스크립트들은 해당 로컬 생성 이미지와 저장된 API fixture를 사용한다.

이 검증은 ComfyUI REST 직접 호출이다. Generation 서비스의 보조 노드 endpoint/전체 생성 파이프라인 연결까지 완료한 것으로 해석하지 않는다.

## 사용자가 실행할 예제

ComfyUI Workflow 목록의 `AtelierX` 폴더에 다음 파일을 설치했다. Load Image에서 입력 이미지를 바꾸고 실행할 수 있다. 출력은 `ComfyUI/output/AtelierX`에 저장한다.

- `Encode - PNG and WebP - 20260913.json`
- `Alpha - Detect Character - 20260913.json`
- `Censor - Automatic Detection - 20260913.json`
- `Detailer - Anima All Parts - 20260913.json`

실제 위치는 `C:\StabilityMatrix\Packages\ComfyUI\user\default\workflows\AtelierX`다. Detailer에서 이미지를 바꿀 때 원본 이미지의 생성 Prompt와 사용 모델도 함께 맞춘다. Censor 예제는 제공 모델과 confidence 0.35, mosaic 처리로 시작하며 처리 방식과 강도는 노드에서 변경할 수 있다.

## ComfyUI 화면 검증

설치한 네 예제를 Workflow 목록에서 직접 열고 실행 버튼으로 각각 실행하여 성공을 확인했다. object_info의 COMBO 타입에 맞춰 예제의 위젯 값 직렬화를 수정했다. UI 실행 기록은 artifacts/postprocess-workflows/ui-execution-report.json이다. Censor 단위 테스트 7개와 Core/Generation 테스트 15개도 통과했다.
