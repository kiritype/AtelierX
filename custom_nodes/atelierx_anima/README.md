# AtelierX Anima Generate

`AtelierX Anima Generate` is an initial ComfyUI 0.35.0 Custom Node that runs
one text-to-image Anima generation and returns an `IMAGE` value. It is limited
to files registered by ComfyUI as `diffusion_models`, `text_encoders`, and
`vae`; it does not use machine-specific paths.

The installed WAI Anima example uses an Anima diffusion model, its matching
`qwen3_06b` text encoder, and `qwen_image_vae`. The node checks the loaded
diffusion model is ComfyUI's `Anima` model and checks that the VAE exposes the
required 16 latent channels. Its provisional smoke defaults are 512 × 512,
24 steps, CFG 4.5, `euler_ancestral`, and `normal`, based on the local WAI
model card's 20–30 step / CFG 4–5 example. They are not a global model-default
policy.

The node has an ordered LoRA list with **+ Add LoRA** and **−** controls. Each
entry selects a LoRA registered by ComfyUI and sets its model strength; entries
apply from top to bottom. An empty list retains base-model behavior. The
installed Anima LoRAs have diffusion-model adapter keys only, so this node
exposes model strength and does not imply that their Qwen text encoder supports
a separate LoRA strength. A selected LoRA must be a registered readable file
and must apply at least one patch to the selected Anima model.

This slice intentionally excludes save/encode, presets, postprocessing, REST
APIs, databases, and SDXL. The node creates Anima's one-frame 16-channel Wan21
latent internally, conditions both positive and negative prompts, samples
through ComfyUI's `common_ksampler`, and decodes with the chosen VAE.

Run the unit tests with the installed ComfyUI Python environment:

```powershell
C:\StabilityMatrix\Packages\ComfyUI\venv\Scripts\python.exe -B -m unittest discover -s custom_nodes\atelierx_anima\tests -v
node custom_nodes\atelierx_anima\tests\test_frontend_widget.js
```

Install a junction from ComfyUI's `custom_nodes` directory to this package:

```powershell
powershell -ExecutionPolicy Bypass -File .\custom_nodes\atelierx_anima\scripts\Install-AtelierXAnima.ps1 -ComfyRoot C:\StabilityMatrix\Packages\ComfyUI
```

The helper creates only `custom_nodes\atelierx_anima`. When that target is an
existing junction to this package it reports success without changing it. It
refuses any normal directory, file, or junction that targets elsewhere; it does
not delete or replace existing Custom Nodes. Restart ComfyUI after installation.

Open [examples/anima-preview.workflow.json](examples/anima-preview.workflow.json)
in ComfyUI to run the verified WAI Anima example and inspect the result with
`PreviewImage`. Send [examples/anima-preview.api.json](examples/anima-preview.api.json)
as the JSON body to ComfyUI's `POST /prompt` endpoint for the equivalent API
request. ComfyUI adds its seed-control widget after the seed value in workflow
files; this example selects `fixed`, so rerunning preserves seed `123456789`.
For a two-LoRA example using the locally installed Anima adapters, open
[examples/anima-lora-preview.workflow.json](examples/anima-lora-preview.workflow.json)
or send [examples/anima-lora-preview.api.json](examples/anima-lora-preview.api.json)
to `POST /prompt`. Its first and second list entries use `0.35` and `0.5`
model strength, respectively; those are example values, not a model-default
policy. The API uses the same ordered `lora_stack` JSON string that the visual
control serializes; users of the ComfyUI node do not need to edit JSON.

Validate both JSON artifacts and, optionally, their installed ComfyUI registry
and local model choices without running the GPU:

```powershell
C:\StabilityMatrix\Packages\ComfyUI\venv\Scripts\python.exe -B .\custom_nodes\atelierx_anima\scripts\validate_examples.py --comfy-root C:\StabilityMatrix\Packages\ComfyUI
```

The GPU smoke runner is [scripts/smoke_anima.py](scripts/smoke_anima.py). It is
deliberately opt-in and loads the configured ComfyUI model paths before invoking
ComfyUI's custom-node registry. It writes only under `artifacts/anima-smoke/`.

The runner was verified on 2026-09-12 against ComfyUI 0.35.0 with the local WAI
Anima diffusion model, matching Qwen3 0.6B text encoder, and Qwen Image VAE. A
768 × 1024 generation at 24 steps, CFG 4.5, `euler_ancestral` / `normal`, and
seed `123456789` completed with a finite `IMAGE` tensor of the expected shape;
the saved result is `artifacts/anima-smoke/anima-20260912T144010Z.png` with its
input record beside it. The runner loaded this repository package directly for
verification. It does not mean the node has been copied into, or installed in,
the existing ComfyUI Custom Nodes directory.

On 2026-09-13, the package was also linked into the installed ComfyUI through
the junction above. The example was opened and executed from the ComfyUI UI;
the full generation-to-PreviewImage workflow succeeded. The installed example
is under `user/default/workflows/AtelierX/Anima - Generate and Preview.json`.
See the [installation and execution record](../../docs/modules/custom-nodes-design.md)
for the verified settings and local output location.
