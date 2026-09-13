# AtelierX Upscale

`AtelierX Upscale` accepts an RGB `IMAGE`, an upscale model registered by ComfyUI,
and a final scale relative to the input image. It returns `IMAGE` only. The
model's native scale is internal: for example, a 4x model with scale `1.5`
returns an image 1.5 times the input width and height.

The node's initial scale is `1.5`. AtelierX's Generation default selects
`4x-UltraSharp.safetensors` only when that model is registered by ComfyUI;
missing or differently named models are reported by Generation as unavailable,
never replaced with another model.

The package delegates model loading and tiled inference to ComfyUI 0.35.0's
`UpscaleModelLoader` and `ImageUpscaleWithModel`. The first implementation
then uses ComfyUI's Lanczos resize to reach the requested final dimensions.
Fractional dimensions use half-up rounding (for example, `101 * 1.5 = 152`).
Those internal resampling and rounding choices implement the first prototype;
they do not settle ADR-0002 N-13's remaining product policy.

Only names registered as `upscale_models` can be selected. In the current
Stability Matrix installation this maps to `Models/ESRGAN`, `Models/RealESRGAN`,
and `Models/SwinIR`. No model is bundled or downloaded by this package.

Run its isolated tests with the existing ComfyUI Python environment:

```powershell
& 'C:\StabilityMatrix\Packages\ComfyUI\venv\Scripts\python.exe' -B -m unittest discover -s custom_nodes\atelierx_upscale\tests -v
```

Create the safe junction into the installed ComfyUI:

```powershell
powershell -ExecutionPolicy Bypass -File .\custom_nodes\atelierx_upscale\scripts\Install-AtelierXUpscale.ps1 -ComfyRoot C:\StabilityMatrix\Packages\ComfyUI
```

After restarting ComfyUI, open
[examples/upscale-preview.workflow.json](examples/upscale-preview.workflow.json),
choose an installed input image and registered upscale model, then run it to
inspect the output in `PreviewImage`. The matching API body is
[examples/upscale-preview.api.json](examples/upscale-preview.api.json); replace
both explicit `REPLACE_*` values before sending it to `POST /prompt`.
