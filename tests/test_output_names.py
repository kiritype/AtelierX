import importlib.util
import unittest
from pathlib import Path

from atelierx.output_names import build_output_name, sanitize_segment, validate_output_name


class OutputNameTests(unittest.TestCase):
    def test_sanitize_keeps_unicode_and_replaces_forbidden_characters(self):
        self.assertEqual(sanitize_segment("작품 이름"), "작품 이름")
        self.assertEqual(sanitize_segment('a<b>c:d"e/f\\g|h?i*j'), "a_b_c_d_e_f_g_h_i_j")
        self.assertEqual(sanitize_segment("a\x00b\x1fc\x7f"), "a_b_c_")
        self.assertEqual(sanitize_segment("  여러   칸\u3000공백 "), "여러 칸 공백")
        self.assertEqual(sanitize_segment("끝점. . ."), "끝점")
        for empty in ("", "   ", "...", ". ."):
            self.assertEqual(sanitize_segment(empty), "_")

    def test_reserved_windows_names_get_suffix(self):
        for name, expected in (("CON", "CON_"), ("nul", "nul_"), ("Com1", "Com1_"), ("LPT9", "LPT9_"),
                               ("aux.png", "aux_.png"), ("PRN .txt", "PRN_.txt"), ("CONSOLE", "CONSOLE"), ("COM0", "COM0")):
            with self.subTest(name=name):
                self.assertEqual(sanitize_segment(name), expected)

    def test_segment_length_cap_is_idempotent(self):
        long = "가" * 79 + ". b"
        value = sanitize_segment(long)
        self.assertLessEqual(len(value), 80)
        self.assertEqual(sanitize_segment(value), value)
        self.assertEqual(len(sanitize_segment("x" * 200)), 80)
        reserved_long = "CON." + "y" * 90
        self.assertEqual(len(sanitize_segment(reserved_long)), 80)
        self.assertTrue(sanitize_segment(reserved_long).startswith("CON_."))

    def test_build_joins_sanitized_segments(self):
        self.assertEqual(build_output_name("AtelierX", "작품/1", "캐릭터:A", "복장?", "12"), "AtelierX/작품_1/캐릭터_A/복장_/12")
        self.assertEqual(build_output_name("AtelierX", "..", "CON"), "AtelierX/_/CON_")
        with self.assertRaises(ValueError):
            build_output_name(*["a"] * 7)
        self.assertLessEqual(len(build_output_name(*["x" * 80] * 4)), 240)

    def test_validate_rejects_traversal_absolute_and_unsanitized(self):
        self.assertEqual(validate_output_name("AtelierX/작품/캐릭터/복장/12"), "AtelierX/작품/캐릭터/복장/12")
        for bad in (None, 1, "", "/abs", "a/", "a//b", "../x", "a/../b", "./a", "C:/x", "a\\b", "CON", "a/nul.txt",
                    " a", "a.", "a  b", "a/b/c/d/e/f/g", "x" * 81, "/".join(["y" * 50] * 5), "a\nb"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                validate_output_name(bad)
        self.assertEqual(len(validate_output_name("/".join(["z" * 47] * 5))), 239)

    def test_encode_node_copy_matches_shared_rules(self):
        path = Path(__file__).resolve().parents[1] / "custom_nodes" / "atelierx_encode" / "encode.py"
        spec = importlib.util.spec_from_file_location("atelierx_encode_rules", path)
        module = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)
        except ImportError as exc:
            self.skipTest(f"Encode dependencies unavailable: {exc}")
        samples = ["작품", "CON", "aux.png", "a<b", "  x  ", "끝.", "", "...", "x" * 100, "CON." + "y" * 90, "a\tb", "COM0", "12 (2)"]
        for sample in samples:
            with self.subTest(sample=sample):
                self.assertEqual(module.sanitize_segment(sample), sanitize_segment(sample))
        for name in ("AtelierX/작품/12", "a/../b", "CON", "a/b/c/d/e/f/g", "x" * 81, "/".join(["y" * 50] * 5)):
            with self.subTest(name=name):
                try:
                    expected = validate_output_name(name)
                except ValueError:
                    with self.assertRaises(ValueError):
                        module.validate_output_name(name)
                else:
                    self.assertEqual(module.validate_output_name(name), expected)


if __name__ == "__main__":
    unittest.main()


class LongNameTests(unittest.TestCase):
    def test_long_middle_segments_are_trimmed_not_rejected(self):
        name = build_output_name("AtelierX", "작" * 80, "캐" * 80, "복" * 80, "12")
        self.assertLessEqual(len(name), 240)
        parts = name.split("/")
        self.assertEqual((parts[0], parts[-1]), ("AtelierX", "12"))
        self.assertEqual(validate_output_name(name), name)

    def test_non_text_segment_is_converted(self):
        self.assertEqual(build_output_name("AtelierX", 12), "AtelierX/12")
