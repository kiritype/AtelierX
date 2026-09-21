const el = (tag, text = "", className = "") => {
  const value = document.createElement(tag);
  value.textContent = text;
  if (className) value.className = className;
  return value;
};
const button = (text, action, disabled = false) => {
  const value = el("button", text, "button"); value.type = "button"; value.disabled = disabled; value.addEventListener("click", action); return value;
};
const errorText = (error) => error?.message || "요청을 완료하지 못했습니다.";
const key = () => globalThis.crypto?.randomUUID?.() || `jobs-${Date.now()}-${Math.random().toString(36).slice(2)}`;
const items = (value) => Array.isArray(value?.items) ? value.items : [];
export const jobLabel = (state) => ({queued:"대기",pending:"대기",running:"실행 중",completed:"실행 완료",failed:"실패",cancelled:"취소됨",cancelling:"취소 중",generated:"생성 완료",generation_pending:"생성 중",single_validation_pending:"단일 검사 중",group_validation_pending:"그룹 검사 중",single_failed:"단일 불합격",generation_failed:"생성 실패",passed:"통과",error:"실행 오류",incomplete:"판정 미완료",awaiting_reference_confirmation:"기준 확인 필요",insufficient_images:"비교 이미지 부족",draft:"준비됨"}[state] || state || "대기");
let controlSequence = 0;

export function presetReference(value) {
  const [id, revision] = String(value).split("@");
  if (!id || !Number.isInteger(Number(revision)) || Number(revision) < 1) throw new Error("Preset을 선택하세요.");
  return { id, revision: Number(revision) };
}

export function buildBatchRequest(draft) {
  if (!draft.groupId) throw new Error("Group을 선택하세요.");
  if (!draft.singleProfile || !draft.singleProvider || !draft.groupProfile || !draft.groupProvider) {
    throw new Error("각 행의 Single 검사와 Batch의 Group 검사를 모두 선택하세요.");
  }
  const generation = presetReference(draft.generationPreset);
  const postprocess = draft.postprocessPreset ? presetReference(draft.postprocessPreset) : null;
  if (!Array.isArray(draft.rows) || draft.rows.length < 1 || draft.rows.length > 32) throw new Error("1~32개 행을 준비하세요.");
  const batchItems = draft.rows.map((row) => {
    if (row.framing !== "upper_body" && row.framing !== "full_body") throw new Error("구도를 확인하세요.");
    const result = { framing: row.framing, presets: { generation, ...(postprocess ? { postprocess } : {}) }, validation: { profile_id: draft.singleProfile, provider_id: draft.singleProvider } };
    for (const name of ["expression", "action", "situation"]) if (String(row[name] || "").trim()) result[name] = String(row[name]).trim();
    return result;
  });
  return { items: batchItems, group_validation: { profile_id: draft.groupProfile, provider_id: draft.groupProvider } };
}

export function batchFingerprint(body) { return JSON.stringify(body); }

export function groupRunDisplay(run) {
  const result = run?.result && typeof run.result === "object" ? run.result : {};
  const rawTargets = Array.isArray(result.items) ? result.items : [];
  return {
    state: run?.state || "unknown",
    outcome: run?.outcome ?? "pending",
    summary: result.summary ?? null,
    error: run?.error ?? null,
    partialResults: Array.isArray(run?.partial_results) ? run.partial_results : [],
    targets: rawTargets.map((target) => ({
      id: target.target_id || target.image_ref || target.ref || target.id || "unknown",
      status: target.status || target.outcome || "unknown",
      evidence: target.evidence ?? target.assessment ?? null,
    })),
  };
}

export function postprocessJobDisplay(job) {
  return {id: job?.id || "unknown", state: job?.state || "unknown", sourceImageId: job?.source_image_id || null,
    cancelRequested: Boolean(job?.cancel_requested), images: Array.isArray(job?.images) ? job.images : [], error: job?.error || null};
}

export function postprocessListFallback(error) { return error?.status === 404; }

