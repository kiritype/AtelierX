# Detailer Custom Node 검증 기록

상태: Impact orchestration 구현 및 CPU stub 검증. 작성일: 2026-09-13.

`AtelierXImpactDetailerPipeline`은 제공된 AssetManager workflow와
`pipeline_detailer.js`의 **Face → Eye → Mouth → Hand** 순서를 따른다. 각 pass의
enabled flag와 Ultralytics detector model을 개별 입력으로 두며, `SAMLoader`,
`ToDetailerPipe`, `FaceDetailerPipe`를 사용한다. 기본 detector는 reference의
`bbox/face_yolov8m.pt`, `segm/PitEyeDetailer-v2-seg.pt`,
`bbox/face_yolov8m.pt`, `bbox/hand_yolov8s.pt`; SAM은
`sam_vit_b_01ec64.pth`다.

Impact Pack 또는 Subpack이 없으면 package discovery 자체는 계속 가능하다. enabled
pass를 실제 실행할 때 `nodes.NODE_CLASS_MAPPINGS`에서 필요한 class를 확인하고
누락 class 이름을 포함해 오류를 낸다. disabled pass는 provider, SAM, model을 load하지
않으며 모두 disabled면 입력 IMAGE를 그대로 돌려준다. 가중치 다운로드·설치·GPU
추론은 이 작업에서 하지 않았다.

기존 `AtelierXDetailer`는 supplied MASK로 native masked diffusion을 실행하는
보조 node다. 이는 detector orchestration의 대체가 아니다.

```powershell
C:\StabilityMatrix\Packages\ComfyUI\venv\Scripts\python.exe -B -m unittest discover -s custom_nodes\atelierx_detailer\tests -v
C:\StabilityMatrix\Packages\ComfyUI\venv\Scripts\python.exe -B custom_nodes\atelierx_detailer\scripts\validate_examples.py
```

테스트는 실제 file/model 없이 realistic Impact stubs로 detector → SAM → detailer
pipe → FaceDetailerPipe 호출과 Face/Eye/Mouth/Hand 순서, disabled skip, required class
오류 및 public schema를 검증한다. `Install-AtelierXDetailer.ps1`은 source junction만
생성한다. 설치된 ComfyUI 연결, Impact dependency 설치, model 배치, restart와 실제
workflow/REST 실행은 주 에이전트가 조율한다.


## 2026-09-13 실제 설치·실행 후속 기록

이 문서의 초기 CPU 검증·미설치 기록 이후 ComfyUI 설치와 REST 실행을 완료했다. 현재 모델·실행 결과·사용자 Workflow와 검증 한계는 [보조 노드 실제 검증](postprocess-live-validation.md)을 따른다.
