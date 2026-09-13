"""Core-owned, revisioned prompt fragments."""
import copy
import json
import time
import uuid

from aiohttp import web

from .common import ApiError, canonical


def invalid(message):
    raise ApiError("CORE_FRAGMENT_INVALID", message, 400)


class CoreFragments:
    def __init__(self, db):
        self.db = db
        db.executescript("""
        CREATE TABLE IF NOT EXISTS prompt_fragments (
          id TEXT PRIMARY KEY, revision INTEGER NOT NULL, archived INTEGER NOT NULL,
          document TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS prompt_fragment_revisions (
          fragment_id TEXT NOT NULL, revision INTEGER NOT NULL, document TEXT NOT NULL,
          PRIMARY KEY(fragment_id, revision));
        """)

    @staticmethod
    def _value(name, body, include):
        if not isinstance(name, str) or not name.strip() or len(name) > 200: invalid("name must be non-empty text up to 200 characters")
        if not isinstance(body, str) or not body.strip() or len(body) > 20000: invalid("body must be non-empty text up to 20000 characters")
        if not isinstance(include, dict) or set(include) != {"upper", "lower"} or any(type(value) is not bool for value in include.values()): invalid("include requires upper and lower booleans")
        return {"name": name, "body": body, "include": dict(include)}

    def _get(self, fragment_id):
        row = self.db.execute("SELECT document FROM prompt_fragments WHERE id=?", (fragment_id,)).fetchone()
        if not row: raise ApiError("CORE_FRAGMENT_NOT_FOUND", "Prompt fragment not found", 404)
        return json.loads(row[0])

    def create(self, name, body, include):
        document = dict(id=str(uuid.uuid4()), revision=1, archived=False, created_at=time.time(), updated_at=time.time(), **self._value(name, body, include))
        with self.db:
            self.db.execute("INSERT INTO prompt_fragments VALUES(?,?,?,?)", (document["id"], 1, 0, canonical(document)))
            self.db.execute("INSERT INTO prompt_fragment_revisions VALUES(?,?,?)", (document["id"], 1, canonical(document)))
        return document

    def get(self, fragment_id, active=False):
        document = self._get(fragment_id)
        if active and document["archived"]: raise ApiError("CORE_FRAGMENT_ARCHIVED", "Archived prompt fragment cannot be applied", 409)
        return document

    def list(self, limit, offset, archived=None):
        if type(limit) is not int or not 1 <= limit <= 200 or type(offset) is not int or offset < 0: invalid("limit must be 1..200 and offset nonnegative")
        if archived not in (None, True, False): invalid("archived must be true or false")
        rows = self.db.execute("SELECT document FROM prompt_fragments WHERE (? IS NULL OR archived=?) ORDER BY id LIMIT ? OFFSET ?", (archived, None if archived is None else int(archived), limit, offset)).fetchall()
        return [json.loads(row[0]) for row in rows]

    def update(self, fragment_id, expected, changes):
        if type(expected) is not int or expected < 1 or not isinstance(changes, dict) or not changes or set(changes) - {"name", "body", "include", "archived"}: invalid("revision and one or more supported changes are required")
        with self.db:
            current = self.get(fragment_id)
            if current["revision"] != expected: raise ApiError("CORE_REVISION_CONFLICT", "Prompt fragment changed; refresh before editing", 409)
            value = self._value(changes.get("name", current["name"]), changes.get("body", current["body"]), changes.get("include", current["include"]))
            document = dict(current, **value, archived=changes.get("archived", current["archived"]), revision=expected + 1, updated_at=time.time())
            if type(document["archived"]) is not bool: invalid("archived must be boolean")
            cursor = self.db.execute("UPDATE prompt_fragments SET revision=?,archived=?,document=? WHERE id=? AND revision=?", (document["revision"], int(document["archived"]), canonical(document), fragment_id, expected))
            if cursor.rowcount != 1: raise ApiError("CORE_REVISION_CONFLICT", "Concurrent prompt fragment edit", 409)
            self.db.execute("INSERT INTO prompt_fragment_revisions VALUES(?,?,?)", (fragment_id, document["revision"], canonical(document)))
        return document

    def history(self, fragment_id, limit, offset):
        if type(limit) is not int or not 1 <= limit <= 200 or type(offset) is not int or offset < 0:
            invalid("limit must be 1..200 and offset nonnegative")
        self.get(fragment_id)
        return [json.loads(row[0]) for row in self.db.execute("SELECT document FROM prompt_fragment_revisions WHERE fragment_id=? ORDER BY revision DESC LIMIT ? OFFSET ?", (fragment_id, limit, offset))]

    def snapshot(self, selection):
        if not isinstance(selection, dict) or set(selection) != {"id", "revision"} or not isinstance(selection["id"], str) or type(selection["revision"]) is not int or selection["revision"] < 1: invalid("fragment requires id and revision")
        current = self.get(selection["id"], active=True)
        if current["revision"] != selection["revision"]: raise ApiError("CORE_REVISION_CONFLICT", "Prompt fragment changed; refresh preview", 409)
        return copy.deepcopy({key: current[key] for key in ("id", "revision", "body", "include")})

    def attach(self, app):
        def page(request):
            try: return int(request.query.get("limit", 50)), int(request.query.get("offset", 0))
            except ValueError: invalid("limit and offset must be integers")
        async def collection(request):
            if request.method == "GET":
                limit, offset = page(request); archived = request.query.get("archived")
                if archived not in (None, "true", "false"): invalid("archived must be true or false")
                return web.json_response({"items": self.list(limit, offset, None if archived is None else archived == "true"), "limit": limit, "offset": offset})
            body = await request.json()
            if not isinstance(body, dict) or set(body) != {"name", "body", "include"}: invalid("name, body and include are required")
            return web.json_response(self.create(body["name"], body["body"], body["include"]), status=201)
        async def item(request):
            if request.method == "GET": return web.json_response(self.get(request.match_info["id"]))
            body = await request.json()
            if not isinstance(body, dict) or "revision" not in body: invalid("revision is required")
            return web.json_response(self.update(request.match_info["id"], body["revision"], {key: value for key, value in body.items() if key != "revision"}))
        async def revisions(request):
            limit, offset = page(request); return web.json_response({"items": self.history(request.match_info["id"], limit, offset), "limit": limit, "offset": offset})
        app.add_routes([web.get("/v1/prompt-fragments", collection), web.post("/v1/prompt-fragments", collection), web.get("/v1/prompt-fragments/{id}", item), web.patch("/v1/prompt-fragments/{id}", item), web.get("/v1/prompt-fragments/{id}/revisions", revisions)])
