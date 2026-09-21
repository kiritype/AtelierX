"""Contract model checks only: no provider, database, GPU or server calls."""
import copy
import json
from pathlib import Path
import unittest
from pydantic import ValidationError
from contract_models import MODELS, validate_exchange

ROOT = Path(__file__).parent


def load(name):
    return json.loads((ROOT / "examples" / f"{name}.json").read_text(encoding="utf-8"))


class ContractChecks(unittest.TestCase):
    def invalid(self, model, value):
        with self.assertRaises(ValidationError):
            MODELS[model].model_validate(value)

    def test_all_examples(self):
        manifest = load("manifest")
        for name, model in manifest.items():
            with self.subTest(example=name):
                MODELS[model].model_validate(load(name))

    def test_schemas_are_current(self):
        for name, model in MODELS.items():
            saved = json.loads((ROOT / "schemas" / f"{name}.schema.json").read_text(encoding="utf-8"))
            saved.pop("$schema")
            self.assertEqual(saved, model.model_json_schema())

    def test_invalid_requests(self):
        cases = [
            ("positive prompt absent", lambda x: x["image"].pop("positive_prompt")),
            ("blank prompt", lambda x: x["image"].update(positive_prompt="   ")),
            ("negative omitted", lambda x: x["image"].pop("negative_prompt")),
            ("arbitrary URL", lambda x: x["image"].update(source={"type": "url", "url": "http://example.test/a"})),
            ("path injection", lambda x: x["image"]["source"].update(path="C:/private.png")),
            ("bad digest", lambda x: x["image"]["source"].update(sha256="bad")),
            ("secret leakage", lambda x: x["provider"].update(api_key="secret")),
            ("expected output absent", lambda x: x.update(expected_output=None)),
            ("jpeg output", lambda x: x["expected_output"].update(media_type="image/jpeg")),
            ("invalid bool seed", lambda x: x["generation_settings"].update(seed=True)),
            ("NaN cfg", lambda x: x["generation_settings"].update(cfg=float("nan"))),
            ("disable mandatory preflight", lambda x: x["profile"].update(preflight=False)),
        ]
        for name, mutate in cases:
            with self.subTest(case=name):
                value = load("single-request"); mutate(value); self.invalid("single-request", value)

    def test_output_disabled_allows_no_expected_conditions(self):
        value = load("single-request")
        value["profile"]["output_conditions"] = False
        value["expected_output"] = None
        value["generation_settings"] = None
        value["image"]["negative_prompt"] = ""
        MODELS["single-request"].model_validate(value)

    def test_group_reference_integrity(self):
        cases = [lambda x: x.update(primary_reference="missing"),
                 lambda x: x["targets"].append(x["targets"][0]),
                 lambda x: x["images"].append(copy.deepcopy(x["images"][0])),
                 lambda x: x["auxiliary_references"].append(x["primary_reference"]),
                 lambda x: x.update(targets=[x["primary_reference"]], images=[x["images"][0],x["images"][1]]),
                 lambda x: x["images"][1].update(source=x["images"][0]["source"]),
                 lambda x: x["generation_summary"].update(requested=999)]
        for index, mutate in enumerate(cases):
            with self.subTest(case=index):
                value = load("group-request"); mutate(value); self.invalid("group-request", value)

    def test_error_cannot_regenerate(self):
        value = load("single-error")
        value["result"] = load("single-rejected")["result"]
        self.invalid("single-result", value)

    def test_changes_must_be_all_valid(self):
        for field, val in [("seed", True), ("seed", -1), ("seed", 2**64), ("cfg", float("inf")),
                           ("output_path", "C:/file"), ("max_regenerations", 99), ("loras", "[]"),
                           ("positive_prompt", " ")]:
            with self.subTest(field=field, value=val):
                value = load("single-rejected")
                value["result"]["regeneration"]["changes"].append(dict(field=field, value=val, reason="reason"))
                self.invalid("single-result", value)

    def test_duplicate_changes_rejected(self):
        value = load("single-rejected")
        value["result"]["regeneration"]["changes"] *= 2
        self.invalid("single-result", value)

    def test_regeneration_branch_invariants(self):
        for sample, mutate in [
            ("single-passed", lambda x: x.update(outcome="rejected")),
            ("single-rejected", lambda x: x.update(outcome="passed")),
            ("single-rejected", lambda x: x["result"]["regeneration"].update(changes=[])),
            ("single-rejected", lambda x: x["result"]["regeneration"].update(required=False)),
        ]:
            value=load(sample); mutate(value); self.invalid("single-result", value)

    def test_group_aggregate_cannot_hide_error(self):
        value = load("group-partial-failure")
        value["summary"] = "all_match"
        self.invalid("group-result", value)
        value = load("group-partial-failure")
        value["counts"]["error"] = 0
        self.invalid("group-result", value)

    def test_missing_item_and_unrecorded_reference(self):
        value=load("group-partial-failure"); value["items"].pop(); self.invalid("group-result", value)
        value=load("group-partial-failure"); value["items"][0]["compared_with"]=["other"]; self.invalid("group-result", value)

    def test_group_insufficient_is_not_match(self):
        value = load("group-partial-recheck")
        value["items"][0]["unavailable_features"] = ["eyes not visible in reference"]
        self.invalid("group-result", value)
        value["items"][0]["verdict"] = "insufficient"
        value["counts"].update(match=0, insufficient=1)
        value["summary"] = "incomplete"
        MODELS["group-result"].model_validate(value)

    def test_partial_recheck_scope_is_preserved(self):
        value = MODELS["group-result"].model_validate(load("group-partial-recheck"))
        self.assertEqual(value.scope, "partial")
        self.assertEqual(len(value.targets), 1)
        self.assertEqual(value.generation_summary.requested, 5)

    def test_job_state_constraints(self):
        for update in [dict(state="completed"), dict(result_available=True), dict(state="failed")]:
            value=load("job-running"); value.update(update); self.invalid("job", value)

    def test_single_exchange_identity_and_configuration(self):
        request = MODELS["single-request"].model_validate(load("single-request"))
        result = MODELS["single-result"].model_validate(load("single-passed"))
        j = load("job-running"); j.update(state="completed", result_available=True)
        job = MODELS["job"].model_validate(j)
        validate_exchange(request, result, job)
        for field, value in [("image_ref", "other"), ("job_id", "other")]:
            wrong = result.model_copy(update={field: value})
            with self.assertRaises(ValueError):
                validate_exchange(request, wrong, job)
        wrong = result.model_copy(deep=True); wrong.evidence.provider.revision += 1
        with self.assertRaises(ValueError):
            validate_exchange(request, wrong, job)

    def test_group_exchange_detects_stale_reference(self):
        request = MODELS["group-request"].model_validate(load("group-request"))
        result = MODELS["group-result"].model_validate(load("group-partial-failure"))
        j = load("job-running"); j.update(state="completed", result_available=True, kind="group", job_id="job-group")
        job = MODELS["job"].model_validate(j)
        validate_exchange(request, result, job)
        wrong = result.model_copy(deep=True); wrong.group.reference_revision += 1
        with self.assertRaises(ValueError):
            validate_exchange(request, wrong, job)

    def test_recovery_has_no_implicit_retry(self):
        table = json.loads((ROOT / "job-transitions.json").read_text(encoding="utf-8"))
        for state, transitions in table.items():
            for event, destination in transitions.items():
                if "recover" in event:
                    self.assertNotEqual(destination, "running" if state != "running" else "queued")
        self.assertEqual(table["running"]["recover_untraceable"], "failed")
        self.assertEqual(table["cancelling"]["recover_untraceable"], "failed")

    def test_transition_traces(self):
        transitions = json.loads((ROOT / "job-transitions.json").read_text(encoding="utf-8"))
        cases = [(["recover", "dispatch", "finish"], "completed"),
                 (["cancel", "late_response"], "cancelled"),
                 (["dispatch", "cancel", "late_response"], "cancelled"),
                 (["dispatch", "recover_untraceable", "late_response"], "failed"),
                 (["dispatch", "recover_attached", "finish"], "completed"),
                 (["dispatch", "timeout", "late_response"], "failed"),
                 (["dispatch", "cancel", "recover_untraceable"], "failed")]
        for events, expected in cases:
            with self.subTest(events=events):
                state="queued"
                for event in events:
                    state=transitions[state][event]
                self.assertEqual(state, expected)
        for state in ["completed", "failed", "cancelled"]:
            self.assertTrue(all(end == state for end in transitions[state].values()))
            self.assertNotIn("dispatch", transitions[state])


if __name__ == "__main__":
    unittest.main(verbosity=2)
