import assert from "node:assert/strict";
import test from "node:test";
import { appearanceMigrationChoiceRequired, buildGenerationBody, buildProductionPlanBody, buildProductionPlanRequests, clearProductionPlanSelection, creationPreviewPage, entityMutationRequest, estimatedUpscaleResolution, fragmentPickerQuery, freezeMultiProductionPlanRequests, loadProductionData, postprocessResolutionEstimate, previewRequestIsCurrent, randomSafeSeed, SAMPLER_OPTIONS, SCHEDULER_OPTIONS, toggleTreeSelection, treeSelectionState } from "../frontend/production.js";

function state(overrides = {}) {
  return {
    selection: { groupId: "group-1" },
    draft: {
      framingPrompt: "upper body, white background\ncalm portrait",
      include: { upper: true, lower: false, accessories: true },
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
  assert.deepEqual(body.include, { upper: true, lower: false, accessories: true, hands: true });
  assert.equal(body.framing, "custom");
  assert.equal(body.framing_prompt, "upper body, white background\ncalm portrait");
  assert.deepEqual(body.presets, { generation: { id: "generation-1", revision: 3 } });
  assert.equal(body.postprocess, undefined);
  assert.equal(body.expression, "soft smile\nlooking at viewer");
});

test("production request requires a nonempty free framing prompt and explicit all-area inclusion", () => {
  assert.throws(() => buildGenerationBody(state({ framingPrompt: "\n  " })), /구도 Prompt/);
  const body = buildGenerationBody(state({ include: { upper: false, lower: true, accessories: false } }));
  assert.deepEqual(body.include, { upper: false, lower: true, accessories: false, hands: true });
  assert.equal(buildGenerationBody(state({ include: { upper: true, lower: false, accessories: true, hands: false } })).include.hands, false);
});

test("random seed sentinel and optional plan validation preserve the Core contract", () => {
  const generated = buildGenerationBody(state({generationPreset: "", generation: {diffusion_model: "model", text_encoder: "encoder", vae: "vae", width: 1024, height: 1024, seed: -1, steps: 20, cfg: 4, sampler: "euler", scheduler: "normal"}, validationMode: "generation"}));
  assert.equal(generated.generation_inputs.seed, -1);
  const plan = buildProductionPlanBody(state({compositionMode: "fragment", fragmentSelections: ["fragment-a@2"], validationMode: "generation", validationEnabled: false}), 1);
  assert.equal("validation" in plan, false);
  assert.equal("group_validation" in plan, false);
});

test("final resolution uses the explicit final factor with half-up rounding", () => {
  assert.deepEqual(estimatedUpscaleResolution(1024, 768, 1.5), {width: 1536, height: 1152, factor: 1.5});
  assert.equal(estimatedUpscaleResolution(1008, 1008, 1.0625).width, 1071);
  assert.equal(estimatedUpscaleResolution(1008, 1008, 1.0005).width, 1009);
  assert.throws(() => estimatedUpscaleResolution(1, 1, 0), /0보다/);
  assert.deepEqual(estimatedUpscaleResolution(1, 1, 0.1), {width: 1, height: 1, factor: 0.1});
  const draft = {generationPreset: "generation@2", postprocessPreset: "postprocess@3", postprocessMode: "default", generation: {width: 1, height: 1}};
  assert.deepEqual(postprocessResolutionEstimate(draft, {generation: [{id: "generation", revision: 2, settings: {width: 1008, height: 1008}}], postprocess: [{id: "postprocess", revision: 3, settings: {upscale: {}}}]}), {width: 1512, height: 1512, factor: 1.5});
  assert.deepEqual(postprocessResolutionEstimate({...draft, generationPreset: "", postprocessPreset: "", generation: {width: 1008, height: 1008}}, {}), {width: 1512, height: 1512, factor: 1.5});
});

test("tree parent selection includes every descendant and reports partial state", () => {
  assert.deepEqual(treeSelectionState(["outfit-a", "outfit-b"], ["outfit-a"]), {checked: false, indeterminate: true, count: 1, total: 2});
  assert.deepEqual(toggleTreeSelection(["outfit-a"], ["outfit-a", "outfit-b"], true), ["outfit-a", "outfit-b"]);
  assert.deepEqual(toggleTreeSelection(["outfit-a", "outfit-b", "other"], ["outfit-a", "outfit-b"], false), ["other"]);
});

test("appearance migration requires an explicit candidate choice and strips legacy outfit appearance", () => {
  const editor = {kind: "characters", value: {appearance_migration: {status: "conflict"}}, migrationChoiceConfirmed: false};
  assert.equal(appearanceMigrationChoiceRequired(editor), true);
  editor.migrationChoiceConfirmed = true;
  assert.equal(appearanceMigrationChoiceRequired(editor), false);
  const request = entityMutationRequest({mode: "edit", kind: "outfits", targetId: "outfit-1", revision: 2, value: {name: "coat", components: {appearance: "legacy", upper: "coat", lower: "pants", accessories: "bag"}}});
  assert.deepEqual(request.body.components, {upper: "coat", lower: "pants", accessories: "bag", hands: ""});
});

test("creation preview pages the outfit and fragment product without dropping combinations", () => {
  const page = creationPreviewPage(["outfit-a", "outfit-b"], [{id: "f1"}, {id: "f2"}, {id: "f3"}], 2, 3);
  assert.equal(page.total, 6);
  assert.deepEqual(page.items.map((item) => [item.outfitId, item.fragment.id]), [["outfit-a", "f3"], ["outfit-b", "f1"], ["outfit-b", "f2"]]);
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

test("common prompt selections are sent separately from image variants", () => {
  const single = buildGenerationBody(state({compositionMode: "fragment", fragmentSelections: ["variant@2"], commonFragmentSelections: ["common-a@3", "common-b@4"]}));
  assert.deepEqual(single.fragment, {id: "variant", revision: 2});
  assert.deepEqual(single.common_fragments, [{id: "common-a", revision: 3}, {id: "common-b", revision: 4}]);
  const plan = buildProductionPlanBody(state({compositionMode: "fragment", fragmentSelections: ["variant-a@2", "variant-b@3"], commonFragmentSelections: ["common-a@4"], validationMode: "generation"}));
  assert.deepEqual(plan.fragments, [{id: "variant-a", revision: 2}, {id: "variant-b", revision: 3}]);
  assert.deepEqual(plan.common_fragments, [{id: "common-a", revision: 4}]);
  assert.throws(() => buildGenerationBody(state({compositionMode: "fragment", fragmentSelections: [], commonFragmentSelections: ["common-a@4"]})), /하나만/);
});

test("fragment mode rejects zero or multiple selections for a single preview", () => {
  assert.throws(() => buildGenerationBody(state({ compositionMode: "fragment", fragmentSelections: [] })), /하나만/);
  assert.throws(() => buildGenerationBody(state({ compositionMode: "fragment", fragmentSelections: ["a@1", "b@1"] })), /하나만/);
});

test("fragment picker uses Core category and query filters without placing selection in the request", () => {
  const path = fragmentPickerQuery({fragmentSearch: "미소", fragmentCategoryId: "expression", fragmentLimit: 25, fragmentOffset: 50});
  assert.equal(path, "/v1/prompt-fragments?archived=false&limit=25&offset=50&q=%EB%AF%B8%EC%86%8C&category_id=expression");
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

test("production plans accept selected fragment references from the shared picker", () => {
  const body = buildProductionPlanBody(state({
    compositionMode: "fragment", fragmentSelections: [{id: "fragment-a", revision: 2}, {id: "fragment-b", revision: 5}],
    validationEnabled: true, validationProfile: "single-profile", validationProvider: "single-provider",
    groupValidationProfile: "group-profile", groupValidationProvider: "group-provider",
  }));
  assert.deepEqual(body.fragments, [{id: "fragment-a", revision: 2}, {id: "fragment-b", revision: 5}]);
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

test("prepare defers compose catalogs and cached branches avoid repeated API calls", async () => {
  const calls = [];
  const api = {get: async (path) => { calls.push(path); return {items: []}; }};
  const current = {selection: {workId: null, characterId: null, outfitId: null}, expanded: {works: {}, characters: {}}, entities: {works: [], characters: [], outfits: [], groups: []}, presets: {}, productionSection: "prepare", fragmentSearch: "", fragmentCategoryId: "", fragmentLimit: 25, fragmentOffset: 0};
  await loadProductionData(current, api);
  assert.deepEqual(calls, ["/v1/works?limit=200&offset=0"]);
  await loadProductionData(current, api);
  assert.equal(calls.length, 1);
  current.productionSection = "compose";
  await loadProductionData(current, api);
  assert.equal(calls.includes("/v1/presets/generation?archived=false"), true);
  assert.equal(calls.includes("/v1/validation-settings/providers"), true);
  assert.equal(calls.filter((path) => path.startsWith("/v1/groups")).length, 0);
});

test("stale production loads do not apply a late catalog response", async () => {
  const current = {selection: {workId: null, characterId: null, outfitId: null}, expanded: {works: {}, characters: {}}, entities: {works: [{id: "kept"}], characters: [], outfits: [], groups: []}, presets: {}, productionSection: "prepare", fragmentSearch: "", fragmentCategoryId: "", fragmentLimit: 25, fragmentOffset: 0};
  await loadProductionData(current, {get: async () => ({items: [{id: "late"}]})}, () => false);
  assert.deepEqual(current.entities.works, [{id: "kept"}]);
});

test("explicit editor mode keeps a new child as POST despite an old selected target", () => {
  assert.deepEqual(entityMutationRequest({mode: "create", kind: "works", value: {name: "새 작품"}}), {method: "post", path: "/v1/works", body: {name: "새 작품"}});
  assert.deepEqual(entityMutationRequest({mode: "create", kind: "characters", value: {name: "새 캐릭터", parent_id: "work-new"}}), {method: "post", path: "/v1/characters", body: {name: "새 캐릭터", parent_id: "work-new", appearance_prompt: "", negative_prompt: "", check_features: []}});
  const created = entityMutationRequest({mode: "create", kind: "outfits", targetId: null, value: {name: "새 의상", parent_id: "character-new", components: {upper: "shirt"}}});
  assert.deepEqual(created, {method: "post", path: "/v1/outfits", body: {name: "새 의상", parent_id: "character-new", components: {upper: "shirt", lower: "", accessories: "", hands: ""}}});
  const edited = entityMutationRequest({mode: "edit", kind: "characters", targetId: "character-old", revision: 7, value: {name: "변경", appearance_prompt: "black hair", negative_prompt: "glasses", check_features: []}});
  assert.deepEqual(edited, {method: "patch", path: "/v1/characters/character-old", body: {name: "변경", revision: 7, appearance_prompt: "black hair", negative_prompt: "glasses", check_features: []}});
});
