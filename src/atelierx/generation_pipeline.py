"""Fixed, inspectable ComfyUI post-processing graphs.

This module intentionally has no generic graph or file-path input.  The
Generation service may only append the registered nodes below to an Anima
image.  That makes the graph persisted with a job a useful recovery snapshot.
"""
from __future__ import annotations

import math

from .common import ApiError

NODES = {
    "upscale": ("AtelierXUpscale",),
    "censor": ("AtelierXDetectNsfwMask", "AtelierXCensor"),
    "alpha": ("AtelierXDetectCharacterMask", "AtelierXApplyCharacterAlpha"),
    "encode": ("AtelierXEncodeSave",),
    "detailer": ("AtelierXImpactDetailerPipeline", "UNETLoader", "CLIPLoader", "VAELoader", "CLIPTextEncode",
                 "UltralyticsDetectorProvider", "SAMLoader", "ToDetailerPipe", "FaceDetailerPipe"),
}


def _object_schema(info, node):
    value = info.get(node)
    if not isinstance(value, dict):
        raise ApiError("GEN_NODE_UNAVAILABLE", f"Required ComfyUI node is not registered: {node}", 503)
    return value


def _options(schema, field):
    item = schema.get("input", {}).get("required", {}).get(field, [None, {}])
    if not isinstance(item, list) or not item:
        return []
    if isinstance(item[0], list):
        return item[0]
    return item[1].get("options", []) if len(item) > 1 and isinstance(item[1], dict) else []


def _finite(value, name, low, high, integer=False):
    valid = type(value) is int if integer else type(value) in (int, float)
    if not valid or not math.isfinite(value) or value < low or value > high:
        raise ApiError("GEN_INVALID_POSTPROCESS", f"{name} must be within {low}..{high}")


def _positive_finite(value, name):
    if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
        raise ApiError("GEN_INVALID_POSTPROCESS", f"{name} must be a finite number greater than zero")


def upscale_dimensions(width, height, scale):
    """Return final dimensions using the custom node's half-up scale contract."""
    _finite(width, "width", 1, 2**31 - 1, True)
    _finite(height, "height", 1, 2**31 - 1, True)
    _positive_finite(scale, "upscale.scale")
    from decimal import Decimal, ROUND_HALF_UP
    return tuple(max(1, int((Decimal(value) * Decimal(str(scale))).quantize(Decimal("1"), rounding=ROUND_HALF_UP)))
                 for value in (width, height))


