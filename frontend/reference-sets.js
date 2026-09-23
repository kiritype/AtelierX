/**
 * ADR-0027 reference sets and generation consistency — shared helpers plus the
 * character-management outfit panel (sample generation, pair selection,
 * confirm/reconfirm, minimal history).
 *
 * Pure helpers at the top have no DOM dependency so they are unit tested
 * directly. `mountReferenceSetPanel` is the only DOM-facing export used by
 * `production.js`'s outfit editor; `openLightbox` from `lightbox.js` is reused
 * for viewing full/face images.
 */
import { openLightbox } from "./lightbox.js";

const STATUS_LABELS = Object.freeze({ none: "없음", valid: "유효", needs_review: "재확인 필요" });
const STALE_LABELS = Object.freeze({ character: "캐릭터", outfit: "의상" });
const REFERENCE_SETTINGS_LABELS = Object.freeze({
  diffusion_model: "Diffusion model", text_encoder: "Text encoder",
  common_fragments: "공통 적용 조각", positive_quality: "품질 Positive", loras: "LoRA",
});

export function referenceStatusLabel(status) {
  return STATUS_LABELS[status] || "알 수 없음";
}

export function referenceStaleText(stale) {
  if (!Array.isArray(stale) || !stale.length) return "";
  return `변경됨: ${stale.map((name) => STALE_LABELS[name] || name).join(", ")}`;
}

/** `settings_summary` -> ordered `{label, text}` rows for display. */
export function referenceSettingsSummaryRows(summary) {
  if (!summary || typeof summary !== "object") return [];
  const rows = [];
  for (const key of ["diffusion_model", "text_encoder", "common_fragments", "positive_quality", "loras"]) {
    if (!(key in summary)) continue;
    const value = summary[key];
    const text = key === "common_fragments" ? (Array.isArray(value) && value.length ? value.map((item) => `${item.id}@${item.revision}`).join(", ") : "없음")
      : key === "loras" ? (Array.isArray(value) && value.length ? value.map((item) => `${item.name}×${item.strength}`).join(", ") : "없음")
      : (value || "(없음)");
    rows.push({ key, label: REFERENCE_SETTINGS_LABELS[key] || key, text: String(text) });
  }
  return rows;
}

/** `CORE_REFERENCE_SETTINGS_MISMATCH`'s `{diff:{field:{reference,plan}}}` -> display rows. */
export function referenceMismatchDiffRows(diff) {
  if (!diff || typeof diff !== "object") return [];
  return Object.entries(diff).map(([field, value]) => ({
    field, label: REFERENCE_SETTINGS_LABELS[field] || field,
    reference: JSON.stringify(value?.reference ?? null), plan: JSON.stringify(value?.plan ?? null),
  }));
}

/** Normalizes a `consistency_methods[].params` schema entry set against
 * current values, clamping to min/max and reporting keys under `warn_below`. */
export function consistencyFormValues(paramsSchema, current = {}) {
  const values = {};
  const warnings = [];
  for (const [key, spec] of Object.entries(paramsSchema || {})) {
    if (!spec || typeof spec !== "object") continue;
    if (spec.type === "boolean") {
      values[key] = current[key] === undefined ? Boolean(spec.default) : Boolean(current[key]);
      continue;
    }
    let value = current[key] === undefined || current[key] === "" ? Number(spec.default) : Number(current[key]);
    if (!Number.isFinite(value)) value = Number(spec.default) || 0;
    if (typeof spec.min === "number") value = Math.max(spec.min, value);
    if (typeof spec.max === "number") value = Math.min(spec.max, value);
    if (typeof spec.warn_below === "number" && value < spec.warn_below) warnings.push(key);
    values[key] = value;
  }
  return { values, warnings };
}

/** Normalizes `GET /v1/generation/resources`'s `consistency_methods` list. */
export function consistencyMethodChoices(methods) {
  return (Array.isArray(methods) ? methods : []).map((method) => ({
    id: method?.id, families: Array.isArray(method?.families) ? method.families : [],
    available: method?.available !== false, reason: method?.unavailable_reason || null,
    params: method?.params && typeof method.params === "object" ? method.params : {},
  })).filter((method) => method.id);
}

/** Estimated per-image seconds with ADR-0027 P7's consistency-method factor
 * (~3.3x measured). Returns null when there is nothing to scale. */
