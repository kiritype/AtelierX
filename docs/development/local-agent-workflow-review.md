# 로컬 Agent 기반 캐릭터 생성 흐름 검토 초안

상태: 설계 검토 초안. 작성일: 2026-09-13.

최신 사용자 지시: 로컬 Agent/skill 및 Qwen 27B 공용 모델 운용은 [후속 로드맵](../requirements/roadmap.md)에 기록하고 **Backend 3개 완료 후** 실제 구현 방식을 검토한다. 아래 권고 순서는 즉시 착수 지시가 아니다. 현재 Validation 모델 설정은 변경하지 않는다. 이 문서는 특정 LM Studio 모델,
Hermes/OpenClaw 또는 다른 외부 프로젝트의 기능·호환성·성능을 주장하거나, 제품
결정을 확정하는 ADR이 아니다. 해당 도구의 정확한 model ID와 tool-calling 지원은 별도
공식 문서 확인이 필요하다.

## 확인한 로컬 Planner 후보 메타데이터와 GPU 경계

주 에이전트의 읽기 전용 LM Studio `/api/v1/models` 확인에서
`qwen3.8-27b-uncensored`는 display name `Qwen3.8 27B Uncensored NoMTP`,
architecture `qwen35`, Q4_K_M 파일 크기 17,475,007,072 bytes로 보였다. metadata에는
`vision=true`, `trained_for_tool_use=true`, reasoning on/off가 표시됐다. 이는 실행 가능한
tool call 또는 이미지 작업 품질의 검증이 아니다. 확인 시 `loaded_instances=[]`였고 현재
검증용 8B VLM은 idle 상태다.

단일 RTX 4090에서 이 27B planner, Anima 생성, VLM 검증을 동시에 상주시킬 수 있다고
가정하면 안 된다. 현재 Core GPU broker는 Generation/Validation 및 선택된 VLM의 조정만
대상으로 하며, 외부 planner 모델의 상주·unload·재로드를 등록하거나 조정하지 않는다.
따라서 planner를 도입하면 planner가 REST Job 계획을 만든 뒤 유휴 unload → Generation →
Validation → 결과 확인 시 planner 재로드 같은 메모리 계획과 실패/대기 표시가 필요하다.
이 추가 조정은 Core의 GPU/실행 정책에 등록하고 thin bridge는 Core REST 요청만 전달해야 하며, 별도 BFF나 agent 내부의 중복
orchestrator를 만드는 근거가 되지 않는다.

## 현재 REST로 가능한 범위

로컬 LLM이 HTTP tool caller 역할을 할 수 있다면, 현재 API만으로 다음의 **Prompt가
같은 새 생성 시도**는 조정할 수 있다.

1. Core에 작품·캐릭터·의상을 만들고, 외형·복장 문구를 포함하는 의상과 그룹을 만든다.
   응답의 `group_id`를 계속 보관한다. 임의 파일명·로컬 경로는 식별자로 쓰지 않는다.
2. `POST /v1/prompts/preview`에 `group_id`, `framing`, generation preset 또는
   `generation_inputs`를 보낸다. 1024×1024은 현 입력 범위(256--1920, 16의 배수)에
   들어간다. Core가 외형·복장과 `expression`/`action`/`situation`을 최종 Prompt에
   조합하고 preview hash를 반환한다.
3. 검토한 preview hash와 같은 입력을 `POST /v1/tasks`에 멱등 키와 함께 보낸다.
   Task ID를 보관하고 `GET /v1/tasks/{id}`로 결과 Image ID와 상태를 조회한다.
4. 상반신 표정 변형은 **각각 새 Task**다. 같은 `group_id`, `framing="upper_body"`,
   고정 generation settings를 사용하고 `expression`만 `surprised`, `embarrassed`,
   `cute` 등으로 바꾼다. 그룹은 외형·복장 Prompt 구성을 고정하지만 이 자체가 이미지
   참조나 시각적 정체성 보존을 제공하지는 않는다.
5. 필요하면 단일/묶음 Validation을 결과 선택에 사용한다. 묶음 일관성 검증은 결과를
   비교·기록하는 기능이며 다음 생성의 conditioning 입력은 아니다.

