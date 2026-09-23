import os
import sqlite3
import tempfile
import unittest

from atelierx.common import ApiError
from atelierx.core.fragments import CoreFragments
from atelierx.core.store import Store


class CharacterAppearanceContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(os.path.join(self.temp.name, "core.sqlite"))

    def tearDown(self):
        self.store.close(); self.temp.cleanup()

    def test_new_group_freezes_character_appearance_and_outfit_parts(self):
        work = self.store.create_entity("works", "work", None)
        character = self.store.create_entity("characters", "character", work["id"], appearance_prompt="silver hair, blue eyes")
        outfit = self.store.create_entity("outfits", "outfit", character["id"], {"upper": "shirt", "lower": "boots", "accessories": "brooch"})
        group = self.store.create_group(outfit["id"])
        self.assertEqual(character["appearance_prompt"], "silver hair, blue eyes")
        self.assertEqual(group["character_appearance_prompt"], "silver hair, blue eyes")
        self.assertEqual(group["components"], {"upper": "shirt", "lower": "boots", "accessories": "brooch"})

    def test_legacy_fragment_snapshot_stays_unchanged_while_new_include_accepts_accessories(self):
        fragments = CoreFragments(self.store.db)
        legacy = fragments.create("legacy", "pose", {"upper": True, "lower": False})
        modern = fragments.create("modern", "pose", {"upper": True, "lower": False, "accessories": False})
        self.assertNotIn("accessories", fragments.snapshot({"id": legacy["id"], "revision": 1})["include"])
        self.assertEqual(fragments.snapshot({"id": modern["id"], "revision": 1})["include"]["accessories"], False)

    def test_reopen_migrates_an_unambiguous_legacy_outfit_without_rewriting_its_old_revision(self):
        work = self.store.create_entity("works", "work", None)
        character = self.store.create_entity("characters", "character", work["id"])
        outfit = self.store.create_entity("outfits", "outfit", character["id"], {"appearance": "silver hair", "upper": "shirt", "lower": "boots"})
        path = self.store.db.execute("PRAGMA database_list").fetchone()[2]
        self.store.close()
        self.store = Store(path)
        migrated_character = self.store.entity(character["id"], "characters")
        migrated_outfit = self.store.entity(outfit["id"], "outfits")
        old_outfit = self.store.history(outfit["id"], "outfits", 10, 0)[-1]
        self.assertEqual(migrated_character["appearance_prompt"], "silver hair")
        self.assertEqual(migrated_outfit["components"], {"upper": "shirt", "lower": "boots", "accessories": ""})
        self.assertEqual(old_outfit["components"]["appearance"], "silver hair")

    def test_conflicting_legacy_appearance_requires_an_explicit_candidate_resolution(self):
        work = self.store.create_entity("works", "work", None)
        character = self.store.create_entity("characters", "character", work["id"])
        first = self.store.create_entity("outfits", "one", character["id"], {"appearance": "silver hair", "upper": "shirt", "lower": "boots"})
        second = self.store.create_entity("outfits", "two", character["id"], {"appearance": "black hair", "upper": "coat", "lower": "boots"})
        path = self.store.db.execute("PRAGMA database_list").fetchone()[2]
        self.store.close(); self.store = Store(path)
        status = self.store.entity_response(character["id"], "characters")["appearance_migration"]
        self.assertEqual(status["status"], "conflict")
        with self.assertRaisesRegex(ApiError, "Choose one"):
            self.store.update_entity(character["id"], "characters", 1, {"appearance_prompt": "red hair"})
        resolved = self.store.update_entity(character["id"], "characters", 1, {"appearance_prompt": "silver hair"})
        self.assertEqual(resolved["appearance_prompt"], "silver hair")
        self.assertEqual(self.store.entity_response(character["id"], "characters")["appearance_migration"]["status"], "complete")
        self.assertNotIn("appearance", self.store.entity(first["id"], "outfits")["components"])
        self.assertNotIn("appearance", self.store.entity(second["id"], "outfits")["components"])

    def test_reopen_migration_does_not_rewrite_existing_group_or_task_snapshot_bytes(self):
        work = self.store.create_entity("works", "work", None)
        character = self.store.create_entity("characters", "character", work["id"])
        outfit = self.store.create_entity("outfits", "outfit", character["id"], {"appearance": "silver hair", "upper": "shirt", "lower": "boots"})
        group = self.store.create_group(outfit["id"])
        task = self.store.create_task("legacy-key", "legacy-fingerprint", group["id"], {"group": group, "legacy": {"appearance": "silver hair"}})
        before = [self.store.db.execute(f"SELECT document FROM {table} WHERE id=?", (ident,)).fetchone()[0] for table, ident in (("groups", group["id"]), ("tasks", task["id"]))]
        path = self.store.db.execute("PRAGMA database_list").fetchone()[2]
        self.store.close(); self.store = Store(path)
        after = [self.store.db.execute(f"SELECT document FROM {table} WHERE id=?", (ident,)).fetchone()[0] for table, ident in (("groups", group["id"]), ("tasks", task["id"]))]
        self.assertEqual(after, before)

    def test_empty_and_nonempty_legacy_appearances_are_an_explicit_conflict(self):
        work = self.store.create_entity("works", "work", None)
        character = self.store.create_entity("characters", "character", work["id"])
        self.store.create_entity("outfits", "empty", character["id"], {"appearance": "", "upper": "shirt", "lower": "boots"})
        self.store.create_entity("outfits", "visible", character["id"], {"appearance": "silver hair", "upper": "coat", "lower": "boots"})
        path = self.store.db.execute("PRAGMA database_list").fetchone()[2]
        self.store.close(); self.store = Store(path)
        conflict = self.store.entity_response(character["id"], "characters")["appearance_migration"]
        self.assertEqual(conflict["status"], "conflict")
        self.assertEqual({entry["appearance_prompt"] for entry in conflict["candidates"]}, {"", "silver hair"})

    def test_existing_character_appearance_that_differs_from_legacy_outfit_is_a_conflict(self):
        work = self.store.create_entity("works", "work", None)
        character = self.store.create_entity("characters", "character", work["id"], appearance_prompt="blue hair")
        self.store.create_entity("outfits", "outfit", character["id"], {"appearance": "silver hair", "upper": "shirt", "lower": "boots"})
        path = self.store.db.execute("PRAGMA database_list").fetchone()[2]
        self.store.close(); self.store = Store(path)
        candidates = self.store.entity_response(character["id"], "characters")["appearance_migration"]["candidates"]
        self.assertEqual({entry["appearance_prompt"] for entry in candidates}, {"blue hair", "silver hair"})

    def test_conflict_blocks_group_and_outfit_component_edits_and_stale_resolution(self):
        work = self.store.create_entity("works", "work", None)
        character = self.store.create_entity("characters", "character", work["id"])
        outfit = self.store.create_entity("outfits", "one", character["id"], {"appearance": "silver hair", "upper": "shirt", "lower": "boots"})
        self.store.create_entity("outfits", "two", character["id"], {"appearance": "black hair", "upper": "coat", "lower": "boots"})
        path = self.store.db.execute("PRAGMA database_list").fetchone()[2]
        self.store.close(); self.store = Store(path)
        with self.assertRaisesRegex(ApiError, "Resolve") as blocked_group:
            self.store.create_group(outfit["id"])
        self.assertEqual(blocked_group.exception.code, "CORE_APPEARANCE_MIGRATION_RESOLUTION_REQUIRED")
        with self.assertRaisesRegex(ApiError, "Resolve") as blocked_outfit:
            self.store.update_entity(outfit["id"], "outfits", 1, {"components": {"upper": "new", "lower": "boots", "accessories": ""}})
        self.assertEqual(blocked_outfit.exception.code, "CORE_APPEARANCE_MIGRATION_RESOLUTION_REQUIRED")
        with self.assertRaisesRegex(ApiError, "changed") as stale:
            self.store.update_entity(character["id"], "characters", 2, {"appearance_prompt": "silver hair"})
        self.assertEqual(stale.exception.code, "CORE_REVISION_CONFLICT")

    def test_resolution_rolls_back_all_outfit_changes_when_sqlite_aborts(self):
        work = self.store.create_entity("works", "work", None)
        character = self.store.create_entity("characters", "character", work["id"])
        first = self.store.create_entity("outfits", "one", character["id"], {"appearance": "silver hair", "upper": "shirt", "lower": "boots"})
        second = self.store.create_entity("outfits", "two", character["id"], {"appearance": "black hair", "upper": "coat", "lower": "boots"})
        path = self.store.db.execute("PRAGMA database_list").fetchone()[2]
        self.store.close(); self.store = Store(path)
        self.store.db.execute(f"CREATE TRIGGER abort_second_appearance_resolution BEFORE UPDATE ON entities WHEN NEW.id='{second['id']}' BEGIN SELECT RAISE(ABORT, 'injected abort'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            self.store.update_entity(character["id"], "characters", 1, {"appearance_prompt": "silver hair"})
        self.assertIn("appearance", self.store.entity(first["id"], "outfits")["components"])
        self.assertIn("appearance", self.store.entity(second["id"], "outfits")["components"])
        self.assertEqual(self.store.entity_response(character["id"], "characters")["appearance_migration"]["status"], "conflict")
