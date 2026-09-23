from __future__ import annotations

import sqlite3
import json
import tempfile
import unittest
from pathlib import Path

from aiohttp.test_utils import TestClient, TestServer

from atelierx.common import ApiError
from atelierx.core import CORE, Core, create_app
from atelierx.core.fragments import CoreFragments
from _reference_fixture import confirm_reference_set_offline


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
        created = self.fragments.create("Friendly pose", "smiling, waving", {"upper": True, "lower": False}, number="1")
        frozen = self.fragments.snapshot({"id": created["id"], "revision": 1})
        revised = self.fragments.update(created["id"], 1, {"body": "surprised, waving"})
        self.assertEqual(revised["revision"], 2)
        self.assertEqual(frozen, {"id": created["id"], "revision": 1, "number": "1", "body": "smiling, waving", "include": {"upper": True, "lower": False}})
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
            self.fragments.create("Bad", "body", {"appearance": True, "upper": True, "lower": True}, number="1")
        created = self.fragments.create("Good", "body", {"upper": True, "lower": True}, number="1")
        with self.assertRaisesRegex(ApiError, "refresh before editing"):
            self.fragments.update(created["id"], 2, {"name": "stale"})
        with self.assertRaisesRegex(ApiError, "supported changes"):
            self.fragments.update(created["id"], 1, {"appearance": True})

    def test_hands_include_is_optional_and_revisioned(self):
        legacy = self.fragments.create("Legacy", "pose", {"upper": True, "lower": True}, number="1")
        self.assertNotIn("hands", legacy["include"])
        modern = self.fragments.create("Modern", "pose", {"upper": True, "lower": True, "accessories": True, "hands": False}, number="2")
        self.assertEqual(self.fragments.snapshot({"id": modern["id"], "revision": 1})["include"]["hands"], False)
        changed = self.fragments.update(legacy["id"], 1, {"include": {"upper": True, "lower": True, "hands": False}})
        self.assertEqual(changed["include"], {"upper": True, "lower": True, "hands": False})
        with self.assertRaisesRegex(ApiError, "include requires"):
            self.fragments.create("Bad", "pose", {"upper": True, "lower": True, "hands": "yes"}, number="3")

    def test_common_flag_is_revisioned_without_rewriting_older_history(self):
        created = self.fragments.create("Lighting", "warm rim light", {"upper": False, "lower": False}, common=True)
        self.assertTrue(created["common"])
        self.assertIsNone(created["number"])
        self.assertTrue(self.fragments.snapshot({"id": created["id"], "revision": 1})["common"])
        with self.assertRaises(ApiError) as missing:
            self.fragments.update(created["id"], 1, {"common": False})
        self.assertEqual(missing.exception.code, "CORE_FRAGMENT_NUMBER_REQUIRED")
        revised = self.fragments.update(created["id"], 1, {"common": False, "number": "L-1"})
        self.assertEqual((revised["common"], revised["number"]), (False, "L-1"))
        self.assertTrue(self.fragments.history(created["id"], 10, 0)[1]["common"])
        common_again = self.fragments.update(created["id"], 2, {"common": True})
        self.assertIsNone(common_again["number"])

    def test_user_numbers_are_validated_editable_and_may_repeat(self):
        for bad in ("", "   ", "a" * 33, "1/2", "a:b", "x?", "end.", "CON", "com1", "a  b", "tab\tx", "bell\x07", 7):
            with self.assertRaises(ApiError, msg=repr(bad)) as caught:
                self.fragments.create("Bad", "body", {"upper": True, "lower": True}, number=bad)
            self.assertEqual(caught.exception.code, "CORE_FRAGMENT_NUMBER_INVALID")
        with self.assertRaises(ApiError) as missing:
            self.fragments.create("Missing", "body", {"upper": True, "lower": True})
        self.assertEqual(missing.exception.code, "CORE_FRAGMENT_NUMBER_REQUIRED")
        with self.assertRaises(ApiError) as common_number:
            self.fragments.create("Common", "body", {"upper": True, "lower": True}, common=True, number="1")
        self.assertEqual(common_number.exception.code, "CORE_FRAGMENT_NUMBER_INVALID")
        first = self.fragments.create("First", "one", {"upper": True, "lower": True}, number=" 표정-01 ")
        self.assertEqual(first["number"], "표정-01")
        second = self.fragments.create("Second", "two", {"upper": True, "lower": True}, number="표정-01")
        self.assertEqual(self.fragments.warnings(second), [{"code": "duplicate_number", "number": "표정-01", "fragment_ids": [first["id"]]}])
        renumbered = self.fragments.update(second["id"], 1, {"number": "A2"})
        self.assertEqual((renumbered["number"], renumbered["revision"]), ("A2", 2))
        self.assertEqual(self.fragments.history(second["id"], 10, 0)[1]["number"], "표정-01")
        self.assertEqual(self.fragments.warnings(renumbered), [])
        third = self.fragments.create("Third", "three", {"upper": True, "lower": True}, number="a2")
        self.assertEqual(self.fragments.warnings(third)[0]["fragment_ids"], [second["id"]])
        self.fragments.update(renumbered["id"], 2, {"archived": True})
        self.assertEqual(self.fragments.warnings(third), [])
        check = self.fragments.number_check("A2", exclude_id=third["id"])
        self.assertEqual(check, {"number": "A2", "duplicates": [{"id": second["id"], "number": "A2", "name": "Second", "archived": True}]})
        self.assertEqual(self.fragments.number_check("zzz")["duplicates"], [])

    def test_negative_is_optional_generation_text_and_legacy_documents_stay_unchanged(self):
        legacy = self.fragments.create("Legacy", "pose", {"upper": True, "lower": True}, number="1")
        self.assertNotIn("negative", legacy)
        self.assertNotIn("negative", self.fragments.snapshot({"id": legacy["id"], "revision": 1}))
        blank = self.fragments.create("Blank", "pose", {"upper": True, "lower": True}, number="2", negative="   ")
        self.assertNotIn("negative", blank)
        variant = self.fragments.create("Variant", "pose", {"upper": True, "lower": True}, number="3", negative="hat, mask")
        common = self.fragments.create("Common", "rim light", {"upper": False, "lower": False}, common=True, negative="lens flare")
        self.assertEqual(self.fragments.snapshot({"id": variant["id"], "revision": 1})["negative"], "hat, mask")
        self.assertEqual(self.fragments.snapshot({"id": common["id"], "revision": 1})["negative"], "lens flare")
        for bad in (None, 3, "x" * 20001):
            with self.assertRaisesRegex(ApiError, "negative must be text"):
                self.fragments.create("Bad", "pose", {"upper": True, "lower": True}, number="4", negative=bad)
        # Unrelated edits keep the Negative; clearing it removes the key again.
        renamed = self.fragments.update(variant["id"], 1, {"name": "Renamed"})
        self.assertEqual(renamed["negative"], "hat, mask")
        cleared = self.fragments.update(variant["id"], 2, {"negative": ""})
        self.assertNotIn("negative", cleared)
        self.assertNotIn("negative", self.fragments.snapshot({"id": variant["id"], "revision": 3}))
        history = self.fragments.history(variant["id"], 10, 0)
        self.assertEqual([entry.get("negative") for entry in history], [None, "hat, mask", "hat, mask"])
        added = self.fragments.update(legacy["id"], 1, {"negative": "watermark"})
        self.assertEqual((added["negative"], self.fragments.history(legacy["id"], 10, 0)[1].get("negative")), ("watermark", None))
        with self.assertRaisesRegex(ApiError, "negative must be text"):
            self.fragments.update(legacy["id"], 2, {"negative": ["watermark"]})

    def test_legacy_stored_document_without_negative_is_readable_and_editable(self):
        created = self.fragments.create("Old", "pose", {"upper": True, "lower": True}, number="1")
        stored = self.db.execute("SELECT document FROM prompt_fragment_revisions WHERE fragment_id=?", (created["id"],)).fetchone()[0]
        self.assertNotIn("negative", json.loads(stored))
        self.db.close()
        self.db = sqlite3.connect(self.path)
        self.fragments = CoreFragments(self.db)
        self.assertEqual(self.db.execute("SELECT document FROM prompt_fragment_revisions WHERE fragment_id=?", (created["id"],)).fetchone()[0], stored)
        self.assertEqual(self.fragments.update(created["id"], 1, {"body": "new pose"})["body"], "new pose")

    def test_category_filters_archive_rules_and_visible_numbers(self):
        poses = self.fragments.create_category("Poses")
        first = self.fragments.create("Standing", "standing", {"upper": True, "lower": True}, poses["id"], number="10")
        second = self.fragments.create("No category", "sitting", {"upper": True, "lower": False}, number="2")
        named = self.fragments.create("Named", "kneeling", {"upper": True, "lower": False}, number="B-1")
        self.assertEqual((first["number"], second["number"], second["category_id"]), ("10", "2", None))
        self.assertEqual([item["number"] for item in self.fragments.list(50, 0)["items"]], ["2", "10", "B-1"])
        self.assertEqual(self.fragments.list(50, 0, category_id=poses["id"])["total"], 1)
        self.assertEqual(self.fragments.list(50, 0, category_id="uncategorized")["total"], 2)
        self.assertEqual(self.fragments.list(50, 0, search="stand")["items"][0]["id"], first["id"])
        self.assertEqual(self.fragments.list(50, 0, search="#10")["items"][0]["id"], first["id"])
        self.assertEqual([item["id"] for item in self.fragments.list(50, 0, search="b-1")["items"]], [named["id"]])
        self.assertEqual(self.fragments.list(50, 0, search="9" * 200)["total"], 0)
        # sort="name" orders by name (case-insensitive) instead of number; default order is unchanged.
        self.assertEqual([item["name"] for item in self.fragments.list(50, 0, sort="name")["items"]], ["Named", "No category", "Standing"])
        self.assertEqual([item["number"] for item in self.fragments.list(50, 0)["items"]], ["2", "10", "B-1"])
        with self.assertRaisesRegex(ApiError, "sort must be"):
            self.fragments.list(50, 0, sort="bogus")
        archived = self.fragments.update_category(poses["id"], 1, {"archived": True})
        self.assertTrue(archived["archived"])
        self.assertEqual(self.fragments.get(first["id"])["category_id"], poses["id"])
        self.fragments.update(first["id"], 1, {"category_id": poses["id"], "name": "Standing pose"})
        with self.assertRaisesRegex(ApiError, "Archived prompt fragment category"):
            self.fragments.create("Blocked", "blocked", {"upper": True, "lower": True}, poses["id"], number="3")

    def test_integer_unique_numbers_migrate_to_editable_text_without_rewriting_history(self):
        self.db.close()
        self.db = sqlite3.connect(self.path)
        self.db.executescript("""
            DROP TABLE prompt_fragment_revisions;
            DROP TABLE prompt_fragments;
            CREATE TABLE prompt_fragments (id TEXT PRIMARY KEY, revision INTEGER NOT NULL, archived INTEGER NOT NULL, document TEXT NOT NULL, number INTEGER, category_id TEXT);
            CREATE TABLE prompt_fragment_revisions (fragment_id TEXT NOT NULL, revision INTEGER NOT NULL, document TEXT NOT NULL, PRIMARY KEY(fragment_id, revision));
            CREATE TABLE prompt_fragment_number_sequence (name TEXT PRIMARY KEY, next_number INTEGER NOT NULL);
            INSERT INTO prompt_fragment_number_sequence VALUES('global', 14);
            CREATE UNIQUE INDEX prompt_fragments_number_unique ON prompt_fragments(number);
            CREATE INDEX prompt_fragments_category_number ON prompt_fragments(category_id, number);
        """)
        base = {"include": {"upper": True, "lower": True}, "revision": 1, "archived": False, "category_id": None}
        variant = dict(base, id="v-id", name="Variant", body="one", number=12, created_at=10, updated_at=10)
        common = dict(base, id="c-id", name="Common", body="light", number=13, common=True, created_at=20, updated_at=20)
        for document in (variant, common):
            encoded = json.dumps(document, separators=(",", ":"), sort_keys=True)
            self.db.execute("INSERT INTO prompt_fragments VALUES(?,?,?,?,?,?)", (document["id"], 1, 0, encoded, document["number"], None))
            self.db.execute("INSERT INTO prompt_fragment_revisions VALUES(?,?,?)", (document["id"], 1, encoded))
        self.db.commit()
        self.fragments = CoreFragments(self.db)
        columns = {row[1]: row[2] for row in self.db.execute("PRAGMA table_info(prompt_fragments)")}
        self.assertEqual(columns["number"], "TEXT")
        self.assertFalse([row for row in self.db.execute("PRAGMA index_list(prompt_fragments)") if row[2] and not row[1].startswith("sqlite_autoindex")])
        self.assertEqual(self.fragments.get("v-id")["number"], "12")
        self.assertIsNone(self.fragments.get("c-id")["number"])
        self.assertEqual(self.db.execute("SELECT number FROM prompt_fragments WHERE id='v-id'").fetchone()[0], "12")
        self.assertEqual(self.fragments.history("v-id", 10, 0)[0], variant)
        duplicate = self.fragments.create("Again", "two", {"upper": True, "lower": True}, number="12")
        self.assertEqual(self.fragments.warnings(duplicate)[0]["fragment_ids"], ["v-id"])
        self.fragments = CoreFragments(self.db)
        self.assertEqual((self.fragments.get("v-id")["number"], self.fragments.get(duplicate["id"])["number"]), ("12", "12"))

    def test_pre_number_documents_receive_stable_text_numbers(self):
        self.db.close()
        self.db = sqlite3.connect(self.path)
        self.db.executescript("""
            DROP TABLE prompt_fragment_revisions;
            DROP TABLE prompt_fragments;
            DROP TABLE prompt_fragment_category_revisions;
            DROP TABLE prompt_fragment_categories;
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
        self.assertEqual((self.fragments.get("z-id")["number"], self.fragments.get("a-id")["number"]), ("1", "2"))
        self.assertEqual(self.fragments.history("z-id", 10, 0)[0], older)
        self.fragments = CoreFragments(self.db)
        self.assertEqual(self.fragments.get("z-id")["number"], "1")


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
        fragment = self.core.fragments.create("Reaction", "surprised smile", {"upper": True, "lower": False}, number="7")
        request = {"group_id": self.group["id"], "fragment": {"id": fragment["id"], "revision": 1}, "generation_inputs": GENERATION}
        preview = self.core.preview(request)
        snapshot = preview["snapshot"]
        self.assertTrue(snapshot["generation_inputs"]["positive_prompt"].endswith("surprised smile"))
        self.assertIn("silver hair", snapshot["generation_inputs"]["positive_prompt"])
        self.assertIn("blue jacket", snapshot["generation_inputs"]["positive_prompt"])
        self.assertNotIn("black boots", snapshot["generation_inputs"]["positive_prompt"])
        self.assertEqual(snapshot["fragment"], {"id": fragment["id"], "revision": 1, "number": "7", "body": "surprised smile", "include": {"upper": True, "lower": False}})
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
        status, created = await self.request("POST", "/v1/prompt-fragments", {"name": "Scene", "number": "S1", "body": "at a cafe", "include": {"upper": False, "lower": True}})
        self.assertEqual((status, created["warnings"]), (201, []))
        status, listed = await self.request("GET", "/v1/prompt-fragments?archived=false")
        self.assertEqual((status, listed["items"][0]["id"]), (200, created["id"]))
        self.assertNotIn("warnings", listed["items"][0])
        _, work = await self.request("POST", "/v1/works", {"name": "work"})
        _, character = await self.request("POST", "/v1/characters", {"name": "character", "parent_id": work["id"]})
        _, outfit = await self.request("POST", "/v1/outfits", {"name": "outfit", "parent_id": character["id"], "components": {"appearance": "hair", "upper": "shirt", "lower": "boots"}})
        _, group = await self.request("POST", "/v1/groups", {"outfit_id": outfit["id"]})
        confirm_reference_set_offline(self.client.server.app[CORE], group["id"], outfit["id"], GENERATION)
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

    async def test_number_warnings_patch_and_number_check_endpoint(self):
        include = {"upper": True, "lower": True}
        _, first = await self.request("POST", "/v1/prompt-fragments", {"name": "A", "number": "12", "body": "a", "include": include})
        status, second = await self.request("POST", "/v1/prompt-fragments", {"name": "B", "number": "12", "body": "b", "include": include})
        self.assertEqual((status, second["warnings"]), (201, [{"code": "duplicate_number", "number": "12", "fragment_ids": [first["id"]]}]))
        status, missing = await self.request("POST", "/v1/prompt-fragments", {"name": "C", "body": "c", "include": include})
        self.assertEqual((status, missing["error"]["code"]), (400, "CORE_FRAGMENT_NUMBER_REQUIRED"))
        status, bad = await self.request("POST", "/v1/prompt-fragments", {"name": "C", "number": "a|b", "body": "c", "include": include})
        self.assertEqual((status, bad["error"]["code"]), (400, "CORE_FRAGMENT_NUMBER_INVALID"))
        status, check = await self.request("GET", "/v1/prompt-fragments/number-check?number=12&exclude_id=" + second["id"])
        self.assertEqual((status, check), (200, {"number": "12", "duplicates": [{"id": first["id"], "number": "12", "name": "A", "archived": False}]}))
        status, invalid = await self.request("GET", "/v1/prompt-fragments/number-check?number=CON")
        self.assertEqual((status, invalid["error"]["code"]), (400, "CORE_FRAGMENT_NUMBER_INVALID"))
        status, renumbered = await self.request("PATCH", "/v1/prompt-fragments/" + second["id"], {"revision": 1, "number": "13"})
        self.assertEqual((status, renumbered["number"], renumbered["revision"], renumbered["warnings"]), (200, "13", 2, []))
        status, clash = await self.request("PATCH", "/v1/prompt-fragments/" + first["id"], {"revision": 1, "number": "13"})
        self.assertEqual((status, clash["warnings"][0]["fragment_ids"]), (200, [second["id"]]))
        status, common = await self.request("POST", "/v1/prompt-fragments", {"name": "L", "number": "1", "common": True, "body": "light", "include": include})
        self.assertEqual((status, common["error"]["code"]), (400, "CORE_FRAGMENT_NUMBER_INVALID"))

    async def test_sort_by_name_query_param(self):
        include = {"upper": True, "lower": True}
        await self.request("POST", "/v1/prompt-fragments", {"name": "C001 - Zed", "number": "1", "body": "a", "include": include})
        await self.request("POST", "/v1/prompt-fragments", {"name": "C002 - Amy", "number": "2", "body": "b", "include": include})
        status, sorted_by_name = await self.request("GET", "/v1/prompt-fragments?archived=false&sort=name")
        self.assertEqual((status, [item["name"] for item in sorted_by_name["items"]]), (200, ["C001 - Zed", "C002 - Amy"]))
        status, bad = await self.request("GET", "/v1/prompt-fragments?archived=false&sort=bogus")
        self.assertEqual((status, bad["error"]["code"]), (400, "CORE_FRAGMENT_INVALID"))


if __name__ == "__main__":
    unittest.main()
