import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace

from multidict import MultiDict
from aiohttp.test_utils import TestClient, TestServer

from atelierx.common import ApiError, canonical
from atelierx.core import create_app
from atelierx.core.batches import CoreBatches
from atelierx.core.store import Store
from atelierx.core.task_queries import list_batches, list_tasks


class CoreTaskQueryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name) / "core.sqlite3")
        self.core = SimpleNamespace(store=self.store)
        CoreBatches(self.core)
        self.work = self.store.create_entity("works", "work", None)
        self.character = self.store.create_entity("characters", "character", self.work["id"])
        self.outfit = self.store.create_entity("outfits", "outfit", self.character["id"], {"appearance": "hair", "upper": "shirt", "lower": "boots"})
        self.group = self.store.create_group(self.outfit["id"])
        self.other_work = self.store.create_entity("works", "other", None)
        self.other_character = self.store.create_entity("characters", "other", self.other_work["id"])
        self.other_outfit = self.store.create_entity("outfits", "other", self.other_character["id"], {"appearance": "hair", "upper": "shirt", "lower": "boots"})
        self.other_group = self.store.create_group(self.other_outfit["id"])
        self.old = self.make_task(self.group, "old", "generated", 10)
        self.tie_a = self.make_task(self.group, "tie-a", "failed", 20)
        self.tie_b = self.make_task(self.group, "tie-b", "queued", 20)
        self.other = self.make_task(self.other_group, "other", "generated", 30)
        self.make_batch("batch-old", self.group["id"], "completed", 10)
        self.make_batch("batch-b", self.group["id"], "creating", 20)
        self.make_batch("batch-a", self.group["id"], "creating", 20)
        self.make_batch("batch-other", self.other_group["id"], "failed", 30)

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def make_task(self, group, key, state, created_at):
        task = self.store.create_task(key, key, group["id"], {"generation_inputs": {}})
        task.update(state=state, created_at=created_at)
        with self.store.db:
            self.store.db.execute("UPDATE tasks SET state=?,created_at=?,document=? WHERE id=?", (state, created_at, canonical(task), task["id"]))
        return task

    def make_batch(self, ident, group_id, state, created_at):
        document = {"id": ident, "group_id": group_id, "state": state, "created_at": created_at,
                    "request": {}, "items": [], "error": None}
        with self.store.db:
            self.store.db.execute("INSERT INTO group_batches VALUES(?,?,?,?)", (ident + "-key", ident + "-key", ident, canonical(document)))
        return document

    def test_task_relationship_state_filters_and_unknown_ids(self):
        self.assertEqual({item["id"] for item in list_tasks(self.core, {"group_id": self.group["id"]})["items"]}, {self.old["id"], self.tie_a["id"], self.tie_b["id"]})
        for key, value in (("work_id", self.work["id"]), ("character_id", self.character["id"]), ("outfit_id", self.outfit["id"])):
            self.assertEqual({item["id"] for item in list_tasks(self.core, {key: value})["items"]}, {self.old["id"], self.tie_a["id"], self.tie_b["id"]})
        self.assertEqual([item["id"] for item in list_tasks(self.core, {"state": "failed"})["items"]], [self.tie_a["id"]])
        # Category tables may be reorganized after group creation; Task browse
        # continues to use the immutable relationship saved by the group.
        with self.store.db:
            self.store.db.execute("UPDATE entities SET parent_id=? WHERE id=?", (self.other_character["id"], self.outfit["id"]))
        self.assertEqual({item["id"] for item in list_tasks(self.core, {"work_id": self.work["id"]})["items"]}, {self.old["id"], self.tie_a["id"], self.tie_b["id"]})
        self.assertEqual(list_tasks(self.core, {"group_id": "unknown"})["items"], [])
        self.assertEqual(list_tasks(self.core, {"state": "unknown"})["items"], [])

    def test_task_pagination_stable_ties_raw_public_document_and_archives(self):
        expected_ties = sorted((self.tie_a["id"], self.tie_b["id"]))
        page = list_tasks(self.core, {"group_id": self.group["id"], "limit": "2", "offset": "0"})
        self.assertEqual(page, {"items": [next(task for task in (self.tie_a, self.tie_b) if task["id"] == ident) for ident in expected_ties], "limit": 2, "offset": 0})
        next_page = list_tasks(self.core, {"group_id": self.group["id"], "limit": "2", "offset": "2"})
        self.assertEqual([item["id"] for item in next_page["items"]], [self.old["id"]])
        self.store.update_entity(self.work["id"], "works", 1, {"archived": True})
        self.assertEqual({item["id"] for item in list_tasks(self.core, {"work_id": self.work["id"]})["items"]}, {self.old["id"], self.tie_a["id"], self.tie_b["id"]})

    def test_batch_filters_pagination_and_ties(self):
        page = list_batches(self.core, {"group_id": self.group["id"], "limit": "2"})
        self.assertEqual([item["id"] for item in page["items"]], ["batch-a", "batch-b"])
        self.assertEqual([item["id"] for item in list_batches(self.core, {"group_id": self.group["id"], "offset": "2"})["items"]], ["batch-old"])
        self.assertEqual([item["id"] for item in list_batches(self.core, {"state": "failed"})["items"]], ["batch-other"])
        self.assertEqual(list_batches(self.core, {"group_id": "unknown"})["items"], [])

    def test_invalid_unknown_duplicate_and_empty_queries_are_rejected(self):
        invalid = [
            {"unknown": "x"}, {"group_id": ""}, {"limit": "0"}, {"limit": "201"},
            {"limit": "1.5"}, {"offset": "-1"}, {"offset": "9223372036854775808"}, {"offset": "9" * 5000},
            MultiDict([("state", "queued"), ("state", "failed")]),
        ]
        for query in invalid:
            with self.subTest(query=query), self.assertRaises(ApiError) as raised:
                list_tasks(self.core, query)
            self.assertEqual((raised.exception.code, raised.exception.status), ("CORE_INVALID_INPUT", 400))
        with self.assertRaises(ApiError) as raised:
            list_batches(self.core, {"work_id": self.work["id"]})
        self.assertEqual(raised.exception.code, "CORE_INVALID_INPUT")

    def test_queries_are_read_only(self):
        before_tasks = [row[0] for row in self.store.db.execute("SELECT document FROM tasks ORDER BY id")]
        before_batches = [row[0] for row in self.store.db.execute("SELECT document FROM group_batches ORDER BY id")]
        list_tasks(self.core, {"state": "generated", "limit": "1"})
        list_batches(self.core, {"state": "creating", "limit": "1"})
        after_tasks = [row[0] for row in self.store.db.execute("SELECT document FROM tasks ORDER BY id")]
        after_batches = [row[0] for row in self.store.db.execute("SELECT document FROM group_batches ORDER BY id")]
        self.assertEqual((after_tasks, after_batches), (before_tasks, before_batches))


class CoreTaskQueryAuthTests(unittest.IsolatedAsyncioTestCase):
    async def test_existing_task_collection_requires_core_bearer_token(self):
        with tempfile.TemporaryDirectory() as directory:
            client = TestClient(TestServer(create_app(Path(directory) / "core.sqlite3", "http://generation.invalid", "query-token", "generation-token", .01)))
            await client.start_server()
            try:
                self.assertEqual((await client.get("/v1/tasks")).status, 401)
            finally:
                await client.close()


if __name__ == "__main__":
    unittest.main()
