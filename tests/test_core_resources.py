import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from atelierx.common import ApiError
from atelierx.core.resources import attach


class ResourcesTests(unittest.IsolatedAsyncioTestCase):
    async def test_proxy_is_read_only_and_old_generation_is_explicitly_unavailable(self):
        @web.middleware
        async def errors(request, handler):
            try:
                return await handler(request)
            except ApiError as error:
                return web.json_response({"error": str(error)}, status=503)

        core = SimpleNamespace(generation=AsyncMock(return_value={"family": "anima", "vaes": ["registered"]}))
        app = web.Application(middlewares=[errors])
        attach(app, core)
        async with TestClient(TestServer(app)) as client:
            response = await client.get("/v1/generation/resources")
            self.assertEqual((await response.json())["vaes"], ["registered"])
            self.assertEqual(response.headers["Cache-Control"], "no-store")
            core.generation.assert_awaited_once_with("GET", "/v1/resources")
            core.generation.return_value = None
            self.assertEqual((await client.get("/v1/generation/resources")).status, 503)
