import {fragmentListPath, pageOffsetForTotal} from "./fragment-picker.js";

let controlSequence = 0;
const collection = (value) => Array.isArray(value?.items) ? value.items : [];
const errorText = (error) => error?.message || "요청을 완료하지 못했습니다.";
const query = (path, parameters = {}) => {
  const entries = Object.entries(parameters).filter(([, value]) => value !== "" && value !== null && value !== undefined);
  return entries.length ? `${path}?${new URLSearchParams(entries)}` : path;
};
function el(tag, properties = {}, children = []) {
  const result = document.createElement(tag);
  for (const [key, value] of Object.entries(properties)) {
    if (value === null || value === undefined) continue;
    if (key === "text") result.textContent = String(value);
    else if (key === "class") result.className = value;
    else if (key === "checked") result.checked = Boolean(value);
    else if (key === "disabled") result.disabled = Boolean(value);
    else if (key.startsWith("on")) result.addEventListener(key.slice(2).toLowerCase(), value);
    else result.setAttribute(key, String(value));
  }
  for (const child of Array.isArray(children) ? children : [children]) if (child) result.append(child);
  return result;
}
function button(text, action, {secondary = false, disabled = false} = {}) {
  return el("button", {type: "button", class: secondary ? "button secondary" : "button", disabled, onclick: action, text});
}
function field(labelText, control, hint = "") {
  const id = control.id || `fragment-control-${++controlSequence}`;
  control.id = id;
  return el("label", {class: "field", for: id}, [el("span", {text: labelText}), control, hint ? el("small", {class: "muted", text: hint}) : null]);
}
function input(value, oninput, attrs = {}) { return el("input", {type: "text", value: value ?? "", oninput: (event) => oninput(event.target.value), ...attrs}); }
function textarea(value, oninput) { const control = el("textarea", {rows: "8", oninput: (event) => oninput(event.target.value)}); control.value = value ?? ""; return control; }

export function initialFragmentState(state) {
  state.limit ||= 25; state.offset ||= 0; state.query ||= ""; state.categoryId ??= ""; state.showArchived ||= false;
  state.categories ||= []; state.fragments ||= []; state.total ||= 0; state.mobilePanel ||= "list";
  return state;
}
export function shouldRestoreRouteDetail({requestedId, editor, selected} = {}) {
  return Boolean(requestedId) && (!editor || selected?.id !== requestedId);
}
export function routeFragmentId(value) {
  const id = String(value || "");
  return id && id !== "new" ? id : null;
}
export function prepareNewRouteState(state, routeId) {
  if (routeId !== "new" || state.editor) return false;
  state.selected = null;
  state.editor = fragmentDraft();
  state.dirty = false;
  state.mobilePanel = "detail";
  return true;
}
export function fragmentDraft(item = null) {
  return item ? {id: item.id, revision: item.revision, number: item.number, name: item.name, body: item.body,
    category_id: item.category_id ?? null, include: {upper: Boolean(item.include?.upper), lower: Boolean(item.include?.lower)}} :
    {name: "", body: "", category_id: null, include: {upper: true, lower: false}};
}
export function draftChanged(draft, item) {
  if (!draft) return false;
  if (!item) return Boolean(draft.name || draft.body || draft.category_id);
  return draft.name !== item.name || draft.body !== item.body || (draft.category_id ?? null) !== (item.category_id ?? null) ||
    Boolean(draft.include.upper) !== Boolean(item.include?.upper) || Boolean(draft.include.lower) !== Boolean(item.include?.lower);
}

async function load(state, api) {
  const categoriesPage = async () => {
    const all = [];
    for (let offset = 0; ; offset += 200) {
      const page = await api.get(query("/v1/prompt-fragment-categories", {archived: state.showArchived, limit: 200, offset}));
      const values = collection(page); all.push(...values);
      if (values.length < 200 || (Number.isInteger(page?.total) && all.length >= page.total)) return all;
    }
  };
  const [categories, fragments] = await Promise.all([
    categoriesPage(),
    api.get(fragmentListPath({query: state.query, categoryId: state.categoryId, archived: state.showArchived, limit: state.limit, offset: state.offset})),
  ]);
  const items = collection(fragments);
  const total = Number.isInteger(fragments?.total) ? fragments.total : items.length;
  return {categories, fragments: items, total, offset: pageOffsetForTotal(state.offset, state.limit, total)};
}

