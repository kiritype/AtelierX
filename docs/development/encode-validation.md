# Encode / Save Custom Node 검증 기록

상태: 구현 및 CPU 검증 준비. 작성일: 2026-09-13.

`AtelierXEncodeSave`는 ADR-0002 N-07/N-12와 ADR-0003의 마지막 Encode 순서를
구현하는 ComfyUI output node다. RGB 또는 기존 RGBA `IMAGE` batch를 받고 PNG를
항상 `ComfyUI output/AtelierX`에 저장하며, 선택하면 같은 stem의 WebP를 추가로
저장한다. PNG의 standard `filename`/`subfolder`/`type` descriptor는 `ui.images`로
반환하고 원본 IMAGE도 반환하므로 ComfyUI history와 UI가 PNG를 표시할 수 있다. 또한
`ui.atelierx_files`에는 `format`이 있는 PNG와 선택 WebP descriptor 전체를 반환해
Generation 같은 기계 consumer가 WebP를 발견할 수 있다.

입력은 `image`, `filename_prefix`(기본 `image`), `webp_enabled`(기본 false),
`webp_quality`(기본 90, 1~100)다. `filename_prefix`는 경로 구분자와 상위 경로를
받지 않아 output 바깥으로 저장할 수 없다. MASK는 입력으로 두지 않았다. 최종
저장 단계에서는 RGBA 자체의 alpha를 보존하고, ComfyUI MASK 적용은 Alpha node 등
상위 단계가 담당한다.

각 파일명은 UUID stem과 원자적 no-clobber publish를 사용하므로 기존 출력은 덮어쓰지
않는다. PNG는 임시 파일 후 완료하며 WebP가 뒤이어 실패해도 완료된 PNG는 복구용으로 남는다.
그 경우 node는 오류를 전파하고 결과 descriptor를 반환하지 않는다. PNG와 WebP는
Pillow가 decode 가능한 실제 이미지이며 RGBA alpha를 보존한다. WebP의 RGB는 손실
압축이므로 PNG와 픽셀 동일성은 요구하지 않는다.

## CPU 검증

다음은 GPU, 모델 다운로드, ComfyUI 재시작 없이 실행한다.

```powershell
C:\StabilityMatrix\Packages\ComfyUI\venv\Scripts\python.exe -B -m unittest discover -s custom_nodes\atelierx_encode\tests -v
C:\StabilityMatrix\Packages\ComfyUI\venv\Scripts\python.exe -B custom_nodes\atelierx_encode\scripts\validate_examples.py
```

단위 테스트는 실제 Pillow 출력 decode, PNG/WebP 크기와 RGB/RGBA alpha, WebP Off,
batch 별 다른 stem, 기존 파일 비덮어쓰기, 경로/품질/입력 오류 및 WebP 실패 시 PNG
보존과 오류 전파를 확인한다. Comfy 0.35.0 API fake registry test는 node schema,
output-node 표기와 `ui.images` history descriptor도 확인한다.

`scripts/Install-AtelierXEncode.ps1 -ComfyRoot C:\StabilityMatrix\Packages\ComfyUI`
는 소스 패키지를 `custom_nodes\atelierx_encode` junction으로 연결할 준비만 하며
다른 파일·Node를 덮어쓰지 않는다. 실제 설치, 재시작 여부와 `LoadImage` 예제 workflow
실행 및 REST 검증은 실행 중인 사용자 작업과 GPU를 조율하는 주 에이전트가 수행한다.


## 2026-09-13 실제 설치·실행 후속 기록

이 문서의 초기 CPU 검증·미설치 기록 이후 ComfyUI 설치와 REST 실행을 완료했다. 현재 모델·실행 결과·사용자 Workflow와 검증 한계는 [보조 노드 실제 검증](postprocess-live-validation.md)을 따른다.
