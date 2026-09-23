import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from atelierx.launcher import run as pilot


class FakeLog:
    def __init__(self): self.entries = []
    def write(self, service, message): self.entries.append((service, str(message)))


IDLE = {"core_tasks": 0, "plans": 0, "gpu_active": False, "generation": 0}
BUSY = {"core_tasks": 2, "plans": 0, "gpu_active": True, "generation": 1}


class StopRequestProtocolTests(unittest.TestCase):
    def run_launcher(self, status, request, timeout=2):
        with tempfile.TemporaryDirectory() as directory:
            files = pilot.StopRequestFiles(directory)
            files.request.write_text(json.dumps(request) if isinstance(request, dict) else request, encoding="utf-8")
            logs, event = FakeLog(), asyncio.Event()
            async def scenario():
                task = asyncio.ensure_future(pilot.wait_for_safe_stop(event, None, None, None, logs, interval=0.02, stop_requests=files))
                try:
                    await asyncio.wait_for(asyncio.shield(task), timeout)
                    return True
                except asyncio.TimeoutError:
                    task.cancel()
                    return False
            with mock.patch.object(pilot, "service_status", return_value=dict(status)):
                stopped = asyncio.run(scenario())
            response = json.loads(files.response.read_text(encoding="utf-8"))
            self.assertFalse(files.request.exists())
            return stopped, response, logs

    def test_idle_request_is_accepted_and_echoes_request_id(self):
        stopped, response, _ = self.run_launcher(IDLE, {"request_id": "abc123"})
        self.assertTrue(stopped)
        self.assertEqual(response["request_id"], "abc123")
        self.assertTrue(response["accepted"])
        self.assertEqual(response["active_work"], IDLE)
        self.assertIn("at", response)

    def test_busy_request_is_refused_with_counts_and_keeps_running(self):
        stopped, response, logs = self.run_launcher(BUSY, {"request_id": "busy-1"}, timeout=0.3)
        self.assertFalse(stopped)
        self.assertEqual(response["request_id"], "busy-1")
        self.assertFalse(response["accepted"])
        self.assertEqual(response["active_work"]["core_tasks"], 2)
        self.assertTrue(any("refused" in message for _, message in logs.entries))

    def test_malformed_request_is_refused(self):
        stopped, response, _ = self.run_launcher(IDLE, "{not json", timeout=0.3)
        self.assertFalse(stopped)
        self.assertFalse(response["accepted"])
        self.assertIsNone(response["request_id"])

    def test_stale_request_is_discarded_at_startup(self):
        with tempfile.TemporaryDirectory() as directory:
            files = pilot.StopRequestFiles(directory)
            files.request.write_text('{"request_id": "old"}', encoding="utf-8")
            files.discard_stale()
            self.assertEqual(files.take(), (False, None, False))


class LauncherOptionTests(unittest.TestCase):
    def test_sigbreak_routes_to_same_stop_event(self):
        class Loop:
            def call_soon_threadsafe(self, callback): callback()
        class Signals:
            SIGINT, SIGBREAK = "INT", "BREAK"
            def __init__(self): self.handlers = {}
            def getsignal(self, number): return "previous-" + number
            def signal(self, number, handler): self.handlers[number] = handler
        signals, event = Signals(), asyncio.Event()
        previous = pilot.install_stop_signal(Loop(), event, signals)
        self.assertEqual(previous, {"INT": "previous-INT", "BREAK": "previous-BREAK"})
        signals.handlers["BREAK"]()
        self.assertTrue(event.is_set())
        pilot.restore_stop_signal(previous, signals)
        self.assertEqual(signals.handlers, {"INT": "previous-INT", "BREAK": "previous-BREAK"})

    def test_operations_status_passed_only_when_core_accepts_it(self):
        def old_core(db_path, generation_url, token, gpu_config=None): pass
        def new_core(db_path, generation_url, token, operations_status=None): pass
        self.assertEqual(pilot.operations_status_option(old_core, Path("C:/data/control")), {})
        option = pilot.operations_status_option(new_core, Path("C:/data/control"))
        self.assertEqual(option["operations_status"]["url"], "http://127.0.0.1:8180")
        self.assertEqual(Path(option["operations_status"]["token_file"]), Path("C:/data/control/token.txt"))

    def test_repo_root_resolves_to_repository(self):
        self.assertTrue((pilot.ROOT / "pyproject.toml").is_file())
        self.assertEqual(pilot.CONTROL_DIR, pilot.ROOT / ".atelierx" / "control")

    def test_cli_passes_service_toggles(self):
        captured = {}
        async def fake_run(*args, **kwargs): captured.update(kwargs)
        with mock.patch.object(pilot, "run", fake_run):
            self.assertEqual(pilot.main(["--no-generation", "--no-validation", "--control-dir", "X:/control"]), 0)
        self.assertFalse(captured["start_generation"])
        self.assertFalse(captured["start_validation"])
        self.assertEqual(captured["control_dir"], Path("X:/control"))


if __name__ == "__main__": unittest.main()