function initialBatchDraft() {
  return { groupId: "", generationPreset: "", postprocessPreset: "", singleProfile: "", singleProvider: "", groupProfile: "", groupProvider: "",
    rows: [{ framing: "upper_body", expression: "", action: "", situation: "" }], previews: null, previewFingerprint: null, submitting: false, requestKey: null };
}

function select(value, entries, onChange, empty = "선택") {
  const result = document.createElement("select");
  const first = el("option", empty); first.value = ""; first.selected = !value; result.append(first);
  for (const entry of entries) {
    const option = el("option", `${entry.name || entry.id || entry.profile_id || entry.provider_id}${entry.revision ? ` (r${entry.revision})` : ""}`);
    option.value = entry.id || entry.profile_id || entry.provider_id;
    option.selected = option.value === value;
    result.append(option);
  }
  result.addEventListener("change", (event) => onChange(event.target.value));
  return result;
}
function field(labelText, control) {
  const label = document.createElement("label"); label.className = "field";
  control.id ||= `jobs-control-${++controlSequence}`; label.htmlFor = control.id;
  label.append(el("span", labelText), control); return label;
}
function invalidate(draft) { draft.previews = null; draft.previewFingerprint = null; }
function groupOptions(groups) { return groups.map((group) => ({ id: group.id, name: `r${group.outfit_revision} · ${group.id.slice(0, 8)}` })); }

