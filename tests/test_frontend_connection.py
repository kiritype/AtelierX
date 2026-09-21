import base64
import json
from pathlib import Path
import tempfile
import time
import unittest

from aiohttp.test_utils import TestClient, TestServer
from cryptography.hazmat.primitives.asymmetric import rsa
import jwt

from atelierx.core import FRONTEND_CONNECTION, create_app
from atelierx.frontend_connection import FrontendConnection
from atelierx.common import ApiError


def _b64(value):
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode()


class FrontendConnectionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "frontend-connection.json"
        self.private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        public = self.private.public_key().public_numbers()
        self.kid = "fixture-key"
        self.config = {"public_origin": "https://atelier.cftm.net", "issuer": "https://cftmz.cloudflareaccess.com",
                       "audience": "frontend-audience", "allowed_emails": ["kiritype@gmail.com"], "core_token": "core-token"}
        self.path.write_text(json.dumps(self.config), encoding="utf-8")
        self.client = TestClient(TestServer(create_app(Path(self.temp.name) / "core.sqlite3", "http://generation.invalid", "core-token",
                                                        frontend_connection_path=self.path)))
        await self.client.start_server()
        connection = self.client.app[FRONTEND_CONNECTION]
        connection._keys = {self.kid: self.private.public_key()}
        connection._keys_at = time.monotonic()

    async def asyncTearDown(self):
        await self.client.close()
        self.temp.cleanup()

    def assertion(self, **claims):
        payload = {"iss": self.config["issuer"], "aud": self.config["audience"], "sub": "user-id", "email": "kiritype@gmail.com",
                   "iat": int(time.time()), "exp": int(time.time()) + 60, **claims}
        return jwt.encode(payload, self.private, algorithm="RS256", headers={"kid": self.kid})

    async def access(self, method="GET", path="/v1/frontend-connection", **extra):
        headers = {"Host": "atelier.cftm.net", "Cf-Access-Jwt-Assertion": self.assertion(), **extra.pop("headers", {})}
        return await self.client.request(method, path, headers=headers, **extra)

    async def test_access_status_does_not_expose_token_and_bearer_stays_compatible(self):
        response = await self.access()
        self.assertEqual(response.status, 200)
        body = await response.json()
        self.assertEqual(body, {"configured": True, "connected": True, "auth_mode": "cloudflare_access", "token_configured": True,
                                "public_origin": "https://atelier.cftm.net"})
        self.assertNotIn("core-token", json.dumps(body))
        response = await self.client.get("/v1/frontend-connection", headers={"Authorization": "Bearer core-token"})
        self.assertEqual(response.status, 200)
        self.assertEqual((await response.json())["auth_mode"], "bearer")

    async def test_invalid_bearer_never_falls_back_and_access_claims_are_verified(self):
        response = await self.access(headers={"Authorization": "Bearer wrong"})
        self.assertEqual(response.status, 401)
        for claims in ({"email": "other@example.com"}, {"aud": "other"}, {"iss": "https://other.cloudflareaccess.com"}, {"exp": int(time.time()) - 1}):
            response = await self.client.get("/v1/frontend-connection", headers={"Host": "atelier.cftm.net", "Cf-Access-Jwt-Assertion": self.assertion(**claims)})
            self.assertEqual(response.status, 403)
        forged = jwt.encode({"iss": self.config["issuer"], "aud": self.config["audience"], "sub": "user-id", "email": "kiritype@gmail.com",
                             "iat": int(time.time()), "exp": int(time.time()) + 60},
                            rsa.generate_private_key(public_exponent=65537, key_size=2048), algorithm="RS256", headers={"kid": self.kid})
        response = await self.client.get("/v1/frontend-connection", headers={"Host": "atelier.cftm.net", "Cf-Access-Jwt-Assertion": forged})
        self.assertEqual(response.status, 403)

    async def test_access_host_origin_and_token_save_are_strict_and_persistent(self):
        self.assertEqual((await self.client.get("/v1/frontend-connection", headers={"Cf-Access-Jwt-Assertion": self.assertion()})).status, 403)
        response = await self.access("PUT", json={"token": "core-token"}, headers={"Origin": "https://wrong.invalid"})
        self.assertEqual(response.status, 403)
        original = self.path.read_text(encoding="utf-8")
        response = await self.access("PUT", json={"token": "bad"}, headers={"Origin": self.config["public_origin"]})
        self.assertEqual(response.status, 400)
        self.assertEqual(self.path.read_text(encoding="utf-8"), original)
        response = await self.access("PUT", json={"token": "core-token"}, headers={"Origin": self.config["public_origin"]})
        self.assertEqual(response.status, 200)
        self.assertEqual(FrontendConnection(self.path, "core-token").status("bearer")["connected"], True)

    async def test_saved_token_mismatch_blocks_core_but_connection_can_repair_it(self):
        connection = self.client.app[FRONTEND_CONNECTION]
        connection.config = dict(connection.config, core_token="previous-core-token")
        self.assertEqual((await self.access(path="/health")).status, 401)
        status = await self.access()
        self.assertEqual(status.status, 200)
        self.assertFalse((await status.json())["connected"])
        repaired = await self.access("PUT", json={"token": "core-token"}, headers={"Origin": self.config["public_origin"]})
        self.assertEqual(repaired.status, 200)
        self.assertEqual((await self.access(path="/health")).status, 200)

    def test_jwks_config_rejects_unsafe_origins(self):
        for origin in ("http://example.test", "https://user@example.test", "https://example.test/path", "https://example.test\n"):
            bad = dict(self.config, public_origin=origin)
            with self.assertRaises(ValueError):
                FrontendConnection(self._write(bad), "core-token")

    async def test_jwks_is_bounded_and_network_failure_is_not_accepted(self):
        public = self.private.public_key().public_numbers()
        jwks = {"keys": [{"kid": self.kid, "kty": "RSA", "alg": "RS256", "n": _b64(public.n.to_bytes((public.n.bit_length() + 7) // 8, "big")),
                           "e": _b64(public.e.to_bytes((public.e.bit_length() + 7) // 8, "big"))}]}

        class Content:
            def __init__(self, value): self.value = value
            async def iter_chunked(self, size): yield self.value
        class Response:
            status = 200
            def __init__(self, value): self.content = Content(value)
            async def __aenter__(self): return self
            async def __aexit__(self, *args): pass
        class Session:
            def get(self, *args, **kwargs): return Response(json.dumps(jwks).encode())
        connection = FrontendConnection(self.path, "core-token")
        await connection._refresh_keys(Session())
        self.assertIn(self.kid, connection._keys)
        class BrokenSession:
            def get(self, *args, **kwargs): raise OSError("offline")
        with self.assertRaises(ApiError) as raised:
            await FrontendConnection(self.path, "core-token")._refresh_keys(BrokenSession())
        self.assertEqual((raised.exception.code, raised.exception.status), ("CORE_ACCESS_UNAVAILABLE", 503))

        class OversizedSession:
            def get(self, *args, **kwargs): return Response(b"x" * (128 * 1024 + 1))
        with self.assertRaises(ApiError) as raised:
            await FrontendConnection(self.path, "core-token")._refresh_keys(OversizedSession())
        self.assertEqual((raised.exception.code, raised.exception.status), ("CORE_ACCESS_UNAVAILABLE", 503))

    async def test_stale_key_is_never_accepted_after_refresh_failure_or_during_cooldown(self):
        connection = FrontendConnection(self.path, "core-token")
        connection._keys = {self.kid: self.private.public_key()}
        connection._keys_at = time.monotonic() - 301
        class BrokenSession:
            def get(self, *args, **kwargs): raise OSError("offline")
        with self.assertRaises(ApiError) as first:
            await connection._keys_for(BrokenSession(), self.kid)
        self.assertEqual(first.exception.status, 503)
        with self.assertRaises(ApiError) as second:
            await connection._keys_for(BrokenSession(), self.kid)
        self.assertEqual(second.exception.status, 503)

    def _write(self, value):
        path = Path(self.temp.name) / "unsafe.json"
        path.write_text(json.dumps(value), encoding="utf-8")
        return path
