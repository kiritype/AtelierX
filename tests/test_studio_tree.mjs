import assert from "node:assert/strict";
import test from "node:test";
import {studioTreeItems, studioTreeModel} from "../frontend/studio-tree.js";

const items = [
  {id: "w", kind: "works", name: "긴 작품 이름"},
  {id: "c", type: "character", parent_id: "w", name: "인물"},
  {id: "o", type: "outfit", parent_id: "c", name: "의상"},
  {id: "orphan", type: "outfit", parent_id: "missing", name: "고아"},
];

test("normalizes Core plural kinds without mutating supplied records", () => {
  const normalized = studioTreeItems(items);
  assert.equal(normalized[0].type, "work");
  assert.equal(items[0].type, undefined);
});

test("only valid work character outfit links become tree descendants", () => {
  const model = studioTreeModel(items);
  assert.equal(model.length, 1);
  assert.equal(model[0].item.id, "w");
  assert.equal(model[0].children[0].item.id, "c");
  assert.equal(model[0].children[0].children[0].item.id, "o");
});

test("siblings at every depth are sorted by name ascending, numeric-aware", () => {
  const mixed = [
    {id: "w2", type: "work", name: "C010 작품"}, {id: "w1", type: "work", name: "C002 작품"},
    {id: "c2", type: "character", parent_id: "w1", name: "B 캐릭터"}, {id: "c1", type: "character", parent_id: "w1", name: "A 캐릭터"},
  ];
  const model = studioTreeModel(mixed);
  assert.deepEqual(model.map((entry) => entry.item.id), ["w1", "w2"]);
  assert.deepEqual(model[0].children.map((entry) => entry.item.id), ["c1", "c2"]);
});