def validate_pipeline(value, info, has_loras=False):
    """Return a canonical, allow-listed stage configuration."""
    if value is None:
        return {}
    if not isinstance(value, dict) or set(value) - set(NODES):
        raise ApiError("GEN_INVALID_POSTPROCESS", "postprocess has unknown stages")
    result = {}
    for name, settings in value.items():
        if not isinstance(settings, dict):
            raise ApiError("GEN_INVALID_POSTPROCESS", f"{name} must be an object")
        if name == "upscale":
            if set(settings) - {"upscale_model", "scale"}:
                raise ApiError("GEN_INVALID_POSTPROCESS", "upscale has unknown settings")
            schema = _object_schema(info, NODES[name][0])
            model = settings.get("upscale_model")
            if not isinstance(model, str) or not model.strip():
                raise ApiError("GEN_INVALID_POSTPROCESS", "upscale.upscale_model must be non-empty text")
            models = _options(schema, "upscale_model")
            if not models or model not in models:
                raise ApiError("GEN_UPSCALE_MODEL_UNAVAILABLE", f"Upscale model is not registered: {model}", 503)
            scale = settings.get("scale", 1.5)
            _positive_finite(scale, "upscale.scale")
            result[name] = {"upscale_model": model, "scale": scale}
        elif name == "detailer":
            allowed = {"face_enabled", "eye_enabled", "mouth_enabled", "hand_enabled", "face_detector_model", "eye_detector_model", "mouth_detector_model", "hand_detector_model", "sam_model", "seed", "steps", "cfg", "sampler_name", "scheduler", "denoise"}
            if set(settings) - allowed: raise ApiError("GEN_INVALID_POSTPROCESS", "detailer has unknown settings")
            for node in NODES[name]: _object_schema(info, node)
            if has_loras:
                _object_schema(info, "LoraLoaderModelOnly")
            defaults = {"face_enabled": True, "eye_enabled": True, "mouth_enabled": True, "hand_enabled": True,
                "face_detector_model": "bbox/face_yolov8m.pt", "eye_detector_model": "segm/PitEyeDetailer-v2-seg.pt", "mouth_detector_model": "bbox/face_yolov8m.pt", "hand_detector_model": "bbox/hand_yolov8s.pt", "sam_model": "sam_vit_b_01ec64.pth", "seed": 0, "steps": 10, "cfg": 5.0, "sampler_name": "euler_ancestral", "scheduler": "normal", "denoise": .5}
            cfg = {**defaults, **settings}
            if any(type(cfg[x]) is not bool for x in ("face_enabled", "eye_enabled", "mouth_enabled", "hand_enabled")): raise ApiError("GEN_INVALID_POSTPROCESS", "detailer enabled values must be boolean")
            if any(not isinstance(cfg[x], str) or not cfg[x] for x in ("face_detector_model", "eye_detector_model", "mouth_detector_model", "hand_detector_model", "sam_model")): raise ApiError("GEN_INVALID_POSTPROCESS", "detailer model settings must be text")
            detail_schema = info[NODES[name][0]]
            for field in ("sampler_name", "scheduler"):
                if cfg[field] not in _options(detail_schema, field):
                    raise ApiError("GEN_INVALID_POSTPROCESS", f"detailer.{field} is not registered")
            for region in ("face", "eye", "mouth", "hand"):
                if cfg[region + "_enabled"] and cfg[region + "_detector_model"] not in _options(info["UltralyticsDetectorProvider"], "model_name"):
                    raise ApiError("GEN_INVALID_POSTPROCESS", f"detailer.{region}_detector_model is not registered")
            if any(cfg[region + "_enabled"] for region in ("face", "eye", "mouth", "hand")) and cfg["sam_model"] not in _options(info["SAMLoader"], "model_name"):
                raise ApiError("GEN_INVALID_POSTPROCESS", "detailer.sam_model is not registered")
            _finite(cfg["seed"], "detailer.seed", 0, 2**64-1, True); _finite(cfg["steps"], "detailer.steps", 1, 100, True); _finite(cfg["cfg"], "detailer.cfg", 0, 20); _finite(cfg["denoise"], "detailer.denoise", 0, 1)
            result[name] = cfg
        elif name == "encode":
            if set(settings) - {"webp_enabled", "webp_quality"}:
                raise ApiError("GEN_INVALID_POSTPROCESS", "encode has unknown settings")
            enabled = settings.get("webp_enabled", False)
            quality = settings.get("webp_quality", 90)
            if type(enabled) is not bool:
                raise ApiError("GEN_INVALID_POSTPROCESS", "encode.webp_enabled must be boolean")
            _finite(quality, "encode.webp_quality", 1, 100, True)
            _object_schema(info, NODES[name][0])
            result[name] = {"webp_enabled": enabled, "webp_quality": quality}
        elif name == "alpha":
            if set(settings) - {"segmentation_model", "confidence"}:
                raise ApiError("GEN_INVALID_POSTPROCESS", "alpha has unknown settings")
            detector = _object_schema(info, NODES[name][0])
            _object_schema(info, NODES[name][1])
            model = settings.get("segmentation_model")
            if not isinstance(model, str) or model not in _options(detector, "segmentation_model"):
                raise ApiError("GEN_INVALID_POSTPROCESS", "alpha.segmentation_model is not registered")
            confidence = settings.get("confidence", .35)
            _finite(confidence, "alpha.confidence", 0, 1)
            result[name] = {"segmentation_model": model, "confidence": confidence}
        else:
            if set(settings) - {"segmentation_model", "labels", "confidence", "treatment", "intensity"}:
                raise ApiError("GEN_INVALID_POSTPROCESS", "censor has unknown settings")
            detector = _object_schema(info, NODES[name][0])
            censor = _object_schema(info, NODES[name][1])
            model = settings.get("segmentation_model")
            labels = settings.get("labels")
            treatment = settings.get("treatment", "mosaic")
            confidence, intensity = settings.get("confidence", .35), settings.get("intensity", 15)
            if not isinstance(model, str) or model not in _options(detector, "segmentation_model"):
                raise ApiError("GEN_INVALID_POSTPROCESS", "censor.segmentation_model is not registered")
            if not isinstance(labels, str) or not labels.strip():
                raise ApiError("GEN_INVALID_POSTPROCESS", "censor.labels must be non-empty text")
            if treatment not in _options(censor, "treatment"):
                raise ApiError("GEN_INVALID_POSTPROCESS", "censor.treatment is not registered")
            _finite(confidence, "censor.confidence", 0, 1)
            _finite(intensity, "censor.intensity", 1, 128, True)
            result[name] = {"segmentation_model": model, "labels": labels, "confidence": confidence,
                            "treatment": treatment, "intensity": intensity}
    return result


