"""Pairwise consistency within a frozen group reference, one durable parent job."""
import base64
import io
import json
import asyncio
import aiohttp
from itertools import combinations
from .common import ApiError, canonical
from .provider_response import diagnostics as provider_response_diagnostics, was_truncated

STATUSES = {"matched", "mismatch", "insufficient", "reference_conflict"}
IDENTITY_ATTRIBUTES = ("hair_length", "hair_style", "hair_color", "eye_color", "facial_features", "clothing", "accessories", "body_features")


def summary(items):
    counts = {key: sum(item["status"] == key for item in items) for key in (*sorted(STATUSES), "error")}
    state = "mismatch" if counts["mismatch"] else "matched" if items and counts["matched"] == len(items) else "incomplete"
    return {"state": state, "counts": counts, "review_image_ids": [item["image_ref"] for item in items if item["status"] != "matched"]}


def request_body(raw, single_parser):
    required = {"group_id", "reference_revision", "representative", "auxiliaries", "targets", "identity", "profile", "provider"}
    def bad(message): raise ApiError("VAL_GROUP_INPUT_INVALID", message, 400)
    if not isinstance(raw, dict) or set(raw) != required: bad("Missing or unknown group fields")
    if not isinstance(raw["group_id"], str) or not raw["group_id"].strip(): bad("group_id required")
    if type(raw["reference_revision"]) is not int or raw["reference_revision"] < 1: bad("Positive reference revision required")
    profile = raw["profile"]
    if not isinstance(profile, dict) or set(profile) != {"profile_id", "revision", "consistency"} or profile["consistency"] is not True: bad("Select a group consistency profile")
    if not isinstance(profile["profile_id"], str) or not profile["profile_id"] or type(profile["revision"]) is not int or profile["revision"] < 1: bad("Invalid profile revision")
    identity = raw["identity"]
    if not isinstance(identity, dict) or not identity or set(identity) - {"appearance", "upper", "lower"} or any(not isinstance(v, str) or not v.strip() for v in identity.values()): bad("Visible identity requirements required")
    if not isinstance(raw["auxiliaries"], list) or len(raw["auxiliaries"]) > 2: bad("At most two auxiliary images supported")
    if not isinstance(raw["targets"], list) or not 1 <= len(raw["targets"]) <= 32: bad("Select 1..32 targets")
    images = [raw["representative"], *raw["auxiliaries"], *raw["targets"]]
    parsed = []
    for image in images:
        dummy = {"profile_id": "input-check", "revision": 1, "positive_prompt": True, "negative_prompt": False,
                 "output_conditions": False, "body_parts": [], "metadata": False, "consistency": False}
        parsed.append(single_parser({"image": image, "generation_attempt_id": None, "profile": dummy,
                                     "provider": raw["provider"], "expected_output": None})["image"])
    if len({image["ref"] for image in parsed}) != len(parsed): bad("Reference and target identifiers must be distinct")
    return dict(raw, representative=parsed[0], auxiliaries=parsed[1:1 + len(raw["auxiliaries"])], targets=parsed[1 + len(raw["auxiliaries"]):])


def schema(identity, references=None):
    references = list(references or [])
    return {"type": "object", "additionalProperties": False, "required": ["assessments"], "properties": {
        "assessments": {"type": "array", "minItems": len(identity), "maxItems": len(identity), "items": {"type": "object", "additionalProperties": False,
            "required": ["feature", "status", "reference_observed", "target_observed", "differences", "reference_refs"], "properties": {
                "feature": {"type": "string", "enum": list(identity)},
                "status": {"type": "string", "enum": sorted(STATUSES)},
                "reference_observed": {"type": "object", "properties": {ref: {"type": "string"} for ref in references}, "required": references, "additionalProperties": False}, "target_observed": {"type": "string"},
                "differences": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                    "required": ["attribute", "description"], "properties": {"attribute": {"type": "string", "enum": list(IDENTITY_ATTRIBUTES)}, "description": {"type": "string"}}}},
                "reference_refs": {"type": "array", "uniqueItems": True, "maxItems": len(references), "items": {"type": "string", **({"enum": references} if references else {})}}}}}}}


