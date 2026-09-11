# ADR-0002: 생성 및 후처리 Custom Node 기능 범위

- 상태: Accepted
- 작성일 / 확정일: 2026-09-11
- Supersedes: 없음
- Superseded by: 없음
- 후속 구체화: [ADR-0003](0003-generation-execution-and-queue.md) — 전체 생성용 Workflow 두 개, 후처리 순서, Preset 적용·시도 입력 고정, Generation 파일 보관. 이 ADR은 Accepted로 유지한다.
- 관련 요구사항: [기능 대조표 N-01~N-17](../../requirements/module-feature-comparison.md)

## 결정할 질문

생성 및 후처리 Node가 제공할 기능과 입력·출력 범위. 사용자의 N-01~N-17 검토 결과를 기록하며 각 항목의 확정 요구·미결정 설계·후속 로드맵을 구분한다. 구현 시작 승인은 아니다.

## 배경과 제약

Custom Node는 제작 대상이며 Generation REST Backend와 구분한다. Generation은 ComfyUI를 통해 작업하며 SQLite와 AI Provider에 직접 접근하지 않는다. Core는 SQLite와 주요 상태를 소유한다.

## 결정

| 항목 | 확정 요구 |
| --- | --- |
| N-01 | 생성 및 후처리 Custom Node 기능을 제공한다. 정확한 Node 수는 고정하지 않는다. |
| N-02 | 생성 입력은 모델, 다중 LoRA와 개별 가중치, Positive / Negative Prompt, Resolution, CFG, Steps, Sampler, Scheduler, Seed 등의 파라미터이며 출력은 이미지다. 파라미터 설정을 저장한다. 저장 형식은 미정이며 SQLite 사용도 허용된다. |
| N-03 | Anima와 SDXL Illustrious 계열을 지원한다. 모델 계열별 Scheduler 구성과 Text Encoder 등의 차이를 처리한다. Anima / SDXL 생성 Node를 분리해도 된다. 구체적인 모델 버전별 호환성은 별도 정의한다. |
| N-04 | 설치 모델·LoRA 목록은 ComfyUI 또는 Stability Matrix로 설치한 ComfyUI의 기본 모델·LoRA 폴더 구조를 기반으로 한다. 사용자가 경로를 설정할 수 있어야 한다. 다중 LoRA 선택과 개별 가중치를 지원한다. |
| N-05 | Checkpoint, VAE, CFG, Steps, Seed, Sampler, Scheduler 등의 설정을 제공한다. Steps·CFG 등의 초기값은 각 기본 모델이 제공하는 값을 사용하고 설정을 저장한다. 값의 취득 방식과 제공되지 않을 때의 처리는 미정이다. |
| N-06 | Upscale은 이미지를 입력받고 모델과 배율을 지정한다. Generation Backend가 이전에 생성된 이미지를 입력해 실행할 수 있다. Upscale 모델 목록도 기본 폴더 구조와 사용자 지정 경로를 지원한다. |
| N-07 | 이미지 생성 완료 후 PNG를 유지하면서 별도 WebP를 생성한다. WebP 생성은 On / Off 가능하다. 후속 ADR-0003에서 Encode를 선택한 후처리의 마지막 단계로 확정했다. |
| N-08 | 눈·입·손·얼굴 Detailer를 제공한다. 검출 및 실제 적용 흐름은 ComfyUI-AssetManager를 참고할 수 있다. 특정 모델·옵션·알고리즘 채택은 별도 결정한다. |
| N-09 | NSFW Censor를 제공한다. 검출 및 실제 적용 흐름은 N-08과 같은 저장소를 참고할 수 있다. 검출 대상과 처리 방식은 미정이다. |
| N-10 | 배경 투명화는 On / Off 가능하다. 캐릭터를 검출해 마스크를 만들고 캐릭터 이외 영역의 Alpha를 변경한다. 검출·마스크 모델과 경계 처리 세부는 미정이다. |

