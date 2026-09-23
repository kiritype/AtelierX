# AtelierX Encode / Save

`AtelierXEncodeSave` is a ComfyUI output node. It accepts a batched RGB or RGBA
`IMAGE`, always writes PNG files, and can also write a WebP copy for every image.
The node is deliberately an output node: its standard `ui.images` records point
at the PNG files so ComfyUI history and the UI can display them. Its
`ui.atelierx_files` records every durable output, with `format: png` or
`format: webp`, so service consumers can discover optional WebP artifacts.

## Inputs and output

| Name | Type | Default | Meaning |
| --- | --- | --- | --- |
| `image` | `IMAGE` | required | Non-empty RGB or RGBA image batch. RGBA alpha is retained. |
| `filename_prefix` | `STRING` | `image` | Filename stem: ASCII letters, digits, `.`, `_`, `-`, up to 120 characters. Paths are rejected. |
| `webp_enabled` | `BOOLEAN` | `false` | Adds a WebP copy beside each PNG. |
| `webp_quality` | `INT` | `90` | WebP quality from 1 through 100. |
| `output_name` | `STRING` (선택) | `""` | 비어 있지 않으면 아래 "지정 출력 파일명" 규칙으로 저장한다. 비어 있으면 기존 동작과 같다. |

The output is the original `IMAGE`. A MASK is intentionally not accepted: native
RGBA alpha is authoritative at this final stage. Use the Alpha node or another
upstream operation to apply a ComfyUI MASK before saving.

## Files and failure behavior

Files are written only below `<ComfyUI output>/AtelierX`. Each batch item receives
a UUID-based stem and an atomic no-clobber publish, so this node does not overwrite an existing output. PNG and
WebP use the same stem. The PNG write is atomic. If optional WebP encoding fails,
the completed PNG remains for recovery, but the node raises an error and returns
no successful ComfyUI result descriptors.

## 지정 출력 파일명 (ADR-0026)

`output_name`은 ComfyUI 출력 폴더 기준 상대 이름이며 확장자를 붙이지 않는다(예: `AtelierX/작품/캐릭터/복장/12`).

- `/`로 구분한 1~6개 요소, 전체 240자 이하. 각 요소는 이미 정리된 형태여야 한다: `<>:"/\|?*`·제어 문자 없음, 앞뒤 공백·끝의 점 없음, 연속 공백 없음, Windows 예약 이름(CON, PRN, AUX, NUL, COM1~9, LPT1~9) 아님, 80자 이하. `.`/`..`·빈 요소·절대 경로는 거부한다. 한글 등 Unicode 문자는 허용한다. 규칙은 `src/atelierx/output_names.py`와 같으며(ComfyUI가 AtelierX 패키지를 import하지 않으므로 복제) 백엔드 테스트가 두 구현의 일치를 확인한다.
- `<output>/<output_name>.png`(WebP 사용 시 같은 이름의 `.webp`)로 저장하며 필요한 폴더를 만든다. 이때 `filename_prefix`는 쓰지 않는다.
- `<이름>.png` 또는 `<이름>.webp` 중 하나라도 있으면 `<이름> (2)`, `(3)`…에서 두 확장자가 모두 없는 첫 번호를 쓴다. PNG·WebP는 같은 번호를 쓰고 기존 파일은 덮어쓰지 않는다. 배치의 둘째 이미지부터는 같은 규칙으로 다음 번호를 받는다.
- 최종 경로를 resolve해 ComfyUI 출력 폴더 안인지 확인한다(링크를 통한 탈출 거부).
- `ui.images`/`ui.atelierx_files`의 `subfolder`는 출력 폴더 기준 `/` 구분 상대 폴더(예: `AtelierX/작품/캐릭터/복장`), `filename`은 실제 저장 이름(예: `12 (2).png`)이다. Generation은 이 값으로 `output_path`를 기록한다.
- 기존 Workflow·예제는 `output_name` 없이 그대로 동작한다(마지막 선택 입력으로 추가).

PNG is the history-preview artifact. The optional WebP is an additional delivery
file; its lossy RGB data is not required to be pixel-identical to PNG. Pillow
preserves an RGBA alpha channel in both formats.

Run `scripts/Install-AtelierXEncode.ps1 -ComfyRoot C:\StabilityMatrix\Packages\ComfyUI`
to create a guarded junction. It refuses to replace an existing non-junction or a
junction that points at another source. Import `examples/encode-save.workflow.json`,
choose a file in `LoadImage`, then queue it. The saved files appear under
`output/AtelierX`.
