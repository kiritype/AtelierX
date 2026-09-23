import asyncio
import json
import socket
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from aiohttp.test_utils import TestClient, TestServer

from atelierx.control import deps, procs
from atelierx.control.config import ControlPaths
from atelierx.control.items import Item, OperationError, comfyui_args, comfyui_launch, lms_busy
from atelierx.control.panel import Panel
from atelierx.control.server import create_app
from atelierx.control.shortcut import StartupShortcut
from atelierx.launcher import run as pilot

ROOT = Path(__file__).resolve().parents[1]
SM_FIXTURE = {"InstalledPackages": [
    {"PackageName": "Other", "LibraryPath": "Packages\\Other", "LaunchArgs": []},
    {"PackageName": "ComfyUI", "LibraryPath": "Packages\\ComfyUI", "LaunchCommand": "main.py", "LaunchArgs": [
        {"Name": "--listen", "Type": "String", "OptionValue": "0.0.0.0"},
        {"Name": "--port", "Type": "String", "OptionValue": "9999"},
        {"Name": "--reserve-vram", "Type": "String", "OptionValue": "1.5"},
        {"Name": "--preview-method auto", "Type": "Bool", "OptionValue": True},
        {"Name": "--directml", "Type": "Bool", "OptionValue": False},
        {"Name": "--cpu", "Type": "Bool", "OptionValue": False},
        {"Name": "--use-pytorch-cross-attention", "Type": "Bool", "OptionValue": True},
        {"Name": "--disable-xformers", "Type": "Bool", "OptionValue": False},
        {"Name": "--enable-manager", "Type": "Bool", "OptionValue": True},
        {"Name": "", "Type": "String", "OptionValue": ""},
    ]}]}
SLEEPER = [sys.executable, "-c", "import time; time.sleep(60)"]


def free_port():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


class TempPanel:
    """Panel over a temporary repo root; every URL/port points at an unused loopback port."""
    def __init__(self, item_classes=None):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        dead = free_port()
        self.paths = ControlPaths(self.root, self.root / ".atelierx" / "control")
        self.paths.ensure()
        self.kwargs = dict(port=free_port(), urls={"core": f"http://127.0.0.1:{dead}", "comfyui": f"http://127.0.0.1:{dead}"},
                           ports={"services": dead, "comfyui": dead, "lmstudio": dead}, poll_interval=0.05, item_classes=item_classes)
        self.panel = Panel(self.paths, **self.kwargs)

    def reopen(self):
        self.panel = Panel(self.paths, **self.kwargs)
        return self.panel

    def close(self):
        asyncio.run(self.panel.close()) if self.panel.session else None
        self.directory.cleanup()


class ComfyArgumentTests(unittest.TestCase):
    def test_launch_args_from_stability_matrix_force_loopback(self):
        command, root = comfyui_launch(SM_FIXTURE, Path("C:/StabilityMatrix"))
        self.assertEqual(root, Path("C:/StabilityMatrix/Packages/ComfyUI"))
        self.assertEqual(command[0], str(root / "venv" / "Scripts" / "python.exe"))
        self.assertEqual(command[1:], ["main.py", "--reserve-vram", "1.5", "--preview-method", "auto", "--use-pytorch-cross-attention",
                                       "--enable-manager", "--listen", "127.0.0.1", "--port", "8188"])

    def test_empty_values_and_root_override(self):
        self.assertEqual(comfyui_args([{"Name": "--reserve-vram", "Type": "String", "OptionValue": ""}]), ["--listen", "127.0.0.1", "--port", "8188"])
        _, root = comfyui_launch(SM_FIXTURE, Path("C:/SM"), "D:/Comfy")
        self.assertEqual(root, Path("D:/Comfy"))
        with self.assertRaises(ValueError):
            comfyui_launch({"InstalledPackages": []}, Path("C:/SM"))


class DependencyHelperTests(unittest.TestCase):
    def test_node_scan_finds_repository_nodes(self):
        found = deps.expected_node_ids(ROOT / "custom_nodes")
        self.assertIn("AtelierXAnimaGenerate", found)
        self.assertIn("AtelierXUpscale", found)

    def test_combo_inputs_and_lms_rules(self):
        node = {"input": {"required": {"model": [["a.safetensors"]], "vae": ["COMBO", {"options": []}], "seed": ["INT", {}]}}}
        self.assertEqual(deps.empty_model_inputs(node), (2, ["vae"]))
        self.assertTrue(deps.lms_has_model([{"modelKey": "qwen"}], "qwen"))
        self.assertFalse(lms_busy([{"identifier": "m", "status": "idle", "queued": 0}]))
        self.assertTrue(lms_busy([{"identifier": "m", "status": "generating"}]))
        self.assertTrue(lms_busy(None))