def normalize(answer, identity, references):
    def invalid(): raise ApiError("VAL_PROVIDER_RESPONSE_INVALID", "Invalid group feature evidence", 502)
    if not isinstance(answer, dict) or set(answer) != {"assessments"} or not isinstance(answer["assessments"], list): invalid()
    seen = set()
    for item in answer["assessments"]:
        if not isinstance(item, dict) or set(item) != {"feature", "status", "reference_observed", "target_observed", "differences", "reference_refs"}: invalid()
        feature, status = item["feature"], item["status"]
        if not isinstance(feature, str) or feature not in identity or feature in seen or not isinstance(status, str) or status not in STATUSES: invalid()
        seen.add(feature)
        if not isinstance(item["reference_observed"], dict) or not isinstance(item["target_observed"], str) or not item["target_observed"].strip(): invalid()
        if not isinstance(item["differences"], list) or any(not isinstance(value, dict) or set(value) != {"attribute", "description"} or value["attribute"] not in IDENTITY_ATTRIBUTES or not isinstance(value["description"], str) or not value["description"].strip() for value in item["differences"]): invalid()
        refs = item["reference_refs"]
        if not isinstance(refs, list) or any(not isinstance(ref, str) or ref not in references for ref in refs): invalid()
        if len(set(refs)) != len(refs): invalid()
        if any(not isinstance(ref, str) or ref not in references for ref in item["reference_observed"]) or any(not isinstance(value, str) or not value.strip() for value in item["reference_observed"].values()): invalid()
        if refs and set(item["reference_observed"]) != set(refs): invalid()
        if status in {"matched", "mismatch"} and not refs: invalid()
        # Structural evidence prevents a model from recording a concrete visual
        # difference and nevertheless returning a matched verdict.
        if status == "matched" and item["differences"]: invalid()
        if status == "mismatch" and not item["differences"]: invalid()
        if status == "matched" and set(refs) != set(references): invalid()
        if status == "reference_conflict" and len(set(refs)) < 2: invalid()
    if seen != set(identity): invalid()
    statuses = {item["status"] for item in answer["assessments"]}
    status = next((value for value in ("reference_conflict", "mismatch", "insufficient") if value in statuses), "matched")
    return {"status": status, "evidence": answer["assessments"], "error": None}