export function estimatedSecondsWithConsistency(baseSeconds, consistencyOn, factor = 3.3) {
  if (!Number.isFinite(baseSeconds) || baseSeconds <= 0) return null;
  return consistencyOn ? baseSeconds * factor : baseSeconds;
}

/** Tracks the user's choice of one full and one face image, possibly from
 * different sample pairs (spec allows mixing). */
export function selectPairImage(selection, role, pairId, imageId) {
  const next = { ...(selection || {}) };
  if (role === "full") { next.fullPairId = pairId; next.fullImageId = imageId; }
  else if (role === "face") { next.facePairId = pairId; next.faceImageId = imageId; }
  return next;
}

export function pairSelectionReady(selection) {
  return Boolean(selection?.fullImageId && selection?.faceImageId);
}

export function togglePairMultiSelect(selectedIds, pairId, checked) {
  const next = new Set(selectedIds || []);
  checked ? next.add(pairId) : next.delete(pairId);
  return [...next];
}

/** Builds `POST /v1/outfits/{id}/reference-samples`'s body. */
export function sampleGenerationInputs(generation) {
  const number = (value, name, { integer = false } = {}) => {
    const n = Number(value);
    if (!Number.isFinite(n) || (integer && !Number.isInteger(n))) throw new Error(`${name} 값을 확인하세요.`);
    return n;
  };
  const seed = number(generation.seed, "Seed", { integer: true });
  if (!Number.isSafeInteger(seed) || seed < -1) throw new Error("Seed는 -1(랜덤) 또는 0 이상의 안전 정수여야 합니다.");
  return {
    diffusion_model: String(generation.diffusion_model || "").trim(),
    text_encoder: String(generation.text_encoder || "").trim(),
    vae: String(generation.vae || "").trim(),
    width: number(generation.width, "너비", { integer: true }), height: number(generation.height, "높이", { integer: true }),
    seed, steps: number(generation.steps, "Steps", { integer: true }), cfg: number(generation.cfg, "CFG"),
    sampler: String(generation.sampler || "").trim(), scheduler: String(generation.scheduler || "").trim(),
    loras: (generation.loras || []).filter((item) => item.name?.trim()).map((item) => ({ name: item.name.trim(), strength: number(item.strength, "LoRA 가중치") })),
  };
}

export function sampleRequestBody(generation, commonFragments, count = 1) {
  const body = { generation_inputs: sampleGenerationInputs(generation) };
  if (commonFragments?.length) body.common_fragments = commonFragments;
  const requests = [];
  for (let index = 0; index < Math.max(1, Math.min(4, Number(count) || 1)); index += 1) requests.push({ ...body });
  return requests;
}

/** Reference sample templates (settings.reference_templates) <-> form draft. */
export function referenceTemplatesDraft(templates) {
  const role = (value) => ({ framing_prompt: value?.framing_prompt || "", include: { upper: Boolean(value?.include?.upper), lower: Boolean(value?.include?.lower), accessories: Boolean(value?.include?.accessories), hands: Boolean(value?.include?.hands) } });
  return { full: role(templates?.full), face: role(templates?.face) };
}

export function referenceTemplatesFromDraft(draft) {
  const role = (value) => ({ framing_prompt: String(value.framing_prompt || "").trim(), include: { upper: Boolean(value.include.upper), lower: Boolean(value.include.lower), accessories: Boolean(value.include.accessories), hands: Boolean(value.include.hands) } });
  if (!draft.full.framing_prompt.trim() || !draft.face.framing_prompt.trim()) throw new Error("전신·얼굴 구도 문구를 모두 입력하세요.");
  return { full: role(draft.full), face: role(draft.face) };
}

// -- DOM: character-management outfit panel ---------------------------------

