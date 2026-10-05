---
layout: home
hero:
  name: AtelierX
  text: 쓰고, 그리고, 대화로 다듬는 RP 챗봇 작업실
  tagline: 메인 프롬프트·로어북·시작 상황을 파일로 쓰고, LLM 에이전트와 다듬고, 대화 테스트로 확인하세요. 캐릭터 이미지 생성·검수·후처리와 LoRA 학습까지 이어집니다. 모든 데이터는 내 PC의 앱 폴더 안에 둡니다.
  image:
    src: /icon.svg
    alt: AtelierX 아이콘
  actions:
    - theme: brand
      text: 다운로드 (Windows)
      link: https://github.com/kiritype/AtelierX/releases/latest
    - theme: alt
      text: 처음 사용하기
      link: /tutorial/first-run
    - theme: alt
      text: 0.0.8에서 바뀐 점
      link: /changelog
features:
  - title: 파일로 쓰는 작품
    details: 메인 프롬프트, 시작 상황, 로어북, 캐릭터, JSX를 Markdown 파일로 나눠 씁니다. 용량 제한과 키워드를 검사하고 스냅숏으로 되돌립니다.
  - title: 에이전트 패널
    details: 모드 지침에 따라 LLM과 대화하며 원고를 다듬습니다. 에이전트는 파일 전체를 제안하고, 바뀐 부분만 골라 채택합니다.
  - title: 대화 테스트
    details: 시작 상황과 페르소나를 골라 실제 모델로 대화해 봅니다. 이번 턴에 어떤 로어북이 불려 왔는지 함께 보여 줍니다.
  - title: 캐릭터 이미지
    details: 외모·의상 설명을 이미지 프롬프트로 바꾸고, 표정·의상 조합을 ComfyUI로 생성해 갤러리에서 검수합니다.
  - title: 후처리와 LoRA
    details: 업스케일·디테일러·배경 제거 같은 후처리를 하고, 채택한 이미지로 데이터셋을 만들어 LoRA를 학습합니다.
  - title: 로컬 우선, 포터블
    details: 로컬 LLM을 기본으로 쓰고 외부 서비스는 작품마다 동의를 받습니다. API 키는 마스터 비밀번호로 암호화하고, 앱 폴더 하나로 옮길 수 있습니다.
---

## 이 설명서는

**AtelierX 0.0.8**을 기준으로 씁니다. 화면 캡처는 0.0.3에서 찍었습니다. 버전마다 바뀐 점은 [바뀐 점](changelog.md)에 모읍니다. 앱의 **도움말 → 사용 설명서(이 PC)** 로 같은 내용을 인터넷 없이 볼 수 있습니다.

![작품 창: 파일 트리, 편집기, 에이전트 패널](screenshots/agent-conversation.webp)

## 어디서부터 읽을까요

- **처음 설치했다면**: [처음 사용하기](tutorial/first-run.md)를 순서대로 따라가세요. 비밀번호 설정부터 작품 만들기, LLM·ComfyUI 연결, 에이전트로 원고 쓰기, 캐릭터 이미지 생성과 후처리, LLM으로 다듬기, 테스트와 내보내기까지 샘플 작품 하나로 이어 갑니다.
- **기능별로 찾는다면**: [사용 설명서](guide/getting-started.md)에서 화면별 설명을 보세요.
- **업데이트했다면**: [바뀐 점](changelog.md)과 [유지 관리](guide/maintenance.md)의 업데이트 절차를 보세요.

## 필요한 것

| 무엇 | 필요한 때 |
|---|---|
| Windows 10/11 x64, Microsoft Edge WebView2 Runtime | 항상 |
| LLM: 로컬 서버(LM Studio 등 OpenAI 호환) 또는 외부 API(Ollama Cloud 등) | 에이전트, LLM 도구, 대화 테스트, 이미지 프롬프트 변환 |
| ComfyUI와 GPU, 모델 파일 | 이미지 생성과 후처리 |
| LoRA 학습 도구(앱의 설치 화면에서 받음) | LoRA 학습 |

글을 쓰고 정리하는 데에는 LLM이나 ComfyUI가 없어도 됩니다. 외부 프로그램과 모델의 판·라이선스는 [외부 구성 요소](guide/external.md)에 있습니다.
