import json
import unittest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from atelierx.queue_api import attach_queue_api


class QueueTests(unittest.IsolatedAsyncioTestCase):
    async def test_pages_and_sse_reset_change_without_large_payload(self):
        rows = [{"id": "one", "state": "queued", "created_at": 1, "request": {"secret": "not-sent"}}]
        app = web.Application()
        attach_queue_api(app, lambda: rows)
        client = TestClient(TestServer(app))
        await client.start_server()
        try:
            response = await client.get("/v1/queue?limit=1")
            page = await response.json()
            self.assertEqual(page["total"], 1)
            self.assertNotIn("request", page["items"][0])
            self.assertEqual((await client.get("/v1/queue?limit=0")).status, 400)
            response = await client.get("/v1/events", headers={"Last-Event-ID": "older"})
            async def event():
                lines = []
                while True:
                    line = await response.content.readline()
                    if line == b"\n": return b"".join(lines).decode()
                    lines.append(line)
            self.assertIn("event: reset", await event())
            rows[0]["state"] = "cancelled"
            update = await event()
            self.assertIn("event: changed", update)
            self.assertIn("cancelled", update)
            self.assertNotIn("not-sent", update)
            response.close()
        finally:
            await client.close()
