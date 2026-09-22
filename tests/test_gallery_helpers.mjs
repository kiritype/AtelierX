import assert from "node:assert/strict";
import {readFile} from "node:fs/promises";

const source = await readFile(new URL("../frontend/gallery.js", import.meta.url), "utf8");
const {eligibleIds, referenceRequest, groupValidationRequest, replacementRequest, activeDetail, resolvedSeed, classificationFilters, postprocessRequest} = await import(`data:text/javascript,${encodeURIComponent(source)}`);

assert.deepEqual(eligibleIds({eligible_image_ids: ["passed-a", "passed-b", "passed-a"]}), ["passed-a", "passed-b"]);
assert.deepEqual(eligibleIds({eligible_image_ids: null}), []);
assert.deepEqual(referenceRequest(4, "representative", ["aux-a", "aux-b"]), {
  revision: 4, representative_id: "representative", auxiliary_ids: ["aux-a", "aux-b"],
});
assert.throws(() => referenceRequest(4, "representative", ["representative"]));
assert.throws(() => referenceRequest(4, "representative", ["a", "b", "c"]));
assert.throws(() => referenceRequest(0.5, "representative", []));

const consistency = {reference: {revision: 3, representative_id: "reference", auxiliary_ids: ["auxiliary"]},
  eligible_image_ids: ["reference", "auxiliary", "target-a", "target-b"], target_ids: ["target-a", "target-b"]};
assert.deepEqual(groupValidationRequest(consistency, ["target-a"], {profile_id: "group", provider_id: "vision"}), {
  reference_revision: 3, target_ids: ["target-a"], validation: {profile_id: "group", provider_id: "vision"},
});
assert.throws(() => groupValidationRequest(consistency, ["reference"], {profile_id: "group", provider_id: "vision"}));
assert.throws(() => groupValidationRequest(consistency, ["target-a", "target-a"], {profile_id: "group", provider_id: "vision"}));
assert.throws(() => groupValidationRequest(consistency, ["target-a"], {profile_id: "", provider_id: "vision"}));

const regeneration = {validation: {profile_id: "single", provider_id: "vision"}};
const groupValidation = {profile_id: "group", provider_id: "vision"};
assert.deepEqual(replacementRequest(consistency, "target-b", regeneration, groupValidation), {
  reference_revision: 3, target_image_id: "target-b", regeneration, group_validation: groupValidation,
});
assert.throws(() => replacementRequest(consistency, "reference", regeneration, groupValidation));
assert.throws(() => replacementRequest({...consistency, target_ids: ["target-b"]}, "target-a", regeneration, groupValidation));
assert.throws(() => replacementRequest(consistency, "target-a", {validation: {profile_id: "", provider_id: "vision"}}, groupValidation));

assert.equal(activeDetail(false, 8, 8, "image", "image"), true);
assert.equal(activeDetail(false, 9, 8, "image", "image"), false);
assert.equal(activeDetail(true, 8, 8, "image", "image"), false);
assert.equal(resolvedSeed({generation_inputs: {seed: 42}}), 42);
assert.equal(resolvedSeed({generation_inputs: {seed: -1}}), null);
assert.equal(resolvedSeed({generation_inputs: {seed: "42"}}), null);

const initialFilters = {work_id: "work-a", character_id: "character-a", outfit_id: "outfit-a", media_type: "image/png"};
assert.deepEqual(classificationFilters(initialFilters, "works", "work-b"), {work_id: "work-b", media_type: "image/png"});
assert.deepEqual(classificationFilters(initialFilters, "characters", "character-b"), {work_id: "work-a", character_id: "character-b", media_type: "image/png"});
assert.deepEqual(classificationFilters(initialFilters, "outfits", "outfit-b"), {...initialFilters, outfit_id: "outfit-b"});

assert.deepEqual(postprocessRequest({preset: "portrait-finish@3"}), {preset: {id: "portrait-finish", revision: 3}});
assert.deepEqual(postprocessRequest({preset: "", upscaleEnabled: true, upscaleModel: "4x-UltraSharp.safetensors", upscaleScale: "1.5", encodeEnabled: true, webpEnabled: true, webpQuality: "90", advanced: ""}), {postprocess: {upscale: {upscale_model: "4x-UltraSharp.safetensors", scale: 1.5}, encode: {webp_enabled: true, webp_quality: 90}}});
assert.deepEqual(postprocessRequest({preset: "", advanced: '{"alpha":{"segmentation_model":"seg.pt"}}'}), {postprocess: {alpha: {segmentation_model: "seg.pt"}}});
assert.throws(() => postprocessRequest({preset: "", upscaleEnabled: false, encodeEnabled: false, advanced: ""}), /stage/);
assert.throws(() => postprocessRequest({preset: "", upscaleEnabled: true, upscaleModel: "", upscaleScale: "1.5", advanced: ""}), /Upscale/);
