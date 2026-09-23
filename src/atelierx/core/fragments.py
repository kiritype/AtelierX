"""Core-owned, revisioned prompt fragments and their user-managed categories."""
import copy
import json
import time
import uuid

from aiohttp import web

from ..common import ApiError, canonical


def invalid(message):
    raise ApiError("CORE_FRAGMENT_INVALID", message, 400)


def _page(limit, offset):
    if type(limit) is not int or not 1 <= limit <= 200 or type(offset) is not int or offset < 0:
        invalid("limit must be 1..200 and offset nonnegative")


def _name(value, label="name"):
    if not isinstance(value, str) or not value.strip() or len(value) > 200:
        invalid(f"{label} must be non-empty text up to 200 characters")
    return value


class CoreFragments:
    """Own fragment/category state without changing historic revision documents."""

    def __init__(self, db):
        self.db = db
        db.executescript("""
        CREATE TABLE IF NOT EXISTS prompt_fragments (
          id TEXT PRIMARY KEY, revision INTEGER NOT NULL, archived INTEGER NOT NULL,
          document TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS prompt_fragment_revisions (
          fragment_id TEXT NOT NULL, revision INTEGER NOT NULL, document TEXT NOT NULL,
          PRIMARY KEY(fragment_id, revision));
        CREATE TABLE IF NOT EXISTS prompt_fragment_categories (
          id TEXT PRIMARY KEY, revision INTEGER NOT NULL, archived INTEGER NOT NULL,
          document TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS prompt_fragment_category_revisions (
          category_id TEXT NOT NULL, revision INTEGER NOT NULL, document TEXT NOT NULL,
          PRIMARY KEY(category_id, revision));
        CREATE TABLE IF NOT EXISTS prompt_fragment_number_sequence (
          name TEXT PRIMARY KEY, next_number INTEGER NOT NULL);
        """)
        self._migrate()

    def _column(self, table, name):
        return any(row[1] == name for row in self.db.execute(f"PRAGMA table_info({table})"))

    def _migrate(self):
        """Backfill current documents in stable order; revision history stays untouched."""
        with self.db:
            if not self._column("prompt_fragments", "number"):
                self.db.execute("ALTER TABLE prompt_fragments ADD COLUMN number INTEGER")
            if not self._column("prompt_fragments", "category_id"):
                self.db.execute("ALTER TABLE prompt_fragments ADD COLUMN category_id TEXT")
            rows = self.db.execute("SELECT id,document FROM prompt_fragments WHERE number IS NULL ORDER BY json_extract(document,'$.created_at'), id").fetchall()
            used = {row[0] for row in self.db.execute("SELECT number FROM prompt_fragments WHERE number IS NOT NULL")}
            next_number = 1
            for fragment_id, raw in rows:
                while next_number in used:
                    next_number += 1
                document = json.loads(raw)
                document.setdefault("number", next_number)
                document.setdefault("category_id", None)
                self.db.execute("UPDATE prompt_fragments SET number=?,category_id=?,document=? WHERE id=?", (next_number, None, canonical(document), fragment_id))
                used.add(next_number)
                next_number += 1
            maximum = self.db.execute("SELECT COALESCE(MAX(number),0) FROM prompt_fragments").fetchone()[0]
            existing = self.db.execute("SELECT next_number FROM prompt_fragment_number_sequence WHERE name='global'").fetchone()
            if existing is None:
                self.db.execute("INSERT INTO prompt_fragment_number_sequence VALUES('global',?)", (maximum + 1,))
            elif existing[0] <= maximum:
                self.db.execute("UPDATE prompt_fragment_number_sequence SET next_number=? WHERE name='global'", (maximum + 1,))
            self.db.execute("CREATE UNIQUE INDEX IF NOT EXISTS prompt_fragments_number_unique ON prompt_fragments(number)")
            self.db.execute("CREATE INDEX IF NOT EXISTS prompt_fragments_category_number ON prompt_fragments(category_id, number)")

    @staticmethod
    def _value(name, body, include, common=False):
        name = _name(name)
        if not isinstance(body, str) or not body.strip() or len(body) > 20000:
            invalid("body must be non-empty text up to 20000 characters")
        if type(common) is not bool:
            invalid("common must be boolean")
        if not isinstance(include, dict) or set(include) not in ({"upper", "lower"}, {"upper", "lower", "accessories"}) or any(type(value) is not bool for value in include.values()):
            invalid("include requires upper, lower and optional accessories booleans")
        # Keep legacy revision documents byte-compatible; Core composition
        # supplies accessories=True when this optional key is absent.
        normalized = {"upper": include["upper"], "lower": include["lower"]}
        if "accessories" in include: normalized["accessories"] = include["accessories"]
        return {"name": name, "body": body, "include": normalized, "common": common}

    def _get(self, fragment_id):
        row = self.db.execute("SELECT document FROM prompt_fragments WHERE id=?", (fragment_id,)).fetchone()
        if not row:
            raise ApiError("CORE_FRAGMENT_NOT_FOUND", "Prompt fragment not found", 404)
        return json.loads(row[0])

    def _category(self, category_id, active=False):
        row = self.db.execute("SELECT document FROM prompt_fragment_categories WHERE id=?", (category_id,)).fetchone()
        if not row:
            raise ApiError("CORE_FRAGMENT_CATEGORY_NOT_FOUND", "Prompt fragment category not found", 404)
        document = json.loads(row[0])
        if active and document["archived"]:
            raise ApiError("CORE_FRAGMENT_CATEGORY_ARCHIVED", "Archived prompt fragment category cannot be assigned", 409)
        return document

    def _category_id(self, value):
        if value is not None and not isinstance(value, str):
            invalid("category_id must be a category id or null")
        if value is not None:
            self._category(value, active=True)
        return value

    def _next_number(self):
        if not self.db.in_transaction:
            self.db.execute("BEGIN IMMEDIATE")
        row = self.db.execute("SELECT next_number FROM prompt_fragment_number_sequence WHERE name='global'").fetchone()
        number = row[0]
        self.db.execute("UPDATE prompt_fragment_number_sequence SET next_number=? WHERE name='global'", (number + 1,))
        return number

    def create(self, name, body, include, category_id=None, common=False):
        value = self._value(name, body, include, common)
        with self.db:
            number = self._next_number()
            category_id = self._category_id(category_id)
            document = dict(id=str(uuid.uuid4()), number=number, category_id=category_id, revision=1, archived=False,
                            created_at=time.time(), updated_at=time.time(), **value)
            self.db.execute("INSERT INTO prompt_fragments(id,revision,archived,document,number,category_id) VALUES(?,?,?,?,?,?)",
                            (document["id"], 1, 0, canonical(document), number, category_id))
            self.db.execute("INSERT INTO prompt_fragment_revisions VALUES(?,?,?)", (document["id"], 1, canonical(document)))
        return document

    def get(self, fragment_id, active=False):
        document = self._get(fragment_id)
        if active and document["archived"]:
            raise ApiError("CORE_FRAGMENT_ARCHIVED", "Archived prompt fragment cannot be applied", 409)
        return document

    def list(self, limit, offset, archived=None, category_id=None, search=None):
        _page(limit, offset)
        if archived not in (None, True, False): invalid("archived must be true or false")
        if category_id is not None and not isinstance(category_id, str): invalid("category_id must be a category id or uncategorized")
        if search is not None and (not isinstance(search, str) or len(search) > 200): invalid("q must be text up to 200 characters")
        clauses, values = [], []
        if archived is not None: clauses.append("archived=?"); values.append(int(archived))
        if category_id == "uncategorized": clauses.append("category_id IS NULL")
        elif category_id is not None: clauses.append("category_id=?"); values.append(category_id)
        if search:
            number_text = search[1:] if search.startswith("#") else search
            if number_text.isascii() and number_text.isdigit():
                if len(number_text) > 19 or int(number_text) > 2**63 - 1:
                    invalid("numeric q must be a SQLite integer visible number")
                clauses.append("number=?")
                values.append(int(number_text))
            else:
                clauses.append("(json_extract(document,'$.name') LIKE ? COLLATE NOCASE OR json_extract(document,'$.body') LIKE ? COLLATE NOCASE)")
                values.extend([f"%{search}%", f"%{search}%"])
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        total = self.db.execute("SELECT count(*) FROM prompt_fragments" + where, values).fetchone()[0]
        rows = self.db.execute("SELECT document FROM prompt_fragments" + where + " ORDER BY number LIMIT ? OFFSET ?", [*values, limit, offset]).fetchall()
        return {"items": [json.loads(row[0]) for row in rows], "total": total, "limit": limit, "offset": offset}

    def update(self, fragment_id, expected, changes):
        if type(expected) is not int or expected < 1 or not isinstance(changes, dict) or not changes or set(changes) - {"name", "body", "include", "common", "archived", "category_id"}:
            invalid("revision and one or more supported changes are required")
        with self.db:
            if not self.db.in_transaction:
                self.db.execute("BEGIN IMMEDIATE")
            current = self.get(fragment_id)
            if current["revision"] != expected:
                raise ApiError("CORE_REVISION_CONFLICT", "Prompt fragment changed; refresh before editing", 409)
            value = self._value(changes.get("name", current["name"]), changes.get("body", current["body"]), changes.get("include", current["include"]), changes.get("common", current.get("common", False)))
            category_id = current.get("category_id")
            if "category_id" in changes and changes["category_id"] != category_id:
                category_id = self._category_id(changes["category_id"])
            archived = changes.get("archived", current["archived"])
            if type(archived) is not bool: invalid("archived must be boolean")
            document = dict(current, **value, category_id=category_id, archived=archived, revision=expected + 1, updated_at=time.time())
            cursor = self.db.execute("UPDATE prompt_fragments SET revision=?,archived=?,category_id=?,document=? WHERE id=? AND revision=?",
                                     (document["revision"], int(archived), category_id, canonical(document), fragment_id, expected))
            if cursor.rowcount != 1: raise ApiError("CORE_REVISION_CONFLICT", "Concurrent prompt fragment edit", 409)
            self.db.execute("INSERT INTO prompt_fragment_revisions VALUES(?,?,?)", (fragment_id, document["revision"], canonical(document)))
        return document

    def history(self, fragment_id, limit, offset):
        _page(limit, offset); self.get(fragment_id)
        return [json.loads(row[0]) for row in self.db.execute("SELECT document FROM prompt_fragment_revisions WHERE fragment_id=? ORDER BY revision DESC LIMIT ? OFFSET ?", (fragment_id, limit, offset))]

    def create_category(self, name):
        now = time.time()
        document = {"id": str(uuid.uuid4()), "name": _name(name), "revision": 1, "archived": False, "created_at": now, "updated_at": now}
        with self.db:
            if not self.db.in_transaction:
                self.db.execute("BEGIN IMMEDIATE")
            self.db.execute("INSERT INTO prompt_fragment_categories VALUES(?,?,?,?)", (document["id"], 1, 0, canonical(document)))
            self.db.execute("INSERT INTO prompt_fragment_category_revisions VALUES(?,?,?)", (document["id"], 1, canonical(document)))
        return document

    def get_category(self, category_id): return self._category(category_id)

    def list_categories(self, limit, offset, archived=None):
        _page(limit, offset)
        if archived not in (None, True, False): invalid("archived must be true or false")
        where, values = ("", []) if archived is None else (" WHERE archived=?", [int(archived)])
        total = self.db.execute("SELECT count(*) FROM prompt_fragment_categories" + where, values).fetchone()[0]
        rows = self.db.execute("SELECT document FROM prompt_fragment_categories" + where + " ORDER BY lower(json_extract(document,'$.name')),id LIMIT ? OFFSET ?", [*values, limit, offset]).fetchall()
        return {"items": [json.loads(row[0]) for row in rows], "total": total, "limit": limit, "offset": offset}

    def update_category(self, category_id, expected, changes):
        if type(expected) is not int or expected < 1 or not isinstance(changes, dict) or not changes or set(changes) - {"name", "archived"}:
            invalid("revision and name or archived are required")
        with self.db:
            if not self.db.in_transaction:
                self.db.execute("BEGIN IMMEDIATE")
            current = self._category(category_id)
            if current["revision"] != expected: raise ApiError("CORE_REVISION_CONFLICT", "Prompt fragment category changed; refresh before editing", 409)
            archived = changes.get("archived", current["archived"])
            if type(archived) is not bool: invalid("archived must be boolean")
            document = dict(current, name=_name(changes.get("name", current["name"])), archived=archived, revision=expected + 1, updated_at=time.time())
            cursor = self.db.execute("UPDATE prompt_fragment_categories SET revision=?,archived=?,document=? WHERE id=? AND revision=?",
                                     (document["revision"], int(archived), canonical(document), category_id, expected))
            if cursor.rowcount != 1: raise ApiError("CORE_REVISION_CONFLICT", "Concurrent prompt fragment category edit", 409)
            self.db.execute("INSERT INTO prompt_fragment_category_revisions VALUES(?,?,?)", (category_id, document["revision"], canonical(document)))
        return document

    def snapshot(self, selection):
        if not isinstance(selection, dict) or set(selection) != {"id", "revision"} or not isinstance(selection["id"], str) or type(selection["revision"]) is not int or selection["revision"] < 1:
            invalid("fragment requires id and revision")
        current = self.get(selection["id"], active=True)
        if current["revision"] != selection["revision"]: raise ApiError("CORE_REVISION_CONFLICT", "Prompt fragment changed; refresh preview", 409)
        frozen = {key: current[key] for key in ("id", "revision", "body", "include")}
        if current.get("common", False): frozen["common"] = True
        return copy.deepcopy(frozen)

    def attach(self, app):
        def page(request):
            try: return int(request.query.get("limit", 50)), int(request.query.get("offset", 0))
            except ValueError: invalid("limit and offset must be integers")
        def archived_query(request):
            archived = request.query.get("archived")
            if archived not in (None, "true", "false"): invalid("archived must be true or false")
            return None if archived is None else archived == "true"
        async def collection(request):
            if request.method == "GET":
                limit, offset = page(request)
                return web.json_response(self.list(limit, offset, archived_query(request), request.query.get("category_id"), request.query.get("q")))
            body = await request.json()
            if not isinstance(body, dict) or set(body) - {"name", "body", "include", "category_id", "common"} or not {"name", "body", "include"} <= set(body): invalid("name, body and include are required; category_id and common are optional")
            return web.json_response(self.create(body["name"], body["body"], body["include"], body.get("category_id"), body.get("common", False)), status=201)
        async def item(request):
            if request.method == "GET": return web.json_response(self.get(request.match_info["id"]))
            body = await request.json()
            if not isinstance(body, dict) or "revision" not in body: invalid("revision is required")
            return web.json_response(self.update(request.match_info["id"], body["revision"], {key: value for key, value in body.items() if key != "revision"}))
        async def revisions(request):
            limit, offset = page(request)
            return web.json_response({"items": self.history(request.match_info["id"], limit, offset), "limit": limit, "offset": offset})
        async def categories(request):
            if request.method == "GET":
                limit, offset = page(request)
                return web.json_response(self.list_categories(limit, offset, archived_query(request)))
            body = await request.json()
            if not isinstance(body, dict) or set(body) != {"name"}: invalid("name is required")
            return web.json_response(self.create_category(body["name"]), status=201)
        async def category(request):
            if request.method == "GET": return web.json_response(self.get_category(request.match_info["id"]))
            body = await request.json()
            if not isinstance(body, dict) or "revision" not in body: invalid("revision is required")
            return web.json_response(self.update_category(request.match_info["id"], body["revision"], {key: value for key, value in body.items() if key != "revision"}))
        app.add_routes([
            web.get("/v1/prompt-fragment-categories", categories), web.post("/v1/prompt-fragment-categories", categories), web.get("/v1/prompt-fragment-categories/{id}", category), web.patch("/v1/prompt-fragment-categories/{id}", category),
            web.get("/v1/prompt-fragments", collection), web.post("/v1/prompt-fragments", collection), web.get("/v1/prompt-fragments/{id}", item), web.patch("/v1/prompt-fragments/{id}", item), web.get("/v1/prompt-fragments/{id}/revisions", revisions),
        ])
