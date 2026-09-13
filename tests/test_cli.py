import io
import json
import tempfile
import unittest
from pathlib import Path
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

from atelierx.common import ApiError
from atelierx import cli


class FakeCoreClient:
    instances = []
    failure = None
    payload = None

    def __init__(self, base_url, token, timeout=30):
        self.base_url, self.token, self.timeout, self.calls = base_url, token, timeout, []
        self.__class__.instances.append(self)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return None

    async def _call(self, name, *args, **kwargs):
        self.calls.append((name, args, kwargs))
        if self.__class__.failure is not None:
            raise self.__class__.failure
        if self.__class__.payload is not None:
            return self.__class__.payload
        return {"method": name, "args": list(args), "filters": kwargs}

    async def health(self): return await self._call("health")
    async def queue(self, **filters): return await self._call("queue", **filters)
    async def get_settings(self): return await self._call("get_settings")
    async def update_settings(self, body): return await self._call("update_settings", body)
    async def list_groups(self, **filters): return await self._call("list_groups", **filters)
    async def get_group(self, ident): return await self._call("get_group", ident)
    async def list_images(self, **filters): return await self._call("list_images", **filters)
    async def get_image(self, ident): return await self._call("get_image", ident)
    async def list_tasks(self, **filters): return await self._call("list_tasks", **filters)
    async def get_task(self, ident): return await self._call("get_task", ident)
    async def list_group_batches(self, **filters): return await self._call("list_group_batches", **filters)
    async def get_group_batch(self, ident): return await self._call("get_group_batch", ident)
    async def create_group_batch(self, group_id, body, key): return await self._call("create_group_batch", group_id, body, key)
    async def cancel_group_batch(self, ident): return await self._call("cancel_group_batch", ident)
    async def confirm_group_batch_reference(self, ident, body, key): return await self._call("confirm_group_batch_reference", ident, body, key)
    async def preview_prompt(self, body): return await self._call("preview_prompt", body)
    async def create_task(self, body, key): return await self._call("create_task", body, key)
    async def get_task_by_key(self, key): return await self._call("get_task_by_key", key)
    async def validate_image(self, ident, body, key): return await self._call("validate_image", ident, body, key)
    async def regenerate_task(self, ident, body, key): return await self._call("regenerate_task", ident, body, key)
    async def cancel_task(self, ident): return await self._call("cancel_task", ident)
    async def get_validation_run(self, ident): return await self._call("get_validation_run", ident)
    async def cancel_validation(self, ident): return await self._call("cancel_validation", ident)
    async def list_task_attempts(self, ident, **filters): return await self._call("list_task_attempts", ident, **filters)
    async def get_cycle(self, ident): return await self._call("get_cycle", ident)
    async def stop_cycle(self, ident): return await self._call("stop_cycle", ident)