async def compare(service, job, target, references, *, assessment_key="provider_assessments", response_key="provider_responses", record_id=None):
    request = job["request"]
    config = service.registry.provider(request["provider"]) if service.registry.enabled else service.providers[request["provider"]["provider_id"]]
    content = [{"type": "text", "text": "Shared identity: " + canonical(request["identity"])}]
    for role, image in [("reference", image) for image in references] + [("target", target)]:
        data, media = await service.image_bytes({"image": image, "profile": {"output_conditions": False}, "expected_output": None})
        if config.get("image_format", "original") == "png":
            from PIL import Image
            buffer = io.BytesIO()
            with Image.open(io.BytesIO(data)) as decoded: decoded.save(buffer, format="PNG")
            data, media = buffer.getvalue(), "image/png"
        content.extend([{"type": "text", "text": canonical({"role": role, "ref": image["ref"], "positive_prompt": image["positive_prompt"]})},
                        {"type": "image_url", "image_url": {"url": "data:" + media + ";base64," + base64.b64encode(data).decode()}}])
    mode = config.get("response_format", "json_object")
    response_format = {"type": mode} if mode != "json_schema" else {"type": "json_schema", "json_schema": {"name": "atelierx_group_evidence", "strict": True, "schema": schema(request["identity"], [i["ref"] for i in references])}}
    rubric = ("Compare the target with the representative (first reference) and optional auxiliary images. "
              "Assess each shared identity feature once from the actual pixels in the reference and target images. "
              "Only the requested shared identity categories matter; expression, pose, framing and lighting are allowed changes. The prompt labels which identity features matter but does not prove that they match. "
              "Inspect every supplied reference before assessing the target. When multiple references are supplied, reference_observed must give a separate observation for each reference ID. If references disagree on a requested identity feature, return reference_conflict before judging the target. "
              "Compare each requested category independently: appearance covers character traits, upper covers only upper clothing, and lower covers only lower clothing. Hair or facial details are never upper/lower mismatch evidence, and upper clothing is never appearance/lower mismatch evidence. "
              "A requested identity difference is mismatch even when both images satisfy the prompt. A reference conflict occurs when references disagree on that requested category, even if the target matches one reference. "
              "differences contains only identity attributes: hair_length, hair_style, hair_color, eye_color, facial_features, clothing, accessories, or body_features, each with a concrete description. "
              "Pose, framing, expression and lighting are allowed variations: they may be mentioned in observations but never included in differences and never cause mismatch. "
              "Use matched only when no relevant visual difference is observed and differences is []. If visibility or certainty is insufficient, return insufficient, never invent details. "
              "Conflicting references require reference_conflict, never majority voting or blaming the target. "
              "Return JSON assessments, each with feature, status (matched/mismatch/insufficient/reference_conflict), "
              "reference_observed keyed by reference ID, target_observed, differences, and reference_refs. A matched assessment must cite every supplied reference. No regeneration proposals.")
    try:
        body = {"model": request["provider"]["model"], "messages": [{"role": "system", "content": rubric}, {"role": "user", "content": content}], "response_format": response_format, "temperature": 0}
        if "max_tokens" in config:
            body["max_tokens"] = config["max_tokens"]
        async with service.session.post(config["url"].rstrip("/") + "/chat/completions",
            headers={"Authorization": "Bearer " + config["api_key"]}, allow_redirects=False,
            timeout=aiohttp.ClientTimeout(total=request["provider"]["timeout_seconds"]),
            json=body) as response:
            if response.status != 200: raise ApiError("VAL_PROVIDER_HTTP_ERROR", "Vision provider returned HTTP " + str(response.status), 502)
            data = bytearray()
            async for chunk in response.content.iter_chunked(65536):
                data.extend(chunk)
                if len(data) > 1024 * 1024: raise ApiError("VAL_PROVIDER_RESPONSE_INVALID", "Provider response exceeds limit", 502)
            payload = json.loads(data)
            record_id = record_id or target["ref"]
            job.setdefault(response_key, {})[record_id] = provider_response_diagnostics(payload)
            service.save(job)
            if was_truncated(payload):
                raise ApiError("VAL_PROVIDER_RESPONSE_INVALID", "Provider response was truncated", 502)
            answer = json.loads(payload["choices"][0]["message"]["content"])
            job.setdefault(assessment_key, {})[record_id] = answer
            service.save(job)
            return normalize(answer, request["identity"], {i["ref"] for i in references})
    except asyncio.TimeoutError as exc: raise ApiError("VAL_PROVIDER_TIMEOUT", "Vision provider timed out", 504) from exc
    except aiohttp.ClientError as exc: raise ApiError("VAL_PROVIDER_UNAVAILABLE", "Vision provider unavailable", 503) from exc
    except (ValueError, KeyError, TypeError) as exc: raise ApiError("VAL_PROVIDER_RESPONSE_INVALID", "Invalid group response", 502) from exc


def pair_id(first, second):
    return canonical([first["ref"], second["ref"]])


def conflict_evidence(checks):
    """Expose completed pair evidence without pretending it observed a target."""
    return [{"reference_refs": [check["reference_ref"], check["comparison_ref"]],
             "evidence": [item for item in check["evidence"] if item["status"] == "mismatch"]}
            for check in checks.values()
            if check.get("state") == "completed" and check.get("status") == "mismatch"]


def conflicted_target_evidence(identity, conflicts):
    """Cover every required feature without inventing a target observation."""
    result = []
    for feature in identity:
        supporting = next((conflict for conflict in conflicts
                           if any(item["feature"] == feature for item in conflict["evidence"])), None)
        if supporting:
            pair = next(item for item in supporting["evidence"] if item["feature"] == feature)
            first, second = supporting["reference_refs"]
            # The original pair evidence remains item-level audit data. This
            # v8-compatible assessment only changes roles: pair target is the
            # second reference, while the requested target was never observed.
            result.append({"feature": feature, "status": "reference_conflict",
                           "reference_observed": {first: pair["reference_observed"][first], second: pair["target_observed"]},
                           "target_observed": "Not compared due to reference conflict",
                           "differences": pair["differences"], "reference_refs": [first, second]})
        else:
            result.append({"feature": feature, "status": "insufficient", "reference_observed": {},
                           "target_observed": "Not compared due to reference conflict",
                           "differences": [], "reference_refs": []})
    return result


def reference_precheck_errors(checks):
    return [{"reference_refs": [check["reference_ref"], check["comparison_ref"]], "error": check["error"]}
            for check in checks.values()
            if check.get("state") == "completed" and check.get("status") == "error"]


