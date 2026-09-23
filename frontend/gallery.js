const el = (tag, text = "", className = "") => {
  const node = document.createElement(tag);
  node.textContent = text;
  if (className) node.className = className;
  return node;
};
const key = () => crypto.randomUUID();
const errorText = (error) => error?.code ? `${error.code}: ${error.message || "Request failed"}` : error?.message || String(error);
export const verdictLabel = value => ({passed:"통과",failed:"불합격",matched:"일치",mismatch:"불일치",reference:"기준 이미지",stale:"이전 기준",insufficient:"비교 불충분",reference_conflict:"기준 충돌",not_eligible:"검사 대상 제외",error:"실행 오류",unvalidated:"미검증",pending:"대기",cancelled:"취소",completed:"검사 완료",running:"검사 중",queued:"대기"}[value] || value || "미검증");

export function eligibleIds(consistency) {
  return Array.isArray(consistency?.eligible_image_ids) ? [...new Set(consistency.eligible_image_ids)] : [];
}

export function referenceRequest(revision, representativeId, auxiliaryIds) {
  const ids = [representativeId, ...auxiliaryIds];
  if (!Number.isInteger(revision) || !representativeId || auxiliaryIds.length > 2 || new Set(ids).size !== ids.length) {
    throw new Error("대표 1장과 서로 다른 보조 이미지 최대 2장을 선택하세요.");
  }
  return {revision, representative_id: representativeId, auxiliary_ids: auxiliaryIds};
}

export function groupValidationRequest(consistency, targetIds, validation) {
  const reference = consistency?.reference;
  const eligible = new Set(eligibleIds(consistency));
  const current = new Set(Array.isArray(consistency?.target_ids) ? consistency.target_ids : []);
  const refs = new Set(reference ? [reference.representative_id, ...(reference.auxiliary_ids || [])] : []);
  if (!reference || !Number.isInteger(reference.revision) || !Array.isArray(targetIds) || targetIds.length < 1 || targetIds.length > 32 ||
      new Set(targetIds).size !== targetIds.length || targetIds.some((id) => !eligible.has(id) || !current.has(id) || refs.has(id)) ||
      !validation?.profile_id || !validation?.provider_id) {
    throw new Error("현재 기준 revision, 적격 대상 1..32장, 묶음 Profile과 Provider를 선택하세요.");
  }
  return {reference_revision: reference.revision, target_ids: targetIds, validation};
}

export function replacementRequest(consistency, targetImageId, regeneration, groupValidation) {
  const reference = consistency?.reference;
  const currentTargets = new Set(Array.isArray(consistency?.target_ids) ? consistency.target_ids : []);
  if (!reference || !Number.isInteger(reference.revision) || !currentTargets.has(targetImageId) ||
      !regeneration?.validation?.profile_id || !regeneration.validation.provider_id ||
      !groupValidation?.profile_id || !groupValidation.provider_id) {
    throw new Error("현재 기준 revision, 현재 대상 이미지, 단일 및 묶음 검증 선택을 확인하세요.");
  }
  return {reference_revision: reference.revision, target_image_id: targetImageId, regeneration, group_validation: groupValidation};
}

export function activeDetail(disposed, currentEpoch, expectedEpoch, selectedId, imageId) {
  return !disposed && currentEpoch === expectedEpoch && selectedId === imageId;
}

export function resolvedSeed(snapshot) {
  const seed = snapshot?.generation_inputs?.seed;
  return Number.isSafeInteger(seed) && seed >= 0 ? seed : null;
}

export function classificationFilters(filters, kind, id) {
  const next = {...filters};
  if (kind === "works") { next.work_id = id; delete next.character_id; delete next.outfit_id; }
  if (kind === "characters") { next.character_id = id; delete next.outfit_id; }
  if (kind === "outfits") next.outfit_id = id;
  return next;
}

export function postprocessRequest(draft) {
  if (draft.preset) {
    const [id, revision] = String(draft.preset).split("@");
    if (!id || !Number.isInteger(Number(revision)) || Number(revision) < 1) throw new Error("후처리 Preset을 선택하세요.");
    return {preset: {id, revision: Number(revision)}};
  }
  let postprocess;
  if (draft.advanced) {
    try { postprocess = JSON.parse(draft.advanced); } catch { throw new Error("고급 후처리 JSON 형식이 올바르지 않습니다."); }
  } else {
    postprocess = {};
    if (draft.upscaleEnabled) {
      const scale = Number(draft.upscaleScale), model = String(draft.upscaleModel || "").trim();
      if (!model || !Number.isFinite(scale) || scale <= 0) throw new Error("Upscale 모델과 양의 배율을 입력하세요.");
      postprocess.upscale = {upscale_model: model, scale};
    }
    if (draft.encodeEnabled) {
      const quality = Number(draft.webpQuality);
      if (!Number.isSafeInteger(quality) || quality < 1 || quality > 100) throw new Error("WebP 품질은 1..100 정수여야 합니다.");
      postprocess.encode = {webp_enabled: Boolean(draft.webpEnabled), webp_quality: quality};
    }
  }
  if (!postprocess || typeof postprocess !== "object" || Array.isArray(postprocess) || !Object.keys(postprocess).length) throw new Error("실행할 후처리 stage를 하나 이상 선택하세요.");
  return {postprocess};
}

export const FINDING_SOURCE_LABELS = Object.freeze({character_features: "외형 특징", character_appearance: "외형 설명", outfit_upper: "상의", outfit_lower: "하의", outfit_accessories: "액세서리", outfit_hands: "손", fragment: "조각"});
export const findingSourceLabel = (source) => (source && FINDING_SOURCE_LABELS[source]) || null;

export function singleValidationSummary(run) {
  const result = run?.result && typeof run.result === "object" ? run.result : {};
  const describe = (item) => {
    const source = findingSourceLabel(item?.source);
    const subject = String(item?.prompt_excerpt || item?.expected || item?.feature || item?.code || "항목");
    const observed = item?.observed ? String(item.observed) : "";
    return {source, subject, observed, text: `${source ? `[${source}] ` : ""}${subject}${observed ? ` — ${observed}` : ""}`};
  };
  const diagnostics = (result.diagnostics && typeof result.diagnostics === "object" ? result.diagnostics : null) || (run?.diagnostics && typeof run.diagnostics === "object" ? run.diagnostics : {});
  const dropped = diagnostics.regeneration_proposal_dropped;
  return {
    findings: (Array.isArray(result.findings) ? result.findings : []).map(describe),
    notAssessable: (Array.isArray(result.not_assessable) ? result.not_assessable : []).map(describe),
    proposalDropped: typeof dropped === "string" && dropped ? dropped : null,
  };
}

