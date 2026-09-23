import assert from "node:assert/strict";
import {
  clamp, wrapIndex, moveIndex, clampZoom, computeFitZoom, zoomAroundPoint, toggleFitOrActual,
  pointerDistance, pointerMidpoint, pinchZoom,
  createCompareState, markCompareA, enterCompare, exitCompare, swapCompare, toggleSync,
} from "../frontend/lightbox.js";

// clamp
assert.equal(clamp(5, 0, 10), 5);
assert.equal(clamp(-5, 0, 10), 0);
assert.equal(clamp(15, 0, 10), 10);

// wrapIndex / moveIndex
assert.equal(wrapIndex(0, 5), 0);
assert.equal(wrapIndex(5, 5), 0);
assert.equal(wrapIndex(-1, 5), 4);
assert.equal(wrapIndex(-6, 5), 4);
assert.equal(wrapIndex(3, 0), 0);
assert.equal(moveIndex(4, 5, 1), 0);
assert.equal(moveIndex(0, 5, -1), 4);
assert.equal(moveIndex(2, 5, 2), 4);

// clampZoom relative to fit scale
assert.equal(clampZoom(1, 2), 1);
assert.equal(clampZoom(0.0001, 2), 2 * 0.2);
assert.equal(clampZoom(1000, 2), 2 * 10);
assert.equal(clampZoom(Number.NaN, 2), 2);

// computeFitZoom
assert.equal(computeFitZoom(1000, 500, 500, 500), 0.5);
assert.equal(computeFitZoom(200, 800, 400, 400), 0.5);
assert.equal(computeFitZoom(0, 500, 400, 400), 1);
assert.equal(computeFitZoom(500, 500, 0, 400), 1);

// zoomAroundPoint keeps the point under the cursor fixed
{
  const view = {zoom: 1, panX: 10, panY: -4};
  const next = zoomAroundPoint(view, 2, 50, 30, 1);
  // The content coordinate under the cursor before and after zoom must match.
  const before = {x: (50 - view.panX) / view.zoom, y: (30 - view.panY) / view.zoom};
  const after = {x: (50 - next.panX) / next.zoom, y: (30 - next.panY) / next.zoom};
  assert.ok(Math.abs(before.x - after.x) < 1e-9);
  assert.ok(Math.abs(before.y - after.y) < 1e-9);
  assert.equal(next.zoom, 2);
}
{
  // Zoom is clamped, so at the max bound further zoom-in is a no-op and pan is unchanged.
  const view = {zoom: 10, panX: 3, panY: 7};
  const next = zoomAroundPoint(view, 5, 0, 0, 1);
  assert.equal(next.zoom, 10);
  assert.equal(next.panX, 3);
  assert.equal(next.panY, 7);
}

// toggleFitOrActual
assert.equal(toggleFitOrActual(0.5, 0.5, 1), 1);
assert.equal(toggleFitOrActual(1, 0.5, 1), 0.5);
assert.equal(toggleFitOrActual(0.7, 0.5, 1), 1);

// pointer distance / midpoint
assert.equal(pointerDistance({x: 0, y: 0}, {x: 3, y: 4}), 5);
assert.deepEqual(pointerMidpoint({x: 0, y: 0}, {x: 4, y: 10}), {x: 2, y: 5});

// pinchZoom
assert.equal(pinchZoom(1, 100, 200, 1), clampZoom(2, 1));
assert.equal(pinchZoom(2, 100, 50, 1), clampZoom(1, 1));
assert.equal(pinchZoom(1, 0, 200, 1), clampZoom(1, 1)); // guards against missing previous distance
assert.equal(pinchZoom(1, 100, 0, 1), clampZoom(1, 1));

// compare-mode state machine
{
  let state = createCompareState();
  assert.deepEqual(state, {aIndex: null, bIndex: null, active: false, synced: true});

  // Entering compare without an A first is a no-op.
  assert.deepEqual(enterCompare(state, 2), state);

  state = markCompareA(state, 0);
  assert.equal(state.aIndex, 0);
  assert.equal(state.active, false);

  // Comparing an image against itself is rejected.
  assert.deepEqual(enterCompare(state, 0), state);

  state = enterCompare(state, 3);
  assert.equal(state.bIndex, 3);
  assert.equal(state.active, true);

  const swapped = swapCompare(state);
  assert.equal(swapped.aIndex, 3);
  assert.equal(swapped.bIndex, 0);
  assert.equal(swapped.active, true);

  // Swapping while inactive is a no-op.
  assert.deepEqual(swapCompare(createCompareState()), createCompareState());

  const synced = toggleSync(state);
  assert.equal(synced.synced, false);
  assert.equal(toggleSync(synced).synced, true);

  const exited = exitCompare(state);
  assert.equal(exited.active, false);
  assert.equal(exited.aIndex, 0);
  assert.equal(exited.bIndex, 3);

  // Re-marking A to the current B while compare is active drops out of compare.
  const remarked = markCompareA(state, 3);
  assert.equal(remarked.aIndex, 3);
  assert.equal(remarked.active, false);
}

console.log("lightbox helpers: all assertions passed");
