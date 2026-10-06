# AtelierX

[Windows용 다운로드](https://github.com/kiritype/AtelierX/releases/latest) · [웹 사용 설명서](https://atelierx.cftm.net/) · [오류 제보·제안·질문](https://github.com/kiritype/AtelierX/discussions)

한국어 | [English](README.en.md)

RP 챗봇을 만드는 Windows 데스크톱 도구입니다. 메인 프롬프트, 시작 상황, 로어북, 캐릭터, JSX 컴포넌트를 작품 단위로 관리하고,
LLM 에이전트로 쓰고 다듬은 뒤 대화 테스트로 확인합니다. 캐릭터 이미지 생성·검수·후처리와 LoRA 학습도 같은 프로그램에서 합니다.

![작품 편집 화면](docs/manual/screenshots/work-main.webp)

> **현재 상태: 1.0 이전 릴리스(0.x).** 앱 안에서 업데이트를 받을 수 있습니다. 1.0 전에는 기능과 데이터 형식이 바뀔 수 있고,
> 형식이 바뀌면 변환 도구를 함께 냅니다. 개발 PC에서 확인한 범위와 아직 확인하지 않은 범위는 설명서의
> [검증 범위와 출시 상태](https://atelierx.cftm.net/guide/release-status.html)에 있습니다.

## 주요 기능

**작품 작성**
- 작품은 직접 정리하는 Markdown·JSX 파일 폴더입니다. 파일 트리, 디스크 내용, 내보내기 결과가 같습니다.
- 파일마다 종류(메인·시작 상황·로어북·캐릭터·JSX·메모)와 ID를 두고, 로어북 키워드·우선순위는 편집기 상단 폼에서 정합니다.
- 플랫폼별 규칙(용량, 로어북 활성화, JSX 규칙)은 수정할 수 있는 플랫폼 프리셋으로 관리합니다.
- 규칙 검사, 관계도·용어집, 이름 일괄 변경, JSX 미리보기를 제공합니다.

**LLM**
- 오른쪽 **에이전트** 패널에서 모드(작성·압축·JSX 문구 등)를 골라 작업을 맡깁니다. 결과는 파일 전체 교체 제안으로 오고,
  검토 탭에서 덩어리 단위로 골라 적용합니다. 몰래 덮어쓰지 않습니다.
- 상단 **▶ 테스트**(`F5`)로 대화 테스트 화면을 엽니다. 시작 상황·페르소나·테스트 세트로 고치기 전후를 비교합니다.
- 로컬 OpenAI 호환 서버와 Ollama Cloud·Gemini API·Vertex AI·OpenRouter·DeepSeek 연결 프리셋을 제공합니다.

**캐릭터 이미지**
- 캐릭터 × 의상 × 표정 조합을 미리 보고 한꺼번에 생성합니다. 표정·구도·화풍·공통 프롬프트는 프롬프트 라이브러리에서 조합합니다.
- 생성 서비스: 이 PC의 ComfyUI, 또는 인터넷 서비스 NovelAI·PixAI(사용자 계정과 API 키 필요, 요금은 각 서비스 기준).
- 갤러리에서 검수(통과·실패·채택)하고, 완성도 보드로 빠진 조합을 찾습니다.
- 이미지 도구: 업스케일, 디테일러, 검열, 배경 제거, 인페인트, 태깅, WebP 변환, 프롬프트 형식 변환.
- 채택 이미지로 LoRA 데이터셋을 만들고 학습해 등록합니다.

**보관과 보안**
- 스냅숏 기록, 비교(diff), 복원, 배포 표시, 휴지통.
- 작품 꾸러미(ZIP)로 다른 PC로 옮기거나 전체를 백업합니다.
- 마스터 비밀번호로 앱을 잠그고, API 키 같은 인증 정보는 금고에 암호화해 저장합니다(작품 파일은 평문).
- 포터블: 프로그램·설정·데이터·출력을 앱 폴더 하나에 둡니다.

## 실행 환경

Windows x64, Microsoft Edge WebView2 Runtime, .NET Framework 4.8이 필요합니다. 받은 ZIP을 풀어 `AtelierX.exe`를 실행합니다.
자세한 내용은 [포터블 패키지 안내](packaging/PORTABLE_README.txt)를 보세요.

작성·편집과 클라우드 LLM은 추가 설치 없이 씁니다. 이미지 생성 서버(ComfyUI), 로컬 LLM 서버, LoRA 학습 도구는 선택 사항이며
AtelierX에 들어 있지 않습니다. 필요한 것만 따로 설치하거나 앱의 **설정 → 설치**에서 받습니다.

## 외부 구성 요소

이미지 기능은 아래를 따로 받아 씁니다. 앱은 설정 → 설치에서 원래 배포처로부터 정해진 판을 받을 뿐 함께 배포하지 않습니다.
판·라이선스·받는 곳 전체 목록은 설명서의 [외부 구성 요소](https://atelierx.cftm.net/guide/external.html)에 있습니다.

- 이미지 생성 서버: [ComfyUI](https://github.com/comfyanonymous/ComfyUI)
- 확장 노드: [WD14 Tagger](https://github.com/pythongosssss/ComfyUI-WD14-Tagger),
  [ComfyUI_essentials](https://github.com/cubiq/ComfyUI_essentials), [Impact Pack](https://github.com/ltdrdata/ComfyUI-Impact-Pack),
  [Impact Subpack](https://github.com/ltdrdata/ComfyUI-Impact-Subpack)
- 모델: [Anima](https://huggingface.co/circlestone-labs/Anima)(비상업 라이선스), [adetailer](https://huggingface.co/Bingsu/adetailer),
  [Segment Anything](https://github.com/facebookresearch/segment-anything), [2x-AnimeSharpV4](https://huggingface.co/Kim2091/2x-AnimeSharpV4)·[UltraSharp](https://huggingface.co/Kim2091/UltraSharp)(비상업)
- LoRA 학습: [anima_lora](https://github.com/sorryhyun/anima_lora), [anime_tools](https://github.com/sorryhyun/anime_tools)
- 보조 도구: [uv](https://github.com/astral-sh/uv), [Git for Windows](https://github.com/git-for-windows/git)(MinGit)

인터넷 이미지 서비스 [NovelAI](https://novelai.net/)·[PixAI](https://pixai.art/)는 설치하는 것이 아니라 사용자 계정으로 쓰는
유료 외부 서비스입니다. API 키는 사용자가 직접 등록하고, 이용 약관과 요금은 각 서비스를 따릅니다.

## 저장소 구성

| 폴더 | 내용 |
|---|---|
| [server/](server/) | Python 서버(Starlette): 작품, LLM, 이미지, 설치, 꾸러미 |
| [web/](web/) | 화면(React + TypeScript + Vite) |
| [tests/](tests/) | 서버 테스트(pytest). 화면 테스트는 `web/` 안에 있습니다(vitest) |
| [docs/](docs/README.md) | 설계 문서: 개요, 데이터 구조, 구조, 플랫폼 프리셋, 기능별 설계, 결정 기록 |
| [docs/manual/](docs/manual/index.md) | 사용 설명서 원본(웹·오프라인) |
| [defaults/](defaults/README.md) | 처음 실행할 때 복사하는 기본 지침과 이미지 라이브러리, 모델 다운로드 목록 |
| [samples/](samples/README.md) | 앱에 함께 들어가는 샘플 작품 세 개 |
| [comfy_nodes/](comfy_nodes/) | 앱이 ComfyUI에 설치하는 노드 묶음 |
| [trainer/](trainer/) | LoRA 학습 도구에 적용하는 패치 |
| [packaging/](packaging/), [tools/](tools/) | Windows 패키지 빌드와 개발 도구 |

## 제보와 문의

오류 제보, 기능 제안, 질문은 [Discussions](https://github.com/kiritype/AtelierX/discussions)에 남겨 주세요(앱의 **도움말** 메뉴에서도
열 수 있습니다). Issues는 확인된 작업 목록으로 씁니다. 보안 취약점은 [보안 정책](SECURITY.md)에 따라 비공개로 제보해 주세요.

## 기여

개발 환경, 검사, 코드 규칙, 브랜치와 릴리스, 설명서 빌드는 [기여 안내](CONTRIBUTING.md)에 있습니다.

## 라이선스

[MIT](LICENSE)