function renderBatchForm(host, state, ctx, refresh) {
  const draft = state.batchDraft;
  host.replaceChildren();
  const panel = el("section", "", "panel");
  panel.append(el("h2", "일괄 생성 접수"), el("p", "행마다 Single 검사를 고정하고, 모든 행의 Core preview hash를 확인한 뒤 한 Batch로 접수합니다. 후처리 Preset을 고르지 않으면 기본 1024 → 1536 설정을 사용합니다.", "muted"));
  const form = el("div", "", "grid");
  form.append(field("Group", select(draft.groupId, groupOptions(state.form.groups), (value) => { draft.groupId = value; invalidate(draft); }, "Group 선택")));
  const presets = state.form.generation.map((entry) => ({ id: `${entry.id}@${entry.revision}`, name: entry.name, revision: entry.revision }));
  const postprocess = state.form.postprocess.map((entry) => ({ id: `${entry.id}@${entry.revision}`, name: entry.name, revision: entry.revision }));
  form.append(field("Generation preset", select(draft.generationPreset, presets, (value) => { draft.generationPreset = value; invalidate(draft); }, "Generation preset 선택")));
  form.append(field("Postprocess preset", select(draft.postprocessPreset, postprocess, (value) => { draft.postprocessPreset = value; invalidate(draft); }, "기본 후처리 사용")));
  form.append(field("Single Profile", select(draft.singleProfile, state.form.singleProfiles, (value) => { draft.singleProfile = value; invalidate(draft); }, "Single Profile 선택")));
  form.append(field("Single Provider", select(draft.singleProvider, state.form.providers, (value) => { draft.singleProvider = value; invalidate(draft); }, "Single Provider 선택")));
  form.append(field("Group Profile", select(draft.groupProfile, state.form.groupProfiles, (value) => { draft.groupProfile = value; invalidate(draft); }, "Group Profile 선택")));
  form.append(field("Group Provider", select(draft.groupProvider, state.form.providers, (value) => { draft.groupProvider = value; invalidate(draft); }, "Group Provider 선택")));
  panel.append(form, el("h3", "생성 행"));
  draft.rows.forEach((row, index) => {
    const line = el("fieldset"); line.append(el("legend", `행 ${index + 1}`));
    const controls = el("div", "", "grid");
    const framing = document.createElement("select");
    for (const [value, label] of [["upper_body", "상반신"], ["full_body", "전신"]]) { const option = el("option", label); option.value = value; option.selected = row.framing === value; framing.append(option); }
    framing.addEventListener("change", (event) => { row.framing = event.target.value; invalidate(draft); }); controls.append(field("구도", framing));
    for (const [name, label] of [["expression", "표정"], ["action", "자세·동작"], ["situation", "상황"]]) {
      const input = document.createElement("input"); input.value = row[name] || ""; input.addEventListener("input", (event) => { row[name] = event.target.value; invalidate(draft); }); controls.append(field(label, input));
    }
    line.append(controls, button("행 제거", () => { if (draft.rows.length > 1) { draft.rows.splice(index, 1); invalidate(draft); renderBatchForm(host, state, ctx, refresh); } }, draft.rows.length === 1));
    panel.append(line);
  });
  if (draft.previews) {
    const previews = el("details"); previews.open = true; previews.append(el("summary", "행별 Core 미리보기"));
    draft.previews.forEach((preview, index) => {
      const snapshot = preview?.snapshot || {}, generation = snapshot.generation_inputs || {};
      const item = el("section", "", "panel"); item.append(el("h3", `행 ${index + 1}`),
        el("p", `Positive: ${generation.positive_prompt || ""}`), el("p", `Negative: ${generation.negative_prompt || ""}`));
      const inclusion = document.createElement("pre"); inclusion.textContent = JSON.stringify(snapshot.inclusion || {}, null, 2);
      const postprocess = document.createElement("pre"); postprocess.textContent = JSON.stringify(snapshot.postprocess ?? "기본 후처리", null, 2);
      item.append(el("p", "포함/제외 사유", "muted"), inclusion, el("p", "후처리", "muted"), postprocess); previews.append(item);
    });
    panel.append(previews);
  }
  const preview = async () => {
    try {
      const body = buildBatchRequest(draft);
      const responses = await Promise.all(body.items.map((item) => ctx.api.post("/v1/prompts/preview", { ...item, group_id: draft.groupId })));
      draft.previews = responses; draft.previewFingerprint = batchFingerprint(body);
      ctx.notify(`${responses.length}개 행의 Core preview를 확인했습니다.`); renderBatchForm(host, state, ctx, refresh);
    } catch (error) { ctx.notify(errorText(error), true); }
  };
  const submit = async () => {
    try {
      const body = buildBatchRequest(draft);
      if (!draft.previews || draft.previewFingerprint !== batchFingerprint(body)) throw new Error("모든 행을 최신 Core preview로 확인하세요.");
      const withHashes = { ...body, items: body.items.map((item, index) => ({ ...item, preview_hash: draft.previews[index].preview_hash })) };
      draft.submitting = true; draft.requestKey ||= key(); renderBatchForm(host, state, ctx, refresh);
      const batch = await ctx.api.post(`/v1/groups/${draft.groupId}/batches`, withHashes, draft.requestKey);
      state.selectedBatch = batch.id; state.selectedTask = null; draft.submitting = false; draft.requestKey = null;
      ctx.notify(`일괄 작업 ${batch.id}을 접수했습니다.`); await refresh();
    } catch (error) { draft.submitting = false; ctx.notify(errorText(error), true); renderBatchForm(host, state, ctx, refresh); }
  };
  const toolbar = el("div", "", "toolbar");
  toolbar.append(button("+ 행", () => { if (draft.rows.length < 32) { draft.rows.push({ framing: "upper_body", expression: "", action: "", situation: "" }); invalidate(draft); renderBatchForm(host, state, ctx, refresh); } }),
    button("모든 행 미리보기", preview, draft.submitting), button("명시적으로 Batch 접수", submit, draft.submitting || !draft.previews));
  panel.append(toolbar);
  if (draft.requestKey) panel.append(el("p", `같은 키로 다시 확인할 수 있습니다: ${draft.requestKey}`, "muted"));
  const advanced = el("details"); advanced.append(el("summary", "고급 JSON 요청 보기"));
  const json = document.createElement("pre"); try { json.textContent = JSON.stringify(buildBatchRequest(draft), null, 2); } catch (error) { json.textContent = errorText(error); }
  advanced.append(json); panel.append(advanced); host.append(panel);
}