N-01~N-05는 생성 Node 기능이며 Anima / SDXL로 분리할 수 있다. N-06~N-10은 후처리 기능이다. Upscale·Detailer·Censor·투명 배경을 별도 Node와 Workflow로 구성하거나 통합 Node로 구성하는 선택 모두 허용된다. Encode / Save는 아래 N-12의 후속 확정에 따라 별도 기능·Node로 분리한다.

## N-11~N-15 검토 결과

2026-09-11 사용자가 기능 범위와 후속 확장 방향을 보완했다.

| 항목 | 현재 결론 | 남은 결정 |
| --- | --- | --- |
| N-11 | 통합 생성 Node를 필수로 요구하지 않는다. 모델별 별도 Node 구성에서 공통 Adapter / Capability 구조를 필수 전제로 두지 않는다. | Node별 설정 검사·Preset 계열 일치 처리는 계속 필요하다. 구체적인 구조는 미선택이며 두 추상화가 모든 경우 불필요하다고 확정하지 않는다. |
| N-12 | Encode / Save를 생성·Upscale 등 이미지 처리와 별도 기능·Node로 분리한다. Frontend에서는 선택적 WebP 출력을 단순 On / Off로 제어하고 WebP 품질을 이 출력 설정에서 지정한다. PNG 보존과 별도 WebP 생성 원칙을 유지한다. | Encode와 Save 자체를 각각 두 Node로 나눌지, 품질 범위·기본값·저장 API는 미정이다. Encode 마지막 순서는 후속 ADR-0003에서 확정했다. |
| N-13 | Upscale은 입력 이미지 외에 모델과 배율만 사용자 설정으로 제공한다. 모델의 고유 배율과 별도로 입력 이미지 대비 최종 배율을 지정한다. 예: UltraSharp 4x를 선택하고 배율 1.5를 지정하면 최종 가로·세로가 입력의 1.5배가 되도록 한다. | 고유 배율과 요청 배율을 맞추는 내부 처리·리샘플링·크기 반올림은 미정이다. 타일·Overlap·목표 크기·Lossless 옵션은 현재 요구에서 제외한다. WebP 품질은 N-12로 이동한다. |
| N-14 | 캐릭터 일관성을 Generation 단계에서 최대한 확보하는 것이 현재 목표다. Anima 자연어 Prompt를 포함한 Prompt 활용과 IP-Adapter·Img2Img 등의 기법을 이 목표를 위한 검토 대상으로 둔다. Inpaint·ControlNet은 후속 로드맵으로 이관한다. | 특정 기법의 일괄 채택이나 Anima / SDXL 공통 호환성을 확정하지 않는다. 모델별 실현 방법·입력·일관성 평가 기준은 미정이다. |
| N-15 | Crop·색감 보정·Watermark는 현재 구현 범위에 넣지 않고 후속 로드맵으로 이관한다. | 도입 시점·릴리즈·세부 옵션은 미정이다. |

로드맵 이관은 [후속 확장 목록](../../requirements/roadmap.md)에 기록한다. N-14의 목적은 생성 시 일관성 확보이며 Validation의 일관성 검사 기능과 구분한다. Core의 Prompt 관리·작성 책임과 Generation의 ComfyUI 전용 실행 원칙을 유지한다.

## 추가 확정: 생성·후처리 Preset Load / Save

2026-09-11 사용자 추가 요구로 설정 저장의 의미를 보완했다.

- **N-16 생성 Preset**: 생성 Node에 입력한 설정을 Preset으로 Save하고 Load할 수 있어야 한다. Anima와 SDXL 사이를 전환할 때 모델 계열별 설정이 섞이거나 부적합한 설정이 적용되지 않도록 해야 한다.
- **N-17 후처리 Preset**: 후처리 Node 또는 Workflow의 설정도 Preset으로 Save하고 Load할 수 있어야 한다. 개별 Node 또는 통합 Workflow 중 어떤 구성을 선택하더라도 이 기능 요구를 충족해야 한다.

