from __future__ import annotations

import asyncio
import importlib
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


PACKAGE_PARENT = str(Path(__file__).resolve().parents[2])


class FakeNodeOutput:
    def __init__(self, *args, ui=None):
        self.args, self.ui = args, ui

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


class NodeRegistrationTests(unittest.TestCase):
    def setUp(self):
        folder_paths = types.ModuleType("folder_paths")
        folder_paths.get_output_directory = Mock(return_value="C:/Comfy/output")
        comfy_api = types.ModuleType("comfy_api")
        comfy_api.__path__ = []
        latest = types.ModuleType("comfy_api.latest")
        latest.ComfyExtension = type("ComfyExtension", (), {})
        latest.io = types.SimpleNamespace(
            ComfyNode=type("ComfyNode", (), {}), Schema=FakeSchema, NodeOutput=FakeNodeOutput,
            Image=FakeField, String=FakeField, Boolean=FakeField, Int=FakeField,
        )
        self.modules = {"folder_paths": folder_paths, "comfy_api": comfy_api, "comfy_api.latest": latest}
        self.patch = patch.dict(sys.modules, self.modules)
        self.patch.start()
        sys.path.insert(0, PACKAGE_PARENT)
        for name in ("atelierx_encode.nodes", "atelierx_encode"):
            sys.modules.pop(name, None)
        self.module = importlib.import_module("atelierx_encode.nodes")

    def tearDown(self):
        for name in ("atelierx_encode.nodes", "atelierx_encode"):
            sys.modules.pop(name, None)
        sys.path.remove(PACKAGE_PARENT)
        self.patch.stop()

    def test_schema_is_output_node_and_exposes_the_public_contract(self):
        schema = self.module.AtelierXEncodeSave.define_schema()
        self.assertEqual(schema.node_id, "AtelierXEncodeSave")
        self.assertTrue(schema.is_output_node)
        self.assertEqual([field["id"] for field in schema.inputs], ["image", "filename_prefix", "webp_enabled", "webp_quality"])
        self.assertEqual(schema.inputs[3]["min"], 1)
        self.assertEqual(schema.inputs[3]["max"], 100)
        self.assertEqual(asyncio.run(self.module.AtelierXEncodeSaveExtension().get_node_list()), [self.module.AtelierXEncodeSave])

    def test_execute_returns_standard_history_image_descriptors(self):
        saved = {"images": [{"filename": "image.png", "subfolder": "AtelierX", "type": "output"}],
                 "files": [{"filename": "image.png", "subfolder": "AtelierX", "type": "output", "format": "png"},
                           {"filename": "image.webp", "subfolder": "AtelierX", "type": "output", "format": "webp"}]}
        with patch.object(self.module, "save_images", return_value=saved) as save:
            image = object()
            result = self.module.AtelierXEncodeSave.execute(image, "image", True, 90)
        save.assert_called_once_with(image, "C:/Comfy/output", "image", True, 90)
        self.assertIs(result[0], image)
        self.assertEqual(result.ui, {"images": saved["images"], "atelierx_files": saved["files"]})


if __name__ == "__main__":
    unittest.main()
