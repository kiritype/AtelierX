AtelierX 0.0.1 — Windows x64 테스트 패키지

1. ZIP 전체를 쓰기 가능한 폴더에 압축 해제합니다.
2. AtelierX.exe를 실행합니다. Python, Node.js, Git은 앱 실행에 필요하지 않습니다.
3. 처음 실행할 때 이 앱 전용 비밀번호를 정합니다.

필수 환경: Windows 10/11 x64, Microsoft Edge WebView2 Runtime, .NET Framework 4.8.
WebView2가 없다면 Microsoft 공식 배포 페이지에서 Evergreen Runtime을 설치하세요.
https://developer.microsoft.com/microsoft-edge/webview2/

AtelierX.exe와 _internal 폴더를 함께 보관하세요. exe만 옮기면 실행되지 않습니다.
설정·작품·출력은 실행 파일 옆의 config, state, data, output에 저장됩니다.
앱은 설치하지 않고 실행하는 포터블 형식이며 관리자 권한이 필요하지 않습니다.
업데이트하거나 이동할 때 기존 config, state, data, output은 보존하세요.
Program Files처럼 쓰기 제한이 있는 폴더에서는 실행하지 마세요.

ComfyUI, 이미지 모델, LoRA 학습 도구, LLM 서버는 포함하지 않습니다.
설정 → 설치에서 필요한 도구를 준비하고 설정 → 이미지/LLM에서 연결합니다.
기존 개발 환경의 경로·비밀번호·API 키·이미지는 패키지에 포함하지 않습니다.

사용 설명서: manual/index.html을 브라우저에서 열면 오프라인으로 읽을 수 있습니다.
라이선스: LICENSE, THIRD_PARTY_NOTICES.md와 licenses/를 함께 보관하세요.
실행 문제: state/logs/desktop.log를 확인하세요.
이 패키지는 스테이징 검증용이며 코드 서명은 하지 않았습니다.