class SecurityAndStatusTests(unittest.TestCase):
    def setUp(self):
        self.temp = TempPanel()
        self.panel = self.temp.panel
        self.token = self.temp.paths.read_token()
        self.panel.dependency_checks = mock.AsyncMock(return_value=[{"id": "tunnel_token", "label": "Tunnel token 파일", "status": "missing", "detail": "없음"}])
        self.shortcut_dir = self.temp.root / "startup"

    def tearDown(self):
        self.temp.close()

    def call(self, scenario):
        async def run():
            app = create_app(self.panel, self.token, StartupShortcut(self.temp.root, self.shortcut_dir))
            client = TestClient(TestServer(app, host="127.0.0.1", port=self.panel.port))
            await client.start_server()
            try:
                return await scenario(client, f"127.0.0.1:{self.panel.port}")
            finally:
                await client.close()
        return asyncio.run(run())

    def test_host_origin_and_header_rules(self):
        async def scenario(client, host):
            results = {}
            results["good"] = (await client.get("/api/status", headers={"Host": host})).status
            results["localhost"] = (await client.get("/api/status", headers={"Host": f"localhost:{self.panel.port}"})).status
            results["bad_host"] = (await client.get("/api/status", headers={"Host": "evil.example:80"})).status
            results["bad_host_page"] = (await client.get("/", headers={"Host": "evil.example"})).status
            body = {"autostart": {"tunnel": True}}
            results["no_header"] = (await client.put("/api/settings", json=body, headers={"Host": host})).status
            results["bad_origin"] = (await client.put("/api/settings", json=body, headers={"Host": host, "X-AtelierX-Control": "1", "Origin": "http://evil.example"})).status
            results["ok_origin"] = (await client.put("/api/settings", json=body, headers={"Host": host, "X-AtelierX-Control": "1", "Origin": f"http://{host}"})).status
            results["cors"] = (await client.get("/api/status", headers={"Host": host, "Origin": "http://evil.example"})).headers.get("Access-Control-Allow-Origin")
            return results
        results = self.call(scenario)
        self.assertEqual((results["good"], results["localhost"]), (200, 200))
        self.assertEqual((results["bad_host"], results["bad_host_page"]), (403, 403))
        self.assertEqual((results["no_header"], results["bad_origin"], results["ok_origin"]), (403, 403, 200))
        self.assertIsNone(results["cors"])
        self.assertTrue(json.loads(self.temp.paths.settings.read_text(encoding="utf-8"))["autostart"]["tunnel"])

    def test_core_status_requires_bearer_and_has_contract_shape(self):
        async def scenario(client, host):
            missing = (await client.get("/status", headers={"Host": host})).status
            wrong = (await client.get("/status", headers={"Host": host, "Authorization": "Bearer nope"})).status
            bad_host = (await client.get("/status", headers={"Host": "evil.example", "Authorization": "Bearer " + self.token})).status
            response = await client.get("/status", headers={"Host": host, "Authorization": "Bearer " + self.token})
            return missing, wrong, bad_host, response.status, await response.json()
        missing, wrong, bad_host, status, body = self.call(scenario)
        self.assertEqual((missing, wrong, bad_host, status), (401, 401, 403, 200))
        self.assertEqual(set(body), {"version", "generated_at", "items", "dependencies"})
        self.assertEqual(body["version"], 1)
        self.assertEqual([item["id"] for item in body["items"]], ["services", "comfyui", "lmstudio", "tunnel"])
        base = {"id", "label", "state", "managed", "pid", "started_at", "ports", "autostart", "last_error"}
        for item in body["items"]:
            self.assertEqual(set(item), base | ({"options"} if item["id"] == "services" else set()))
            self.assertIn(item["state"], {"running", "external", "stopped", "starting", "stopping", "error"})
        self.assertEqual(body["items"][0]["options"], {"generation": True, "validation": True, "discord_bridge": False})
        self.assertEqual(set(body["dependencies"][0]), {"id", "label", "status", "detail"})
        self.assertNotIn(self.token, json.dumps(body))

    def test_startup_shortcut_uses_injected_folder_only(self):
        (self.temp.root / "scripts").mkdir()
        (self.temp.root / "scripts" / "start_control_panel.bat").write_text("@echo off\r\n", encoding="ascii")
        async def scenario(client, host):
            headers = {"Host": host, "X-AtelierX-Control": "1"}
            created = await (await client.post("/api/startup-shortcut", headers=headers)).json()
            listed = await (await client.get("/api/startup-shortcut", headers={"Host": host})).json()
            removed = await (await client.delete("/api/startup-shortcut", headers=headers)).json()
            return created, listed, removed
        created, listed, removed = self.call(scenario)
        self.assertEqual((created["exists"], listed["exists"], removed["exists"]), (True, True, False))
        self.assertFalse((self.shortcut_dir / "AtelierX Control Panel.lnk").exists())


