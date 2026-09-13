from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image
import torch


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE_ROOT))
import encode


class EncodeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.output = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    @staticmethod
    def rgb_batch():
        return torch.tensor([[[[0.0, 0.5, 1.0], [1.0, 0.0, 0.25]]]], dtype=torch.float32)

    @staticmethod
    def rgba_batch():
        return torch.tensor([[[[1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.5]]]], dtype=torch.float32)

    def output_files(self, suffix: str):
        return list((self.output / "AtelierX").glob(f"*{suffix}"))

    def test_png_decode_dimensions_and_rgb_are_written(self):
        saved = encode.save_images(self.rgb_batch(), self.output, "portrait", False, 90)
        files = self.output_files(".png")
        self.assertEqual(len(files), 1)
        self.assertEqual(saved, {"images": [{"filename": files[0].name, "subfolder": "AtelierX", "type": "output"}],
                                 "files": [{"filename": files[0].name, "subfolder": "AtelierX", "type": "output", "format": "png"}]})
        with Image.open(files[0]) as image:
            self.assertEqual(image.mode, "RGB")
            self.assertEqual(image.size, (2, 1))
            self.assertEqual(image.getpixel((0, 0)), (0, 128, 255))
        self.assertEqual(self.output_files(".webp"), [])

    def test_png_and_webp_decode_with_rgba_alpha(self):
        saved = encode.save_images(self.rgba_batch(), self.output, "transparent", True, 100)
        png, webp = self.output_files(".png")[0], self.output_files(".webp")[0]
        self.assertEqual(png.stem, webp.stem)
        self.assertEqual([entry["format"] for entry in saved["files"]], ["png", "webp"])
        self.assertEqual([entry["filename"] for entry in saved["files"]], [png.name, webp.name])
        for file in (png, webp):
            with Image.open(file) as image:
                self.assertEqual(image.size, (2, 1))
                self.assertEqual(image.mode, "RGBA")
                self.assertEqual([image.getpixel((x, 0))[3] for x in range(2)], [0, 128])

    def test_batch_and_repeated_requests_never_overwrite(self):
        batch = self.rgb_batch().repeat((2, 1, 1, 1))
        first = encode.save_images(batch, self.output, "batch", False, 90)["images"]
        original = {entry["filename"]: (self.output / "AtelierX" / entry["filename"]).read_bytes() for entry in first}
        second = encode.save_images(batch, self.output, "batch", False, 90)["images"]
        self.assertEqual(len(self.output_files(".png")), 4)
        self.assertTrue(set(entry["filename"] for entry in first).isdisjoint(entry["filename"] for entry in second))
        self.assertEqual(original, {name: (self.output / "AtelierX" / name).read_bytes() for name in original})

    def test_rejects_paths_bad_quality_and_invalid_image(self):
        for prefix in ("../escape", "folder/name", "folder\\name", "", "한글"):
            with self.subTest(prefix=prefix), self.assertRaisesRegex(ValueError, "filename_prefix"):
                encode.save_images(self.rgb_batch(), self.output, prefix, False, 90)
        for quality in (0, 101, True, 90.0):
            with self.subTest(quality=quality), self.assertRaisesRegex(ValueError, "webp_quality"):
                encode.save_images(self.rgb_batch(), self.output, "safe", False, quality)
        with self.assertRaisesRegex(ValueError, "RGB"):
            encode.save_images(torch.zeros((1, 2, 2, 2)), self.output, "safe", False, 90)
        with self.assertRaisesRegex(ValueError, "finite"):
            encode.save_images(torch.tensor([[[[float("nan"), 0, 0]]]]), self.output, "safe", False, 90)

    def test_webp_failure_keeps_png_and_raises(self):
        original = encode._atomic_save

        def fail_webp(image, destination, image_format, **options):
            if image_format == "WEBP":
                raise OSError("simulated WebP encoder failure")
            return original(image, destination, image_format, **options)

        with patch.object(encode, "_atomic_save", side_effect=fail_webp):
            with self.assertRaisesRegex(OSError, "WebP"):
                encode.save_images(self.rgb_batch(), self.output, "recover", True, 90)
        self.assertEqual(len(self.output_files(".png")), 1)
        self.assertEqual(self.output_files(".webp"), [])


if __name__ == "__main__":
    unittest.main()
