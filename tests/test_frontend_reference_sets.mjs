import assert from "node:assert/strict";
import test from "node:test";
import {
  consistencyFormValues, consistencyMethodChoices, estimatedSecondsWithConsistency,
  generationFromPreset, pairSelectionReady, referenceMismatchDiffRows, referenceSettingsSummaryRows,
  referenceStaleText, referenceStatusLabel, referenceTemplatesDraft, referenceTemplatesFromDraft,
  resourceSelectValues, sampleGenerationInputs, sampleRequestBody, sampleSizesBody,
  selectPairImage, togglePairMultiSelect,
} from "../frontend/reference-sets.js";

test("reference status and stale text use the ADR-0027 Korean labels", () => {
  assert.equal(referenceStatusLabel("none"), "없음");
  assert.equal(referenceStatusLabel("valid"), "유효");
  assert.equal(referenceStatusLabel("needs_review"), "재확인 필요");
  assert.equal(referenceStatusLabel("bogus"), "알 수 없음");
  assert.equal(referenceStaleText([]), "");
  assert.equal(referenceStaleText(["character", "outfit"]), "변경됨: 캐릭터, 의상");
});

test("settings summary rows format fragments and loras readably", () => {
  const rows = referenceSettingsSummaryRows({
    diffusion_model: "model.safetensors", text_encoder: "encoder.safetensors",
    common_fragments: [{ id: "f1", revision: 2 }], positive_quality: "masterpiece",
    loras: [{ name: "lora.safetensors", strength: 0.8 }],
  });
  assert.deepEqual(rows.map((row) => row.key), ["diffusion_model", "text_encoder", "common_fragments", "positive_quality", "loras"]);
  assert.equal(rows.find((row) => row.key === "common_fragments").text, "f1@2");
  assert.equal(rows.find((row) => row.key === "loras").text, "lora.safetensors×0.8");
  assert.deepEqual(referenceSettingsSummaryRows(null), []);
});

test("mismatch diff rows expose readable reference/plan pairs", () => {
  const rows = referenceMismatchDiffRows({ diffusion_model: { reference: "a.safetensors", plan: "b.safetensors" } });
  assert.deepEqual(rows, [{ field: "diffusion_model", label: "Diffusion model", reference: '"a.safetensors"', plan: '"b.safetensors"' }]);
  assert.deepEqual(referenceMismatchDiffRows(null), []);
});

test("consistency form values clamp to schema bounds and flag warn_below", () => {
  const schema = { strength: { type: "number", default: 1.0, min: 0.5, max: 1.5 },
    end_percent: { type: "number", default: 0.5, min: 0.3, max: 1.0, warn_below: 0.5 },
    suppress_reference_background: { type: "boolean", default: true } };
  const { values, warnings } = consistencyFormValues(schema, { strength: 5, end_percent: 0.4 });
  assert.deepEqual(values, { strength: 1.5, end_percent: 0.4, suppress_reference_background: true });
  assert.deepEqual(warnings, ["end_percent"]);
  const defaults = consistencyFormValues(schema, {});
  assert.deepEqual(defaults.values, { strength: 1.0, end_percent: 0.5, suppress_reference_background: true });
  assert.deepEqual(defaults.warnings, []);
});

test("consistency method choices normalize availability and reason", () => {
  const choices = consistencyMethodChoices([
    { id: "anima-incontext-character", families: ["anima"], available: true, params: {} },
    { id: "future-method", families: ["illustrious"], available: false, unavailable_reason: "node missing" },
    { id: null },
  ]);
  assert.equal(choices.length, 2);
  assert.equal(choices[0].available, true);
  assert.equal(choices[1].available, false);
  assert.equal(choices[1].reason, "node missing");
});

test("estimated seconds applies the ~3.3x consistency factor and returns null without a base", () => {
  assert.equal(estimatedSecondsWithConsistency(9, false), 9);
  assert.equal(Math.round(estimatedSecondsWithConsistency(9, true)), 30);
  assert.equal(estimatedSecondsWithConsistency(0, true), null);
  assert.equal(estimatedSecondsWithConsistency(NaN, true), null);
});

test("pair selection tracks one full and one face image, possibly from different pairs", () => {
  let selection = {};
  selection = selectPairImage(selection, "full", "pair-a", "image-full-1");
  assert.equal(pairSelectionReady(selection), false);
  selection = selectPairImage(selection, "face", "pair-b", "image-face-1");
  assert.equal(pairSelectionReady(selection), true);
  assert.deepEqual(selection, { fullPairId: "pair-a", fullImageId: "image-full-1", facePairId: "pair-b", faceImageId: "image-face-1" });
});

test("multi-select toggle for regenerating chosen pairs", () => {
  let selected = togglePairMultiSelect([], "pair-a", true);
  selected = togglePairMultiSelect(selected, "pair-b", true);
  assert.deepEqual(selected, ["pair-a", "pair-b"]);
  selected = togglePairMultiSelect(selected, "pair-a", false);
  assert.deepEqual(selected, ["pair-b"]);
});