class ProcessRecordTests(unittest.TestCase):
    def setUp(self):
        self.temp = TempPanel()
        self.children = []

    def tearDown(self):
        for child in self.children:
            if child.poll() is None:
                child.kill()
                child.wait(10)
        self.temp.close()

    def spawn_managed(self, item):
        process, record = procs.spawn(SLEEPER, self.temp.root, self.temp.paths.logs / f"{item.id}-test.log")
        self.children.append(process)
        item.save_record(record)
        return process, record

    def test_adopt_keeps_matching_process_then_panel_stops_it(self):
        _, record = self.spawn_managed(self.temp.panel.items["comfyui"])
        self.assertEqual(json.loads(self.temp.paths.state.read_text(encoding="utf-8"))["items"]["comfyui"]["pid"], record["pid"])
        panel = self.temp.reopen()
        panel.adopt()
        item = panel.items["comfyui"]
        self.assertEqual(item.record["pid"], record["pid"])
        panel.observe()
        self.assertEqual((item.observed["state"], item.observed["managed"]), ("running", True))
        self.assertIsNone(asyncio.run(panel.run_op("comfyui", "stop")))
        self.assertFalse(procs.process_alive(record["pid"], record["create_time"]))
        self.assertIsNone(panel.store.get("comfyui"))

    def test_stale_or_mismatched_record_is_dropped_and_not_stopped(self):
        process, record = self.spawn_managed(self.temp.panel.items["services"])
        record = dict(record, command_line=record["command_line"] + " --other")
        self.temp.panel.store.set("services", record)
        panel = self.temp.reopen()
        panel.adopt()
        self.assertIsNone(panel.store.get("services"))
        error = asyncio.run(panel.run_op("services", "stop"))
        self.assertIn("제어판이 시작한", error)
        self.assertIsNone(process.poll())
        panel.store.set("lmstudio", None)
        panel.store.set("comfyui", {"pid": 999999, "exe": sys.executable, "command_line": "x", "create_time": 1})
        panel = self.temp.reopen()
        panel.adopt()
        self.assertIsNone(panel.store.get("comfyui"))

    def test_tunnel_pid_file_pointing_elsewhere_is_external_and_not_stopped(self):
        process = subprocess.Popen(SLEEPER, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.children.append(process)
        self.temp.paths.cloudflare.mkdir(parents=True)
        self.temp.paths.tunnel_pid.write_text(str(process.pid), encoding="ascii")
        panel = self.temp.panel
        panel.observe()
        self.assertEqual(panel.items["tunnel"].observed["state"], "external")
        error = asyncio.run(panel.run_op("tunnel", "stop"))
        self.assertIn("일치하지 않아", error)
        self.assertIsNone(process.poll())
        self.assertTrue(self.temp.paths.tunnel_pid.exists())

    def test_services_stop_uses_request_file_and_reports_refusal(self):
        panel = self.temp.panel
        item = panel.items["services"]
        item.stop_response_timeout = 5
        process, record = self.spawn_managed(item)
        files = pilot.StopRequestFiles(self.temp.paths.data)

        async def exchange():
            event = asyncio.Event()
            async def launcher():
                await pilot.wait_for_safe_stop(event, None, None, None, mock.Mock(), interval=0.05, stop_requests=files)
                process.kill()
            side = asyncio.ensure_future(launcher())
            error = await panel.run_op("services", "stop")
            if not side.done():
                side.cancel()
            await panel.close()
            return error

        with mock.patch.object(pilot, "service_status", return_value={"core_tasks": 3, "gpu_active": False}):
            error = asyncio.run(exchange())
        self.assertIn("core_tasks=3", error)
        self.assertEqual(item.active_work, {"core_tasks": 3, "gpu_active": False})
        self.assertIsNone(process.poll())
        with mock.patch.object(pilot, "service_status", return_value={"core_tasks": 0, "gpu_active": False}):
            error = asyncio.run(exchange())
        self.assertIsNone(error)
        self.assertIsNotNone(process.wait(10))
        self.assertIsNone(panel.store.get("services"))


class FakeItem(Item):
    events = []
    fail = set()

    def __init__(self, panel):
        super().__init__(panel)
        self.started = False

    async def is_ready(self):
        return self.started

    async def start(self):
        FakeItem.events.append(self.id)
        if self.id in FakeItem.fail:
            raise OperationError(self.id + " failed")
        self.started = True


def fake(item_id):
    return type("Fake_" + item_id, (FakeItem,), {"id": item_id, "label": item_id, "ready_timeout": 0.2})


class AutostartTests(unittest.TestCase):
    def setUp(self):
        FakeItem.events, FakeItem.fail = [], set()
        self.temp = TempPanel([fake(item) for item in ("services", "comfyui", "lmstudio", "tunnel")])
        self.panel = self.temp.panel
        self.panel.settings.update({"autostart": {"services": True, "comfyui": True, "lmstudio": False, "tunnel": True}})

    def tearDown(self):
        self.temp.close()

    def test_order_and_skip_unchecked(self):
        self.panel.items["tunnel"].started = True
        status = asyncio.run(self.panel.autostart())
        self.assertEqual(status["state"], "completed")
        self.assertEqual(FakeItem.events, ["comfyui", "services"])

    def test_failure_stops_later_stages(self):
        FakeItem.fail = {"comfyui"}
        status = asyncio.run(self.panel.autostart())
        self.assertEqual(status["state"], "failed")
        self.assertIn("comfyui failed", status["error"])
        self.assertEqual(FakeItem.events, ["comfyui"])
        self.assertEqual(self.panel.items["comfyui"].state(), "error")


if __name__ == "__main__": unittest.main()
