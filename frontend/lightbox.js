/**
 * Full-screen image lightbox for the review and gallery screens.
 *
 * The pure helpers below (index wrapping, zoom/pan math, compare-mode state)
 * have no DOM dependency so they can be unit tested directly. `openLightbox`
 * is the only DOM-facing export; it builds the overlay, wires listeners, and
 * returns a controller so the caller (a screen module) can close it when the
 * screen unmounts.
 *
 * Touch behaviour (pinch-zoom, one-finger pan) is implemented with Pointer
 * Events on a best-effort basis; it has not been verified on a physical
 * mobile device.
 */

export const MIN_ZOOM_FACTOR = 0.2;
export const MAX_ZOOM_FACTOR = 10;

export function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value));
}

/** Wraps an index into [0, length). Negative and overflowing indexes cycle. */
export function wrapIndex(index, length) {
  if (!Number.isInteger(length) || length <= 0) return 0;
  const n = ((index % length) + length) % length;
  return n;
}

export function moveIndex(index, length, delta) {
  return wrapIndex((Number.isInteger(index) ? index : 0) + delta, length);
}

/** Zoom is expressed in "natural pixel" scale; fitZoom is the scale that fits
 * the image inside its container (may be < 1 or > 1). Bounds are relative to
 * that fit scale so very large/small images behave consistently. */
export function clampZoom(zoom, fitZoom = 1) {
  const base = Number.isFinite(fitZoom) && fitZoom > 0 ? fitZoom : 1;
  return clamp(Number.isFinite(zoom) ? zoom : base, base * MIN_ZOOM_FACTOR, base * MAX_ZOOM_FACTOR);
}

export function computeFitZoom(naturalWidth, naturalHeight, containerWidth, containerHeight) {
  if (!(naturalWidth > 0) || !(naturalHeight > 0) || !(containerWidth > 0) || !(containerHeight > 0)) return 1;
  return Math.min(containerWidth / naturalWidth, containerHeight / naturalHeight);
}

/** Zooms a view (zoom/panX/panY, where the transform is translate(pan) then
 * scale(zoom) around the container center) so the point under (pointerX,
 * pointerY) — relative to the container center — stays fixed on screen. */
export function zoomAroundPoint(view, factor, pointerX, pointerY, fitZoom = 1) {
  const zoom = Number.isFinite(view?.zoom) ? view.zoom : fitZoom;
  const panX = Number.isFinite(view?.panX) ? view.panX : 0;
  const panY = Number.isFinite(view?.panY) ? view.panY : 0;
  const nextZoom = clampZoom(zoom * factor, fitZoom);
  if (nextZoom === zoom) return {zoom, panX, panY};
  const scale = nextZoom / zoom;
  return {
    zoom: nextZoom,
    panX: pointerX - (pointerX - panX) * scale,
    panY: pointerY - (pointerY - panY) * scale,
  };
}

/** Toggles between the fit scale and 100% (natural pixel) scale. */
export function toggleFitOrActual(currentZoom, fitZoom, actualZoom = 1) {
  return Math.abs(currentZoom - actualZoom) < Math.max(0.01, actualZoom * 0.02) ? fitZoom : actualZoom;
}

export function pointerMidpoint(a, b) {
  return {x: (a.x + b.x) / 2, y: (a.y + b.y) / 2};
}

export function pointerDistance(a, b) {
  return Math.hypot(a.x - b.x, a.y - b.y);
}

/** Scales zoom by the ratio of pinch distances. Guards against a zero or
 * missing previous distance (e.g. the very first pinch sample). */
export function pinchZoom(previousZoom, previousDistance, nextDistance, fitZoom = 1) {
  if (!(previousDistance > 0) || !(nextDistance > 0)) return clampZoom(previousZoom, fitZoom);
  return clampZoom(previousZoom * (nextDistance / previousDistance), fitZoom);
}

