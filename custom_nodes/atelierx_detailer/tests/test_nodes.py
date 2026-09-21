from __future__ import annotations

import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


NODE_PATH = Path(__file__).resolve().parents[1] / "nodes.py"


class Tensor:
    def __init__(self, shape): self.shape = shape
    def __getitem__(self, _): return self
    def unsqueeze(self, _): return self
    def to(self, **_): return self
    def clamp(self, *_): return self
    def __mul__(self, _): return self
    def __rmul__(self, _): return self
    def __add__(self, _): return self


class Field:
    @staticmethod
    def Input(identifier, **kwargs): return {"id": identifier, **kwargs}
    @staticmethod
    def Output(**kwargs): return kwargs


class Output:
    def __init__(self, *args): self.args = args


def fake_modules():
    samplers = types.ModuleType("comfy.samplers")
    samplers.KSampler = types.SimpleNamespace(SAMPLERS=["euler"], SCHEDULERS=["normal"])
    comfy = types.ModuleType("comfy"); comfy.__path__ = []; comfy.samplers = samplers
    api = types.ModuleType("comfy_api"); api.__path__ = []
    latest = types.ModuleType("comfy_api.latest")
    latest.ComfyExtension = type("ComfyExtension", (), {})
    latest.io = types.SimpleNamespace(ComfyNode=type("ComfyNode", (), {}), NodeOutput=Output, Schema=lambda **kwargs: kwargs,
        Image=Field, Mask=Field, Model=Field, Clip=Field, Vae=Field, Conditioning=Field, Combo=Field, String=Field, Boolean=Field, Int=Field, Float=Field)
    nodes = types.ModuleType("nodes")
    nodes.CLIPTextEncode = lambda: types.SimpleNamespace(encode=Mock(side_effect=[("positive",), ("negative",)]))
    nodes.VAEEncodeForInpaint = lambda: types.SimpleNamespace(encode=Mock(return_value=("latent",)))
    nodes.KSampler = lambda: types.SimpleNamespace(sample=Mock(return_value=("sampled",)))
    nodes.VAEDecode = lambda: types.SimpleNamespace(decode=Mock(return_value=("decoded",)))
    package = types.ModuleType("atelierx_detailer"); package.__path__ = [str(NODE_PATH.parent)]
    detectors = types.ModuleType("atelierx_detailer.detectors")
    detectors.detect_ultralytics_bbox_masks = Mock(return_value="mask")
    folder_paths = types.ModuleType("folder_paths")
    folder_paths.get_filename_list = Mock(return_value=[])
    return {"comfy": comfy, "comfy.samplers": samplers, "comfy_api": api, "comfy_api.latest": latest, "nodes": nodes, "folder_paths": folder_paths, "atelierx_detailer": package, "atelierx_detailer.detectors": detectors}


class DetailerTests(unittest.TestCase):
    def setUp(self):
        self.modules = fake_modules(); self.patch = patch.dict(sys.modules, self.modules); self.patch.start()
        spec = importlib.util.spec_from_file_location("atelierx_detailer.nodes", NODE_PATH)
        self.module = importlib.util.module_from_spec(spec); assert spec.loader; spec.loader.exec_module(self.module)

    def tearDown(self): self.patch.stop()

    def test_supported_targets_are_explicit(self):
        self.assertEqual(self.module.DETAIL_TARGETS, ("eyes", "mouth", "hands", "face"))

    def test_rejects_wrong_mask_size_before_sampling(self):
        with self.assertRaisesRegex(ValueError, "exactly match"):
            self.module._validate_image_and_mask(Tensor((1, 16, 16, 3)), Tensor((1, 15, 16)))

    def test_rejects_unknown_target_and_invalid_denoise(self):
        with self.assertRaisesRegex(ValueError, "target"):
            self.module._validate_request("nose", 0, 20, 5, "euler", "normal", .3, 6)
        with self.assertRaisesRegex(ValueError, "denoise"):
            self.module._validate_request("face", 0, 20, 5, "euler", "normal", 1.1, 6)

    def test_execute_uses_native_inpaint_chain(self):
        image, mask = Tensor((1, 16, 16, 3)), Tensor((1, 16, 16))
        with patch.object(self.module, "_composite_region", return_value="result") as composite:
            result = self.module.AtelierXDetailer.execute(image, mask, "model", "clip", "vae", "face", "detail face", "", 4, 20, 5, "euler", "normal", .35, 6)
        self.assertEqual(result.args, ("result",)); composite.assert_called_once_with(image, "decoded", mask)

    def test_impact_schema_has_four_enabled_stages_and_reference_models(self):
        schema = self.module.AtelierXImpactDetailerPipeline.define_schema()
        inputs = {field["id"]: field for field in schema["inputs"]}
        self.assertEqual([name for name in inputs if name.endswith("_enabled")], ["face_enabled", "eye_enabled", "mouth_enabled", "hand_enabled"])
        self.assertEqual(inputs["face_detector_model"]["default"], "bbox/face_yolov8m.pt")
        self.assertEqual(inputs["eye_detector_model"]["default"], "segm/PitEyeDetailer-v2-seg.pt")
        self.assertEqual(inputs["hand_detector_model"]["default"], "bbox/hand_yolov8s.pt")


if __name__ == "__main__": unittest.main()
