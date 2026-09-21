import assert from "node:assert/strict";
import {readFile} from "node:fs/promises";

const source = await readFile(new URL("../frontend/jobs.js", import.meta.url), "utf8");
const {buildBatchRequest, batchFingerprint, presetReference, groupRunDisplay, postprocessJobDisplay, postprocessListFallback} = await import(`data:text/javascript,${encodeURIComponent(source)}`);
const draft = {groupId: "group-1", generationPreset: "anima-pilot@2", postprocessPreset: "", singleProfile: "single", singleProvider: "vision", groupProfile: "group", groupProvider: "vision", rows: [
  {framing: "upper_body", expression: "calm smile", action: "", situation: "studio"}, {framing: "full_body", expression: "", action: "walking", situation: ""},
]};
const body = buildBatchRequest(draft);
assert.deepEqual(body.group_validation, {profile_id: "group", provider_id: "vision"});
assert.equal(body.items.length, 2);
assert.deepEqual(body.items[0].presets, {generation: {id: "anima-pilot", revision: 2}});
assert.deepEqual(body.items[0].validation, {profile_id: "single", provider_id: "vision"});
assert.equal(body.items[0].postprocess, undefined);
assert.equal(body.items[1].action, "walking");
assert.equal(batchFingerprint(body), batchFingerprint(structuredClone(body)));
assert.throws(() => buildBatchRequest({...draft, rows: []}), /1~32/);
assert.throws(() => presetReference("missing-revision"), /Preset/);
assert.deepEqual(groupRunDisplay({state: "completed", outcome: "incomplete", result: {summary: {incomplete: 1}, items: [
  {target_id: "target-1", status: "insufficient", evidence: [{feature: "lower", status: "insufficient"}]},
]}}), {state: "completed", outcome: "incomplete", summary: {incomplete: 1}, targets: [
  {id: "target-1", status: "insufficient", evidence: [{feature: "lower", status: "insufficient"}]},
] , error: null, partialResults: []});
assert.deepEqual(groupRunDisplay({state: "failed", outcome: "error", error: {code: "CORE_VALIDATION_PROTOCOL_ERROR"}, partial_results: [{image_ref: "target-1"}]}), {
  state: "failed", outcome: "error", summary: null, error: {code: "CORE_VALIDATION_PROTOCOL_ERROR"}, partialResults: [{image_ref: "target-1"}], targets: [],
});
assert.deepEqual(postprocessJobDisplay({id: "post-1", state: "running", source_image_id: "source-1", cancel_requested: true, images: [{image_id: "derived-1"}], error: null}), {
  id: "post-1", state: "running", sourceImageId: "source-1", cancelRequested: true, images: [{image_id: "derived-1"}], error: null,
});
assert.equal(postprocessListFallback({status: 404, code: "CLIENT_PROTOCOL_ERROR"}), true);
assert.equal(postprocessListFallback({status: 500}), false);
