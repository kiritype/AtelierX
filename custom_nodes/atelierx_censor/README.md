# AtelierX Censor

`AtelierX Censor` applies `mosaic` or `white` treatment where a supplied
`detection_mask` is `1`. It preserves pixels outside that mask and preserves
an existing IMAGE alpha channel. Mosaic averages each `block_size` square then
expands it with nearest-neighbour pixels; the value is a practical prototype
choice rather than an accepted product-policy default. `enabled=false` passes
the original IMAGE through unchanged.

This package does **not** claim to detect NSFW regions. Connect a compatible
upstream detector mask, or use a reviewed prepared mask image through
`LoadImageMask`; the example reads its red channel. No detector, model, or
runtime is bundled or downloaded. `AtelierX Detect NSFW Mask` is an optional
local NudeNet adapter: it accepts only an absolute existing ONNX `model_path`,
requires the separately installed `nudenet` runtime, and turns selected
NudeNet detection boxes into a mask. Its default sensitive classes are exposed
breast/genitalia/anus/buttocks labels and can be supplied explicitly as JSON.
It reports missing runtime/model errors and has not been quality-validated in
this environment.

```powershell
& 'C:\StabilityMatrix\Packages\ComfyUI\venv\Scripts\python.exe' -B -m unittest discover -s custom_nodes\atelierx_censor\tests -v
& 'C:\StabilityMatrix\Packages\ComfyUI\venv\Scripts\python.exe' custom_nodes\atelierx_censor\scripts\validate_examples.py
powershell -ExecutionPolicy Bypass -File .\custom_nodes\atelierx_censor\scripts\Install-AtelierXCensor.ps1 -ComfyRoot C:\StabilityMatrix\Packages\ComfyUI
```

After ComfyUI is restarted by the coordinating operator, load
[censor-mask.workflow.json](examples/censor-mask.workflow.json). The matching
REST body is [censor-mask.api.json](examples/censor-mask.api.json); replace
its `REPLACE_*` values before `POST /prompt`.