// --- Compare-mode state -----------------------------------------------
// Kept as plain data + pure transitions so the workflow (mark A, enter
// compare with B, swap, exit, toggle sync) is testable without a DOM.

export function createCompareState() {
  return {aIndex: null, bIndex: null, active: false, synced: true};
}

export function markCompareA(state, index) {
  const aIndex = Number.isInteger(index) ? index : null;
  return {...state, aIndex, active: state.active && state.bIndex !== null && state.bIndex !== aIndex};
}

export function enterCompare(state, bIndex) {
  if (state.aIndex === null || !Number.isInteger(bIndex) || bIndex === state.aIndex) return state;
  return {...state, bIndex, active: true};
}

export function exitCompare(state) {
  return {...state, active: false};
}

export function swapCompare(state) {
  if (!state.active) return state;
  return {...state, aIndex: state.bIndex, bIndex: state.aIndex};
}

export function toggleSync(state) {
  return {...state, synced: !state.synced};
}

// --- DOM ----------------------------------------------------------------

function node(tag, props = {}, children = []) {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(props)) {
    if (value === undefined || value === null) continue;
    if (key === "text") el.textContent = String(value);
    else if (key === "class") el.className = value;
    else if (key.startsWith("on")) el.addEventListener(key.slice(2).toLowerCase(), value);
    else el.setAttribute(key, String(value));
  }
  for (const child of Array.isArray(children) ? children : [children]) {
    if (child !== undefined && child !== null) el.append(child);
  }
  return el;
}

function focusableElements(root) {
  return [...root.querySelectorAll('button:not([disabled]), [href], input, select, textarea, [tabindex]:not([tabindex="-1"])')]
    .filter((el) => el.offsetParent !== null || el === document.activeElement);
}

/**
 * Opens the lightbox over `images` (an array of
 * `{id?, src?, loadSrc?, title?, caption?}`), starting at `startIndex`.
 *
 * Exactly one of `src` (an already-usable URL, e.g. an existing blob URL) or
 * `loadSrc` (an `() => Promise<string>` returning a usable URL, called
 * lazily and cached per image — used for images that require an
 * authenticated fetch through the shared API client) must be present.
 *
 * `options.signal`, when given, closes the lightbox when aborted (used so a
 * screen unmount via `ctx.signal` cannot leave the overlay open).
 * `options.onClose` is called once, after cleanup, however the lightbox closed.
 *
 * Returns `{close}`.
 */
