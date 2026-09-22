# 기능 요구사항과 범위

2026-09-22 최신 사용자 확정: 외형은 캐릭터에 저장하고 의상은 상의·하의·액세서리를 저장한다. 조각은 상의·하의·액세서리 포함 여부(액세서리 기본 포함)를 지정하며 외형은 항상 포함한다. 아래 과거 의상 내부 외형 표현보다 이 정정이 우선한다. 캐릭터 관리/이미지 생성 및 검토/갤러리를 분리한다. 상세 실행 범위는 [UI 개편](../development/frontend-library-ux-review.md)을 따른다.

2026-09-22 사용자 승인: [전역 조각·모바일 제작 UI](../development/frontend-library-ux-review.md)를 구현한다. 조각은 사용자 관리 단일 계층 카테고리와 전체 고유 자동 번호(불변·재사용 없음)를 사용한다. 캐릭터/의상별 검증 통과 결과를 이미지셋으로 조회하고, 파일명 구조는 보류한다. 반응형 탐색·입력·상태 보존을 포함하며 Core의 실행·판정 책임을 유지한다.

2026-09-21 사용자 승인: 개인용 Frontend는 고정 주소의 Cloudflare Access 로그인 후 Core 토큰을 반복 입력하지 않고 연결한다. 연결 토큰은 서버의 비공개 설정에 저장하고 설정 화면에서 상태 확인·검증 후 교체한다. 토큰 원문을 응답·정적 파일·브라우저 저장소·URL에 넣지 않으며, 서비스 전체 토큰 회전과 구분한다. Google OAuth 전환은 후속으로 미룬다. [적용 및 검증 상태](../development/remote-access.md).

2026-09-21 Discord 서버 추가: 기존 테스트 서버와 사용자가 추가 지정한 서버를 허용한다. 두 서버의 모든 채널에서 멤버가 사용할 수 있으며 다른 서버와 DM은 차단한다. [운영 반영 상태](../development/discord-personal-bot.md).

2026-09-21 최신 사용자 지시: Discord 봇은 일반 테스트용으로 두고 추가 개발의 순위를 뒤로 미룬다. 본체 Backend/F/E 제작 흐름의 남은 기능을 우선 검토한다. 아래 같은 날짜의 Discord 우선 착수 기록은 당시 범위다. [현재 우선순위 제안](../development/remaining-work-priorities.md).

2026-09-21 사용자 지시: 배포 전에는 개인 제작용으로 사용한다. Discord 봇을 우선 구현하며, 자연어→로컬 LLM Prompt 변환 또는 자연어/Positive 원문 입력→이미지 응답을 지원한다. Discord 요청에는 F/E의 그룹 선택이 필요하지 않다. 후속 지시로 봇 설치는 소유자만, 지정한 서버/채널의 사용은 모든 멤버에게 허용한다. 새 `/draw`의 생성 결과는 채널에 공개하고 이미지 스포일러를 기본 적용한다. `/status` 조회는 요청자별로 분리한다. Discord 대기시간·응답 만료를 처리한다. 기존 분류/조각 제작의 프롬프트 정책은 유지하며, 그룹 없는 요청에 캐릭터 문구를 임의 삽입하지 않는다. [상세](../development/discord-personal-bot.md).

2026-09-13 최신 사용자 정정: 조각 기반 제작에서는 **외형을 항상 포함**한다. 전역 공유 조각은 본문과 **상의·하의 포함 여부만** 저장하며 appearance 선택 필드는 두지 않는다. 아래 과거 조각별 외형 선택 설명을 대체한다. 전역 Positive + 외형 + 선택한 상의/하의 + 조각 본문, 전역 Negative + 캐릭터 Negative를 사용한다. 구현·테스트를 계속 진행하도록 승인됐다.


2026-09-13 최신 사용자 확정: 사용자 Prompt 조각은 작품·캐릭터·의상과 독립된 **전역 공유 라이브러리**로 관리한다. 조각별로 외형·상의·하의 포함 여부를 지정한다. 기존 캐릭터 소속/연결을 필수로 하는 조각 설계는 대체한다. 제작에서는 대상 의상 그룹과 전역 조각을 선택하며, 구도·표정·동작·상황은 조각 본문에 함께 작성한다. Positive는 전역 품질 + 조각이 포함하도록 지정한 의상의 외형·상의·하의 + 조각 본문으로 조합한다. 기존 전역 Negative + 캐릭터 Negative 및 검증 책임은 유지한다.

2026-09-13 대량 조합 추가 정정: 기본 구도는 1개이며 표정·동작은 한 묶음으로 사용한다. 구도×표정×동작의 독립 Cartesian 전개는 기본 흐름이 아니다. 사용자는 조각의 구도/표정/동작 구분을 없앤 단일 Prompt 조각 모델도 허용했다. 캐릭터 일괄 제작으로 수천 개 이미지를 한 번에 Queue에 접수할 수 있어야 하며 32개 제한은 해제한다. 전체 대기 개수와 GPU 동시 실행 수는 구분한다.