def build_anima_prompt(anima_inputs, pipeline, job_id):
    """Build the fixed Anima -> Upscale -> Detailer -> Censor -> Alpha -> Encode chain."""
    prompt = {"1": {"class_type": "AtelierXAnimaGenerate", "inputs": anima_inputs}}
    image = ["1", 0]
    next_id = 2
    if "upscale" in pipeline:
        cfg = pipeline["upscale"]
        node = str(next_id)
        prompt[node] = {"class_type": "AtelierXUpscale", "inputs": {"image": image, **cfg}}
        image, next_id = [node, 0], next_id + 1
    if "detailer" in pipeline:
        cfg = pipeline["detailer"]
        # Re-load exactly the named Anima assets and rebuild conditioning.  The
        # model-only LoRA chain mirrors the Anima node's ordered stack.
        unet, clip, vae = str(next_id), str(next_id + 1), str(next_id + 2)
        prompt[unet] = {"class_type": "UNETLoader", "inputs": {"unet_name": anima_inputs["diffusion_model"], "weight_dtype": "default"}}
        prompt[clip] = {"class_type": "CLIPLoader", "inputs": {"clip_name": anima_inputs["text_encoder"], "type": "stable_diffusion", "device": "default"}}
        prompt[vae] = {"class_type": "VAELoader", "inputs": {"vae_name": anima_inputs["vae"]}}
        model = [unet, 0]; next_id += 3
        import json
        loras = json.loads(anima_inputs.get("lora_stack", "[]"))
        for item in loras:
            loader = str(next_id); prompt[loader] = {"class_type": "LoraLoaderModelOnly", "inputs": {"model": model, "lora_name": item["name"], "strength_model": item["strength"]}}; model = [loader, 0]; next_id += 1
        positive, negative = str(next_id), str(next_id + 1)
        prompt[positive] = {"class_type": "CLIPTextEncode", "inputs": {"text": anima_inputs["positive_prompt"], "clip": [clip, 0]}}
        prompt[negative] = {"class_type": "CLIPTextEncode", "inputs": {"text": anima_inputs["negative_prompt"], "clip": [clip, 0]}}
        detail = str(next_id + 2)
        prompt[detail] = {"class_type": "AtelierXImpactDetailerPipeline", "inputs": {"image": image, "model": model, "clip": [clip, 0], "vae": [vae, 0], "positive": [positive, 0], "negative": [negative, 0], **cfg}}
        image, next_id = [detail, 0], next_id + 3
    if "censor" in pipeline:
        cfg = pipeline["censor"]
        detect, apply = str(next_id), str(next_id + 1)
        prompt[detect] = {"class_type": "AtelierXDetectNsfwMask", "inputs": {
            "image": image, "segmentation_model": cfg["segmentation_model"], "labels": cfg["labels"], "confidence": cfg["confidence"]}}
        prompt[apply] = {"class_type": "AtelierXCensor", "inputs": {"image": image, "detection_mask": [detect, 0],
            "treatment": cfg["treatment"], "intensity": cfg["intensity"], "enabled": True}}
        image, next_id = [apply, 0], next_id + 2
    if "alpha" in pipeline:
        cfg = pipeline["alpha"]
        detect, apply = str(next_id), str(next_id + 1)
        prompt[detect] = {"class_type": "AtelierXDetectCharacterMask", "inputs": {
            "image": image, "segmentation_model": cfg["segmentation_model"], "confidence": cfg["confidence"]}}
        prompt[apply] = {"class_type": "AtelierXApplyCharacterAlpha", "inputs": {"image": image, "character_mask": [detect, 0], "enabled": True}}
        image, next_id = [apply, 0], next_id + 2
    output = str(next_id)
    if "encode" in pipeline:
        cfg = pipeline["encode"]
        prompt[output] = {"class_type": "AtelierXEncodeSave", "inputs": {"image": image,
            "filename_prefix": job_id, **cfg}}
    else:
        prompt[output] = {"class_type": "SaveImage", "inputs": {"images": image, "filename_prefix": f"AtelierX/{job_id}"}}
    return prompt, output
