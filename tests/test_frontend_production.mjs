import assert from "node:assert/strict";
import test from "node:test";
import { buildGenerationBody, buildProductionPlanBody, buildProductionPlanRequests, clearProductionPlanSelection, freezeMultiProductionPlanRequests, previewRequestIsCurrent, randomSafeSeed, SAMPLER_OPTIONS, SCHEDULER_OPTIONS } from "../frontend/production.js";

function state(overrides = {}) {
  return {
    selection: { groupId: "group-1" },
    draft: {
      framingPrompt: "upper body, white background\ncalm portrait",
      include: { appearance: true, upper: true, lower: false },
      expression: "soft smile\nlooking at viewer",
      action: "", situation: "studio",
      generationPreset: "generation-1@3", postprocessPreset: "", postprocessMode: "default",
      validationEnabled: false, loras: [],
      ...overrides,
    },
  };
}

test("production request uses the custom framing contract and preserves multiline framing", () => {
  const body = buildGenerationBody(state());
  assert.deepEqual(body.include, { appearance: true, upper: true, lower: false });
  assert.equal(body.framing, "custom");
  assert.equal(body.framing_prompt, "upper body, white background\ncalm portrait");
  assert.deepEqual(body.presets, { generation: { id: "generation-1", revision: 3 } });
  assert.equal(body.postprocess, undefined);
  assert.equal(body.expression, "soft smile\nlooking at viewer");
});

test("production request requires a nonempty free framing prompt and explicit all-area inclusion", () => {
  assert.throws(() => buildGenerationBody(state({ framingPrompt: "\n  " })), /구도 Prompt/);
  const body = buildGenerationBody(state({ include: { appearance: false, upper: false, lower: true } }));
  assert.deepEqual(body.include, { appearance: false, upper: false, lower: true });
});

test("random seed stays a JavaScript-safe integer over the full generated range", () => {
  const maximum = randomSafeSeed((values) => { values[0] = 0xffffffff; values[1] = 0xffffffff; return values; });
  assert.equal(maximum, Number.MAX_SAFE_INTEGER);
  assert.equal(Number.isSafeInteger(maximum), true);
  const zero = randomSafeSeed((values) => { values[0] = 0; values[1] = 0; return values; });
  assert.equal(zero, 0);
});

test("sampler and scheduler controls include the verified Anima smoke defaults", () => {
  assert.equal(SAMPLER_OPTIONS.includes("euler_ancestral"), true);
  assert.equal(SCHEDULER_OPTIONS.includes("normal"), true);
  assert.equal(SAMPLER_OPTIONS.includes("uni_pc_bh2"), true);
});


test("direct generation rejects a manually entered unsafe seed before preview", () => {
  const direct = state({
    generationPreset: "",
    generation: {
      diffusion_model: "waiANIMA_v10Base10.safetensors", text_encoder: "waiANIMA_v10Base10_txt.safetensors",
      vae: "qwen_image_vae.safetensors", width: 1024, height: 1024, seed: Number.MAX_SAFE_INTEGER + 2,
      steps: 24, cfg: 4.5, sampler: "euler_ancestral", scheduler: "normal",
    },
  });
  assert.throws(() => buildGenerationBody(direct), /안전 정수/);
});


test("a preview response is discarded after prompt, seed, or group changes", () => {
  const current = state({
    generationPreset: "",
    generation: {
      diffusion_model: "waiANIMA_v10Base10.safetensors", text_encoder: "waiANIMA_v10Base10_txt.safetensors",
      vae: "qwen_image_vae.safetensors", width: 1024, height: 1024, seed: 123456789,
      steps: 24, cfg: 4.5, sampler: "euler_ancestral", scheduler: "normal",
    },
  });
  const request = buildGenerationBody(current);
  const revision = 0;
  assert.equal(previewRequestIsCurrent(current, request, revision), true);
  current.draft.generation.seed = 2136712158049072;
  current.draft.previewRevision = 1;
  assert.equal(previewRequestIsCurrent(current, request, revision), false);
  // Reverting the visible input still must not revive an earlier response.
  current.draft.generation.seed = request.generation_inputs.seed;
  current.draft.framingPrompt = "full body";
  assert.equal(previewRequestIsCurrent(current, request, revision), false);
  current.selection.groupId = "group-2";
  assert.equal(previewRequestIsCurrent(current, request, revision), false);
});


