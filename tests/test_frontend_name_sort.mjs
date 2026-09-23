import assert from "node:assert/strict";
import test from "node:test";
import { compareByName, sortByName } from "../frontend/name-sort.js";

test("compareByName sorts numeric codes in names naturally, not lexically", () => {
  const items = [{ id: "a", name: "C010 - 이름" }, { id: "b", name: "C002 - 이름" }, { id: "c", name: "C1 - 이름" }];
  assert.deepEqual(sortByName(items).map((item) => item.id), ["c", "b", "a"]);
});

test("compareByName is case-insensitive and locale-aware for Korean names", () => {
  const items = [{ id: "a", name: "banana" }, { id: "b", name: "Apple" }, { id: "c", name: "가나" }, { id: "d", name: "apple" }];
  const sorted = sortByName(items);
  // "Apple"/"apple" are equal under sensitivity:"base"; ties then break by id.
  assert.deepEqual(sorted.map((item) => item.id), ["c", "b", "d", "a"]);
});

test("ties break by id for a deterministic order", () => {
  const items = [{ id: "z", name: "같음" }, { id: "a", name: "같음" }];
  assert.deepEqual(sortByName(items).map((item) => item.id), ["a", "z"]);
});

test("sortByName does not mutate the input array and tolerates missing names/ids", () => {
  const items = [{ id: "b", name: "b" }, { id: "a", name: "a" }];
  const sorted = sortByName(items);
  assert.notEqual(sorted, items);
  assert.deepEqual(items.map((item) => item.id), ["b", "a"]);
  assert.doesNotThrow(() => sortByName([{ id: "x" }, {}, null, undefined]));
});