export function outputPathText(image) {
  return typeof image?.output_path === "string" && image.output_path.trim() ? image.output_path : null;
}

function singleValidationView(run) {
  const summary = singleValidationSummary(run);
  const wrap = el("div", "", "validation-result");
  const list = (items) => { const ul = el("ul"); for (const item of items) ul.append(el("li", item.text)); return ul; };
  if (summary.findings.length) wrap.append(el("h4", `불합격 근거 ${summary.findings.length}개`), list(summary.findings));
  else if (run?.result) wrap.append(el("p", "불합격 근거가 없습니다.", "muted"));
  if (summary.notAssessable.length) {
    const box = el("details", "", "validation-not-assessable");
    box.append(el("summary", `판단 불가 항목 ${summary.notAssessable.length}개 (불합격 아님)`), el("p", "이미지나 구도로 확인할 수 없어 판정에서 제외한 항목입니다.", "muted"), list(summary.notAssessable));
    wrap.append(box);
  }
  if (summary.proposalDropped) wrap.append(el("p", "재생성 제안 형식 오류로 제안을 생략했습니다.", "muted"));
  if (run?.error) wrap.append(el("p", errorText(run.error), "error"));
  return wrap;
}

function field(label, value = "", type = "text") {
  const wrap = el("label", "", "field");
  wrap.append(el("span", label));
  const input = document.createElement("input");
  input.type = type;
  input.value = value;
  wrap.append(input);
  return [wrap, input];
}
function select(label, values) {
  const wrap = el("label", "", "field");
  wrap.append(el("span", label));
  const input = document.createElement("select");
  for (const [value, title] of values) {
    const option = document.createElement("option"); option.value = value; option.textContent = title; input.append(option);
  }
  wrap.append(input); return [wrap, input];
}
function button(title, action, className = "button") {
  const item = el("button", title, className); item.type = "button"; item.addEventListener("click", action); return item;
}

