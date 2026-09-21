"""Rebuild reviewable JSON Schema and valid request/result examples."""
import json
from pathlib import Path
from contract_models import MODELS

ROOT = Path(__file__).parent


def write(path, value):
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def profile(group=False):
    return dict(profile_id="profile-default", revision=1, output_conditions=not group,
                positive_prompt=not group, negative_prompt=not group,
                body_parts=[], metadata=False, consistency=group)


PROVIDER = dict(provider_id="local-vision", revision=1, model="configured-vision-model", timeout_seconds=180)


def image(ref):
    return dict(ref=ref, source=dict(type="generation", server_id="generation-local",
                image_id=ref, sha256="a" * 64),
                positive_prompt="adult woman, blue eyes, black jacket, upper body",
                negative_prompt="text, watermark")


GROUP = dict(group_id="group-1", group_revision=3, reference_revision=2,
             work_id="work-1", character_id="character-1", outfit_id="outfit-1")
GENERATION = dict(requested=5, passed=4, generation_failed=1, validation_error=0, rejected=0, cancelled=0)
ERROR = dict(code="VAL_PROVIDER_TIMEOUT", message="Provider did not respond in time.", stage="provider")
FINDING = dict(code="ELEMENT_MISMATCH", feature="eyes", expected="blue", observed="brown", prompt_excerpt="blue eyes")


def examples():
    single = dict(schema_version="0.1", kind="single", image=image("img-1"),
                  generation_attempt_id="attempt-1", profile=profile(), provider=PROVIDER,
                  expected_output=dict(width=768, height=1024, media_type="image/png", alpha="not_required"),
                  generation_settings=dict(capability_revision="cap-1", seed=123, steps=24, cfg=4.5))
    group = dict(schema_version="0.1", kind="group", group=GROUP, scope="full",
                 images=[image(x) for x in ["ref-1", "img-1", "img-2", "img-3"]],
                 targets=["img-1", "img-2", "img-3"], primary_reference="ref-1", auxiliary_references=[],
                 common_features=[dict(name="eyes", expected="blue")],
                 generation_summary=GENERATION, profile=profile(True), provider=PROVIDER)
    base = dict(schema_version="0.1", kind="single", job_id="job-1", request_id="request-1",
                image_ref="img-1", evidence=dict(profile=profile(), provider=PROVIDER))
    passed = dict(base, outcome="passed", error=None, result=dict(findings=[], regeneration=dict(required=False, reason="All checks passed.", changes=[])))
    rejected = dict(base, outcome="rejected", error=None, result=dict(findings=[FINDING], regeneration=dict(required=True,
                    reason="Attempt another seed while retaining blue eyes.", changes=[dict(field="seed", value=124, reason="Eye color mismatch.")])))
    no_proposal = dict(base, outcome="rejected", error=None, result=dict(findings=[FINDING], regeneration=dict(required=False,
                      reason="Generation capability information unavailable.", changes=[])))
    failed = dict(base, outcome="error", result=None, error=ERROR)
    items = [dict(image_ref="img-1", compared_with=["ref-1"], verdict="match", findings=[], unavailable_features=[], error=None),
             dict(image_ref="img-2", compared_with=["ref-1"], verdict="mismatch", findings=[FINDING], unavailable_features=[], error=None),
             dict(image_ref="img-3", compared_with=["ref-1"], verdict="error", findings=[], unavailable_features=[], error=ERROR)]
    group_result = dict(schema_version="0.1", kind="group", job_id="job-group", request_id="req-group", group=GROUP,
                        scope="full", targets=group["targets"], primary_reference="ref-1", auxiliary_references=[], items=items,
                        counts=dict(match=1, mismatch=1, insufficient=0, error=1), summary="mismatch_present",
                        generation_summary=GENERATION, evidence=dict(profile=profile(True), provider=PROVIDER))
    partial = dict(group_result, scope="partial", targets=["img-1"], items=[items[0]],
                   counts=dict(match=1, mismatch=0, insufficient=0, error=0), summary="all_match")
    return {
        "single-request": ("single-request", single), "group-request": ("group-request", group),
        "single-passed": ("single-result", passed), "single-rejected": ("single-result", rejected),
        "single-rejected-no-proposal": ("single-result", no_proposal), "single-error": ("single-result", failed),
        "group-partial-failure": ("group-result", group_result), "group-partial-recheck": ("group-result", partial),
        "job-running": ("job", dict(schema_version="0.1", job_id="job-1", kind="single", revision=2,
                                   state="running", wait_reason=None, result_available=False, error=None)),
        "job-failed": ("job", dict(schema_version="0.1", job_id="job-1", kind="single", revision=3,
                                  state="failed", wait_reason=None, result_available=True, error=ERROR)),
    }


if __name__ == "__main__":
    for name, model in MODELS.items():
        schema = model.model_json_schema()
        schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
        write(f"schemas/{name}.schema.json", schema)
    manifest = {}
    for name, (model, value) in examples().items():
        MODELS[model].model_validate(value)
        write(f"examples/{name}.json", value)
        manifest[name] = model
    write("examples/manifest.json", manifest)
    print(f"Built {len(MODELS)} schemas and {len(manifest)} examples.")
