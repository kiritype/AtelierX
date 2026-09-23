import {fragmentListPath, pageOffsetForTotal} from "./fragment-picker.js";
import {FRAGMENT_NUMBER_MAX, OUTFIT_PARTS, PART_LABELS, defaultFragmentInclude, duplicateNumberMessage, fragmentIncludeSummary, fragmentLabel, fragmentNumberError, normalizeFragmentInclude, saveWarningMessages} from "./fragment-rules.js";
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
function textarea(value, oninput, rows = "8") { const control = el("textarea", {rows, oninput: (event) => oninput(event.target.value)}); control.value = value ?? ""; return control; }

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
const numberText = (value) => value === null || value === undefined ? "" : String(value);
export function fragmentDraft(item = null) {
  return item ? {id: item.id, revision: item.revision, number: numberText(item.number), name: item.name, body: item.body, negative: item.negative ?? "",
    category_id: item.category_id ?? null, common: Boolean(item.common), include: normalizeFragmentInclude(item.include)} :
    {number: "", name: "", body: "", negative: "", category_id: null, common: false, include: defaultFragmentInclude()};
}
export function draftChanged(draft, item) {
  if (!draft) return false;
  if (!item) return Boolean(draft.name || draft.body || draft.negative || draft.category_id || draft.number);
  const saved = normalizeFragmentInclude(item.include);
  return draft.name !== item.name || draft.body !== item.body || (draft.negative ?? "") !== (item.negative ?? "") || (draft.category_id ?? null) !== (item.category_id ?? null) || Boolean(draft.common) !== Boolean(item.common) ||
    (!draft.common && numberText(draft.number) !== numberText(item.number)) ||
    OUTFIT_PARTS.some((name) => Boolean(draft.include[name]) !== saved[name]);
}
export function fragmentSaveBody(draft) {
  const common = Boolean(draft.common);
  const include = normalizeFragmentInclude(draft.include);
  return {name: String(draft.name).trim(), body: String(draft.body).trim(), negative: String(draft.negative ?? "").trim(), category_id: draft.category_id || null, common,
    number: common ? null : numberText(draft.number), include: {upper: include.upper, lower: include.lower, accessories: include.accessories, hands: include.hands}};
}
export function fragmentValidationError(draft) {
  if (!String(draft?.name || "").trim() || !String(draft?.body || "").trim()) return "조각 이름과 본문을 입력하세요.";
  return draft.common ? null : fragmentNumberError(numberText(draft.number));
}
export function numberCheckPath(number, excludeId) {
  const params = new URLSearchParams({number: String(number)});
  if (excludeId) params.set("exclude_id", excludeId);
  return `/v1/prompt-fragments/number-check?${params}`;
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

/** Global prompt fragment management page. Core owns revisions and duplicate-number warnings. */
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
  const saveFragment = async (duplicateConfirmed = false) => {
    const value = state.editor;
    const invalid = fragmentValidationError(value);
    if (invalid) { state.error = invalid; render(); return; }
    if (state.saving) return;
    state.saving = true; state.numberConfirm = null; render();
    try {
      const body = fragmentSaveBody(value);
      if (!body.common && duplicateConfirmed !== true) {
        const check = await ctx.api.get(numberCheckPath(body.number, value.id));
        if (disposed || state.editor !== value) return;
        const duplicates = Array.isArray(check?.duplicates) ? check.duplicates.filter((item) => item.id !== value.id) : [];
        if (duplicates.length) { state.numberConfirm = {editor: value, number: body.number, message: duplicateNumberMessage(body.number, duplicates)}; return; }
      }
      const saved = value.id ? await ctx.api.patch(`/v1/prompt-fragments/${value.id}`, {revision: value.revision, ...body}) : await ctx.api.post("/v1/prompt-fragments", body);
      state.selected = saved; state.selectedId = saved.id; state.editor = fragmentDraft(saved); state.dirty = false; state.history = null; state.offset = value.id ? state.offset : 0;
      ctx.onDetailChange?.(saved.id);
      const warnings = saveWarningMessages(saved?.warnings);
      notify(warnings.length ? `전역 조각을 저장했습니다. ${warnings.join(" ")}` : "전역 조각을 저장했습니다.", false);
      await refresh();
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
    const rows = state.categories.map((category) => {
      const selectCategory = button(category.name, () => guarded(() => { state.categoryId = category.id; state.categoryOpen = false; state.offset = 0; state.mobilePanel = "list"; refresh(); }), {secondary: state.categoryId !== category.id});
      selectCategory.title = category.name;
      selectCategory.setAttribute("aria-current", String(state.categoryId === category.id));
      const actions = el("details", {class: "fragment-category-actions", ontoggle: (event) => {
        if (event.currentTarget.open) container.querySelectorAll(".fragment-category-actions[open]").forEach((other) => { if (other !== event.currentTarget) other.open = false; });
      }, onkeydown: (event) => {
        if (event.key === "Escape") { event.currentTarget.open = false; event.currentTarget.querySelector("summary").focus(); }
      }}, [
        el("summary", {text: "⋯", "aria-label": `${category.name} 관리`, title: "카테고리 관리"}),
        el("div", {class: "fragment-category-action-list"}, [
          button("이름 수정", () => { state.categoryEditor = {...category}; render(); }, {secondary: true}),
          button(category.archived ? "복원" : "보관", () => archiveCategory(category), {secondary: true}),
          el("small", {class: "muted", text: "보관해도 안의 조각은 삭제되지 않습니다."}),
        ]),
      ]);
      return el("li", {class: "fragment-category-row"}, [selectCategory, actions]);
    });
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
    const rows = state.fragments.map((item) => el("li", {class: `fragment-row${state.selected?.id === item.id ? " selected" : ""}`}, [button(item.common ? item.name : fragmentLabel(item), () => select(item, true), {secondary: true}), el("span", {class: "badge", text: item.common ? "공통 적용" : "이미지별"}), item.common ? null : el("small", {class: "muted", text: fragmentIncludeSummary(item.include)}), el("p", {class: "muted", text: String(item.body || "").slice(0, 120)}), item.negative ? el("p", {class: "muted", text: `Negative: ${String(item.negative).slice(0, 80)}`}) : null]));
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
    const numberError = editor.common ? null : fragmentNumberError(editor.number);
    const numberId = `fragment-number-${++controlSequence}`;
    const numberHint = el("small", {class: "muted", id: `${numberId}-hint`, "aria-live": "polite", text: editor.number && numberError ? numberError : "파일명에 쓰는 번호입니다. 숫자·문자 모두 가능하며 < > : \" / \\ | ? * 는 쓸 수 없습니다."});
    const numberInput = input(editor.number, (value) => {
      editor.number = value; state.dirty = true; state.numberConfirm = null;
      const message = value ? fragmentNumberError(value) : null;
      numberHint.textContent = message || "파일명에 쓰는 번호입니다. 숫자·문자 모두 가능하며 < > : \" / \\ | ? * 는 쓸 수 없습니다.";
      numberHint.className = message ? "error" : "muted";
      numberInput.setAttribute("aria-invalid", String(Boolean(message)));
    }, {id: numberId, maxlength: String(FRAGMENT_NUMBER_MAX), required: "", autocomplete: "off", "aria-describedby": numberHint.id, "aria-invalid": String(Boolean(editor.number && numberError))});
    if (editor.number && numberError) numberHint.className = "error";
    const numberField = editor.common ? null : el("div", {class: "field"}, [el("label", {for: numberId, text: "번호 (필수)"}), numberInput, numberHint]);
    const includeToggle = (name) => field(`${PART_LABELS[name]} 포함`, el("input", {type: "checkbox", checked: Boolean(editor.include[name]), onchange: (event) => { editor.include[name] = event.target.checked; state.dirty = true; }}));
    if (state.numberConfirm && state.numberConfirm.editor !== editor) state.numberConfirm = null;
    const numberConfirm = state.numberConfirm ? el("section", {class: "panel fragment-number-confirm", role: "alertdialog", "aria-label": "중복 번호 확인"}, [
      el("p", {text: state.numberConfirm.message}),
      el("div", {class: "toolbar"}, [button("같은 번호로 저장", () => saveFragment(true), {disabled: state.saving}), button("번호 수정", () => { state.numberConfirm = null; render(); }, {secondary: true})]),
    ]) : null;
    return el("aside", {class: "fragment-detail panel"}, [el("div", {class: "toolbar"}, [button("목록으로", () => guarded(() => { state.selectedId = null; state.mobilePanel = "list"; ctx.onDetailChange?.(null); render(); }), {secondary: true})]), el("h2", {text: editor.id ? `${editor.common ? "" : `#${editor.number || "–"} `}조각 편집` : "새 전역 조각"}),
      el("p", {class: "badge", text: editor.common ? "공통 적용 프롬프트" : "이미지별 조각"}),
      numberField,
      field("이름", input(editor.name, (value) => { editor.name = value; state.dirty = true; })), field("카테고리", category), field("Prompt 본문", textarea(editor.body, (value) => { editor.body = value; state.dirty = true; })),
      field("Negative (선택)", textarea(editor.negative, (value) => { editor.negative = value; state.dirty = true; }, "3"), "생성에만 쓰는 제외 조건입니다. 전역·캐릭터 Negative 뒤에 붙으며 VLM 검사 대상이 아닙니다."),
      field("공통 적용 프롬프트로 사용", el("input", {type: "checkbox", checked: editor.common, onchange: (event) => { editor.common = event.target.checked; state.dirty = true; state.numberConfirm = null; render(); }}), "모든 선택 이미지에 본문만 덧붙입니다. 공통 조각은 번호가 없습니다."),
      editor.common ? el("p", {class: "muted", text: "공통 조각은 의상 상의·하의·액세서리·손 포함 여부를 바꾸지 않습니다."}) : el("div", {class: "grid"}, OUTFIT_PARTS.map(includeToggle)),
      numberConfirm,
      el("div", {class: "toolbar"}, [button("저장", () => saveFragment(false), {disabled: state.saving || Boolean(state.numberConfirm)}), button("취소", () => { state.numberConfirm = null; state.editor = state.selected ? fragmentDraft(state.selected) : null; state.selectedId = state.selected?.id || null; state.dirty = false; state.mobilePanel = "list"; ctx.onDetailChange?.(null); render(); }, {secondary: true}), editor.id ? button(state.selected?.archived ? "복원" : "보관", archiveFragment, {secondary: true, disabled: state.saving}) : null]), historyPanel]);
  };
  function render() {
    const main = el("div", {class: `fragment-library${state.mobilePanel === "detail" ? " fragment-detail-open" : ""}`}, [categoryPanel(), listPanel(), detailPanel()]);
    container.replaceChildren(...(state.error ? [el("p", {class: "error", role: "alert", text: state.error}), main] : [main]));
    state.error = null;
  }
  await refresh();
  return () => { disposed = true; };
}
