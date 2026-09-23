import assert from "node:assert/strict";
import test from "node:test";
import {draftChanged, fragmentDraft, initialFragmentState, prepareNewRouteState, routeFragmentId, shouldRestoreRouteDetail} from "../frontend/fragments.js";
import {fragmentKey, fragmentListPath, preserveSelection, sameFragmentReference, pageOffsetForTotal} from "../frontend/fragment-picker.js";

test("new fragments include accessories by default while older records stay compatible", () => {
  assert.equal(fragmentDraft().include.accessories, true);
  assert.equal(fragmentDraft({id: "old", revision: 1, name: "old", body: "x", include: {upper: true, lower: false}}).include.accessories, true);
  assert.equal(fragmentDraft({id: "new", revision: 1, name: "new", body: "x", include: {accessories: false}}).include.accessories, false);
});

test("fragment list path preserves category, search and pagination", () => {
  const path = fragmentListPath({query: " smile ", categoryId: "expression", limit: 25, offset: 50});
  const url = new URL(path, "https://atelierx.test");
  assert.equal(url.searchParams.get("q"), "smile"); assert.equal(url.searchParams.get("category_id"), "expression");
  assert.equal(url.searchParams.get("offset"), "50"); assert.equal(url.searchParams.get("archived"), "false");
  assert.equal(pageOffsetForTotal(50, 25, 42), 25);
});

test("fragment list path sorts by name by default; a caller can opt back into number order", () => {
  assert.equal(new URL(fragmentListPath({}), "https://atelierx.test").searchParams.get("sort"), "name");
  assert.equal(new URL(fragmentListPath({sort: null}), "https://atelierx.test").searchParams.has("sort"), false);
});

test("selection survives list changes and remains revision-specific", () => {
  const first = {id: "a", revision: 2}; const changed = {id: "a", revision: 3};
  const selected = preserveSelection([], first, true);
  assert.deepEqual(selected, [first]); assert.equal(fragmentKey(first), "a@2"); assert.equal(sameFragmentReference(first, changed), false);
  assert.deepEqual(preserveSelection(selected, first, false), []);
});

test("editing draft detects changes and state keeps list position", () => {
  const item = {id: "a", revision: 1, number: 10, name: "Smile", body: "soft smile", category_id: "face", include: {upper: true, lower: false}};
  const state = initialFragmentState({query: "smile", categoryId: "face", offset: 25});
  assert.equal(state.offset, 25); assert.equal(state.query, "smile");
  const draft = fragmentDraft(item); assert.equal(draftChanged(draft, item), false);
  draft.body = "wide smile"; assert.equal(draftChanged(draft, item), true);
});

test("new form defaults do not trigger an unsaved-edit guard until meaningful input", () => {
  const draft = fragmentDraft();
  assert.equal(draftChanged(draft, null), false);
  draft.name = "New fragment";
  assert.equal(draftChanged(draft, null), true);
  const uncategorized = new URL(fragmentListPath({categoryId: "uncategorized"}), "https://atelierx.test");
  assert.equal(uncategorized.searchParams.get("category_id"), "uncategorized");
});

test("route restoration never replaces a retained editor, but opens a requested different detail", () => {
  const retained = fragmentDraft({id: "kept", revision: 1, number: 4, name: "Unsaved", body: "draft", include: {upper: true, lower: false}});
  assert.equal(shouldRestoreRouteDetail({requestedId: "kept", editor: retained, selected: {id: "kept"}}), false);
  assert.equal(shouldRestoreRouteDetail({requestedId: "linked", editor: retained, selected: {id: "kept"}}), true);
  assert.equal(shouldRestoreRouteDetail({requestedId: "linked", editor: null, selected: null}), true);
});

test("new-fragment route is an editor state, never a Core fragment lookup id", () => {
  assert.equal(routeFragmentId("new"), null);
  assert.equal(routeFragmentId(""), null);
  assert.equal(routeFragmentId("fragment-123"), "fragment-123");
  assert.equal(shouldRestoreRouteDetail({requestedId: routeFragmentId("new"), editor: null, selected: null}), false);
});

test("new route state initializes a blank editor only when no draft is retained", () => {
  const fresh = initialFragmentState({selectedId: "new"});
  assert.equal(prepareNewRouteState(fresh, fresh.selectedId), true);
  assert.equal(fresh.mobilePanel, "detail"); assert.equal(fresh.editor.name, "");
  const retained = initialFragmentState({editor: fragmentDraft()}); retained.editor.name = "kept draft";
  assert.equal(prepareNewRouteState(retained, "new"), false);
  assert.equal(retained.editor.name, "kept draft");
});
