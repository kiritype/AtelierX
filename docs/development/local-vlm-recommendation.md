# 로컬 VLM 첫 설치 권고

2026-09-13 검토. 사용자 요청에 따른 설치 후보이며 자동 설치나 실제 정확도 평가 결과가 아니다.

첫 기준 모델은 **Qwen3-VL-8B-Instruct, Q4_K_M**를 권고한다. 이미지 입력과 공간·시각 이해를 지원하며, Ollama의 해당 패키지는 약 6.1GB다. 모델 파일 크기는 실제 VRAM 사용량과 다르다. 4090 24GB에서 단일 이미지 검증의 초기 후보로 선택하되 ComfyUI와 동시 상주 가능 여부는 별도로 확인한다. 애니메이션 이미지의 작은 장식·손·의상 판정 정확도를 보장하지 않으며 예제 세트로 평가한다.

Ollama를 설치한 뒤 사용자가 실행할 명령:

```powershell
ollama pull qwen3-vl:8b-instruct-q4_K_M
```

준비한 Validation 설정은 API base URL `http://127.0.0.1:11434/v1`, 모델 `qwen3-vl:8b-instruct-q4_K_M`, 로컬 호환 키 `ollama`다. Instruct 변형을 명시하여 초기 JSON 판정 흐름을 시험한다. 이 설정으로 실제 로컬 VLM 호출은 아직 실행하지 않았다.

Qwen3.5-9B도 공식 멀티모달 모델이므로 이후 비교 후보로 둔다. 현재 작업의 첫 모델 선택은 최고 성능 주장보다는 설치·API 연동과 검증 결과 비교를 위한 기준선이다.

공식 자료:

- [Qwen3-VL-8B-Instruct 모델 카드](https://huggingface.co/Qwen/Qwen3-VL-8B-Instruct)
- [Ollama Q4_K_M 패키지·크기](https://ollama.com/library/qwen3-vl:8b-instruct-q4_K_M)
- [Ollama OpenAI 호환 API](https://docs.ollama.com/api/openai-compatibility)
- [Qwen3.5-9B 모델 카드](https://huggingface.co/Qwen/Qwen3.5-9B)

## LM Studio 실제 실행 후속 기록

사용자가 LM Studio를 선택했다. 로컬 모델 연결, json_schema 호환 수정 및 누락 요소 오판을 [실제 검증 기록](lmstudio-live-validation.md)에 남겼다. 이전 미연결 기록보다 이 실행 결과가 우선한다.
