from pathlib import Path
import tempfile
import unittest

from aiohttp.test_utils import TestClient, TestServer

from atelierx.core import create_app


class FrontendHostTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.client = TestClient(TestServer(create_app(Path(self.temp.name) / "core.sqlite3", "http://generation.invalid", "token", poll=60)))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()
        self.temp.cleanup()

    async def test_only_allowlisted_ui_assets_bypass_rest_authentication(self):
        for path, content_type in (("/ui/", "text/html"), ("/ui/api.js", "text/javascript"), ("/ui/app.js", "text/javascript"),
                                   ("/ui/production.js", "text/javascript"), ("/ui/gallery.js", "text/javascript"),
                                   ("/ui/jobs.js", "text/javascript"), ("/ui/settings.js", "text/javascript"), ("/ui/connection.js", "text/javascript"),
                                   ("/ui/fragments.js", "text/javascript"), ("/ui/fragment-picker.js", "text/javascript"),
                                   ("/ui/styles.css", "text/css")):
            response = await self.client.get(path)
            self.assertEqual(response.status, 200, path)
            self.assertIn(content_type, response.headers["Content-Type"])
            self.assertEqual(response.headers["Cache-Control"], "no-store")
            self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual((await self.client.get("/v1/settings")).status, 401)
        self.assertEqual((await self.client.get("/health")).status, 401)
        self.assertEqual((await self.client.get("/ui/core.py")).status, 404)