2026-09-13 대량 제작 후속 정정: 캐릭터별 생성 수는 수십 개 이상 가능하며 제품 차원의 개수 상한을 두지 않는다(32개 초과 지원). 사용자가 직접 입력·저장한 Prompt 조각을 체크하여 가져온다. 기존 Batch의 32개 제한은 구현 제약이며 요구사항이 아니다. 조각 기반 대량 실행을 구현하기 전에 전체 flow를 재검토한다.

2026-09-13 사용자 UI 추가 요구: 제작·갤러리는 작품 > 캐릭터 > 의상의 접이식 분류 탐색을 공유한다. Seed 랜덤 선택, sampler/scheduler 드롭다운, 자유 구도 Prompt 및 구도·표정·자세/동작·상황 다중 행 편집을 제공한다. 캐릭터와 연결한 Prompt 조각을 이용한 대량 제작은 기존 Batch·검증 flow와 사전 대조 후 진행한다. 대량 후보의 자동 전개나 저장 모델 확정은 이번 화면 입력 확장과 구분한다.

[ADR-0023](../architecture/adr/0023-negative-prompt-sources.md) 확정: 전역 Negative는 생성에만 사용하고 불합격 근거에서 제외한다. 캐릭터별 Negative는 생성에 사용하며 이미지에 나타나면 불합격이다. 실제 합성 문구와 출처별 원문을 시도별 보존한다.

이 문서는 사용자가 전달한 기능 요구사항을 기록한다. **요구사항은 구현 완료를 뜻하지 않으며**, 지원 후보와 구체적인 설계는 별도 확정이 필요하다. 아키텍처의 확정 여부는 [overview](../architecture/overview.md), 미정 설계는 [ADR backlog](../architecture/adr/backlog.md)를 참고한다.

원래 공유 대화의 구체 기능 중 이 문서에서 누락·축약된 항목을 [모듈별 기능 대조표](module-feature-comparison.md)에 복원해 사용자 검토 중이다. 이 문서만으로 원문 요구 전체가 보존됐다고 간주하지 않는다. 검토 결과에 따라 본문과 관련 ADR을 갱신한다.

## Core 관리 기능

[ADR-0022](../architecture/adr/0022-prompt-composition.md) 확정: Positive는 전역 퀄리티 → 외형 → 상의 → 하의 → 선택 구도·표정·동작·상황 순서로 조합하며 구도상 제외 항목은 넣지 않는다. Negative는 전역 기본, 초기 의상별 저장 항목 없음이다. 분류명 자동 삽입 없이 문구·가중치를 보존하고 일반 조합에서 AI 재작성·번역·유사 문구 삭제나 후순위 자동 덮어쓰기를 하지 않는다. 확인 가능한 모순은 생성 전에 수정하도록 안내한다. Core가 최종 문구를 확인 가능하게 제공하고 제출 문구를 시도별로 보존한다. 저장 버전·복수 선택 조합·모델 문법은 후속 계약이다.

ADR-0021 추가 확정: 전역 Positive(퀄리티)·Negative Prompt를 별도 저장·편집한다. 의상 내부 Prompt는 외형 / 상의 / 하의(풋웨어 포함)로 관리한다. 풋웨어는 하의에 포함하며 조합·구도별 적용 상세는 미정이다.

현재 확정 계층은 **작품 > 캐릭터 > 의상(외형 포함)** 이다(2026-09-13 사용자 추가 정정). 외형은 의상 항목 내부 Prompt 구성으로 관리하며 별도 선택 단위로 두지 않는다. 아래 최초 ADR-0021의 독립 외형 표현은 이 정정으로 대체된다. 그룹은 선택 의상 항목의 외형·복장 내용을 고정하며 재사용·참조의 상세 계약은 미정이다.

2026-09-13 사용자 정정: 작품 / 캐릭터 / 의상은 Frontend Prompt 편집 화면과 DB 저장의 category다. 작품은 생성 Prompt에 들어가지 않으며 분류명 자동 삽입이나 분류 순서에 따른 Prompt 조합을 요구하지 않는다. 아래 ADR-0021의 독립 관계 표현은 category 의미에 맞춰 재검토 중이고 구체 DB 구조는 미정이다.

[ADR-0021](../architecture/adr/0021-core-domain-and-image-groups.md) 확정: 작품 미지정·여러 작품 연결이 가능한 독립 캐릭터, 캐릭터별 복수 외형 완성본(초기 상속 없음), 캐릭터 간 공유·복제 가능한 의상을 지원한다. 의상 내부에 분류별 복수 요소와 여러 신체 영역에 걸치는 요소를 표현한다. 공유 데이터 편집 시 사용처를 확인하며 과거 이미지·진행 중 작업은 당시 내용을 유지한다. 기본 정리는 보관이고 참조 중 영구 삭제를 제한하며 작품 보관·연결 해제로 캐릭터·의상·이미지를 연쇄 삭제하지 않는다. 그룹마다 외형·의상 구성을 고정하고 기존 그룹 추가는 고정 구성을 사용한다. 수정 구성은 새 그룹으로 생성하며 같은 조합의 별도 그룹도 허용한다. Prompt 조합과 상세 삭제 절차는 후속 결정이다.