Preset Load 시 Current Settings를 변경하고 생성 시도 입력을 고정하는 적용 방식은 후속 ADR-0003에서 확정했다. 모델 계열 구분·호환성 처리, 계열 전환 시 자동 Load 여부, 미저장 설정 처리, Preset의 필드·덮어쓰기 규칙, 후처리 개별 단계와 전체 Workflow Preset의 지원 단위는 미정이다. Preset Load / Save 요구는 N-11 Adapter / Capability 구조의 채택을 의미하지 않는다.

이 보완은 기존 설정 저장 요구를 구체화하며 기존 결정을 대체하지 않는다. Core SQLite 소유권, 저장 형식 미정 및 Generation의 직접 DB 접근 금지 원칙을 유지한다.

## 검토한 대안

사용자는 생성 Node의 모델 계열별 분리와 후처리 Node의 개별·통합 구성 모두 허용했다. 이번에는 어느 한쪽을 선택하지 않는다. 설정 저장도 특정 포맷으로 고정하지 않는다.

## 영향과 트레이드오프

설정 지속 저장은 필요하지만 저장 단위, 시점, 복원·덮어쓰기 규칙과 API는 미정이다. SQLite를 사용한다면 Core 소유 원칙을 유지한다. Node나 Generation이 Core DB를 직접 열도록 승인한 것은 아니다. 모델 경로는 ComfyUI가 설치된 실행 환경의 경로를 대상으로 하며 Client PC의 경로와 같다고 가정하지 않는다.

PNG와 WebP는 별도 파일이므로 파일 관계, Metadata·Alpha 보존 및 실패 처리를 후속 정의해야 한다. 기본 모델이 제공하는 설정값의 출처·우선순위·누락 시 정책도 필요하다.

## 참고 코드 검토

- [Detailer 파이프라인](https://github.com/kiritype/ComfyUI-AssetManager/blob/master/web/js/pipeline/pipeline_detailer.js): 얼굴·눈·입·손 처리의 개별 활성화와 순차 연결을 확인했다.
- [Censor 파이프라인](https://github.com/kiritype/ComfyUI-AssetManager/blob/master/web/js/pipeline/pipeline_censor.js): 검출 마스크에 모자이크 또는 흰색 처리를 합성하는 구성을 확인했다.

2026-09-11 읽기 전용 검토다. 해당 저장소의 Frontend Workflow 구성 위치, 모델 이름, 순서, 옵션 및 소스 재사용을 AtelierX 결정으로 채택하지 않는다. 실행 검증은 하지 않았다.

## 이번에 결정하지 않는 사항

N-11의 구체적인 구조, N-12의 세부 출력 계약, N-13의 내부 배율 처리, N-14의 일관성 구현 기법 및 상세 Node 구조·저장 계약·모델 탐색·기본값 취득·서비스 간 전달은 [backlog](backlog.md)에 남긴다. 후속 로드맵의 기능은 현재 구현 요구로 취급하지 않는다.

## 충돌 및 대체 확인

[ADR-0001](0001-contribution-workflow.md)의 Git 운영 결정과 충돌하지 않는다. 초기 기준선의 Core SQLite 소유권 및 Generation의 직접 DB 접근 금지를 유지한다. Custom Node의 필요 여부를 TODO로만 기록했던 누락을 기능 요구로 보완한다. 기존 ADR의 대체는 없다.

### 변경 이력과 부분 변경 범위

2026-09-11 N-12 확정으로 이 ADR의 이전 표현인 ‘WebP의 물리적인 Node 배치도 고정하지 않는다’를 Encode / Save 별도 기능·Node로 구체화했다. N-13은 Upscale 설정 범위를 좁혔고 N-14~N-15는 현재 목적과 후속 확장을 분리했다. 이는 동일 ADR의 사용자 검토에 따른 갱신이며 별도 ADR 대체 관계는 없다. N-11 공통 추상화 제안을 필수 전제로 삼지 않으며 기존 Preset 설정 혼합 방지 요구는 유지한다.

## 문서 반영

- [x] overview 갱신
- [x] ADR 목록 및 backlog 갱신
- [x] 요구사항·모듈 및 기능 대조표 갱신
- [x] 기존 ADR 상태 및 supersede 관계 확인
- [x] N-11~N-15의 검토 결과·미결정 설계·후속 로드맵 구분