function el(tag, properties = {}, children = []) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(properties)) {
    if (value === undefined || value === null || value === false) continue;
    if (key === "text") node.textContent = String(value);
    else if (key === "class") node.className = value;
    else if (key === "checked") node.checked = Boolean(value);
    else if (key.startsWith("on")) node.addEventListener(key.slice(2).toLowerCase(), value);
    else node.setAttribute(key, String(value));
  }
  for (const child of Array.isArray(children) ? children.flat() : [children]) if (child) node.append(child);
  return node;
}
const button = (text, onclick, { secondary = false, disabled = false } = {}) => el("button", { type: "button", class: secondary ? "button secondary" : "button", disabled, onclick, text });
const field = (label, control, hint) => el("div", { class: "field" }, [el("label", { text: label }), control, hint ? el("small", { class: "muted", text: hint }) : null]);
const errorText = (error) => error?.code ? `${error.code}: ${error.message || "요청을 완료하지 못했습니다."}` : (error?.message || "요청을 완료하지 못했습니다.");
const makeKey = () => (globalThis.crypto?.randomUUID ? globalThis.crypto.randomUUID() : `ref-${Date.now()}-${Math.random().toString(36).slice(2)}`);
const DEFAULT_GENERATION = { diffusion_model: "", text_encoder: "", vae: "", width: 1024, height: 1024, seed: -1, steps: 24, cfg: 4.5, sampler: "euler_ancestral", scheduler: "normal" };

function imageThumb(ctx, imageId, label, onOpen) {
  const img = el("img", { class: "reference-set-thumb", alt: label });
  img.style.maxHeight = "160px";
  ctx.api.imageBlob(`/v1/images/${imageId}/content`).then((blob) => {
    const url = URL.createObjectURL(blob);
    ctx.ownedUrls?.add(url);
    img.src = url;
  }).catch(() => { img.alt = `${label} (불러오기 실패)`; });
  img.tabIndex = 0; img.role = "button"; img.setAttribute("aria-label", `${label} 확대 보기`);
  img.addEventListener("click", onOpen);
  img.addEventListener("keydown", (event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); onOpen(); } });
  return img;
}

/** Mount the reference-set section inside the character-management outfit
 * editor. Returns a dispose function; caller must call it on unmount/outfit
 * change (it owns object URLs and does its own polling). */