- 작품, 캐릭터, 캐릭터 외형 관리.
- 의상 내부 외형 / 상의 / 하의(풋웨어 포함) 관리. 장식은 관련 구성에 포함한다.
- Prompt, 전역 Positive / Negative Prompt, 표정 / 상황 / 동작 등의 Prompt 관리.
- Prompt Version 관리.
- 생성 Preset 및 설정, Validation 관련 설정, 애플리케이션 전역 설정 관리.
- 작업 Context 준비와 생성·검증·재생성 흐름 조정. 전체 작업 이력·재생성 상한 관리([ADR-0003](../architecture/adr/0003-generation-execution-and-queue.md)).
- 이미지 Metadata 관리.
- JSON 등의 Import / Export.

Prompt 생성·편집 보조를 위한 Provider 연동을 지원하는 방향이다. 지원 대상으로 Local LLM, OpenAI, Gemini, OpenAI-compatible API 및 향후 추가 Provider를 고려한다. 구체적인 모델·실행 방식·구현 라이브러리는 미정이다.

AI 또는 Agent는 허용된 Core REST API 작업을 사용한다. SQLite나 임의 SQL 실행 권한을 직접 제공하지 않는다. 외부 AI Context는 요청에 필요한 최소 데이터로 제한한다. AI Prompt 변경의 Draft → Review → Apply는 **Proposed**이며 상세 권한과 Secret 관리는 별도 ADR 대상이다.

## Generation 실행 요구 — ADR-0003

[ADR-0003](../architecture/adr/0003-generation-execution-and-queue.md)에 G-01~G-10 검토 결과를 반영했다.

- 각 Node 기능별 REST API와 Node 입력 기준 파라미터를 제공한다. 전체 생성용 Workflow는 Anima 기본·SDXL 보조 두 개이며 단독 기능은 별도 Workflow 또는 부분 실행을 허용한다.
- 생성 → Upscale → Detailing → Censor → 배경 투명화 → Encode 순서로 선택한 후처리를 적용한다.
- Core가 작품·캐릭터·Prompt·생성 및 후처리 설정을 포함한 작업 Context를 준비하고 API로 전달해 생성·검증 흐름을 조정한다. 공유 파일이나 Generation의 DB 직접 접근을 요구하지 않는다.
- Preset Load는 Current Settings 값을 변경한다. 생성 시도 입력은 고정되어 이후 편집의 영향을 받지 않는다. 정확한 Context Schema·접수 계약은 미정이다.
- Validation은 재생성 여부와 해당 이미지의 새 시도에 사용할 변경값을 반환한다. 모든 생성 설정 변경을 허용하되 최소 변경을 기본으로 한다. Core는 상한·이력을 관리하며 원본 Prompt·Preset을 변경하지 않고 새 생성 시도를 요청한다.
- 자동 재생성 On / Off 및 최대 횟수는 Core 설정으로 지정하며 상한 기본값은 5회다. 사용자 수동 재생성은 횟수 제한이 없으며, 최초 생성·수동 재생성은 자동 재생성 횟수에 포함하지 않는다. 수동 요청마다 자동 사용 횟수를 0으로 초기화하고 설정 상한을 새로 부여하며 기존 이력은 보존한다. 자동 재생성 Off와 오류 후 자동 실행 금지는 유지한다. 상한은 0 이상의 정수이며 0이면 자동 재생성하지 않는다. 실제 자동 실행 시작 시 1회 차감하고 대기 취소는 제외하되 실행 후 실패·취소는 포함한다. 생성 후 Validation 오류는 횟수를 유지하고 자동 흐름을 종료한다. 상한 도달 시 마지막 이미지·검증 결과를 보존하고 추가 자동 생성을 종료한다. 설정 변경은 새 생성·수동 재생성 요청부터 적용하며 진행 중인 흐름에는 소급하지 않는다(ADR-0003, 2026-09-13 추가 확정).
- 동일 GPU의 Generation 작업은 하나씩 접수 순서대로 실행한다. 대기·실행 취소 및 전체 작업의 후속 단계 중지를 지원한다. 재시작 시 대기를 복원하고 실행 중 작업은 ComfyUI 상태를 확인해 추적하거나 실패 처리한다.
- 현재 실행 Node를 표시한다. 최종 출력 검토를 사용하며 진행 중 이미지 미리보기는 보류다. 결과 파일은 Generation 영역에 보관하고 원격 접근·경로·Metadata 등록 계약은 후속 정의한다.
- Generation은 에러코드·관련 로그·API 오류 정보를 제공한다. Validation의 코드별 예외·복구 정책은 Validation 설계에서 정한다.
- 예상 Queue 2,000~3,000건을 위해 REST 페이지 조회 + SSE 변경 알림을 제공한다. 취소 UI를 즉시 반영하고 실제 중단과 요청 중 상태를 구분한다. 대량 변경 묶음, 필요 페이지 재조회, 누락분 복구 불가 시 재조회를 지원한다. 완료마다 전체 목록 재조회나 전체 목록 반복 SSE 전송은 사용하지 않는다.
- Queue 저장 기술·Batch 묶음·SSE 이벤트 및 복구 계약·Generation과 Validation의 GPU 자원 공유는 미정이다.

