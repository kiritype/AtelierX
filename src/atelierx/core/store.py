"""Core-owned SQLite state. No consumer receives a SQL execution API."""
import copy
import json
from pathlib import Path
import sqlite3
import time
import uuid
import secrets

from ..common import ApiError, ProcessLock, canonical

KINDS = {"works": None, "characters": "works", "outfits": "characters"}


class Store:
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.owner = ProcessLock(str(Path(path).resolve()) + ".lock")
        self.db = sqlite3.connect(path, timeout=5)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        version = self.db.execute("PRAGMA user_version").fetchone()[0]
        if version not in (0, 1, 2):
            self.db.close()
            self.owner.close()
            raise RuntimeError(f"Unsupported Core database version: {version}")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS entities (
                id TEXT PRIMARY KEY, kind TEXT NOT NULL, parent_id TEXT REFERENCES entities(id),
                revision INTEGER NOT NULL, archived INTEGER NOT NULL, document TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS entities_parent ON entities(kind,parent_id,id);
            CREATE TABLE IF NOT EXISTS revisions (
                entity_id TEXT NOT NULL REFERENCES entities(id), revision INTEGER NOT NULL,
                document TEXT NOT NULL, PRIMARY KEY(entity_id,revision));
            CREATE TABLE IF NOT EXISTS settings (
                revision INTEGER PRIMARY KEY, document TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS groups (
                id TEXT PRIMARY KEY, outfit_id TEXT NOT NULL REFERENCES entities(id), document TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS tasks (
                id TEXT PRIMARY KEY, group_id TEXT NOT NULL REFERENCES groups(id),
                request_key TEXT NOT NULL UNIQUE, fingerprint TEXT NOT NULL,
                state TEXT NOT NULL, created_at REAL NOT NULL, document TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS tasks_state ON tasks(state,created_at);
            CREATE TABLE IF NOT EXISTS images (
                id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES tasks(id),
                generation_image_id TEXT NOT NULL UNIQUE, document TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS validation_runs (
                id TEXT PRIMARY KEY, image_id TEXT NOT NULL REFERENCES images(id),
                request_key TEXT NOT NULL UNIQUE, fingerprint TEXT NOT NULL,
                state TEXT NOT NULL, created_at REAL NOT NULL, document TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS validation_runs_image ON validation_runs(image_id,created_at);
            CREATE TABLE IF NOT EXISTS regeneration_cycles (id TEXT PRIMARY KEY, document TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS appearance_migration_conflicts (character_id TEXT PRIMARY KEY, document TEXT NOT NULL);
            PRAGMA user_version=2;
        """)
        if not self.db.execute("SELECT 1 FROM settings LIMIT 1").fetchone():
            with self.db:
                self.db.execute("INSERT INTO settings VALUES(?,?)", (1, canonical({
                    "revision": 1, "positive_quality": "", "negative": "",
                    "auto_regeneration_enabled": True, "max_auto_regenerations": 5})))
        self._migrate_existing_outfit_appearance()

    def close(self):
        self.db.close()
        self.owner.close()

    def _migrate_existing_outfit_appearance(self):
        """Move only unambiguous legacy current documents; revisions/groups stay immutable."""
        rows = [(row[0], json.loads(row[1])) for row in self.db.execute("SELECT id,document FROM entities WHERE kind='outfits'")]
        by_character = {}
        for outfit_id, outfit in rows:
            appearance = outfit.get("components", {}).get("appearance")
            if appearance is not None:
                by_character.setdefault(outfit["parent_id"], []).append((outfit_id, outfit, appearance))
        with self.db:
            for character_id, outfits in by_character.items():
                character = self.entity(character_id, "characters")
                values = {appearance for _, _, appearance in outfits}
                if character.get("appearance_prompt"):
                    values.add(character["appearance_prompt"])
                if len(values) > 1:
                    self.db.execute("INSERT OR REPLACE INTO appearance_migration_conflicts VALUES(?,?)", (character_id, canonical({"character_id": character_id, "appearances": sorted(values), "outfit_ids": [item[0] for item in outfits], "appearances_by_outfit": [item[2] for item in outfits]})))
                    continue
                appearance = next(iter(values), "")
                if not character.get("appearance_prompt") and appearance:
                    character.update(appearance_prompt=appearance, revision=character["revision"] + 1)
                    self.db.execute("UPDATE entities SET revision=?,document=? WHERE id=?", (character["revision"], canonical(character), character_id))
                    self.db.execute("INSERT INTO revisions VALUES(?,?,?)", (character_id, character["revision"], canonical(character)))
                for outfit_id, outfit, _ in outfits:
                    parts = outfit["components"]
                    outfit.update(components={"upper": parts.get("upper", ""), "lower": parts.get("lower", ""), "accessories": parts.get("accessories", "")}, revision=outfit["revision"] + 1)
                    self.db.execute("UPDATE entities SET revision=?,document=? WHERE id=?", (outfit["revision"], canonical(outfit), outfit_id))
                    self.db.execute("INSERT INTO revisions VALUES(?,?,?)", (outfit_id, outfit["revision"], canonical(outfit)))

    def entity(self, entity_id, kind=None, active=False):
        row = self.db.execute("SELECT * FROM entities WHERE id=?", (entity_id,)).fetchone()
        if row is None or (kind and row["kind"] != kind):
            raise ApiError("CORE_NOT_FOUND", "Category entry not found", 404)
        if active and row["archived"]:
            raise ApiError("CORE_ARCHIVED", "Category entry is archived", 409)
        return json.loads(row["document"])

    def entity_response(self, entity_id, kind=None):
        document = self.entity(entity_id, kind)
        if document["kind"] == "characters":
            document.setdefault("appearance_prompt", "")
            row = self.db.execute("SELECT document FROM appearance_migration_conflicts WHERE character_id=?", (entity_id,)).fetchone()
            if row:
                conflict = json.loads(row[0]); candidates = {}
                for outfit_id, appearance in zip(conflict["outfit_ids"], conflict["appearances_by_outfit"]): candidates.setdefault(appearance, []).append(outfit_id)
                for appearance in conflict["appearances"]: candidates.setdefault(appearance, [])
                document["appearance_migration"] = {"status": "conflict", "candidates": [{"appearance_prompt": value, "outfit_ids": ids} for value, ids in sorted(candidates.items())]}
            else: document["appearance_migration"] = {"status": "complete"}
        return document

    def active_chain(self, entity_id, kind):
        entry = self.entity(entity_id, kind, active=True)
        parent_kind = KINDS[kind]
        if parent_kind:
            self.active_chain(entry["parent_id"], parent_kind)
        return entry

    def create_entity(self, kind, name, parent_id, components=None, negative_prompt="", appearance_prompt=""):
        with self.db:
            if KINDS[kind]:
                self.active_chain(parent_id, KINDS[kind])
            document = dict(id=str(uuid.uuid4()), kind=kind, parent_id=parent_id,
                            name=name, revision=1, archived=False)
            if components is not None:
                document["components"] = components
            if kind == "characters":
                document["negative_prompt"] = negative_prompt
                document["appearance_prompt"] = appearance_prompt
            self.db.execute("INSERT INTO entities VALUES(?,?,?,?,?,?)",
                            (document["id"], kind, parent_id, 1, 0, canonical(document)))
            self.db.execute("INSERT INTO revisions VALUES(?,?,?)", (document["id"], 1, canonical(document)))
        return document

    def update_entity(self, entity_id, kind, revision, changes):
        with self.db:
            document = self.entity(entity_id, kind)
            if document["revision"] != revision:
                raise ApiError("CORE_REVISION_CONFLICT", "Category entry changed; refresh before editing", 409)
            conflict = self.db.execute("SELECT document FROM appearance_migration_conflicts WHERE character_id=?", (entity_id,)).fetchone() if kind == "characters" else None
            if conflict and "appearance_prompt" in changes:
                detail = json.loads(conflict[0])
                if changes["appearance_prompt"] not in detail["appearances"]:
                    raise ApiError("CORE_APPEARANCE_MIGRATION_RESOLUTION_REQUIRED", "Choose one listed legacy appearance before editing", 409)
                for outfit_id in detail["outfit_ids"]:
                    outfit = self.entity(outfit_id, "outfits"); parts = outfit.get("components", {})
                    if "appearance" in parts:
                        outfit.update(components={"upper": parts.get("upper", ""), "lower": parts.get("lower", ""), "accessories": parts.get("accessories", "")}, revision=outfit["revision"] + 1)
                        self.db.execute("UPDATE entities SET revision=?,document=? WHERE id=?", (outfit["revision"], canonical(outfit), outfit_id))
                        self.db.execute("INSERT INTO revisions VALUES(?,?,?)", (outfit_id, outfit["revision"], canonical(outfit)))
                self.db.execute("DELETE FROM appearance_migration_conflicts WHERE character_id=?", (entity_id,))
            if kind == "outfits" and "components" in changes and self.db.execute("SELECT 1 FROM appearance_migration_conflicts WHERE character_id=?", (document["parent_id"],)).fetchone():
                raise ApiError("CORE_APPEARANCE_MIGRATION_RESOLUTION_REQUIRED", "Resolve the character appearance migration before editing outfits", 409)
            document.update(changes, revision=revision + 1)
            cursor = self.db.execute("UPDATE entities SET document=?,revision=?,archived=? WHERE id=? AND revision=?",
                                     (canonical(document), revision + 1, int(document["archived"]), entity_id, revision))
            if cursor.rowcount != 1:
                raise ApiError("CORE_REVISION_CONFLICT", "Concurrent edit", 409)
            self.db.execute("INSERT INTO revisions VALUES(?,?,?)", (entity_id, revision + 1, canonical(document)))
        return document

    def list_entities(self, kind, parent_id, limit, offset):
        rows = self.db.execute("SELECT document FROM entities WHERE kind=? AND (? IS NULL OR parent_id=?) ORDER BY id LIMIT ? OFFSET ?",
                               (kind, parent_id, parent_id, limit, offset)).fetchall()
        values = [json.loads(row[0]) for row in rows]
        return [self.entity_response(item["id"], kind) for item in values] if kind == "characters" else values

    def history(self, entity_id, kind, limit, offset):
        self.entity(entity_id, kind)
        return [json.loads(row[0]) for row in self.db.execute(
            "SELECT document FROM revisions WHERE entity_id=? ORDER BY revision DESC LIMIT ? OFFSET ?",
            (entity_id, limit, offset))]

    def settings(self):
        return json.loads(self.db.execute("SELECT document FROM settings ORDER BY revision DESC LIMIT 1").fetchone()[0])

    def update_settings(self, revision, changes):
        with self.db:
            document = self.settings()
            if document["revision"] != revision:
                raise ApiError("CORE_REVISION_CONFLICT", "Settings changed; refresh before editing", 409)
            document.update(changes, revision=revision + 1)
            try:
                self.db.execute("INSERT INTO settings VALUES(?,?)", (revision + 1, canonical(document)))
            except sqlite3.IntegrityError:
                raise ApiError("CORE_REVISION_CONFLICT", "Concurrent settings edit", 409)
        return document

    def create_group(self, outfit_id):
        with self.db:
            outfit = self.active_chain(outfit_id, "outfits")
            character = self.entity(outfit["parent_id"], "characters")
            if self.db.execute("SELECT 1 FROM appearance_migration_conflicts WHERE character_id=?", (character["id"],)).fetchone():
                raise ApiError("CORE_APPEARANCE_MIGRATION_RESOLUTION_REQUIRED", "Resolve the character appearance migration before creating a group", 409)
            work = self.entity(character["parent_id"], "works")
            document = dict(id=str(uuid.uuid4()), outfit_id=outfit_id,
                            character_id=character["id"], work_id=work["id"],
                            outfit_revision=outfit["revision"], components=outfit["components"],
                            character_revision=character["revision"], character_appearance_prompt=character.get("appearance_prompt") or outfit.get("components", {}).get("appearance", ""),
                            created_at=time.time())
            self.db.execute("INSERT INTO groups VALUES(?,?,?)", (document["id"], outfit_id, canonical(document)))
        return document

    def group(self, group_id):
        row = self.db.execute("SELECT document FROM groups WHERE id=?", (group_id,)).fetchone()
        if not row:
            raise ApiError("CORE_NOT_FOUND", "Group not found", 404)
        return json.loads(row[0])

    def task(self, task_id):
        row = self.db.execute("SELECT document FROM tasks WHERE id=?", (task_id,)).fetchone()
        if not row:
            raise ApiError("CORE_NOT_FOUND", "Task not found", 404)
        task = json.loads(row[0])
        if task.get("regeneration"):
            cycle = self.cycle(task["regeneration"]["cycle_id"])
            task["automatic_attempts_used"] = cycle["used"]
        return task

    def by_key(self, key):
        row = self.db.execute("SELECT fingerprint,document FROM tasks WHERE request_key=?", (key,)).fetchone()
        return (row[0], self.task(json.loads(row[1])["id"])) if row else None

    def create_task(self, key, fingerprint, group_id, snapshot, regeneration=None):
        # ``-1`` is a request for randomness, not a value Generation may see.
        # Keep previews stable with that sentinel, then freeze one concrete value
        # at the same durable boundary as the Task.  Reopening or retrying a
        # request returns this document, so it cannot silently choose again.
        snapshot = self.execution_snapshot(snapshot)
        document = dict(id=str(uuid.uuid4()), group_id=group_id, state="queued", created_at=time.time(),
                        snapshot=snapshot, generation_job_id=None, images=[], error=None,
                        validation={"state": "not_requested", "outcome": None}, automatic_attempts_used=0)
        link = dict(regeneration or {"kind": "initial", "parent_task_id": None, "lineage_id": document["id"]})
        if link["kind"] != "automatic":
            link["cycle_id"] = document["id"]
        document["regeneration"] = link
        with self.db:
            if link.get("supersedes_cycle"):
                previous = self.cycle(link["supersedes_cycle"])
                previous.update(state="manual_restart", reason="New manual cycle requested")
                self.db.execute("UPDATE regeneration_cycles SET document=? WHERE id=?", (canonical(previous), previous["id"]))
            if link["kind"] != "automatic":
                settings = snapshot.get("settings", {})
                cycle = {"id": link["cycle_id"], "lineage_id": link["lineage_id"], "active_task_id": document["id"],
                         "enabled": settings.get("auto_regeneration_enabled", True), "limit": settings.get("max_auto_regenerations", 5),
                         "used": 0, "state": "active", "reason": None}
            else:
                cycle = self.cycle(link["cycle_id"])
                cycle["active_task_id"] = document["id"]
            self.db.execute("INSERT OR REPLACE INTO regeneration_cycles VALUES(?,?)", (cycle["id"], canonical(cycle)))
            self.db.execute("INSERT INTO tasks VALUES(?,?,?,?,?,?,?)", (
                document["id"], group_id, key, fingerprint, "queued", document["created_at"], canonical(document)))
        return document

    @staticmethod
    def execution_snapshot(snapshot):
        """Copy a preview snapshot and replace its random-seed sentinel once."""
        frozen = copy.deepcopy(snapshot)
        inputs = frozen.get("generation_inputs") if isinstance(frozen, dict) else None
        if isinstance(inputs, dict) and inputs.get("seed") == -1:
            # API consumers include JavaScript clients, so generated values
            # must remain exactly representable when returned as JSON numbers.
            inputs["seed"] = secrets.randbelow(2**53)
        return frozen

    def cycle(self, cycle_id):
        row = self.db.execute("SELECT document FROM regeneration_cycles WHERE id=?", (cycle_id,)).fetchone()
        if not row: raise ApiError("CORE_NOT_FOUND", "Regeneration cycle not found", 404)
        return json.loads(row[0])

    def update_cycle(self, cycle, **changes):
        cycle.update(changes)
        with self.db:
            self.db.execute("UPDATE regeneration_cycles SET document=? WHERE id=?", (canonical(cycle), cycle["id"]))
        return cycle

    def active_cycles(self):
        return [cycle for row in self.db.execute("SELECT document FROM regeneration_cycles") if (cycle := json.loads(row[0]))["state"] == "active"]

    def charge_automatic_start(self, task_id):
        with self.db:
            task = self.task(task_id)
            link = task.get("regeneration", {})
            if link.get("kind") != "automatic" or task.get("automatic_started_counted"): return
            cycle = self.cycle(link["cycle_id"])
            cycle["used"] += 1
            task.update(automatic_started_counted=True, automatic_attempts_used=cycle["used"])
            self.db.execute("UPDATE regeneration_cycles SET document=? WHERE id=?", (canonical(cycle), cycle["id"]))
            self.db.execute("UPDATE tasks SET document=? WHERE id=?", (canonical(task), task["id"]))

    def save_task(self, task):
        current = self.task(task["id"])
        if current.get("automatic_started_counted"):
            task["automatic_started_counted"] = True
        task["automatic_attempts_used"] = current.get("automatic_attempts_used", 0)
        if current.get("cancel_requested"):
            task["cancel_requested"] = True
        self.db.execute("UPDATE tasks SET state=?,document=? WHERE id=? AND state NOT IN ('generated','failed','cancelled')",
                        (task["state"], canonical(task), task["id"]))

    def update_task(self, task):
        with self.db:
            self.save_task(task)

    def pending(self):
        return [json.loads(row[0]) for row in self.db.execute(
            "SELECT document FROM tasks WHERE state IN ('queued','dispatching','generation_pending','generating') ORDER BY created_at,id")]

    def finish_generation(self, task, images):
        # Image metadata and task completion share one transaction: lost reply cannot
        # leave a completed task with missing image records or duplicate ingestion.
        with self.db:
            current = self.task(task["id"])
            if current["state"] in {"generated", "failed", "cancelled"}:
                return
            if current.get("cancel_requested"):
                task.update(state="cancelled", images=[], error=None)
                self.save_task(task)
                return
            for image in images:
                self.db.execute("INSERT INTO images VALUES(?,?,?,?)", (
                    image["id"], task["id"], image["generation_image_id"], canonical(image)))
            task.update(state="generated", images=images, error=None)
            self.save_task(task)

    def image(self, image_id):
        row = self.db.execute("SELECT document FROM images WHERE id=?", (image_id,)).fetchone()
        if not row:
            raise ApiError("CORE_NOT_FOUND", "Image not found", 404)
        return json.loads(row[0])

    def list_tasks(self, group_id, limit, offset):
        return [json.loads(row[0]) for row in self.db.execute(
            "SELECT document FROM tasks WHERE (? IS NULL OR group_id=?) ORDER BY created_at DESC,id LIMIT ? OFFSET ?",
            (group_id, group_id, limit, offset))]

    def validation_run(self, run_id):
        row = self.db.execute("SELECT document FROM validation_runs WHERE id=?", (run_id,)).fetchone()
        if not row:
            raise ApiError("CORE_NOT_FOUND", "Validation run not found", 404)
        return json.loads(row[0])

    def validation_by_key(self, key):
        row = self.db.execute("SELECT fingerprint,document FROM validation_runs WHERE request_key=?", (key,)).fetchone()
        return (row[0], json.loads(row[1])) if row else None

    def image_validations(self, image_id):
        self.image(image_id)
        return [json.loads(row[0]) for row in self.db.execute(
            "SELECT document FROM validation_runs WHERE image_id=? ORDER BY created_at DESC,id", (image_id,))]

    def create_validation(self, image_id, key, fingerprint, payload, endpoint):
        with self.db:
            self.image(image_id)
            if self.db.execute("SELECT 1 FROM validation_runs WHERE image_id=? AND state NOT IN ('completed','failed','cancelled')", (image_id,)).fetchone():
                raise ApiError("CORE_VALIDATION_ACTIVE", "This image already has an active validation", 409)
            run = dict(id=str(uuid.uuid4()), image_id=image_id, state="queued", outcome=None,
                       request=payload, endpoint=endpoint, job_id=None, result=None, error=None, created_at=time.time())
            self.db.execute("INSERT INTO validation_runs VALUES(?,?,?,?,?,?,?)", (
                run["id"], image_id, key, fingerprint, run["state"], run["created_at"], canonical(run)))
            return run

    def pending_validations(self):
        return [json.loads(row[0]) for row in self.db.execute(
            "SELECT document FROM validation_runs WHERE state NOT IN ('completed','failed','cancelled') ORDER BY created_at,id")]

    def generated_for_validation(self):
        tasks = [json.loads(row[0]) for row in self.db.execute("SELECT document FROM tasks WHERE state='generated' ORDER BY created_at,id")]
        return [t for t in tasks if t["snapshot"].get("validation") and not t.get("cancel_requested") and not t.get("automatic_validation_error")]

    def task_metadata(self, task_id, **changes):
        with self.db:
            task = self.task(task_id)
            task.update(changes)
            self.db.execute("UPDATE tasks SET document=? WHERE id=?", (canonical(task), task_id))
        return task

    def update_validation(self, run):
        with self.db:
            current = self.validation_run(run["id"])
            if current.get("cancel_requested"):
                run["cancel_requested"] = True
                if run["state"] in {"completed", "failed"}:
                    run.update(state="cancelled", outcome=None, result=None, error=None)
            changed = self.db.execute("UPDATE validation_runs SET state=?,document=? WHERE id=? AND state NOT IN ('completed','failed','cancelled')",
                                     (run["state"], canonical(run), run["id"]))
            if not changed.rowcount:
                return
            image = self.image(run["image_id"])
            image.update(validation_state=run["state"], validation={key: run[key] for key in ("id", "state", "outcome", "error", "result")})
            self.db.execute("UPDATE images SET document=? WHERE id=?", (canonical(image), image["id"]))
            task = self.task(image["task_id"])
            task["images"] = [self.image(item["id"]) for item in task["images"]]
            task["validation"] = {"state": "per_image", "outcome": None,
                                  "images": [{"image_id": item["id"], "state": item["validation_state"],
                                              "outcome": item.get("validation", {}).get("outcome")} for item in task["images"]]}
            # Generation remains terminal; validation updates only the result metadata.
            self.db.execute("UPDATE tasks SET document=? WHERE id=?", (canonical(task), task["id"]))