export function mountReferenceSetPanel(container, ctx) {
  const state = {
    status: null, pairs: [], loading: true, error: null,
    generation: { ...DEFAULT_GENERATION }, seedMode: "random", pairCount: 1,
    commonFragments: [], selectedCommon: [],
    selection: {}, multiSelect: [], pending: false, pendingKeys: {}, templates: null,
    historyOpen: false, history: null,
  };
  const ownedUrls = new Set();
  let disposed = false;
  let pollHandle = null;

  const load = async (showSpinner = true) => {
    if (disposed) return;
    if (showSpinner) { state.loading = true; render(); }
    try {
      const [status, samples] = await Promise.all([
        ctx.api.get(`/v1/outfits/${ctx.outfitId}/reference-set`),
        ctx.api.get(`/v1/outfits/${ctx.outfitId}/reference-samples`),
      ]);
      if (disposed) return;
      state.status = status; state.pairs = Array.isArray(samples.items) ? samples.items : [];
      state.loading = false; state.error = null;
    } catch (error) { if (!disposed) { state.error = errorText(error); state.loading = false; } }
    if (!disposed) render();
  };

  const loadAncillary = async () => {
    try {
      if (!ctx.resources) ctx.resources = await ctx.api.get("/v1/generation/resources").catch(() => null);
      const settings = await ctx.api.get("/v1/settings");
      state.templates = settings?.reference_templates || null;
      const fragments = await ctx.api.get("/v1/prompt-fragments?archived=false&limit=200&offset=0").catch(() => ({ items: [] }));
      state.commonFragments = (fragments.items || []).filter((item) => item.common);
    } catch { /* best effort: sample form still works with manual model names */ }
    if (!disposed) render();
  };

  const hasPending = () => (state.pairs || []).some((pair) => ["queued", "dispatching", "generation_pending", "generating"].includes(pair.full_task?.state) || ["queued", "dispatching", "generation_pending", "generating"].includes(pair.face_task?.state));
  const schedulePoll = () => {
    if (pollHandle || disposed) return;
    if (!hasPending()) return;
    pollHandle = setTimeout(async () => { pollHandle = null; if (!disposed) { await load(false); schedulePoll(); } }, 4000);
  };
  ctx.signal?.addEventListener("abort", () => { disposed = true; if (pollHandle) clearTimeout(pollHandle); for (const url of ownedUrls) URL.revokeObjectURL(url); });

  const submitSamples = async () => {
    try {
      const generation = { ...state.generation };
      if (state.seedMode === "random") generation.seed = -1;
      const commonFragments = state.selectedCommon.map((item) => ({ id: item.id, revision: item.revision }));
      state.pending = true; render();
      const requests = sampleRequestBody(generation, commonFragments, state.pairCount);
      for (const body of requests) {
        const key = makeKey();
        await ctx.api.post(`/v1/outfits/${ctx.outfitId}/reference-samples`, body, key);
      }
      ctx.notify?.("참조 샘플 생성을 접수했습니다.");
      await load(false); schedulePoll();
    } catch (error) { ctx.notify?.(errorText(error), true); } finally { state.pending = false; render(); }
  };

  const regenerateSelectedPairs = async () => {
    const targets = state.pairs.filter((pair) => state.multiSelect.includes(pair.id));
    if (!targets.length) return;
    try {
      state.pending = true; render();
      for (const pair of targets) {
        const gen = pair.full_task?.snapshot?.generation_inputs || state.generation;
        const generation = { ...gen, seed: -1 };
        const commonFragments = (pair.full_task?.snapshot?.common_fragments || []).map((item) => ({ id: item.id, revision: item.revision }));
        const body = sampleRequestBody(generation, commonFragments, 1)[0];
        await ctx.api.post(`/v1/outfits/${ctx.outfitId}/reference-samples`, body, makeKey());
      }
      state.multiSelect = [];
      ctx.notify?.("선택한 쌍을 새 Seed로 다시 생성했습니다.");
      await load(false); schedulePoll();
    } catch (error) { ctx.notify?.(errorText(error), true); } finally { state.pending = false; render(); }
  };

  const confirmSet = async () => {
    if (!pairSelectionReady(state.selection)) return;
    try {
      state.pending = true; render();
      const key = makeKey();
      await ctx.api.post(`/v1/outfits/${ctx.outfitId}/reference-set/confirm`, { full_image_id: state.selection.fullImageId, face_image_id: state.selection.faceImageId }, key);
      state.selection = {};
      ctx.notify?.("참조 세트를 확정했습니다.");
      await load(false);
    } catch (error) { ctx.notify?.(errorText(error), true); } finally { state.pending = false; render(); }
  };

  const reconfirm = async () => {
    if (!state.status?.set) return;
    try {
      state.pending = true; render();
      await ctx.api.post(`/v1/outfits/${ctx.outfitId}/reference-set/reconfirm`, { revision: state.status.set.revision }, makeKey());
      ctx.notify?.("변경을 확인하고 현재 참조 세트를 유지했습니다.");
      await load(false);
    } catch (error) { ctx.notify?.(errorText(error), true); } finally { state.pending = false; render(); }
  };

  const loadHistory = async () => {
    try {
      state.history = await ctx.api.get(`/v1/outfits/${ctx.outfitId}/reference-set/revisions?limit=20&offset=0`);
    } catch (error) { ctx.notify?.(errorText(error), true); }
    render();
  };

  function pairCard(pair) {
    const running = ["queued", "dispatching", "generation_pending", "generating"].includes(pair.full_task?.state) || ["queued", "dispatching", "generation_pending", "generating"].includes(pair.face_task?.state);
    const failed = pair.full_task?.state === "failed" || pair.face_task?.state === "failed";
    const roleImages = (role, task) => {
      if (task?.state !== "generated" || !task.images?.length) return el("p", { class: "muted", text: running ? "생성 중…" : failed ? "생성 실패" : "이미지 없음" });
      const image = task.images[0];
      const selected = role === "full" ? state.selection.fullImageId === image.id : state.selection.faceImageId === image.id;
      const openViewer = () => { const entries = task.images.map((item) => ({ id: item.id, title: `${role === "full" ? "전신" : "얼굴"} · Seed ${pair.seed}`, loadSrc: () => ctx.api.imageBlob(`/v1/images/${item.id}/content`).then((blob) => { const url = URL.createObjectURL(blob); ownedUrls.add(url); return url; }) })); openLightbox(entries, 0, { signal: ctx.signal }); };
      return el("div", {}, [imageThumb({ api: ctx.api, ownedUrls }, image.id, role === "full" ? "전신" : "얼굴", openViewer),
        el("label", { class: "row" }, [el("input", { type: "radio", name: `reference-${role}`, checked: selected, onchange: () => { state.selection = selectPairImage(state.selection, role, pair.id, image.id); render(); } }), el("span", { text: role === "full" ? "전신으로 선택" : "얼굴로 선택" })])]);
    };
    return el("li", { class: "panel reference-sample-pair" }, [
      el("div", { class: "row" }, [el("input", { type: "checkbox", "aria-label": `쌍 ${pair.seed} 선택`, checked: state.multiSelect.includes(pair.id), onchange: (event) => { state.multiSelect = togglePairMultiSelect(state.multiSelect, pair.id, event.target.checked); render(); } }),
        el("strong", { text: `Seed ${pair.seed}` }), running ? el("span", { class: "badge", text: "생성 중" }) : failed ? el("span", { class: "badge error", text: "실패" }) : el("span", { class: "badge", text: "완료" })]),
      el("div", { class: "row" }, [roleImages("full", pair.full_task), roleImages("face", pair.face_task)]),
    ]);
  }

  function render() {
    if (disposed) return;
    if (state.loading) { container.replaceChildren(el("p", { class: "muted", text: "참조 세트를 불러오는 중…" })); return; }
    const status = state.status || { status: "none", set: null, stale: [] };
    const summaryRows = referenceSettingsSummaryRows(status.set?.settings_summary);
    const header = el("section", { class: "panel reference-set-panel" }, [
      el("h3", { text: "참조 세트" }),
      el("p", {}, [el("span", { class: "badge", text: referenceStatusLabel(status.status) }), status.status === "needs_review" ? el("span", { class: "muted", text: ` ${referenceStaleText(status.stale)}` }) : null]),
      status.set ? el("div", { class: "row" }, [
        imageThumb({ api: ctx.api, ownedUrls }, status.set.full.core_image_id, "전신", () => openLightbox([
          { id: status.set.full.core_image_id, title: "전신", loadSrc: () => ctx.api.imageBlob(`/v1/images/${status.set.full.core_image_id}/content`).then((blob) => { const url = URL.createObjectURL(blob); ownedUrls.add(url); return url; }) },
          { id: status.set.face.core_image_id, title: "얼굴", loadSrc: () => ctx.api.imageBlob(`/v1/images/${status.set.face.core_image_id}/content`).then((blob) => { const url = URL.createObjectURL(blob); ownedUrls.add(url); return url; }) },
        ], 0, { signal: ctx.signal })),
        imageThumb({ api: ctx.api, ownedUrls }, status.set.face.core_image_id, "얼굴", () => openLightbox([
          { id: status.set.face.core_image_id, title: "얼굴", loadSrc: () => ctx.api.imageBlob(`/v1/images/${status.set.face.core_image_id}/content`).then((blob) => { const url = URL.createObjectURL(blob); ownedUrls.add(url); return url; }) },
        ], 0, { signal: ctx.signal })),
        el("div", {}, [el("p", { text: `revision ${status.set.revision} · Seed ${status.set.seed}` }),
          el("p", { class: "muted", text: `확정 시각: ${new Date(status.set.confirmed_at * 1000).toLocaleString("ko-KR")}` }),
          ...summaryRows.map((row) => el("p", { class: "muted", text: `${row.label}: ${row.text}` }))]),
      ]) : el("p", { class: "muted", text: "확정된 참조 세트가 없습니다. 아래에서 샘플을 만들고 전신·얼굴을 골라 확정하세요." }),
      status.status === "needs_review" ? el("div", { class: "toolbar" }, [button("변경 확인 후 유지", reconfirm, { disabled: state.pending }), el("p", { class: "muted", text: "이미지는 바꾸지 않고 현재 캐릭터·의상 revision으로 다시 확정합니다." })]) : null,
      el("details", {}, [el("summary", { text: "확정 이력" }), state.history ? el("ul", {}, (state.history.items || []).map((item) => el("li", { text: `r${item.revision} · Seed ${item.seed} · ${new Date(item.confirmed_at * 1000).toLocaleString("ko-KR")}` }))) : button("이력 불러오기", loadHistory, { secondary: true })]),
    ]);

    const templateInfo = state.templates ? el("details", {}, [el("summary", { text: "사용 중인 구도 템플릿 (읽기 전용)" }),
      el("p", { class: "muted", text: `전신: ${state.templates.full?.framing_prompt || ""}` }), el("p", { class: "muted", text: `얼굴: ${state.templates.face?.framing_prompt || ""}` }),
      el("p", { class: "muted", text: "구도 문구는 설정 > 참조 템플릿에서 바꿀 수 있습니다." })]) : null;

    const generationFields = ["diffusion_model", "text_encoder", "vae", "sampler", "scheduler"].map((key) => field(key, el("input", { type: "text", value: state.generation[key], oninput: (event) => { state.generation[key] = event.target.value; } })));
    const numberFields = [["steps", 1, 100, 1], ["cfg", 0, 20, 0.1]].map(([key, min, max, step]) => field(key, el("input", { type: "number", value: state.generation[key], min, max, step, oninput: (event) => { state.generation[key] = event.target.value; } })));
    const seedControl = el("div", { class: "field" }, [el("label", { text: "Seed" }),
      el("select", { onchange: (event) => { state.seedMode = event.target.value; render(); } }, [el("option", { value: "random", selected: state.seedMode === "random", text: "-1: 이미지별 무작위" }), el("option", { value: "fixed", selected: state.seedMode === "fixed", text: "고정값" })]),
      state.seedMode === "fixed" ? el("input", { type: "number", min: 0, step: 1, value: state.generation.seed === -1 ? "" : state.generation.seed, oninput: (event) => { state.generation.seed = event.target.value; } }) : null]);
    const commonFragmentList = el("ul", { class: "fragment-list" }, state.commonFragments.map((item) => {
      const key = `${item.id}@${item.revision}`;
      const checked = state.selectedCommon.some((selected) => `${selected.id}@${selected.revision}` === key);
      return el("li", { class: "row" }, [el("input", { type: "checkbox", checked, onchange: (event) => { state.selectedCommon = event.target.checked ? [...state.selectedCommon, item] : state.selectedCommon.filter((selected) => `${selected.id}@${selected.revision}` !== key); } }), el("span", { text: item.name })]);
    }));
    const sampleForm = el("section", { class: "panel reference-sample-form" }, [
      el("h3", { text: "참조 샘플 생성" }), templateInfo,
      el("div", { class: "grid" }, [...generationFields, ...numberFields, seedControl,
        field("생성할 쌍 수 (1~4)", el("input", { type: "number", min: 1, max: 4, step: 1, value: state.pairCount, oninput: (event) => { state.pairCount = Math.max(1, Math.min(4, Number(event.target.value) || 1)); } }), "각 쌍은 같은 Seed의 전신·얼굴 2개 Task로, 서로 다른 Seed로 별도 요청합니다.")]),
      state.commonFragments.length ? el("div", {}, [el("h4", { text: "공통 적용 프롬프트" }), commonFragmentList]) : null,
      el("div", { class: "toolbar" }, [button("샘플 쌍 생성", submitSamples, { disabled: state.pending })]),
    ]);

    const pairsSection = el("section", { class: "panel reference-sample-pairs" }, [
      el("h3", { text: `샘플 쌍 (${state.pairs.length})` }),
      state.pairs.length ? el("ul", { class: "reference-sample-pair-list" }, state.pairs.map(pairCard)) : el("p", { class: "muted", text: "아직 만든 샘플이 없습니다." }),
      el("div", { class: "toolbar" }, [
        button("참조 세트로 확정", confirmSet, { disabled: state.pending || !pairSelectionReady(state.selection) }),
        button("선택한 쌍 다시 생성", regenerateSelectedPairs, { secondary: true, disabled: state.pending || !state.multiSelect.length }),
      ]),
      !pairSelectionReady(state.selection) ? el("p", { class: "muted", text: "각 카드에서 전신 하나·얼굴 하나를 골라야 확정할 수 있습니다(다른 쌍이어도 됩니다)." }) : null,
    ]);

    container.replaceChildren(header, sampleForm, pairsSection, state.error ? el("p", { class: "error", text: state.error }) : null);
  }

  load().then(() => { schedulePoll(); loadAncillary(); });
  return () => { disposed = true; if (pollHandle) clearTimeout(pollHandle); for (const url of ownedUrls) URL.revokeObjectURL(url); };
}
