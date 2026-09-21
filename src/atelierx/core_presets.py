"""Core-owned revisioned presets for generation and post-processing settings.

This module is intentionally attached by ``core.create_app`` rather than by a
Generation worker: only Core opens the SQLite tables and exposes the REST API.
"""
from __future__ import annotations

import copy
import json
import math
import sqlite3
import time
import uuid

from aiohttp import web

from .common import ApiError, canonical


KINDS = {"generation", "postprocess"}
STAGES = {"upscale", "detailer", "censor", "alpha", "encode"}
_STAGE_FIELDS = {
    "upscale": {"upscale_model", "scale"},
    "detailer": {"face_enabled", "eye_enabled", "mouth_enabled", "hand_enabled", "face_detector_model", "eye_detector_model", "mouth_detector_model", "hand_detector_model", "sam_model", "seed", "steps", "cfg", "sampler_name", "scheduler", "denoise"},
    "censor": {"segmentation_model", "labels", "confidence", "treatment", "intensity"},
    "alpha": {"segmentation_model", "confidence"},
    "encode": {"webp_enabled", "webp_quality"},
}


def _invalid(message: str) -> None:
    raise ApiError("CORE_PRESET_INVALID", message)


def _text(value: object, label: str, limit: int = 255) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        _invalid(f"{label} must be non-empty text up to {limit} characters")
    return value


def _model_name(value: object, label: str) -> str:
    name = _text(value, label)
    normalized = name.replace("\\", "/")
    if normalized.startswith("/") or ":" in normalized or ".." in normalized.split("/"):
        _invalid(f"{label} must be a registered model name, not a path")
    return name


def _finite(value: object, label: str, low: float, high: float, integer: bool = False) -> None:
    valid = type(value) is int if integer else type(value) in (int, float)
    if not valid or not math.isfinite(value) or not low <= value <= high:
        _invalid(f"{label} must be within {low}..{high}")


def validate_postprocess_settings(value: object) -> dict:
    """Validate portable stage settings without accepting a graph, path, or secret."""
    if not isinstance(value, dict) or set(value) - STAGES:
        _invalid("postprocess settings have unknown stages")
    result: dict[str, dict] = {}
    for stage, settings in value.items():
        if not isinstance(settings, dict) or set(settings) - _STAGE_FIELDS[stage]:
            _invalid(f"{stage} has unknown settings")
        cfg = copy.deepcopy(settings)
        if stage == "upscale":
            if "upscale_model" not in cfg:
                _invalid("upscale requires upscale_model")
            _model_name(cfg["upscale_model"], "upscale.upscale_model")
            scale = cfg.get("scale", 1.5)
            if type(scale) not in (int, float) or not math.isfinite(scale) or scale <= 0:
                _invalid("upscale.scale must be finite and greater than zero")
        elif stage == "detailer":
            for field in ("face_enabled", "eye_enabled", "mouth_enabled", "hand_enabled"):
                if field in cfg and type(cfg[field]) is not bool:
                    _invalid(f"detailer.{field} must be boolean")
            for field in ("face_detector_model", "eye_detector_model", "mouth_detector_model", "hand_detector_model", "sam_model"):
                if field in cfg:
                    _model_name(cfg[field], f"detailer.{field}")
            for field in ("sampler_name", "scheduler"):
                if field in cfg:
                    _text(cfg[field], f"detailer.{field}")
            for field, low, high, integer in (("seed", 0, 2**64 - 1, True), ("steps", 1, 100, True), ("cfg", 0, 20, False), ("denoise", 0, 1, False)):
                if field in cfg:
                    _finite(cfg[field], f"detailer.{field}", low, high, integer)
        elif stage == "encode":
            if "webp_enabled" in cfg and type(cfg["webp_enabled"]) is not bool:
                _invalid("encode.webp_enabled must be boolean")
            if "webp_quality" in cfg:
                _finite(cfg["webp_quality"], "encode.webp_quality", 1, 100, True)
        else:
            required = {"alpha": {"segmentation_model"}, "censor": {"segmentation_model", "labels"}}[stage]
            if required - set(cfg):
                _invalid(f"{stage} requires {', '.join(sorted(required))}")
            if "segmentation_model" in cfg:
                _model_name(cfg["segmentation_model"], f"{stage}.segmentation_model")
            if "confidence" in cfg:
                _finite(cfg["confidence"], f"{stage}.confidence", 0, 1)
            if stage == "censor":
                if "labels" in cfg:
                    _text(cfg["labels"], "censor.labels")
                if "treatment" in cfg:
                    _text(cfg["treatment"], "censor.treatment")
                if "intensity" in cfg:
                    _finite(cfg["intensity"], "censor.intensity", 1, 128, True)
        result[stage] = cfg
    return result


