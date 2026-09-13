# 일관성 판정 개선 및 기본 Upscale 실검증 — 2026-09-13

## 완료 범위

서브에이전트가 묶음 판정·Upscale REST·정책 문서를 분담했고 주 에이전트가 Core 기본값/Validation 최종 크기 계산, 실제 설치·실행 및 통합 회귀를 담당했다. Backend 전체 124개 시험이 통과했다(15.144초). 별도 Upscale 노드 시험 5개 및 예제 검증도 통과했다.

### 묶음 일관성

이전 실검증의 두 이미지를 새로 생성하지 않고 재사용했다. 기준/대상 관찰 분리, identity 속성별 차이 근거, 모순 응답 거부를 적용했다. 최초 개선(v6)은 머리 길이와 함께 표정 차이도 differences에 기록했으므로, 허용되는 변화가 불합격 근거에 섞이지 않도록 속성을 제한한 v7로 보완했다.

최종 실제 결과는 completed / outcome=failed / 대상 mismatch다. 유일한 차이 속성은 hair_length이며 기준의 bob haircut과 대상의 long straight hair를 구분했다. upper(white shirt)는 matched이며 표정은 불합격 근거에 들어가지 않았다. Provider 오류·자동 재생성은 없었다.

결과: `artifacts/group-batches-rest/20260913-142529/group-consistency-recheck-v7.json`. 이전 합격 결과와 v6 재검증 결과는 덮어쓰지 않았다. 이는 특정 회귀 사례 개선 확인이며 모든 캐릭터·복장·가림 조건의 정확도를 보장하지 않는다.

### 1024 생성→1536 최종 출력

Core 요청에서 width/height/postprocess를 생략해 실제 기본값을 확인했다. Anima 1024×1024→AtelierXUpscale(4x-UltraSharp.safetensors, scale1.5)→AtelierXEncodeSave가 실행되어 PNG와 WebP가 모두 1536×1536으로 저장됐다. Validation의 최종 기대 크기도 1536으로 고정되어 두 형식 모두 통과했다. 이 시험의 VLM은 로컬 계약 검증용 stub이며 이미지 품질 판정 시험은 아니다. ComfyUI 생성·모델 Upscale은 실제 GPU 실행이다.

첫 실행의 PNG는 테스트 stub의 기본 HTTP body 제한으로 413이 발생했다. 실제 Upscale 출력은 정상이고 WebP 검증도 통과했다. stub 수신 한도를 보완한 후 새 격리 시험에서 두 형식 모두 통과했다. 성공 결과: `artifacts/upscale-default-rest/20260913-144356/report.json`. 출력은 같은 폴더의 `generation/images`, ComfyUI 원본은 `C:\StabilityMatrix\Packages\ComfyUI\output\AtelierX`에 있다. 완료 후 Core GPU owner/waiting/blocked가 비어 있음을 확인했다.

### 설치 및 직접 실행

- 모델: [저자 Kim2091의 4x-UltraSharp.safetensors](https://huggingface.co/Kim2091/UltraSharp/blob/920fe218c211f831b43cb30327f203e2b59f5dab/4x-UltraSharp.safetensors), 66,864,028 bytes.
- 설치 경로: `C:\StabilityMatrix\Models\ESRGAN\4x-UltraSharp.safetensors`.
- SHA-256: `36a340b5509b699d2c06cb445ddc1d3d39199ac734d889ed6d7915f60e05bcbc` (다운로드 메타데이터와 대조).
- Upscale 노드는 기존 ComfyUI custom_nodes에 저장소 junction으로 연결했다. 자동 재시작은 정책 검토에 차단됐으며 사용자가 재시작한 후 실제 등록·실행을 확인했다. 사용자의 0.0.0.0 listen 설정은 유지하며 시험은 localhost:8188로 접속했다.
- 직접 실행 Workflow: `C:\StabilityMatrix\Packages\ComfyUI\user\default\workflows\AtelierX_1024_to_1536_UltraSharp.workflow.json`.
- 저장소 예제: `custom_nodes/atelierx_upscale/examples/anima-ultrasharp-default.workflow.json`.

위 Workflow는 Anima→Upscale→Encode 3개 노드로 구성되며 기존 사용자 Workflow를 덮어쓰지 않고 추가했다. 실제 REST 경로는 실행 검증했고, 추가한 UI Workflow 파일의 화면 조작 자체는 별도로 실행하지 않았다. http://localhost:8188에서 파일을 열고 Queue로 실행할 수 있다.

다음 검증은 동일 외형에서 표정만 바뀐 경우, 복장 변경, 가림, 여러 보조 기준이 있는 경우의 일관성 회귀 확장이다. 27B Agent 연동과 SDXL 등 나머지 범위는 기존 로드맵을 유지한다.

후속 [6개 대조 사례 검증](group-consistency-controls.md): v7 4/6 기대 일치 이후 v8 근거 계약을 보완했다. 최신 실제 실행은 2건 일치·1건 timeout·3건 미실행이며, 회귀 131개 통과와 VLM 품질 완료를 구분한다.

[토큰 상한 후속](group-consistency-controls.md): 회귀 135개 통과, json_schema 실제 6건 모두 실행(4건 기대 일치·1건 상한 오류·1건 기준 충돌 오판). 약180초 timeout 사례를 약10초의 명시적 상한 오류로 종료했으며 판정 품질은 미완료다.
