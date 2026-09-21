"""Read-only, paginated Task and group-batch browse queries for Core."""
from __future__ import annotations

import json
import re

from .common import ApiError


TASK_FILTERS = {"group_id", "work_id", "character_id", "outfit_id", "state"}
BATCH_FILTERS = {"group_id", "state"}
PAGING = {"limit", "offset"}
_INTEGER = re.compile(r"[0-9]+\Z")
_SQLITE_INTEGER_MAX = 9_223_372_036_854_775_807


def _invalid(message):
    raise ApiError("CORE_INVALID_INPUT", message, 400)


def _values(query):
    """Return a single-value query map, rejecting duplicate and empty inputs."""
    if not hasattr(query, "keys") or not hasattr(query, "get"):
        _invalid("Query must be a mapping")
    values = {}
    for key in set(query.keys()):
        entries = query.getall(key) if hasattr(query, "getall") else [query.get(key)]
        if len(entries) != 1:
            _invalid("Duplicate query parameter: " + str(key))
        value = entries[0]
        if not isinstance(key, str) or not isinstance(value, str) or not value.strip():
            _invalid("Query parameters must be non-empty text")
        values[key] = value
    return values


def _query(query, filters):
    values = _values(query)
    unknown = set(values) - filters - PAGING
    if unknown:
        _invalid("Unknown query parameter: " + sorted(unknown)[0])
    for key, default, minimum, maximum in (("limit", 50, 1, 200), ("offset", 0, 0, None)):
        raw = values.get(key, str(default))
        if not _INTEGER.fullmatch(raw):
            _invalid(key + " must be an integer")
        try:
            number = int(raw)
        except ValueError:
            _invalid(key + " must be an integer")
        if number < minimum or number > _SQLITE_INTEGER_MAX or maximum is not None and number > maximum:
            _invalid("limit must be 1..200 and offset nonnegative")
        values[key] = number
    return values


def list_tasks(core, query):
    """Return existing raw Task documents without mutating task/cycle state."""
    values = _query(query, TASK_FILTERS)
    clauses, params = [], []
    columns = {
        "group_id": "tasks.group_id",
        # A group records its category ancestry at creation. Browse filters must
        # retain that immutable relationship even if categories are archived or
        # later reorganized.
        "work_id": "json_extract(groups.document, '$.work_id')",
        "character_id": "json_extract(groups.document, '$.character_id')",
        "outfit_id": "json_extract(groups.document, '$.outfit_id')",
        "state": "tasks.state",
    }
    for key, column in columns.items():
        if key in values:
            clauses.append(column + "=?")
            params.append(values[key])
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    rows = core.store.db.execute(
        "SELECT tasks.document FROM tasks "
        "JOIN groups ON groups.id=tasks.group_id" + where +
        " ORDER BY tasks.created_at DESC,tasks.id ASC LIMIT ? OFFSET ?",
        (*params, values["limit"], values["offset"]),
    )
    return {"items": [json.loads(row[0]) for row in rows], "limit": values["limit"], "offset": values["offset"]}


def list_batches(core, query):
    """Return only the requested page of durable batch documents via SQLite."""
    values = _query(query, BATCH_FILTERS)
    clauses, params = [], []
    for key in ("group_id", "state"):
        if key in values:
            clauses.append("json_extract(document, '$." + key + "')=?")
            params.append(values[key])
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    rows = core.store.db.execute(
        "SELECT document FROM group_batches" + where +
        " ORDER BY json_extract(document, '$.created_at') DESC,json_extract(document, '$.id') ASC LIMIT ? OFFSET ?",
        (*params, values["limit"], values["offset"]),
    )
    return {"items": [json.loads(row[0]) for row in rows], "limit": values["limit"], "offset": values["offset"]}
