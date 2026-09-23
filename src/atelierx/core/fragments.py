"""Core-owned, revisioned prompt fragments and their user-managed categories."""
import copy
import json
import time
import uuid

from aiohttp import web

from ..common import ApiError, canonical
from ..output_names import sanitize_segment

INCLUDE = {"upper", "lower", "accessories", "hands"}
ORDER = ("number IS NULL, CASE WHEN number GLOB '[0-9]*' AND number NOT GLOB '*[^0-9]*' THEN 0 ELSE 1 END, "
         "CAST(number AS INTEGER), number COLLATE NOCASE, id")


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
        """)
        self._migrate()

    def _columns(self, table):
        return {row[1]: (row[2] or "").upper() for row in self.db.execute(f"PRAGMA table_info({table})")}

    def _migrate(self):
        """Move to user-entered TEXT numbers; revision history stays untouched."""
        with self.db:
            if not self.db.in_transaction:
                self.db.execute("BEGIN IMMEDIATE")
            columns = self._columns("prompt_fragments")
            if "category_id" not in columns:
                self.db.execute("ALTER TABLE prompt_fragments ADD COLUMN category_id TEXT")
            if "number" not in columns:
                self.db.execute("ALTER TABLE prompt_fragments ADD COLUMN number TEXT")
            elif columns["number"] != "TEXT":
                self.db.execute("DROP INDEX IF EXISTS prompt_fragments_number_unique")
                self.db.execute("DROP INDEX IF EXISTS prompt_fragments_category_number")
                self.db.execute("""CREATE TABLE prompt_fragments_text_number (
                  id TEXT PRIMARY KEY, revision INTEGER NOT NULL, archived INTEGER NOT NULL,
                  document TEXT NOT NULL, number TEXT, category_id TEXT)""")
                self.db.execute("""INSERT INTO prompt_fragments_text_number
                  SELECT id,revision,archived,document,CASE WHEN number IS NULL THEN NULL ELSE CAST(number AS TEXT) END,category_id FROM prompt_fragments""")
                self.db.execute("DROP TABLE prompt_fragments")
                self.db.execute("ALTER TABLE prompt_fragments_text_number RENAME TO prompt_fragments")
            rows = self.db.execute("SELECT id,number,document FROM prompt_fragments ORDER BY json_extract(document,'$.created_at'), id").fetchall()
            used = {row[1] for row in rows if row[1] is not None}
            next_number = 1
            for fragment_id, stored, raw in rows:
                document = json.loads(raw)
                number = stored
                if document.get("common", False):
                    number = None
                elif number is None:
                    while str(next_number) in used:
                        next_number += 1
                    number = str(next_number)
                    used.add(number)
                if stored != number or document.get("number") != number or "category_id" not in document:
                    document["number"] = number
                    document.setdefault("category_id", None)
                    self.db.execute("UPDATE prompt_fragments SET number=?,document=? WHERE id=?", (number, canonical(document), fragment_id))
            self.db.execute("CREATE INDEX IF NOT EXISTS prompt_fragments_number ON prompt_fragments(number COLLATE NOCASE)")
            self.db.execute("CREATE INDEX IF NOT EXISTS prompt_fragments_category ON prompt_fragments(category_id)")

    @staticmethod
    def _number(value):
        if isinstance(value, str):
            value = value.strip()
            if 1 <= len(value) <= 32 and value == sanitize_segment(value):
                return value
        raise ApiError("CORE_FRAGMENT_NUMBER_INVALID", "조각 번호는 1–32자여야 하며 파일명에 쓸 수 없는 문자(<>:\"/\\|?*, 제어 문자, 끝의 점·공백, 연속 공백, Windows 예약 이름)는 사용할 수 없습니다", 400)

    @classmethod
    def _numbered(cls, common, number):
        if common:
            if number is not None:
                raise ApiError("CORE_FRAGMENT_NUMBER_INVALID", "공통 적용 조각에는 번호를 지정할 수 없습니다", 400)
            return None
        if number is None:
            raise ApiError("CORE_FRAGMENT_NUMBER_REQUIRED", "이미지별 조각에는 번호가 필요합니다", 400)
        return cls._number(number)

    @staticmethod
    def _value(name, body, include, common=False, negative=""):
        name = _name(name)
        if not isinstance(body, str) or not body.strip() or len(body) > 20000:
            invalid("body must be non-empty text up to 20000 characters")
        if type(common) is not bool:
            invalid("common must be boolean")
        if not isinstance(include, dict) or not {"upper", "lower"} <= set(include) or set(include) - INCLUDE or any(type(value) is not bool for value in include.values()):
            invalid("include requires upper, lower and optional accessories/hands booleans")
        # Keep legacy revision documents byte-compatible; Core composition
        # supplies accessories/hands=True when these optional keys are absent.
        normalized = {name: include[name] for name in ("upper", "lower", "accessories", "hands") if name in include}
        if not isinstance(negative, str) or len(negative) > 20000:
            invalid("negative must be text up to 20000 characters")
        value = {"name": name, "body": body, "include": normalized, "common": common}
        # Generation-only Negative. Empty/whitespace is stored as an absent key so
        # documents and Task snapshots without a Negative keep their prior bytes.
        if negative.strip():
            value["negative"] = negative
        return value

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

    def duplicates(self, number, exclude_id=None, include_archived=True):
        rows = self.db.execute("SELECT document FROM prompt_fragments WHERE number=? COLLATE NOCASE AND id IS NOT ?" + ("" if include_archived else " AND archived=0") + " ORDER BY " + ORDER,
                               (number, exclude_id)).fetchall()
        return [json.loads(row[0]) for row in rows]

    def warnings(self, document):
        if document.get("number") is None:
            return []
        others = self.duplicates(document["number"], document["id"], include_archived=False)
        return [{"code": "duplicate_number", "number": document["number"], "fragment_ids": [item["id"] for item in others]}] if others else []

    def number_check(self, number, exclude_id=None):
        number = self._number(number)
        if exclude_id is not None and not isinstance(exclude_id, str):
            invalid("exclude_id must be a fragment id")
        return {"number": number, "duplicates": [{key: item.get(key) for key in ("id", "number", "name", "archived")} for item in self.duplicates(number, exclude_id)]}

    def create(self, name, body, include, category_id=None, common=False, number=None, negative=""):
        value = self._value(name, body, include, common, negative)
        number = self._numbered(common, number)
        with self.db:
            if not self.db.in_transaction:
                self.db.execute("BEGIN IMMEDIATE")
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

    def list(self, limit, offset, archived=None, category_id=None, search=None, sort=None):
        _page(limit, offset)
        if archived not in (None, True, False): invalid("archived must be true or false")
        if category_id is not None and not isinstance(category_id, str): invalid("category_id must be a category id or uncategorized")
        if search is not None and (not isinstance(search, str) or len(search) > 200): invalid("q must be text up to 200 characters")
        if sort not in (None, "name"): invalid("sort must be 'name' when given")
        clauses, values = [], []
        if archived is not None: clauses.append("archived=?"); values.append(int(archived))
        if category_id == "uncategorized": clauses.append("category_id IS NULL")
        elif category_id is not None: clauses.append("category_id=?"); values.append(category_id)
        if search:
            if search.startswith("#") or (search.isascii() and search.isdigit()):
                clauses.append("number=? COLLATE NOCASE")
                values.append(search[1:] if search.startswith("#") else search)
            else:
                clauses.append("(number=? COLLATE NOCASE OR json_extract(document,'$.name') LIKE ? COLLATE NOCASE OR json_extract(document,'$.body') LIKE ? COLLATE NOCASE)")
                values.extend([search.strip(), f"%{search}%", f"%{search}%"])
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        order = "json_extract(document,'$.name') COLLATE NOCASE, id" if sort == "name" else ORDER
        total = self.db.execute("SELECT count(*) FROM prompt_fragments" + where, values).fetchone()[0]
        rows = self.db.execute("SELECT document FROM prompt_fragments" + where + " ORDER BY " + order + " LIMIT ? OFFSET ?", [*values, limit, offset]).fetchall()
        return {"items": [json.loads(row[0]) for row in rows], "total": total, "limit": limit, "offset": offset}

    def update(self, fragment_id, expected, changes):
        if type(expected) is not int or expected < 1 or not isinstance(changes, dict) or not changes or set(changes) - {"name", "body", "include", "common", "archived", "category_id", "number", "negative"}:
            invalid("revision and one or more supported changes are required")
        with self.db:
            if not self.db.in_transaction:
                self.db.execute("BEGIN IMMEDIATE")
            current = self.get(fragment_id)
            if current["revision"] != expected:
                raise ApiError("CORE_REVISION_CONFLICT", "Prompt fragment changed; refresh before editing", 409)
            value = self._value(changes.get("name", current["name"]), changes.get("body", current["body"]), changes.get("include", current["include"]), changes.get("common", current.get("common", False)), changes.get("negative", current.get("negative", "")))
            if value["common"]:
                number = self._numbered(True, changes.get("number"))
            else:
                number = self._numbered(False, changes["number"] if "number" in changes else current.get("number"))
            category_id = current.get("category_id")
            if "category_id" in changes and changes["category_id"] != category_id:
                category_id = self._category_id(changes["category_id"])
            archived = changes.get("archived", current["archived"])
            if type(archived) is not bool: invalid("archived must be boolean")
            document = dict(current, **value, number=number, category_id=category_id, archived=archived, revision=expected + 1, updated_at=time.time())
            if "negative" not in value:
                document.pop("negative", None)
            cursor = self.db.execute("UPDATE prompt_fragments SET revision=?,archived=?,category_id=?,number=?,document=? WHERE id=? AND revision=?",
                                     (document["revision"], int(archived), category_id, number, canonical(document), fragment_id, expected))
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
        if current.get("negative", "").strip(): frozen["negative"] = current["negative"]
        if current.get("common", False): frozen["common"] = True
        elif current.get("number") is not None: frozen["number"] = str(current["number"])
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
                sort = request.query.get("sort")
                if sort not in (None, "name"): invalid("sort must be 'name' when given")
                return web.json_response(self.list(limit, offset, archived_query(request), request.query.get("category_id"), request.query.get("q"), sort))
            body = await request.json()
            if not isinstance(body, dict) or set(body) - {"name", "body", "include", "category_id", "common", "number", "negative"} or not {"name", "body", "include"} <= set(body): invalid("name, body and include are required; category_id, common, number and negative are optional")
            created = self.create(body["name"], body["body"], body["include"], body.get("category_id"), body.get("common", False), body.get("number"), body.get("negative", ""))
            return web.json_response(dict(created, warnings=self.warnings(created)), status=201)
        async def item(request):
            if request.method == "GET": return web.json_response(self.get(request.match_info["id"]))
            body = await request.json()
            if not isinstance(body, dict) or "revision" not in body: invalid("revision is required")
            updated = self.update(request.match_info["id"], body["revision"], {key: value for key, value in body.items() if key != "revision"})
            return web.json_response(dict(updated, warnings=self.warnings(updated)))
        async def number_check(request):
            if set(request.query) - {"number", "exclude_id"} or "number" not in request.query: invalid("number is required; exclude_id is optional")
            return web.json_response(self.number_check(request.query["number"], request.query.get("exclude_id")))
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
            web.get("/v1/prompt-fragments", collection), web.post("/v1/prompt-fragments", collection), web.get("/v1/prompt-fragments/number-check", number_check), web.get("/v1/prompt-fragments/{id}", item), web.patch("/v1/prompt-fragments/{id}", item), web.get("/v1/prompt-fragments/{id}/revisions", revisions),
        ])
