from __future__ import annotations

import os
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

    def test_output_name_saves_exact_path_then_numbers_png_only(self):
        name = "AtelierX/작품/캐릭터/복장/12"
        folder = self.output / "AtelierX" / "작품" / "캐릭터" / "복장"
        first = encode.save_images(self.rgb_batch(), self.output, "ignored", False, 90, name)
        self.assertEqual(first["files"], [{"filename": "12.png", "subfolder": "AtelierX/작품/캐릭터/복장", "type": "output", "format": "png"}])
        self.assertEqual(first["images"], [{"filename": "12.png", "subfolder": "AtelierX/작품/캐릭터/복장", "type": "output"}])
        original = (folder / "12.png").read_bytes()
        second = encode.save_images(self.rgb_batch().repeat((2, 1, 1, 1)), self.output, "image", False, 90, name)
        self.assertEqual([f["filename"] for f in second["files"]], ["12 (2).png", "12 (3).png"])
        self.assertEqual((folder / "12.png").read_bytes(), original)
        self.assertEqual(sorted(p.name for p in folder.iterdir()), ["12 (2).png", "12 (3).png", "12.png"])

    def test_output_name_png_and_webp_share_suffix(self):
        name = "AtelierX/a/b/c/7"
        encode.save_images(self.rgb_batch(), self.output, "image", True, 90, name)
        second = encode.save_images(self.rgb_batch(), self.output, "image", True, 90, name)
        self.assertEqual([(f["filename"], f["format"]) for f in second["files"]], [("7 (2).png", "png"), ("7 (2).webp", "webp")])
        folder = self.output / "AtelierX/a/b/c"
        self.assertEqual(sorted(p.name for p in folder.iterdir()), ["7 (2).png", "7 (2).webp", "7.png", "7.webp"])

    def test_output_name_existing_webp_only_advances_png(self):
        folder = self.output / "AtelierX" / "x"
        folder.mkdir(parents=True)
        (folder / "3.webp").write_bytes(b"old")
        (folder / "3 (2).png").write_bytes(b"old")
        saved = encode.save_images(self.rgb_batch(), self.output, "image", False, 90, "AtelierX/x/3")
        self.assertEqual(saved["files"][0]["filename"], "3 (3).png")
        self.assertEqual((folder / "3.webp").read_bytes(), b"old")
        self.assertFalse((folder / "3.png").exists())

    def test_output_name_rejects_traversal_and_unsanitized_names(self):
        for name in ("../escape", "AtelierX/../../x", "/abs/x", "C:/x", "a\\b", "a//b", "a/./b", "CON", "a/b.", " a",
                     "a/b/c/d/e/f/g", "x" * 81, "a:b", "a\tb"):
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "output_name"):
                encode.save_images(self.rgb_batch(), self.output, "image", False, 90, name)
        self.assertEqual(list(self.output.iterdir()), [])

    def test_output_name_symlink_escape_is_refused(self):
        outside = tempfile.TemporaryDirectory()
        self.addCleanup(outside.cleanup)
        link = self.output / "AtelierX"
        try:
            link.symlink_to(outside.name, target_is_directory=True)
        except OSError:
            import subprocess
            if subprocess.run(["cmd", "/c", "mklink", "/J", str(link), outside.name], capture_output=True).returncode:
                self.skipTest("cannot create directory link")
        try:
            with self.assertRaisesRegex(RuntimeError, "escaped"):
                encode.save_images(self.rgb_batch(), self.output, "image", False, 90, "AtelierX/escape")
            self.assertEqual(list(Path(outside.name).iterdir()), [])
        finally:
            os.rmdir(link)

    def test_sanitize_segment_rules(self):
        self.assertEqual(encode.sanitize_segment('a<b>c:"d|e?f*g/h\\i'), "a_b_c__d_e_f_g_h_i")
        self.assertEqual(encode.sanitize_segment("  한글   이름.. "), "한글 이름")
        self.assertEqual(encode.sanitize_segment("con.txt"), "con_.txt")
        self.assertEqual(encode.sanitize_segment("..."), "_")

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
