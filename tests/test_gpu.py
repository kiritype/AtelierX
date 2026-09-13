import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock
from atelierx.core_store import Store
from atelierx.gpu import GpuCoordinator


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