## Generation Node 기능

- 생성 Node의 입력 설정을 Preset으로 Save / Load할 수 있어야 한다. Anima / SDXL 전환 시 모델 계열별 설정 혼합과 부적합한 적용을 방지한다(N-16).
- 후처리 Node 또는 Workflow의 설정도 Preset Save / Load를 지원한다(N-17). 개별 단계와 전체 Workflow의 Preset 지원 단위는 미정이다.
- 위 Preset 기능은 [ADR-0002](../architecture/adr/0002-custom-node-functional-scope.md)의 추가 확정 요구다. 자동 Load, 미저장 변경·덮어쓰기 처리, 필드·저장 형식·API는 후속 정의한다.

- ComfyUI 연결 및 Workflow 생성·실행.
- 이미지 생성 및 최종 결과 저장을 위한 Generation 작업.
- Checkpoint, 다중 LoRA 및 개별 Weight, VAE 설정.
- CFG, Steps, Seed, Sampler / Scheduler 등 Advanced 설정.
- Upscale 및 이미지 후처리.
- Generation Job / Progress 제공.

Anima와 SDXL Illustrious 계열 지원은 N-03 검토로 확정했다. 향후 추가 모델은 검토 대상이다. 구체적인 모델 버전별 지원 수준은 미정이다. 별도 생성 Node에 공통 Adapter / Capability 구조를 필수로 요구하지 않는다. 모델별 설정·Preset 검사 세부는 후속 정의한다.

Custom Node의 N-01~N-10 기능은 [ADR-0002](../architecture/adr/0002-custom-node-functional-scope.md)에 확정 기록했다. 생성 입력은 모델, 다중 LoRA·가중치, Positive/Negative Prompt, Resolution, CFG, Steps, Sampler, Scheduler, Seed 등이며 이미지가 출력된다. 기본 생성 해상도는 1024×1024이고 사용자가 명시한 해상도는 이를 우선한다. 설정을 저장하고 기본 모델 제공값으로 초기화한다. SQLite 저장도 허용되나 저장 형식·단위·복원과 기본값 취득·누락 정책은 미정이다.

설치 모델·LoRA 및 Upscale 모델은 ComfyUI 또는 Stability Matrix 설치의 기본 폴더 구조와 사용자 지정 경로를 지원한다. Anima / SDXL의 Scheduler·Text Encoder 차이를 처리하며 생성 Node를 계열별로 분리할 수 있다.

Upscale은 이미지·모델·배율을 입력받으며 Generation Backend에서 이전 생성 이미지를 입력할 수 있다. PNG를 유지하며 별도 WebP를 생성하는 옵션을 제공한다. 눈·입·손·얼굴 Detailer와 NSFW Censor는 ComfyUI-AssetManager의 검출·적용 흐름을 참고할 수 있다. 배경 투명화는 캐릭터를 검출·마스킹하고 이외 영역의 Alpha를 변경한다. WebP 생성 및 배경 투명화는 On / Off 가능하다.

N-01~N-05는 생성, N-06~N-10은 후처리 기능이다. 후처리는 개별 Node / Workflow 또는 통합 Node 구성이 가능하다. Encode / Save는 별도 기능·Node로 분리하고 Frontend는 WebP On / Off와 품질 설정을 제공한다(N-12). Encode는 선택한 후처리의 마지막 단계다(ADR-0003). Encode와 Save 자체의 Node 수·저장 계약은 미정이다.

Upscale 사용자 설정은 모델과 입력 대비 최종 가로·세로 배율만 제공한다(N-13). 기본값은 UltraSharp 4x 등 4배 모델과 최종 배율 1.5로, 기본 1024×1024 입력에서 최종 1536×1536이다. 모델의 고유 4배는 최종 출력 배율과 별개이며 사용자가 명시한 모델·최종 배율은 기본값보다 우선한다. 타일·Overlap·목표 크기·Lossless 옵션은 현재 요구에서 제외하고 WebP 품질은 N-12로 이동한다. 내부 배율 조정·반올림은 미정이다.