async def validate_target(service, target):
    """Keep target access/integrity checks even when conflicted refs skip inference."""
    await service.image_bytes({"image": target, "profile": {"output_conditions": False}, "expected_output": None})


async def precheck_references(service, job, references):
    """Compare every reference pair before a target request can be submitted."""
    checks = job.setdefault("reference_checks", {})
    for first, second in combinations(references, 2):
        identifier = pair_id(first, second)
        check = checks.get(identifier)
        if check and check.get("state") == "completed":
            continue
        if job.get("cancel_requested"):
            return False
        # The record precedes the outbound submission. A restarted running job
        # is rejected by Validation.run rather than replaying this comparison.
        check = {"reference_ref": first["ref"], "comparison_ref": second["ref"],
                 "state": "submitting", "status": None, "evidence": [], "error": None}
        checks[identifier] = check
        job.update(state="running", phase="reference_precheck", active_reference_pair=identifier)
        service.save(job)
        try:
            result = await compare(service, job, second, [first], assessment_key="reference_assessments",
                                   response_key="reference_responses", record_id=identifier)
            check.update(state="completed", status=result["status"], evidence=result["evidence"], error=None,
                         provider_response=job.get("reference_responses", {}).get(identifier, {}))
        except ApiError as exc:
            check.update(state="completed", status="error", evidence=[],
                         error={"code": exc.code, "message": exc.message},
                         provider_response=job.get("reference_responses", {}).get(identifier, {}))
            service.save(job)
            if exc.code in {"VAL_PROVIDER_TIMEOUT", "VAL_PROVIDER_UNAVAILABLE"}:
                job.update(state="failed", outcome="error", result=None, error=dict(check["error"], stage="provider"))
                service.save(job)
                return None
        service.save(job)
    return not job.get("cancel_requested")


async def run(service, job):
    references = [job["request"]["representative"], *job["request"]["auxiliaries"]]
    checks_ready = await precheck_references(service, job, references)
    if checks_ready is None:
        return  # Provider may still be running; retain GPU lease and do not start another inference.
    if checks_ready is False:
        # Match the normal post-provider cancellation path: persist a terminal
        # result so Validation.save discards it as a late cancelled result.
        job.update(state="completed", phase="cancelled", outcome="incomplete",
                   result={"items": job.get("partial_results", []), "summary": summary(job.get("partial_results", []))}, error=None)
        service.save(job)
        return
    conflicts = conflict_evidence(job.get("reference_checks", {}))
    precheck_errors = reference_precheck_errors(job.get("reference_checks", {}))
    items = job.setdefault("partial_results", [])
    completed_refs = {item["image_ref"] for item in items}
    for target in job["request"]["targets"]:
        if job.get("cancel_requested"):
            break
        if target["ref"] in completed_refs:
            continue
        job.update(state="running", phase="target_comparison", active_target=target["ref"])
        service.save(job)  # Before remote submission: crash never silently repeats inference.
        try:
            if precheck_errors:
                await validate_target(service, target)
                item = {"status": "error", "evidence": [], "reference_precheck_errors": precheck_errors,
                        "error": dict(precheck_errors[0]["error"])}
            elif conflicts:
                await validate_target(service, target)
                item = {"status": "reference_conflict", "evidence": conflicted_target_evidence(job["request"]["identity"], conflicts), "reference_evidence": conflicts,
                        "target_not_compared": True, "error": None}
            else:
                item = await compare(service, job, target, references)
        except ApiError as exc:
            item = {"status": "error", "evidence": [], "error": {"code": exc.code, "message": exc.message}}
        items.append(dict(item, image_ref=target["ref"]))
        service.save(job)
        if item.get("error", {}) and item["error"]["code"] in {"VAL_PROVIDER_TIMEOUT", "VAL_PROVIDER_UNAVAILABLE"}:
            job.update(state="failed", outcome="error", result=None, error=dict(item["error"], stage="provider"))
            service.save(job)
            return  # Provider may still be running; retain GPU lease and do not start another inference.
    job.update(state="completed", phase="completed", outcome="failed" if any(i["status"] == "mismatch" for i in items) else "passed" if items and all(i["status"] == "matched" for i in items) else "incomplete",
               result={"items": items, "summary": summary(items)}, error=None)
    service.save(job)
