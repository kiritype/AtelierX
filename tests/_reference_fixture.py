"""Shared ADR-0027 P5 test fixture: confirm a valid reference set for an outfit.

REST test classes across the suite share the ``async def request(method, path,
body=None, key=None)`` shape (see ``tests/test_core.py``). This helper drives
the real reference-sample generation + confirm endpoints through that same
method so every real ``create_app()``-backed test can obtain a ``valid``
reference set before creating ordinary Tasks/plans, without duplicating the
polling loop in each test file.
"""
import asyncio
import hashlib
import uuid


def confirm_reference_set_offline(core, group_id, outfit_id, generation_inputs, key="reference-fixture"):
    """Build+confirm a reference set without a reachable Generation backend.

    For fixtures whose Core worker never runs or whose Generation endpoint is
    unreachable/unstubbed (they only assert on immediate REST responses), this
    drives ``core.preview``/``store.create_task``/``store.finish_generation``/
    ``reference_sets.confirm`` directly instead of waiting on real generation.
    """
    gen = dict(generation_inputs, seed=generation_inputs.get("seed", 1) if generation_inputs.get("seed", -1) != -1 else 1)
    images = {}
    for role, framing_prompt, include in (
            ("full", "full body ref", {"upper": True, "lower": True, "accessories": True, "hands": True}),
            ("face", "face ref", {"upper": True, "lower": False, "accessories": True, "hands": False})):
        snapshot = core.preview({"group_id": group_id, "framing": "custom", "framing_prompt": framing_prompt,
                                 "include": include, "generation_inputs": gen, "consistency": None})["snapshot"]
        snapshot["purpose"] = "reference_sample"
        task = core.store.create_task(f"{key}:{role}", f"{key}:{role}:fp", group_id, snapshot)
        image = {"id": str(uuid.uuid4()), "task_id": task["id"], "group_id": group_id,
                 "generation_image_id": str(uuid.uuid4()) + "-0", "sha256": hashlib.sha256(task["id"].encode()).hexdigest(),
                 "bytes": 7, "media_type": "image/png", "validation_state": "not_requested"}
        core.store.finish_generation(task, [image])
        images[role] = image["id"]
    return core.reference_sets.confirm(outfit_id, key + ":confirm",
                                       {"full_image_id": images["full"], "face_image_id": images["face"]})


async def confirm_reference_set(request, outfit_id, generation_inputs, key=None, timeout=10.0):
    key = key or "reference-samples:" + outfit_id
    status, pair = await request("POST", f"/v1/outfits/{outfit_id}/reference-samples",
                                 {"generation_inputs": generation_inputs}, key)
    assert status in (200, 201), pair
    images = {}
    for role in ("full", "face"):
        task_id = pair[f"{role}_task_id"]
        deadline = asyncio.get_event_loop().time() + timeout
        task = None
        while asyncio.get_event_loop().time() < deadline:
            _, task = await request("GET", f"/v1/tasks/{task_id}")
            if task["state"] in ("generated", "failed", "cancelled"):
                break
            await asyncio.sleep(0.01)
        assert task is not None and task["state"] == "generated", task
        png = next((image for image in task["images"] if image["media_type"] == "image/png"), task["images"][0])
        images[role] = png["id"]
    status, confirmed = await request("POST", f"/v1/outfits/{outfit_id}/reference-set/confirm",
                                      {"full_image_id": images["full"], "face_image_id": images["face"]}, key + ":confirm")
    assert status in (200, 201), confirmed
    return confirmed