class CliTests(unittest.TestCase):
    def setUp(self):
        FakeCoreClient.instances, FakeCoreClient.failure, FakeCoreClient.payload = [], None, None

    def invoke(self, argv, environment={"ATELIERX_CORE_TOKEN": "token"}, stdin=None):
        output, errors = io.StringIO(), io.StringIO()
        with patch("atelierx.cli.CoreClient", FakeCoreClient), redirect_stdout(output), redirect_stderr(errors):
            code = cli.main(argv, environment, stdin)
        return code, output.getvalue(), errors.getvalue()

    def json_file(self, value):
        handle = tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", suffix=".json", delete=False)
        self.addCleanup(lambda: Path(handle.name).unlink(missing_ok=True))
        with handle:
            json.dump(value, handle)
        return handle.name

    def test_read_only_list_commands_forward_api_filters(self):
        cases = [
            (["--core-url", "http://127.0.0.1:8190", "groups", "list", "--work-id", "work", "--limit", "1"], "list_groups", {"work_id": "work", "limit": 1}),
            (["images", "list", "--group-id", "group", "--media-type", "image/png", "--offset", "2"], "list_images", {"group_id": "group", "media_type": "image/png", "offset": 2}),
            (["tasks", "list", "--state", "generated", "--outfit-id", "outfit"], "list_tasks", {"state": "generated", "outfit_id": "outfit"}),
            (["group-batches", "list", "--group-id", "group", "--state", "creating"], "list_group_batches", {"group_id": "group", "state": "creating"}),
            (["queue", "--state", "running", "--limit", "50"], "queue", {"state": "running", "limit": 50}),
        ]
        for argv, method, filters in cases:
            with self.subTest(argv=argv):
                code, output, errors = self.invoke(argv)
                self.assertEqual((code, errors), (0, ""))
                self.assertEqual(json.loads(output)["method"], method)
                self.assertEqual(FakeCoreClient.instances[-1].calls, [(method, (), filters)])

    def test_get_commands_health_and_settings_use_expected_client_methods(self):
        cases = [
            (["groups", "get", "group"], "get_group", ("group",)),
            (["images", "get", "image"], "get_image", ("image",)),
            (["tasks", "get", "task"], "get_task", ("task",)),
            (["group-batches", "get", "batch"], "get_group_batch", ("batch",)),
            (["health"], "health", ()),
            (["settings", "get"], "get_settings", ()),
        ]
        for argv, method, arguments in cases:
            with self.subTest(argv=argv):
                code, output, errors = self.invoke(argv)
                self.assertEqual((code, errors, json.loads(output)["method"]), (0, "", method))
                self.assertEqual(FakeCoreClient.instances[-1].calls, [(method, arguments, {})])

    def test_default_core_url_uses_environment_without_exposing_token(self):
        code, output, errors = self.invoke(["health"], {"ATELIERX_CORE_TOKEN": "token", "ATELIERX_CORE_URL": "http://localhost:8190"})
        self.assertEqual((code, errors, json.loads(output)["method"]), (0, "", "health"))
        self.assertEqual((FakeCoreClient.instances[-1].base_url, FakeCoreClient.instances[-1].token), ("http://localhost:8190", "token"))

    def test_missing_token_argument_and_client_errors_are_safe_json_and_nonzero(self):
        code, output, errors = self.invoke(["health"], {})
        self.assertEqual((code, output), (1, ""))
        self.assertEqual(json.loads(errors)["error"]["code"], "CLI_TOKEN_MISSING")
        code, output, errors = self.invoke(["tasks", "list", "--unknown", "x"])
        self.assertEqual((code, output, json.loads(errors)["error"]["code"]), (1, "", "CLI_INVALID_ARGUMENT"))
        FakeCoreClient.failure = ApiError("CORE_NOT_FOUND", "safe service error", 404)
        code, output, errors = self.invoke(["health"])
        self.assertEqual((code, output, json.loads(errors)["error"]), (1, "", {"code": "CORE_NOT_FOUND", "message": "safe service error", "status": 404}))

    def test_terminal_service_state_is_printed_as_successful_read(self):
        FakeCoreClient.payload = {"state": "failed", "error": {"code": "GEN_EXECUTION_FAILED"}}
        code, output, errors = self.invoke(["tasks", "get", "task"])
        self.assertEqual((code, errors, json.loads(output)), (0, "", FakeCoreClient.payload))

    def test_submission_commands_use_object_input_and_exact_user_idempotency_key(self):
        task_body = {"group_id": "group", "prompt": "adult portrait"}
        validation_body = {"profile_id": "profile"}
        cases = [
            (["prompts", "preview", "--input", self.json_file(task_body)], "preview_prompt", (task_body,)),
            (["tasks", "create", "--input", self.json_file(task_body), "--idempotency-key", "create-key"], "create_task", (task_body, "create-key")),
            (["tasks", "by-key", "--idempotency-key", "recover-key"], "get_task_by_key", ("recover-key",)),
            (["tasks", "regenerate", "task", "--input", "-", "--idempotency-key", "regen-key"], "regenerate_task", ("task", task_body, "regen-key")),
            (["images", "validate", "image", "--input", self.json_file(validation_body), "--idempotency-key", "validation-key"], "validate_image", ("image", validation_body, "validation-key")),
        ]
        for argv, method, arguments in cases:
            with self.subTest(argv=argv):
                code, output, errors = self.invoke(argv, stdin=io.StringIO(json.dumps(task_body)))
                self.assertEqual((code, errors, json.loads(output)["method"]), (0, "", method))
                self.assertEqual(FakeCoreClient.instances[-1].calls, [(method, arguments, {})])

    def test_command_methods_for_cancellation_attempts_validation_and_cycles(self):
        cases = [
            (["tasks", "cancel", "task"], "cancel_task", ("task",), {}),
            (["tasks", "attempts", "task", "--limit", "2", "--offset", "1"], "list_task_attempts", ("task",), {"limit": 2, "offset": 1}),
            (["validations", "get", "run"], "get_validation_run", ("run",), {}),
            (["validations", "cancel", "run"], "cancel_validation", ("run",), {}),
            (["cycles", "get", "cycle"], "get_cycle", ("cycle",), {}),
            (["cycles", "stop", "cycle"], "stop_cycle", ("cycle",), {}),
        ]
        for argv, method, arguments, filters in cases:
            with self.subTest(argv=argv):
                code, output, errors = self.invoke(argv)
                self.assertEqual((code, errors, json.loads(output)["method"]), (0, "", method))
                self.assertEqual(FakeCoreClient.instances[-1].calls, [(method, arguments, filters)])

    def test_settings_and_group_batch_mutations_forward_user_bodies_and_keys(self):
        settings = {"revision": 1, "changes": {"quality": "high"}}
        batch = {"items": [{"prompt": "portrait"}], "group_validation": {"profile_id": "profile"}}
        confirmation = {"reference_revision": 2}
        cases = [
            (["settings", "update", "--input", self.json_file(settings)], "update_settings", (settings,)),
            (["group-batches", "create", "group", "--input", self.json_file(batch), "--idempotency-key", "batch-key"], "create_group_batch", ("group", batch, "batch-key")),
            (["group-batches", "cancel", "batch"], "cancel_group_batch", ("batch",)),
            (["group-batches", "confirm-reference", "batch", "--input", self.json_file(confirmation), "--idempotency-key", "confirm-key"], "confirm_group_batch_reference", ("batch", confirmation, "confirm-key")),
        ]
        for argv, method, arguments in cases:
            with self.subTest(argv=argv):
                code, output, errors = self.invoke(argv)
                self.assertEqual((code, errors, json.loads(output)["method"]), (0, "", method))
                self.assertEqual(FakeCoreClient.instances[-1].calls, [(method, arguments, {})])

    def test_input_requires_a_readable_utf8_json_object_without_network_call(self):
        cases = [
            (["prompts", "preview", "--input", self.json_file(["not", "an object"])], "CLI_INPUT_INVALID"),
            (["tasks", "create", "--input", self.json_file("{"), "--idempotency-key", "key"], "CLI_INPUT_INVALID"),
            (["tasks", "create", "--input", self.json_file({"cfg": float("nan")}), "--idempotency-key", "key"], "CLI_INPUT_INVALID"),
            (["images", "validate", "image", "--input", "does-not-exist.json", "--idempotency-key", "key"], "CLI_INPUT_UNREADABLE"),
        ]
        for argv, error_code in cases:
            with self.subTest(argv=argv):
                code, output, errors = self.invoke(argv)
                self.assertEqual((code, output, json.loads(errors)["error"]["code"]), (1, "", error_code))
                self.assertEqual(FakeCoreClient.instances, [])

    def test_mutating_commands_require_an_explicit_idempotency_key(self):
        cases = [
            ["tasks", "create", "--input", self.json_file({})],
            ["tasks", "regenerate", "task", "--input", self.json_file({})],
            ["images", "validate", "image", "--input", self.json_file({})],
            ["group-batches", "create", "group", "--input", self.json_file({})],
            ["group-batches", "confirm-reference", "batch", "--input", self.json_file({})],
        ]
        for argv in cases:
            with self.subTest(argv=argv):
                code, output, errors = self.invoke(argv)
                self.assertEqual((code, output, json.loads(errors)["error"]["code"]), (1, "", "CLI_INVALID_ARGUMENT"))


if __name__ == "__main__":
    unittest.main()