Generation에서 캐릭터 일관성을 최대한 확보하는 것이 N-14의 현재 목표다. Anima 자연어 Prompt 활용과 IP-Adapter·Img2Img 등을 수단으로 검토하며 특정 기법의 일괄 지원이나 모델 간 공통 호환성은 확정하지 않는다. Inpaint·ControlNet과 N-15의 Crop·색감·Watermark는 [후속 로드맵](roadmap.md)으로 이관한다.

LoRA **사용**은 지원하며 LoRA **Training**은 현재 핵심 기능 범위에서 제외한다. Generation은 ComfyUI와만 생성 연동하며 AI Provider나 SQLite에 직접 접근하지 않는다.

## Validation 기능

응답 필드·초기 에러코드·HTTP 매핑은 [ADR-0005의 Proposed 설계](../architecture/adr/0005-validation-response-contract.md)에서 검토한다. 아래 확정 요구와 구분한다.

재생성 여부와 해당 이미지에 적용할 설정 변경값을 반환하는 책임은 [ADR-0003](../architecture/adr/0003-generation-execution-and-queue.md)에서 확정했다. [ADR-0004](../architecture/adr/0004-validation-outcomes-and-errors.md)는 다음 입력·판정·오류 경계를 확정한다.

- 이미지와 실제 생성 시도에 사용한 Prompt를 파라미터로 받아 Local VLM 또는 외부 AI Vision으로 검증한다. Prompt 없는 이미지의 Prompt 일치 검증은 현재 범위에 포함하지 않는다.
- Core는 자세·구도에 맞게 Prompt를 구성한다. 예를 들어 upper body에서는 하의·footwear를 포함하지 않으며 제외된 요소는 해당 일치 검사 대상이 아니다.
- 이미지에 있어야 한다고 Prompt에 명시한 요소가 보이지 않거나 상이하면 불합격이다. 가림·구도로 보이지 않는 경우에도 불합격이다.
- Provider 오류·응답 파싱 실패 등 실행 오류는 이미지 불합격과 구분해 에러코드로 반환하며 자동 이미지 재생성을 유발하지 않는다.
- CLI·Frontend에서 오류를 안내하고 사용자가 해당 이미지의 수동 재생성을 요청할 수 있다. Core가 작업·이력·새 시도를 조정하고 Client에 자동 복구 업무 규칙을 복제하지 않는다.
- [ADR-0006](../architecture/adr/0006-validation-manual-retry.md): 완료 응답 `outcome=error` 이후 자동 검증 재시도는 도입하지 않는다. 사용자는 기존 이미지·생성 Prompt로 다시 검증하거나 수동 재생성을 선택할 수 있다. Core가 요청·이력을 관리하며 다시 검증은 이미지 재생성 횟수에 포함하지 않는다.
- 전체 응답 Schema·에러코드와 Generation 오류별 복구, 응답을 받지 못한 통신 오류 처리는 미정이다.

[ADR-0007](../architecture/adr/0007-group-image-validation.md) 확정: 묶음 검증은 단일 검증 통과 이미지를 비교 대상으로 하고 그룹의 외형·의상 일관성을 검사하며 자세·구도·표정 차이는 허용한다. 문제 이미지만 기준 이미지와 선택 재검증하며 대상 판정만 갱신하고 이력은 보존한다. 중복 검사·중복 불합격·자동 제외/삭제는 초기 범위에서 제외한다. 기준은 시스템이 선정하고 사용자가 수정할 수 있다. 기준 교체 시 새 기준의 그룹 재검증이 필요함을 표시하고 사용자 확인 후 재검증한다. 결과를 보고 사용자가 재생성 대상을 선택·확인하며 새 결과는 단일 검증 후 그룹 일관성을 검사한다. 기준 변경 자체로 자동 실행하지 않는다.

Deterministic Validation의 검사 후보:

- 파일 손상, Decode 가능 여부.
- 해상도, Aspect Ratio, 이미지 포맷, Alpha Channel.
- Hash, Metadata 확인. 중복 이미지 검사는 ADR-0007에 따라 초기 범위에서 제외.

AI / VLM Validation의 검사 후보:

- Prompt와 실제 이미지 비교.
- 머리색, 눈 색, 외형, 의상, 액세서리.
- 표정, 동작, 손 / 얼굴 등의 이상.
- 동일 캐릭터 일관성 및 Character Identity.

AI Validation은 특정 모델에 종속시키지 않는다. Provider 지원 대상으로 Local VLM, OpenAI multimodal model, Gemini multimodal model, OpenAI-compatible local/remote endpoint 및 향후 추가 Provider를 고려한다. Backend 내부 Provider abstraction은 **Proposed**다.

VLM Provider 설정 후보는 Provider type, Endpoint, Model, Authentication, Timeout, Temperature, Max tokens, Max concurrency, Batch size, Input image resolution, Structured output 지원 여부, Multi-image 지원 여부, Retry 설정이다. 필수 여부, 기본값, Provider별 지원 및 적용 위치는 **TODO**다.