export async function mount(container, ctx) {
  const state = ctx.state;
  const reviewMode = ctx.mode === "review";
  state.filters ??= {}; state.offset ??= 0; state.mutationKeys ??= {}; state.inflight ??= {};
  if (!reviewMode && !state.galleryInitialFilterApplied && !Object.keys(state.filters).length) {
    state.filters.single_outcome = "passed";
    state.galleryInitialFilterApplied = true;
  }
  state.classification ??= {works: [], characters: {}, outfits: {}, expanded: {}, loading: {}, error: null};
  if (state.selectedId) { state.selected = state.selectedId; state.selectedId = null; }
  const cardUrls = new Set(); const detailUrls = new Set();
  let disposed = false;
  let refreshEpoch = 0; let detailEpoch = 0;
  const mutationKey = (scope, body) => {
    const fingerprint = `${scope}:${JSON.stringify(body)}`;
    return [fingerprint, state.mutationKeys[fingerprint] ??= key()];
  };
  const revoke = (urls) => { for (const url of urls) URL.revokeObjectURL(url); urls.clear(); };
  const mutate = async (item, scope, body, request) => {
    const [fingerprint, requestKey] = mutationKey(scope, body);
    if (state.inflight[fingerprint]) return state.inflight[fingerprint];
    item.disabled = true;
    const pending = (async () => {
      try { return await request(requestKey); }
      finally { delete state.inflight[fingerprint]; item.disabled = false; }
    })();
    state.inflight[fingerprint] = pending;
    return pending;
  };
  container.replaceChildren();
  const root = el("section", "", "panel");
  const toolbar = el("div", "", "toolbar");
  const cards = el("div", "", "gallery-grid");
  const detail = el("aside", "이미지를 선택하세요.", "panel muted");
  const message = el("p", "", "error");
  const browser = el("aside", "", "classification-tree panel");
  const layout = el("div", "", "gallery-browser-layout");
  layout.classList.toggle("gallery-review", reviewMode);
  layout.classList.toggle("detail-open", Boolean(state.mobileDetail));
  const treeToggle = button("작품·캐릭터 선택", () => {
    const open = layout.classList.toggle("tree-open"); treeToggle.setAttribute("aria-expanded", String(open));
  }, "mobile-only button");
  treeToggle.setAttribute("aria-expanded", "false");
  toolbar.append(treeToggle);
  layout.append(browser, cards, detail); root.append(toolbar, message, layout); container.append(root);
  root.prepend(el("p", reviewMode ? "이미지별 검사 이력과 현재 그룹 일관성을 검토합니다." : "단일 검사 통과 결과를 탐색하고 원본을 내려받습니다. 그룹 일관성 상태는 카드에서 별도로 확인하세요.", "muted"));

  const [singleWrap, single] = select("단일 검사", [["", "전체"], ["passed", "통과"], ["failed", "불합격"], ["pending", "대기"], ["error", "오류"], ["unvalidated", "미검증"], ["cancelled", "취소"]]);
  const [groupWrap, group] = select("묶음 검사", [["", "전체"], ["matched", "일치"], ["mismatch", "불일치"], ["reference", "기준"], ["stale", "이전 기준"], ["insufficient", "부족"], ["reference_conflict", "기준 충돌"], ["not_eligible", "대상 제외"], ["error", "오류"], ["unvalidated", "미검증"]]);
  const [mediaWrap, media] = select("형식", [["", "전체"], ["image/png", "PNG"], ["image/webp", "WebP"]]);
  single.value = state.filters.single_outcome || ""; group.value = state.filters.group_status || ""; media.value = state.filters.media_type || "";
  toolbar.append(singleWrap, groupWrap, mediaWrap);
  toolbar.append(button(reviewMode ? "통과 결과 보기" : "통과 결과만", () => {
    single.value = "passed"; group.value = "matched"; state.offset = 0; clearDetail(); refresh();
  }), el("span", "단일 통과 + 현재 기준 그룹 일치", "muted"));
  if (!reviewMode) toolbar.append(button("미검증 보기", () => {
    single.value = "unvalidated"; group.value = ""; state.offset = 0; clearDetail(); refresh();
  }), button("전체 결과", () => {
    for (const input of [single, group, media]) input.value = "";
    state.filters = {}; state.offset = 0; clearDetail(); renderClassification(); refresh();
  }));
  toolbar.append(button("필터 적용", () => { state.offset = 0; refresh(); }), button("초기화", () => {
    for (const input of [single, group, media]) input.value = ""; state.filters = {}; state.offset = 0; clearDetail(); renderClassification(); refresh();
  }));

  const collection = (payload) => Array.isArray(payload?.items) ? payload.items : [];
  let classificationEpoch = 0;
  const clearDetail = () => { state.selected = null; state.mobileDetail = false; layout.classList.remove("detail-open"); detailEpoch++; revoke(detailUrls); detail.replaceChildren(el("p", "이미지를 선택하세요.", "muted")); };
  const backToList = () => { clearDetail(); ctx.onDetailChange?.(null); };
  let imageQueue = [], imageLoads = 0;
  const drainImages = () => {
    if (disposed) return;
    while (imageLoads < 3 && imageQueue.length) {
      const load = imageQueue.shift(); imageLoads++;
      load().finally(() => { imageLoads--; drainImages(); });
    }
  };
  const observeImages = typeof IntersectionObserver === "function" ? new IntersectionObserver(entries => {
    for (const entry of entries) if (entry.isIntersecting) {
      observeImages.unobserve(entry.target); imageQueue.push(entry.target.loadPreview); drainImages();
    }
  }, {rootMargin: "200px"}) : null;
  const entityPath = (kind, parentId) => `/v1/${kind}?${new URLSearchParams({parent_id: parentId, limit: "200", offset: "0"})}`;
  const loadChildren = async (kind, parentId) => {
    const tree = state.classification; const cache = kind === "characters" ? tree.characters : tree.outfits;
    if (cache[parentId] || tree.loading[`${kind}:${parentId}`]) return;
    tree.loading[`${kind}:${parentId}`] = true; renderClassification();
    try { cache[parentId] = collection(await ctx.api.get(entityPath(kind, parentId))); tree.error = null; }
    catch (error) { tree.error = errorText(error); }
    finally { delete tree.loading[`${kind}:${parentId}`]; if (!disposed) renderClassification(); }
  };
  const selectClassification = (kind, item) => {
    state.filters = classificationFilters(state.filters, kind, item.id); state.offset = 0; clearDetail(); layout.classList.remove("tree-open"); treeToggle.setAttribute("aria-expanded", "false"); renderClassification(); refresh();
  };
  const row = (kind, item, childrenKind = null) => {
    const tree = state.classification; const expandedKey = `${kind}:${item.id}`; const hasChildren = Boolean(childrenKind);
    const line = el("div", "", "tree-row"); line.setAttribute("role", "treeitem");
    if (hasChildren) {
      const expanded = Boolean(tree.expanded[expandedKey]); const toggle = button(expanded ? "˅" : ">", async () => {
        tree.expanded[expandedKey] = !expanded; if (tree.expanded[expandedKey]) await loadChildren(childrenKind, item.id); else renderClassification();
      }, "tree-toggle"); toggle.setAttribute("aria-expanded", String(expanded)); toggle.setAttribute("aria-label", `${item.name} ${expanded ? "접기" : "펼치기"}`); line.append(toggle);
    }
    const choose = button(item.name || item.id, () => selectClassification(kind, item), "tree-select");
    choose.setAttribute("aria-current", String(state.filters[`${kind.slice(0, -1)}_id`] === item.id)); line.append(choose);
    const wrapper = el("div", ""); wrapper.append(line);
    if (hasChildren && tree.expanded[expandedKey]) {
      const children = childrenKind === "characters" ? tree.characters[item.id] : tree.outfits[item.id];
      const group = el("div", "", "tree-children"); group.setAttribute("role", "group");
      if (tree.loading[`${childrenKind}:${item.id}`]) group.append(el("p", "불러오는 중…", "muted"));
      else if (!children?.length) group.append(el("p", "하위 분류가 없습니다.", "muted"));
      else for (const child of children) group.append(row(childrenKind, child, childrenKind === "characters" ? "outfits" : null));
      wrapper.append(group);
    }
    return wrapper;
  };
  const renderClassification = () => {
    const tree = state.classification; browser.replaceChildren(el("h2", "분류 탐색")); browser.setAttribute("role", "tree");
    if (tree.error) { const retry = button("분류 다시 불러오기", loadWorks); browser.append(el("p", tree.error, "error"), retry); }
    if (tree.loading.works) browser.append(el("p", "작품을 불러오는 중…", "muted"));
    else if (!tree.works.length) browser.append(el("p", "작품 분류가 없습니다.", "muted"));
    else for (const workItem of tree.works) browser.append(row("works", workItem, "characters"));
  };
  const loadWorks = async () => {
    const epoch = ++classificationEpoch; const tree = state.classification; tree.loading.works = true; tree.error = null; renderClassification();
    try { tree.works = collection(await ctx.api.get("/v1/works?limit=200&offset=0")); }
    catch (error) { if (epoch === classificationEpoch) tree.error = errorText(error); }
    finally { if (epoch === classificationEpoch) { delete tree.loading.works; if (!disposed) renderClassification(); } }
  };

  async function refresh() {
    const epoch = ++refreshEpoch;
    observeImages?.disconnect(); imageQueue = [];
    message.textContent = ""; cards.replaceChildren(el("p", "불러오는 중…", "muted"));
    const filters = {...state.filters, single_outcome: single.value, group_status: group.value, media_type: media.value};
    state.filters = Object.fromEntries(Object.entries(filters).filter(([, value]) => value));
    const query = new URLSearchParams({ ...state.filters, limit: "30", offset: String(state.offset) });
    try {
      const page = await ctx.api.get(`/v1/images?${query}`);
      if (disposed || epoch !== refreshEpoch) return;
      revoke(cardUrls);
      cards.replaceChildren();
      if (!page.items.length) cards.append(el("p", "조건에 맞는 이미지가 없습니다.", "muted"));
      for (const image of page.items) cards.append(card(image));
      const pager = el("div", "", "toolbar");
      pager.append(el("span", `총 ${page.total}개`, "muted"));
      pager.append(button("이전", () => { state.offset = Math.max(0, state.offset - page.limit); refresh(); }));
      pager.append(button("다음", () => { if (state.offset + page.limit < page.total) { state.offset += page.limit; refresh(); } }));
      cards.append(pager);
    } catch (error) { if (!disposed && epoch === refreshEpoch) { cards.replaceChildren(); message.textContent = errorText(error); ctx.notify(message.textContent, true); } }
  }
  function card(image) {
    const item = el("article", "", "panel");
    const preview = document.createElement("img"); preview.alt = "생성 이미지"; preview.loading = "lazy";
    item.append(preview, el("strong", image.media_type), el("span", `단일: ${verdictLabel(image.single_outcome)}`, "badge"), el("span", `그룹: ${verdictLabel(image.group_status)}`, "badge"));
    item.append(el("small", image.id, "muted"));
    item.setAttribute("role", "button"); item.tabIndex = 0; item.setAttribute("aria-label", `이미지 상세 열기: ${image.id}`);
    const openDetail = () => { ctx.onDetailChange?.(image.id); showDetail(image.id); };
    item.addEventListener("click", openDetail);
    item.addEventListener("keydown", (event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); openDetail(); } });
    const epoch = refreshEpoch;
    item.loadPreview = async () => {
      if (disposed || epoch !== refreshEpoch) return;
      await ctx.api.imageBlob(image.content_url).then((blob) => {
      const url = URL.createObjectURL(blob);
      if (disposed || epoch !== refreshEpoch) { URL.revokeObjectURL(url); return; }
      cardUrls.add(url); preview.src = url;
      }).catch(() => { if (!disposed && epoch === refreshEpoch) preview.alt = "이미지를 불러올 수 없음"; });
    };
    if (observeImages) observeImages.observe(item); else { imageQueue.push(item.loadPreview); drainImages(); }
    return item;
  }
  async function showDetail(imageId) {
    state.mobileDetail = true; layout.classList.add("detail-open");
    state.selected = imageId; const epoch = ++detailEpoch; revoke(detailUrls); detail.replaceChildren(el("p", "상세를 불러오는 중…", "muted"));
    try {
      const image = await ctx.api.get(`/v1/images/${imageId}`);
      const task = await ctx.api.get(`/v1/tasks/${image.task_id}`);
      const history = await ctx.api.get(`/v1/images/${imageId}/validations`);
      if (!activeDetail(disposed, detailEpoch, epoch, state.selected, imageId)) return;
      const seed = resolvedSeed(task.snapshot);
      detail.replaceChildren(el("h2", "이미지 상세"), el("p", `형식: ${image.media_type} · ${image.bytes} bytes`), el("p", `Task: ${image.task_id}`, "muted"), ...(seed === null ? [] : [el("p", `Seed: ${seed}`)]));
      detail.prepend(button("← 이미지 목록", backToList, "button mobile-only"));
      const outputPath = outputPathText(image);
      if (outputPath) { const pathLine = el("p", "", "output-path"); pathLine.append(el("span", "파일 경로: "), el("code", outputPath)); detail.append(pathLine); }
      if (task.snapshot?.fragment?.id) {
        const fragmentInfo = el("p", "조각 번호 확인 중…", "muted"); detail.append(fragmentInfo);
        ctx.api.get(`/v1/prompt-fragments/${task.snapshot.fragment.id}`).then(fragment => {
          if (activeDetail(disposed, detailEpoch, epoch, state.selected, imageId)) fragmentInfo.textContent = `조각 #${fragment.number ?? "–"} · 생성 당시 revision ${task.snapshot.fragment.revision}`;
        }).catch(() => { if (activeDetail(disposed, detailEpoch, epoch, state.selected, imageId)) fragmentInfo.textContent = "조각 번호 조회 불가 · 당시 생성 입력은 아래에서 확인할 수 있습니다."; });
      }
      const enlarged = document.createElement("img"); enlarged.alt = "선택한 생성 이미지"; enlarged.style.maxHeight = "480px"; enlarged.style.maxWidth = "100%";
      const retryImage = button("이미지 다시 불러오기", () => loadImage()); retryImage.hidden = true;
      let enlargedUrl = null;
      const loadImage = () => {
        retryImage.hidden = true; enlarged.alt = "이미지를 불러오는 중…";
        ctx.api.imageBlob(image.content_url || `/v1/images/${image.id}/content`).then((blob) => {
          const url = URL.createObjectURL(blob);
          if (!activeDetail(disposed, detailEpoch, epoch, state.selected, imageId)) { URL.revokeObjectURL(url); return; }
          if (enlargedUrl) { URL.revokeObjectURL(enlargedUrl); detailUrls.delete(enlargedUrl); }
          enlargedUrl = url;
          detailUrls.add(url); enlarged.src = url; enlarged.alt = "선택한 생성 이미지";
        }).catch((error) => {
          if (activeDetail(disposed, detailEpoch, epoch, state.selected, imageId)) { enlarged.alt = `이미지를 불러올 수 없음: ${errorText(error)}`; retryImage.hidden = false; }
        });
      };
      enlarged.addEventListener("error", () => { if (activeDetail(disposed, detailEpoch, epoch, state.selected, imageId)) retryImage.hidden = false; });
      detail.append(enlarged, retryImage);
      if (!reviewMode) detail.append(button("원본 내려받기", async () => {
        try {
          const blob = await ctx.api.imageBlob(image.content_url || `/v1/images/${image.id}/content`);
          const url = URL.createObjectURL(blob); const anchor = document.createElement("a");
          anchor.href = url; anchor.download = `${image.id}.${image.media_type === "image/webp" ? "webp" : "png"}`;
          anchor.click(); setTimeout(() => URL.revokeObjectURL(url), 0);
        } catch (error) { ctx.notify(errorText(error), true); }
      }));
      loadImage();
      const inputs = task.snapshot?.generation_inputs || {};
      const prompt = { positive_prompt: inputs.positive_prompt ?? "", negative_prompt: inputs.negative_prompt ?? "" };
      const inputsDetail = el("details"); inputsDetail.append(el("summary", "생성 당시 프롬프트·설정"), el("h3", "당시 Prompt"), el("pre", JSON.stringify(prompt, null, 2)), el("h3", "당시 후처리 설정"), el("pre", JSON.stringify(task.snapshot?.postprocess ?? {}, null, 2))); detail.append(inputsDetail);
      detail.append(el("h3", "단일 검사 이력"));
      for (const run of history.items) {
        const row = el("div", `${verdictLabel(run.state)}${run.outcome ? ` / ${verdictLabel(run.outcome)}` : ""}`, "row");
        const resultBox = el("div");
        if (run.result || run.error) resultBox.append(singleValidationView(run));
        row.append(button("결과", async () => {
          try {
            const current = await ctx.api.get(`/v1/validation-runs/${run.id}`);
            if (activeDetail(disposed, detailEpoch, epoch, state.selected, imageId)) resultBox.replaceChildren(singleValidationView(current));
          } catch (error) { if (activeDetail(disposed, detailEpoch, epoch, state.selected, imageId)) ctx.notify(errorText(error), true); }
        })); detail.append(row, resultBox);
      }
      if (reviewMode) {
        void addSingleActions(image, epoch); await addGroupActions(image, epoch);
      } else {
        await addPostprocessActions(image, epoch);
        if (!activeDetail(disposed, detailEpoch, epoch, state.selected, imageId)) return;
        addRegenerationAction(image);
      }
    } catch (error) { if (!disposed && epoch === detailEpoch) { detail.replaceChildren(); detail.append(button("← 이미지 목록", backToList, "button mobile-only"), el("p", errorText(error), "error")); } }
  }
  async function registry(kind) {
    const response = await ctx.api.get(`/v1/validation-settings/${kind}`);
    return Array.isArray(response.items) ? response.items.filter((item) => !item.archived) : [];
  }
  function registrySelect(label, items, fieldName) {
    return select(label, items.map((item) => [item[fieldName], `${item[fieldName]} · revision ${item.revision}`]));
  }
  async function addSingleActions(image, expectedEpoch) {
    const section = el("section", "", "panel"); section.append(el("h3", "단일 검사 재요청"));
    try {
      const [profiles, providers] = await Promise.all([registry("single-profiles"), registry("providers")]);
      if (!activeDetail(disposed, detailEpoch, expectedEpoch, state.selected, image.id)) return;
      if (!profiles.length || !providers.length) { section.append(el("p", "활성 단일 Profile과 Provider를 설정에서 등록한 뒤 선택하세요.", "muted")); detail.append(section); return; }
      const [profileWrap, profile] = registrySelect("단일 Profile", profiles, "profile_id");
      const [providerWrap, provider] = registrySelect("Provider", providers, "provider_id");
      const submit = button("검사 접수", async () => {
        const body = {provider_id: provider.value, profile_id: profile.value};
        try {
          const run = await mutate(submit, `single:${image.id}`, body,
            (requestKey) => ctx.api.post(`/v1/images/${image.id}/validations`, body, requestKey));
          ctx.notify(`검사 Run ${run.id} (${run.state})`); await refresh(); showDetail(image.id);
        } catch (error) { ctx.notify(errorText(error), true); }
      });
      section.append(profileWrap, providerWrap, submit);
    } catch (error) { if (activeDetail(disposed, detailEpoch, expectedEpoch, state.selected, image.id)) section.append(el("p", errorText(error), "error")); }
    if (activeDetail(disposed, detailEpoch, expectedEpoch, state.selected, image.id)) detail.append(section);
  }
  function addRegenerationAction(image) {
    const section = el("section", "", "panel"); section.append(el("h3", "수동 재생성"), el("p", "기본 입력을 그대로 사용해 새 Task를 요청합니다.", "muted"));
    const submit = button("수동 재생성", async () => {
      const body = {};
      try { const task = await mutate(submit, `manual:${image.task_id}`, body, (requestKey) => ctx.api.post(`/v1/tasks/${image.task_id}/regenerations`, body, requestKey)); ctx.notify(`새 Task ${task.id}`); ctx.navigate("jobs", task.id); } catch (error) { ctx.notify(errorText(error), true); }
    }); section.append(submit); detail.append(section);
  }
  async function addPostprocessActions(image, expectedEpoch) {
    const section = el("section", "", "panel"); section.append(el("h3", "독립 후처리"), el("p", "원본과 그룹 판정·기준은 바꾸지 않고, 파생 결과를 별도 작업으로 만듭니다.", "muted"));
    const draft = state.postprocessDrafts ??= {};
    const value = draft[image.id] ??= {preset: "", upscaleEnabled: false, upscaleModel: "4x-UltraSharp.safetensors", upscaleScale: "1.5", encodeEnabled: false, webpEnabled: true, webpQuality: "90", advanced: ""};
    try {
      const presets = await ctx.api.get("/v1/presets/postprocess?archived=false");
      if (!activeDetail(disposed, detailEpoch, expectedEpoch, state.selected, image.id)) return;
      const options = [["", "직접 설정"]].concat((presets.items || []).map((preset) => [`${preset.id}@${preset.revision}`, `${preset.name} · r${preset.revision}`]));
      const [presetWrap, preset] = select("저장 후처리 Preset", options); preset.value = value.preset;
      preset.addEventListener("change", () => { value.preset = preset.value; renderPostprocessControls(); });
      const controls = el("div", "", "grid");
      const renderPostprocessControls = () => {
        controls.replaceChildren();
        if (value.preset) { controls.append(el("p", "선택한 저장 Preset revision을 그대로 고정해 접수합니다.", "muted")); return; }
        const [upscaleWrap, upscale] = field("Upscale 사용", "", "checkbox"); upscale.checked = value.upscaleEnabled;
        upscale.addEventListener("change", () => { value.upscaleEnabled = upscale.checked; renderPostprocessControls(); }); controls.append(upscaleWrap);
        if (value.upscaleEnabled) {
          const [modelWrap, model] = field("Upscale 모델", value.upscaleModel); model.addEventListener("input", () => { value.upscaleModel = model.value; });
          const [scaleWrap, scale] = field("최종 배율", value.upscaleScale, "number"); scale.min = "0.01"; scale.step = "0.1"; scale.addEventListener("input", () => { value.upscaleScale = scale.value; }); controls.append(modelWrap, scaleWrap);
        }
        const [encodeWrap, encode] = field("WebP Encode 사용", "", "checkbox"); encode.checked = value.encodeEnabled;
        encode.addEventListener("change", () => { value.encodeEnabled = encode.checked; renderPostprocessControls(); }); controls.append(encodeWrap);
        if (value.encodeEnabled) {
          const [webpWrap, webp] = field("WebP 출력", "", "checkbox"); webp.checked = value.webpEnabled; webp.addEventListener("change", () => { value.webpEnabled = webp.checked; });
          const [qualityWrap, quality] = field("WebP 품질", value.webpQuality, "number"); quality.min = "1"; quality.max = "100"; quality.step = "1"; quality.addEventListener("input", () => { value.webpQuality = quality.value; }); controls.append(webpWrap, qualityWrap);
        }
        const advanced = document.createElement("details"); advanced.append(el("summary", "고급 stage JSON"), el("p", "고급 JSON에 값이 있으면 위 일반 설정 대신 그 JSON으로 접수합니다. 비우면 일반 설정으로 돌아갑니다.", "muted"));
        const json = document.createElement("textarea"); json.value = value.advanced; json.placeholder = '{"detailer": {...}, "alpha": {...}}'; json.setAttribute("aria-label", "독립 후처리 고급 JSON"); json.addEventListener("input", () => { value.advanced = json.value; });
        advanced.append(json, button("고급 JSON 사용", () => { try { value.advanced = json.value; postprocessRequest(value); renderPostprocessControls(); ctx.notify("고급 JSON을 사용할 수 있습니다."); } catch (error) { ctx.notify(errorText(error), true); } }));
        if (value.advanced) advanced.append(button("고급 JSON 지우고 일반 설정으로", () => { value.advanced = ""; renderPostprocessControls(); }));
        controls.append(advanced);
      };
      renderPostprocessControls();
      const submit = button("독립 후처리 접수", async () => {
        try {
          const body = postprocessRequest(value);
          const scope = `postprocess:${image.id}`, fingerprint = `${scope}:${JSON.stringify(body)}`;
          const job = await mutate(submit, scope, body, (requestKey) => ctx.api.post(`/v1/images/${image.id}/postprocess-jobs`, body, requestKey));
          delete state.mutationKeys[fingerprint];
          ctx.notify(`후처리 작업 ${job.id} (${job.state})`); await loadPostprocessJobs();
        } catch (error) { ctx.notify(errorText(error), true); }
      });
      section.append(presetWrap, controls, submit);
      const history = el("section", "", "panel"); history.append(el("h3", "파생 후처리 작업"));
      const rows = el("div", "", "grid");
      const historyUrls = new Set(); let historyEpoch = 0;
      const revokeHistoryUrls = () => { for (const url of historyUrls) { URL.revokeObjectURL(url); detailUrls.delete(url); } historyUrls.clear(); };
      state.postprocessHistoryOffsets ??= {}; state.postprocessHistoryOffsets[image.id] ??= 0;
      const loadPostprocessJobs = async () => {
        const historyVersion = ++historyEpoch; revokeHistoryUrls();
        rows.replaceChildren(el("p", "불러오는 중…", "muted"));
        try {
          const offset = state.postprocessHistoryOffsets[image.id];
          const page = await ctx.api.get(`/v1/postprocess-jobs?${new URLSearchParams({source_image_id: image.id, limit: "20", offset: String(offset)})}`);
          if (!activeDetail(disposed, detailEpoch, expectedEpoch, state.selected, image.id) || historyVersion !== historyEpoch) return;
          rows.replaceChildren();
          for (const job of page.items || []) {
            const row = el("div", "", "panel"); row.append(el("p", `${job.state} · ${job.id}`), el("pre", JSON.stringify(job.postprocess || job.requested_postprocess || {}, null, 2)));
            if (job.error) row.append(el("p", `${job.error.code || "POSTPROCESS_ERROR"}: ${job.error.message || "후처리 오류"}`, "error"));
            for (const output of job.images || []) {
              const imageNode = document.createElement("img"); imageNode.alt = `파생 이미지 ${output.image_id}`; imageNode.style.maxHeight = "240px"; imageNode.style.maxWidth = "100%";
              ctx.api.imageBlob(output.content_url).then((blob) => { const url = URL.createObjectURL(blob); if (!activeDetail(disposed, detailEpoch, expectedEpoch, state.selected, image.id) || historyVersion !== historyEpoch) { URL.revokeObjectURL(url); return; } detailUrls.add(url); historyUrls.add(url); imageNode.src = url; }).catch(() => { if (historyVersion === historyEpoch) imageNode.alt = "파생 이미지를 불러올 수 없음"; });
              row.append(el("p", `${output.media_type} · ${output.bytes} bytes`, "muted"), imageNode);
            }
            row.append(button("작업 현황 보기", () => ctx.navigate("jobs", `postprocess:${job.id}`)));
            rows.append(row);
          }
          if (!rows.childNodes.length) rows.append(el("p", "이 이미지의 독립 후처리 기록이 없습니다.", "muted"));
          const pager = el("div", "", "toolbar"), previous = button("이전", () => { state.postprocessHistoryOffsets[image.id] = Math.max(0, offset - page.limit); loadPostprocessJobs(); }), next = button("다음", () => { state.postprocessHistoryOffsets[image.id] = offset + page.limit; loadPostprocessJobs(); });
          previous.disabled = offset === 0; next.disabled = offset + page.limit >= page.total; pager.append(previous, next);
          rows.append(pager);
        } catch (error) { if (activeDetail(disposed, detailEpoch, expectedEpoch, state.selected, image.id) && historyVersion === historyEpoch) rows.replaceChildren(el("p", errorText(error), "error")); }
      };
      history.append(button("후처리 기록 새로고침", loadPostprocessJobs), rows); section.append(history); detail.append(section); await loadPostprocessJobs();
    } catch (error) { if (activeDetail(disposed, detailEpoch, expectedEpoch, state.selected, image.id)) section.append(el("p", errorText(error), "error")); }
    if (activeDetail(disposed, detailEpoch, expectedEpoch, state.selected, image.id) && !section.parentNode) detail.append(section);
  }
  async function addGroupActions(image, expectedEpoch) {
    const section = el("section", "", "panel"); section.append(el("h3", "현재 그룹 검토"));
    try {
      const [consistency, groupProfiles, singleProfiles, providers] = await Promise.all([
        ctx.api.get(`/v1/groups/${image.group_id}/consistency`), registry("group-profiles"), registry("single-profiles"), registry("providers")]);
      if (!activeDetail(disposed, detailEpoch, expectedEpoch, state.selected, image.id)) return;
      section.append(el("p", `상태: ${consistency.state}`), el("p", `기준 revision: ${consistency.reference?.revision ?? "없음"}`));
      const eligible = eligibleIds(consistency);
      if (!eligible.length) { section.append(el("p", "현재 단일 검증을 통과한 적격 이미지가 없습니다.", "muted")); detail.append(section); return; }
      const [representativeWrap, representative] = select("대표 기준 이미지", eligible.map((id) => [id, id]));
      representative.value = consistency.reference?.representative_id || eligible[0];
      const auxiliaryWrap = el("fieldset", "", "field"); auxiliaryWrap.append(el("legend", "보조 기준 이미지 (최대 2장)"));
      const targetWrap = el("fieldset", "", "field"); targetWrap.append(el("legend", "묶음 재검증 대상 (현재 적격 이미지)"));
      const auxiliaries = () => [...auxiliaryWrap.querySelectorAll("input:checked")].map((input) => input.value);
      const renderAuxiliaries = () => {
        auxiliaryWrap.replaceChildren(el("legend", "보조 기준 이미지 (최대 2장)"));
        for (const id of eligible.filter((id) => id !== representative.value)) {
          const label = el("label", "", "row"); const input = document.createElement("input"); input.type = "checkbox"; input.value = id;
          input.checked = (consistency.reference?.auxiliary_ids || []).includes(id);
          input.addEventListener("change", () => { if (auxiliaries().length > 2) { input.checked = false; ctx.notify("보조 기준 이미지는 최대 2장입니다.", true); } renderTargets(); });
          label.append(input, el("span", id)); auxiliaryWrap.append(label);
        }
      };
      const renderTargets = () => {
        const refs = new Set([representative.value, ...auxiliaries()]);
        const current = Array.isArray(consistency.target_ids) ? new Set(consistency.target_ids) : new Set(eligible);
        targetWrap.replaceChildren(el("legend", "묶음 재검증 대상 (현재 적격 이미지)"));
        for (const id of eligible.filter((id) => current.has(id) && !refs.has(id))) {
          const label = el("label", "", "row"); const input = document.createElement("input"); input.type = "checkbox"; input.value = id;
          input.checked = id === image.id; label.append(input, el("span", id)); targetWrap.append(label);
        }
        if (targetWrap.querySelectorAll("input").length === 0) targetWrap.append(el("span", "현재 기준과 분리된 재검증 대상이 없습니다.", "muted"));
      };
      representative.addEventListener("change", () => { renderAuxiliaries(); renderTargets(); }); renderAuxiliaries(); renderTargets();
      const candidateInfo = el("p", "후보를 읽어도 기준은 바뀌지 않습니다.", "muted");
      const candidates = button("기준 후보 보기", async () => {
        try { const candidate = await ctx.api.get(`/v1/groups/${image.group_id}/reference-candidate`); if (activeDetail(disposed, detailEpoch, expectedEpoch, state.selected, image.id)) candidateInfo.textContent = `${candidate.state}: ${candidate.reason || ""}`; }
        catch (error) { if (activeDetail(disposed, detailEpoch, expectedEpoch, state.selected, image.id)) ctx.notify(errorText(error), true); }
      });
      const saveReference = button("선택한 기준 저장", async () => {
        try {
          const body = referenceRequest(consistency.reference?.revision ?? 0, representative.value, auxiliaries());
          const saved = await mutate(saveReference, `reference:${image.group_id}`, body,
            () => ctx.api.put(`/v1/groups/${image.group_id}/reference`, body));
          ctx.notify(`기준 revision ${saved.reference?.revision ?? saved.revision}`); showDetail(image.id);
        } catch (error) { ctx.notify(errorText(error), true); }
      });
      section.append(candidates, candidateInfo, representativeWrap, auxiliaryWrap, saveReference);

      const replacementPanel = el("section", "", "panel"); replacementPanel.append(el("h3", "교체 재생성 진행"), el("p", "이 상태는 replacement 작업 단계이며 묶음 통과 판정이 아닙니다.", "muted"));
      const replacementRows = el("div", "", "rows");
      const loadReplacements = async () => {
        replacementRows.replaceChildren(el("p", "불러오는 중…", "muted"));
        try {
          const response = await ctx.api.get(`/v1/groups/${image.group_id}/replacements`);
          if (!activeDetail(disposed, detailEpoch, expectedEpoch, state.selected, image.id)) return;
          replacementRows.replaceChildren();
          for (const replacement of response.items || []) {
            const text = [replacement.id, `상태: ${replacement.state}`, replacement.source_image_id && `원본: ${replacement.source_image_id}`,
              replacement.replacement_task_id && `Task: ${replacement.replacement_task_id}`, replacement.replacement_image_id && `결과 이미지: ${replacement.replacement_image_id}`,
              replacement.group_run_id && `묶음 Run: ${replacement.group_run_id}`]
              .filter(Boolean).join(" · ");
            const row = el("div", text, "row");
            if (replacement.replacement_task_id) row.append(button("작업 보기", () => ctx.navigate("jobs", replacement.replacement_task_id)));
            if (replacement.replacement_image_id) row.append(button("결과 이미지 보기", () => showDetail(replacement.replacement_image_id)));
            if (replacement.error?.code) row.append(el("span", `${replacement.error.code}: ${replacement.error.message || ""}`, "error"));
            replacementRows.append(row);
          }
          if (!replacementRows.childNodes.length) replacementRows.append(el("p", "교체 재생성 기록이 없습니다.", "muted"));
        } catch (error) { if (activeDetail(disposed, detailEpoch, expectedEpoch, state.selected, image.id)) replacementRows.replaceChildren(el("p", errorText(error), "error")); }
      };
      const refreshReplacements = button("교체 진행 새로고침", loadReplacements);
      replacementPanel.append(refreshReplacements, replacementRows); section.append(replacementPanel); await loadReplacements();

      if (!groupProfiles.length || !providers.length) section.append(el("p", "묶음 Profile과 Provider를 설정에서 등록한 뒤 선택하세요.", "muted"));
      else if (!consistency.reference) section.append(el("p", "먼저 기준을 저장하고 새 revision을 확인한 뒤 묶음 검증을 접수하세요.", "muted"));
      else {
        const [groupProfileWrap, groupProfile] = registrySelect("묶음 Profile", groupProfiles, "profile_id");
        const [groupProviderWrap, groupProvider] = registrySelect("묶음 Provider", providers, "provider_id");
        const groupSubmit = button("선택 대상 묶음 재검증", async () => {
          const targetIds = [...targetWrap.querySelectorAll("input:checked")].map((input) => input.value);
          const body = groupValidationRequest(consistency, targetIds,
            {profile_id: groupProfile.value, provider_id: groupProvider.value});
          try {
            const run = await mutate(groupSubmit, `group-validation:${image.group_id}`, body,
              (requestKey) => ctx.api.post(`/v1/groups/${image.group_id}/validations`, body, requestKey));
            ctx.notify(`묶음 Run ${run.id} (${run.state})`); showDetail(image.id);
          } catch (error) { ctx.notify(errorText(error), true); }
        });
        section.append(groupProfileWrap, groupProviderWrap, targetWrap, groupSubmit);

        const [singleProfileWrap, singleProfile] = registrySelect("교체용 단일 Profile", singleProfiles, "profile_id");
        const [singleProviderWrap, singleProvider] = registrySelect("교체용 단일 Provider", providers, "provider_id");
        const currentTargets = Array.isArray(consistency.target_ids) ? consistency.target_ids : [];
        const [replacementTargetWrap, replacementTarget] = select("교체할 현재 대상", currentTargets.map((id) => [id, id]));
        const replacementSubmit = button("선택 이미지 교체 재생성", async () => {
          const body = replacementRequest(consistency, replacementTarget.value,
            {validation: {profile_id: singleProfile.value, provider_id: singleProvider.value}},
            {profile_id: groupProfile.value, provider_id: groupProvider.value});
          try {
            const replacement = await mutate(replacementSubmit, `replacement:${image.group_id}`, body,
              (requestKey) => ctx.api.post(`/v1/groups/${image.group_id}/replacements`, body, requestKey));
            ctx.notify(`교체 작업 ${replacement.id} (${replacement.state})`); await loadReplacements();
          } catch (error) { ctx.notify(errorText(error), true); }
        });
        if (!singleProfiles.length || !replacementTarget.options.length) section.append(el("p", "교체할 현재 적격 대상과 단일 Profile이 필요합니다.", "muted"));
        else section.append(el("h3", "선택 이미지 교체"), replacementTargetWrap, singleProfileWrap, singleProviderWrap, replacementSubmit);

        const advanced = document.createElement("details"); advanced.append(el("summary", "고급 JSON 요청"));
        const advancedBody = document.createElement("textarea"); advancedBody.setAttribute("aria-label", "묶음 검증 고급 JSON"); advancedBody.value = JSON.stringify({reference_revision: consistency.reference.revision, target_ids: [], validation: {profile_id: groupProfile.value, provider_id: groupProvider.value}}, null, 2);
        const advancedSubmit = button("고급 묶음 검증 접수", async () => {
          try { const body = JSON.parse(advancedBody.value); const run = await mutate(advancedSubmit, `group-validation:${image.group_id}`, body, (requestKey) => ctx.api.post(`/v1/groups/${image.group_id}/validations`, body, requestKey)); ctx.notify(`묶음 Run ${run.id} (${run.state})`); showDetail(image.id); }
          catch (error) { ctx.notify(errorText(error), true); }
        });
        advanced.append(advancedBody, advancedSubmit); section.append(advanced);
        const advancedReplacement = document.createElement("details"); advancedReplacement.append(el("summary", "고급 교체 재생성 JSON"));
        const replacementJson = document.createElement("textarea"); replacementJson.setAttribute("aria-label", "교체 재생성 고급 JSON"); replacementJson.value = JSON.stringify({reference_revision: consistency.reference.revision, target_image_id: replacementTarget.value, regeneration: {validation: {profile_id: singleProfile.value, provider_id: singleProvider.value}}, group_validation: {profile_id: groupProfile.value, provider_id: groupProvider.value}}, null, 2);
        const replacementJsonSubmit = button("고급 교체 재생성 접수", async () => {
          try { const body = JSON.parse(replacementJson.value); const replacement = await mutate(replacementJsonSubmit, `replacement:${image.group_id}`, body, (requestKey) => ctx.api.post(`/v1/groups/${image.group_id}/replacements`, body, requestKey)); ctx.notify(`교체 작업 ${replacement.id} (${replacement.state})`); await loadReplacements(); }
          catch (error) { ctx.notify(errorText(error), true); }
        });
        advancedReplacement.append(replacementJson, replacementJsonSubmit); section.append(advancedReplacement);
      }
    } catch (error) { if (activeDetail(disposed, detailEpoch, expectedEpoch, state.selected, image.id)) section.append(el("p", errorText(error), "error")); }
    if (activeDetail(disposed, detailEpoch, expectedEpoch, state.selected, image.id)) detail.append(section);
  }
  await loadWorks(); await refresh(); if (state.selected) showDetail(state.selected);
  return () => { disposed = true; imageQueue = []; observeImages?.disconnect(); revoke(cardUrls); revoke(detailUrls); };
}
