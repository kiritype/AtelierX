from __future__ import annotations

import sqlite3
import json
import tempfile
import threading
import unittest
from pathlib import Path

from aiohttp.test_utils import TestClient, TestServer

from atelierx.common import ApiError
from atelierx.core import Core, create_app
from atelierx.core.fragments import CoreFragments


GENERATION = {
    "diffusion_model": "anima.safetensors", "text_encoder": "anima-te.safetensors",
    "vae": "anima-vae.safetensors", "width": 768, "height": 1024, "seed": 7,
    "steps": 24, "cfg": 4.5, "sampler": "euler_ancestral", "scheduler": "normal",
}


class FragmentStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "core.sqlite3"
        self.db = sqlite3.connect(self.path)
        self.fragments = CoreFragments(self.db)

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def test_revision_snapshot_archive_and_reopen(self):
        created = self.fragments.create("Friendly pose", "smiling, waving", {"upper": True, "lower": False})
        frozen = self.fragments.snapshot({"id": created["id"], "revision": 1})
        revised = self.fragments.update(created["id"], 1, {"body": "surprised, waving"})
        self.assertEqual(revised["revision"], 2)
        self.assertEqual(frozen, {"id": created["id"], "revision": 1, "body": "smiling, waving", "include": {"upper": True, "lower": False}})
        self.assertEqual([entry["revision"] for entry in self.fragments.history(created["id"], 50, 0)], [2, 1])
        with self.assertRaisesRegex(ApiError, "refresh preview"):
            self.fragments.snapshot({"id": created["id"], "revision": 1})
        self.fragments.update(created["id"], 2, {"archived": True})
        with self.assertRaisesRegex(ApiError, "Archived"):
            self.fragments.snapshot({"id": created["id"], "revision": 3})
        self.db.close()
        self.db = sqlite3.connect(self.path)
        self.fragments = CoreFragments(self.db)
        self.assertTrue(self.fragments.get(created["id"])["archived"])

    def test_rejects_invalid_documents_and_optimistic_conflict(self):
        with self.assertRaisesRegex(ApiError, "include requires"):
            self.fragments.create("Bad", "body", {"appearance": True, "upper": True, "lower": True})
        created = self.fragments.create("Good", "body", {"upper": True, "lower": True})
        with self.assertRaisesRegex(ApiError, "refresh before editing"):
            self.fragments.update(created["id"], 2, {"name": "stale"})
        with self.assertRaisesRegex(ApiError, "supported changes"):
            self.fragments.update(created["id"], 1, {"appearance": True})

    def test_common_flag_is_revisioned_without_rewriting_older_history(self):
        created = self.fragments.create("Lighting", "warm rim light", {"upper": False, "lower": False}, common=True)
        self.assertTrue(created["common"])
        self.assertTrue(self.fragments.snapshot({"id": created["id"], "revision": 1})["common"])
        revised = self.fragments.update(created["id"], 1, {"common": False})
        self.assertFalse(revised["common"])
        self.assertTrue(self.fragments.history(created["id"], 10, 0)[1]["common"])

    def test_category_filters_archive_rules_and_visible_numbers(self):
        poses = self.fragments.create_category("Poses")
        first = self.fragments.create("Standing", "standing", {"upper": True, "lower": True}, poses["id"])
        second = self.fragments.create("No category", "sitting", {"upper": True, "lower": False})
        self.assertEqual((first["number"], second["number"], second["category_id"]), (1, 2, None))
        self.assertEqual(self.fragments.list(50, 0, category_id=poses["id"])["total"], 1)
        self.assertEqual(self.fragments.list(50, 0, category_id="uncategorized")["items"][0]["id"], second["id"])
        self.assertEqual(self.fragments.list(50, 0, search="stand")["items"][0]["id"], first["id"])
        self.assertEqual(self.fragments.list(50, 0, search="#0001")["items"][0]["id"], first["id"])
        with self.assertRaisesRegex(ApiError, "SQLite integer"):
            self.fragments.list(50, 0, search="9" * 200)
        archived = self.fragments.update_category(poses["id"], 1, {"archived": True})
        self.assertTrue(archived["archived"])
        self.assertEqual(self.fragments.get(first["id"])["category_id"], poses["id"])
        self.fragments.update(first["id"], 1, {"category_id": poses["id"], "name": "Standing pose"})
        with self.assertRaisesRegex(ApiError, "Archived prompt fragment category"):
            self.fragments.create("Blocked", "blocked", {"upper": True, "lower": True}, poses["id"])
        self.fragments.update(first["id"], 2, {"body": "still standing"})
        self.fragments.update(second["id"], 1, {"archived": True})
        third = self.fragments.create("Later", "walking", {"upper": True, "lower": True})
        self.assertEqual(third["number"], 3)
        self.db.close()
        self.db = sqlite3.connect(self.path)
        self.fragments = CoreFragments(self.db)
        fourth = self.fragments.create("After reopen", "running", {"upper": True, "lower": True})
        self.assertEqual(fourth["number"], 4)

    def test_legacy_migration_assigns_stable_numbers_without_rewriting_history(self):
        self.db.close()
        self.db = sqlite3.connect(self.path)
        self.db.executescript("""
            DROP TABLE prompt_fragment_revisions;
            DROP TABLE prompt_fragments;
            DROP TABLE prompt_fragment_category_revisions;
            DROP TABLE prompt_fragment_categories;
            DROP TABLE prompt_fragment_number_sequence;
            CREATE TABLE prompt_fragments (id TEXT PRIMARY KEY, revision INTEGER NOT NULL, archived INTEGER NOT NULL, document TEXT NOT NULL);
            CREATE TABLE prompt_fragment_revisions (fragment_id TEXT NOT NULL, revision INTEGER NOT NULL, document TEXT NOT NULL, PRIMARY KEY(fragment_id, revision));
        """)
        older = {"id": "z-id", "name": "Older", "body": "one", "include": {"upper": True, "lower": True}, "revision": 1, "archived": False, "created_at": 10, "updated_at": 10}
        newer = {"id": "a-id", "name": "Newer", "body": "two", "include": {"upper": True, "lower": True}, "revision": 1, "archived": False, "created_at": 20, "updated_at": 20}
        for document in (older, newer):
            encoded = json.dumps(document, separators=(",", ":"), sort_keys=True)
            self.db.execute("INSERT INTO prompt_fragments VALUES(?,?,?,?)", (document["id"], 1, 0, encoded))
            self.db.execute("INSERT INTO prompt_fragment_revisions VALUES(?,?,?)", (document["id"], 1, encoded))
        self.db.commit()
        self.fragments = CoreFragments(self.db)
        self.assertEqual((self.fragments.get("z-id")["number"], self.fragments.get("a-id")["number"]), (1, 2))
        self.assertEqual(self.fragments.history("z-id", 10, 0)[0], older)
        self.fragments = CoreFragments(self.db)
        self.assertEqual(self.fragments.get("z-id")["number"], 1)

    def test_concurrent_connections_allocate_distinct_numbers(self):
        self.db.close()
        ready = threading.Barrier(2)
        numbers, errors = [], []
        lock = threading.Lock()

        def create_from_connection(name):
            connection = sqlite3.connect(self.path, timeout=5)
            try:
                fragments = CoreFragments(connection)
                ready.wait()
                result = fragments.create(name, name, {"upper": True, "lower": True})
                with lock:
                    numbers.append(result["number"])
            except Exception as error:  # surface worker failures in the test process
                with lock:
                    errors.append(error)
            finally:
                connection.close()

        workers = [threading.Thread(target=create_from_connection, args=(name,)) for name in ("one", "two")]
        for worker in workers: worker.start()
        for worker in workers: worker.join()
        self.assertEqual(errors, [])
        self.assertEqual(sorted(numbers), [1, 2])


class FragmentPreviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.core = Core(Path(self.tmp.name) / "core.sqlite3", "http://generation.invalid", "core", "generation", 60)
        work = self.core.store.create_entity("works", "work", None)
        character = self.core.store.create_entity("characters", "character", work["id"])
        outfit = self.core.store.create_entity("outfits", "outfit", character["id"], {"appearance": "silver hair", "upper": "blue jacket", "lower": "black boots"})
        self.group = self.core.store.create_group(outfit["id"])

    def tearDown(self):
        self.core.store.close()
        self.tmp.cleanup()

    def test_fragment_composes_and_freezes_body_without_changing_legacy_requests(self):
        fragment = self.core.fragments.create("Reaction", "surprised smile", {"upper": True, "lower": False})
        request = {"group_id": self.group["id"], "fragment": {"id": fragment["id"], "revision": 1}, "generation_inputs": GENERATION}
        preview = self.core.preview(request)
        snapshot = preview["snapshot"]
        self.assertTrue(snapshot["generation_inputs"]["positive_prompt"].endswith("surprised smile"))
        self.assertIn("silver hair", snapshot["generation_inputs"]["positive_prompt"])
        self.assertIn("blue jacket", snapshot["generation_inputs"]["positive_prompt"])
        self.assertNotIn("black boots", snapshot["generation_inputs"]["positive_prompt"])
        self.assertEqual(snapshot["fragment"], {"id": fragment["id"], "revision": 1, "body": "surprised smile", "include": {"upper": True, "lower": False}})
        self.core.fragments.update(fragment["id"], 1, {"body": "calm smile"})
        self.assertEqual(snapshot["fragment"]["body"], "surprised smile")
        with self.assertRaisesRegex(ApiError, "refresh preview"):
            self.core.preview(request)
        legacy = self.core.preview({"group_id": self.group["id"], "framing": "upper_body", "generation_inputs": GENERATION})
        self.assertNotIn("fragment", legacy["snapshot"])
        with self.assertRaisesRegex(ApiError, "cannot be combined"):
            self.core.preview(dict(request, fragment={"id": fragment["id"], "revision": 2}, expression="happy"))


class FragmentRestTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.client = TestClient(TestServer(create_app(Path(self.tmp.name) / "core.sqlite3", "http://generation.invalid", "core-token", "generation-token", 60)))
        await self.client.start_server()
        self.headers = {"Authorization": "Bearer core-token"}

    async def asyncTearDown(self):
        await self.client.close()
        self.tmp.cleanup()

    async def request(self, method, path, body=None, key=None):
        headers = dict(self.headers)
        if key:
            headers["Idempotency-Key"] = key
        response = await self.client.request(method, path, json=body, headers=headers)
        return response.status, await response.json()

    async def test_authenticated_crud_and_revision_history(self):
        self.assertEqual((await self.client.get("/v1/prompt-fragments")).status, 401)
        status, created = await self.request("POST", "/v1/prompt-fragments", {"name": "Scene", "body": "at a cafe", "include": {"upper": False, "lower": True}})
        self.assertEqual(status, 201)
        status, listed = await self.request("GET", "/v1/prompt-fragments?archived=false")
        self.assertEqual((status, listed["items"][0]["id"]), (200, created["id"]))
        _, work = await self.request("POST", "/v1/works", {"name": "work"})
        _, character = await self.request("POST", "/v1/characters", {"name": "character", "parent_id": work["id"]})
        _, outfit = await self.request("POST", "/v1/outfits", {"name": "outfit", "parent_id": character["id"], "components": {"appearance": "hair", "upper": "shirt", "lower": "boots"}})
        _, group = await self.request("POST", "/v1/groups", {"outfit_id": outfit["id"]})
        task_input = {"group_id": group["id"], "fragment": {"id": created["id"], "revision": 1}, "generation_inputs": GENERATION}
        status, task = await self.request("POST", "/v1/tasks", task_input, "fragment-task")
        self.assertEqual(status, 202)
        status, changed = await self.request("PATCH", "/v1/prompt-fragments/" + created["id"], {"revision": 1, "archived": True})
        self.assertEqual((status, changed["revision"]), (200, 2))
        _, original_task = await self.request("GET", "/v1/tasks/" + task["id"])
        self.assertEqual(original_task["snapshot"]["fragment"]["body"], "at a cafe")
        self.assertEqual((await self.request("GET", "/v1/prompt-fragments?archived=false"))[1]["items"], [])
        status, history = await self.request("GET", "/v1/prompt-fragments/" + created["id"] + "/revisions")
        self.assertEqual((status, [item["revision"] for item in history["items"]]), (200, [2, 1]))


if __name__ == "__main__":
    unittest.main()