test("sample generation inputs validate the -1/safe-integer seed contract", () => {
  const generation = { diffusion_model: "m", text_encoder: "e", vae: "v", width: 1024, height: 1024, seed: -1, steps: 24, cfg: 4.5, sampler: "euler", scheduler: "normal", loras: [] };
  const inputs = sampleGenerationInputs(generation);
  assert.equal(inputs.seed, -1);
  assert.throws(() => sampleGenerationInputs({ ...generation, seed: -2 }), /Seed/);
  assert.throws(() => sampleGenerationInputs({ ...generation, steps: "not-a-number" }), /Steps/);
});

test("sample request body builds 1..4 independent pair requests sharing settings", () => {
  const generation = { diffusion_model: "m", text_encoder: "e", vae: "v", width: 1024, height: 1024, seed: -1, steps: 24, cfg: 4.5, sampler: "euler", scheduler: "normal", loras: [] };
  const requests = sampleRequestBody(generation, [{ id: "f1", revision: 1 }], 3);
  assert.equal(requests.length, 3);
  for (const request of requests) {
    assert.equal(request.generation_inputs.seed, -1);
    assert.deepEqual(request.common_fragments, [{ id: "f1", revision: 1 }]);
  }
  assert.equal(sampleRequestBody(generation, [], 0).length, 1);
  assert.equal(sampleRequestBody(generation, [], 99).length, 4);
});

test("sample sizes body validates per-role width/height like Core (256..1920, multiple of 16)", () => {
  assert.equal(sampleSizesBody(null), undefined);
  assert.equal(sampleSizesBody({}), undefined);
  assert.deepEqual(sampleSizesBody({ full: { width: 896, height: 1152 } }), { full: { width: 896, height: 1152 } });
  assert.deepEqual(sampleSizesBody({ full: { width: 896, height: 1152 }, face: { width: 1024, height: 1024 } }),
    { full: { width: 896, height: 1152 }, face: { width: 1024, height: 1024 } });
  assert.throws(() => sampleSizesBody({ full: { width: 900, height: 1152 } }), /16의 배수/);
  assert.throws(() => sampleSizesBody({ full: { width: 100, height: 1152 } }), /256~1920/);
});

test("sample request body includes sizes only when given and keeps prior 3-arg calls working", () => {
  const generation = { diffusion_model: "m", text_encoder: "e", vae: "v", width: 1024, height: 1024, seed: -1, steps: 24, cfg: 4.5, sampler: "euler", scheduler: "normal", loras: [] };
  const withoutSizes = sampleRequestBody(generation, [], 1);
  assert.equal("sizes" in withoutSizes[0], false);
  const withSizes = sampleRequestBody(generation, [], 1, { full: { width: 896, height: 1152 }, face: { width: 1024, height: 1024 } });
  assert.deepEqual(withSizes[0].sizes, { full: { width: 896, height: 1152 }, face: { width: 1024, height: 1024 } });
});

test("generation preset fills known fields but leaves the rest of the draft untouched", () => {
  const current = { diffusion_model: "old", text_encoder: "old-e", vae: "old-v", sampler: "euler", scheduler: "normal", steps: 20, cfg: 4, width: 512, height: 512, seed: -1, loras: [] };
  const preset = { id: "p1", revision: 2, name: "Anima base", settings: { diffusion_model: "anima.safetensors", text_encoder: "clip.safetensors", vae: "vae.safetensors", sampler: "euler_ancestral", scheduler: "karras", steps: 28, cfg: 5, width: 832, height: 1216, loras: [{ name: "style.safetensors", strength: 0.6 }] } };
  const filled = generationFromPreset(current, preset);
  assert.equal(filled.diffusion_model, "anima.safetensors");
  assert.equal(filled.steps, 28);
  assert.deepEqual(filled.loras, [{ name: "style.safetensors", strength: 0.6 }]);
  assert.equal(filled.seed, -1); // untouched field kept
  assert.deepEqual(generationFromPreset(current, null), current);
});

test("resource select values keep the current value visible and flagged when missing from the list", () => {
  assert.deepEqual(resourceSelectValues("anima.safetensors", ["anima.safetensors", "other.safetensors"]), { values: ["anima.safetensors", "other.safetensors"], missing: false });
  assert.deepEqual(resourceSelectValues("removed.safetensors", ["anima.safetensors"]), { values: ["removed.safetensors", "anima.safetensors"], missing: true });
  assert.deepEqual(resourceSelectValues("", null), { values: [], missing: false });
});

test("reference templates draft round-trips through the settings PATCH shape", () => {
  const templates = {
    full: { framing_prompt: "full body", include: { upper: true, lower: true, accessories: true, hands: true } },
    face: { framing_prompt: "portrait", include: { upper: true, lower: false, accessories: true, hands: false } },
  };
  const draft = referenceTemplatesDraft(templates);
  assert.deepEqual(referenceTemplatesFromDraft(draft), templates);
  assert.throws(() => referenceTemplatesFromDraft({ full: { framing_prompt: "  ", include: {} }, face: { framing_prompt: "x", include: {} } }), /구도 문구/);
});