Generation과 Validation이 같은 GPU를 사용할 경우의 자원 경합 정책은 별도 ADR에서 결정한다. ADR-0004의 판정·오류 경계 외에 검사별 세부 기준, 정확도 보장 및 복구 정책은 아직 확정되지 않았다.

## Client 기능

Web Frontend는 UI / UX, Form, Tree Explorer, Gallery, Lightbox, 최종 생성 결과 표시(진행 중 이미지 Preview는 보류), Validation Result, Generation / Validation Job 상태, Prompt 편집, Model 관리 UI, 설정 UI, API 호출과 로컬 UI State를 담당한다.

AI Prompt Draft 비교 및 승인 UI는 요구 기능으로 기록하되, 구체적 승인 흐름은 Proposed인 Draft → Review → Apply 결정에 맞추어 확정한다. Model 관리 UI의 Backend 책임과 관리 범위도 TODO다.

CLI는 Arguments → Shared API Client → REST API의 얇은 Command Adapter다. Backend 비즈니스 로직을 중복 구현하지 않는다.

Codex 등의 개발 Agent, OpenClaw, Hermes 및 향후 MCP 기반 Agent가 SDK 또는 REST를 통해 작업할 수 있어야 한다. 구체적인 Agent별 연동 및 MCP 제공 방식은 아직 결정하지 않는다.

## 저장 및 이동성

- Runtime DB는 SQLite, 이미지 및 대형 모델 파일은 Filesystem에 저장한다.
- DB에 Image ID, Relative Path, Hash, Generation Metadata, Prompt Snapshot, Model Metadata, Validation Result, Job 정보 등의 Metadata를 저장한다. 상세 Schema는 미정이다.
- 파일명 또는 실제 경로를 Primary Key로 사용하지 않는다.
- JSON 등의 Import / Export는 Backup, Migration, Sharing, Character Export, Work Export, Prompt Preset Export, Settings Export를 위한 용도로 사용한다.
- JSON은 Runtime DB를 대체하지 않는다. 이미지 포함 ZIP + manifest는 검토 후보이며 Backup / Migration의 상세 정책은 미정이다.

## 배치 요구사항

모든 서비스를 한 PC에 배치하거나 여러 머신에 분산할 수 있어야 한다. Core / Generation / Validation Backend URL은 각각 설정 가능해야 하며 AI Provider Endpoint와 별도로 취급한다. 네트워크 인증, 파일 전송 및 GPU 공유 세부 정책은 TODO다.

## 묶음 기준 선정·비교 부족 — ADR-0008

[ADR-0008](../architecture/adr/0008-group-reference-selection.md)에서 단일 검증 통과 후보 중 특징이 잘 보이는 대표 1장과 필요한 보조 이미지의 시스템 선정·사용자 수정을 확정했다. 후보 없음은 대기, 그룹 1장은 묶음 검사 미실행, 일부 특징 비교 불가는 명시하고 전체 합격으로 표시하지 않는다. 대표·보조 충돌은 사용자 확인을 요청한다. 새 이미지는 기존 기준으로 개별 검사하며 기준 삭제는 새 선정·사용자 확인·기준 교체 절차를 따른다. 현재 확정 기준이며 향후 변경 날짜·사유·이전/새 기준·기존 판정 영향을 ADR에 기록한다. 점수·구체 알고리즘·묶음 응답 Schema는 미정이다.

## 묶음 결과·그룹 요약 — ADR-0009

[ADR-0009](../architecture/adr/0009-group-validation-results.md) 확정: 이미지별 일치/불일치/비교 불충분/실행 오류와 근거, 실제 대표·보조 및 당시 기준, 검증 범위·현재 유효성을 기록한다. 그룹은 전체 일치/불일치 있음/판정 미완료로 집계하며 불충분·오류·미검증 수를 함께 표시한다. 부분 재검증을 전체 완료처럼 표시하지 않고 정상 결과와 이력을 보존한다. 사용자 선택 재검증·불일치 대상 재생성 확인을 지원하며 확인 중 기준 변경은 변경 안내 후 재확인한다. 필드명·enum·HTTP·Schema·집계 대상 ID 및 동시성 상세는 미정이다.

## 그룹 완료·부분 실패 — ADR-0010

[ADR-0010](../architecture/adr/0010-group-completion-and-partial-failure.md) 확정: Core는 생성 요청의 대상 목록을 고정하고 모든 대상의 생성·단일 검증·허용 자동 재생성이 완료 또는 실패/취소/상한으로 종료되면 최종 단일 통과 이미지로 묶음 검증을 요청한다. 통과 2장 이상이면 일부 실패에도 진행하며 실패·오류·불합격 종료·취소의 제외 사유를 표시한다. 전체 취소는 후속 묶음 검증을 막고 개별 취소는 나머지 처리를 유지한다. 사용자 수동 요청을 기다리며 기존 처리를 무기한 대기시키지 않는다. 통과 0장은 묶음 대기, 1장은 미실행으로 표시한다. 나중에 추가된 결과는 기존 기준으로 검사한다. 생성 성공/실패 현황과 실제 비교 범위의 일관성 요약을 분리하며 완료 결과·이력을 보존한다. 구체 상태·접수·동시성은 미정이다.