`generation`/`postprocess` Preset은 revision을 지정해 preview/Task에 선택할 수 있고,
Core가 사용 설정과 출처 revision을 Task snapshot에 고정한다. Agent는 Core REST로만
그 작업을 수행해야 하며 SQLite, 임의 SQL, Generation의 파일 저장소를 직접 열면 안
된다. 현재 Bearer service token은 서비스 인증이며, Agent별 세분 권한·사용자 승인
경계는 아직 별도 정책이 필요하다.

## 요청한 두 흐름의 차이

### 1. 1024×1024 생성 뒤 1.5배 upscale

1024×1024 생성은 가능하다. 그러나 현 Generation의 전체/독립 postprocess stage는
Detailer, Censor, Alpha, Encode뿐이다. `AtelierXUpscale` node prototype이 있어도,
Generation REST의 upscale stage 또는 기존 image 입력 upscale Job은 현재 없다. 따라서
1024×1024 결과를 **정확히** 1.5배인 1536×1536으로 업스케일하는 제품 API sequence는
아직 실행 가능하지 않다. 1536×1536으로 처음부터 생성하는 요청은 다른 생성 시도이며
업스케일의 대체가 아니다.

선행 구현은 Generation의 등록 upscale model 선택과 input image ID를 받는 독립 upscale
Job, Core가 그 새 결과 Image ID·원본 관계를 저장하는 연결, 결과 크기/Alpha/실패의
검증이다. 모델 선택·내부 보간/반올림은 ADR-0002 N-13의 미정 사항으로 남아 있다.

### 2. 기존 캐릭터 기반 상반신 표정 변형

현재는 위의 새 Task 방식으로 같은 category/group와 Prompt를 재사용한 변형을 생성할 수
있다. `expression`은 Core가 조합하는 자연어 슬롯이므로 LLM은 문구 후보를 **draft**로
제시하거나, 허용된 Core REST 요청에서 문자열로 사용할 수 있다. 아직 Prompt AI의
Draft → Review → Apply API, 표정 라이브러리, 복수 선택 저장, Agent 승인 절차는 구현된
제품 계약이 아니다.

이는 image-to-image, reference image conditioning, IP-Adapter, ControlNet, face ID 또는
reference embedding 기반의 정체성 보존과 다르다. 현 Anima 요청은 reference image ID
또는 conditioning asset 입력을 받지 않으며, 독립 postprocess API도 이미지를 생성
conditioning으로 되돌려주지 않는다. 같은 Prompt/model/seed는 재현성에 관련될 수
있어도, 표현을 바꾸는 새 시도에서 동일한 시각적 캐릭터 정체성을 보장하지 않는다.
그 품질을 요구하면 reference asset의 소유·선택·접근, 모델별 conditioning 기법,
평가/재시도 기준을 먼저 제품 계약으로 정하고 구현·검증해야 한다.

## LLM, tool calling, playbook의 역할

| 구분 | 현재 할 수 있는 일 | 보장하지 않는 일 |
| --- | --- | --- |
| 로컬 LLM | 요청을 해석하고 외형/복장·표정 문구 초안을 작성 | REST 권한, 입력 검증, 이미지 정체성 보존 |
| Tool calling | allow-listed Core REST 요청을 순서대로 호출하고 ID를 이어감 | 작업 정책·사용자 의도 판단·실행 품질 |
| Skill / playbook | 위 sequence, 멱등 키, preview 확인, Task/Image ID 보관, 실패 시 중단 규칙을 반복 가능하게 문서화 | 새 모델 능력 또는 conditioning 기능 |
| Core / Generation | Prompt 조합·snapshot·실행·결과 ID와 파일 접근을 소유 | LLM의 자유로운 DB/file 접근 또는 Agent의 직접 Workflow 조립 |
| identity-preserving conditioning | 현재 없음 | 동일 인물 외형을 생성 변형마다 유지한다는 보장 |

따라서 별도의 “skill”은 현재 REST를 호출하는 데 필수는 아니다. 다만 local agent를
반복 운용한다면 **thin playbook/skill**로 Core REST 도구 목록, 입력 JSON schema, preview
확인, ID 보관, 재시도/취소 경계, 사용자 확인 필요 조건을 고정하는 편이 안전하다. 이는
LLM 자체의 tool-calling 기능이나 실제 이미지 conditioning을 대체하지 않는다.

