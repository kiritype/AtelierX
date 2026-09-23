import asyncio
import json
import tempfile
import unittest
import base64
import io
from PIL import Image

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from atelierx.validation import SERVICE, create_app

PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGNgZGIGAAAOAAfXb+R4AAAAAElFTkSuQmCC")
PROFILE = {"profile_id":"default","revision":1,"output_conditions":True,"positive_prompt":True,"negative_prompt":True,"body_parts":[],"metadata":False,"consistency":False}
PROVIDER = {"provider_id":"vision","revision":1,"model":"mock-vlm","timeout_seconds":2}


class ValidationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.calls = 0; self.mode = "pass"; self.provider_bodies = []
        app = web.Application()
        async def completion(request):
            self.calls += 1
            if getattr(self, "provider_gate", None): await self.provider_gate.wait()
            self.provider_bodies.append(await request.json())
            if self.mode == "bad": return web.json_response({"choices":[{"message":{"content":"not json"}}]})
            if self.mode == "reject": return web.Response(status=401)
            checks = json.loads(self.provider_bodies[-1]["messages"][1]["content"][0]["text"].split(": ", 1)[1])
            first = {"fail": "mismatch", "not_assessable": "not_assessable"}.get(self.mode, "matched")
            verdict = {"assessments": [{"id": check["id"], "status": first if i == 0 else "matched",
                        "observed": "test visual observation", "location": "center"} for i, check in enumerate(checks)]}
            if getattr(self, "proposal", None) is not None:
                verdict["regeneration_changes"] = self.proposal
            choice = {"message":{"content":json.dumps(verdict)}}
            if self.mode == "length": choice["finish_reason"] = "length"
            return web.json_response({"choices":[choice], "usage":{"prompt_tokens":12,"completion_tokens":7,"total_tokens":19,"ignored":"secret"}})
        app.router.add_post("/chat/completions", completion); self.provider = TestServer(app); await self.provider.start_server()
        self.client = await self.new_client()

    async def new_client(self, providers=True):
        config = {"vision":{"url":str(self.provider.make_url("/")),"api_key":"not-in-response","model":"mock-vlm","revision":1,"timeout_seconds":2}} if providers else {}
        client = TestClient(TestServer(create_app(self.tmp.name, "token", config, profiles={"default": PROFILE}, poll=.01))); await client.start_server(); return client

    async def asyncTearDown(self):
        await self.client.close(); await self.provider.close(); self.tmp.cleanup()

    async def upload(self, value=PNG):
        response = await self.client.post("/v1/uploads", data=value, headers={"Authorization":"Bearer token"})
        return response.status, await response.json()

    async def post(self, source, key="one"):
        body = {"image":{"ref":"image","source":source,"positive_prompt":"adult woman","negative_prompt":"text"},"generation_attempt_id":"attempt","profile":PROFILE,"provider":PROVIDER,"expected_output":{"width":1,"height":1,"media_type":"image/png","alpha":"not_required"},"generation_settings":None}
        return await self.client.post("/v1/validations/single", json=body, headers={"Authorization":"Bearer token","Idempotency-Key":key})

    async def wait(self, job_id):
        for _ in range(100):
            response = await self.client.get("/v1/validation-jobs/" + job_id, headers={"Authorization":"Bearer token"}); job = await response.json()
            if job["state"] in {"completed","failed"}: return job
            await asyncio.sleep(.01)
        self.fail("job did not finish")

    async def test_upload_pass_idempotency_and_restart(self):
        status, upload = await self.upload(); self.assertEqual(status, 201)
        source = {"type":"upload","upload_id":upload["upload_id"],"sha256":upload["sha256"]}
        responses = await asyncio.gather(*(self.post(source) for _ in range(4)))
        self.assertEqual(sorted(r.status for r in responses), [200,200,200,202])
        job = await self.wait((await responses[0].json())["job_id"])
        self.assertEqual((job["outcome"], job["error"]), ("passed", None)); self.assertEqual(self.calls, 1)
        self.assertIn("adult woman", self.provider_bodies[0]["messages"][1]["content"][0]["text"])
        await self.client.close(); self.client = await self.new_client()
        again = await self.post(source); self.assertEqual(again.status, 200); self.assertEqual(self.calls, 1)

    async def test_failed_and_provider_errors_are_explicit_no_retry(self):
        _, upload = await self.upload(); source = {"type":"upload","upload_id":upload["upload_id"],"sha256":upload["sha256"]}
        self.mode = "fail"; job = await self.wait((await (await self.post(source, "failed")).json())["job_id"])
        self.assertEqual((job["outcome"], job["result"]["regeneration"]["required"]), ("failed", True))
        self.mode = "bad"; job = await self.wait((await (await self.post(source, "bad")).json())["job_id"])
        self.assertEqual((job["outcome"], job["error"]["code"]), ("error", "VAL_PROVIDER_RESPONSE_INVALID")); calls = self.calls
        await asyncio.sleep(.05); self.assertEqual(self.calls, calls)

    async def test_max_tokens_is_optional_and_length_completion_is_an_error(self):
        _, upload = await self.upload(); source = {"type":"upload","upload_id":upload["upload_id"],"sha256":upload["sha256"]}
        self.client.app[SERVICE].providers["vision"]["max_tokens"] = 1024
        bounded = self.body(upload); bounded["provider"] = dict(PROVIDER, max_tokens=1024)
        self.assertEqual((await self.submit_body(self.body(upload), "legacy-uncapped"))[0], 422)
        _, job = await self.submit_body(bounded, "capped")
        result = await self.wait(job["job_id"])
        self.assertEqual(result["outcome"], "passed")
        self.assertEqual(self.provider_bodies[-1]["max_tokens"], 1024)
        self.mode = "length"
        _, job = await self.submit_body(bounded, "truncated")
        result = await self.wait(job["job_id"])
        self.assertEqual((result["outcome"], result["error"]["code"]), ("error", "VAL_PROVIDER_RESPONSE_INVALID"))
        self.assertEqual(result["provider_response"], {"finish_reason":"length", "usage":{"prompt_tokens":12,"completion_tokens":7,"total_tokens":19}})
        calls = self.calls; await asyncio.sleep(.05); self.assertEqual(self.calls, calls)

    async def test_auth_input_integrity_and_unconfigured_provider(self):
        self.assertEqual((await self.client.get("/health")).status, 401)
        self.assertEqual((await self.upload(b"bad"))[0], 422)
        _, upload = await self.upload(); source = {"type":"upload","upload_id":upload["upload_id"],"sha256":"0" * 64}
        self.assertEqual((await self.post(source, "bad-hash")).status, 202)
        job = await self.wait((await (await self.post(source, "bad-hash")).json())["job_id"]); self.assertEqual(job["error"]["code"], "VAL_IMAGE_INTEGRITY")
        await self.client.close(); self.client = await self.new_client(False)
        source["sha256"] = upload["sha256"]; response = await self.post(source, "none"); self.assertEqual(response.status, 422)

    async def test_recovered_running_job_never_reposts_provider(self):
        _, upload = await self.upload(); source = {"type":"upload","upload_id":upload["upload_id"],"sha256":upload["sha256"]}
        service = self.client.server.app[SERVICE]
        job, _ = await service.submit("recovery", {"image":{"ref":"image","source":source,"positive_prompt":"adult woman","negative_prompt":"text"},"generation_attempt_id":"attempt","profile":PROFILE,"provider":PROVIDER,"expected_output":{"width":1,"height":1,"media_type":"image/png","alpha":"not_required"},"generation_settings":None})
        job["state"] = "running"; service.save(job)
        await service.run(job)
        self.assertEqual(job["error"]["code"], "VAL_PROVIDER_ACCEPTANCE_UNKNOWN")
        self.assertEqual(self.calls, 0)

    def body(self, upload, profile=None, expected=None):
        return {"image": {"ref": "image", "source": {"type": "upload", "upload_id": upload["upload_id"], "sha256": upload["sha256"]},
                          "positive_prompt": "adult woman", "negative_prompt": "PRIVATE-DISABLED-CONTENT"},
                "generation_attempt_id": "attempt", "profile": profile or PROFILE, "provider": PROVIDER,
                "expected_output": expected or {"width": 1, "height": 1, "media_type": "image/png", "alpha": "not_required"},
                "generation_settings": None}

    async def submit_body(self, body, key):
        response = await self.client.post("/v1/validations/single", json=body,
            headers={"Authorization": "Bearer token", "Idempotency-Key": key})
        return response.status, await response.json()

    async def test_output_failure_and_profile_flags(self):
        _, upload = await self.upload()
        status, job = await self.submit_body(self.body(upload, expected={"width": 2, "height": 1, "media_type": "image/png", "alpha": "not_required"}), "wrong-size")
        self.assertEqual(status, 202)
        result = await self.wait(job["job_id"])
        self.assertEqual((result["state"], result["outcome"], result["error"], self.calls), ("completed", "failed", None, 0))
        profile = dict(PROFILE, negative_prompt=False)
        self.client.app[SERVICE].profiles["default"] = profile
        _, job = await self.submit_body(self.body(upload, profile), "disabled-negative")
        self.assertEqual((await self.wait(job["job_id"]))["outcome"], "passed")
        self.assertNotIn("PRIVATE-DISABLED-CONTENT", json.dumps(self.provider_bodies))
        profile = dict(profile, positive_prompt=False)
        self.client.app[SERVICE].profiles["default"] = profile
        _, job = await self.submit_body(self.body(upload, profile), "local-only")
        self.assertEqual((await self.wait(job["job_id"]))["outcome"], "passed")
        self.assertEqual(self.calls, 1)

    async def test_transparency_decode_and_unsafe_inputs(self):
        service = self.client.app[SERVICE]
        image = Image.new("P", (1, 1), 0)
        buffer = io.BytesIO(); image.save(buffer, format="PNG", transparency=0)
        self.assertEqual(service.decode_image(buffer.getvalue())[-2:], (True, True))
        opaque_upload = None
        for format, media_type in (("PNG", "image/png"), ("WEBP", "image/webp")):
            for alpha, expected_outcome in ((0, "passed"), (255, "failed")):
                data = io.BytesIO()
                kwargs = {"format": format}
                if format == "WEBP": kwargs["lossless"] = True
                Image.new("RGBA", (1, 1), (10, 20, 30, alpha)).save(data, **kwargs)
                _, upload = await self.upload(data.getvalue())
                if alpha == 255: opaque_upload = upload
                _, job = await self.submit_body(self.body(upload, expected={
                    "width": 1, "height": 1, "media_type": media_type, "alpha": "transparency_required"}),
                    f"{format.lower()}-{alpha}")
                self.assertEqual((await self.wait(job["job_id"]))["outcome"], expected_outcome)

        # A profile that opts out of output conditions keeps that opt-out even
        # when the request records an alpha requirement.
        disabled_output = dict(PROFILE, output_conditions=False)
        service.profiles["default"] = disabled_output
        _, job = await self.submit_body(self.body(opaque_upload, disabled_output, {
            "width": 1, "height": 1, "media_type": "image/webp", "alpha": "transparency_required"}), "output-opt-out")
        self.assertEqual((await self.wait(job["job_id"]))["outcome"], "passed")
        body = self.body(opaque_upload); body["image"]["source"]["upload_id"] = "../outside"
        self.assertEqual((await self.submit_body(body, "unsafe"))[0], 400)
        body = self.body(opaque_upload); body["provider"]["url"] = "http://untrusted.invalid"
        self.assertEqual((await self.submit_body(body, "unknown-field"))[0], 400)
        PROVIDER.pop("url", None)
        self.assertEqual((await self.upload(PNG[:-10]))[0], 422)
        self.assertEqual(self.calls, 3)

    async def test_queued_provider_change_rejected_and_old_key_still_returns(self):
        _, upload = await self.upload()
        service = self.client.app[SERVICE]
        job, _ = await service.submit("config-change", self.body(upload))
        service.providers["vision"]["url"] = "http://127.0.0.1:1"
        await service.run(job)
        self.assertEqual(job["error"]["code"], "VAL_PROVIDER_CONFIG_CHANGED")
        service.providers["vision"]["revision"] = 2
        same, created = await service.submit("config-change", self.body(upload))
        self.assertFalse(created)
        self.assertEqual(same["job_id"], job["job_id"])
        self.assertEqual(self.calls, 0)

    async def test_lmstudio_structured_format_and_rejection_no_fallback(self):
        service = self.client.app[SERVICE]
        service.providers["vision"]["response_format"] = "json_schema"
        _, upload = await self.upload()
        _, job = await self.submit_body(self.body(upload), "schema")
        self.assertEqual((await self.wait(job["job_id"]))["outcome"], "passed")
        response_format = self.provider_bodies[0]["response_format"]
        self.assertEqual(response_format["type"], "json_schema")
        self.assertTrue(response_format["json_schema"]["strict"])
        self.assertEqual(response_format["json_schema"]["schema"]["required"], ["assessments"])
        self.mode = "reject"
        _, job = await self.submit_body(self.body(upload), "rejected")
        result = await self.wait(job["job_id"])
        self.assertEqual(result["error"]["code"], "VAL_PROVIDER_REJECTED")
        self.assertIn("401", result["error"]["message"])
        await asyncio.sleep(.04)
        self.assertEqual(self.calls, 2)
        self.assertTrue(all(body["response_format"]["type"] == "json_schema" for body in self.provider_bodies))

    async def test_webp_provider_conversion_preserves_source_and_pixels(self):
        service = self.client.app[SERVICE]
        service.providers["vision"]["image_format"] = "png"
        original = Image.new("RGBA", (2, 1), (15, 85, 155, 128))
        buffer = io.BytesIO(); original.save(buffer, format="WEBP", lossless=True)
        data = buffer.getvalue()
        _, upload = await self.upload(data)
        expected = {"width": 2, "height": 1, "media_type": "image/webp", "alpha": "transparency_required"}
        _, submitted = await self.submit_body(self.body(upload, expected=expected), "webp-png")
        job = await self.wait(submitted["job_id"])
        self.assertEqual(job["outcome"], "passed")
        self.assertEqual(job["request"]["expected_output"], expected)
        self.assertEqual(job["provider_image"]["source_sha256"], upload["sha256"])
        url = self.provider_bodies[-1]["messages"][1]["content"][1]["image_url"]["url"]
        self.assertTrue(url.startswith("data:image/png;base64,"))
        decoded = Image.open(io.BytesIO(base64.b64decode(url.split(",", 1)[1])))
        self.assertEqual(decoded.convert("RGBA").tobytes(), original.tobytes())
        self.assertEqual(self.calls, 1)
        # Format changes invalidate queued snapshots rather than silently changing transport.
        queued, _ = await service.submit("webp-config-change", self.body(upload, expected=expected))
        service.providers["vision"]["image_format"] = "original"
        await service.run(queued)
        self.assertEqual(queued["error"]["code"], "VAL_PROVIDER_CONFIG_CHANGED")
        self.assertEqual(self.calls, 1)

    async def test_negative_sources_only_character_sent_and_mismatch_rejected(self):
        _, upload = await self.upload()
        body = self.body(upload)
        body["image"].update(negative_prompt="low quality, glasses, beard", negative_sources={"global": "low quality, glasses", "character": "beard"})
        _, job = await self.submit_body(body, "negative-sources")
        result = await self.wait(job["job_id"])
        self.assertEqual(result["outcome"], "passed")
        sent = self.provider_bodies[-1]["messages"][1]["content"][0]["text"]
        self.assertIn("beard", sent)
        self.assertNotIn("low quality", sent)
        self.assertNotIn("glasses", sent)
        body["image"]["negative_sources"]["character"] = "hat"
        self.assertEqual((await self.submit_body(body, "tampered"))[0], 400)

    async def test_cancel_queued_job_never_calls_provider_and_queue_pages(self):
        from unittest.mock import AsyncMock
        _, upload = await self.upload()
        service = self.client.app[SERVICE]
        service.run = AsyncMock()
        job, _ = await service.submit("cancelled", self.body(upload))
        response = await self.client.post("/v1/validation-jobs/" + job["job_id"] + "/cancel", headers={"Authorization": "Bearer token"})
        self.assertEqual((await response.json())["state"], "cancelled")
        await asyncio.sleep(.03)
        self.assertEqual(self.calls, 0)
        response = await self.client.get("/v1/queue?state=cancelled&limit=1", headers={"Authorization": "Bearer token"})
        self.assertEqual((await response.json())["total"], 1)


    async def test_running_cancellation_discards_late_provider_result(self):
        self.provider_gate = asyncio.Event()
        _, upload = await self.upload()
        _, job = await self.submit_body(self.body(upload), "cancel-running")
        for _ in range(100):
            if self.calls: break
            await asyncio.sleep(.01)
        self.assertEqual(self.calls, 1)
        response = await self.client.post("/v1/validation-jobs/" + job["job_id"] + "/cancel", headers={"Authorization": "Bearer token"})
        self.assertEqual(response.status, 202)
        self.assertTrue((await response.json())["cancel_requested"])
        self.provider_gate.set()
        for _ in range(100):
            result = self.client.app[SERVICE].jobs[job["job_id"]]
            if result["state"] == "cancelled": break
            await asyncio.sleep(.01)
        self.assertEqual(result["state"], "cancelled")
        self.assertIsNone(result["outcome"])
        self.assertIsNone(result["result"])
        self.assertEqual(result["late_result"]["outcome"], "passed")

    async def test_positive_check_contract_fingerprint_and_not_assessable(self):
        _, upload = await self.upload()
        service = self.client.app[SERVICE]
        check = [{"text": "silver hair", "source": "character_features"}, {"text": "black boots", "source": "outfit_lower"}]
        for bad in ([], [{"text": "x", "source": "quality"}], [{"text": "", "source": "fragment"}],
                    [{"text": "x" * 4001, "source": "fragment"}], [{"text": "x", "source": "fragment", "extra": 1}], "x"):
            body = self.body(upload); body["image"]["positive_check"] = bad
            self.assertEqual((await self.submit_body(body, "bad-check"))[0], 400)
        legacy = self.body(upload)
        scoped = self.body(upload); scoped["image"]["positive_check"] = check
        self.assertEqual((await self.submit_body(legacy, "scope-key"))[0], 202)
        self.assertEqual((await self.submit_body(scoped, "scope-key"))[0], 409)
        self.mode = "not_assessable"
        status, job = await self.submit_body(scoped, "scoped")
        self.assertEqual(status, 202)
        result = await self.wait(job["job_id"])
        self.assertEqual(result["evaluation_version"], 6)
        self.assertEqual(result["outcome"], "passed")
        self.assertEqual(result["result"]["not_assessable"], [{"prompt_excerpt": "silver hair", "source": "character_features", "observed": "test visual observation"}])
        content = self.provider_bodies[-1]["messages"][1]["content"]
        listed = json.loads(content[0]["text"].split(": ", 1)[1])
        self.assertEqual([item["requirement"] for item in listed if item["kind"] == "positive"], ["silver hair", "black boots"])
        self.assertIn("adult woman", content[-1]["text"])
        self.assertIn("not_assessable", self.provider_bodies[-1]["messages"][0]["content"])
        self.assertEqual(len(service.jobs), 2)

    async def test_invalid_regeneration_proposal_is_dropped_but_failure_kept(self):
        _, upload = await self.upload()
        body = self.body(upload); body["generation_settings"] = {"seed": 1, "steps": 24, "cfg": 4.5}
        self.mode = "fail"
        self.proposal = [{"field": "steps", "value": 500, "reason": "more detail", "evidence_ids": ["positive-1"]}]
        _, job = await self.submit_body(body, "bad-proposal")
        result = await self.wait(job["job_id"])
        self.assertEqual((result["state"], result["outcome"], result["error"]), ("completed", "failed", None))
        self.assertEqual(result["result"]["regeneration"]["changes"], [])
        self.assertIn("steps is out of range", result["result"]["diagnostics"]["regeneration_proposal_dropped"])
        self.assertIn("proposal_unavailable_reason", result["result"]["regeneration"])
        self.proposal = [{"field": "steps", "value": 30, "reason": "more detail", "evidence_ids": ["positive-1"]}]
        _, job = await self.submit_body(body, "good-proposal")
        result = await self.wait(job["job_id"])
        self.assertEqual(result["result"]["regeneration"]["changes"], self.proposal)
        self.assertNotIn("diagnostics", result["result"])
        self.proposal = None; self.mode = "bad"
        _, job = await self.submit_body(body, "bad-judgment")
        self.assertEqual((await self.wait(job["job_id"]))["error"]["code"], "VAL_PROVIDER_RESPONSE_INVALID")

if __name__ == "__main__": unittest.main()