test("fragment mode sends one pinned fragment without direct composition fields", () => {
  const body = buildGenerationBody(state({ compositionMode: "fragment", fragmentSelections: ["fragment-1@7"] }));
  assert.deepEqual(body.fragment, { id: "fragment-1", revision: 7 });
  for (const key of ["framing", "framing_prompt", "expression", "action", "situation", "include"]) assert.equal(key in body, false);
});

test("fragment mode rejects zero or multiple selections for a single preview", () => {
  assert.throws(() => buildGenerationBody(state({ compositionMode: "fragment", fragmentSelections: [] })), /하나만/);
  assert.throws(() => buildGenerationBody(state({ compositionMode: "fragment", fragmentSelections: ["a@1", "b@1"] })), /하나만/);
});


test("production plan freezes ordered fragment refs with required validation settings", () => {
  const body = buildProductionPlanBody(state({
    compositionMode: "fragment", fragmentSelections: ["fragment-a@2", "fragment-b@5"],
    validationEnabled: true, validationProfile: "single-profile", validationProvider: "single-provider",
    groupValidationProfile: "group-profile", groupValidationProvider: "group-provider",
  }));
  assert.deepEqual(body.fragments, [{ id: "fragment-a", revision: 2 }, { id: "fragment-b", revision: 5 }]);
  assert.deepEqual(body.validation, { profile_id: "single-profile", provider_id: "single-provider" });
  assert.deepEqual(body.group_validation, { profile_id: "group-profile", provider_id: "group-provider" });
  assert.equal("fragment" in body, false);
});

test("production plan requires two fragments and both validation selections", () => {
  assert.throws(() => buildProductionPlanBody(state({ compositionMode: "fragment", fragmentSelections: ["fragment-a@2"] })), /두 개/);
  assert.throws(() => buildProductionPlanBody(state({ compositionMode: "fragment", fragmentSelections: ["fragment-a@2", "fragment-b@2"], validationEnabled: true, validationProfile: "x", validationProvider: "y" })), /묶음 검사/);
});

test("multiple frozen groups receive separate production-plan requests with the same global selections", () => {
  const current = state({
    compositionMode: "fragment", fragmentSelections: ["fragment-a@2", "fragment-b@5"],
    validationEnabled: true, validationProfile: "single-profile", validationProvider: "single-provider",
    groupValidationProfile: "group-profile", groupValidationProvider: "group-provider",
  });
  current.selection.groupIds = ["group-a", "group-b", "group-a"];
  const requests = buildProductionPlanRequests(current);
  assert.deepEqual(Object.keys(requests), ["group-a", "group-b"]);
  assert.equal(requests["group-a"].group_id, "group-a");
  assert.equal(requests["group-b"].group_id, "group-b");
  assert.deepEqual(requests["group-a"].fragments, requests["group-b"].fragments);
  current.draft.fragmentSelections = ["fragment-a@2"];
  assert.equal(buildProductionPlanRequests(current)["group-b"].fragments.length, 1);
});

test("multi-group retries retain each group’s frozen body and idempotency key", () => {
  const current = state({
    compositionMode: "fragment", fragmentSelections: ["fragment-a@2", "fragment-b@5"],
    validationEnabled: true, validationProfile: "single-profile", validationProvider: "single-provider",
    groupValidationProfile: "group-profile", groupValidationProvider: "group-provider",
  });
  current.selection.groupIds = ["group-a", "group-b"];
  let counter = 0;
  const frozen = freezeMultiProductionPlanRequests(current, () => `key-${++counter}`);
  const firstRequest = frozen["group-a"].request;
  current.draft.fragmentSelections = ["fragment-changed@9", "fragment-b@5"];
  current.selection.groupIds = ["group-a"];
  const retried = freezeMultiProductionPlanRequests(current, () => `unexpected-${++counter}`);
  assert.equal(retried["group-a"].key, "key-1");
  assert.equal(retried["group-a"].request, firstRequest);
  assert.equal(retried["group-a"].request.fragments[0].id, "fragment-a");
  assert.equal(retried["group-b"].key, "key-2");
});


test("returning from a frozen plan clears navigation only and preserves the draft", () => {
  const current = state();
  current.selectedId = "plan:plan-1";
  current.productionPlanId = "plan-1";
  current.productionPlan = { id: "plan-1" };
  current.productionPlanItems = [{ index: 0 }];
  current.planItemsOffset = 20;
  const draft = current.draft;
  clearProductionPlanSelection(current);
  assert.equal(current.productionPlanId, null);
  assert.equal(current.selectedId, null);
  assert.deepEqual(current.productionPlanItems, []);
  assert.equal(current.planItemsOffset, 0);
  assert.equal(current.draft, draft);
});
