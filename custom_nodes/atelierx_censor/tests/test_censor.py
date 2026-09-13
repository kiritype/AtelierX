from __future__ import annotations

import sys
import unittest
from pathlib import Path

import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from censor import apply_censor
from detectors import detect_selected_segmentation_masks


class CensorTests(unittest.TestCase):
    def test_white_solid_changes_only_masked_pixels(self):
        image = torch.tensor([[[[.1, .2, .3], [.4, .5, .6]]]])
        result = apply_censor(image, torch.tensor([[[0., 1.]]]), "white_solid", 2)
        self.assertTrue(torch.equal(result[0, 0, 0], torch.ones(3)))
        self.assertTrue(torch.equal(result[0, 0, 1], torch.ones(3)))

    def test_mosaic_uses_block_average_and_preserves_alpha(self):
        image = torch.tensor([[[[0., 0., 0., .2], [1., 1., 1., .8]], [[0., 0., 0., .4], [1., 1., 1., .6]]]])
        result = apply_censor(image, torch.ones((1, 2, 2)), "mosaic", 2)
        self.assertTrue(torch.allclose(result[..., :3], torch.full((1, 2, 2, 3), .5)))
        self.assertTrue(torch.equal(result[..., 3], image[..., 3]))

    def test_disabled_returns_original_tensor(self):
        image = torch.zeros((1, 2, 2, 3)); self.assertIs(apply_censor(image, torch.ones((1, 2, 2)), "white", 2, False), image)

    def test_rejects_wrong_mask_and_invalid_treatment(self):
        image = torch.zeros((1, 2, 2, 3))
        with self.assertRaisesRegex(ValueError, "exactly matching"):
            apply_censor(image, torch.zeros((2, 2)), "white", 2)
        with self.assertRaisesRegex(ValueError, "treatment"):
            apply_censor(image, torch.zeros((1, 2, 2)), "black", 2)

    def test_local_segmentation_adapter_selects_reference_labels(self):
        class Result:
            names={0:"nipples",1:"face"}; masks=type("Masks",(),{"data":torch.tensor([[[0,1,1,0],[0,1,1,0]],[[1,0,0,0],[0,0,0,0]]])})(); boxes=type("Boxes",(),{"cls":torch.tensor([0,1])})()
        class Detector:
            def predict(self, **_): return [Result()]
        result = detect_selected_segmentation_masks(torch.zeros((1, 2, 4, 3)), "C:/local/model.pt", ("nipples",), .5, model_loader=lambda _: Detector())
        self.assertTrue(torch.equal(result, torch.tensor([[[0., 1., 1., 0.], [0., 1., 1., 0.]]])))

    def test_detector_receives_bgr_bytes_and_wrong_model_is_error(self):
        captured = []
        class Result:
            names = {0: "nipples"}
            masks = None
            boxes = None
        class Detector:
            names = Result.names
            def predict(self, **kwargs):
                captured.append(kwargs["source"])
                return [Result()]
        image = torch.tensor([[[[.1, .5, .9]]]])
        output = detect_selected_segmentation_masks(image, "C:/local/model.pt", ("nipples",), .5, model_loader=lambda _: Detector())
        self.assertEqual(str(captured[0].dtype), "uint8")
        self.assertEqual(captured[0][0, 0].tolist(), [230, 128, 26])
        self.assertFalse(output.any())
        Result.names = {0: "person"}
        with self.assertRaises((ValueError, RuntimeError)):
            detect_selected_segmentation_masks(image, "C:/local/model.pt", ("nipples",), .5, model_loader=lambda _: Detector())

    def test_detector_rejects_nonfinite_before_loading(self):
        image = torch.full((1, 2, 2, 3), float("nan"))
        def forbidden(_):
            self.fail("Model must not load for invalid image")
        with self.assertRaises(ValueError):
            detect_selected_segmentation_masks(image, "C:/local/model.pt", ("nipples",), .5, model_loader=forbidden)


if __name__ == "__main__": unittest.main()
