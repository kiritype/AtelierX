"""Paged queue views and resumable-by-snapshot SSE notifications."""
import asyncio
import hashlib
import json
from aiohttp import web


def attach_queue_api(app, rows):
    def snapshot():
        items = rows()
        return [{key: row[key] for key in ("id", "job_id", "kind", "state", "created_at", "updated_at", "outcome", "cancel_requested") if key in row} for row in items]

    async def queue(request):
        try:
            limit, offset = int(request.query.get("limit", 50)), int(request.query.get("offset", 0))
            if not 1 <= limit <= 200 or offset < 0: raise ValueError()
        except ValueError:
            return web.json_response({"error": {"code": "QUEUE_INVALID_PAGE", "message": "limit must be 1..200 and offset nonnegative"}}, status=400)
        items = snapshot()
        if request.query.get("state"):
            items = [item for item in items if item["state"] == request.query["state"]]
        items.sort(key=lambda item: (item.get("created_at", 0), item.get("id", item.get("job_id", ""))))
        return web.json_response({"items": items[offset:offset+limit], "limit": limit, "offset": offset, "total": len(items)})

    async def events(request):
        response = web.StreamResponse(headers={"Content-Type": "text/event-stream", "Cache-Control": "no-cache"})
        await response.prepare(request)
        previous, ticks = None, 0
        try:
            while request.transport is not None and not request.transport.is_closing():
                items = snapshot()
                current = {item.get("id", item.get("job_id")): item for item in items}
                if current != previous:
                    changed = list(current.values()) if previous is None else [v for k, v in current.items() if previous.get(k) != v]
                    removed = [] if previous is None else list(previous.keys() - current.keys())
                    data = json.dumps({"items": changed, "removed": removed}, ensure_ascii=False, sort_keys=True)
                    revision = hashlib.sha256(json.dumps(current, sort_keys=True).encode()).hexdigest()
                    event = "reset" if previous is None else "changed"
                    await response.write(f"id: {revision}\nevent: {event}\ndata: {data}\n\n".encode())
                    previous = current
                elif ticks % 15 == 0:
                    await response.write(b": heartbeat\n\n")
                ticks += 1
                await asyncio.sleep(1)
        except (ConnectionError, asyncio.CancelledError):
            pass
        return response

    app.add_routes([web.get("/v1/queue", queue), web.get("/v1/events", events)])
