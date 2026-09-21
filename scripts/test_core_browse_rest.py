"""Exercise browse REST on a SQLite backup of preserved integration data.

The worker is intentionally paused: this is a read-only routing/data test,
not an orchestration or GPU test. The source database is opened read-only.
"""
import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import secrets
import sqlite3
import sys
import time

import aiohttp
from aiohttp import web

from atelierx.core import CORE, create_app


def digest(db):
    return hashlib.sha256("\n".join(db.iterdump()).encode()).hexdigest()


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-db", default="artifacts/group-batches-rest/20260913-142529/core.sqlite3")
    parser.add_argument("--with-cli", action="store_true", help="Also exercise the Shared Client through CLI subprocesses")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    source_path = (root / args.source_db).resolve()
    if not source_path.is_file():
        parser.error("source database must exist")
    output = root / "artifacts/core-browse-rest" / time.strftime("%Y%m%d-%H%M%S")
    output.mkdir(parents=True, exist_ok=False)
    source = sqlite3.connect(source_path.as_uri() + "?mode=ro", uri=True)
    target = sqlite3.connect(output / "core.sqlite3")
    source_before = digest(source)
    source.backup(target)
    target.close()
    report = {"source": str(source_path), "worker_paused": True, "runs": []}
    token = secrets.token_urlsafe(32)

    async def paused_worker():
        await asyncio.Event().wait()

    try:
        prior = None
        for iteration in range(2):
            app = create_app(output / "core.sqlite3", "http://127.0.0.1:1", token)
            core = app[CORE]
            core.worker = paused_worker
            before = digest(core.store.db)
            runner = web.AppRunner(app)
            await runner.setup()
            try:
                await web.TCPSite(runner, "127.0.0.1", 0).start()
                base = "http://127.0.0.1:" + str(runner.addresses[0][1])
                async with aiohttp.ClientSession(headers={"Authorization": "Bearer " + token}) as client:
                    pages = {}
                    for route in ("groups", "images", "tasks", "group-batches"):
                        async with client.get(base + "/v1/" + route + "?limit=1&offset=0") as response:
                            page = await response.json()
                            assert response.status == 200, (route, response.status, page)
                        assert len(page["items"]) == 1, (route, page)
                        pages[route] = page
                        async with client.get(base + "/v1/" + route + "?limit=0") as response:
                            assert response.status == 400, (route, response.status)
                        async with client.get(base + "/v1/" + route,
                                              headers={"Authorization": "Bearer wrong"}) as response:
                            assert response.status == 401, (route, response.status)
                    group = pages["groups"]["items"][0]
                    for route, field, value in (("groups", "outfit_id", group["outfit_id"]),
                                                 ("images", "group_id", group["id"]),
                                                 ("tasks", "group_id", group["id"]),
                                                 ("group-batches", "group_id", group["id"])):
                        async with client.get(base + "/v1/" + route, params={field: value}) as response:
                            filtered = await response.json()
                            assert response.status == 200 and filtered["items"], (route, filtered)
                    after = digest(core.store.db)
                    cli_checks = []
                    if args.with_cli:
                        env = dict(os.environ, ATELIERX_CORE_URL=base, ATELIERX_CORE_TOKEN=token, PYTHONIOENCODING="utf-8")

                        async def invoke_cli(arguments, expected_exit=0, expected_code=None, token_override=None):
                            child_env = dict(env)
                            if token_override is not None:
                                child_env["ATELIERX_CORE_TOKEN"] = token_override
                            process = await asyncio.create_subprocess_exec(
                                sys.executable, "-B", "-m", "atelierx.cli", *arguments,
                                env=child_env, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
                            try:
                                stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=20)
                            except asyncio.TimeoutError:
                                process.kill()
                                await process.communicate()
                                raise
                            assert process.returncode == expected_exit, (arguments, process.returncode, stderr.decode("utf-8"))
                            assert token.encode() not in stdout + stderr, "CLI exposed bearer token"
                            payload = json.loads((stdout if expected_exit == 0 else stderr).decode("utf-8"))
                            if expected_code is not None:
                                assert payload["error"]["code"] == expected_code, payload
                            cli_checks.append({"command": arguments, "exit_code": process.returncode})
                            return payload

                        for route in ("groups", "images", "tasks", "group-batches"):
                            page = await invoke_cli([route, "list", "--limit", "1", "--offset", "0"])
                            assert page == pages[route], (route, "CLI and REST differ")
                            detail = await invoke_cli([route, "get", page["items"][0]["id"]])
                            assert detail["id"] == page["items"][0]["id"], (route, detail)
                        await invoke_cli(["health"])
                        await invoke_cli(["queue"])
                        await invoke_cli(["settings", "get"])
                        await invoke_cli(["groups", "list"], expected_exit=1,
                                         expected_code="CORE_UNAUTHORIZED", token_override="incorrect-test-token")
                        await invoke_cli(["images", "list", "--limit", "0"], expected_exit=1,
                                         expected_code="CORE_INVALID_INPUT")
                        after = digest(core.store.db)
                    assert before == after, "Read-only endpoints changed persisted state"
                    if prior is not None:
                        assert pages == prior, "Browse results changed after restart"
                    prior = pages
                    report["runs"].append({"iteration": iteration, "pages": pages, "database_unchanged": True, "cli_checks": cli_checks})
            finally:
                await runner.cleanup()
        assert digest(source) == source_before, "Original database changed"
        report.update(source_unchanged=True, restart_stable=True, result="passed")
    except Exception as exc:
        report["failure"] = {"type": type(exc).__name__, "message": str(exc)}
        raise
    finally:
        source.close()
        (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(output / "report.json")


if __name__ == "__main__":
    asyncio.run(main())
