"""Read-only catalog projections for Core's browse endpoints.

The projections deliberately expose IDs and immutable/public metadata only.  They
do not turn a catalog request into a task, validation, or group mutation.
"""
from __future__ import annotations

import json
import uuid

from .common import ApiError


_PAGE_FIELDS = {"limit", "offset"}
_GROUP_FIELDS = _PAGE_FIELDS | {"work_id", "character_id", "outfit_id"}
_IMAGE_FIELDS = _PAGE_FIELDS | {
    "work_id", "character_id", "outfit_id", "group_id", "task_id",
    "media_type", "single_outcome", "group_status",
}
_MEDIA_TYPES = {"image/png", "image/webp"}
_SINGLE_OUTCOMES = {"unvalidated", "pending", "passed", "failed", "error", "cancelled"}
_GROUP_STATUSES = {"reference", "matched", "mismatch", "insufficient", "reference_conflict", "error", "unvalidated", "not_eligible", "stale"}


def _invalid(message):
    raise ApiError("CORE_INVALID_INPUT", message)


def _keys(query):
    return set(query.keys()) if hasattr(query, "keys") else set(query)


def _values(query, name):
    if hasattr(query, "getall"):
        return list(query.getall(name, []))
    if name not in query:
        return []
    value = query[name]
    return list(value) if isinstance(value, (list, tuple)) else [value]


def _one(query, name):
    values = _values(query, name)
    if len(values) > 1:
        _invalid(f"Duplicate query parameter: {name}")
    if not values:
        return None
    value = values[0]
    if not isinstance(value, str) or not value:
        _invalid(f"{name} must be a nonempty string")
    return value


def _uuid_filter(query, name):
    value = _one(query, name)
    if value is None:
        return None
    try:
        parsed = str(uuid.UUID(value))
    except (TypeError, ValueError, AttributeError):
        _invalid(f"{name} must be a canonical UUID")
    if parsed != value:
        _invalid(f"{name} must be a canonical UUID")
    return value


def _page(query, allowed):
    unknown = _keys(query) - allowed
    if unknown:
        _invalid("Unknown query parameter")
    limit = _one(query, "limit")
    offset = _one(query, "offset")
    try:
        limit = 50 if limit is None else int(limit)
        offset = 0 if offset is None else int(offset)
    except ValueError:
        _invalid("limit and offset must be integers")
    if not 1 <= limit <= 200 or not 0 <= offset <= 2**63 - 1:
        _invalid("limit must be 1..200 and offset nonnegative")
    return limit, offset


def _ordered(items):
    return sorted(items, key=lambda item: (-float(item.get("created_at", 0)), item["id"]))


def _group_item(group):
    result = {name: group[name] for name in ("id", "outfit_id", "character_id", "work_id", "outfit_revision", "components", "created_at")}
    if "reference" in group:
        result["reference"] = group["reference"]
    return result


def list_groups(core, query):
    """Return a stable, immutable-group catalog page from a request query mapping."""
    limit, offset = _page(query, _GROUP_FIELDS)
    filters = {name: _uuid_filter(query, name) for name in ("work_id", "character_id", "outfit_id")}
    clauses, values = [], []
    for name, value in filters.items():
        if value is not None:
            path = "$." + name
            clauses.append("json_extract(document, ?) = ?")
            values.extend((path, value))
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    total = core.store.db.execute("SELECT COUNT(*) FROM groups" + where, values).fetchone()[0]
    rows = core.store.db.execute(
        "SELECT document FROM groups" + where + " ORDER BY CAST(json_extract(document, '$.created_at') AS REAL) DESC,id ASC LIMIT ? OFFSET ?",
        [*values, limit, offset]).fetchall()
    return {"items": [_group_item(json.loads(row[0])) for row in rows], "limit": limit, "offset": offset, "total": total}


def _single_outcome(image, latest_run=None):
    validation = latest_run if latest_run is not None else image.get("validation")
    state = validation.get("state") if isinstance(validation, dict) else image.get("validation_state")
    if isinstance(validation, dict) and validation.get("outcome") in {"passed", "failed", "error"}:
        return validation["outcome"]
    if state in {"queued", "dispatching", "pending", "submitting", "running"}:
        return "pending"
    if state == "failed":
        return "error"
    if state == "cancelled":
        return "cancelled"
    return "unvalidated"


