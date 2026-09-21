# 이미지 저장 경로

2026-09-13 현재 설치·실행 기준이다. 서비스를 다른 `--data-dir`로 실행하면 해당 경로 아래에 저장된다.

| 용도 | 실제 경로 |
| --- | --- |
| ComfyUI SaveImage 및 AtelierX Encode 저장 결과 | `C:\StabilityMatrix\Packages\ComfyUI\output\AtelierX` |
| ComfyUI PreviewImage 임시 결과 | `C:\Users\kirit\Documents\workspace\AtelierX\artifacts\anima-smoke\comfyui-temp` |
| 일반 Generation 서비스의 결과 사본 | `C:\Users\kirit\Documents\workspace\AtelierX\.atelierx\generation\images` |
| Generation 단독 REST 테스트 이미지·리포트 | `C:\Users\kirit\Documents\workspace\AtelierX\artifacts\generation-rest\<실행시각>` |
| Core 생성 REST 테스트 이미지·리포트 | `C:\Users\kirit\Documents\workspace\AtelierX\artifacts\core-rest\<실행시각>` |
| 보조 노드 ComfyUI 직접 테스트 | `C:\Users\kirit\Documents\workspace\AtelierX\artifacts\postprocess-rest\<실행시각>` |
| Backend 통합 테스트 이미지·리포트 | `C:\Users\kirit\Documents\workspace\AtelierX\artifacts\backend-pipeline-rest\<실행시각>` |
| 그룹 일괄 실행·설정 관리 실환경 테스트 | `C:\Users\kirit\Documents\workspace\AtelierX\artifacts\group-batches-rest\20260913-142529` (이미지: `generation\images`, 결과: `report.json`) |

ComfyUI 원본과 Generation이 HTTP로 회수해 보관하는 사본은 서로 다른 파일이다. Core는 이미지 메타데이터를 SQLite에 저장하고, 이미지 내용은 Generation API를 통해 전달한다. Core API로 새 이미지 파일을 별도 저장하지 않는다. 테스트는 일반 서비스 데이터 디렉터리 대신 실행시각별 폴더의 `generation/images`를 사용한다.

PreviewImage는 미리보기용 임시 저장이므로 보관할 결과는 SaveImage 또는 AtelierX Encode 노드를 통해 저장한다. 현재 ComfyUI 임시 디렉터리는 실행 옵션으로 지정되어 있으며 향후 Stability Matrix에서 다른 옵션으로 재시작하면 달라질 수 있다. 사용자 지정 Workflow의 다른 저장 노드는 해당 노드의 경로 설정을 따른다.

Validation 업로드는 기본 `.atelierx/validation/uploads`에 입력 사본을 보관한다. 검증 서비스 자체는 생성 이미지를 만들지 않는다. 등록 Generation 이미지를 읽어 검증한 요청은 해당 원본 ID와 SHA-256을 이력에 연결한다.

묶음 일관성 대조 검증 보고서는 `artifacts/group-consistency-cases/<실행시각>/report.json`에 저장한다. 원본 이미지를 재사용하며 새 생성은 하지 않는다. 다른 실행의 이미지는 해시/원본 프롬프트를 보존한 Validation 진단 업로드 사본으로만 추가한다.
