from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from segmentation import detect_ultralytics_person_masks


class _Masks:
    def __init__(self, data):
        self.data = data


class _Result:
    def __init__(self, data):
        self.masks = None if data is None else _Masks(data)


class _Model:
    def __init__(self, results):
        self.results = results
        self.calls = []

    def predict(self, **kwargs):
        self.calls.append(kwargs)
        return [self.results.pop(0)]


class UltralyticsCharacterMaskTests(unittest.TestCase):
    def test_combines_all_detected_people_and_preserves_batch_order(self):
        model = _Model([
            _Result(torch.tensor([[[1, 0], [0, 0]], [[0, 0], [0, 1]]])),
            _Result(torch.tensor([[[0, 1], [0, 0]]])),
        ])
        images = torch.zeros((2, 2, 2, 3), dtype=torch.float32)

        actual = detect_ultralytics_person_masks(
            images, "C:/models/local-person-seg.pt", 0.35, model_loader=lambda _: model
        )

        expected = torch.tensor([[[1, 0], [0, 1]], [[0, 1], [0, 0]]], dtype=torch.float32)
        self.assertTrue(torch.equal(actual, expected))
        self.assertEqual(model.calls[0]["classes"], [0])
        self.assertTrue(model.calls[0]["retina_masks"])

    def test_converts_comfy_rgb_float_to_ultralytics_bgr_uint8(self):
        model = _Model([_Result(torch.ones((1, 1, 1)))])
        image = torch.tensor([[[[0.1, 0.5, 0.9]]]], dtype=torch.float32)

        detect_ultralytics_person_masks(
            image, "C:/models/local-person-seg.pt", 0.35, model_loader=lambda _: model
        )

        source = model.calls[0]["source"]
        self.assertEqual(source.dtype, np.uint8)
        self.assertEqual(source.shape, (1, 1, 3))
        self.assertTrue(np.array_equal(source[0, 0], np.array([230, 128, 26], dtype=np.uint8)))

    def test_rejects_non_aligned_backend_masks(self):
        model = _Model([_Result(torch.ones((1, 1, 1)))])
        with self.assertRaisesRegex(RuntimeError, "dimensions do not match"):
            detect_ultralytics_person_masks(
                torch.zeros((1, 2, 2, 3)), "C:/models/local-person-seg.pt", 0.5,
                model_loader=lambda _: model,
            )

    def test_no_detection_fails_without_returning_an_all_transparent_alpha_mask(self):
        model = _Model([_Result(None)])
        with self.assertRaisesRegex(RuntimeError, "No person segmentation was detected"):
            detect_ultralytics_person_masks(
                torch.zeros((1, 2, 2, 3)), "C:/models/local-person-seg.pt", 0.5,
                model_loader=lambda _: model,
            )

    def test_rejects_bad_request_values_before_loading_model(self):
        with self.assertRaisesRegex(ValueError, "confidence"):
            detect_ultralytics_person_masks(
                torch.zeros((1, 1, 1, 3)), "model.pt", 1.1, model_loader=lambda _: None
            )

    def test_missing_runtime_is_reported_without_any_download_attempt(self):
        with patch.dict(sys.modules, {"ultralytics": None}):
            with self.assertRaisesRegex(RuntimeError, "requires the 'ultralytics' Python package"):
                detect_ultralytics_person_masks(
                    torch.zeros((1, 1, 1, 3)), "C:/models/local-person-seg.pt", 0.35
                )


if __name__ == "__main__":
    unittest.main()