/** Global prompt fragment management page. Core owns number allocation and revisions. */
export async function mount(container, ctx) {
  const state = initialFragmentState(ctx.state || {});
  // The router supplies this only for an explicit detail URL. Consume it once:
  // ordinary search/category refreshes must never re-open a detail panel.
  const requestedNewFragment = state.selectedId === "new";
  const requestedDetailId = routeFragmentId(state.selectedId);
  state.selectedId = null;
  prepareNewRouteState(state, requestedNewFragment ? "new" : null);
  let routeDetailHandled = false;
  let disposed = false;
  let loading = 0;
  const notify = (message, isError = false) => ctx.notify?.(message, isError);
  const guarded = (action) => {
    if (state.editor && (state.dirty || draftChanged(state.editor, state.selected))) {
      state.error = "저장하지 않은 변경이 있습니다. 저장하거나 취소한 뒤 이동하세요."; render(); return false;
    }
    action(); return true;
  };
  const refresh = async () => {
    const ticket = ++loading;
    const requestedOffset = state.offset;
    try {
      const result = await load(state, ctx.api);
      if (disposed || ticket !== loading) return;
      Object.assign(state, result); state.error = null;
      if (!routeDetailHandled && shouldRestoreRouteDetail({requestedId: requestedDetailId, editor: state.editor, selected: state.selected})) {
        routeDetailHandled = true;
        let restored = state.fragments.find((item) => item.id === requestedDetailId);
        if (!restored) restored = await ctx.api.get(`/v1/prompt-fragments/${encodeURIComponent(requestedDetailId)}`);
        if (disposed || ticket !== loading) return;
        state.selected = restored; state.editor = fragmentDraft(restored); state.dirty = false; state.mobilePanel = "detail";
      } else if (!requestedDetailId && !state.editor && state.mobilePanel === "detail") state.mobilePanel = "list";
      // A deletion can make the previous page empty. Load the now-valid page.
      if (result.offset !== requestedOffset) { state.offset = result.offset; return refresh(); }
    }
    catch (error) { state.error = errorText(error); }
    if (!disposed && ticket === loading) render();
  };
  const select = (item, mobile = false) => guarded(() => { state.selected = item; state.selectedId = item.id; state.editor = fragmentDraft(item); state.dirty = false; state.history = null; if (mobile) { state.mobilePanel = "detail"; ctx.onDetailChange?.(item.id); } render(); });
  const saveFragment = async () => {
    const value = state.editor;
    if (!String(value.name).trim() || !String(value.body).trim()) { state.error = "조각 이름과 본문을 입력하세요."; render(); return; }
    if (state.saving) return;
    state.saving = true; render();
    try {
      const body = {name: value.name.trim(), body: value.body.trim(), category_id: value.category_id || null, include: {upper: Boolean(value.include.upper), lower: Boolean(value.include.lower)}};
      const saved = value.id ? await ctx.api.patch(`/v1/prompt-fragments/${value.id}`, {revision: value.revision, ...body}) : await ctx.api.post("/v1/prompt-fragments", body);
      state.selected = saved; state.selectedId = saved.id; state.editor = fragmentDraft(saved); state.dirty = false; state.history = null; state.offset = value.id ? state.offset : 0;
      ctx.onDetailChange?.(saved.id);
      notify("전역 조각을 저장했습니다."); await refresh();
    } catch (error) { state.error = errorText(error); render(); }
    finally { state.saving = false; if (!disposed) render(); }
  };
  const archiveFragment = async () => {
    if (!state.selected) return;
    if (state.saving) return;
    state.saving = true; render();
    try { const archived = !state.selected.archived; await ctx.api.patch(`/v1/prompt-fragments/${state.selected.id}`, {revision: state.selected.revision, archived}); state.selected = null; state.selectedId = null; state.editor = null; state.dirty = false; state.mobilePanel = "list"; ctx.onDetailChange?.(null); notify(archived ? "조각을 보관했습니다." : "조각을 복원했습니다."); await refresh(); }
    catch (error) { state.error = errorText(error); render(); } finally { state.saving = false; if (!disposed) render(); }
  };
  const loadHistory = async () => {
    if (!state.selected?.id) return;
    const expected = `${state.selected.id}@${state.selected.revision}`;
    state.historyLoading = true; render();
    try {
      const result = await ctx.api.get(query(`/v1/prompt-fragments/${state.selected.id}/revisions`, {limit: 50, offset: 0}));
      if (`${state.selected?.id}@${state.selected?.revision}` !== expected) return;
      state.history = collection(result); state.historyError = null;
    } catch (error) { if (`${state.selected?.id}@${state.selected?.revision}` === expected) state.historyError = errorText(error); }
    finally { if (`${state.selected?.id}@${state.selected?.revision}` === expected) { state.historyLoading = false; render(); } }
  };
  const saveCategory = async () => {
    if (state.categorySaving) return;
    const value = String(state.categoryEditor?.name || "").trim();
    if (!value) { state.error = "카테고리 이름을 입력하세요."; render(); return; }
    state.categorySaving = true; render();
    try {
      if (state.categoryEditor.id) await ctx.api.patch(`/v1/prompt-fragment-categories/${state.categoryEditor.id}`, {revision: state.categoryEditor.revision, name: value});
      else await ctx.api.post("/v1/prompt-fragment-categories", {name: value});
      state.categoryEditor = null; await refresh();
    } catch (error) { state.error = errorText(error); render(); }
    finally { state.categorySaving = false; if (!disposed) render(); }
  };
  const archiveCategory = async (category) => {
    try { await ctx.api.patch(`/v1/prompt-fragment-categories/${category.id}`, {revision: category.revision, archived: !category.archived}); if (state.categoryId === category.id) state.categoryId = ""; await refresh(); }
    catch (error) { state.error = errorText(error); render(); }
  };
  const categoryPanel = () => {
    const rows = state.categories.map((category) => el("li", {class: "fragment-category-row"}, [
      button(category.name, () => guarded(() => { state.categoryId = category.id; state.categoryOpen = false; state.offset = 0; state.mobilePanel = "list"; refresh(); }), {secondary: state.categoryId !== category.id}),
      button("수정", () => { state.categoryEditor = {...category}; render(); }, {secondary: true}), button(category.archived ? "복원" : "보관", () => archiveCategory(category), {secondary: true}),
    ]));
    const categoryForm = state.categoryEditor ? el("form", {class: "fragment-category-form", onsubmit: (event) => { event.preventDefault(); saveCategory(); }}, [
      field("카테고리 이름", input(state.categoryEditor.name, (value) => { state.categoryEditor.name = value; state.categoryEditor.dirty = true; })),
      button("카테고리 저장", saveCategory, {disabled: state.categorySaving}), button("취소", () => { state.categoryEditor = null; render(); }, {secondary: true, disabled: state.categorySaving}),
    ]) : null;
    const toggle = button(`카테고리 · ${state.categories.find(c => c.id === state.categoryId)?.name || (state.categoryId === 'uncategorized' ? '미분류' : '전체')}`, () => {state.categoryOpen = !state.categoryOpen;render();});
    toggle.classList.add('fragment-category-toggle');toggle.setAttribute('aria-expanded', String(Boolean(state.categoryOpen)));
    return el("aside", {class: `fragment-categories panel${state.categoryOpen ? ' categories-open' : ''}`}, [toggle, el("h2", {text: "카테고리"}), button("전체 조각", () => guarded(() => { state.categoryId = ""; state.categoryOpen = false; state.offset = 0; refresh(); }), {secondary: state.categoryId !== ""}),
      button("미분류", () => guarded(() => { state.categoryId = "uncategorized"; state.offset = 0; refresh(); }), {secondary: state.categoryId !== "uncategorized"}),
      el("ul", {class: "fragment-category-list"}, rows), categoryForm || button("+ 카테고리", () => { state.categoryEditor = {name: ""}; render(); }, {secondary: true})]);
  };
  const listPanel = () => {
    const rows = state.fragments.map((item) => el("li", {class: `fragment-row${state.selected?.id === item.id ? " selected" : ""}`}, [button(`#${item.number ?? "–"} ${item.name}`, () => select(item, true), {secondary: true}), el("p", {class: "muted", text: String(item.body || "").slice(0, 120)})]));
    const from = state.total ? state.offset + 1 : 0;
    return el("section", {class: "fragment-list-panel panel"}, [el("h2", {text: "전역 조각"}),
      field("검색", input(state.query, (value) => { state.query = value; }, {placeholder: "이름 또는 Prompt 검색"})),
      el("div", {class: "toolbar"}, [button("검색", () => guarded(() => { state.offset = 0; refresh(); }), {secondary: true}), button(state.showArchived ? "활성 조각 보기" : "보관함", () => guarded(() => { state.showArchived = !state.showArchived; state.categoryId = ""; state.offset = 0; refresh(); }), {secondary: true}), button("+ 새 조각", () => guarded(() => { state.selected = null; state.selectedId = "new"; state.editor = fragmentDraft(); state.dirty = false; state.mobilePanel = "detail"; ctx.onDetailChange?.("new"); render(); }))]),
      el("ul", {class: "fragment-list"}, rows.length ? rows : [el("li", {class: "muted", text: "조건에 맞는 조각이 없습니다."})]),
      el("div", {class: "toolbar"}, [button("이전", () => guarded(() => { state.offset = Math.max(0, state.offset - state.limit); refresh(); }), {secondary: true, disabled: state.offset === 0}), button("다음", () => guarded(() => { state.offset += state.limit; refresh(); }), {secondary: true, disabled: state.offset + state.limit >= state.total})]),
      el("p", {class: "muted", text: `조각 ${from}–${Math.min(state.offset + state.limit, state.total)} / ${state.total}`})]);
  };
  const detailPanel = () => {
    if (!state.editor) return el("aside", {class: "fragment-detail panel"}, [el("h2", {text: "상세"}), el("p", {class: "muted", text: "목록에서 조각을 선택하거나 새 조각을 만드세요."})]);
    const editor = state.editor;
    const hasCurrentCategory = state.categories.some((item) => item.id === editor.category_id);
    const category = el("select", {onchange: (event) => { editor.category_id = event.target.value || null; state.dirty = true; }}, [el("option", {value: "", text: "미분류"}),
      editor.category_id && !hasCurrentCategory ? el("option", {value: editor.category_id, selected: "", text: "현재 보관된 카테고리"}) : null,
      ...state.categories.map((item) => el("option", {value: item.id, text: item.name, selected: editor.category_id === item.id ? "" : null}))]);
    const history = state.history?.map((entry) => el("li", {class: "fragment-history-row"}, [el("strong", {text: `r${entry.revision}`}), el("span", {text: entry.name || "이전 이름"}), entry.archived ? el("span", {class: "muted", text: "보관됨"}) : null])) || [];
    const historyPanel = editor.id ? el("section", {class: "fragment-history"}, [el("h3", {text: "변경 이력"}),
      state.historyError ? el("p", {class: "error", text: state.historyError}) : null,
      state.history ? el("ul", {}, history.length ? history : [el("li", {class: "muted", text: "기록된 이력이 없습니다."})]) : button(state.historyLoading ? "이력 불러오는 중…" : "이력 보기", loadHistory, {secondary: true, disabled: state.historyLoading})]) : null;
    return el("aside", {class: "fragment-detail panel"}, [el("div", {class: "toolbar"}, [button("목록으로", () => guarded(() => { state.selectedId = null; state.mobilePanel = "list"; ctx.onDetailChange?.(null); render(); }), {secondary: true})]), el("h2", {text: editor.id ? `#${editor.number ?? "–"} 조각 편집` : "새 전역 조각"}),
      el("p", {class: "muted", text: "표시 번호는 Core가 전체 조각에 자동으로 부여하며 수정할 수 없습니다."}),
      field("이름", input(editor.name, (value) => { editor.name = value; state.dirty = true; })), field("카테고리", category), field("Prompt 본문", textarea(editor.body, (value) => { editor.body = value; state.dirty = true; })),
      field("상의 포함", el("input", {type: "checkbox", checked: editor.include.upper, onchange: (event) => { editor.include.upper = event.target.checked; state.dirty = true; }})), field("하의 포함", el("input", {type: "checkbox", checked: editor.include.lower, onchange: (event) => { editor.include.lower = event.target.checked; state.dirty = true; }})),
      el("div", {class: "toolbar"}, [button("저장", saveFragment, {disabled: state.saving}), button("취소", () => { state.editor = state.selected ? fragmentDraft(state.selected) : null; state.selectedId = state.selected?.id || null; state.dirty = false; state.mobilePanel = "list"; ctx.onDetailChange?.(null); render(); }, {secondary: true}), editor.id ? button(state.selected?.archived ? "복원" : "보관", archiveFragment, {secondary: true, disabled: state.saving}) : null]), historyPanel]);
  };
  function render() {
    const main = el("div", {class: `fragment-library${state.mobilePanel === "detail" ? " fragment-detail-open" : ""}`}, [categoryPanel(), listPanel(), detailPanel()]);
    container.replaceChildren(...(state.error ? [el("p", {class: "error", role: "alert", text: state.error}), main] : [main]));
    state.error = null;
  }
  await refresh();
  return () => { disposed = true; };
}
