# AtelierX

[Windows용 다운로드](https://github.com/kiritype/AtelierX/releases/latest) · [웹 사용 설명서](https://kiritype.github.io/AtelierX/)

한국어 | [English](README.en.md)

RP 챗봇 제작을 위한 데스크톱 도구다. 작품별 메인 프롬프트, 로어북, 캐릭터, JSX 컴포넌트를 관리하고
작성·압축·테스트 채팅을 지원한다. 별도로 설치한 서비스와 연결하는 이미지 프롬프트·이미지 작업 기능도 포함한다.

> **현재 상태: 스테이징 빌드.** Windows x64 포터블 패키지를 개발 PC에서 새 앱 데이터로 실행했고 네이티브 창의
> 열기와 닫기를 확인했다. Ollama Cloud 연결에서 모델 목록, 합성 응답과 스트리밍도 확인했다. 같은 PC에서의 검증이며,
> 깨끗한 별도 Windows 환경의 출시 적합성 검증은 아니다. Vertex AI, 이미지 생성, 모델·학습 도구 전체 흐름은 확인하지 않았다.

## 주요 기능

- 작품은 직접 정리하는 Markdown 및 JSX 파일로 구성된다. 파일 트리, 디스크 내용, 내보내기 내용이 일치한다.
- 플랫폼별 규칙은 수정 가능한 프리셋으로 관리한다.
- 작성·압축·이미지 프롬프트 결과를 검토한 뒤 적용한다.
- 로컬 OpenAI 호환 서버와 Ollama Cloud·Gemini API·Vertex AI·OpenRouter·DeepSeek 외부 연결 프리셋을 제공한다. 연결 점검은 제공자 응답과 스트리밍을
  확인한다. 인증 정보는 인증 정보 저장소에 암호화해 저장한다. Vertex AI 액세스 토큰은 만료되며 현재 자동 갱신되지 않아 직접 갱신해야 한다.
- 스냅샷, diff, 복원, 릴리스 표시, 휴지통을 제공한다.

Windows 포터블 ZIP에는 Windows x64, Microsoft Edge WebView2 Runtime, .NET Framework 4.8이 필요하다.
자세한 내용은 [포터블 패키지 안내](packaging/PORTABLE_README.txt)를 참고한다. ComfyUI, 이미지 모델, LoRA 학습 도구,
로컬 LLM 서버는 선택 사항인 외부 구성 요소이며 AtelierX에 포함되지 않는다. 별도로 설치하고 연결해야 한다.
Ollama Cloud 연결 점검은 모델 목록과 합성 응답·스트리밍을 확인했다. Vertex AI와 실제 이미지 생성은 아직 검증하지 않았다.

## 저장소 구성

| 폴더 | 내용 |
|---|---|
| [docs/](docs/README.md) | 설계 문서: 개요, 데이터 구조, 구조, 플랫폼 프리셋, 기능별 설계, 결정 기록 |
| [defaults/](defaults/README.md) | 앱이 처음 실행될 때 복사해 주는 기본 가이드라인과 이미지 라이브러리 |
| [samples/](samples/README.md) | 앱에 함께 들어가는 샘플 작품 세 개 |

## 라이선스

[MIT](LICENSE)

## 사용 설명서

[한국어 설명서 원본](docs/manual/index.md)은 설치부터 작품 편집·테스트·이미지·LoRA·내보내기까지 안내합니다.
GitHub Pages용 빌드는 `docs/manual`에서 `npm ci` 후 `npm run build`로 만듭니다.
오프라인판은 웹 앱 의존성 설치 후 `python tools/build_manual.py`로 만들고, `dist/manual/index.html`을 브라우저에서 엽니다.
빌드와 Pages 배포 설정은 [기여 안내](CONTRIBUTING.md)를 참고하세요.
