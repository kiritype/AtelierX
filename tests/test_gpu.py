import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock
import aiohttp
from aiohttp import web
from aiohttp.test_utils import TestServer
from atelierx.core.store import Store
from atelierx.gpu import GpuCoordinator, permission


class GpuTests(unittest.IsolatedAsyncioTestCase):
    async def test_fifo_permission_survives_restart_and_no_wrong_owner_release(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "core.sqlite3"
            store = Store(path)
            gpu = GpuCoordinator(store, {"enabled": True})
            gpu.prepare = AsyncMock(return_value=(True, None))
            self.assertTrue((await gpu.acquire(None, "generation", "a"))["granted"])
            self.assertFalse((await gpu.acquire(None, "validation", "b"))["granted"])
            self.assertFalse((await gpu.acquire(None, "generation", "c"))["granted"])
            await gpu.release("validation", "other")
            self.assertEqual(gpu.state()["owner"]["job_id"], "a")
            store.close()
            store = Store(path)
            gpu = GpuCoordinator(store, {"enabled": True})
            gpu.prepare = AsyncMock(return_value=(True, None))
            self.assertTrue((await gpu.acquire(None, "generation", "a"))["granted"])
            gpu.prepare.assert_not_awaited()
            await gpu.release("generation", "a")
            self.assertFalse((await gpu.acquire(None, "generation", "c"))["granted"])
            self.assertTrue((await gpu.acquire(None, "validation", "b"))["granted"])
            await gpu.release("validation", "b")
            self.assertTrue((await gpu.acquire(None, "generation", "c"))["granted"])
            store.close()

    async def test_busy_runtime_does_not_grant_and_waiter_can_cancel(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory) / "core.sqlite3")
            gpu = GpuCoordinator(store, {"enabled": True})
            gpu.prepare = AsyncMock(return_value=(False, "busy"))
            self.assertFalse((await gpu.acquire(None, "generation", "a"))["granted"])
            self.assertIsNone(gpu.state()["owner"])
            await gpu.release("generation", "a")
            self.assertEqual(gpu.state()["waiting"], [])
            store.close()

    async def test_malformed_coordinator_acknowledgement_withholds_permission(self):
        malformed = web.Application()
        async def invalid_json(request):
            return web.Response(text="{", content_type="application/json")
        malformed.router.add_post("/v1/gpu/acquire", invalid_json)
        server = TestServer(malformed)
        await server.start_server()
        class Service:
            coordinator_url = str(server.make_url("/"))
            token = "token"
            def save(self, job): pass
        try:
            async with aiohttp.ClientSession() as session:
                service = Service(); service.session = session
                self.assertFalse(await permission(service, {"job_id": "bad-json"}, "generation"))
        finally:
            await server.close()

        non_object = web.Application()
        async def array_json(request):
            return web.json_response([])
        non_object.router.add_post("/v1/gpu/acquire", array_json)
        server = TestServer(non_object)
        await server.start_server()
        try:
            async with aiohttp.ClientSession() as session:
                service = Service(); service.coordinator_url = str(server.make_url("/")); service.session = session
                self.assertFalse(await permission(service, {"job_id": "array-json"}, "generation"))
        finally:
            await server.close()