## 권장 순서와 사용자 결정

1. 먼저 Core REST tool wrapper/playbook으로 category → group → preview → Task → Image
   조회를 구현한다. Agent의 쓰기 권한은 Core API로만 제한하고 raw DB/filesystem 권한을
   주지 않는다.
2. planner를 실제 사용하기 전에는 4090에서 planner/Anima/VLM 간 메모리 조정과 유휴
   unload·재로드의 등록/오류 경계를 설계한다. metadata의 tool-use 학습 표시는 이 단계를
   대체하지 않는다.
3. 1.5배 결과가 필요하면 독립 upscale Job과 Core 결과 연결을 구현·실제 모델로 검증한다.
4. 같은 인물의 시각 정체성이 요구되면 reference conditioning을 우선 설계·구현·평가한다.
   단순 Prompt/seed 반복을 그 기능의 완료로 표시하지 않는다.
5. 그 뒤에 Agent가 category/Preset을 자동 생성·수정할 수 있는지, draft만 만들고 사용자가
   apply할지, reference image 선택과 자동 재시도 범위를 사용자와 결정한다.

확인이 필요한 제품 결정은 (a) 정체성 보존의 기술과 참조 이미지 소유/선택 방식, (b) Agent
쓰기 권한 및 Draft/Review/Apply 사용자 확인 경계, (c) upscale 모델·최종 배율 처리다.


## 공식 자료 확인과 권장 연결

2026-09-13 확인:

- [LM Studio MCP Host](https://lmstudio.ai/docs/app/mcp): 앱에서 로컬/원격 MCP 서버를 연결해 모델에 도구 제공 가능.
- [LM Studio Tool Use](https://lmstudio.ai/docs/developer/openai-compat/tools): 모델의 tool 요청을 실행 측에서 처리하고 결과를 모델에 돌려주는 호출 루프. 모델이 직접 API를 실행하는 것은 아니다.
- [Hermes Skills](https://hermes-agent.nousresearch.com/docs/user-guide/features/skills), [OpenClaw Skills](https://docs.openclaw.ai/tools/skills): SKILL.md 기반 작업 지침을 지원. 호스트별 설치·도구 노출 방식은 별도 adapter/config로 맞춘다.

권고는 AtelierX Core REST를 감싸는 공통 MCP/도구 adapter와 create-character/character-variants 작업 지침이다. LM Studio에서 바로 말하려면 MCP tool description 및 호스트 지침으로 같은 절차를 제공한다. Hermes/OpenClaw의 skill 파일이 LM Studio에 자동으로 동일하게 로드된다고 가정하지 않는다. JSON Schema/도구 실행 코드·Core 검증·지속 Task ID가 필수이며 skill은 유용한 지침으로, 그 자체가 실행 기능이나 권한 통제는 아니다.

같은 캐릭터의 표정 변형은 참조 이미지 ID로 Core의 해당 group/task/prompt snapshot을 찾고 외형·복장 유지, upper_body의 하의 제외, 표정별 Task 생성으로 시작할 수 있다. 원본의 시각적 정체성을 유지하는 이미지 조건부 생성은 별도 Generation adapter/ComfyUI workflow 지원 및 품질 시험이 필요하다. 특정 IP-Adapter/Img2Img 기법을 현재 Anima와 호환된다고 확정하지 않는다.

현재 ComfyUI 읽기 전용 확인: `/object_info/AtelierXUpscale`에 등록 정보 없음, `/object_info/UpscaleModelLoader`의 model_name options 빈 배열. 따라서 1.5배는 1024→1536 목표 크기 자체는 명확하지만 모델 준비·노드 등록·Generation/Core 실행 연결을 먼저 완료해야 한다. 단순히 처음부터1536 생성하는 것은 요청한 원본 업스케일과 다르다.

구현 우선순위 권고: Upscale 실행 연결 → Core 표정 변형 묶음 요청 및 이미지 참조 Context → 공통 도구 adapter/제작 지침 → 27B 실제 tool calling·GPU 전환 시험. 이 검토에서는 27B 모델 로드, Hermes/OpenClaw 설치, skill 설치나 신규 제품 기능 구현을 수행하지 않았다.
