import assert from "node:assert/strict";
import test from "node:test";
import {readFile} from "node:fs/promises";
import {duplicateNumberMessage, fragmentIncludeSummary, fragmentLabel, fragmentNumberError, inclusionLabels, normalizeFragmentInclude, parseCheckFeatures, saveWarningMessages} from "../frontend/fragment-rules.js";
import {draftChanged, fragmentDraft, fragmentSaveBody, fragmentValidationError, numberCheckPath} from "../frontend/fragments.js";
import {characterCheckFeatures, entityMutationRequest, plannedItemLabel} from "../frontend/production.js";

const gallerySource = await readFile(new URL("../frontend/gallery.js", import.meta.url), "utf8");
const {findingSourceLabel, outputPathText, singleValidationSummary} = await import(`data:text/javascript,${encodeURIComponent(gallerySource)}`);

test("fragment numbers accept any filename-safe text and reject unsafe names", () => {
  for (const value of ["12", "A-03", "표정 1", "x".repeat(32), "con1", "COM10"]) assert.equal(fragmentNumberError(value), null, value);
  for (const value of ["", "x".repeat(33), "a/b", "a\\b", "a:b", "a*b", "a?b", 'a"b', "a<b", "a|b", "a\u0001", " 12", "12 ", "12.", "CON", "nul", "com1", "LPT9", "aux.txt"]) {
    assert.equal(typeof fragmentNumberError(value), "string", value);
  }
});

test("hands inclusion defaults to true for new and older fragments", () => {
  assert.equal(fragmentDraft().include.hands, true);
  assert.equal(fragmentDraft({id: "old", revision: 1, number: 7, name: "old", body: "x", include: {upper: true, lower: false}}).include.hands, true);
  assert.equal(normalizeFragmentInclude({hands: false}).hands, false);
  assert.equal(fragmentIncludeSummary({upper: true, lower: false}), "포함: 상의·액세서리·손");
  assert.equal(fragmentIncludeSummary({upper: false, lower: false, accessories: false, hands: false}), "포함: 의상 없음");
});

test("fragment save body sends a string number only for per-image fragments", () => {
  const draft = fragmentDraft({id: "a", revision: 2, number: 10, name: " Smile ", body: " smile ", include: {upper: true, lower: false, accessories: true}});
  assert.equal(draft.number, "10");
  assert.equal(draftChanged(draft, {id: "a", revision: 2, number: "10", name: " Smile ", body: " smile ", include: {upper: true, lower: false, accessories: true, hands: true}}), false);
  draft.include.hands = false;
  assert.equal(draftChanged(draft, {id: "a", number: "10", name: " Smile ", body: " smile ", include: {upper: true, lower: false}}), true);
  assert.deepEqual(fragmentSaveBody(draft), {name: "Smile", body: "smile", category_id: null, common: false, number: "10", include: {upper: true, lower: false, accessories: true, hands: false}});
  assert.equal(fragmentSaveBody({...draft, common: true}).number, null);
  assert.match(fragmentValidationError({...draft, number: "a/b"}), /문자/);
  assert.equal(fragmentValidationError({...draft, common: true, number: ""}), null);
  assert.equal(new URL(numberCheckPath("12 (a)", "frag-1"), "https://x.test").searchParams.get("number"), "12 (a)");
  assert.equal(new URL(numberCheckPath("12"), "https://x.test").searchParams.has("exclude_id"), false);
});

test("duplicate number messages name the other fragments and surface save warnings", () => {
  const message = duplicateNumberMessage("12", [{id: "b", number: "12", name: "웃음", archived: false}, {id: "c", number: "12", name: "옛 조각", archived: true}]);
  assert.match(message, /^번호 12은\(는\) 이미 다른 조각\(웃음, 옛 조각\(보관됨\)\)에서 사용 중입니다\./);
  assert.match(message, /\(2\) 같은 번호가 붙습니다\. 저장할까요\?$/);
  assert.equal(saveWarningMessages([{code: "duplicate_number", number: "12", fragment_ids: ["b"]}]).length, 1);
  assert.deepEqual(saveWarningMessages(undefined), []);
});

test("labels and inclusion display include hands and use fragment numbers", () => {
  assert.equal(fragmentLabel({number: "A-1", name: "웃음"}), "#A-1 웃음");
  assert.equal(fragmentLabel({number: null, name: "화풍"}), "화풍");
  assert.deepEqual(inclusionLabels({upper: {included: true}, hands: {included: false}, appearance: {included: true}}), ["상의: 포함", "손: 제외"]);
  assert.equal(plannedItemLabel("교복", {number: "3", name: "손 흔들기", include: {upper: true, lower: true, accessories: false, hands: true}}), "교복 × #3 손 흔들기 (포함: 상의·하의·손)");
});

test("character check features are trimmed non-empty lines with limits", () => {
  assert.deepEqual(parseCheckFeatures(" 은발 \r\n\n오드아이(왼쪽 호박색·오른쪽 파란색)\n  \n아호게"), ["은발", "오드아이(왼쪽 호박색·오른쪽 파란색)", "아호게"]);
  assert.deepEqual(characterCheckFeatures({check_features: ["은발", " "]}), ["은발"]);
  assert.deepEqual(characterCheckFeatures({check_features: ["old"], check_features_text: "new\n"}), ["new"]);
  assert.throws(() => characterCheckFeatures({check_features_text: Array.from({length: 51}, (_, i) => `f${i}`).join("\n")}), /50개/);
  assert.throws(() => characterCheckFeatures({check_features_text: "x".repeat(201)}), /200자/);
  const request = entityMutationRequest({mode: "edit", kind: "characters", targetId: "c", revision: 1, value: {name: "c", appearance_prompt: "", negative_prompt: "", check_features_text: "은발\n아호게"}});
  assert.deepEqual(request.body.check_features, ["은발", "아호게"]);
  const outfit = entityMutationRequest({mode: "edit", kind: "outfits", targetId: "o", revision: 1, value: {name: "o", components: {upper: "coat", hands: "white gloves"}}});
  assert.deepEqual(outfit.body.components, {upper: "coat", lower: "", accessories: "", hands: "white gloves"});
});

test("single validation summary separates not-assessable items and labels sources", () => {
  assert.equal(findingSourceLabel("outfit_hands"), "손");
  assert.equal(findingSourceLabel("character_features"), "외형 특징");
  assert.equal(findingSourceLabel(null), null);
  const summary = singleValidationSummary({result: {
    findings: [{code: "positive_prompt_missing", prompt_excerpt: "white gloves", observed: "보이지 않음", source: "outfit_hands"}, {prompt_excerpt: "smile", observed: "무표정", source: null}],
    not_assessable: [{prompt_excerpt: "17 years old", source: "character_appearance", observed: "나이는 이미지로 판단 불가"}],
    diagnostics: {regeneration_proposal_dropped: "changes[0] invalid"},
  }});
  assert.deepEqual(summary.findings.map((item) => item.text), ["[손] white gloves — 보이지 않음", "smile — 무표정"]);
  assert.deepEqual(summary.notAssessable.map((item) => item.text), ["[외형 설명] 17 years old — 나이는 이미지로 판단 불가"]);
  assert.equal(summary.proposalDropped, "changes[0] invalid");
  const empty = singleValidationSummary({result: {findings: []}});
  assert.deepEqual(empty, {findings: [], notAssessable: [], proposalDropped: null});
  assert.equal(outputPathText({output_path: "AtelierX/작품/캐릭터/복장/12 (2).webp"}), "AtelierX/작품/캐릭터/복장/12 (2).webp");
  assert.equal(outputPathText({output_path: null}), null);
});