def _group_statuses(core, group_ids):
    """Reuse CoreGroups.status once per group, never once per image.

    That status already discards results for a stale reference revision and uses
    current_target_ids() to exclude superseded replacement descendants.
    """
    result = {}
    for group_id in group_ids:
        status = core.groups.status(group_id)
        reference = status.get("reference") or {}
        refs = {reference.get("representative_id"), *reference.get("auxiliary_ids", [])} - {None}
        current = set(status.get("target_ids", []))
        details = {item["image_ref"]: item for item in status.get("results", [])}
        historical = {}
        if reference:
            for run in core.groups.runs(group_id):
                if run["request"]["reference_revision"] != reference["revision"] and run["state"] == "completed":
                    historical.update({item["ref"]: run["id"] for item in run["request"]["targets"]})
        result[group_id] = (reference.get("revision") if reference else None, refs, current, details, historical)
    return result


def _group_status(image_id, group_status):
    reference_revision, refs, current, details, historical = group_status
    if reference_revision is None:
        return "unvalidated", None, None
    if image_id in refs:
        return "reference", None, reference_revision
    if image_id not in current:
        return ("stale", historical[image_id], reference_revision) if image_id in historical else ("not_eligible", None, reference_revision)
    current_result = details.get(image_id)
    if current_result and current_result.get("run_id"):
        return current_result["status"], current_result.get("run_id"), reference_revision
    if image_id in historical:
        return "stale", historical[image_id], reference_revision
    return "unvalidated", None, reference_revision


def _image_item(image, group, created_at, single_outcome, single_run_id, group_status, group_run_id, reference_revision):
    return {
        "id": image["id"], "task_id": image["task_id"], "group_id": image["group_id"],
        "work_id": group["work_id"], "character_id": group["character_id"], "outfit_id": group["outfit_id"],
        # Image records have no own timestamp; this is the accepted Task time.
        "created_at": created_at, "generation_image_id": image["generation_image_id"],
        "sha256": image["sha256"], "bytes": image["bytes"], "media_type": image["media_type"],
        "single_outcome": single_outcome, "single_validation_run_id": single_run_id,
        "group_status": group_status, "group_validation_run_id": group_run_id,
        "group_reference_revision": reference_revision,
        "content_url": "/v1/images/" + image["id"] + "/content",
    }


def list_images(core, query):
    """Return gallery metadata without files, snapshots, paths, or credentials."""
    limit, offset = _page(query, _IMAGE_FIELDS)
    identifiers = {name: _uuid_filter(query, name) for name in ("work_id", "character_id", "outfit_id", "group_id", "task_id")}
    media_type = _one(query, "media_type")
    if media_type is not None and media_type not in _MEDIA_TYPES:
        _invalid("media_type must be image/png or image/webp")
    single_filter = _one(query, "single_outcome")
    if single_filter is not None and single_filter not in _SINGLE_OUTCOMES:
        _invalid("Unknown single_outcome")
    group_filter = _one(query, "group_status")
    if group_filter is not None and group_filter not in _GROUP_STATUSES:
        _invalid("Unknown group_status")

    clauses, values = [], []
    for name, value in identifiers.items():
        if value is None:
            continue
        if name == "task_id":
            clauses.append("i.task_id=?")
        elif name == "group_id":
            clauses.append("t.group_id=?")
        else:
            clauses.append("json_extract(g.document, ?) = ?")
            values.append("$." + name)
        values.append(value)
    if media_type is not None:
        clauses.append("json_extract(i.document, '$.media_type') = ?")
        values.append(media_type)
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    rows = core.store.db.execute(
        "SELECT i.document,g.document,t.created_at FROM images i "
        "JOIN tasks t ON t.id=i.task_id JOIN groups g ON g.id=t.group_id" + where,
        values).fetchall()
    candidates = [(json.loads(row[0]), json.loads(row[1]), row[2]) for row in rows]

    latest = {}
    if candidates:
        image_ids = sorted({image["id"] for image, _, _ in candidates})
        # Keep below SQLite's usual 999 bound for a large gallery page/filter.
        for start in range(0, len(image_ids), 500):
            chunk = image_ids[start:start + 500]
            placeholders = ",".join("?" for _ in chunk)
            rows = core.store.db.execute(
                "SELECT image_id,document FROM validation_runs WHERE image_id IN (" + placeholders + ") "
                "ORDER BY image_id,created_at DESC,id ASC", chunk).fetchall()
            for row in rows:
                latest.setdefault(row[0], json.loads(row[1]))

    statuses = _group_statuses(core, {group["id"] for _, group, _ in candidates})
    projected = []
    for image, group, created_at in candidates:
        single = _single_outcome(image, latest.get(image["id"]))
        grouped, group_run_id, reference_revision = _group_status(image["id"], statuses[group["id"]])
        if (single_filter is not None and single != single_filter) or (group_filter is not None and grouped != group_filter):
            continue
        projected.append(_image_item(image, group, created_at, single, (latest.get(image["id"]) or {}).get("id"), grouped, group_run_id, reference_revision))
    projected = _ordered(projected)
    return {"items": projected[offset:offset + limit], "limit": limit, "offset": offset, "total": len(projected)}
