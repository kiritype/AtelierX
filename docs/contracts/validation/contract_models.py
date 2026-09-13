"""Executable contract draft, not a Backend implementation or SDK dependency.

Uses the already installed Pydantic v2 to export JSON Schema and check fixtures.
Cross-document, environment and visual/semantic checks remain service concerns.
"""
from __future__ import annotations

from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


Id = Annotated[str, Field(min_length=1, max_length=200, pattern=r"^\S+$")]
Text = Annotated[str, Field(min_length=1, pattern=r"\S")]
Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Count = Annotated[int, Field(ge=0)]


class GenerationSource(Contract):
    type: Literal["generation"]
    server_id: Id
    image_id: Id
    sha256: Digest


class UploadSource(Contract):
    type: Literal["upload"]
    upload_id: Id
    sha256: Digest


Source = Annotated[GenerationSource | UploadSource, Field(discriminator="type")]


class Image(Contract):
    ref: Id  # Request-local identity, including unregistered uploaded images.
    source: Source
    positive_prompt: Text
    negative_prompt: str  # Empty explicitly means unused.


class Profile(Contract):
    profile_id: Id
    revision: Count
    output_conditions: bool
    positive_prompt: bool
    negative_prompt: bool
    body_parts: list[Literal["hands", "face", "limbs"]]
    metadata: bool
    consistency: bool

    @model_validator(mode="after")
    def unique_parts(self):
        if len(self.body_parts) != len(set(self.body_parts)):
            raise ValueError("duplicate body part")
        return self


class Provider(Contract):
    provider_id: Id
    revision: Count
    model: Id
    timeout_seconds: Annotated[int, Field(gt=0)]
    # Endpoint and credentials resolved by trusted server config, never here.


class ExpectedOutput(Contract):
    width: Annotated[int, Field(gt=0)]
    height: Annotated[int, Field(gt=0)]
    media_type: Literal["image/png", "image/webp"]
    alpha: Literal["not_required", "channel_required", "transparency_required"]


class Lora(Contract):
    model_id: Id
    strength: float  # Bounds come from Generation capabilities, not Anima alone.


class GenerationSettings(Contract):
    capability_revision: Id
    model_id: Id | None = None
    text_encoder_id: Id | None = None
    vae_id: Id | None = None
    seed: Annotated[int, Field(ge=0, le=18446744073709551615)] | None = None
    cfg: Annotated[float, Field(ge=0)] | None = None
    steps: Annotated[int, Field(gt=0)] | None = None
    sampler: Id | None = None
    scheduler: Id | None = None
    width: Annotated[int, Field(gt=0)] | None = None
    height: Annotated[int, Field(gt=0)] | None = None
    loras: list[Lora] | None = None
    postprocessing_snapshot_id: Id | None = None


class SingleRequest(Contract):
    schema_version: Literal["0.1"]
    kind: Literal["single"]
    image: Image
    generation_attempt_id: Id | None
    profile: Profile
    provider: Provider
    expected_output: ExpectedOutput | None
    generation_settings: GenerationSettings | None

    @model_validator(mode="after")
    def compatible_profile(self):
        if self.profile.consistency:
            raise ValueError("single request cannot perform group consistency")
        if self.profile.output_conditions and self.expected_output is None:
            raise ValueError("active output check requires expected output")
        return self


class GroupContext(Contract):
    group_id: Id
    group_revision: Count
    reference_revision: Count
    work_id: Id
    character_id: Id
    outfit_id: Id


class Feature(Contract):
    name: Text
    expected: Text


class GenerationSummary(Contract):
    requested: Count
    passed: Count
    generation_failed: Count
    validation_error: Count
    rejected: Count
    cancelled: Count

    @model_validator(mode="after")
    def totals(self):
        if self.requested != sum(getattr(self, k) for k in (
            "passed", "generation_failed", "validation_error", "rejected", "cancelled"
        )):
            raise ValueError("generation counts do not sum to requested")
        return self


