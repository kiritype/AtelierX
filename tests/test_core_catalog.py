import json
import sqlite3
import tempfile
import unittest
import uuid
from types import SimpleNamespace

from multidict import MultiDict

from atelierx.common import ApiError
from atelierx.core.catalog import list_groups, list_images
from atelierx.core.groups import CoreGroups
from atelierx.core.store import Store


def identifier(number):
    return str(uuid.UUID(int=number))


class FixtureGroups:
    def __init__(self, statuses, runs=None):
        self.statuses = statuses
        self._runs = runs or {}
        self.calls = []

    def status(self, group_id):
        self.calls.append(group_id)
        return self.statuses[group_id]

    def runs(self, group_id):
        return self._runs.get(group_id, [])


class CoreCatalogTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.executescript("""
            CREATE TABLE groups (id TEXT PRIMARY KEY, outfit_id TEXT, document TEXT NOT NULL);
            CREATE TABLE tasks (id TEXT PRIMARY KEY, group_id TEXT, created_at REAL NOT NULL, document TEXT NOT NULL);
            CREATE TABLE images (id TEXT PRIMARY KEY, task_id TEXT, document TEXT NOT NULL);
            CREATE TABLE validation_runs (id TEXT PRIMARY KEY, image_id TEXT NOT NULL, request_key TEXT, fingerprint TEXT, state TEXT, created_at REAL, document TEXT NOT NULL);
        """)
        self.work, self.character, self.outfit = identifier(1), identifier(2), identifier(3)
        self.group_a, self.group_b = identifier(4), identifier(5)
        self.task_a, self.task_b, self.task_c, self.task_d = identifier(6), identifier(7), identifier(8), identifier(13)
        self.reference, self.current, self.stale, self.unvalidated, self.not_eligible = (identifier(i) for i in (9, 10, 11, 12, 14))
        self._put("groups", {"id": self.group_a, "work_id": self.work, "character_id": self.character,
                               "outfit_id": self.outfit, "outfit_revision": 1,
                               "components": {"appearance": "silver hair", "upper": "white shirt", "lower": "boots"},
                               "created_at": 20, "reference": {"revision": 1, "representative_id": self.reference, "auxiliary_ids": []}})
        self._put("groups", {"id": self.group_b, "work_id": self.work, "character_id": self.character,
                               "outfit_id": self.outfit, "outfit_revision": 2,
                               "components": {"appearance": "red hair", "upper": "coat", "lower": "boots"}, "created_at": 10})
        self._put("tasks", {"id": self.task_a, "group_id": self.group_a, "created_at": 30, "snapshot": {"secret": "not-public"}})
        self._put("tasks", {"id": self.task_b, "group_id": self.group_a, "created_at": 30, "snapshot": {"secret": "not-public"}})
        self._put("tasks", {"id": self.task_c, "group_id": self.group_b, "created_at": 25, "snapshot": {"secret": "not-public"}})
        self._put("tasks", {"id": self.task_d, "group_id": self.group_a, "created_at": 20, "snapshot": {"secret": "not-public"}})
        self._put_image(self.reference, self.task_a, self.group_a, "image/png", "passed")
        self._put_image(self.current, self.task_b, self.group_a, "image/webp", "error")
        self._put_image(self.stale, self.task_a, self.group_a, "image/png", "passed")
        self._put_image(self.unvalidated, self.task_c, self.group_b, "image/png", None)
        self._put_image(self.not_eligible, self.task_d, self.group_a, "image/png", "failed")
        self.groups = FixtureGroups({
            self.group_a: {"reference": {"revision": 1, "representative_id": self.reference, "auxiliary_ids": []},
                           "target_ids": [self.current],
                           "results": [{"image_ref": self.current, "status": "error", "run_id": "current-group-run"}]},
            self.group_b: {"reference": None, "target_ids": [], "results": []},
        }, {self.group_a: [{"id": "old-group-run", "state": "completed", "request": {"reference_revision": 0, "targets": [{"ref": self.stale}]}}]})
        self.core = SimpleNamespace(store=SimpleNamespace(db=self.db), groups=self.groups)

    def tearDown(self):
        self.db.close()

    def _put(self, table, document):
        encoded = json.dumps(document)
        if table == "groups":
            self.db.execute("INSERT INTO groups VALUES(?,?,?)", (document["id"], document["outfit_id"], encoded))
        elif table == "tasks":
            self.db.execute("INSERT INTO tasks VALUES(?,?,?,?)", (document["id"], document.get("group_id"), document["created_at"], encoded))
        else:
            self.db.execute("INSERT INTO images VALUES(?,?,?)", (document["id"], document["task_id"], encoded))
        self.db.commit()

    def _put_image(self, image_id, task_id, group_id, media_type, outcome):
        document = {"id": image_id, "task_id": task_id, "group_id": group_id,
                    "generation_image_id": "generation-" + image_id, "sha256": "a" * 64,
                    "bytes": 17, "media_type": media_type, "path": "C:/secret/image.png"}
        if outcome is not None:
            document["validation_state"] = "completed" if outcome != "error" else "failed"
            document["validation"] = {"outcome": outcome, "error": {"secret": "not-public"}}
        self._put("images", document)

    def test_groups_filter_page_order_and_immutable_metadata(self):
        result = list_groups(self.core, {"outfit_id": self.outfit, "limit": "1", "offset": "0"})
        self.assertEqual((result["limit"], result["offset"], result["total"]), (1, 0, 2))
        self.assertEqual(result["items"][0]["id"], self.group_a)
        self.assertEqual(result["items"][0]["outfit_revision"], 1)
        self.assertIn("components", result["items"][0])
        self.assertNotIn("snapshot", result["items"][0])
        self.assertEqual(list_groups(self.core, {"outfit_id": identifier(99)})["items"], [])

    def test_images_project_latest_single_and_current_group_status_once_per_group(self):
        result = list_images(self.core, {})
        by_id = {item["id"]: item for item in result["items"]}
        self.assertEqual(result["total"], 5)
        self.assertEqual(by_id[self.reference]["group_status"], "reference")
        self.assertEqual((by_id[self.current]["single_outcome"], by_id[self.current]["group_status"]), ("error", "error"))
        self.assertEqual(by_id[self.stale]["group_status"], "stale")
        self.assertEqual(by_id[self.not_eligible]["group_status"], "not_eligible")
        self.assertEqual((by_id[self.unvalidated]["single_outcome"], by_id[self.unvalidated]["group_status"]), ("unvalidated", "unvalidated"))
        self.assertEqual(set(self.groups.calls), {self.group_a, self.group_b})
        self.assertEqual(len(self.groups.calls), 2)  # no per-image consistency recomputation
        descriptor = by_id[self.current]
        self.assertEqual(descriptor["content_url"], "/v1/images/" + self.current + "/content")
        self.assertNotIn("path", descriptor)
        self.assertNotIn("snapshot", descriptor)
        self.assertNotIn("validation", descriptor)

    def test_images_filter_and_stable_pagination(self):
        first = list_images(self.core, {"group_id": self.group_a, "limit": "2", "offset": "0"})
        second = list_images(self.core, {"group_id": self.group_a, "limit": "2", "offset": "2"})
        expected = [self.reference, self.current, self.stale, self.not_eligible]
        self.assertEqual([item["id"] for item in first["items"] + second["items"]], expected)
        self.assertEqual(list_images(self.core, {"single_outcome": "error"})["items"][0]["id"], self.current)
        self.assertEqual(list_images(self.core, {"group_status": "stale"})["items"][0]["id"], self.stale)
        self.assertEqual(list_images(self.core, {"task_id": identifier(99)})["total"], 0)

    def test_invalid_duplicate_unknown_and_empty_query_are_rejected(self):
        invalid_queries = [
            {"unknown": "x"}, {"group_id": ""}, {"media_type": "image/jpeg"},
            {"single_outcome": "maybe"}, {"limit": "0"}, {"offset": "-1"}, {"offset": str(2**63)},
            MultiDict([("group_id", self.group_a), ("group_id", self.group_b)]),
        ]
        for query in invalid_queries:
            with self.subTest(query=query):
                with self.assertRaises(ApiError) as raised:
                    list_images(self.core, query)
                self.assertEqual((raised.exception.code, raised.exception.status), ("CORE_INVALID_INPUT", 400))

    def test_actual_store_new_queued_revalidation_overrides_cached_pass(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(directory + "/core.sqlite3")
            try:
                work = store.create_entity("works", "work", None)
                character = store.create_entity("characters", "character", work["id"])
                outfit = store.create_entity("outfits", "outfit", character["id"], {"appearance": "hair", "upper": "shirt", "lower": "boots"})
                group = store.create_group(outfit["id"])
                task = store.create_task("task-key", "task-fingerprint", group["id"], {"settings": {}})
                image = {"id": identifier(100), "task_id": task["id"], "group_id": group["id"],
                         "generation_image_id": "generation-queued", "sha256": "b" * 64, "bytes": 1,
                         "media_type": "image/png", "validation_state": "completed",
                         "validation": {"state": "completed", "outcome": "passed"}}
                store.finish_generation(task, [image])
                store.create_validation(image["id"], "new-validation", "new-fingerprint", {}, "http://validation")
                core = SimpleNamespace(store=store, generation_url="http://generation")
                core.groups = CoreGroups(core)
                result = list_images(core, {"task_id": task["id"]})
                self.assertEqual(result["items"][0]["single_outcome"], "pending")
            finally:
                store.close()

    def test_actual_group_reference_change_marks_old_result_stale_while_target_is_current(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(directory + "/core.sqlite3")
            try:
                work = store.create_entity("works", "work", None)
                character = store.create_entity("characters", "character", work["id"])
                outfit = store.create_entity("outfits", "outfit", character["id"], {"appearance": "hair", "upper": "shirt", "lower": "boots"})
                group = store.create_group(outfit["id"])
                core = SimpleNamespace(store=store, generation_url="http://generation")
                core.groups = CoreGroups(core)
                images = []
                for number in (201, 202):
                    task = store.create_task("task-" + str(number), "fingerprint-" + str(number), group["id"], {"generation_endpoint": core.generation_url, "settings": {}})
                    image = {"id": identifier(number), "task_id": task["id"], "group_id": group["id"],
                             "generation_image_id": "generation-" + str(number), "sha256": "c" * 64,
                             "bytes": 1, "media_type": "image/png", "validation_state": "completed",
                             "validation": {"outcome": "passed"}}
                    store.finish_generation(task, [image])
                    images.append((task, image))
                core.groups.reference(group["id"], {"revision": 0, "representative_id": images[0][1]["id"], "auxiliary_ids": []})
                old_run = {"id": "old-reference-run", "group_id": group["id"], "created_at": 1, "state": "completed",
                           "request": {"reference_revision": 1, "targets": [{"ref": images[1][1]["id"]}]},
                           "result": {"items": [{"image_ref": images[1][1]["id"], "status": "matched"}]}}
                store.db.execute("INSERT INTO group_runs VALUES(?,?,?,?)", (old_run["id"], "old-key", "old-fingerprint", json.dumps(old_run)))
                store.db.commit()
                core.groups.reference(group["id"], {"revision": 1, "representative_id": images[0][1]["id"], "auxiliary_ids": []})
                result = list_images(core, {"task_id": images[1][0]["id"]})["items"][0]
                self.assertEqual((result["group_status"], result["group_reference_revision"], result["group_validation_run_id"]),
                                 ("stale", 2, old_run["id"]))
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main()
