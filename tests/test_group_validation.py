import asyncio
import copy
import hashlib
import json
import tempfile
import unittest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from atelierx.validation import GROUP_EVALUATION_VERSION, create_app, SERVICE
from atelierx.group_validation import normalize, schema, summary
from atelierx.common import ApiError
from test_validation import PNG

PROFILE = {"profile_id": "group", "revision": 1, "consistency": True}
PROVIDER = {"provider_id": "v", "revision": 1, "model": "mock", "timeout_seconds": 2}

class GroupValidationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.calls = []
        self.mode = "matched"
        app = web.Application()
        async def vision(request):
            body = await request.json()
            self.calls.append(body)
            if getattr(self, "gate", None): await self.gate.wait()
            if self.mode == "partial" and len(self.calls) == 2:
                return web.json_response({"choices": [{"message": {"content": "bad"}}]})
            identity = {}
            roles = []
            for entry in body["messages"][1]["content"]:
                if entry.get("type") != "text":
                    continue
                if entry["text"].startswith("Shared identity: "):
                    identity = json.loads(entry["text"].split(": ", 1)[1])
                    continue
                try: value = json.loads(entry["text"])
                except (KeyError, TypeError, ValueError): continue
                if value.get("role") in {"reference", "target"}: roles.append(value)
            refs = [item["ref"] for item in roles if item["role"] == "reference"]
            compared = next(item["ref"] for item in roles if item["role"] == "target")
            reference_pair = compared.startswith("auxiliary")
            if self.mode == "reference_bad" and reference_pair:
                return web.json_response({"choices": [{"message": {"content": "bad"}}]})
            status = "matched" if self.mode == "partial" else self.mode
            if self.mode == "reference_conflict": status = "mismatch" if reference_pair else "matched"
            if self.mode == "reference_insufficient": status = "insufficient" if reference_pair else "matched"
            if self.mode == "all_pairs_conflict": status = "mismatch" if (refs, compared) == (["auxiliary-1"], "auxiliary-2") else "matched"
            if self.mode == "reference_timeout" and reference_pair:
                await asyncio.sleep(2)
            assessments = []
            for feature in identity:
                feature_status = status
                if self.mode in {"reference_conflict", "all_pairs_conflict"} and reference_pair and feature != "appearance":
                    feature_status = "matched"
                differences = [{"attribute": "hair_length", "description": "Different visible hair length"}] if feature_status == "mismatch" else []
                assessments.append({"feature": feature, "status": feature_status, "reference_observed": {ref: "Visible blue eyes" for ref in refs}, "target_observed": "Visible blue eyes", "differences": differences, "reference_refs": refs})
            data = {"assessments": assessments}
            choice = {"message": {"content": json.dumps(data)}}
            if self.mode == "length": choice["finish_reason"] = "length"
            return web.json_response({"choices": [choice], "usage": {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8, "unsafe": "ignored"}})
        app.router.add_post("/chat/completions", vision)
        self.provider = TestServer(app)
        await self.provider.start_server()
        self.config = {"v": dict(PROVIDER, url=str(self.provider.make_url("/")), api_key="local", response_format="json_schema", image_format="png")}
        self.client = TestClient(TestServer(create_app(self.tmp.name, "token", self.config, profiles={"group": PROFILE}, poll=.01)))
        await self.client.start_server()
        response = await self.client.post("/v1/uploads", data=PNG, headers={"Authorization": "Bearer token"})
        upload = await response.json()
        image = {"ref": "reference", "source": {"type": "upload", "upload_id": upload["upload_id"], "sha256": upload["sha256"]}, "positive_prompt": "blue eyes", "negative_prompt": ""}
        self.body = {"group_id": "group", "reference_revision": 1, "representative": image, "auxiliaries": [],
                     "targets": [dict(image, ref="target1"), dict(image, ref="target2")], "identity": {"appearance": "blue eyes"}, "profile": PROFILE, "provider": PROVIDER}

    async def asyncTearDown(self):
        await self.client.close()
        await self.provider.close()
        self.tmp.cleanup()

    async def submit(self, body=None, key="group-run"):
        response = await self.client.post("/v1/validations/group", json=body or self.body, headers={"Authorization": "Bearer token", "Idempotency-Key": key})
        return response.status, await response.json()

    async def wait(self, job):
        for _ in range(200):
            response = await self.client.get("/v1/validation-jobs/" + job["job_id"], headers={"Authorization": "Bearer token"})
            job = await response.json()
            if job["state"] in {"completed", "failed", "cancelled"}: return job
            await asyncio.sleep(.01)
        self.fail(str(job))

    async def test_partial_errors_preserve_results_and_idempotency(self):
        self.mode = "partial"
        status, job = await self.submit()
        self.assertEqual(status, 202)
        job = await self.wait(job)
        self.assertEqual(job["outcome"], "incomplete")
        self.assertEqual([i["status"] for i in job["result"]["items"]], ["matched", "error"])
        self.assertEqual((await self.submit())[0], 200)
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(sum(i["type"] == "image_url" for i in self.calls[0]["messages"][1]["content"]), 2)

    async def test_group_jobs_use_new_evaluation_version(self):
        _, job = await self.submit(key="group-version")
        self.assertEqual(GROUP_EVALUATION_VERSION, 9)
        self.assertEqual(job["evaluation_version"], GROUP_EVALUATION_VERSION)

    def with_auxiliaries(self, *refs):
        body = copy.deepcopy(self.body)
        body["auxiliaries"] = [dict(body["representative"], ref=ref) for ref in refs]
        return body

    async def test_reference_precheck_conflict_precedes_targets_and_survives_restart(self):
        self.mode = "reference_conflict"
        body = self.with_auxiliaries("auxiliary")
        body["identity"] = {"appearance": "blue eyes", "upper": "white shirt"}
        _, accepted = await self.submit(body, "reference-conflict")
        job = await self.wait(accepted)
        self.assertEqual((job["state"], job["outcome"], len(self.calls)), ("completed", "incomplete", 1))
        check = job["reference_checks"]['["reference","auxiliary"]']
        self.assertEqual((check["state"], check["status"]), ("completed", "mismatch"))
        self.assertEqual(check["evidence"][0]["differences"][0]["attribute"], "hair_length")
        self.assertTrue(all(item["status"] == "reference_conflict" and item["target_not_compared"] for item in job["result"]["items"]))
        self.assertTrue(all([assessment["status"] for assessment in item["evidence"]] == ["reference_conflict", "insufficient"] for item in job["result"]["items"]))
        self.assertTrue(all(item["evidence"][0]["reference_refs"] == ["reference", "auxiliary"] and item["evidence"][0]["target_observed"] == "Not compared due to reference conflict" for item in job["result"]["items"]))
        self.assertTrue(all(item["evidence"][1]["reference_refs"] == [] and item["evidence"][1]["target_observed"] == "Not compared due to reference conflict" for item in job["result"]["items"]))
        await self.client.close()
        self.client = TestClient(TestServer(create_app(self.tmp.name, "token", self.config, profiles={"group": PROFILE}, poll=.01)))
        await self.client.start_server()
        response = await self.client.get("/v1/validation-jobs/" + accepted["job_id"], headers={"Authorization": "Bearer token"})
        restored = await response.json()
        self.assertEqual(restored["reference_checks"], job["reference_checks"])
        self.assertEqual(len(self.calls), 1)

    async def test_every_reference_pair_is_checked_before_target_submission(self):
        self.mode = "all_pairs_conflict"
        _, accepted = await self.submit(self.with_auxiliaries("auxiliary-1", "auxiliary-2"), "all-reference-pairs")
        job = await self.wait(accepted)
        self.assertEqual(len(self.calls), 3)
        self.assertEqual(sorted(check["status"] for check in job["reference_checks"].values()), ["matched", "matched", "mismatch"])
        self.assertTrue(all(item["status"] == "reference_conflict" for item in job["result"]["items"]))

    async def test_insufficient_reference_precheck_does_not_create_a_conflict(self):
        self.mode = "reference_insufficient"
        _, accepted = await self.submit(self.with_auxiliaries("auxiliary"), "reference-insufficient")
        job = await self.wait(accepted)
        self.assertEqual((job["outcome"], len(self.calls)), ("passed", 3))
        self.assertEqual(job["reference_checks"]['["reference","auxiliary"]']["status"], "insufficient")
        self.assertTrue(all(item["status"] == "matched" for item in job["result"]["items"]))

    async def test_conflict_still_validates_target_access_before_assignment(self):
        self.mode = "reference_conflict"
        body = self.with_auxiliaries("auxiliary")
        body["targets"] = [dict(body["targets"][0], source=dict(body["targets"][0]["source"], sha256="0" * 64))]
        _, accepted = await self.submit(body, "conflict-invalid-target")
        job = await self.wait(accepted)
        self.assertEqual((len(self.calls), job["result"]["items"][0]["status"], job["result"]["items"][0]["error"]["code"]), (1, "error", "VAL_IMAGE_INTEGRITY"))

    async def test_reference_precheck_parse_error_becomes_target_error_not_a_pass(self):
        self.mode = "reference_bad"
        _, accepted = await self.submit(self.with_auxiliaries("auxiliary"), "reference-bad")
        job = await self.wait(accepted)
        self.assertEqual((job["state"], job["outcome"], len(self.calls)), ("completed", "incomplete", 1))
        self.assertTrue(all(item["status"] == "error" and item["error"]["code"] == "VAL_PROVIDER_RESPONSE_INVALID" for item in job["result"]["items"]))
        self.assertTrue(all(item["reference_precheck_errors"][0]["reference_refs"] == ["reference", "auxiliary"] for item in job["result"]["items"]))

    async def test_reference_timeout_stops_before_next_pair_or_target(self):
        self.mode = "reference_timeout"
        body = self.with_auxiliaries("auxiliary")
        body["provider"] = dict(PROVIDER, timeout_seconds=1)
        self.client.app[SERVICE].providers["v"]["timeout_seconds"] = 1
        _, accepted = await self.submit(body, "reference-timeout")
        job = await self.wait(accepted)
        self.assertEqual((job["state"], job["outcome"], job["error"]["code"], len(self.calls)), ("failed", "error", "VAL_PROVIDER_TIMEOUT", 1))
        self.assertEqual(job["reference_checks"]['["reference","auxiliary"]']["error"]["code"], "VAL_PROVIDER_TIMEOUT")

    async def test_cancelling_an_active_reference_precheck_stops_before_targets(self):
        self.gate = asyncio.Event()
        _, accepted = await self.submit(self.with_auxiliaries("auxiliary"), "cancel-reference-precheck")
        for _ in range(100):
            if self.calls:
                break
            await asyncio.sleep(.01)
        response = await self.client.post("/v1/validation-jobs/" + accepted["job_id"] + "/cancel", headers={"Authorization": "Bearer token"})
        self.assertEqual(response.status, 202)
        self.gate.set()
        job = await self.wait(accepted)
        self.assertEqual((job["state"], job["outcome"], job["result"], len(self.calls)), ("cancelled", None, None, 1))

    async def test_max_tokens_and_truncation_are_recorded_without_retry(self):
        service = self.client.app[SERVICE]
        service.providers["v"]["max_tokens"] = 1024
        body = copy.deepcopy(self.body); body["provider"] = dict(PROVIDER, max_tokens=1024)
        self.assertEqual((await self.submit(key="group-legacy-uncapped"))[0], 422)
        _, job = await self.submit(body, key="group-capped")
        job = await self.wait(job)
        self.assertEqual(self.calls[0]["max_tokens"], 1024)
        self.assertEqual(job["outcome"], "passed")
        self.mode = "length"
        _, job = await self.submit(body, key="group-truncated")
        job = await self.wait(job)
        self.assertEqual((job["state"], job["outcome"]), ("completed", "incomplete"))
        self.assertTrue(all(item["error"]["code"] == "VAL_PROVIDER_RESPONSE_INVALID" for item in job["result"]["items"]))
        self.assertTrue(all(value == {"finish_reason": "length", "usage": {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8}} for value in job["provider_responses"].values()))
        self.assertEqual(len(self.calls), 4)

    async def test_insufficient_is_not_pass_or_execution_error(self):
        self.mode = "insufficient"
        _, job = await self.submit()
        job = await self.wait(job)
        self.assertEqual((job["state"], job["outcome"], job["error"]), ("completed", "incomplete", None))
        self.assertEqual(job["result"]["summary"]["counts"]["insufficient"], 2)

    async def test_bad_source_and_invalid_scope(self):
        bad = copy.deepcopy(self.body)
        bad["targets"][0]["source"] = dict(bad["targets"][0]["source"], sha256="0" * 64)
        _, job = await self.submit(bad)
        job = await self.wait(job)
        self.assertEqual(job["result"]["items"][0]["error"]["code"], "VAL_IMAGE_INTEGRITY")
        self.assertEqual(job["result"]["items"][1]["status"], "matched")
        bad["targets"] = [bad["representative"]]
        self.assertEqual((await self.submit(bad, "bad"))[0], 400)

    async def test_cancel_active_stops_remaining_targets(self):
        self.gate = asyncio.Event()
        _, job = await self.submit()
        for _ in range(100):
            if self.calls: break
            await asyncio.sleep(.01)
        await self.client.post("/v1/validation-jobs/" + job["job_id"] + "/cancel", headers={"Authorization": "Bearer token"})
        self.gate.set()
        job = await self.wait(job)
        self.assertEqual(job["state"], "cancelled")
        self.assertEqual(len(self.calls), 1)
        self.assertIsNone(job["result"])

    def test_reference_conflicts_and_summary_do_not_vote(self):
        evidence = {"assessments": [{"feature": "appearance", "status": "reference_conflict", "reference_observed": {"r": "Short hair", "a": "Long hair"}, "target_observed": "Target is visible", "differences": [{"attribute": "hair_style", "description": "References differ"}], "reference_refs": ["r", "a"]}]}
        result = normalize(evidence, {"appearance": "blue eyes"}, {"r", "a"})
        self.assertEqual(result["status"], "reference_conflict")
        self.assertEqual(summary([dict(result, image_ref="t")])["state"], "incomplete")
        evidence["assessments"][0]["reference_refs"] = ["r"]
        with self.assertRaises(ApiError): normalize(evidence, {"appearance": "blue eyes"}, {"r", "a"})

    def test_recorded_difference_cannot_normalize_as_matched(self):
        evidence = {"assessments": [{"feature": "appearance", "status": "matched", "reference_observed": {"r": "Long silver hair"}, "target_observed": "Short silver hair", "differences": [{"attribute": "hair_length", "description": "Hair length differs"}], "reference_refs": ["r"]}]}
        with self.assertRaises(ApiError): normalize(evidence, {"appearance": "silver hair"}, {"r"})

    def test_allowed_variation_cannot_be_a_mismatch_difference(self):
        evidence = {"assessments": [{"feature": "appearance", "status": "mismatch", "reference_observed": {"r": "Thoughtful expression"}, "target_observed": "Calm smile", "differences": [{"attribute": "expression", "description": "Expression differs"}], "reference_refs": ["r"]}]}
        with self.assertRaises(ApiError): normalize(evidence, {"appearance": "silver hair"}, {"r"})

    def test_expression_pose_and_framing_variations_remain_matched_without_identity_difference(self):
        evidence = {"assessments": [{"feature": "appearance", "status": "matched",
                    "reference_observed": {"r": "Silver bob hair and blue eyes; thoughtful expression, hand near face, upper-body framing"},
                    "target_observed": "Silver bob hair and blue eyes; calm smile, arms lowered, closer upper-body framing",
                    "differences": [], "reference_refs": ["r"]}]}
        result = normalize(evidence, {"appearance": "silver hair, blue eyes"}, {"r"})
        self.assertEqual((result["status"], result["evidence"][0]["status"]), ("matched", "matched"))

    def test_clothing_change_is_a_typed_mismatch(self):
        evidence = {"assessments": [{"feature": "upper", "status": "mismatch",
                    "reference_observed": {"r": "White collared shirt"}, "target_observed": "Black hooded jacket",
                    "differences": [{"attribute": "clothing", "description": "White shirt changed to black hooded jacket"}],
                    "reference_refs": ["r"]}]}
        result = normalize(evidence, {"upper": "white shirt"}, {"r"})
        self.assertEqual(result["status"], "mismatch")
        self.assertEqual(result["evidence"][0]["differences"][0]["attribute"], "clothing")

    def test_occluded_clothing_is_insufficient_not_mismatch(self):
        evidence = {"assessments": [{"feature": "upper", "status": "insufficient",
                    "reference_observed": {"r": "White shirt partly visible"}, "target_observed": "Upper clothing fully hidden by foreground object",
                    "differences": [], "reference_refs": []}]}
        result = normalize(evidence, {"upper": "white shirt"}, {"r"})
        self.assertEqual((result["status"], result["evidence"][0]["status"]), ("insufficient", "insufficient"))

    def test_mismatch_without_typed_identity_evidence_is_rejected(self):
        evidence = {"assessments": [{"feature": "upper", "status": "mismatch",
                    "reference_observed": {"r": "White shirt"}, "target_observed": "Black jacket",
                    "differences": [], "reference_refs": ["r"]}]}
        with self.assertRaises(ApiError): normalize(evidence, {"upper": "white shirt"}, {"r"})

    def test_matched_requires_each_auxiliary_reference_and_individual_observation(self):
        evidence = {"assessments": [{"feature": "upper", "status": "matched",
                    "reference_observed": {"r": "White shirt"}, "target_observed": "White shirt", "differences": [], "reference_refs": ["r"]}]}
        with self.assertRaises(ApiError): normalize(evidence, {"upper": "white shirt"}, {"r", "a"})
        evidence["assessments"][0].update(reference_refs=["r", "a"], reference_observed={"r": "White shirt", "a": "Blue jacket"})
        result = normalize(evidence, {"upper": "white shirt"}, {"r", "a"})
        self.assertEqual(result["status"], "matched")

    def test_schema_constrains_reference_map_and_assessment_cardinality(self):
        result = schema({"appearance": "hair", "upper": "shirt"}, ["r", "a"])
        assessments = result["properties"]["assessments"]
        self.assertEqual((assessments["minItems"], assessments["maxItems"]), (2, 2))
        item = assessments["items"]["properties"]
        observed = item["reference_observed"]
        self.assertEqual((set(observed["properties"]), observed["required"], observed["additionalProperties"]), ({"r", "a"}, ["r", "a"], False))
        self.assertEqual((item["reference_refs"]["uniqueItems"], item["reference_refs"]["maxItems"]), (True, 2))

    def test_target_id_in_reference_observations_and_duplicate_refs_are_rejected(self):
        evidence = {"assessments": [{"feature": "upper", "status": "matched",
                    "reference_observed": {"r": "White shirt", "target": "Black jacket"}, "target_observed": "White shirt",
                    "differences": [], "reference_refs": ["r", "r"]}]}
        with self.assertRaises(ApiError): normalize(evidence, {"upper": "white shirt"}, {"r"})
