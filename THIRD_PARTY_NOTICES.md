# Third-party notices

The license labels below record terms published by the named projects; they are inventory information, not a legal review.
The Python and frontend dependencies included in a built package are collected with `tools/collect_licenses.py` from the
packaging Python environment and locked production frontend dependencies. Include its generated notice and copied license
texts with the package, and review any entries that report missing metadata or license text.

## Danbooru tag list

- File: `defaults/tags/danbooru.csv`
- Source: https://github.com/DraconicDragon/dbr-e621-lists-archive (Danbooru tag list, snapshot 2025-09-01)
- License: The Unlicense (public domain dedication)
- The list is generated from tag data published by Danbooru. Tag names and post counts belong to their respective sources.

## anima_lora method files and patch — MIT

`trainer/anima_lora/methods/*.toml` are adapted from anima_lora's method configs, and
`trainer/anima_lora/preprocess-model-paths.patch` modifies anima_lora's `scripts/tasks/preprocess.py` so
preprocessing reads the model files chosen in the settings.

- Project: https://github.com/sorryhyun/anima_lora
- Copyright (c) 2026 Seunghyun Ji
- License: MIT

```
Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

anima_lora itself contains code derived from [kohya-ss/sd-scripts](https://github.com/kohya-ss/sd-scripts) under
the Apache License 2.0; see anima_lora's own NOTICE when you install it.

## Used at run time, installed separately

ComfyUI, third-party custom nodes, the LoRA trainer and model files are installed separately from the Windows app ZIP.
The image tools talk to ComfyUI over HTTP. `tools/install_comfy_nodes.py` clones the nodes below from their own repositories,
at the tested commits listed in `comfy_nodes/nodes.json`, into the user's ComfyUI; each keeps its own license.

| Project | License | Used for |
|---|---|---|
| [ComfyUI](https://github.com/comfyanonymous/ComfyUI) | GPL-3.0 | Image generation and processing |
| [ComfyUI-WD14-Tagger](https://github.com/pythongosssss/ComfyUI-WD14-Tagger) | MIT | WD14 tagging |
| [ComfyUI_essentials](https://github.com/cubiq/ComfyUI_essentials) | MIT | Background removal (rembg) |
| [ComfyUI-Impact-Pack](https://github.com/ltdrdata/ComfyUI-Impact-Pack) | GPL-3.0 | Detailer pipeline |
| [ComfyUI-Impact-Subpack](https://github.com/ltdrdata/ComfyUI-Impact-Subpack) | AGPL-3.0 | Detectors; installs [ultralytics](https://github.com/ultralytics/ultralytics) (AGPL-3.0) |
| [ComfyUI-Anima-Ref-Adapter](https://github.com/ArcAnima/ComfyUI-Anima-Ref-Adapter) | Apache-2.0 | Optional Anima Reference Image BETA; by ElectronGirl and the ArcAnima project contributors |
| [anima_lora](https://github.com/sorryhyun/anima_lora), [anime_tools](https://github.com/sorryhyun/anime_tools) | MIT (with Apache-2.0 parts) | LoRA training; installed with `tools/install_trainer.py` into its own Python environment |

The app's own node pack (`comfy_nodes/atelierx_nodes`) is MIT like the rest of AtelierX. It runs inside
ComfyUI and calls the packs above there; it does not include their code.

The separate `AtelierX-<version>-anima-ref-adapter.zip` release asset provides the unmodified runtime
files and basic workflow from [the pinned ArcAnima commit](https://github.com/ArcAnima/ComfyUI-Anima-Ref-Adapter/tree/f02d54dd34593b4d4ce27b38de2a996049aeac58).
The archive includes the upstream Apache-2.0 license and a credits file. The node's
[`snapref.py`](https://github.com/ArcAnima/ComfyUI-Anima-Ref-Adapter/blob/f02d54dd34593b4d4ce27b38de2a996049aeac58/snapref.py)
adapts the [original SnapRef code](https://github.com/ArcAnima/SnapRef) under [Apache-2.0](https://github.com/ArcAnima/SnapRef/blob/main/LICENSE).

The [Anima Ref Adapter v2 weights](https://huggingface.co/ElectronGirl/anima-ref-adapter) and
[SnapRef v2a weights](https://huggingface.co/0ppxnhximxr/snapref-v2a/tree/e6d6a21e4d56faae4454a1cc9bfd065d87358bf2)
are separate optional downloads under the [CircleStone Labs Non-Commercial License v1.2](https://huggingface.co/0ppxnhximxr/snapref-v2a/blob/e6d6a21e4d56faae4454a1cc9bfd065d87358bf2/LICENSE.md).

Licenses above reflect the metadata published by each project at the time this file was prepared; check the project pages
for their current terms.

### SnapRef v2a 한국어 안내

AtelierX는 `ComfyUI-Anima-Ref-Adapter` 통합 노드로 SnapRef v2a를 실행합니다. 이 노드의 `snapref.py`는
[SnapRef 원본 코드](https://github.com/ArcAnima/SnapRef)를 바탕으로 작성됐으며 [Apache-2.0](https://github.com/ArcAnima/SnapRef/blob/main/LICENSE)이 적용됩니다.
[SnapRef v2a 가중치](https://huggingface.co/0ppxnhximxr/snapref-v2a/tree/e6d6a21e4d56faae4454a1cc9bfd065d87358bf2)는 별도로 내려받으며
비상업용 이용 조건인 [CircleStone Labs Non-Commercial License v1.2](https://huggingface.co/0ppxnhximxr/snapref-v2a/blob/e6d6a21e4d56faae4454a1cc9bfd065d87358bf2/LICENSE.md)가 적용됩니다.

## Models

AtelierX ships no model files. Each model (checkpoints, LoRAs, upscalers, detectors, taggers, vision LLMs)
has its own license on its download page; some, such as Anima, allow non-commercial use only, and LoRAs
trained from such weights are derivatives under that license.
