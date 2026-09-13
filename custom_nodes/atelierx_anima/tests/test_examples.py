from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "validate_examples.py"
SPEC = importlib.util.spec_from_file_location("atelierx_anima_validate_examples", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
validator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(validator)


class ExampleValidationTests(unittest.TestCase):
    def test_checked_in_workflow_and_api_prompt_are_consistent(self):
        validator.validate_static(
            validator._load(validator.WORKFLOW_PATH),
            validator._load(validator.API_PATH),
        )

    def test_rejects_api_prompt_that_disconnects_preview(self):
        workflow = validator._load(validator.WORKFLOW_PATH)
        api_request = validator._load(validator.API_PATH)
        api_request["prompt"]["2"]["inputs"]["images"] = ["1", 1]

        with self.assertRaisesRegex(ValueError, "PreviewImage"):
            validator.validate_static(workflow, api_request)

    def test_checked_in_lora_workflow_and_api_prompt_are_consistent(self):
        validator.validate_lora_static(
            validator._load(validator.LORA_WORKFLOW_PATH),
            validator._load(validator.LORA_API_PATH),
        )


if __name__ == "__main__":
    unittest.main()
