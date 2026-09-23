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

## Consistency methods (ADR-0027 P3/P7)

The node has three optional inputs used only when a consistency method is
selected: `reference_full` (IMAGE), `reference_face` (IMAGE), and
`consistency` (STRING, default `""`). Leaving `consistency` empty — the
default for every existing Workflow, saved preset, and API prompt — makes the
node build exactly the same graph and produce the same result as before this
change; the three inputs are additive and backward compatible.

`consistency` is a JSON object `{"method":"...", "params":{...}}`. The only
method today is `anima-incontext-character`, which applies the verified
[comfyui-anima-incontext](https://github.com) recipe: it requires both
`reference_full` and `reference_face`, applies the fixed model-only LoRA
`anima-incontext-character.safetensors` at strength 1.0, encodes both
references with the node's own VAE at the generation resolution (white-padded
to the aspect ratio), batches them, and attaches them to the model before
sampling. `params.strength` (default `1.0`, range `0.5`–`1.5`) and
`params.end_percent` (default `0.5`, range `0.3`–`1.0`) are the only exposed
knobs; `start_percent` (`0`), `cond_only` (`true`), `fit_mode` (`pad`), and
`ref_timestep` (`0`) are fixed, matching the ADR-0027 decision.

The three ComfyUI node classes the method needs
(`AnimaRefEncode`, `AnimaRefLatentBatch`, `AnimaInContextApply`) are resolved
at runtime from ComfyUI's own node registry — this package never imports the
third-party `comfyui-anima-incontext` package by path. A missing install (or
a missing `anima-incontext-character.safetensors` LoRA) raises a `ValueError`
naming the exact missing node or file instead of failing in an unrelated way.

An example using two `LoadImage` references is
[examples/anima-incontext-character.workflow.json](examples/anima-incontext-character.workflow.json)
(equivalent API prompt:
[examples/anima-incontext-character.api.json](examples/anima-incontext-character.api.json)).
Unlike the two example pairs above, this one is not yet covered by
`scripts/validate_examples.py`'s strict widget-order static check; treat it as
a manually reviewed reference pending that follow-up.

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
