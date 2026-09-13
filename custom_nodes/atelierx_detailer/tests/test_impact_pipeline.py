from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


PATH = Path(__file__).resolve().parents[1] / "impact_pipeline.py"
SPEC = importlib.util.spec_from_file_location("impact_pipeline_under_test", PATH)
module = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(module)


class Provider:
    def __init__(self, calls): self.calls = calls
    def doit(self, model_name): self.calls.append(("detector", model_name)); return ("bbox:" + model_name, "segm:" + model_name)


class Sam:
    def __init__(self, calls): self.calls = calls
    def load_model(self, model_name, device): self.calls.append(("sam", model_name, device)); return ("sam:" + model_name,)


class Pipe:
    def __init__(self, calls): self.calls = calls
    def doit(self, **kwargs): self.calls.append(("pipe", kwargs["bbox_detector"])); return ("pipe:" + kwargs["bbox_detector"],)


class Detail:
    def __init__(self, calls): self.calls = calls
    def doit(self, image, detailer_pipe, **kwargs): self.calls.append(("detail", image, detailer_pipe, kwargs["seed"])); return (image + ">",)


class ImpactPipelineTests(unittest.TestCase):
    def test_sequences_enabled_stages_and_forwards_reference_api(self):
        calls = []
        classes = {"UltralyticsDetectorProvider": lambda: Provider(calls), "SAMLoader": lambda: Sam(calls),
                   "ToDetailerPipe": lambda: Pipe(calls), "FaceDetailerPipe": lambda: Detail(calls)}
        result = module.run_pipeline("image", {"face": True, "eye": False, "mouth": True, "hand": True},
            {"face": "face.pt", "eye": "eye.pt", "mouth": "mouth.pt", "hand": "hand.pt"}, "sam.pth",
            "model", "clip", "vae", "positive", "negative", {"seed": 7}, module.ImpactPipeline(classes))
        self.assertEqual(result, "image>>>")
        self.assertEqual([call[1] for call in calls if call[0] == "detector"], ["face.pt", "mouth.pt", "hand.pt"])
        self.assertEqual([call[1] for call in calls if call[0] == "detail"], ["image", "image>", "image>>"])
        self.assertTrue(all(call[1] == "sam.pth" and call[2] == "AUTO" for call in calls if call[0] == "sam"))

    def test_all_disabled_returns_original_without_loading_impact(self):
        self.assertIs(module.run_pipeline("image", {stage: False for stage in module.STAGES}, {stage: "model" for stage in module.STAGES}, "sam", None, None, None, None, None, {}, pipeline=None), "image")

    def test_missing_classes_are_explicit(self):
        with self.assertRaisesRegex(RuntimeError, "Missing Impact detailer classes"):
            module.ImpactPipeline({}).run_stage("image", "face", "face.pt", "sam.pth", None, None, None, None, None, {})
