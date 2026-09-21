import tempfile
import unittest
from pathlib import Path

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from atelierx.common import ApiError
from atelierx.core import create_app
from atelierx.validation_registry import RevisionRegistry


class SettingsRouteTests(unittest.IsolatedAsyncioTestCase):
    async def test_saved_revision_is_reported_when_sync_is_unavailable(self):
        async def unavailable(request):
            return web.json_response({"error": {"code": "VAL_UNAVAILABLE", "message": "Fixture offline"}}, status=503)
        backend = web.Application()
        backend.router.add_post("/v1/registry/snapshot", unavailable)
        with tempfile.TemporaryDirectory() as directory:
            async with TestServer(backend) as validation:
                app = create_app(Path(directory) / "core.db", "http://generation.invalid", "token",
                                 validation_config={"url": str(validation.make_url("/"))})
                async with TestClient(TestServer(app)) as client:
                    headers = {"Authorization": "Bearer token"}
                    path = "/v1/validation-settings/group-profiles"
                    body = {"profile_id": "identity", "revision": 1, "consistency": True}
                    response = await client.post(path, json=body, headers=headers)
                    result = await response.json()
                    self.assertEqual(response.status, 201, result)
                    self.assertEqual(result["synchronization"]["state"], "pending")
                    self.assertEqual(result["synchronization"]["error"]["code"], "VAL_UNAVAILABLE")
                    response = await client.get(path + "/identity", headers=headers)
                    self.assertEqual((await response.json())["revision"], 1)
                    response = await client.patch(path + "/identity", json={"revision": 1, "setting": None}, headers=headers)
                    self.assertEqual(response.status, 422, await response.text())
                    response = await client.post(path + "/identity/archive", json={"revision": 1}, headers=headers)
                    result = await response.json()
                    self.assertEqual((response.status, result["revision"], result["archived"]), (200, 2, True))
                    self.assertEqual(result["synchronization"]["state"], "pending")


class RegistryInputTests(unittest.TestCase):
    def test_credential_uses_configured_identity_and_endpoint_across_revisions(self):
        source = {"provider_id": "vision", "revision": 1, "model": "a", "timeout_seconds": 5,
                  "url": "http://provider.fixture/v1", "api_key": "server-only"}
        registry = RevisionRegistry({"vision": source})
        revised = {key: value for key, value in source.items() if key != "api_key"}
        revised.update(revision=2, model="b")
        registry.apply({"profiles": [], "providers": [revised]})
        self.assertEqual(registry.providers[("vision", 2)]["api_key"], "server-only")
        self.assertNotIn("server-only", str(registry.snapshot()))
        registry.apply({"profiles": [], "providers": [dict(revised, revision=3, url="http://other.fixture")]})
        self.assertEqual(registry.providers[("vision", 3)]["api_key"], "")

    def test_config_map_key_supplies_provider_identity_for_credential_resolution(self):
        configured = {"local-vision": {"revision": 5, "model": "8b", "timeout_seconds": 180,
                       "url": "http://127.0.0.1:1234", "api_key": "server-only"}}
        registry = RevisionRegistry(configured)
        registry.apply({"profiles": [], "providers": [{"provider_id": "local-vision", "revision": 6,
                         "model": "new-8b", "timeout_seconds": 180, "url": "http://127.0.0.1:1234"}]})
        self.assertEqual(registry.providers[("local-vision", 6)]["api_key"], "server-only")

    def test_invalid_identifier_is_contract_error_and_does_not_mutate_registry(self):
        registry = RevisionRegistry()
        for invalid_id in ([], {}, True, None):
            with self.assertRaises(ApiError) as caught:
                registry.apply({"profiles": [{"profile_id": invalid_id, "revision": 1, "consistency": True}], "providers": []})
            self.assertEqual(caught.exception.code, "VAL_REGISTRY_INVALID")
            self.assertEqual(registry.profiles, {})
