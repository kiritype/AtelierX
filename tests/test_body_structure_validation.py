import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "test_body_structure_validation.py"
SPEC = importlib.util.spec_from_file_location("body_structure_harness", SCRIPT)
HARNESS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(HARNESS)


class BodyStructureHarnessTests(unittest.TestCase):
    def test_profile_has_only_independent_body_checks(self):
        sample = {"id": "sample", "expected": {"body_parts": {"hands": "matched"}}}
        self.assertEqual(HARNESS.profile(sample)["body_parts"], ["hands"])
        self.assertFalse(HARNESS.profile(sample)["positive_prompt"])
        self.assertFalse(HARNESS.profile(sample)["negative_prompt"])
        self.assertFalse(HARNESS.profile(sample)["output_conditions"])

    def test_unassessable_body_is_never_a_pass(self):
        case = {"expected": {"outcome": "passed", "error_code": None,
                             "body_parts": {"hands": "matched"}}}
        actual, matches = HARNESS.evaluate(case, {"outcome": "passed", "error": None, "result": {"evidence": []}})
        self.assertEqual(actual["body_parts"], {})
        self.assertFalse(matches)

    def test_expected_error_and_part_evidence_are_compared(self):
        case = {"expected": {"outcome": "error", "error_code": HARNESS.NO_ASSESSABLE,
                             "body_parts": {"hands": "not_visible"}}}
        job = {"outcome": "error", "error": {"code": HARNESS.NO_ASSESSABLE},
               "result": {"body_parts": {"hands": {"status": "not_visible"}}}}
        self.assertTrue(HARNESS.evaluate(case, job)[1])

    def test_manifest_rejects_parent_paths_and_unfixed_expectations(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cases.json"
            path.write_text(json.dumps({"schema_version": 1, "cases": [{
                "id": "bad", "image": "../outside.png", "sha256": "a" * 64, "positive_prompt": "actual",
                "expected": {"outcome": None, "error_code": None, "body_parts": {"hands": None}}
            }]}), encoding="utf-8")
            with self.assertRaises(ValueError):
                HARNESS.load_cases(path)


if __name__ == "__main__":
    unittest.main()
