"""ADR-0027 P1/P2: per-outfit reference sets (full+face) with revision history.

A reference set is never deleted; ``confirm``/``reconfirm`` always append a new
revision row and repoint the outfit's current pointer.  Reference *sample*
Tasks are ordinary Core Tasks marked ``snapshot.purpose == "reference_sample"``
so they are excluded from the P5 enforcement gate and from validation.
"""
import hashlib
import json
import secrets
import time
import uuid

from aiohttp import web

from ..common import ApiError, canonical
from ..output_names import build_output_name
from .store import DEFAULT_REFERENCE_TEMPLATES


def bad(message, code="CORE_REFERENCE_SET_INVALID", status=400):
    raise ApiError(code, message, status)


ACTIVE_TASK_STATES = frozenset({"queued", "dispatching", "generation_pending", "generating"})
SETTINGS_SUMMARY_LABELS = {
    "diffusion_model": "모델", "text_encoder": "텍스트 인코더", "common_fragments": "공통 조각",
    "positive_quality": "품질 Positive", "loras": "LoRA",
}


def _fields(value, allowed, required=()):
    if not isinstance(value, dict) or set(value) - set(allowed) or set(required) - set(value):
        bad("Missing or unknown fields")


def _page(query):
    try:
        limit, offset = int(query.get("limit", 50)), int(query.get("offset", 0))
    except (TypeError, ValueError):
        bad("Invalid pagination")
    if not 1 <= limit <= 200 or offset < 0:
        bad("Invalid pagination")
    return limit, offset


