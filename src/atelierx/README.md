# atelierx 패키지 구성

서비스는 서로 Python import가 아니라 REST로 통신한다. 한 서비스만 쓰는 모듈은 서비스 패키지 안에, 둘 이상이 쓰는 모듈은 최상위에 둔다.

| 위치 | 역할 | 실행 |
| --- | --- | --- |
| `core/` | Core 서비스: SQLite 소유, 도메인·제작 계획·그룹·후처리 조정, GPU 조정, Frontend(`/ui/`) 제공 | `atelierx-core`, `python -m atelierx.core` |
| `generation/` | Generation 서비스: ComfyUI REST 실행, 후처리 graph(`pipeline.py`) | `atelierx-generation`, `python -m atelierx.generation` |
| `validation.py` | Validation 서비스: VLM Provider 호출과 판정 집계 | `atelierx-validation` |
| `discord_bridge.py` | Discord Worker 요청을 Core로 전달하는 Bridge | `python -m atelierx.discord_bridge` |
| `api_client.py`, `cli.py` | Shared API Client와 CLI | `python -m atelierx.cli` |

## 공유 모듈

| 모듈 | 사용처 |
| --- | --- |
| `common.py` | 전 서비스 공통 오류·잠금·HTTP 유틸 |
| `gpu.py`, `queue_api.py`, `runtime_info.py` | Core·Generation·Validation |
| `validation_evidence.py`, `validation_registry.py`, `regeneration_contract.py` | Core·Validation 간 판정·설정·재생성 계약 |
| `group_validation.py`, `provider_response.py` | Core·Validation의 묶음 판정 해석 |

현행 사양은 [모듈 문서](../../docs/modules/README.md), 경로·필드 계약은 [REST API](../../docs/api/rest-api.md)를 따른다.