## 검증 입력 정보 — ADR-0011

[ADR-0011](../architecture/adr/0011-validation-input-context.md) 확정: 공통 입력은 추적·검사 설정·이미지 식별/접근 정보, 단일 입력은 실제 Positive/Negative Prompt·생성/후처리 설정·기대 최종 출력 조건, 묶음 입력은 그룹·이번 대상 목록·대표/보조와 기준 식별·이미지별 Prompt·유지할 외형/의상 정보로 구분한다. 단일 검증은 후처리까지 끝난 최종 이미지를 최종 출력 조건과 비교한다. Core가 필요한 Context를 준비하며 Validation은 DB에서 추가 조합하지 않는다. Validation API의 내부 식별/추적 정보와 AI 입력을 구분하고 외부 AI에는 검사에 필요한 최소 Context만 전달한다. 필수/선택·정보 부족·전송 방식·Schema는 미정이다.

## 이미지 전달·입력 부족 — ADR-0012

[ADR-0012](../architecture/adr/0012-validation-image-transfer-and-required-input.md) 확정: 로컬/분산 모두 Generation 이미지 조회 API를 Validation이 사용하고 직접 요청은 미등록 이미지 업로드를 허용한다. 이미지 식별·무결성을 연결하고 접근 실패/파일 변경은 오류로 처리한다. 단일 입력은 이미지·실제 Positive Prompt·검사 설정 필수, Negative Prompt 미사용은 빈 값 명시. 묶음은 그룹·대상·대표/기준 식별·대상별 Prompt·공통 외형/의상 필수, 보조는 선택하되 비교에 필요하면 제공한다. 필수 누락은 AI 호출 전 오류, 재생성 설정만 부족하면 판정은 반환하되 자동 제안 없이 사유를 제공한다. 보이지 않는 비교 특징은 비교 불충분이며 오류와 구분한다. 파일 접근은 요청 범위로 제한하고 전송/인증 수치·Schema는 미정이다.

2026-09-13 [ADR-0012](../architecture/adr/0012-validation-image-transfer-and-required-input.md) 추가 확정: 초기 검증은 정지 이미지만 지원하며 애니메이션·동영상·다중 프레임은 제외한다. 여러 정지 이미지의 묶음 검증은 유지한다. 후속 합의로 정지 PNG·WebP만 지원하고 JPEG는 제외한다. 접근·업로드 제한·임시 보관 정책은 별도 확정한다.

## 접근·업로드·임시 파일 — ADR-0013

[ADR-0013](../architecture/adr/0013-validation-access-and-temporary-files.md)로 원칙을 확정했다. 로컬/분산 모두 서비스 인증을 사용해 설정된 Generation의 요청 이미지에만 접근한다. 대기/실행 중 접근을 유지하고 재검증에서 권한을 재확인한다. 용량·Decode 픽셀·요청당 개수를 각각 제한하고 초과 시 AI 호출 전 오류로 반환하며 임의 축소하지 않는다. Validation이 업로드 임시 파일을 관리하고 처리 중 보호·종료 후 일정 기간 보관·정리한다. 정리 후 재검증은 재업로드를 안내하고 이력과 Generation 원본은 보존한다. 인증 기술·한도·기간·동시성 세부는 미정이다.

## 검사·Profile — ADR-0014

[ADR-0014](../architecture/adr/0014-validation-checks-and-profiles.md) 확정: 단일/묶음 Profile 분리, 기본 제공·사용자 복제/수정, 초기 상속 없음. Core가 관리하고 검증 요청 시 설정을 고정한다. 입력 유효성은 항상 검사하고 출력 조건·Positive/구체 Negative·묶음 일관성은 기본 On, 신체 이상·Metadata는 기본 Off다. 신체 이상은 부위별 On/Off와 보이는 구조만 검사한다. 입력→출력→AI 순서이며 입력 오류/출력 불합격 시 AI를 생략한다. 불합격을 종합 반영하고 오류/미완료를 합격으로 표시하지 않으며 Confidence만으로 판정하지 않는다. 사용자 세부 검사 기준·기본값 제어는 확장 검토하고 필수 검사 비활성화는 허용하지 않는다. 구체 설정 UI/범위·판정 구현·Schema는 미정이다.

## Provider 설정·Fallback — ADR-0015

[ADR-0015](../architecture/adr/0015-validation-providers-and-fallback.md) 확정: Core가 복수 Local/외부 Provider 설정을 관리하고 Validation이 지원 기능 확인·실행·응답 정규화를 담당한다. 단일/묶음별 선택과 연결 확인을 제공하고 요청 시 설정을 고정한다. 미지원 입력/설정은 안내·오류로 처리하고 임의 축소·무시하지 않는다. 구조화 출력 미지원은 형식 요청 후 파싱/검사한다. 자동 Fallback·검증 재시도는 도입하지 않고 오류 후 사용자 Provider 변경 재검증을 지원한다. 실제 Provider/모델/검사 설정을 기록하고 외부에는 필요한 Context만 전달한다. 테스트 후 조정 사유·이전/새 기준·영향을 기록하며 구체 런타임·SDK·수치·Secret 계약은 미정이다.