function referencePanel(detail, state, ctx, batch, group, candidate, refresh, mutate) {
  const current = group.reference || null;
  const draft = state.referenceDrafts[batch.group_id] ||= { revision: current?.revision ?? candidate?.revision ?? 0, representative_id: current?.representative_id ?? candidate?.representative_id ?? "", auxiliary_ids: [...(current?.auxiliary_ids ?? candidate?.auxiliary_ids ?? [])] };
  const panel = el("section", "", "panel");
  panel.append(el("h3", "기준 이미지 확인"), el("p", "기준 후보는 자동 저장되지 않습니다. 저장과 Batch 재개는 각각 명시적으로 실행하세요.", "muted"));
  panel.append(el("p", current ? `현재 기준 r${current.revision}: ${current.representative_id}` : "저장된 기준이 없습니다."), el("p", `후보 상태: ${candidate.state || "알 수 없음"}`));
  const revision = document.createElement("input"); revision.type = "number"; revision.value = draft.revision; revision.addEventListener("input", (event) => { draft.revision = Number(event.target.value); }); panel.append(field("현재 기준 revision", revision));
  const representative = document.createElement("input"); representative.value = draft.representative_id; representative.addEventListener("input", (event) => { draft.representative_id = event.target.value; }); panel.append(field("대표 이미지 ID", representative));
  for (let index = 0; index < 2; index += 1) { const auxiliary = document.createElement("input"); auxiliary.value = draft.auxiliary_ids[index] || ""; auxiliary.addEventListener("input", (event) => { draft.auxiliary_ids[index] = event.target.value; }); panel.append(field(`보조 이미지 ID ${index + 1}`, auxiliary)); }
  panel.append(button("기준 저장", async () => {
    try {
      const saved = await mutate(`reference-save:${batch.group_id}`, () => ctx.api.put(`/v1/groups/${batch.group_id}/reference`, { revision: draft.revision, representative_id: draft.representative_id.trim(), auxiliary_ids: draft.auxiliary_ids.map((id) => id.trim()).filter(Boolean) }));
      if (!saved) return;
      draft.revision = saved.reference.revision; draft.representative_id = saved.reference.representative_id; draft.auxiliary_ids = [...saved.reference.auxiliary_ids];
      ctx.notify(`기준 r${draft.revision}을 저장했습니다. Batch 재개는 아래 버튼으로 별도 확인하세요.`); await refresh();
    } catch (error) { ctx.notify(errorText(error), true); }
  }));
  panel.append(button("현재 기준으로 Batch 재개", async () => {
    try {
      const body = { reference_revision: draft.revision }, fingerprint = `confirm:${batch.id}:${JSON.stringify(body)}`, requestKey = state.mutationKeys[fingerprint] ||= key();
      const confirmed = await mutate(`batch-confirm:${batch.id}`, () => ctx.api.post(`/v1/group-batches/${batch.id}/confirm-reference`, body, requestKey));
      if (!confirmed) return;
      delete state.mutationKeys[fingerprint]; ctx.notify("현재 기준으로 Batch 재개를 요청했습니다."); await refresh();
    } catch (error) { ctx.notify(errorText(error), true); }
  }));
  detail.append(panel);
}

