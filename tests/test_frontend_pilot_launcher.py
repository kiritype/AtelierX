import asyncio
import importlib.util
import json
import socket
import sys
import tempfile
import unittest
from pathlib import Path
from aiohttp import web
from aiohttp.test_utils import TestServer


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from pilot_launcher import load_remote_config, redact_log, unavailable_ports  # noqa: E402
from atelierx.core import CORE, create_app as create_core_app  # noqa: E402
from atelierx.generation import SERVICE as GENERATION_SERVICE, create_app as create_generation_app  # noqa: E402
from atelierx.validation import SERVICE as VALIDATION_SERVICE, create_app as create_validation_app  # noqa: E402

spec = importlib.util.spec_from_file_location("run_frontend_pilot_test", ROOT / "scripts" / "run_frontend_pilot.py")
pilot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pilot)


class FakeLog:
    def __init__(self): self.entries = []
    def write(self, service, message): self.entries.append((service, message))


class FakeRunner:
    instances = []
    def __init__(self, app, access_log=None): self.app = app; self.access_log = access_log; self.setup_called = False; self.cleaned = False; FakeRunner.instances.append(self)
    async def setup(self): self.setup_called = True
    async def cleanup(self): self.cleaned = True


class FakeSite:
    fail_port = None
    def __init__(self, runner, host, port): self.port = port
    async def start(self):
        if self.port == self.fail_port: raise OSError("port fixture failure")


class FrontendPilotLauncherTests(unittest.TestCase):
    def setUp(self): FakeRunner.instances = []; FakeSite.fail_port = None

    def test_redaction_removes_prompt_token_and_query(self):
        self.assertIn("redacted prompt", redact_log('positive_prompt: private words'))
        self.assertNotIn("secret", redact_log("Authorization: Bearer secret"))
        self.assertEqual(redact_log("https://example.test/ui/?token=secret"), "https://example.test/ui/?[redacted]")

    def test_preflight_marks_bound_port_unavailable(self):
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM); listener.bind(("127.0.0.1", 0)); listener.listen()
        try: self.assertIn(listener.getsockname()[1], unavailable_ports((listener.getsockname()[1],)))
        finally: listener.close()

    def test_remote_backend_config_uses_environment_token_references(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "remote.json"
            path.write_text(json.dumps({"mode": "local", "generation_url": "https://generation.example.test", "generation_token_env": "GEN_TOKEN"}), encoding="utf-8")
            config = load_remote_config(path)
            self.assertEqual(config["generation_url"], "https://generation.example.test")
            self.assertEqual(config["generation_token_env"], "GEN_TOKEN")
            self.assertIsNone(config["validation_url"])
            path.write_text(json.dumps({"mode": "local", "generation_url": "https://generation.example.test/?token=secret", "generation_token_env": "GEN_TOKEN"}), encoding="utf-8")
            with self.assertRaises(ValueError): load_remote_config(path)

    def test_sigint_handler_sets_stop_event_without_cancelling_main_task(self):
        class Event:
            def __init__(self): self.set_called = False
            def set(self): self.set_called = True
        class Loop:
            def call_soon_threadsafe(self, callback): callback()
        class Signals:
            SIGINT = object()
            def __init__(self): self.handler = None
            def getsignal(self, _): return "previous"
            def signal(self, _, handler): self.handler = handler
        signals, event = Signals(), Event()
        self.assertEqual(pilot.install_stop_signal(Loop(), event, signals), "previous")
        signals.handler()
        self.assertTrue(event.set_called)

    def test_start_and_stop_uses_only_created_runners(self):
        logs = FakeLog()
        runners = asyncio.run(pilot.start_apps([("core", 8190), ("generation", 8189)], logs, FakeRunner, FakeSite))
        self.assertEqual([entry[0] for entry in logs.entries], ["core", "generation"])
        self.assertTrue(all(item.setup_called for item in runners))
        asyncio.run(pilot.stop_apps(runners))
        self.assertTrue(all(item.cleaned for item in runners))

    def test_start_error_cleans_already_created_runner(self):
        FakeSite.fail_port = 8189
        with self.assertRaises(OSError):
            asyncio.run(pilot.start_apps([("core", 8190), ("generation", 8189)], FakeLog(), FakeRunner, FakeSite))
        self.assertTrue(FakeRunner.instances[0].cleaned)
        self.assertTrue(FakeRunner.instances[1].cleaned)

    def test_real_isolated_apps_report_idle_status(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            core = create_core_app(root / "core.sqlite3", "http://127.0.0.1:8189", "test-token")
            generation = create_generation_app(root / "generation", "http://127.0.0.1:8188", "test-token")
            validation = create_validation_app(root / "validation", "test-token")
            try:
                self.assertTrue(all(value in (0, False) for value in pilot.service_status(core, generation, validation).values()))
            finally:
                core[CORE].store.close()
                generation[GENERATION_SERVICE].owner.close()
                validation[VALIDATION_SERVICE].owner.close()

    def test_remote_queue_parser_and_core_generation_token_wiring(self):
        self.assertEqual(pilot.remote_queue_count({"items": [{"state": "queued"}, {"state": "completed"}], "total": 2}, "generation"), (1, 2))
        with self.assertRaisesRegex(RuntimeError, "malformed"):
            pilot.remote_queue_count({"items": [{"state": 3}], "total": 1}, "generation")
        options = pilot.core_connection_options("remote-generation", {"url": "validation"}, "remote-validation", {"model": "x"}, None, None)
        self.assertEqual(options["generation_token"], "remote-generation")
        self.assertEqual(options["validation_token"], "remote-validation")

    def test_remote_queue_reads_all_pages_with_bearer_authentication(self):
        async def check():
            states = ["completed"] * 200 + ["queued"]
            async def queue(request):
                self.assertEqual(request.headers.get("Authorization"), "Bearer remote-token")
                limit, offset = int(request.query["limit"]), int(request.query["offset"])
                return web.json_response({"items": [{"state": state} for state in states[offset:offset + limit]], "total": len(states)})
            app = web.Application(); app.router.add_get("/v1/queue", queue)
            server = TestServer(app); await server.start_server()
            try: self.assertEqual(await pilot.remote_queue_status(str(server.make_url("/")).rstrip("/"), "remote-token", "generation"), 1)
            finally: await server.close()
        asyncio.run(check())


if __name__ == "__main__": unittest.main()