## Validation 실행·GPU — ADR-0016

[ADR-0016](../architecture/adr/0016-validation-execution-and-gpu-sharing.md) 확정: 단일/묶음 비동기 Job, Provider별 Queue·초기 동시성 1, 실행 가능 요청의 접수 순서, REST 조회/SSE 변경 알림을 제공한다. Validation은 실행 Queue, Core는 전체 흐름과 공유 GPU 권한을 관리한다. 대기/실행 Timeout을 구분하고 오류 자동 재전송은 하지 않는다. 대기 취소·실행 취소 중 표시·복구 시 실제 상태 확인·동일 접수 키의 기존 Job 반환을 적용한다. 묶음은 하나의 Job으로 추적하면서 비교 기준/대상을 유지해 분할한다. 같은 GPU의 Generation/Local Validation 추론은 겹치지 않도록 조정하고 실행 전 메모리 확보를 확인한다. 외부 Provider와 독립 GPU는 병렬 가능하다. ComfyUI 직접 실행은 상태 확인 후 대기하되 확인 직후 경쟁을 완전히 통제한다고 보장하지 않는다. 구체 저장/상태/권한 원자성/메모리/Timeout은 후속 설계한다.

## 재생성 변경값 — ADR-0017

[ADR-0017](../architecture/adr/0017-regeneration-change-validation.md) 확정: 지원되는 생성/후처리 설정만 다음 시도에 변경하며 원본·Preset·경로·권한·상한은 변경하지 않는다. 불합격 근거별 최소 변경과 제작 의도 보존을 적용하고 검사 요소 삭제로 합격을 유도하지 않는다. 사용 가능한 모델과 호환 조합을 사용하며 자동 설치·범위 보정·제안 부분 적용은 하지 않는다. Validation은 분석/제안 형식, Core는 다음 입력/상한, Generation은 실제 환경의 최종 유효성 검사를 담당한다. 잘못된 제안은 오류·자동 생성 없음, 정보만 부족하면 가능한 판정과 제안 불가 이유를 제공한다. 자동 Off이면 사용자 선택을 기다리며 묶음 자동 재생성을 새로 허용하지 않는다. Schema·구체 검사/코드는 미정이다.

## Validation 원칙 정리와 상세 설계 위임

[ADR-0018](../architecture/adr/0018-group-validation-change-handling.md)로 기준 동점·보조 최소 선정·참조/대상 변경·과거 결과 보존·불확실성과 접근 오류 분리·사용자 재확인을 확정했다. [ADR-0019](../architecture/adr/0019-validation-contract-and-operational-draft.md)는 사용자 위임으로 작성한 API/상태/저장/인증·초기 운영값 초안이다. 일상적인 상세는 개별 승인 질문 없이 기존 요구 안에서 설계·테스트하며 제품 의도나 확정 경계 변경만 확인한다. 이 초안과 Backend 구현/테스트 완료를 혼동하지 않는다.

## 접수·취소·결과 경합 — ADR-0020

[ADR-0020](../architecture/adr/0020-job-request-and-result-races.md) 확정: 동일 키/내용은 기존 Job, 다른 내용은 충돌. 응답 유실은 키 조회, 명시 재검증은 새 Job으로 연결한다. 설정 고정·기준 변경 재확인을 유지한다. 완료/취소는 서버 반영 순서로 처리하며 취소 후 늦은 결과는 진단 이력만 보존한다. 과거 기준 결과는 현재 판정을 덮지 않고 Core는 Job별 중복 결과 등록을 방지한다. 임시 이미지 정리 시 결과/기준/설정/오류 이력은 유지한다. 구체 원자성·API·저장 기술은 미정이다.

## Frontend 구성 반영 — 2026-09-13

사용자 승인한 상단 구성은 제작 / 갤러리 / 작업 현황 / 설정이다. 제작에는 작품 > 캐릭터 > 의상 트리, 프롬프트 편집과 생성·후처리 설정을 배치한다. 갤러리에서 이미지·그룹 검토 및 기준 관리를, 작업 현황에서 실행·오류·이력을, 설정에서 전역·Preset·검사·연결 설정을 제공한다. 선택·필터 유지, 미저장 편집 이동 안내와 판정 상태 구분을 포함한다. [상세 구성](../development/frontend-structure.md)과 [제작 상세 초안](../development/frontend-production-screen.md)을 참조한다. 기존 F-01~F-15를 조직한 것이며 새로운 모델 다운로드·삭제 계약을 승인한 것은 아니다.