export function openLightbox(images, startIndex, options = {}) {
  const list = Array.isArray(images) ? images : [];
  if (!list.length) throw new Error("표시할 이미지가 없습니다.");
  const previouslyFocused = document.activeElement;
  let closed = false;
  const urlCache = new Map();
  const ownedUrls = new Set();

  const state = {
    index: wrapIndex(startIndex, list.length),
    view: {zoom: 1, panX: 0, panY: 0, fitZoom: 1, naturalWidth: 0, naturalHeight: 0},
    viewB: {zoom: 1, panX: 0, panY: 0, fitZoom: 1, naturalWidth: 0, naturalHeight: 0},
    compare: createCompareState(),
    loadEpoch: {a: 0, b: 0},
  };

  const overlay = node("div", {class: "lightbox-overlay", role: "dialog", "aria-modal": "true", "aria-label": "이미지 확대 보기"});
  const dialog = node("div", {class: "lightbox-dialog"});
  const header = node("div", {class: "lightbox-header"});
  const indexLabel = node("span", {class: "lightbox-index"});
  const titleLabel = node("strong", {class: "lightbox-title"});
  const captionLabel = node("span", {class: "lightbox-caption"});
  const meta = node("div", {class: "lightbox-meta"}, [indexLabel, titleLabel, captionLabel]);

  const markAButton = node("button", {type: "button", class: "button lightbox-button", "aria-label": "현재 이미지를 비교 A로 지정"});
  const compareButton = node("button", {type: "button", class: "button lightbox-button", "aria-label": "현재 이미지를 비교 B로 지정해 나란히 보기"});
  const swapButton = node("button", {type: "button", class: "button secondary lightbox-button", text: "A/B 바꾸기", "aria-label": "비교 A와 B 바꾸기"});
  const syncButton = node("button", {type: "button", class: "button secondary lightbox-button", "aria-label": "비교 확대·이동 동기화 전환"});
  const exitCompareButton = node("button", {type: "button", class: "button secondary lightbox-button", text: "비교 종료", "aria-label": "비교 보기 종료"});
  const zoomOutButton = node("button", {type: "button", class: "button lightbox-button", text: "−", "aria-label": "축소"});
  const zoomInButton = node("button", {type: "button", class: "button lightbox-button", text: "+", "aria-label": "확대"});
  const actualButton = node("button", {type: "button", class: "button lightbox-button", text: "1:1", "aria-label": "실제 크기(100%)"});
  const fitButton = node("button", {type: "button", class: "button lightbox-button", text: "맞춤", "aria-label": "화면에 맞춤"});
  const closeButton = node("button", {type: "button", class: "button lightbox-close", text: "닫기 ×", "aria-label": "닫기"});
  const toolbar = node("div", {class: "lightbox-toolbar"}, [
    markAButton, compareButton, swapButton, syncButton, exitCompareButton,
    zoomOutButton, zoomInButton, actualButton, fitButton, closeButton,
  ]);
  header.append(meta, toolbar);

  function makePane(key) {
    const label = node("span", {class: "lightbox-pane-label"});
    const img = node("img", {class: "lightbox-image", alt: ""});
    const status = node("p", {class: "muted lightbox-pane-status"});
    const paneNav = node("div", {class: "lightbox-pane-nav"});
    const container = node("div", {class: "lightbox-pane", "data-pane": key}, [label, node("div", {class: "lightbox-pane-frame"}, [img, status]), paneNav]);
    return {container, img, status, label, paneNav};
  }
  const paneA = makePane("a");
  const paneB = makePane("b");
  paneB.container.hidden = true;

  const prevButton = node("button", {type: "button", class: "button lightbox-nav lightbox-prev", text: "‹", "aria-label": "이전 이미지"});
  const nextButton = node("button", {type: "button", class: "button lightbox-nav lightbox-next", text: "›", "aria-label": "다음 이미지"});
  const panes = node("div", {class: "lightbox-panes"}, [paneA.container, paneB.container]);
  const stage = node("div", {class: "lightbox-stage"}, [prevButton, panes, nextButton]);

  dialog.append(header, stage);
  overlay.append(dialog);

  function applyTransform(pane, view) {
    pane.img.style.transform = `translate(${view.panX}px, ${view.panY}px) scale(${view.zoom})`;
  }

  function resetView(view) {
    view.zoom = view.fitZoom || 1;
    view.panX = 0;
    view.panY = 0;
  }

  function loadImageInto(pane, view, index, epochKey) {
    const entry = list[index];
    const epoch = ++state.loadEpoch[epochKey];
    pane.label.textContent = entry?.title ? entry.title : `이미지 ${index + 1}`;
    pane.status.textContent = "불러오는 중…";
    pane.status.hidden = false;
    pane.img.removeAttribute("src");
    view.naturalWidth = 0; view.naturalHeight = 0;
    const cached = urlCache.get(index);
    const promise = cached || (typeof entry?.src === "string"
      ? Promise.resolve(entry.src)
      : typeof entry?.loadSrc === "function"
        ? Promise.resolve(entry.loadSrc()).then((url) => { if (typeof url === "string") ownedUrls.add(url); return url; })
        : Promise.reject(new Error("이미지 경로가 없습니다.")));
    urlCache.set(index, promise);
    promise.then((url) => {
      if (closed || state.loadEpoch[epochKey] !== epoch) return;
      pane.img.onload = () => {
        if (closed || state.loadEpoch[epochKey] !== epoch) return;
        view.naturalWidth = pane.img.naturalWidth || 0;
        view.naturalHeight = pane.img.naturalHeight || 0;
        const rect = pane.container.getBoundingClientRect();
        view.fitZoom = computeFitZoom(view.naturalWidth, view.naturalHeight, rect.width, rect.height);
        resetView(view);
        applyTransform(pane, view);
        pane.status.hidden = true;
      };
      pane.img.onerror = () => { if (!closed && state.loadEpoch[epochKey] === epoch) pane.status.textContent = "이미지를 불러올 수 없습니다."; };
      pane.img.alt = entry?.title || `이미지 ${index + 1}`;
      pane.img.src = url;
    }).catch(() => { if (!closed && state.loadEpoch[epochKey] === epoch) pane.status.textContent = "이미지를 불러올 수 없습니다."; });
  }

  function render() {
    const total = list.length;
    const current = list[state.index];
    indexLabel.textContent = `${state.index + 1} / ${total}`;
    titleLabel.textContent = current?.title || "";
    captionLabel.textContent = current?.caption || "";
    captionLabel.hidden = !current?.caption;
    titleLabel.hidden = !current?.title;

    const compareOn = state.compare.active;
    paneB.container.hidden = !compareOn;
    dialog.classList.toggle("lightbox-compare", compareOn);
    swapButton.hidden = !compareOn;
    syncButton.hidden = !compareOn;
    exitCompareButton.hidden = !compareOn;
    syncButton.textContent = state.compare.synced ? "동기화 해제" : "동기화 켜기";
    syncButton.setAttribute("aria-pressed", String(state.compare.synced));

    markAButton.hidden = compareOn;
    markAButton.textContent = state.compare.aIndex === state.index ? "비교 A (현재)" : "비교 A로 지정";

    const canCompare = !compareOn && state.compare.aIndex !== null && state.compare.aIndex !== state.index;
    compareButton.hidden = compareOn || state.compare.aIndex === null;
    compareButton.disabled = !canCompare;
    compareButton.textContent = "이 이미지와 비교";

    prevButton.hidden = compareOn || total < 2;
    nextButton.hidden = compareOn || total < 2;

    if (!compareOn) {
      loadImageInto(paneA, state.view, state.index, "a");
    } else {
      paneA.paneNav.replaceChildren(
        node("button", {type: "button", class: "button secondary", text: "◀", "aria-label": "비교 A 이전 이미지", onclick: () => { state.compare = {...state.compare, aIndex: moveIndex(state.compare.aIndex, total, -1)}; render(); }}),
        node("span", {class: "muted", text: `A · ${state.compare.aIndex + 1} / ${total}`}),
        node("button", {type: "button", class: "button secondary", text: "▶", "aria-label": "비교 A 다음 이미지", onclick: () => { state.compare = {...state.compare, aIndex: moveIndex(state.compare.aIndex, total, 1)}; render(); }}),
      );
      paneB.paneNav.replaceChildren(
        node("button", {type: "button", class: "button secondary", text: "◀", "aria-label": "비교 B 이전 이미지", onclick: () => { state.compare = {...state.compare, bIndex: moveIndex(state.compare.bIndex, total, -1)}; render(); }}),
        node("span", {class: "muted", text: `B · ${state.compare.bIndex + 1} / ${total}`}),
        node("button", {type: "button", class: "button secondary", text: "▶", "aria-label": "비교 B 다음 이미지", onclick: () => { state.compare = {...state.compare, bIndex: moveIndex(state.compare.bIndex, total, 1)}; render(); }}),
      );
      loadImageInto(paneA, state.view, state.compare.aIndex, "a");
      loadImageInto(paneB, state.viewB, state.compare.bIndex, "b");
    }
  }

  function go(delta) {
    if (state.compare.active) return;
    state.index = moveIndex(state.index, list.length, delta);
    render();
  }

  function syncedViews() {
    return state.compare.active && state.compare.synced;
  }

  function zoomBy(factor, clientX, clientY, target = "a") {
    const pane = target === "b" ? paneB : paneA;
    const view = target === "b" ? state.viewB : state.view;
    const rect = pane.container.getBoundingClientRect();
    const px = (clientX ?? rect.left + rect.width / 2) - rect.left - rect.width / 2;
    const py = (clientY ?? rect.top + rect.height / 2) - rect.top - rect.height / 2;
    const next = zoomAroundPoint(view, factor, px, py, view.fitZoom);
    view.zoom = next.zoom; view.panX = next.panX; view.panY = next.panY;
    applyTransform(pane, view);
    if (syncedViews()) {
      const other = target === "b" ? state.view : state.viewB;
      const otherPane = target === "b" ? paneA : paneB;
      other.zoom = view.zoom; other.panX = view.panX; other.panY = view.panY;
      applyTransform(otherPane, other);
    }
  }

  function toggleZoomAt(clientX, clientY, target = "a") {
    const pane = target === "b" ? paneB : paneA;
    const view = target === "b" ? state.viewB : state.view;
    const rect = pane.container.getBoundingClientRect();
    const px = (clientX ?? rect.left + rect.width / 2) - rect.left - rect.width / 2;
    const py = (clientY ?? rect.top + rect.height / 2) - rect.top - rect.height / 2;
    const targetZoom = toggleFitOrActual(view.zoom, view.fitZoom, 1);
    const factor = targetZoom / (view.zoom || 1);
    zoomBy(factor, clientX, clientY, target);
  }

  function setZoomAbsolute(target, zoom) {
    const view = target === "b" ? state.viewB : state.view;
    const factor = zoom / (view.zoom || 1);
    zoomBy(factor, undefined, undefined, target);
  }

  function panBy(dx, dy, target = "a") {
    const pane = target === "b" ? paneB : paneA;
    const view = target === "b" ? state.viewB : state.view;
    view.panX += dx; view.panY += dy;
    applyTransform(pane, view);
    if (syncedViews()) {
      const other = target === "b" ? state.view : state.viewB;
      const otherPane = target === "b" ? paneA : paneB;
      other.panX = view.panX; other.panY = view.panY;
      applyTransform(otherPane, other);
    }
  }

  // --- Pointer handling (mouse drag + touch pan/pinch) ---
  function wirePane(pane, target) {
    const pointers = new Map();
    let dragLast = null;
    let pinchStartDistance = null;
    let pinchStartZoom = null;

    pane.img.addEventListener("dblclick", (event) => { event.preventDefault(); toggleZoomAt(event.clientX, event.clientY, target); });

    pane.container.addEventListener("wheel", (event) => {
      event.preventDefault();
      const factor = Math.pow(1.0015, -event.deltaY);
      zoomBy(factor, event.clientX, event.clientY, target);
    }, {passive: false});

    pane.container.addEventListener("pointerdown", (event) => {
      if (event.button !== undefined && event.button > 0) return;
      pointers.set(event.pointerId, {x: event.clientX, y: event.clientY});
      pane.container.setPointerCapture?.(event.pointerId);
      if (pointers.size === 1) dragLast = {x: event.clientX, y: event.clientY};
      if (pointers.size === 2) {
        const [p1, p2] = [...pointers.values()];
        pinchStartDistance = pointerDistance(p1, p2);
        pinchStartZoom = (target === "b" ? state.viewB : state.view).zoom;
      }
    });
    pane.container.addEventListener("pointermove", (event) => {
      if (!pointers.has(event.pointerId)) return;
      pointers.set(event.pointerId, {x: event.clientX, y: event.clientY});
      if (pointers.size >= 2) {
        const [p1, p2] = [...pointers.values()];
        const distance = pointerDistance(p1, p2);
        const view = target === "b" ? state.viewB : state.view;
        const nextZoom = pinchZoom(pinchStartZoom, pinchStartDistance, distance, view.fitZoom);
        setZoomAbsolute(target, nextZoom);
        const mid = pointerMidpoint(p1, p2);
        if (dragLast) { panBy(mid.x - dragLast.x, mid.y - dragLast.y, target); }
        dragLast = mid;
        return;
      }
      if (dragLast) {
        panBy(event.clientX - dragLast.x, event.clientY - dragLast.y, target);
        dragLast = {x: event.clientX, y: event.clientY};
      }
    });
    const release = (event) => {
      pointers.delete(event.pointerId);
      pane.container.releasePointerCapture?.(event.pointerId);
      if (pointers.size === 0) { dragLast = null; pinchStartDistance = null; }
      else if (pointers.size === 1) { dragLast = [...pointers.values()][0]; pinchStartDistance = null; }
    };
    pane.container.addEventListener("pointerup", release);
    pane.container.addEventListener("pointercancel", release);
    pane.container.addEventListener("pointerleave", (event) => { if (pointers.size <= 1) release(event); });
  }
  wirePane(paneA, "a");
  wirePane(paneB, "b");

  // --- Toolbar / nav wiring ---
  markAButton.addEventListener("click", () => { state.compare = markCompareA(state.compare, state.index); render(); });
  compareButton.addEventListener("click", () => { state.compare = enterCompare(state.compare, state.index); render(); });
  swapButton.addEventListener("click", () => { state.compare = swapCompare(state.compare); render(); });
  syncButton.addEventListener("click", () => { state.compare = toggleSync(state.compare); if (state.compare.synced) { state.viewB = {...state.view}; applyTransform(paneB, state.viewB); } render(); });
  exitCompareButton.addEventListener("click", () => { state.compare = exitCompare(state.compare); render(); });
  zoomOutButton.addEventListener("click", () => zoomBy(0.8));
  zoomInButton.addEventListener("click", () => zoomBy(1.25));
  actualButton.addEventListener("click", () => setZoomAbsolute("a", 1));
  fitButton.addEventListener("click", () => setZoomAbsolute("a", state.view.fitZoom || 1));
  prevButton.addEventListener("click", () => go(-1));
  nextButton.addEventListener("click", () => go(1));
  closeButton.addEventListener("click", () => close());
  overlay.addEventListener("mousedown", (event) => { if (event.target === overlay) close(); });

  function onKeydown(event) {
    if (event.key === "Escape") { event.preventDefault(); close(); return; }
    if (event.key === "ArrowLeft") { event.preventDefault(); go(-1); return; }
    if (event.key === "ArrowRight") { event.preventDefault(); go(1); return; }
    if (event.key === "Tab") {
      const focusable = focusableElements(dialog);
      if (!focusable.length) return;
      const first = focusable[0], last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    }
  }
  document.addEventListener("keydown", onKeydown);

  let abortListenerTarget = null;
  const onAbort = () => close();
  if (options.signal) {
    if (options.signal.aborted) { queueMicrotask(() => close()); }
    else { options.signal.addEventListener("abort", onAbort); abortListenerTarget = options.signal; }
  }

  function close() {
    if (closed) return;
    closed = true;
    document.removeEventListener("keydown", onKeydown);
    if (abortListenerTarget) abortListenerTarget.removeEventListener("abort", onAbort);
    overlay.remove();
    for (const url of ownedUrls) { try { URL.revokeObjectURL(url); } catch { /* ignore */ } }
    ownedUrls.clear();
    if (previouslyFocused && typeof previouslyFocused.focus === "function") {
      try { previouslyFocused.focus(); } catch { /* ignore */ }
    }
    options.onClose?.();
  }

  document.body.append(overlay);
  render();
  closeButton.focus();

  return {close};
}