class GroupRequest(Contract):
    schema_version: Literal["0.1"]
    kind: Literal["group"]
    group: GroupContext
    scope: Literal["full", "partial"]
    images: Annotated[list[Image], Field(min_length=2, max_length=128)]
    targets: Annotated[list[Id], Field(min_length=1)]
    primary_reference: Id
    auxiliary_references: list[Id]
    common_features: Annotated[list[Feature], Field(min_length=1)]
    generation_summary: GenerationSummary
    profile: Profile
    provider: Provider

    @model_validator(mode="after")
    def references(self):
        refs = [x.ref for x in self.images]
        if len(refs) != len(set(refs)):
            raise ValueError("image refs must be unique")
        sources = [x.source.model_dump_json() for x in self.images]
        if len(sources) != len(set(sources)):
            raise ValueError("same source must not masquerade as distinct images")
        if len(self.targets) != len(set(self.targets)):
            raise ValueError("duplicate targets")
        comparisons = [self.primary_reference, *self.auxiliary_references]
        if len(comparisons) != len(set(comparisons)):
            raise ValueError("duplicate reference roles")
        if not set(self.targets + comparisons).issubset(refs):
            raise ValueError("dangling image reference")
        if set(self.targets + comparisons) != set(refs):
            raise ValueError("unused images would leak unnecessary context")
        if any(not (set(comparisons) - {target}) for target in self.targets):
            raise ValueError("a target cannot only be compared to itself")
        if not self.profile.consistency:
            raise ValueError("group consistency disabled: no group job should be submitted")
        return self


class Error(Contract):
    code: Annotated[str, Field(pattern=r"^VAL_[A-Z0-9_]+$")]
    message: Text
    stage: Literal["input", "access", "provider", "response", "internal", "recovery"]
    field: str | None = None


class Finding(Contract):
    code: Id
    feature: Text
    expected: Text
    observed: Text
    prompt_excerpt: str | None = None


class Change(Contract):
    field: Literal["positive_prompt", "negative_prompt", "seed", "cfg", "steps",
                   "sampler", "scheduler", "model_id", "text_encoder_id", "vae_id",
                   "width", "height", "loras", "postprocessing_snapshot_id"]
    value: str | int | float | list[Lora]
    reason: Text

    @model_validator(mode="after")
    def field_type(self):
        value = self.value
        if self.field in {"seed", "steps", "width", "height"}:
            minimum = 0 if self.field == "seed" else 1
            if type(value) is not int or value < minimum:
                raise ValueError("invalid integer change")
            if self.field == "seed" and value > 18446744073709551615:
                raise ValueError("seed too large")
        elif self.field == "cfg":
            if type(value) not in (int, float) or value < 0:
                raise ValueError("invalid cfg")
        elif self.field == "loras":
            if not isinstance(value, list):
                raise ValueError("LoRA change must replace full ordered list")
        elif not isinstance(value, str) or (self.field != "negative_prompt" and not value.strip()):
            raise ValueError("invalid text/id change")
        return self


class Regeneration(Contract):
    required: bool
    reason: Text
    changes: list[Change]

    @model_validator(mode="after")
    def proposal(self):
        if self.required != bool(self.changes):
            raise ValueError("required needs changes; false must have none")
        fields = [x.field for x in self.changes]
        if len(fields) != len(set(fields)):
            raise ValueError("duplicate changes")
        return self


class SingleVerdict(Contract):
    findings: list[Finding]
    regeneration: Regeneration


class Evidence(Contract):
    profile: Profile
    provider: Provider


class SingleResult(Contract):
    schema_version: Literal["0.1"]
    kind: Literal["single"]
    job_id: Id
    request_id: Id
    image_ref: Id
    outcome: Literal["passed", "rejected", "error"]
    result: SingleVerdict | None
    error: Error | None
    evidence: Evidence

    @model_validator(mode="after")
    def verdict(self):
        if self.outcome == "error":
            if self.error is None or self.result is not None:
                raise ValueError("error cannot carry partial verdict or regeneration")
        else:
            if self.error is not None or self.result is None:
                raise ValueError("normal verdict requires result and no error")
            if self.outcome == "passed" and (self.result.findings or self.result.regeneration.required):
                raise ValueError("passed cannot have rejection/regeneration")
            if self.outcome == "rejected" and not self.result.findings:
                raise ValueError("rejected requires evidence")
        return self


class GroupItem(Contract):
    image_ref: Id
    compared_with: Annotated[list[Id], Field(min_length=1)]
    verdict: Literal["match", "mismatch", "insufficient", "error"]
    findings: list[Finding]
    unavailable_features: list[Text]
    error: Error | None

    @model_validator(mode="after")
    def consistency(self):
        if self.image_ref in self.compared_with or len(set(self.compared_with)) != len(self.compared_with):
            raise ValueError("self/duplicate comparison")
        if (self.verdict == "error") != (self.error is not None):
            raise ValueError("error branch mismatch")
        if self.verdict == "match" and (self.findings or self.unavailable_features):
            raise ValueError("incomplete comparison cannot match")
        if self.verdict == "mismatch" and not self.findings:
            raise ValueError("mismatch requires finding")
        if self.verdict == "insufficient" and not self.unavailable_features:
            raise ValueError("insufficient requires reason")
        return self


