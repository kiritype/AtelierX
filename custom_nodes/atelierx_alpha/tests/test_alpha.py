from __future__ import annotations

import unittest
import sys
from pathlib import Path

import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from alpha import apply_character_alpha


class ApplyCharacterAlphaTests(unittest.TestCase):
    def test_foreground_mask_makes_only_background_transparent(self):
        image = torch.tensor([[[[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]]])
        foreground = torch.tensor([[[1.0, 0.25]]])

        rgba, background = apply_character_alpha(image, foreground, True)

        self.assertTrue(torch.equal(rgba[..., :3], image))
        self.assertTrue(torch.allclose(rgba[..., 3], foreground))
        self.assertTrue(torch.allclose(background, torch.tensor([[[0.0, 0.75]]])))

    def test_existing_alpha_is_preserved_when_mask_is_applied(self):
        image = torch.tensor([[[[0.1, 0.2, 0.3, 0.5], [0.4, 0.5, 0.6, 0.8]]]])
        foreground = torch.tensor([[[0.5, 1.0]]])

        rgba, background = apply_character_alpha(image, foreground, True)

        self.assertTrue(torch.allclose(rgba[..., 3], torch.tensor([[[0.25, 0.8]]])))
        self.assertTrue(torch.allclose(background, torch.tensor([[[0.75, 0.2]]])))

    def test_disabled_leaves_rgb_and_existing_alpha_unchanged(self):
        image = torch.tensor([[[[0.1, 0.2, 0.3, 0.5]]]])
        foreground = torch.zeros((1, 1, 1))

        rgba, background = apply_character_alpha(image, foreground, False)

        self.assertTrue(torch.equal(rgba, image))
        self.assertTrue(torch.allclose(background, torch.tensor([[[0.5]]])))

    def test_rejects_ambiguous_mask_shape_or_image_batch(self):
        image = torch.zeros((1, 2, 2, 3))
        with self.assertRaisesRegex(ValueError, "character_mask"):
            apply_character_alpha(image, torch.zeros((2, 2)), True)
        with self.assertRaisesRegex(ValueError, "exactly match"):
            apply_character_alpha(image, torch.zeros((2, 2, 2)), True)

    def test_rejects_non_finite_or_non_floating_inputs(self):
        image = torch.zeros((1, 1, 1, 3))
        with self.assertRaisesRegex(ValueError, "images"):
            apply_character_alpha(image.to(torch.uint8), torch.ones((1, 1, 1)), True)
        with self.assertRaisesRegex(ValueError, "character_mask"):
            apply_character_alpha(image, torch.tensor([[[float("nan")]]]), True)


if __name__ == "__main__":
    unittest.main()