class CorePresets:
    """Use Core's existing SQLite connection for immutable preset revisions."""

    def __init__(self, db: sqlite3.Connection, validate_generation):
        self.db, self.validate_generation = db, validate_generation
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS presets (
                id TEXT PRIMARY KEY, kind TEXT NOT NULL, revision INTEGER NOT NULL,
                archived INTEGER NOT NULL, updated_at REAL NOT NULL, document TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS presets_kind ON presets(kind, archived, id);
            CREATE TABLE IF NOT EXISTS preset_revisions (
                preset_id TEXT NOT NULL REFERENCES presets(id), revision INTEGER NOT NULL,
                document TEXT NOT NULL, PRIMARY KEY(preset_id, revision));
        """)

    def _settings(self, kind: str, settings: object) -> dict:
        if kind == "generation":
            # The Core task validator rejects prompts, endpoints, paths, and unknown keys.
            result = copy.deepcopy(self.validate_generation(settings))
            for field in ("diffusion_model", "text_encoder", "vae"):
                _model_name(result[field], field)
            for item in result.get("loras", []):
                _model_name(item["name"], "LoRA name")
            return result
        return validate_postprocess_settings(settings)

    def _document(self, row) -> dict:
        if row is None:
            raise ApiError("CORE_PRESET_NOT_FOUND", "Preset not found", 404)
        return json.loads(row[0])

    def create(self, kind: str, name: object, settings: object) -> dict:
        if kind not in KINDS:
            raise ApiError("CORE_PRESET_NOT_FOUND", "Preset kind not found", 404)
        document = {"id": str(uuid.uuid4()), "kind": kind, "name": _text(name, "name", 200),
                    "settings": self._settings(kind, settings), "revision": 1,
                    "archived": False, "created_at": time.time(), "updated_at": time.time()}
        with self.db:
            self.db.execute("INSERT INTO presets VALUES(?,?,?,?,?,?)", (document["id"], kind, 1, 0, document["updated_at"], canonical(document)))
            self.db.execute("INSERT INTO preset_revisions VALUES(?,?,?)", (document["id"], 1, canonical(document)))
        return document

    def get(self, kind: str, preset_id: str, active: bool = False) -> dict:
        if kind not in KINDS:
            raise ApiError("CORE_PRESET_NOT_FOUND", "Preset kind not found", 404)
        document = self._document(self.db.execute("SELECT document FROM presets WHERE id=? AND kind=?", (preset_id, kind)).fetchone())
        if active and document["archived"]:
            raise ApiError("CORE_PRESET_ARCHIVED", "Archived preset cannot be applied", 409)
        return document

    def list(self, kind: str, limit: int = 50, offset: int = 0, archived: bool | None = None) -> list[dict]:
        if kind not in KINDS:
            raise ApiError("CORE_PRESET_NOT_FOUND", "Preset kind not found", 404)
        if type(limit) is not int or not 1 <= limit <= 200 or type(offset) is not int or offset < 0:
            _invalid("limit must be 1..200 and offset must be nonnegative")
        if archived is not None and type(archived) is not bool:
            _invalid("archived must be boolean when supplied")
        rows = self.db.execute("SELECT document FROM presets WHERE kind=? AND (? IS NULL OR archived=?) ORDER BY id LIMIT ? OFFSET ?", (kind, archived, None if archived is None else int(archived), limit, offset)).fetchall()
        return [json.loads(row[0]) for row in rows]

    def update(self, kind: str, preset_id: str, revision: object, changes: object) -> dict:
        if type(revision) is not int or revision < 1:
            _invalid("revision must be a positive integer")
        if not isinstance(changes, dict) or not changes or set(changes) - {"name", "settings", "archived"}:
            _invalid("Update requires name, settings, or archived")
        with self.db:
            current = self.get(kind, preset_id)
            if current["revision"] != revision:
                raise ApiError("CORE_REVISION_CONFLICT", "Preset changed; refresh before editing", 409)
            document = copy.deepcopy(current)
            if "name" in changes:
                document["name"] = _text(changes["name"], "name", 200)
            if "settings" in changes:
                document["settings"] = self._settings(kind, changes["settings"])
            if "archived" in changes:
                if type(changes["archived"]) is not bool:
                    _invalid("archived must be boolean")
                document["archived"] = changes["archived"]
            document.update(revision=revision + 1, updated_at=time.time())
            cursor = self.db.execute("UPDATE presets SET revision=?,archived=?,updated_at=?,document=? WHERE id=? AND kind=? AND revision=?", (document["revision"], int(document["archived"]), document["updated_at"], canonical(document), preset_id, kind, revision))
            if cursor.rowcount != 1:
                raise ApiError("CORE_REVISION_CONFLICT", "Concurrent preset edit", 409)
            self.db.execute("INSERT INTO preset_revisions VALUES(?,?,?)", (preset_id, document["revision"], canonical(document)))
        return document

    def history(self, kind: str, preset_id: str, limit: int = 50, offset: int = 0) -> list[dict]:
        self.get(kind, preset_id)
        if type(limit) is not int or not 1 <= limit <= 200 or type(offset) is not int or offset < 0:
            _invalid("limit must be 1..200 and offset must be nonnegative")
        rows = self.db.execute("SELECT document FROM preset_revisions WHERE preset_id=? ORDER BY revision DESC LIMIT ? OFFSET ?", (preset_id, limit, offset)).fetchall()
        return [json.loads(row[0]) for row in rows]

    def snapshot(self, kind: str, preset_id: str, expected_revision: int | None = None) -> dict:
        """Return immutable task-safe settings and source metadata for Core.preview."""
        preset = self.get(kind, preset_id, active=True)
        if type(expected_revision) is not int or expected_revision < 1:
            _invalid("preset revision must be a positive integer")
        if preset["revision"] != expected_revision:
            raise ApiError("CORE_REVISION_CONFLICT", "Preset changed; refresh before applying", 409)
        return {"preset": {key: preset[key] for key in ("id", "kind", "name", "revision")},
                "settings": copy.deepcopy(preset["settings"])}

    def attach(self, app: web.Application) -> None:
        async def collection(request):
            kind = request.match_info["kind"]
            if request.method == "GET":
                try:
                    limit, offset = int(request.query.get("limit", 50)), int(request.query.get("offset", 0))
                except ValueError:
                    _invalid("limit and offset must be integers")
                archived = request.query.get("archived")
                if archived not in (None, "true", "false"):
                    _invalid("archived must be true or false")
                return web.json_response({"items": self.list(kind, limit, offset, None if archived is None else archived == "true"), "limit": limit, "offset": offset})
            body = await request.json()
            if not isinstance(body, dict) or set(body) != {"name", "settings"}:
                _invalid("Create requires name and settings")
            return web.json_response(self.create(kind, body["name"], body["settings"]), status=201)

        async def item(request):
            kind, preset_id = request.match_info["kind"], request.match_info["id"]
            if request.method == "GET":
                return web.json_response(self.get(kind, preset_id))
            body = await request.json()
            if not isinstance(body, dict) or "revision" not in body:
                _invalid("Update requires revision")
            changes = {key: value for key, value in body.items() if key != "revision"}
            return web.json_response(self.update(kind, preset_id, body["revision"], changes))

        async def revisions(request):
            try:
                limit, offset = int(request.query.get("limit", 50)), int(request.query.get("offset", 0))
            except ValueError:
                _invalid("limit and offset must be integers")
            return web.json_response({"items": self.history(request.match_info["kind"], request.match_info["id"], limit, offset), "limit": limit, "offset": offset})

        app.add_routes([web.get("/v1/presets/{kind}", collection), web.post("/v1/presets/{kind}", collection), web.get("/v1/presets/{kind}/{id}", item), web.patch("/v1/presets/{kind}/{id}", item), web.get("/v1/presets/{kind}/{id}/revisions", revisions)])