class ComparisonCounts(Contract):
    match: Count
    mismatch: Count
    insufficient: Count
    error: Count


class GroupResult(Contract):
    schema_version: Literal["0.1"]
    kind: Literal["group"]
    job_id: Id
    request_id: Id
    group: GroupContext
    scope: Literal["full", "partial"]
    targets: Annotated[list[Id], Field(min_length=1)]
    primary_reference: Id
    auxiliary_references: list[Id]
    items: Annotated[list[GroupItem], Field(min_length=1)]
    counts: ComparisonCounts
    summary: Literal["all_match", "mismatch_present", "incomplete"]
    generation_summary: GenerationSummary
    evidence: Evidence
    # Current validity is a Core projection, not a claim made by Validation.

    @model_validator(mode="after")
    def aggregate(self):
        ids = [x.image_ref for x in self.items]
        if len(self.targets) != len(set(self.targets)) or len(ids) != len(set(ids)) or set(ids) != set(self.targets):
            raise ValueError("exactly one item per requested target")
        refs = [self.primary_reference, *self.auxiliary_references]
        if len(refs) != len(set(refs)):
            raise ValueError("duplicate reference roles")
        for item in self.items:
            if not set(item.compared_with).issubset(refs):
                raise ValueError("unrecorded comparison reference")
        actual = {key: sum(x.verdict == key for x in self.items) for key in self.counts.model_dump()}
        if actual != self.counts.model_dump():
            raise ValueError("counts disagree with image verdicts")
        expected = ("mismatch_present" if actual["mismatch"] else
                    "incomplete" if actual["insufficient"] or actual["error"] else "all_match")
        if self.summary != expected:
            raise ValueError("group summary contradicts results")
        return self


class Job(Contract):
    schema_version: Literal["0.1"]
    job_id: Id
    kind: Literal["single", "group"]
    revision: Count
    state: Literal["queued", "running", "cancelling", "completed", "failed", "cancelled"]
    wait_reason: Literal["provider", "gpu", "memory"] | None
    result_available: bool
    error: Error | None

    @model_validator(mode="after")
    def state_fields(self):
        if self.state == "completed" and (not self.result_available or self.error):
            raise ValueError("completed needs result without job-level failure")
        if self.state == "failed" and self.error is None:
            raise ValueError("failed needs error")
        if self.state != "failed" and self.error is not None:
            raise ValueError("job error belongs to failed state")
        if self.state in {"queued", "running", "cancelling", "cancelled"} and self.result_available:
            raise ValueError("no public terminal result yet")
        if self.state != "queued" and self.wait_reason is not None:
            raise ValueError("wait reason only for queued")
        return self


MODELS = {"single-request": SingleRequest, "group-request": GroupRequest,
          "single-result": SingleResult, "group-result": GroupResult, "job": Job}


def validate_exchange(request, result, job):
    """Check associations against the persisted request, beyond JSON structure."""
    if request.kind != result.kind or job.kind != request.kind or job.job_id != result.job_id:
        raise ValueError("request/result/job association mismatch")
    if not job.result_available:
        raise ValueError("job has no terminal result")
    if result.evidence.profile != request.profile or result.evidence.provider != request.provider:
        raise ValueError("result must record executed request configuration")
    if request.kind == "single":
        if result.image_ref != request.image.ref:
            raise ValueError("wrong image result")
        if (result.outcome == "error") != (job.state == "failed"):
            raise ValueError("single verdict and execution state conflict")
        if result.outcome == "error" and result.error != job.error:
            raise ValueError("job and result errors disagree")
        if result.result and result.result.regeneration.required and request.generation_settings is None:
            raise ValueError("cannot propose changes without capability context")
    else:
        if job.state != "completed":
            raise ValueError("partial-image results require completed group processing")
        for field in ("group", "scope", "targets", "primary_reference", "auxiliary_references", "generation_summary"):
            if getattr(request, field) != getattr(result, field):
                raise ValueError(f"group result changed request {field}")