class ReferenceSets:
    def __init__(self, core):
        self.core, self.db = core, core.store.db
        self.db.executescript("""
          CREATE TABLE IF NOT EXISTS reference_sets
            (outfit_id TEXT PRIMARY KEY, document TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS reference_set_revisions
            (outfit_id TEXT NOT NULL, revision INTEGER NOT NULL, document TEXT NOT NULL,
             PRIMARY KEY(outfit_id,revision));
          CREATE TABLE IF NOT EXISTS reference_set_requests
            (request_key TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, outfit_id TEXT NOT NULL, revision INTEGER NOT NULL);
          CREATE TABLE IF NOT EXISTS reference_sample_pairs
            (id TEXT PRIMARY KEY, outfit_id TEXT NOT NULL, request_key TEXT UNIQUE NOT NULL,
             fingerprint TEXT NOT NULL, document TEXT NOT NULL);
        """)

    # -- reference set: status / read / history --------------------------------

    def status(self, outfit_id):
        outfit = self.core.store.entity(outfit_id, "outfits")
        character = self.core.store.entity(outfit["parent_id"], "characters")
        row = self.db.execute("SELECT document FROM reference_sets WHERE outfit_id=?", (outfit_id,)).fetchone()
        if not row:
            return {"status": "none", "set": None, "stale": []}
        current = json.loads(row[0])
        stale = [name for name, actual in (("character", character["revision"]), ("outfit", outfit["revision"]))
                 if current[name + "_revision"] != actual]
        return {"status": "needs_review" if stale else "valid", "set": current, "stale": stale}

    def revision_document(self, outfit_id, revision):
        row = self.db.execute("SELECT document FROM reference_set_revisions WHERE outfit_id=? AND revision=?", (outfit_id, revision)).fetchone()
        if not row:
            bad("Reference set revision not found", "CORE_NOT_FOUND", 404)
        return json.loads(row[0])

    def history(self, outfit_id, limit, offset):
        self.core.store.entity(outfit_id, "outfits")
        rows = self.db.execute("SELECT document FROM reference_set_revisions WHERE outfit_id=? ORDER BY revision DESC LIMIT ? OFFSET ?",
                               (outfit_id, limit, offset)).fetchall()
        total = self.db.execute("SELECT count(*) FROM reference_set_revisions WHERE outfit_id=?", (outfit_id,)).fetchone()[0]
        return {"items": [json.loads(row[0]) for row in rows], "limit": limit, "offset": offset, "total": total}

    # -- reference set: confirm / reconfirm -------------------------------------

    def _reference_image(self, outfit_id, image_id):
        if not isinstance(image_id, str):
            bad("full_image_id and face_image_id must be image ids")
        image = self.core.store.image(image_id)
        task = self.core.store.task(image["task_id"])
        if task.get("snapshot", {}).get("purpose") != "reference_sample":
            bad("참조 샘플 Task의 이미지만 참조 세트로 확정할 수 있습니다", "CORE_REFERENCE_IMAGE_INVALID", 409)
        if task["state"] != "generated":
            bad("참조 샘플 이미지 생성이 완료되지 않았습니다", "CORE_REFERENCE_IMAGE_INVALID", 409)
        group = self.core.store.group(task["group_id"])
        if group["outfit_id"] != outfit_id:
            bad("이 의상의 참조 샘플이 아닙니다", "CORE_REFERENCE_IMAGE_INVALID", 409)
        return image, task

    @staticmethod
    def _settings_summary(snapshot):
        gen = snapshot["generation_inputs"]
        return {
            "diffusion_model": gen.get("diffusion_model"),
            "text_encoder": gen.get("text_encoder"),
            "common_fragments": [{"id": item["id"], "revision": item["revision"]} for item in snapshot.get("common_fragments", [])],
            "positive_quality": snapshot.get("settings", {}).get("positive_quality", ""),
            "loras": gen.get("loras", []),
        }

    def _write_revision(self, outfit_id, key, fingerprint, build):
        if not isinstance(key, str) or not 1 <= len(key) <= 200:
            bad("Idempotency-Key of 1..200 characters is required")
        row = self.db.execute("SELECT fingerprint,revision FROM reference_set_requests WHERE request_key=?", (key,)).fetchone()
        if row:
            if row[0] != fingerprint:
                bad("Reference set confirmation key already has different content", "CORE_IDEMPOTENCY_CONFLICT", 409)
            return self.revision_document(outfit_id, row[1]), False
        with self.db:
            current = self.status(outfit_id)["set"]
            new_revision = (current["revision"] + 1) if current else 1
            document = build(current, new_revision)
            self.db.execute("INSERT OR REPLACE INTO reference_sets VALUES(?,?)", (outfit_id, canonical(document)))
            self.db.execute("INSERT INTO reference_set_revisions VALUES(?,?,?)", (outfit_id, new_revision, canonical(document)))
            self.db.execute("INSERT INTO reference_set_requests VALUES(?,?,?,?)", (key, fingerprint, outfit_id, new_revision))
        return document, True

    def confirm(self, outfit_id, key, body):
        _fields(body, {"full_image_id", "face_image_id"}, {"full_image_id", "face_image_id"})
        outfit = self.core.store.entity(outfit_id, "outfits")
        character = self.core.store.entity(outfit["parent_id"], "characters")
        full_image, full_task = self._reference_image(outfit_id, body["full_image_id"])
        face_image, face_task = self._reference_image(outfit_id, body["face_image_id"])
        full_seed = full_task["snapshot"]["generation_inputs"]["seed"]
        face_seed = face_task["snapshot"]["generation_inputs"]["seed"]
        # ADR-0027/UX follow-up: full and face may come from different sample
        # pairs (and therefore different seeds) as long as both were produced
        # with the same generation settings, so the outfit's grain/style stays
        # consistent. Reject only when the settings actually differ, and name
        # which fields differ in the error.
        full_settings = self._settings_summary(full_task["snapshot"])
        face_settings = self._settings_summary(face_task["snapshot"])
        diff_fields = [key for key in full_settings if full_settings[key] != face_settings.get(key)]
        if diff_fields:
            names = ", ".join(SETTINGS_SUMMARY_LABELS.get(name, name) for name in diff_fields)
            bad(f"전신·얼굴 참조 이미지의 생성 설정이 서로 다릅니다: {names}", "CORE_REFERENCE_IMAGE_INVALID", 409)
        fingerprint = hashlib.sha256(canonical({"action": "confirm", "outfit_id": outfit_id, "body": body}).encode()).hexdigest()

        def build(current, revision):
            return {
                "id": str(uuid.uuid4()), "outfit_id": outfit_id, "revision": revision,
                "character_revision": character["revision"], "outfit_revision": outfit["revision"],
                "full": {"core_image_id": full_image["id"], "generation_image_id": full_image["generation_image_id"], "sha256": full_image["sha256"]},
                "face": {"core_image_id": face_image["id"], "generation_image_id": face_image["generation_image_id"], "sha256": face_image["sha256"]},
                "seed": full_seed, "face_seed": face_seed, "settings_summary": full_settings,
                "confirmed_at": time.time(),
            }
        return self._write_revision(outfit_id, key, fingerprint, build)

    def reconfirm(self, outfit_id, key, body):
        _fields(body, {"revision"}, {"revision"})
        if type(body["revision"]) is not int:
            bad("revision must be an integer")
        outfit = self.core.store.entity(outfit_id, "outfits")
        character = self.core.store.entity(outfit["parent_id"], "characters")
        current = self.status(outfit_id)["set"]
        if not current:
            bad("확정된 참조 세트가 없습니다", "CORE_REFERENCE_SET_REQUIRED", 409)
        if current["revision"] != body["revision"]:
            bad("참조 세트가 이미 변경되었습니다", "CORE_REVISION_CONFLICT", 409)
        fingerprint = hashlib.sha256(canonical({"action": "reconfirm", "outfit_id": outfit_id, "body": body}).encode()).hexdigest()

        def build(existing, revision):
            return {**existing, "revision": revision, "character_revision": character["revision"],
                    "outfit_revision": outfit["revision"], "confirmed_at": time.time()}
        return self._write_revision(outfit_id, key, fingerprint, build)

    # -- reference sample generation --------------------------------------------

    def _templates(self):
        return self.core.store.settings().get("reference_templates", DEFAULT_REFERENCE_TEMPLATES)

    @staticmethod
    def _role_size(sizes, role):
        """Validates an optional per-role {width,height} override: same range
        and multiple-of-16 rule as ordinary generation_inputs dimensions."""
        if sizes is None:
            return None
        if not isinstance(sizes, dict) or set(sizes) - {"full", "face"}:
            bad("sizes must have only 'full' and/or 'face' entries")
        value = sizes.get(role)
        if value is None:
            return None
        if not isinstance(value, dict) or set(value) != {"width", "height"}:
            bad(f"sizes.{role} must be an object with width and height")
        for name in ("width", "height"):
            if type(value[name]) is not int or not 256 <= value[name] <= 1920:
                bad(f"sizes.{role}.{name} must be an integer in 256..1920")
            if value[name] % 16:
                bad(f"sizes.{role}.{name} must be a multiple of 16")
        return {"width": value["width"], "height": value["height"]}

    def create_sample_pair(self, outfit_id, key, body):
        if not isinstance(key, str) or not 1 <= len(key) <= 200:
            bad("Idempotency-Key of 1..200 characters is required")
        _fields(body, {"generation_inputs", "common_fragments", "postprocess", "sizes"}, {"generation_inputs"})
        fingerprint = hashlib.sha256(canonical({"outfit_id": outfit_id, "body": body}).encode()).hexdigest()
        old = self.db.execute("SELECT fingerprint,document FROM reference_sample_pairs WHERE request_key=?", (key,)).fetchone()
        if old:
            if old[0] != fingerprint:
                bad("Reference sample key already has different content", "CORE_IDEMPOTENCY_CONFLICT", 409)
            return json.loads(old[1]), False
        gen_input = body["generation_inputs"]
        if not isinstance(gen_input, dict):
            bad("generation_inputs must be an object")
        role_sizes = {role: self._role_size(body.get("sizes"), role) for role in ("full", "face")}
        group = self.core.store.find_or_create_group(outfit_id)
        templates = self._templates()
        seed = gen_input.get("seed", -1)
        if seed == -1:
            seed = secrets.randbelow(2**53)
        pair_id = str(uuid.uuid4())
        task_ids = {}
        for role in ("full", "face"):
            template = templates[role]
            role_generation_inputs = dict(gen_input, seed=seed)
            if role_sizes[role]:
                role_generation_inputs.update(role_sizes[role])
            payload = {"group_id": group["id"], "framing": "custom", "framing_prompt": template["framing_prompt"],
                       "include": dict(template["include"]), "generation_inputs": role_generation_inputs,
                       "consistency": None}
            if "common_fragments" in body:
                payload["common_fragments"] = body["common_fragments"]
            if "postprocess" in body:
                payload["postprocess"] = body["postprocess"]
            preview = self.core.preview(payload)
            snapshot = preview["snapshot"]
            snapshot["purpose"] = "reference_sample"
            prefix = snapshot.get("output_name_prefix") or self.core.output_prefix(group)
            snapshot["generation_inputs"]["output_name"] = build_output_name(*prefix, "reference", f"{role}-{pair_id[:8]}")
            task_key = f"reference-sample:{pair_id}:{role}"
            task_fingerprint = hashlib.sha256(canonical(snapshot).encode()).hexdigest()
            task = self.core.store.create_task(task_key, task_fingerprint, group["id"], snapshot)
            task_ids[role] = task["id"]
        document = {"id": pair_id, "outfit_id": outfit_id, "seed": seed, "full_task_id": task_ids["full"],
                    "face_task_id": task_ids["face"], "created_at": time.time()}
        with self.db:
            self.db.execute("INSERT INTO reference_sample_pairs VALUES(?,?,?,?,?)",
                            (pair_id, outfit_id, key, fingerprint, canonical(document)))
        return document, True

    def list_sample_pairs(self, outfit_id, include_archived=False):
        self.core.store.entity(outfit_id, "outfits")
        rows = self.db.execute("SELECT document FROM reference_sample_pairs WHERE outfit_id=? ORDER BY rowid DESC", (outfit_id,)).fetchall()
        items = []
        for row in rows:
            pair = json.loads(row[0])
            if pair.get("archived") and not include_archived:
                continue
            items.append({**pair, "full_task": self.core.store.task(pair["full_task_id"]),
                          "face_task": self.core.store.task(pair["face_task_id"])})
        return {"items": items}

    # -- reference sample deletion -----------------------------------------------

    def _pair_document(self, outfit_id, pair_id):
        row = self.db.execute("SELECT document FROM reference_sample_pairs WHERE id=? AND outfit_id=?", (pair_id, outfit_id)).fetchone()
        return json.loads(row[0]) if row else None

    def delete_sample_pair(self, outfit_id, pair_id):
        """Archives (hides) a sample pair from the sample list without deleting
        its Tasks/images -- those remain reachable from the gallery. Repeat
        deletes of an already-archived pair are a no-op that still returns 200
        (idempotent by effect, not by Idempotency-Key)."""
        self.core.store.entity(outfit_id, "outfits")
        pair = self._pair_document(outfit_id, pair_id)
        if not pair:
            bad("Reference sample pair not found", "CORE_NOT_FOUND", 404)
        if pair.get("archived"):
            return pair
        full_task = self.core.store.task(pair["full_task_id"])
        face_task = self.core.store.task(pair["face_task_id"])
        if full_task["state"] in ACTIVE_TASK_STATES or face_task["state"] in ACTIVE_TASK_STATES:
            bad("참조 샘플 생성이 진행 중입니다. 완료 후 다시 시도하세요", "CORE_REFERENCE_SAMPLE_IN_USE", 409)
        image_ids = {image["id"] for task in (full_task, face_task) for image in (task.get("images") or [])}
        revision_rows = self.db.execute("SELECT document FROM reference_set_revisions WHERE outfit_id=?", (outfit_id,)).fetchall()
        for row in revision_rows:
            revision = json.loads(row[0])
            if revision["full"]["core_image_id"] in image_ids or revision["face"]["core_image_id"] in image_ids:
                bad("참조 세트에서 사용 중인 이미지는 목록에서 삭제할 수 없습니다", "CORE_REFERENCE_SAMPLE_IN_USE", 409)
        pair = {**pair, "archived": True}
        with self.db:
            self.db.execute("UPDATE reference_sample_pairs SET document=? WHERE id=? AND outfit_id=?", (canonical(pair), pair_id, outfit_id))
        return pair

    # -- routes -------------------------------------------------------------------

    def attach(self, app):
        async def samples(request):
            outfit_id = request.match_info["id"]
            if request.method == "GET":
                include_archived = request.query.get("include_archived") == "true"
                return web.json_response(self.list_sample_pairs(outfit_id, include_archived))
            document, created = self.create_sample_pair(outfit_id, request.headers.get("Idempotency-Key"), await request.json())
            return web.json_response(document, status=201 if created else 200)

        async def delete_sample(request):
            document = self.delete_sample_pair(request.match_info["id"], request.match_info["pair_id"])
            return web.json_response(document, status=200)

        async def reference_set(request):
            return web.json_response(self.status(request.match_info["id"]))

        async def confirm(request):
            document, created = self.confirm(request.match_info["id"], request.headers.get("Idempotency-Key"), await request.json())
            return web.json_response(document, status=201 if created else 200)

        async def reconfirm(request):
            document, created = self.reconfirm(request.match_info["id"], request.headers.get("Idempotency-Key"), await request.json())
            return web.json_response(document, status=201 if created else 200)

        async def revisions(request):
            limit, offset = _page(request.query)
            return web.json_response(self.history(request.match_info["id"], limit, offset))

        app.add_routes([
            web.get("/v1/outfits/{id}/reference-samples", samples), web.post("/v1/outfits/{id}/reference-samples", samples),
            web.delete("/v1/outfits/{id}/reference-samples/{pair_id}", delete_sample),
            web.get("/v1/outfits/{id}/reference-set", reference_set),
            web.post("/v1/outfits/{id}/reference-set/confirm", confirm),
            web.post("/v1/outfits/{id}/reference-set/reconfirm", reconfirm),
            web.get("/v1/outfits/{id}/reference-set/revisions", revisions),
        ])