export async function mount(container, ctx) {
  const state = ctx.state;
  state.taskState ||= ""; state.batchState ||= ""; state.postprocessState ||= ""; state.selectedTask ||= null; state.selectedBatch ||= null; state.selectedPostprocess ||= null; state.mutationKeys ||= {}; state.referenceDrafts ||= {}; state.form ||= { groups: [], generation: [], postprocess: [], singleProfiles: [], groupProfiles: [], providers: [] }; state.batchDraft ||= initialBatchDraft();
  if (state.selectedId) { if (String(state.selectedId).startsWith("postprocess:")) { state.selectedPostprocess = String(state.selectedId).slice("postprocess:".length); state.selectedTask = null; state.selectedBatch = null; } else { state.selectedTask = state.selectedId; state.selectedPostprocess = null; state.selectedBatch = null; } state.selectedId = null; }
  let disposed = false, timer = null, inFlight = false, delay = 5000, detailVersion = 0;
  const postprocessUrls = new Set(); const revokePostprocessUrls = () => { for (const url of postprocessUrls) URL.revokeObjectURL(url); postprocessUrls.clear(); };
  state.pendingMutations ||= {};
  const root = el("section", "", "panel"), toolbar = el("div", "", "toolbar"), message = el("p", "", "error"), batchHost = el("div"), lists = el("div", "", "jobs-lists"), tasks = el("section", "", "panel"), batches = el("section", "", "panel"), postprocessJobs = el("section", "", "panel"), detail = el("section", "작업을 선택하세요.", "panel");
  const taskState = document.createElement("input"); taskState.placeholder = "Task 상태 filter"; taskState.setAttribute("aria-label", "Task 상태 필터"); taskState.value = state.taskState;
  const plansHost = el("section", "", "panel");
  state.planOffset ||= 0;
  const batchState = document.createElement("input"); batchState.placeholder = "Batch 상태 filter"; batchState.setAttribute("aria-label", "일괄 작업 상태 필터"); batchState.value = state.batchState;
  const postprocessState = document.createElement("input"); postprocessState.placeholder = "후처리 상태 filter"; postprocessState.setAttribute("aria-label", "후처리 작업 상태 필터"); postprocessState.value = state.postprocessState;
  const legacyForm = el("details");
  legacyForm.append(el("summary", "기존 일괄 생성 양식 (호환용)"), batchHost);
  toolbar.append(taskState, batchState, postprocessState, button("새로고침", () => refresh()), button("조각으로 제작하기", () => ctx.navigate("production")));
  lists.append(tasks, batches, postprocessJobs); root.append(toolbar, message, legacyForm, lists, detail); container.replaceChildren(root);
  root.insertBefore(plansHost, lists);
  const path = (base, value) => value ? `${base}?${new URLSearchParams({ state: value, limit: "30", offset: "0" })}` : `${base}?limit=30&offset=0`;
  async function mutate(scope, action) {
    if (state.pendingMutations[scope]) return null;
    state.pendingMutations[scope] = true;
    try { return await action(); }
    finally { delete state.pendingMutations[scope]; }
  }
  async function loadFormOptions() {
    const [groupPage, generation, postprocess, singleProfiles, groupProfiles, providers] = await Promise.all([
      ctx.api.get("/v1/groups?limit=200&offset=0"), ctx.api.get("/v1/presets/generation?archived=false"), ctx.api.get("/v1/presets/postprocess?archived=false"),
      ctx.api.get("/v1/validation-settings/single-profiles"), ctx.api.get("/v1/validation-settings/group-profiles"), ctx.api.get("/v1/validation-settings/providers"),
    ]);
    state.form = { groups: items(groupPage), generation: items(generation), postprocess: items(postprocess), singleProfiles: items(singleProfiles), groupProfiles: items(groupProfiles), providers: items(providers) };
  }
  function renderTasks(page) {
    tasks.replaceChildren(el("h2", "개별 생성")); if (!items(page).length) tasks.append(el("p", "작업이 없습니다.", "muted"));
    for (const task of items(page)) { const row = el("div", "", "row"); row.append(el("span", `${jobLabel(task.state)} · ${task.id.slice(0,8)}`, "badge"), button("상세", () => { state.selectedTask = task.id; state.selectedBatch = null; state.selectedPostprocess = null; showTask(task.id); })); tasks.append(row); }
  }
  function renderPlans(page) {
    plansHost.replaceChildren(el("h2", "조각 기반 제작 계획"));
    plansHost.append(el("p", `전체 ${page.total}개 계획 · 각 계획의 총 대기 수와 실제 실행 수는 구분됩니다.`, "muted"));
    for (const plan of items(page)) {
      const row = el("div", "", "row");
      row.append(el("span", `${plan.total}장 · ${jobLabel(plan.state)} · 판정: ${jobLabel(plan.outcome)}`),
        button("제작 계획 열기", () => ctx.navigate("production", `plan:${plan.id}`)));
      plansHost.append(row, el("p", Object.entries(plan.counts || {}).map(([status, count]) => `${jobLabel(status)}: ${count}`).join(" · "), "muted"));
    }
    const pager = el("div", "", "row");
    pager.append(button("계획 이전", () => { state.planOffset = Math.max(0, state.planOffset - 20); refresh(); }, !state.planOffset),
      button("계획 다음", () => { state.planOffset += 20; refresh(); }, state.planOffset + 20 >= page.total));
    plansHost.append(pager);
  }
  function renderBatches(page) {
    batches.replaceChildren(el("h2", "일괄 작업")); if (!items(page).length) batches.append(el("p", "일괄 작업이 없습니다.", "muted"));
    for (const batch of items(page)) { const row = el("div", "", "row"); row.append(el("span", `${batch.state} · ${batch.id}`, "badge"), button("상세", () => { state.selectedBatch = batch.id; state.selectedTask = null; state.selectedPostprocess = null; showBatch(batch.id); })); batches.append(row); }
  }
  function renderPostprocessJobs(page) {
    postprocessJobs.replaceChildren(el("h2", "독립 후처리")); if (page?.unavailable) { postprocessJobs.append(el("p", "후처리 기능을 사용하려면 Core 업데이트/재시작이 필요합니다.", "muted")); return; } if (!items(page).length) postprocessJobs.append(el("p", "후처리 작업이 없습니다.", "muted"));
    for (const job of items(page)) { const row = el("div", "", "row"); row.append(el("span", `${job.state} · ${job.id}`, "badge"), el("span", `원본: ${job.source_image_id}`, "muted"), button("상세", () => { state.selectedPostprocess = job.id; state.selectedTask = null; state.selectedBatch = null; showPostprocess(job.id); })); postprocessJobs.append(row); }
  }
  async function showPostprocess(id) {
    const version = ++detailVersion; revokePostprocessUrls(); detail.replaceChildren(el("p", "후처리 상세를 불러오는 중…", "muted"));
    try {
      const job = await ctx.api.get(`/v1/postprocess-jobs/${id}`); if (disposed || version !== detailVersion || state.selectedPostprocess !== id) return;
      const display = postprocessJobDisplay(job); detail.replaceChildren(el("h2", "독립 후처리 상세"), el("p", `상태: ${display.state}${display.cancelRequested ? " · 취소 요청됨" : ""}`), el("p", `원본 이미지: ${display.sourceImageId || "알 수 없음"}`), el("pre", JSON.stringify(job.postprocess || job.requested_postprocess || {}, null, 2)));
      if (display.sourceImageId) detail.append(button("원본 이미지 보기", () => ctx.navigate("gallery", display.sourceImageId)));
      if (display.error) detail.append(el("p", `${display.error.code || "POSTPROCESS_ERROR"}: ${display.error.message || "후처리 오류"}`, "error"));
      for (const image of display.images) { const preview = document.createElement("img"); preview.alt = `파생 이미지 ${image.image_id}`; preview.style.maxHeight = "260px"; preview.style.maxWidth = "100%"; ctx.api.imageBlob(image.content_url).then((blob) => { const url = URL.createObjectURL(blob); if (disposed || version !== detailVersion || state.selectedPostprocess !== id) { URL.revokeObjectURL(url); return; } postprocessUrls.add(url); preview.src = url; }).catch(() => { preview.alt = "파생 이미지를 불러올 수 없음"; }); detail.append(el("p", `${image.image_id} · ${image.media_type} · ${image.bytes} bytes`, "muted"), preview); }
      const terminal = ["completed", "failed", "cancelled"].includes(display.state);
      const cancel = button("후처리 취소", async () => { cancel.disabled = true; try { await mutate(`postprocess-cancel:${id}`, () => ctx.api.post(`/v1/postprocess-jobs/${id}/cancel`)); await refresh(); } catch (error) { ctx.notify(errorText(error), true); cancel.disabled = false; } }, terminal || Boolean(state.pendingMutations[`postprocess-cancel:${id}`]));
      detail.append(cancel);
    } catch (error) { if (!disposed && version === detailVersion && state.selectedPostprocess === id) detail.replaceChildren(el("p", errorText(error), "error")); }
  }
  async function showTask(id) {
    const version = ++detailVersion;
    detail.replaceChildren(el("p", "Task 상세를 불러오는 중…", "muted"));
    try {
      const [task, attempts] = await Promise.all([ctx.api.get(`/v1/tasks/${id}`), ctx.api.get(`/v1/tasks/${id}/attempts?limit=50&offset=0`)]);
      if (disposed || version !== detailVersion || state.selectedTask !== id) return;
      detail.replaceChildren(el("h2", "Task 상세"), el("p", `상태: ${task.state}${task.cancel_requested ? " · 취소 요청됨" : ""}`), el("pre", JSON.stringify(task.snapshot, null, 2)));
      if (task.error) detail.append(el("p", `${task.error.code || "TASK_ERROR"}: ${task.error.message || "작업 실행 오류"}`, "error"));
      if (task.validation) detail.append(el("p", `단일 검증: ${task.validation.state || "미검증"} / ${task.validation.outcome || "결과 없음"}`));
      for (const image of task.images || []) detail.append(button(`갤러리: ${image.id}`, () => ctx.navigate("gallery", image.id)));
      detail.append(button("Task 취소", async () => {
        try { await mutate(`task-cancel:${id}`, () => ctx.api.post(`/v1/tasks/${id}/cancel`)); await refresh(); }
        catch (error) { ctx.notify(errorText(error), true); }
      }, Boolean(state.pendingMutations[`task-cancel:${id}`])));
      detail.append(el("h3", "시도 lineage")); for (const attempt of items(attempts)) detail.append(el("p", `${attempt.regeneration?.kind || "initial"} · ${attempt.state} · ${attempt.id}`));
    } catch (error) { if (!disposed && version === detailVersion && state.selectedTask === id) detail.replaceChildren(el("p", errorText(error), "error")); }
  }
  async function showBatch(id) {
    const version = ++detailVersion;
    detail.replaceChildren(el("p", "일괄 상세를 불러오는 중…", "muted"));
    try {
      const batch = await ctx.api.get(`/v1/group-batches/${id}`); if (disposed || version !== detailVersion || state.selectedBatch !== id) return;
      detail.replaceChildren(el("h2", "일괄 작업 상세"), el("p", `상태: ${batch.state}`), el("pre", JSON.stringify(batch.summary || {}, null, 2)));
      if (batch.error) detail.append(el("p", `${batch.error.code || "BATCH_ERROR"}: ${batch.error.message || "일괄 실행 오류"}`, "error"));
      for (const item of batch.items || []) detail.append(el("p", `${item.state} · ${item.active_task_id || item.task_id || "대기"}`));
      detail.append(button("일괄 취소", async () => {
        try { await mutate(`batch-cancel:${id}`, () => ctx.api.post(`/v1/group-batches/${id}/cancel`)); await refresh(); }
        catch (error) { ctx.notify(errorText(error), true); }
      }, Boolean(state.pendingMutations[`batch-cancel:${id}`])));
      if (batch.group_run_id) {
        try {
          const run = await ctx.api.get(`/v1/group-validation-runs/${batch.group_run_id}`);
          if (disposed || version !== detailVersion || state.selectedBatch !== id) return;
          const display = groupRunDisplay(run), panel = el("section", "", "panel");
          panel.append(el("h3", "묶음 검증 판정"), el("p", `실행 상태: ${display.state} · 판정: ${display.outcome}`),
            el("p", "Batch 완료는 생성·단일 검사 흐름의 종료를 뜻하며, 묶음 검증의 합격을 뜻하지 않습니다.", "muted"));
          if (display.error) panel.append(el("p", `${display.error.code || "GROUP_VALIDATION_ERROR"}: ${display.error.message || "묶음 검증 실행 오류"}`, "error"));
          if (display.partialResults.length) { const partial = document.createElement("pre"); partial.textContent = JSON.stringify(display.partialResults, null, 2); panel.append(el("p", "부분 결과", "muted"), partial); }
          if (display.summary) { const summary = document.createElement("pre"); summary.textContent = JSON.stringify(display.summary, null, 2); panel.append(summary); }
          const advanced = el("details"); advanced.append(el("summary", "대상별 evidence"));
          if (!display.targets.length) advanced.append(el("p", "대상별 결과가 아직 없습니다.", "muted"));
          for (const target of display.targets) { const evidence = document.createElement("pre"); evidence.textContent = JSON.stringify(target.evidence, null, 2); advanced.append(el("p", `${target.id} · ${target.status}`), evidence); }
          panel.append(advanced); detail.append(panel);
        } catch (error) { detail.append(el("p", `묶음 검증 결과를 읽지 못했습니다: ${errorText(error)}`, "error")); }
      }
      if (batch.state === "awaiting_reference_confirmation") {
        const [group, candidate] = await Promise.all([ctx.api.get(`/v1/groups/${batch.group_id}`), ctx.api.get(`/v1/groups/${batch.group_id}/reference-candidate`)]);
        if (!disposed && version === detailVersion && state.selectedBatch === id) referencePanel(detail, state, ctx, batch, group, candidate, refresh, mutate);
      }
    } catch (error) { if (!disposed && version === detailVersion && state.selectedBatch === id) detail.replaceChildren(el("p", errorText(error), "error")); }
  }
  async function refresh() {
    if (disposed || inFlight || document.hidden) return;
    inFlight = true; message.textContent = ""; state.taskState = taskState.value.trim(); state.batchState = batchState.value.trim(); state.postprocessState = postprocessState.value.trim();
    try {
      const postprocessLoad = ctx.api.get(path("/v1/postprocess-jobs", state.postprocessState)).catch((error) => { if (postprocessListFallback(error)) return {unavailable: true, items: []}; throw error; });
      const [taskPage, batchPage, postprocessPage, planPage] = await Promise.all([ctx.api.get(path("/v1/tasks", state.taskState)), ctx.api.get(path("/v1/group-batches", state.batchState)), postprocessLoad, ctx.api.get(`/v1/production-plans?limit=20&offset=${state.planOffset}`)]);
      if (disposed) return; renderTasks(taskPage); renderBatches(batchPage); renderPostprocessJobs(postprocessPage); renderPlans(planPage); if (state.selectedTask) await showTask(state.selectedTask); if (state.selectedBatch) await showBatch(state.selectedBatch); if (state.selectedPostprocess) await showPostprocess(state.selectedPostprocess); delay = 5000;
    } catch (error) { message.textContent = errorText(error); delay = Math.min(delay * 2, 30000); }
    finally { inFlight = false; schedule(); }
  }
  function schedule() { clearTimeout(timer); if (!disposed && !document.hidden) timer = setTimeout(refresh, delay); }
  const visibility = () => { if (document.hidden) clearTimeout(timer); else { delay = 0; refresh(); } };
  document.addEventListener("visibilitychange", visibility);
  try { await loadFormOptions(); renderBatchForm(batchHost, state, ctx, refresh); await refresh(); } catch (error) { message.textContent = errorText(error); }
  return () => { disposed = true; revokePostprocessUrls(); clearTimeout(timer); document.removeEventListener("visibilitychange", visibility); };
}
