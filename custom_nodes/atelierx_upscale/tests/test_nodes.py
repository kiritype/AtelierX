from __future__ import annotations

import asyncio
import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


NODE_PATH = Path(__file__).resolve().parents[1] / "nodes.py"
MODULE_NAME = "atelierx_upscale_nodes_under_test"


class FakeTensor:
    def __init__(self, shape):
        self.shape = shape
        self.moves = []

    def movedim(self, source, destination):
        self.moves.append((source, destination))
        if (source, destination) == (-1, 1):
            return FakeTensor((self.shape[0], self.shape[3], self.shape[1], self.shape[2]))
        if (source, destination) == (1, -1):
            return FakeTensor((self.shape[0], self.shape[2], self.shape[3], self.shape[1]))
        raise AssertionError((source, destination))


class FakeNodeOutput:
    def __init__(self, *args):
        self.args = args

    def __getitem__(self, index):
        return self.args[index]


class FakeField:
    @staticmethod
    def Input(identifier, **kwargs):
        return {"id": identifier, **kwargs}

    @staticmethod
    def Output(**kwargs):
        return kwargs


class FakeSchema:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


def fake_modules():
    folder_paths = types.ModuleType("folder_paths")
    folder_paths.get_filename_list = Mock(return_value=["4x-Test.pth"])

    comfy = types.ModuleType("comfy")
    comfy.__path__ = []
    comfy_utils = types.ModuleType("comfy.utils")
    comfy_utils.common_upscale = Mock(side_effect=lambda tensor, width, height, *_: FakeTensor((tensor.shape[0], tensor.shape[1], height, width)))
    comfy.utils = comfy_utils

    comfy_api = types.ModuleType("comfy_api")
    comfy_api.__path__ = []
    latest = types.ModuleType("comfy_api.latest")
    latest.ComfyExtension = type("ComfyExtension", (), {})
    latest.io = types.SimpleNamespace(
        ComfyNode=type("ComfyNode", (), {}), Schema=FakeSchema, NodeOutput=FakeNodeOutput,
        Combo=FakeField, Float=FakeField, Image=FakeField,
    )

    upscale = types.ModuleType("comfy_extras.nodes_upscale_model")
    upscale.UpscaleModelLoader = types.SimpleNamespace(execute=Mock(return_value=("loaded-model",)))
    upscale.ImageUpscaleWithModel = types.SimpleNamespace(execute=Mock(return_value=(FakeTensor((1, 400, 800, 3)),)))
    return {
        "folder_paths": folder_paths, "comfy": comfy, "comfy.utils": comfy_utils,
        "comfy_api": comfy_api, "comfy_api.latest": latest,
        "comfy_extras": types.ModuleType("comfy_extras"), "comfy_extras.nodes_upscale_model": upscale,
    }


class AtelierXUpscaleTests(unittest.TestCase):
    def setUp(self):
        self.mocks = fake_modules()
        self.module_patch = patch.dict(sys.modules, self.mocks)
        self.module_patch.start()
        spec = importlib.util.spec_from_file_location(MODULE_NAME, NODE_PATH)
        self.module = importlib.util.module_from_spec(spec)
        sys.modules[MODULE_NAME] = self.module
        assert spec.loader is not None
        spec.loader.exec_module(self.module)

    def tearDown(self):
        sys.modules.pop(MODULE_NAME, None)
        self.module_patch.stop()

    def test_target_dimension_uses_half_up_rounding(self):
        self.assertEqual(self.module._target_dimension(101, 1.5), 152)
        self.assertEqual(self.module._target_dimension(100, 1.005), 101)
        self.assertEqual(self.module._target_dimension(1, 0.01), 1)

    def test_target_dimension_rejects_invalid_scale(self):
        for value in (0, -1, True, float("nan"), float("inf"), "2"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.module._target_dimension(100, value)

    def test_execute_uses_registered_model_then_resizes_to_final_scale(self):
        image = FakeTensor((1, 200, 400, 3))
        output = self.module.AtelierXUpscale.execute(image, "4x-Test.pth", 1.5)
        loader = self.mocks["comfy_extras.nodes_upscale_model"].UpscaleModelLoader.execute
        upscaler = self.mocks["comfy_extras.nodes_upscale_model"].ImageUpscaleWithModel.execute
        loader.assert_called_once_with("4x-Test.pth")
        upscaler.assert_called_once_with("loaded-model", image)
        self.mocks["comfy.utils"].common_upscale.assert_called_once()
        args = self.mocks["comfy.utils"].common_upscale.call_args.args
        self.assertEqual(args[1:5], (600, 300, "lanczos", "disabled"))
        self.assertEqual(output[0].shape, (1, 300, 600, 3))

    def test_execute_rejects_unknown_model_or_non_image_before_model_load(self):
        with self.assertRaisesRegex(ValueError, "not registered"):
            self.module.AtelierXUpscale.execute(FakeTensor((1, 2, 2, 3)), "outside.pth", 2)
        with self.assertRaisesRegex(ValueError, "batched RGB IMAGE"):
            self.module.AtelierXUpscale.execute(FakeTensor((2, 2, 3)), "4x-Test.pth", 2)
        for shape in ((0, 2, 2, 3), (1, 2, 2, 1), (1, 2, 2, 4), (1, 0, 2, 3)):
            with self.subTest(shape=shape), self.assertRaisesRegex(ValueError, "batched RGB IMAGE"):
                self.module.AtelierXUpscale.execute(FakeTensor(shape), "4x-Test.pth", 2)
        self.mocks["comfy_extras.nodes_upscale_model"].UpscaleModelLoader.execute.assert_not_called()

    def test_schema_and_extension_expose_only_image_model_and_scale(self):
        schema = self.module.AtelierXUpscale.define_schema()
        self.assertEqual(schema.node_id, "AtelierXUpscale")
        self.assertEqual([field["id"] for field in schema.inputs], ["image", "upscale_model", "scale"])
        self.assertEqual(schema.inputs[1]["options"], ["4x-Test.pth"])
        self.assertEqual(schema.inputs[2]["default"], 1.5)
        self.assertEqual(asyncio.run(self.module.AtelierXUpscaleExtension().get_node_list()), [self.module.AtelierXUpscale])


if __name__ == "__main__":
    unittest.main()
