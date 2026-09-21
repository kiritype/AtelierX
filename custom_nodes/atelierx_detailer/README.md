# AtelierX Detailer

`AtelierX Detailer` performs actual masked diffusion detail work using the
installed ComfyUI `CLIPTextEncode`, `VAEEncodeForInpaint`, `KSampler`, and
`VAEDecode` implementations. It accepts upstream `MODEL`, `CLIP`, and `VAE`
objects plus an IMAGE and a same-sized `region_mask`. A mask value of `1` marks
the region to regenerate; the node composites its decoded result into that
region and preserves pixels outside it. `target` records whether the supplied
mask is for `eyes`, `mouth`, `hands`, or `face`; all four are supported.

The manual-mask node is supplemental. `AtelierX Detailer Pipeline (Impact)` is
the orchestration wrapper for the reference Impact Pack and Impact Subpack
`FaceDetailerPipe`/SAML/Ultralytics pipeline, chained Face → Eye → Mouth → Hand.
Each pass has an enabled flag and its own detector model. Its defaults are `bbox/face_yolov8m.pt` for Face
and Mouth, `segm/PitEyeDetailer-v2-seg.pt` for Eye, and
`bbox/hand_yolov8s.pt` for Hand. Those packs and models are absent here, so
their orchestration cannot execute and reports the exact missing class. It does
not bundle or download models. Import `examples/detailer-pipeline.api.json` for
the four-stage API template; `detail-region.workflow.json` remains the supplied
MASK-only supplemental workflow.

Run isolated tests and validate the example templates:

```powershell
& 'C:\StabilityMatrix\Packages\ComfyUI\venv\Scripts\python.exe' -B -m unittest discover -s custom_nodes\atelierx_detailer\tests -v
& 'C:\StabilityMatrix\Packages\ComfyUI\venv\Scripts\python.exe' custom_nodes\atelierx_detailer\scripts\validate_examples.py
```

Create a non-overwriting junction into ComfyUI:

```powershell
powershell -ExecutionPolicy Bypass -File .\custom_nodes\atelierx_detailer\scripts\Install-AtelierXDetailer.ps1 -ComfyRoot C:\StabilityMatrix\Packages\ComfyUI
```

After ComfyUI is restarted by the coordinating operator, load
[detail-region.workflow.json](examples/detail-region.workflow.json). Choose an
inpaint-compatible checkpoint, an input image, and a matching mask image.
The corresponding REST body is [detail-region.api.json](examples/detail-region.api.json);
replace every `REPLACE_*` value before `POST /prompt`.
