/**
 * Production pilot page.  It only composes Core REST requests; Core remains
 * responsible for prompt composition, frozen groups, and task orchestration.
 */
import {fragmentKey, fragmentListPath, fragmentReference, preserveSelection} from "./fragment-picker.js";
import {mountStudioTree} from "./studio-tree.js";
import {OUTFIT_PARTS, checkFeaturesError, defaultFragmentInclude, fragmentIncludeSummary, fragmentLabel, inclusionLabels, parseCheckFeatures} from "./fragment-rules.js";
import {consistencyFormValues, consistencyMethodChoices, estimatedSecondsWithConsistency, mountReferenceSetPanel, referenceMismatchDiffRows, referenceStatusLabel} from "./reference-sets.js";
import {sortByName} from "./name-sort.js";

const EMPTY_COMPONENTS = Object.freeze({ upper: "", lower: "", accessories: "", hands: "" });
const DEFAULT_GENERATION = Object.freeze({
  diffusion_model: "", text_encoder: "", vae: "", width: 1024, height: 1024,
  seed: -1, steps: 24, cfg: 4.5, sampler: "euler_ancestral", scheduler: "normal",
});
const KNOWN_ANIMA_LORAS = Object.freeze([
  "anima-base-1-masterpiece-v51.safetensors", "anima-highres-aesthetic-boost.safetensors",
  "gpt-image-2_anima-base1_v1-1.safetensors", "shinjiro_AnimaB_v01.safetensors",
]);
// These lists match the installed ComfyUI 0.35.0 KSampler lists. The node
// validates the same names on the server, so this only drives the UI choices.
export const SAMPLER_OPTIONS = Object.freeze([
  "euler", "euler_cfg_pp", "euler_ancestral", "euler_ancestral_cfg_pp", "heun", "heunpp2",
  "exp_heun_2_x0", "exp_heun_2_x0_sde", "dpm_2", "dpm_2_ancestral", "lms", "dpm_fast",
  "dpm_adaptive", "dpmpp_2s_ancestral", "dpmpp_2s_ancestral_cfg_pp", "dpmpp_sde", "dpmpp_sde_gpu",
  "dpmpp_2m", "dpmpp_2m_cfg_pp", "dpmpp_2m_sde", "dpmpp_2m_sde_gpu", "dpmpp_2m_sde_heun",
  "dpmpp_2m_sde_heun_gpu", "dpmpp_3m_sde", "dpmpp_3m_sde_gpu", "ddpm", "lcm", "ipndm", "ipndm_v",
  "deis", "cfgpp_ud10_ab", "res_multistep", "res_multistep_cfg_pp", "res_multistep_ancestral",
  "res_multistep_ancestral_cfg_pp", "gradient_estimation", "gradient_estimation_cfg_pp", "er_sde", "seeds_2",
  "seeds_3", "sa_solver", "sa_solver_pece", "ddim", "uni_pc", "uni_pc_bh2",
]);
export const SCHEDULER_OPTIONS = Object.freeze([
  "simple", "sgm_uniform", "karras", "exponential", "ddim_uniform", "beta", "normal",
  "linear_quadratic", "kl_optimal",
]);
let fieldSequence = 0;

function node(tag, properties = {}, children = []) {
  const result = document.createElement(tag);
  for (const [key, value] of Object.entries(properties)) {
    if (value === undefined || value === null) continue;
    if (key === "text") result.textContent = String(value);
    else if (key === "class") result.className = value;
    else if (key === "for") result.htmlFor = value;
    else if (key.startsWith("on")) result.addEventListener(key.slice(2).toLowerCase(), value);
    else if (key === "checked") result.checked = Boolean(value);
    else result.setAttribute(key, String(value));
  }
  for (const child of Array.isArray(children) ? children : [children]) {
    if (child !== undefined && child !== null) result.append(child);
  }
  return result;
}

function field(labelText, control, hint) {
  const id = control.id || `production-field-${++fieldSequence}`;
  control.id = id;
  const hintId = hint ? `${id}-hint` : null;
  if (hintId) control.setAttribute("aria-describedby", hintId);
  return node("div", { class: "field" }, [node("label", { for: id, text: labelText }), control,
    hint ? node("small", { id: hintId, class: "muted", text: hint }) : null]);
}

function textInput(value, onChange, { type = "text", placeholder = "", min, max, step } = {}) {
  return node("input", { type, value: value ?? "", placeholder, min, max, step,
    oninput: (event) => onChange(event.target.value) });
}

function textArea(value, onChange, placeholder = "") {
  return node("textarea", { rows: "3", placeholder, oninput: (event) => onChange(event.target.value) }, [document.createTextNode(value ?? "")]);
}

function button(label, action, { secondary = false, disabled = false } = {}) {
  return node("button", { type: "button", class: secondary ? "button secondary" : "button", disabled: disabled ? "" : null, onclick: action, text: label });
}

function selectedOption(value, label, selected) {
  return node("option", { value, selected: selected ? "" : null, text: label });
}

function deepCopy(value) {
  return JSON.parse(JSON.stringify(value));
}

export function randomSafeSeed(fill = (values) => globalThis.crypto?.getRandomValues(values)) {
  const values = new Uint32Array(2);
  const filled = fill?.(values);
  if (!filled) return Math.floor(Math.random() * Number.MAX_SAFE_INTEGER);
  return ((values[0] & 0x1fffff) * 0x100000000) + values[1];
}

export function estimatedUpscaleResolution(width, height, scale) {
  const factor = finiteNumber(scale, "Upscale 배율");
  if (factor <= 0) throw new Error("Upscale 배율은 0보다 커야 합니다.");
  const roundHalfUp = (value) => Math.floor(value + 0.5);
  return {width: Math.max(1, roundHalfUp(finiteNumber(width, "너비", {integer: true}) * factor)), height: Math.max(1, roundHalfUp(finiteNumber(height, "높이", {integer: true}) * factor)), factor};
}

export function postprocessResolutionEstimate(draft, presets = {}) {
  const resolve = (value, items) => { const ref = value ? presetReference(value) : null; return ref && (items || []).find((item) => item.id === ref.id && item.revision === ref.revision)?.settings; };
  const generation = resolve(draft.generationPreset, presets.generation) || draft.generation;
  const postprocess = resolve(draft.postprocessPreset, presets.postprocess);
  const scale = postprocess ? (postprocess.upscale ? postprocess.upscale.scale ?? 1.5 : 1) : draft.postprocessMode === "direct" ? draft.upscaleScale : draft.postprocessMode === "none" ? 1 : 1.5;
  return estimatedUpscaleResolution(generation.width, generation.height, scale);
}

function makeKey() {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
  return `production-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

function requestError(error) {
  if (error?.code === "CORE_APPEARANCE_MIGRATION_RESOLUTION_REQUIRED") return "캐릭터 외형 이전 충돌을 먼저 해결하세요. 캐릭터 편집에서 후보 외형을 선택해 저장한 뒤 의상과 생성을 다시 준비하세요.";
  if (error?.code === "CORE_REFERENCE_SET_REQUIRED") {
    const outfits = (error.details?.outfits || []).map((item) => `${item.outfit_id}(${referenceStatusLabel(item.status)})`).join(", ");
    return `참조 세트가 필요합니다${outfits ? `: ${outfits}` : ""}. 캐릭터 관리의 의상 화면에서 먼저 참조 세트를 확정하세요.`;
  }
  return error?.message || "요청을 완료하지 못했습니다.";
}

/** ADR-0027 P1/#7, P5: `POST /v1/production-plans` rejects a missing/needs_review
 * reference set (409 `CORE_REFERENCE_SET_REQUIRED`, re-thrown with a readable
 * message via `requestError`) and warns on a settings mismatch (409
 * `CORE_REFERENCE_SETTINGS_MISMATCH`, `{diff}`). The mismatch is not a hard
 * block: on confirmation this resubmits the same body plus
 * `accept_reference_settings_mismatch: true` under a new idempotency key,
 * since the body content changed. */
async function submitProductionPlan(api, request, key) {
  try {
    return await api.post("/v1/production-plans", request, key);
  } catch (error) {
    if (error?.code !== "CORE_REFERENCE_SETTINGS_MISMATCH") throw error;
    const rows = referenceMismatchDiffRows(error.details?.diff);
    const summary = rows.map((row) => `- ${row.label}: 참조 세트=${row.reference} / 계획=${row.plan}`).join("\n");
    const proceed = typeof window !== "undefined" && window.confirm
      ? window.confirm(`생성 설정이 확정한 참조 세트와 다릅니다.\n${summary}\n\n그래도 진행할까요?`) : false;
    if (!proceed) throw new Error("설정 불일치로 계획을 만들지 않았습니다. 확인 후 다시 시도하세요.");
    return api.post("/v1/production-plans", { ...request, accept_reference_settings_mismatch: true }, makeKey());
  }
}

function collection(payload) {
  return Array.isArray(payload?.items) ? payload.items : [];
}

function finiteNumber(value, name, { integer = false } = {}) {
  const number = Number(value);
  if (!Number.isFinite(number) || (integer && !Number.isInteger(number))) {
    throw new Error(`${name} 값을 확인하세요.`);
  }
  return number;
}

function initialDraft() {
  return {
    compositionMode: "fragment", fragmentSelections: [], commonFragmentSelections: [],
    framing: "custom", framingPrompt: "upper body", expression: "", action: "", situation: "",
    include: defaultFragmentInclude(),
    generation: deepCopy(DEFAULT_GENERATION), loras: [],
    generationPreset: "", postprocessPreset: "", postprocessMode: "default",
    upscaleModel: "4x-UltraSharp.safetensors", upscaleScale: 1.5, webpEnabled: true, webpQuality: 90,
    consistencyMethod: "", consistencyParams: {},
    validationMode: "generation", validationEnabled: false, validationProfile: "", validationProvider: "",
    groupValidationProfile: "", groupValidationProvider: "", planKey: null, planRequest: null, planPending: false,
    multiPlanRequests: {}, multiPlanPending: false,
    preview: null, previewRevision: 0, pendingKey: null, pending: false, task: null,
  };
}

function pageState(ctx) {
  const state = ctx.state;
  state.selection ||= { workId: null, characterId: null, outfitId: null, groupId: null };
  state.selection.groupIds ||= [];
  state.entities ||= { works: [], characters: [], outfits: [], groups: [] };
  state.catalog ||= { works: [], characters: [], outfits: [], groups: [] };
  state.catalogLoaded ||= false;
  state.multiProductionPlans ||= {};
  state.fragments ||= [];
  state.fragmentOffset ||= 0;
  state.fragmentLimit = 25;
  state.fragmentTotal ||= 0;
  state.fragmentCategoryId ||= "";
  state.fragmentSearch ||= "";
  state.fragmentCategories ||= [];
  state.productionSection ||= "prepare";
  state.mobilePreparationPanel ||= "classification";
  state.draft ||= initialDraft();
  state.draft.validationMode ||= state.draft.validationEnabled ? "single-group" : "generation";
  state.draft.validationEnabled = state.draft.validationMode !== "generation";
  state.draft.include ||= defaultFragmentInclude();
  state.draft.fragmentSelections ||= [];
  state.draft.commonFragmentSelections ||= [];
  // Older in-memory drafts used `id@revision` strings. Keep their frozen
  // meaning while moving the picker to the shared serializable reference.
  state.draft.fragmentSelections = state.draft.fragmentSelections.map((value) => {
    if (value && typeof value === "object") return value;
    const [id, revision] = String(value).split("@");
    return {id, revision: Number(revision)};
  }).filter((value) => value.id && Number.isInteger(value.revision) && value.revision > 0);
  state.draft.commonFragmentSelections = state.draft.commonFragmentSelections.map((value) => {
    if (value && typeof value === "object") return value;
    const [id, revision] = String(value).split("@");
    return {id, revision: Number(revision)};
  }).filter((value) => value.id && Number.isInteger(value.revision) && value.revision > 0);
  state.draft.multiPlanRequests ||= {};
  // Preserve existing free-form drafts as an explicitly chosen advanced mode.
  if (!state.draft.compositionMode) state.draft.compositionMode = state.draft.framingPrompt ? "direct" : "fragment";
  // Migrate old enum drafts without inventing an inclusion decision.
  if (state.draft.framing !== "custom") {
    const previous = state.draft.framing;
    state.draft.framingPrompt ||= previous === "full_body" ? "full body" : "upper body";
    if (previous === "upper_body") state.draft.include.lower = false;
    state.draft.framing = "custom";
  }
  state.draft.include = {...state.draft.include, upper: Boolean(state.draft.include.upper), lower: Boolean(state.draft.include.lower), accessories: Boolean(state.draft.include.accessories), hands: state.draft.include.hands !== false};
  state.expanded ||= { works: {}, characters: {} };
  if (typeof state.selectedId === "string" && state.selectedId.startsWith("plan:")) {
    const selectedPlanId = state.selectedId.slice(5);
    if (state.productionPlanId !== selectedPlanId) {
      state.productionPlanId = selectedPlanId;
      state.productionPlan = null; state.productionPlanItems = []; state.productionPlanComparisons = [];
      state.planItemsOffset = 0;
    }
  }
  state.planItemsOffset ||= 0;
  state.presets ||= { generation: [], postprocess: [], profiles: [], providers: [] };
  state.selectedOutfitIds ||= [];
  state.creationPreviewOffset ||= 0;
  state.creationMobilePanel ||= "targets";
  state.creationExpanded ||= {};
  return state;
}

function entityById(items, id) {
  return items.find((item) => item.id === id) || null;
}

function query(path, parameters) {
  const values = Object.entries(parameters || {}).filter(([, value]) => value !== null && value !== undefined && value !== "");
  return values.length ? `${path}?${new URLSearchParams(values)}` : path;
}

/** Current selection is deliberately not an input: a new draft must POST even
 * when an older tree row remains selected in another panel. */
export function entityMutationRequest(editor) {
  const {kind, mode, targetId, revision, value} = editor;
  const body = {name: value.name};
  if (mode === "edit") body.revision = revision;
  else if (kind !== "works") body.parent_id = value.parent_id;
  if (kind === "characters") {
    body.appearance_prompt = value.appearance_prompt || "";
    body.negative_prompt = value.negative_prompt || "";
    body.check_features = characterCheckFeatures(value);
  }
  if (kind === "outfits") body.components = Object.fromEntries(OUTFIT_PARTS.map((key) => [key, String(value.components?.[key] || "")]));
  return {method: mode === "edit" ? "patch" : "post", path: mode === "edit" ? `/v1/${kind}/${targetId}` : `/v1/${kind}`, body};
}

export function characterCheckFeatures(value) {
  const features = typeof value?.check_features_text === "string" ? parseCheckFeatures(value.check_features_text)
    : (Array.isArray(value?.check_features) ? value.check_features : []).map((item) => String(item).trim()).filter(Boolean);
  const problem = checkFeaturesError(features);
  if (problem) throw new Error(problem);
  return features;
}

export function appearanceMigrationChoiceRequired(editor) {
  return editor?.kind === "characters" && editor.value?.appearance_migration?.status === "conflict" && !editor.migrationChoiceConfirmed;
}

function entityEditor(state, api, rerender, notify) {
  const selection = state.selection;
  const editor = state.editor;
  const kind = editor?.kind;
  if (!kind) return node("section", { class: "panel" }, [node("h2", { text: "캐릭터·의상 준비" }), node("p", { class: "muted", text: "분류에서 작품, 캐릭터 또는 의상을 선택하거나 새로 만드세요." })]);
  const draft = editor.value;
  const isEdit = editor.mode === "edit";
  const names = {works: "작품", characters: "캐릭터", outfits: "의상"};
  const parents = [];
  if (kind !== "works") {
    const work = entityById(state.entities.works, editor.workId);
    if (work) parents.push(work.name);
  }
  if (kind === "outfits") {
    const character = entityById(state.entities.characters, editor.characterId);
    if (character) parents.push(character.name);
  }
  const edit = (apply) => (value) => { apply(value); state.dirty = true; };
  const controls = [field("이름", textInput(draft.name, edit((value) => { draft.name = value; })), "분류 이름은 생성 Prompt에 자동으로 들어가지 않습니다.")];
  if (kind === "characters") {
    controls.push(field("외형 Prompt", textArea(draft.appearance_prompt || "", edit((value) => { draft.appearance_prompt = value; })), "머리·눈·신체 특징 등 캐릭터 고유 외형입니다."));
    const migration = draft.appearance_migration;
    if (migration?.status === "conflict") controls.push(node("fieldset", {class: "appearance-migration-conflict"}, [node("legend", {text: "기존 의상 외형 충돌 해결"}), node("p", {class: "error", text: "기존 의상에 서로 다른 외형이 있습니다. 아래 후보 하나를 명시적으로 선택해 저장하면 Core가 의상 외형을 캐릭터로 이전합니다."}), ...(migration.candidates || []).map((candidate) => node("label", {class: "row"}, [node("input", {type: "radio", name: `appearance-migration-${editor.targetId || "new"}`, checked: editor.migrationChoiceConfirmed && draft.appearance_prompt === candidate.appearance_prompt, onchange: () => { draft.appearance_prompt = candidate.appearance_prompt; editor.migrationChoiceConfirmed = true; state.dirty = true; rerender(); }}), node("span", {text: candidate.appearance_prompt || "(빈 외형)"}), node("small", {class: "muted", text: `의상 ${Array.isArray(candidate.outfit_ids) ? candidate.outfit_ids.length : 0}개`})]))]));
    const featureText = typeof draft.check_features_text === "string" ? draft.check_features_text : (Array.isArray(draft.check_features) ? draft.check_features : []).join("\n");
    controls.push(field("검사용 핵심 특징", textArea(featureText, edit((value) => { draft.check_features_text = value; }), "은발\n오드아이(왼쪽 호박색·오른쪽 파란색)\n아호게"), "한 줄에 하나씩 입력합니다. 단일 검증에서 외형 문장 대신 이 항목으로 확인합니다. 예: 은발, 오드아이(왼쪽 호박색·오른쪽 파란색), 아호게"));
    controls.push(field("캐릭터 Negative", textArea(draft.negative_prompt || "", edit((value) => { draft.negative_prompt = value; })), "이 캐릭터에만 적용되는 제외 조건입니다."));
  }
  if (kind === "outfits") {
    const parentCharacter = entityById(state.entities.characters, editor.characterId);
    if (parentCharacter?.appearance_migration?.status === "conflict") controls.push(node("p", {class: "error", text: "상위 캐릭터의 외형 이전 충돌을 먼저 해결해야 의상을 저장하거나 새 생성 고정본을 만들 수 있습니다."}));
    controls.push(field("상의", textArea(draft.components.upper, edit((value) => { draft.components.upper = value; })), "상의"));
    controls.push(field("하의", textArea(draft.components.lower, edit((value) => { draft.components.lower = value; })), "하의와 풋웨어"));
    controls.push(field("액세서리", textArea(draft.components.accessories, edit((value) => { draft.components.accessories = value; })), "가방·장신구 등 의상 액세서리"));
    controls.push(field("손", textArea(draft.components.hands ?? "", edit((value) => { draft.components.hands = value; })), "장갑·손톱·반지 등 손 부분. 조각의 손 포함이 켜진 이미지에만 들어갑니다."));
  }
  const save = async () => {
    if (state.entityPending) return;
    state.entityPending = true;
    rerender();
    try {
      if (appearanceMigrationChoiceRequired(editor)) throw new Error("외형 이전 후보를 하나 선택한 뒤 저장하세요.");
      const request = entityMutationRequest(editor);
      const result = await api[request.method](request.path, request.body);
      state.dirty = false;
      state.entityPending = false;
      if (result.kind === "works") { selection.workId = result.id; selection.characterId = null; selection.outfitId = null; state.loaded.works = false; }
      if (result.kind === "characters") { selection.workId = editor.workId; selection.characterId = result.id; selection.outfitId = null; state.expanded.works[editor.workId] = true; delete state.loaded?.characters?.[editor.workId]; delete state.loaded?.outfits?.[result.id]; }
      if (result.kind === "outfits") { selection.workId = editor.workId; selection.characterId = editor.characterId; selection.outfitId = result.id; state.expanded.works[editor.workId] = true; state.expanded.characters[editor.characterId] = true; delete state.loaded?.outfits?.[editor.characterId]; }
      state.editor = {mode: "edit", kind: result.kind, targetId: result.id, revision: result.revision, archived: Boolean(result.archived), migrationChoiceConfirmed: false, workId: selection.workId, characterId: selection.characterId, value: {...result, components: {...EMPTY_COMPONENTS, ...result.components}}};
      notify(isEdit ? "분류를 수정했습니다." : "새 분류를 만들었습니다.");
      await rerender(true);
    } catch (error) { state.entityPending = false; state.error = requestError(error); rerender(); }
  };
  const archive = async () => {
    if (!isEdit || state.entityPending) return;
    state.archiveConfirm = {kind, id: editor.targetId, revision: editor.revision, archived: editor.archived, workId: editor.workId, characterId: editor.characterId};
    rerender();
  };
  const referenceHost = kind === "outfits" && isEdit && !editor.archived ? node("div", { class: "reference-set-host" }) : null;
  // entityEditor is rebuilt (fresh DOM nodes) on every explicit rerender(), so
  // this always tears down the previous panel and mounts a new one into the
  // current host rather than trying to reuse a detached container.
  state.referencePanelDispose?.();
  state.referencePanelDispose = null;
  if (referenceHost) {
    queueMicrotask(() => {
      state.referencePanelDispose = mountReferenceSetPanel(referenceHost, {
        api, outfitId: editor.targetId, notify, signal: state.pageSignal,
      });
    });
  }
  return node("section", { class: "panel" }, [node("h2", { text: isEdit ? `${names[kind]} 수정` : `새 ${names[kind]} 만들기` }),
    parents.length ? node("p", {class: "muted", text: `상위 분류: ${parents.join(" › ")}`}) : null,
    state.dirty ? node("p", { class: "error", text: "원본에 저장하지 않은 변경이 있습니다." }) : null,
    node("div", { class: "grid" }, controls), node("div", { class: "row" }, [button(isEdit ? `${names[kind]} 변경 저장` : `새 ${names[kind]} 저장`, save, {disabled: state.entityPending}),
      button("취소", () => { if (state.entityPending) return; state.editor = null; state.dirty = false; rerender(); }, { secondary: true, disabled: state.entityPending }),
      isEdit ? button(editor.archived ? "복원" : "보관", archive, {secondary: true, disabled: state.entityPending}) : null]),
    isEdit ? node("p", { class: "muted", text: "보관은 삭제나 연쇄 변경이 아닙니다. 기존 고정 그룹과 과거 이력은 유지됩니다." }) : null,
    referenceHost]);
}

function invalidatePreview(draft, clearTask = false) {
  draft.preview = null;
  draft.previewRevision = (Number(draft.previewRevision) || 0) + 1;
  if (clearTask) draft.task = null;
}

export function previewRequestIsCurrent(state, request, revision) {
  if (!request || state.selection.groupId !== request.group_id) return false;
  if ((Number(state.draft.previewRevision) || 0) !== revision) return false;
  try { return JSON.stringify(buildGenerationBody(state)) === JSON.stringify(request); }
  catch { return false; }
}

export function buildGenerationBody(state) {
  const draft = state.draft;
  const groupId = state.selection.groupId;
  if (!groupId) throw new Error("생성할 고정 그룹을 선택하거나 새로 만드세요.");
  const body = { group_id: groupId };
  if (draft.compositionMode === "fragment") {
    if (!Array.isArray(draft.fragmentSelections) || draft.fragmentSelections.length !== 1) {
      throw new Error("단일 미리보기에는 전역 조각을 하나만 선택하세요.");
    }
    body.fragment = presetReference(draft.fragmentSelections[0]);
  } else {
    if (typeof draft.framingPrompt !== "string" || !draft.framingPrompt.trim()) throw new Error("구도 Prompt를 입력하세요.");
    body.framing = "custom";
    body.framing_prompt = draft.framingPrompt;
    body.include = {
      upper: Boolean(draft.include.upper),
      lower: Boolean(draft.include.lower),
      accessories: Boolean(draft.include.accessories),
      hands: draft.include.hands !== false,
    };
    for (const name of ["expression", "action", "situation"]) {
      if (typeof draft[name] === "string" && draft[name].trim()) body[name] = draft[name].trim();
    }
  }
  if (draft.commonFragmentSelections?.length) body.common_fragments = draft.commonFragmentSelections.map(presetReference);
  if (draft.generationPreset) {
    body.presets = { generation: presetReference(draft.generationPreset) };
  } else {
    const input = draft.generation;
    const seed = finiteNumber(input.seed, "Seed", { integer: true });
    if (!Number.isSafeInteger(seed) || seed < -1) throw new Error("Seed는 -1(랜덤) 또는 0 이상의 안전 정수여야 합니다.");
    body.generation_inputs = {
      diffusion_model: input.diffusion_model.trim(), text_encoder: input.text_encoder.trim(), vae: input.vae.trim(),
      width: finiteNumber(input.width, "너비", { integer: true }), height: finiteNumber(input.height, "높이", { integer: true }),
      seed, steps: finiteNumber(input.steps, "Steps", { integer: true }),
      cfg: finiteNumber(input.cfg, "CFG"), sampler: input.sampler.trim(), scheduler: input.scheduler.trim(),
      loras: draft.loras.filter((item) => item.name.trim()).map((item) => ({ name: item.name.trim(), strength: finiteNumber(item.strength, "LoRA 가중치") })),
    };
  }
  if (draft.postprocessPreset) {
    body.presets = { ...(body.presets || {}), postprocess: presetReference(draft.postprocessPreset) };
  } else if (draft.postprocessMode === "none") {
    body.postprocess = {};
  } else if (draft.postprocessMode === "direct") {
    body.postprocess = { upscale: { upscale_model: draft.upscaleModel.trim(), scale: finiteNumber(draft.upscaleScale, "Upscale 배율") },
      encode: { webp_enabled: Boolean(draft.webpEnabled), webp_quality: finiteNumber(draft.webpQuality, "WebP 품질", { integer: true }) } };
  }
  if (draft.validationMode === "single" || draft.validationMode === "single-group" || draft.validationEnabled) {
    if (!draft.validationProfile || !draft.validationProvider) throw new Error("검사 Profile과 Provider를 모두 선택하세요.");
    body.validation = { profile_id: draft.validationProfile, provider_id: draft.validationProvider };
  }
  // ADR-0027 P3: omitting `consistency` lets Core apply its own default (the
  // registered method, when the outfit's reference set is valid) or nothing
  // (when it is not). An explicit method here overrides only its params.
  if (draft.consistencyMethod) body.consistency = { method: draft.consistencyMethod, params: { ...draft.consistencyParams } };
  return body;
}

export function buildProductionPlanBody(state, minimumFragments = 2) {
  const draft = state.draft;
  if (draft.compositionMode !== "fragment" || !Array.isArray(draft.fragmentSelections) || draft.fragmentSelections.length < minimumFragments) {
    throw new Error(`제작 계획에는 전역 조각을 ${minimumFragments === 2 ? "두 개" : "한 개"} 이상 선택하세요.`);
  }
  const mode = draft.validationMode || (draft.validationEnabled ? "single-group" : "generation");
  if ((mode === "single" || mode === "single-group") && (!draft.validationProfile || !draft.validationProvider)) throw new Error("Single 검사 Profile과 Provider를 모두 선택하세요.");
  if (mode === "single-group" && (!draft.groupValidationProfile || !draft.groupValidationProvider)) {
    throw new Error("제작 계획에는 묶음 검사 Profile과 Provider가 필요합니다.");
  }
  // Reuse the exact common generation/postprocess/validation contract from a
  // one-fragment preview, then replace only the composition selection.
  const previewBody = buildGenerationBody({ ...state, draft: { ...draft, fragmentSelections: [draft.fragmentSelections[0]] } });
  delete previewBody.fragment;
  previewBody.fragments = draft.fragmentSelections.map(presetReference);
  if (mode === "single-group") previewBody.group_validation = { profile_id: draft.groupValidationProfile, provider_id: draft.groupValidationProvider };
  return previewBody;
}

// Core accepts one frozen group per plan. Keep this fan-out at the API edge:
// the client duplicates only the already-defined REST request and leaves prompt
// composition, snapshots, and all execution decisions to Core.
export function buildProductionPlanRequests(state) {
  const groupIds = [...new Set(state.selection?.groupIds || [])];
  if (!groupIds.length) throw new Error("제작할 고정 그룹을 하나 이상 선택하세요.");
  return Object.fromEntries(groupIds.map((groupId) => [groupId, buildProductionPlanBody({
    ...state, selection: { ...state.selection, groupId },
  }, 1)]));
}

export function freezeMultiProductionPlanRequests(state, keyFactory = makeKey) {
  const requests = buildProductionPlanRequests(state);
  state.draft.multiPlanRequests ||= {};
  for (const [groupId, request] of Object.entries(requests)) {
    state.draft.multiPlanRequests[groupId] ||= { request, key: keyFactory(), plan: null, error: null };
  }
  return state.draft.multiPlanRequests;
}

function presetReference(value) {
  if (value && typeof value === "object") return fragmentReference(value);
  const [id, revision] = value.split("@");
  return { id, revision: Number(revision) };
}

function selectChoice(value, options, onChange) {
  return node("select", { onchange: (event) => onChange(event.target.value) }, options.map((option) => selectedOption(option, option, value === option)));
}

/** Checkbox tree state is kept DOM-free so category and catalog parents share it. */
export function treeSelectionState(descendantIds, selectedIds) {
  const ids = [...new Set(descendantIds || [])];
  const selected = selectedIds instanceof Set ? selectedIds : new Set(selectedIds || []);
  const count = ids.filter((id) => selected.has(id)).length;
  return {checked: ids.length > 0 && count === ids.length, indeterminate: count > 0 && count < ids.length, count, total: ids.length};
}

export function toggleTreeSelection(selectedIds, descendantIds, checked) {
  const next = new Set(selectedIds || []);
  for (const id of descendantIds || []) checked ? next.add(id) : next.delete(id);
  return [...next];
}

export function creationPreviewPage(outfitIds, fragments, offset = 0, limit = 50) {
  const outfits = [...new Set(outfitIds || [])];
  const values = Array.isArray(fragments) ? fragments : [];
  const total = outfits.length * values.length;
  const items = [];
  for (let index = offset; index < Math.min(total, offset + limit); index += 1) {
    items.push({outfitId: outfits[Math.floor(index / values.length)], fragment: values[index % values.length], index});
  }
  return {total, offset, limit, items};
}

export function plannedItemLabel(outfitName, fragment) {
  return `${outfitName} × ${fragmentLabel(fragment)} (${fragmentIncludeSummary(fragment?.include)})`;
}

function resourceChoice(value, options, onChange, label) {
  const values = Array.isArray(options) ? [...options] : [];
  if (value && !values.includes(value)) values.unshift(value);
  return node("select", { disabled: values.length ? null : "", onchange: (event) => onChange(event.target.value) }, [selectedOption("", values.length ? `${label} 선택` : "등록 자원 없음", !value),
    ...values.map((option) => selectedOption(option, option, value === option))]);
}

function seedField(value, onChange) {
  const input = textInput(value, onChange, { type: "number", min: -1, step: 1 });
  const id = `production-seed-${++fieldSequence}`;
  input.id = id;
  return node("div", { class: "field" }, [node("label", { for: id, text: "Seed" }), input,
    node("small", { class: "muted", text: "-1은 실행 시 Core가 항목별 랜덤 Seed를 고정합니다. 0 이상은 고정 Seed입니다." })]);
}

function generationPanel(state, api, rerender, notify) {
  const draft = state.draft;
  const resources = state.resources || {};
  let estimateLabel = null;
  let timeEstimateLabel = null;
  const updateEstimate = () => {
    if (estimateLabel) { try { const value = postprocessResolutionEstimate(draft, state.presets); estimateLabel.textContent = value ? `예상 최종 해상도: ${value.width}×${value.height} (최종 ${value.factor}배; 모델 고유 배율과 별개)` : "예상 최종 해상도: 원본 크기"; } catch { estimateLabel.textContent = "예상 최종 해상도를 계산할 수 없습니다."; } }
    if (timeEstimateLabel) {
      const consistencyOn = Boolean(draft.consistencyMethod);
      const seconds = estimatedSecondsWithConsistency(9, consistencyOn);
      timeEstimateLabel.textContent = consistencyOn ? `예상 생성 시간: 장당 약 ${Math.round(seconds)}초 (참조 일관성 적용 시 약 3.3배)` : "참조 일관성을 켜면 장당 약 30초로 늘어납니다(현재 약 9초).";
    }
  };
  const change = (callback) => (value) => { callback(value); invalidatePreview(draft, true); updateEstimate(); };
  const generationControls = draft.generationPreset ? [node("p", { class: "muted", text: "Generation preset을 선택했으므로 직접 모델 설정은 요청에 함께 보내지 않습니다." })] : [
    field("Diffusion model", resourceChoice(draft.generation.diffusion_model, resources.diffusion_models, change((value) => { draft.generation.diffusion_model = value; }), "모델"), state.resourcesError || "Core에 등록된 모델만 선택할 수 있습니다."),
    field("Text encoder", resourceChoice(draft.generation.text_encoder, resources.text_encoders, change((value) => { draft.generation.text_encoder = value; }), "Encoder")),
    field("VAE", resourceChoice(draft.generation.vae, resources.vaes, change((value) => { draft.generation.vae = value; }), "VAE")),
    field("너비", textInput(draft.generation.width, change((value) => { draft.generation.width = value; }), { type: "number", min: 256, max: 1920, step: 16 })),
    field("높이", textInput(draft.generation.height, change((value) => { draft.generation.height = value; }), { type: "number", min: 256, max: 1920, step: 16 })),
    seedField(draft.generation.seed, change((value) => { draft.generation.seed = value; })),
    field("Steps", textInput(draft.generation.steps, change((value) => { draft.generation.steps = value; }), { type: "number", min: 1, max: 100, step: 1 })),
    field("CFG", textInput(draft.generation.cfg, change((value) => { draft.generation.cfg = value; }), { type: "number", min: 0, max: 20, step: 0.1 })),
    field("Sampler", resourceChoice(draft.generation.sampler, resources.samplers, change((value) => { draft.generation.sampler = value; }), "Sampler")),
    field("Scheduler", resourceChoice(draft.generation.scheduler, resources.schedulers, change((value) => { draft.generation.scheduler = value; }), "Scheduler")),
  ];
  const presetSelect = node("select", { onchange: (event) => { draft.generationPreset = event.target.value; invalidatePreview(draft); rerender(); } }, [selectedOption("", "직접 생성 설정", !draft.generationPreset),
    ...state.presets.generation.map((item) => selectedOption(`${item.id}@${item.revision}`, `${item.name} (r${item.revision})`, draft.generationPreset === `${item.id}@${item.revision}`))]);
  const loraRows = draft.loras.map((item, index) => node("div", { class: "row" }, [
    node("input", { type: "text", value: item.name, list: "production-known-anima-loras", placeholder: "등록된 LoRA 파일명",
      oninput: (event) => change((value) => { item.name = value; })(event.target.value) }),
    textInput(item.strength, change((value) => { item.strength = value; }), { type: "number", min: -100, max: 100, step: 0.05 }),
    button("−", () => { draft.loras.splice(index, 1); invalidatePreview(draft); rerender(); }, { secondary: true }),
  ]));
  const postprocess = node("div", { class: "grid" }, [
    field("후처리", node("select", { onchange: (event) => { draft.postprocessMode = event.target.value; draft.postprocessPreset = ""; invalidatePreview(draft); rerender(); } }, [
      selectedOption("default", "기본 사용: 최종 1.5배, WebP", draft.postprocessMode === "default" && !draft.postprocessPreset),
      selectedOption("none", "후처리 없음: {}", draft.postprocessMode === "none"),
      selectedOption("direct", "직접 Upscale/Encode 설정", draft.postprocessMode === "direct"),
    ]), "기본은 요청에서 postprocess를 생략합니다."),
    field("후처리 Preset", node("select", { onchange: (event) => { draft.postprocessPreset = event.target.value; invalidatePreview(draft); rerender(); } }, [selectedOption("", "선택 안 함", !draft.postprocessPreset),
      ...state.presets.postprocess.map((item) => selectedOption(`${item.id}@${item.revision}`, `${item.name} (r${item.revision})`, draft.postprocessPreset === `${item.id}@${item.revision}`))])),
    draft.postprocessMode === "direct" && !draft.postprocessPreset ? field("Upscale model", resourceChoice(draft.upscaleModel, resources.upscale_models, change((value) => { draft.upscaleModel = value; }), "Upscale model")) : null,
    draft.postprocessMode === "direct" && !draft.postprocessPreset ? field("최종 배율", textInput(draft.upscaleScale, change((value) => { draft.upscaleScale = value; }), { type: "number", min: 0.01, step: 0.1 })) : null,
    (() => { estimateLabel = node("p", {class: "muted"}); updateEstimate(); return estimateLabel; })(),
    draft.postprocessMode === "direct" && !draft.postprocessPreset ? field("WebP 출력", node("input", { type: "checkbox", checked: draft.webpEnabled, onchange: (event) => { draft.webpEnabled = event.target.checked; invalidatePreview(draft); } })) : null,
    draft.postprocessMode === "direct" && !draft.postprocessPreset ? field("WebP 품질", textInput(draft.webpQuality, change((value) => { draft.webpQuality = value; }), { type: "number", min: 1, max: 100, step: 1 })) : null,
  ]);
  const validation = node("div", { class: "grid" }, [
    field("검사", node("select", {onchange: (event) => { draft.validationMode = event.target.value; draft.validationEnabled = event.target.value !== "generation"; invalidatePreview(draft); rerender(); }}, [selectedOption("generation", "검사 없이 생성", draft.validationMode === "generation"), selectedOption("single", "Single 검사", draft.validationMode === "single"), selectedOption("single-group", "Single + 묶음 검사", draft.validationMode === "single-group")]), "검사 없이 생성한 결과는 통과가 아니라 미검사 상태입니다."),
    (draft.validationMode === "single" || draft.validationMode === "single-group") ? field("Single Profile", choice(draft.validationProfile, state.presets.profiles, (value) => { draft.validationProfile = value; invalidatePreview(draft); }), "등록된 설정만 선택합니다.") : null,
    (draft.validationMode === "single" || draft.validationMode === "single-group") ? field("Single Provider", choice(draft.validationProvider, state.presets.providers, (value) => { draft.validationProvider = value; invalidatePreview(draft); })) : null,
    draft.validationMode === "single-group" ? field("묶음 검사 Profile", choice(draft.groupValidationProfile, state.presets.groupProfiles || [], (value) => { draft.groupValidationProfile = value; invalidatePreview(draft); })) : null,
    draft.validationMode === "single-group" ? field("묶음 검사 Provider", choice(draft.groupValidationProvider, state.presets.providers, (value) => { draft.groupValidationProvider = value; invalidatePreview(draft); })) : null,
  ]);
  const consistencyMethods = consistencyMethodChoices(resources.consistency_methods);
  const selectedMethod = consistencyMethods.find((method) => method.id === draft.consistencyMethod) || null;
  const applyMethod = (methodId) => {
    draft.consistencyMethod = methodId;
    const method = consistencyMethods.find((item) => item.id === methodId);
    draft.consistencyParams = method ? consistencyFormValues(method.params, draft.consistencyParams).values : {};
    invalidatePreview(draft, true); updateEstimate(); rerender();
  };
  const consistencyParamFields = () => {
    if (!selectedMethod) return [];
    const { values, warnings } = consistencyFormValues(selectedMethod.params, draft.consistencyParams);
    draft.consistencyParams = values;
    return Object.entries(selectedMethod.params).map(([key, spec]) => {
      const warn = warnings.includes(key);
      const control = spec.type === "boolean"
        ? node("input", { type: "checkbox", checked: values[key], onchange: (event) => { draft.consistencyParams[key] = event.target.checked; invalidatePreview(draft, true); } })
        : textInput(values[key], change((value) => { draft.consistencyParams[key] = value; }), { type: "number", min: spec.min, max: spec.max, step: 0.05 });
      return field(key, control, warn ? `경고: ${spec.warn_below} 미만은 의상 색이 흔들릴 수 있습니다.` : (spec.min !== undefined ? `허용 범위 ${spec.min}~${spec.max}` : ""));
    });
  };
  const consistencyPanel = node("div", { class: "grid" }, [
    field("일관성 방식", node("select", { onchange: (event) => applyMethod(event.target.value) }, [
      selectedOption("", "기본값 사용 (참조 세트가 유효하면 Core가 자동 적용)", !draft.consistencyMethod),
      ...consistencyMethods.map((method) => node("option", { value: method.id, selected: draft.consistencyMethod === method.id ? "" : null, disabled: method.available ? null : "", text: `${method.id}${method.available ? "" : ` (사용 불가: ${method.reason || "미등록"})`}` })),
    ]), consistencyMethods.length ? "" : "Generation 자원 목록을 아직 불러오지 못했습니다."),
    ...consistencyParamFields(),
  ]);
  const directSettings = draft.generationPreset ? null : node("details", { class: "production-direct-settings", open: "" }, [
    node("summary", { text: "직접 생성 설정" }), node("div", { class: "grid" }, generationControls),
    node("h3", { text: "LoRA" }), node("p", { class: "muted", text: "행 순서대로 적용합니다. 설치 확인된 Anima LoRA를 제안하며, 다른 등록 파일명도 직접 입력할 수 있습니다." }),
    node("datalist", { id: "production-known-anima-loras" }, (resources.loras || []).map((name) => node("option", { value: name }))), ...loraRows,
    button("+ LoRA", () => { draft.loras.push({ name: "", strength: 1 }); invalidatePreview(draft); rerender(); }, { secondary: true }),
  ]);
  timeEstimateLabel = node("p", { class: "muted" }); updateEstimate();
  return node("section", { class: "panel" }, [node("h2", { text: "생성 설정" }), field("생성 Preset", presetSelect),
    draft.generationPreset ? node("p", { class: "muted", text: "선택한 Preset의 고정 설정을 사용합니다." }) : directSettings,
    node("h3", { text: "일관성(참조 이미지)" }), consistencyPanel, timeEstimateLabel,
    node("h3", { text: "후처리" }), postprocess, node("h3", { text: "검사" }), validation]);
}

function choice(value, items, onChange) {
  return node("select", { onchange: (event) => onChange(event.target.value) }, [selectedOption("", "선택", !value),
    ...items.map((item) => selectedOption(item.profile_id || item.provider_id || item.id, `${item.name || item.profile_id || item.provider_id} (r${item.revision})`, value === (item.profile_id || item.provider_id || item.id)))]);
}

/** Query parameters for the read-only production fragment picker.
 * Selection is deliberately kept in the draft, rather than in this query,
 * so changing category, search text, or page cannot drop a chosen fragment.
 */
export function fragmentPickerQuery(state) {
  return fragmentListPath({query: state.fragmentSearch, categoryId: state.fragmentCategoryId,
    archived: false, limit: state.fragmentLimit, offset: state.fragmentOffset});
}

function directCompositionFields(draft, update) {
  return node("div", { class: "grid" }, [
    field("구도 Prompt", textArea(draft.framingPrompt, update("framingPrompt"), "예: full body, white background\n또는 upper body, cowboy shot"), "쉼표나 줄바꿈으로 한 이미지의 구도를 조합합니다. 줄마다 별도 Task를 만들지 않습니다."),
    field("표정", textArea(draft.expression, update("expression"), "예: gentle smile")),
    field("자세·동작", textArea(draft.action, update("action"), "예: standing, one hand raised")),
    field("상황", textArea(draft.situation, update("situation"), "예: studio portrait")),
    field("상의 포함", node("input", { type: "checkbox", checked: draft.include.upper, onchange: (event) => { draft.include.upper = event.target.checked; invalidatePreview(draft); } })),
    field("하의 포함", node("input", { type: "checkbox", checked: draft.include.lower, onchange: (event) => { draft.include.lower = event.target.checked; invalidatePreview(draft); } }), "상반신 구도에서 하의를 켜면 Core가 구도와의 충돌을 검사합니다. 전신으로 바꾸면 하의를 명시적으로 켜세요."),
    field("액세서리 포함", node("input", { type: "checkbox", checked: draft.include.accessories, onchange: (event) => { draft.include.accessories = event.target.checked; invalidatePreview(draft); } })),
    field("손 포함", node("input", { type: "checkbox", checked: draft.include.hands !== false, onchange: (event) => { draft.include.hands = event.target.checked; invalidatePreview(draft); } })),
  ]);
}

function fragmentPicker(state, rerender) {
  const draft = state.draft;
  const selections = new Set(draft.fragmentSelections.map((value) => fragmentKey(value)));
  const commonSelections = new Set((draft.commonFragmentSelections || []).map((value) => fragmentKey(value)));
  const setMode = (mode) => { draft.compositionMode = mode; invalidatePreview(draft, true); rerender(); };
  const toggle = (item, checked, common = false) => {
    const fieldName = common ? "commonFragmentSelections" : "fragmentSelections";
    draft[fieldName] = preserveSelection(draft[fieldName] || [], item, checked);
    invalidatePreview(draft, true); rerender();
  };
  const selectedCount = draft.fragmentSelections.length;
  const commonCount = (draft.commonFragmentSelections || []).length;
  const mode = node("select", { onchange: (event) => setMode(event.target.value) }, [
    selectedOption("fragment", "전역 조각 라이브러리", draft.compositionMode === "fragment"),
    selectedOption("direct", "고급 단일 직접 입력", draft.compositionMode === "direct"),
  ]);
  if (draft.compositionMode === "direct") return node("div", { class: "grid" }, [field("구성 방식", mode), directCompositionFields(draft, (name) => (value) => { draft[name] = value; invalidatePreview(draft, true); })]);
  const rows = (common) => state.fragments.filter((item) => Boolean(item.common) === common).map((item) => {
    const ref = fragmentKey(item);
    const categoryName = state.fragmentCategories.find((category) => category.id === item.category_id)?.name || "미분류";
    return node("li", { class: "row production-fragment-row" }, [
      node("input", { type: "checkbox", checked: (common ? commonSelections : selections).has(ref), "aria-label": `${item.name} 조각 선택`, onchange: (event) => toggle(item, event.target.checked, common) }),
      node("span", { text: common ? item.name : fragmentLabel(item) }),
      node("small", { class: "muted", text: common ? categoryName : `${categoryName} · ${fragmentIncludeSummary(item.include)}` }),
    ]);
  });
  const categoryOptions = state.fragmentCategories;
  const filter = node("div", { class: "production-fragment-filter grid" }, [
    field("카테고리", node("select", { onchange: (event) => { state.fragmentCategoryId = event.target.value; state.fragmentOffset = 0; rerender(true); } }, [selectedOption("", "전체", !state.fragmentCategoryId), ...categoryOptions.map((item) => selectedOption(item.id, item.name, state.fragmentCategoryId === item.id))])),
    field("조각 찾기", textInput(state.fragmentSearch, (value) => { state.fragmentSearch = value; }, { placeholder: "번호 또는 이름" })),
    button("검색", () => { state.fragmentOffset = 0; rerender(true); }, { secondary: true }),
  ]);
  const chosen = node("p", { class: "muted production-fragment-selection", text: selectedCount ? `선택함: ${selectedCount}개 조각` : "선택한 조각이 없습니다." });
  return node("div", { class: "production-fragment-picker" }, [field("구성 방식", mode),
    node("p", { class: "muted", text: "조각은 별도 ‘조각’ 화면에서 관리합니다. 여기서는 이번 제작에 사용할 조각만 고릅니다." }),
    button("조각 관리 화면 열기", () => state.navigate?.("fragments"), {secondary: true}),
    filter, node("h3", {text: "이미지별 조각"}), node("ul", { class: "fragment-list", "aria-label": "이미지별 전역 조각 목록" }, rows(false)),
    node("h3", {text: "공통 적용 프롬프트"}), node("p", {class: "muted", text: "선택한 모든 이미지에 본문만 더하며 의상 포함 여부를 바꾸지 않습니다."}), node("ul", { class: "fragment-list", "aria-label": "공통 적용 프롬프트 목록" }, rows(true)),
    node("div", { class: "toolbar" }, [button("이전", () => { state.fragmentOffset = Math.max(0, state.fragmentOffset - state.fragmentLimit); rerender(true); }, { secondary: true, disabled: state.fragmentOffset === 0 }),
      button("다음", () => { state.fragmentOffset += state.fragmentLimit; rerender(true); }, { secondary: true, disabled: state.fragmentOffset + state.fragmentLimit >= state.fragmentTotal })]),
    node("p", { class: "muted", text: `조각 ${state.fragmentTotal ? state.fragmentOffset + 1 : 0}–${Math.min(state.fragmentOffset + state.fragmentLimit, state.fragmentTotal)} / ${state.fragmentTotal}` }), chosen,
    commonCount ? node("p", {class: "muted", text: `공통 적용: ${commonCount}개`}) : null,
    node("p", { class: "muted", text: selectedCount === 1 ? "조각 1개를 골랐습니다. 아래에서 단일 미리보기를 확인할 수 있습니다." : selectedCount ? `조각 ${selectedCount}개를 골랐습니다. 복수 조각은 아래 제작 계획으로 만듭니다.` : "조각을 고르면 단일 미리보기 또는 복수 제작 계획을 만들 수 있습니다." }),
  ]);
}

async function refreshProductionPlan(state, api) {
  const requestedPlanId = state.productionPlanId;
  if (!requestedPlanId) return;
  const plan = await api.get(`/v1/production-plans/${requestedPlanId}`);
  if (state.productionPlanId !== requestedPlanId) return;
  const [items, comparisons] = await Promise.all([
    api.get(query(`/v1/production-plans/${plan.id}/items`, { limit: 20, offset: state.planItemsOffset })),
    api.get(`/v1/production-plans/${plan.id}/comparisons`),
  ]);
  if (state.productionPlanId !== requestedPlanId) return;
  const itemValues = collection(items);
  const fragmentIds = [...new Set(itemValues.map((item) => item.fragment?.id).filter(Boolean))];
  const fragmentResults = await Promise.allSettled(fragmentIds.map((id) => api.get(`/v1/prompt-fragments/${id}`)));
  if (state.productionPlanId !== requestedPlanId) return;
  const fragments = Object.fromEntries(fragmentResults.flatMap((result, index) =>
    result.status === "fulfilled" ? [[fragmentIds[index], result.value]] : []));
  const group = plan.state === "awaiting_reference_confirmation" ? await api.get(`/v1/groups/${plan.group_id}`) : null;
  if (state.productionPlanId !== requestedPlanId) return;
  state.productionPlan = plan;
  const pendingEntry = state.draft.multiPlanRequests?.[plan.group_id];
  if (pendingEntry?.plan?.id === plan.id) pendingEntry.plan = plan;
  if (state.multiProductionPlans?.[plan.group_id]?.id === plan.id) state.multiProductionPlans[plan.group_id] = plan;
  state.productionPlanGroup = group;
  state.productionPlanItems = itemValues;
  state.productionPlanItemsTotal = Number.isInteger(items?.total) ? items.total : state.productionPlanItems.length;
  state.productionPlanComparisons = collection(comparisons);
  state.productionPlanFragments = fragments;
}

function planSetupPanel(state, api, rerender, notify) {
  const draft = state.draft;
  if (draft.fragmentSelections.length < 2) return null;
  const create = async () => {
    try {
      draft.planRequest ||= buildProductionPlanBody(state);
      draft.planKey ||= makeKey();
      draft.planPending = true; rerender();
      const plan = await submitProductionPlan(api, draft.planRequest, draft.planKey);
      state.productionPlanId = plan.id; state.productionPlan = plan; draft.planPending = false;
      notify("고정 제작 계획을 만들었습니다. 시작 전에는 GPU 작업을 실행하지 않습니다.");
      await refreshProductionPlan(state, api); rerender();
    } catch (error) { state.error = requestError(error); draft.planPending = false; rerender(); }
  };
  const reset = () => { draft.planKey = null; draft.planRequest = null; invalidatePreview(draft); rerender(); };
  return node("section", { class: "panel" }, [node("h3", { text: "복수 조각 제작 계획" }),
    node("p", { class: "muted", text: `선택한 ${draft.fragmentSelections.length}개 조각을 고정한 뒤, 페이지별 Prompt를 확인하고 별도로 시작합니다.` }),
    field("각 이미지 Single 검사", node("input", { type: "checkbox", checked: draft.validationEnabled, onchange: (event) => { draft.validationEnabled = event.target.checked; invalidatePreview(draft); rerender(); } }), "제작 계획에는 필수입니다."),
    node("div", { class: "grid" }, [
      field("Single Profile", choice(draft.validationProfile, state.presets.profiles, (value) => { draft.validationProfile = value; invalidatePreview(draft); })),
      field("Single Provider", choice(draft.validationProvider, state.presets.providers, (value) => { draft.validationProvider = value; invalidatePreview(draft); })),
      field("묶음 검사 Profile", choice(draft.groupValidationProfile, state.presets.groupProfiles || [], (value) => { draft.groupValidationProfile = value; invalidatePreview(draft); })),
      field("묶음 검사 Provider", choice(draft.groupValidationProvider, state.presets.providers, (value) => { draft.groupValidationProvider = value; invalidatePreview(draft); })),
    ]),
    node("div", { class: "toolbar" }, [button(draft.planKey ? "같은 키로 계획 요청 재시도" : "고정 계획 미리보기", create, { disabled: draft.planPending }),
      draft.planKey ? button("새 계획 입력으로 초기화", reset, { secondary: true }) : null]),
    draft.planKey ? node("p", { class: "muted", text: "응답 유실 시에는 같은 키와 동일한 고정 요청만 다시 보냅니다." }) : null,
  ]);
}

function groupLabel(state, group) {
  const work = entityById(state.catalog.works, group.work_id);
  const character = entityById(state.catalog.characters, group.character_id);
  const outfit = entityById(state.catalog.outfits, group.outfit_id);
  const names = [work?.name, character?.name, outfit?.name].filter(Boolean);
  return `${names.length ? names.join(" / ") : "이름을 불러오는 중"} · 고정본 r${group.outfit_revision}`;
}

function multiPlanSetupPanel(state, api, rerender, notify) {
  const draft = state.draft;
  const selected = new Set(state.selection.groupIds);
  const groups = state.catalog.groups;
  const toggle = (groupId, checked) => {
    if (checked) selected.add(groupId); else selected.delete(groupId);
    state.selection.groupIds = [...selected];
    rerender();
  };
  const reset = () => { draft.multiPlanRequests = {}; state.multiProductionPlans = {}; rerender(); };
  const create = async () => {
    try {
      const requests = buildProductionPlanRequests(state);
      freezeMultiProductionPlanRequests(state);
      draft.multiPlanPending = true; rerender();
      for (const groupId of Object.keys(requests)) {
        const entry = draft.multiPlanRequests[groupId];
        try {
          const plan = await submitProductionPlan(api, entry.request, entry.key);
          entry.plan = plan; entry.error = null;
          state.multiProductionPlans[groupId] = plan;
        } catch (error) { entry.error = requestError(error); }
      }
      const failed = Object.keys(requests).filter((groupId) => draft.multiPlanRequests[groupId].error).length;
      notify(failed ? `${failed}개 계획은 같은 키로 다시 요청할 수 있습니다.` : "모든 고정 제작 계획을 만들었습니다. 아직 GPU 작업은 시작되지 않았습니다.", Boolean(failed));
    } catch (error) { state.error = requestError(error); }
    finally { draft.multiPlanPending = false; rerender(); }
  };
  const entries = state.selection.groupIds.map((groupId) => {
    const group = entityById(groups, groupId);
    const entry = draft.multiPlanRequests[groupId];
    const plan = state.multiProductionPlans[groupId] || entry?.plan;
    return node("li", { class: "row" }, [node("span", { text: group ? groupLabel(state, group) : groupId }),
      plan ? node("span", { class: "badge", text: plan.state || "draft" }) : null,
      entry?.error ? node("span", { class: "error", text: entry.error }) : null,
      plan ? button("계획 미리보기", () => { clearProductionPlanSelection(state); state.productionPlanId = plan.id; state.productionPlan = plan; rerender(true); }, { secondary: true }) : null,
    ]);
  });
  return node("details", { class: "panel production-multi-plan", open: state.multiCatalogOpen ? "" : null, ontoggle: (event) => { if (event.currentTarget.open && !state.multiCatalogOpen) { state.multiCatalogOpen = true; rerender(true); } } }, [node("summary", { text: "여러 캐릭터·의상에 같은 조각 적용" }),
    node("p", { class: "muted", text: "선택한 각 고정 그룹에 같은 전역 조각과 생성 설정을 적용합니다. 그룹마다 별도 계획을 고정한 뒤 Prompt를 확인하고 시작합니다." }),
    node("ul", { class: "fragment-list" }, groups.map((group) => node("li", { class: "row" }, [
      node("input", { type: "checkbox", checked: selected.has(group.id), "aria-label": `${groupLabel(state, group)} 그룹 선택`, onchange: (event) => toggle(group.id, event.target.checked) }),
      node("span", { text: groupLabel(state, group) }),
    ]))),
    groups.length ? null : node("p", { class: "muted", text: "사용 가능한 고정 그룹이 없습니다." }),
    draft.fragmentSelections.length < 1 ? node("p", { class: "muted", text: "여러 그룹 계획에는 전역 조각을 한 개 이상 선택하세요." }) : null,
    !state.selection.outfitId || draft.fragmentSelections.length < 2 ? node("div", { class: "grid" }, [
      field("계획 Single 검사 사용", node("input", { type: "checkbox", checked: draft.validationEnabled, onchange: (event) => { draft.validationEnabled = event.target.checked; invalidatePreview(draft); rerender(); } })),
      field("계획 Single Profile", choice(draft.validationProfile, state.presets.profiles, (value) => { draft.validationProfile = value; invalidatePreview(draft); })),
      field("계획 Single Provider", choice(draft.validationProvider, state.presets.providers, (value) => { draft.validationProvider = value; invalidatePreview(draft); })),
      field("계획 묶음 Profile", choice(draft.groupValidationProfile, state.presets.groupProfiles || [], (value) => { draft.groupValidationProfile = value; invalidatePreview(draft); })),
      field("계획 묶음 Provider", choice(draft.groupValidationProvider, state.presets.providers, (value) => { draft.groupValidationProvider = value; invalidatePreview(draft); })),
    ]) : null,
    node("div", { class: "toolbar" }, [button("선택 그룹의 고정 계획 만들기", create, { disabled: draft.multiPlanPending || !state.selection.groupIds.length || draft.fragmentSelections.length < 1 }),
      Object.keys(draft.multiPlanRequests).length ? button("새 계획 입력으로 초기화", reset, { secondary: true }) : null]),
    entries.length ? node("div", {}, [node("h4", { text: "계획 접수 결과" }), node("ul", { class: "fragment-list" }, entries)]) : null,
    Object.keys(draft.multiPlanRequests).length ? node("p", { class: "muted", text: "응답 유실·부분 실패는 그룹별로 보관한 동일 요청과 멱등성 키로 다시 접수합니다." }) : null,
  ]);
}

export function clearProductionPlanSelection(state) {
  state.productionPlanId = null;
  state.productionPlan = null;
  state.productionPlanGroup = null;
  state.productionPlanItems = [];
  state.productionPlanItemsTotal = 0;
  state.productionPlanComparisons = [];
  state.productionPlanFragments = {};
  state.planItemsOffset = 0;
  if (typeof state.selectedId === "string" && state.selectedId.startsWith("plan:")) state.selectedId = null;
}

function productionPlanPanel(state, api, rerender, notify) {
  const plan = state.productionPlan;
  if (!plan) return node("section", { class: "panel" }, [node("h2", { text: "제작 계획" }), node("p", { class: "muted", text: "계획 정보를 불러오는 중입니다." })]);
  const refresh = async () => { try { await refreshProductionPlan(state, api); rerender(); } catch (error) { state.error = requestError(error); rerender(); } };
  const start = async () => {
    try { state.productionPlan = await api.post(`/v1/production-plans/${plan.id}/start`, { plan_hash: plan.plan_hash }); await refreshProductionPlan(state, api); notify("고정 계획 실행을 시작했습니다."); rerender(); }
    catch (error) { state.error = requestError(error); rerender(); }
  };
  const cancel = async () => {
    try { state.productionPlan = await api.post(`/v1/production-plans/${plan.id}/cancel`, {}); await refreshProductionPlan(state, api); notify("계획 취소를 요청했습니다."); rerender(); }
    catch (error) { state.error = requestError(error); rerender(); }
  };
  const confirmReference = async () => {
    const revision = state.productionPlanGroup?.reference?.revision;
    try {
      if (!Number.isInteger(revision)) throw new Error("Gallery에서 현재 그룹 기준을 먼저 선택하세요.");
      state.planConfirmKey ||= makeKey();
      state.productionPlan = await api.post(`/v1/production-plans/${plan.id}/confirm-reference`, { reference_revision: revision }, state.planConfirmKey);
      await refreshProductionPlan(state, api); notify("현재 기준 revision으로 묶음 검사를 다시 시작했습니다."); rerender();
    } catch (error) { state.error = requestError(error); rerender(); }
  };
  const prev = () => { state.planItemsOffset = Math.max(0, state.planItemsOffset - 20); refresh(); };
  const next = () => { state.planItemsOffset += 20; refresh(); };
  const items = (state.productionPlanItems || []).map((item) => {
    const fragment = state.productionPlanFragments?.[item.fragment?.id];
    const itemLabel = fragment ? `조각 ${fragmentLabel(fragment)}` : "조각 번호를 불러오는 중";
    return node("li", {}, [node("details", {}, [
    node("summary", { text: `${itemLabel} · 항목 ${item.index + 1} · ${item.state}` }),
    node("p", { class: "prompt-preview-text", text: `Positive: ${item.snapshot?.generation_inputs?.positive_prompt || ""}` }),
    node("p", { class: "prompt-preview-text", text: `Negative: ${item.snapshot?.generation_inputs?.negative_prompt || ""}` }),
    Number.isSafeInteger(item.snapshot?.generation_inputs?.seed) ? node("p", {class: "muted", text: `실제 Seed: ${item.snapshot.generation_inputs.seed}`}) : null,
    node("details", { class: "production-advanced" }, [node("summary", { text: "고정된 이미지별·공통 조각과 포함 정보" }), node("pre", { text: JSON.stringify({ fragment: item.fragment, common_fragments: item.snapshot?.common_fragments || [], inclusion: item.snapshot?.inclusion, error: item.error }, null, 2) })]),
    ])]);
  });
  const terminal = ["completed", "failed", "cancelled", "insufficient_images"].includes(plan.state);
  return node("section", { class: "panel" }, [node("h2", { text: "고정 제작 계획" }),
    node("p", { class: "badge", text: plan.state }), node("p", { text: `${plan.total}개 조각 · 결과: ${plan.outcome || "아직 없음"}` }),
    node("details", { class: "production-advanced" }, [node("summary", { text: "고급 정보" }), node("code", { text: `계획 ID: ${plan.id}` })]),
    node("pre", { text: JSON.stringify({ counts: plan.counts || {}, error: plan.error || null }, null, 2) }),
    plan.state === "awaiting_reference_confirmation" ? node("p", { class: "error", text: "현재 그룹 기준이 바뀌었습니다. Gallery에서 기준을 명시적으로 선택한 뒤 현재 revision을 확인하고 재개하세요." }) : null,
    node("div", { class: "toolbar" }, [button("새 제작으로 돌아가기", () => { clearProductionPlanSelection(state); rerender(true); }, { secondary: true }),
      button("상태 새로고침", refresh, { secondary: true }),
      plan.state === "draft" ? button("페이지별 Prompt 확인 후 시작", start) : null,
      plan.state === "awaiting_reference_confirmation" ? button("Gallery에서 기준 선택", () => state.navigate?.("gallery", plan.group_id), { secondary: true }) : null,
      plan.state === "awaiting_reference_confirmation" ? button(`현재 기준 r${state.productionPlanGroup?.reference?.revision ?? "?"}로 재개`, confirmReference, { disabled: !Number.isInteger(state.productionPlanGroup?.reference?.revision) }) : null,
      !terminal && plan.state !== "cancellation_pending" ? button("계획 취소", cancel, { secondary: true }) : null]),
    node("h3", { text: "계획 항목" }), node("ul", {}, items),
    node("div", { class: "toolbar" }, [button("이전", prev, { secondary: true, disabled: state.planItemsOffset === 0 }),
      button("다음", next, { secondary: true, disabled: state.planItemsOffset + 20 >= state.productionPlanItemsTotal })]),
    node("p", { class: "muted", text: `${state.productionPlanItemsTotal ? state.planItemsOffset + 1 : 0}–${Math.min(state.planItemsOffset + 20, state.productionPlanItemsTotal)} / ${state.productionPlanItemsTotal}` }),
    node("h3", { text: "묶음 검사" }), node("pre", { text: JSON.stringify(state.productionPlanComparisons || [], null, 2) }),
  ]);
}

function groupPanel(state, api, rerender, notify) {
  if (state.productionPlanId) return productionPlanPanel(state, api, rerender, notify);
  const outfit = entityById(state.entities.outfits, state.selection.outfitId);
  if (!outfit) return node("section", { class: "panel production-generation" }, [node("h2", { text: "조각 선택과 생성 확인" }),
    node("p", { class: "muted", text: "단일 생성은 의상을 선택한 뒤 고정 그룹을 만듭니다. 먼저 준비 단계에서 캐릭터와 의상을 고르세요." }),
    button("캐릭터·의상 준비로 이동", () => { state.productionSection = "prepare"; state.mobilePreparationPanel = "classification"; rerender(); }, { secondary: true }),
    fragmentPicker(state, rerender), multiPlanSetupPanel(state, api, rerender, notify)]);
  const createGroup = async () => {
    try {
      const group = await api.post("/v1/groups", { outfit_id: outfit.id });
      state.selection.groupId = group.id;
      state.catalogLoaded = false;
      delete state.loaded?.groups?.[outfit.id];
      notify("새 고정 그룹을 만들었습니다.");
      await rerender(true);
    } catch (error) { state.error = requestError(error); rerender(); }
  };
  const groups = state.entities.groups;
  const groupList = node("select", { onchange: (event) => { state.selection.groupId = event.target.value || null; invalidatePreview(state.draft); rerender(); } }, [selectedOption("", "고정 그룹 선택", !state.selection.groupId),
    ...groups.map((item) => selectedOption(item.id, `고정본 r${item.outfit_revision}`, state.selection.groupId === item.id))]);
  const current = groups.find((item) => item.id === state.selection.groupId);
  const stale = current && current.outfit_revision !== outfit.revision;
  const draft = state.draft;
  const preview = async () => {
    let request;
    try {
      request = buildGenerationBody(state);
      const previewRevision = Number(draft.previewRevision) || 0;
      draft.previewing = true; rerender();
      const result = await api.post("/v1/prompts/preview", request);
      if (previewRequestIsCurrent(state, request, previewRevision)) {
        draft.preview = result;
        notify("최신 Core 미리보기를 받았습니다.");
      }
    } catch (error) { state.error = requestError(error); }
    finally { draft.previewing = false; rerender(); }
  };
  const submit = async () => {
    try {
      if (!draft.preview?.preview_hash) throw new Error("먼저 최신 미리보기를 확인하세요.");
      draft.pending = true; draft.pendingKey ||= makeKey(); rerender();
      const result = await api.post("/v1/tasks", { ...buildGenerationBody(state), preview_hash: draft.preview.preview_hash }, draft.pendingKey);
      draft.task = result; draft.pending = false; draft.pendingKey = null;
      notify("생성 작업을 접수했습니다.");
    } catch (error) { state.error = requestError(error); draft.pending = false; }
    finally { rerender(); }
  };
  const recover = async () => {
    try {
      if (!draft.pendingKey) return;
      const task = await api.request("GET", "/v1/tasks/by-key", undefined, draft.pendingKey);
      draft.task = task; draft.pendingKey = null; draft.pending = false;
      notify("기존 멱등성 키의 작업을 확인했습니다.");
    } catch (error) { state.error = requestError(error); }
    finally { rerender(); }
  };
  return node("section", { class: "panel production-generation" }, [node("h2", { text: "조각 선택과 생성 확인" }), node("div", { class: "row" }, [field("생성에 쓸 고정 그룹", groupList), button("현재 의상으로 새 고정본 만들기", createGroup, { secondary: true })]),
    node("p", { class: "muted", text: "현재 의상 원본을 저장해도, 이미 만든 고정 그룹과 과거 결과는 바뀌지 않습니다." }),
    stale ? node("p", { class: "error", text: "선택한 것은 현재 의상과 다른 과거 고정본입니다. 이 구성을 계속 쓰거나 현재 의상으로 새 고정본을 만드세요." }) : null,
    fragmentPicker(state, rerender),
    planSetupPanel(state, api, rerender, notify),
    multiPlanSetupPanel(state, api, rerender, notify),
    node("div", { class: "toolbar" }, [button("미리보기 갱신", preview, { disabled: draft.previewing }), button("명시적으로 Task 접수", submit, { disabled: draft.pending || !draft.preview?.preview_hash }),
      draft.pendingKey ? button("응답 유실 복구", recover, { secondary: true }) : null]),
    previewView(draft.preview), draft.pendingKey ? node("details", { class: "production-advanced" }, [node("summary", { text: "응답 유실 복구 정보" }), node("code", { text: draft.pendingKey })]) : null,
    draft.task ? node("div", { class: "row" }, [node("span", { class: "badge", text: draft.task.state || "accepted" }), button("작업 현황 열기", () => ctxNavigate(state, "jobs", draft.task.id), { secondary: true })]) : null]);
}

function ctxNavigate(state, tab, id) {
  state.navigate?.(tab, id);
}

function previewView(preview) {
  if (!preview) return node("p", { class: "muted", text: "미리보기를 갱신하면 Core가 합성한 Prompt와 포함 사유를 표시합니다." });
  const generation = preview.snapshot?.generation_inputs || {};
  const inclusion = inclusionLabels(preview.snapshot?.inclusion);
  return node("details", { open: "" }, [node("summary", { text: "Core 미리보기" }),
    node("p", { class: "prompt-preview-text", text: `Positive: ${generation.positive_prompt || ""}` }), node("p", { class: "prompt-preview-text", text: `Negative: ${generation.negative_prompt || ""}` }), inclusion.length ? node("p", {class: "muted", text: inclusion.join(" · ")}) : null,
    node("pre", { text: JSON.stringify(preview.snapshot?.inclusion || {}, null, 2) })]);
}

function treePanel(state, rerender) {
  const selection = state.selection;
  const blockDirty = () => {
    if (!state.dirty && !state.entityPending) return false;
    state.error = state.entityPending ? "저장 또는 보관 요청이 끝날 때까지 기다리세요." : "미저장 원본을 먼저 저장하거나 취소하세요.";
    rerender(); return true;
  };
  const select = (item) => {
    if (blockDirty()) return;
    state.archiveConfirm = null;
    const kind = `${item.type}s`;
    if (kind === "works") {
      selection.workId = item.id; selection.characterId = null; selection.outfitId = null; selection.groupId = null;
    }
    if (kind === "characters") {
      selection.workId = item.parent_id; selection.characterId = item.id; selection.outfitId = null; selection.groupId = null;
    }
    if (kind === "outfits") {
      const character = entityById(state.entities.characters, item.parent_id);
      selection.characterId = item.parent_id; selection.workId = character?.parent_id || selection.workId;
      selection.outfitId = item.id; selection.groupId = null;
    }
    state.editor = {mode: "edit", kind, targetId: item.id, revision: item.revision, archived: Boolean(item.archived), migrationChoiceConfirmed: false,
      workId: selection.workId, characterId: selection.characterId,
      value: {...item, components: {...EMPTY_COMPONENTS, ...item.components}}};
    state.mobilePreparationPanel = "editor";
    rerender(true);
  };
  const create = (type, parent = null) => {
    if (blockDirty()) return;
    state.archiveConfirm = null;
    const kind = `${type}s`;
    const parentId = parent?.id || null;
    const workId = kind === "characters" ? parentId : kind === "outfits" ? parent?.parent_id : null;
    state.editor = {mode: "create", kind, targetId: null, parentId, workId, characterId: kind === "outfits" ? parentId : null,
      value: {name: "", parent_id: parentId, appearance_prompt: "", negative_prompt: "", check_features: [], components: {...EMPTY_COMPONENTS}}};
    state.mobilePreparationPanel = "editor";
    rerender();
  };
  const host = node("div", {class: "studio-tree-host"});
  queueMicrotask(() => {
    state.tree?.dispose?.();
    const items = [...state.entities.works, ...state.entities.characters, ...state.entities.outfits].map((item) => {
      const type = item.kind?.slice(0, -1) || item.type;
      const childrenLoaded = type === "work" ? Boolean(state.loaded?.characters?.[item.id]) : type === "character" ? Boolean(state.loaded?.outfits?.[item.id]) : true;
      return {...item, type, children_loaded: childrenLoaded};
    });
    const selectedId = selection.outfitId || selection.characterId || selection.workId;
    const expandedIds = new Set([...Object.entries(state.expanded.works).filter(([, value]) => value).map(([id]) => id), ...Object.entries(state.expanded.characters).filter(([, value]) => value).map(([id]) => id)]);
    const archive = async (item) => {
      if (blockDirty()) return;
      state.archiveConfirm = {kind: `${item.type}s`, id: item.id, revision: item.revision, archived: Boolean(item.archived), workId: item.type === "work" ? item.id : item.parent_id, characterId: item.type === "character" ? item.id : item.parent_id};
      rerender();
    };
    state.tree = mountStudioTree(host, {items, selectedId, expandedIds, onSelect: select, onEdit: select, onCreate: create,
      onArchive: archive, onExpandedChange: (next) => { if (blockDirty()) return; state.expanded.works = {}; state.expanded.characters = {}; for (const id of next) { if (entityById(state.entities.works, id)) state.expanded.works[id] = true; else state.expanded.characters[id] = true; } rerender(true); }});
  });
  return node("section", {class: "panel"}, [host]);
}

function archiveConfirmationPanel(state, rerender) {
  const target = state.archiveConfirm;
  if (!target) return null;
  const names = {works: "작품", characters: "캐릭터", outfits: "의상"};
  const confirm = async () => {
    if (state.entityPending) return;
    state.entityPending = true; rerender();
    try {
      const result = await state.api.patch(`/v1/${target.kind}/${target.id}`, {revision: target.revision, archived: !target.archived});
      if (target.kind === "works") state.loaded.works = false;
      if (target.kind === "characters") delete state.loaded?.characters?.[target.workId];
      if (target.kind === "outfits") delete state.loaded?.outfits?.[target.characterId];
      state.archiveConfirm = null; state.entityPending = false; state.dirty = false;
      if (state.editor?.mode === "edit" && state.editor.targetId === target.id && state.editor.kind === target.kind) {
        state.editor = {...state.editor, revision: result.revision, archived: Boolean(result.archived), value: {...result, components: {...EMPTY_COMPONENTS, ...result.components}}};
      }
      state.notify?.(target.archived ? "분류를 복원했습니다." : "분류를 보관했습니다. 기존 고정 그룹과 과거 이력은 유지됩니다.");
      await rerender(true);
    } catch (error) { state.entityPending = false; state.error = requestError(error); rerender(); }
  };
  return node("section", {class: "panel archive-confirmation", role: "alertdialog", "aria-label": "보관 확인"}, [
    node("h2", {text: target.archived ? `${names[target.kind]} 복원` : `${names[target.kind]} 보관`}),
    node("p", {text: target.archived ? "이 분류를 다시 사용할 수 있게 할까요?" : "이 분류를 보관할까요?"}),
    node("p", {class: "muted", text: "기존 고정 그룹과 과거 이력은 유지됩니다."}),
    node("div", {class: "toolbar"}, [button(target.archived ? "복원 확인" : "보관 확인", confirm, {disabled: state.entityPending}), button("취소", () => { if (!state.entityPending) { state.archiveConfirm = null; rerender(); } }, {secondary: true, disabled: state.entityPending})]),
  ]);
}
export async function loadProductionData(state, api, isCurrent = () => true) {
  const compose = state.productionSection === "compose" || Boolean(state.productionPlanId);
  state.loaded ||= {works: false, characters: {}, outfits: {}, compose: false, groups: {}};
  if (!state.loaded.works) {
    const works = await api.get("/v1/works?limit=200&offset=0"); if (!isCurrent()) return;
    state.entities.works = collection(works); state.loaded.works = true;
  }
  const workIds = [...new Set([state.selection.workId, ...Object.entries(state.expanded.works).filter(([, open]) => open).map(([id]) => id)].filter(Boolean))];
  const missingWorks = workIds.filter((id) => !state.loaded.characters[id]);
  const characterLists = await Promise.all(missingWorks.map(async (parentId) => [parentId, await api.get(query("/v1/characters", {parent_id: parentId, limit: 200, offset: 0}))])); if (!isCurrent()) return;
  for (const [parentId, result] of characterLists) { state.entities.characters = [...state.entities.characters.filter((item) => item.parent_id !== parentId), ...collection(result)]; state.loaded.characters[parentId] = true; }
  const characterIds = [...new Set([state.selection.characterId, ...Object.entries(state.expanded.characters).filter(([, open]) => open).map(([id]) => id)].filter(Boolean))];
  const missingCharacters = characterIds.filter((id) => !state.loaded.outfits[id]);
  const outfitLists = await Promise.all(missingCharacters.map(async (parentId) => [parentId, await api.get(query("/v1/outfits", {parent_id: parentId, limit: 200, offset: 0}))])); if (!isCurrent()) return;
  for (const [parentId, result] of outfitLists) { state.entities.outfits = [...state.entities.outfits.filter((item) => item.parent_id !== parentId), ...collection(result)]; state.loaded.outfits[parentId] = true; }
  if (!compose) return;
  if (!state.loaded.compose) {
    const [generation, postprocess, profiles, providers, groupProfiles, fragmentCategories, resources] = await Promise.all([
      api.get("/v1/presets/generation?archived=false"), api.get("/v1/presets/postprocess?archived=false"), api.get("/v1/validation-settings/single-profiles"), api.get("/v1/validation-settings/providers"), api.get("/v1/validation-settings/group-profiles"), api.get("/v1/prompt-fragment-categories?archived=false&limit=200&offset=0"),
      api.get("/v1/generation/resources").catch((error) => ({__error: requestError(error)})),
    ]); if (!isCurrent()) return;
    state.presets.generation = collection(generation); state.presets.postprocess = collection(postprocess); state.presets.profiles = collection(profiles); state.presets.providers = collection(providers); state.presets.groupProfiles = collection(groupProfiles);
    state.fragmentCategories = collection(fragmentCategories); state.resources = resources?.__error ? null : resources; state.resourcesError = resources?.__error || null; state.loaded.compose = true;
  }
  const fragmentPath = fragmentPickerQuery(state);
  if (state.loaded.fragmentPath !== fragmentPath) {
    const fragments = await api.get(fragmentPath); if (!isCurrent()) return;
    state.fragments = collection(fragments); state.fragmentTotal = Number.isInteger(fragments?.total) ? fragments.total : state.fragments.length; state.loaded.fragmentPath = fragmentPath;
  }
  const selectedOutfitId = state.selection.outfitId;
  if (selectedOutfitId && !state.loaded.groups[selectedOutfitId]) {
    const groups = await api.get(query("/v1/groups", {outfit_id: selectedOutfitId, limit: 200, offset: 0})); if (!isCurrent()) return;
    state.loaded.groups[selectedOutfitId] = collection(groups);
  }
  state.entities.groups = state.selection.outfitId ? (state.loaded.groups[state.selection.outfitId] || []) : [];
  if (state.multiCatalogOpen && !state.catalogLoaded) {
    const page = async (path, parameters = {}) => {
      const all = [];
      for (let offset = 0; ; offset += 200) {
        const result = await api.get(query(path, {...parameters, limit: 200, offset}));
        const values = collection(result); all.push(...values);
        if (values.length < 200 || (Number.isInteger(result?.total) && all.length >= result.total)) return all;
      }
    };
    const catalogWorks = await page("/v1/works");
    const catalogCharacters = (await Promise.all(catalogWorks.map((work) => page("/v1/characters", {parent_id: work.id})))).flat();
    const catalogOutfits = (await Promise.all(catalogCharacters.map((character) => page("/v1/outfits", {parent_id: character.id})))).flat();
    const catalogGroups = await page("/v1/groups"); if (!isCurrent()) return;
    state.catalog = {works: catalogWorks, characters: catalogCharacters, outfits: catalogOutfits, groups: catalogGroups}; state.catalogLoaded = true;
  }
  if (state.productionPlanId) await refreshProductionPlan(state, api);
}

async function pageAll(api, path, parameters = {}) {
  const all = [];
  for (let offset = 0; ; offset += 200) {
    const result = await api.get(query(path, {...parameters, limit: 200, offset}));
    const values = collection(result); all.push(...values);
    if (values.length < 200 || (Number.isInteger(result?.total) && all.length >= result.total)) return all;
  }
}

async function loadCreationData(state, api, isCurrent) {
  await loadProductionData(state, api, isCurrent);
  if (!isCurrent() || state.creationLoaded) return;
  const works = await pageAll(api, "/v1/works"); if (!isCurrent()) return;
  const characters = (await Promise.all(works.filter((item) => !item.archived).map((work) => pageAll(api, "/v1/characters", {parent_id: work.id})))).flat();
  const outfits = (await Promise.all(characters.filter((item) => !item.archived).map((character) => pageAll(api, "/v1/outfits", {parent_id: character.id})))).flat();
  const categories = await pageAll(api, "/v1/prompt-fragment-categories", {archived: false});
  const fragments = await pageAll(api, "/v1/prompt-fragments", {archived: false});
  if (!isCurrent()) return;
  state.entities = {works, characters, outfits, groups: []};
  state.fragmentCategories = categories; state.creationFragments = fragments;
  // ADR-0027 P5: a production plan is rejected for any outfit without a valid
  // reference set, so the target tree shows status up front instead of only
  // surfacing it after a 409. Best effort: a fetch failure leaves the outfit
  // unbadged rather than blocking the whole tree.
  const statusEntries = await Promise.all(outfits.filter((item) => !item.archived).map(async (outfit) => {
    try { return [outfit.id, (await api.get(`/v1/outfits/${outfit.id}/reference-set`)).status]; }
    catch { return [outfit.id, null]; }
  }));
  if (!isCurrent()) return;
  state.referenceStatuses = Object.fromEntries(statusEntries);
  state.creationLoaded = true;
}

function check(label, status, change, disabled = false) {
  const input = node("input", {type: "checkbox", checked: status.checked, disabled: disabled ? "" : null, "aria-label": label, onchange: (event) => change(event.target.checked)});
  input.indeterminate = status.indeterminate;
  return node("label", {class: "creation-check"}, [input, node("span", {text: label})]);
}
function treeToggle(label, open, action) { return node("button", {type: "button", class: "button secondary creation-tree-toggle", "aria-label": `${label} ${open ? "접기" : "펼치기"}`, "aria-expanded": String(open), text: open ? "⌄" : "›", onclick: action}); }

function creationPanel(state, api, rerender, notify) {
  const locked = Boolean(state.creationFrozen || state.creationPending);
  const toggleExpanded = (id) => { state.creationExpanded[id] = state.creationExpanded[id] === false; rerender(); };
  const selectedOutfits = new Set(state.selectedOutfitIds);
  const selectedFragments = new Set(state.draft.fragmentSelections.map(fragmentKey));
  const selectedCommonFragments = new Set((state.draft.commonFragmentSelections || []).map(fragmentKey));
  const activeWorks = sortByName(state.entities.works.filter((work) => !work.archived));
  const charactersFor = (work) => sortByName(state.entities.characters.filter((character) => character.parent_id === work.id && !character.archived));
  const outfitsFor = (character) => sortByName(state.entities.outfits.filter((outfit) => outfit.parent_id === character.id && !outfit.archived));
  const changed = () => { state.creationFrozen = null; state.creationPromptPreview = null; state.draft.multiPlanRequests = {}; state.creationPreviewOffset = 0; };
  const toggleOutfits = (ids, checked) => { state.selectedOutfitIds = toggleTreeSelection(state.selectedOutfitIds, ids, checked); changed(); rerender(); };
  const toggleFragments = (items, checked, common = false) => { const selected = common ? selectedCommonFragments : selectedFragments; const fieldName = common ? "commonFragmentSelections" : "fragmentSelections"; state.draft[fieldName] = toggleTreeSelection(selected, items.map(fragmentKey), checked).map((key) => { const [id, revision] = key.split("@"); return {id, revision: Number(revision)}; }); changed(); invalidatePreview(state.draft); rerender(); };
  const outfitTree = node("section", {class: "panel creation-target-tree"}, [node("h2", {text: "작품 · 캐릭터 · 의상"}), ...activeWorks.map((work) => {
    const characters = charactersFor(work); const outfits = characters.flatMap(outfitsFor);
    const open = state.creationExpanded[work.id] !== false;
    return node("div", {class: "creation-tree-work"}, [treeToggle(work.name, open, () => toggleExpanded(work.id)), check(`작품 · ${work.name}`, treeSelectionState(outfits.map((item) => item.id), selectedOutfits), (checked) => toggleOutfits(outfits.map((item) => item.id), checked), locked || !outfits.length), !outfits.length ? node("small", {class: "muted", text: "선택 가능한 활성 의상이 없습니다."}) : null, open ? node("div", {class: "creation-tree-outfits"}, characters.map((character) => { const children = outfitsFor(character); const characterOpen = state.creationExpanded[character.id] !== false; return node("div", {class: "creation-tree-character"}, [treeToggle(character.name, characterOpen, () => toggleExpanded(character.id)), check(`캐릭터 · ${character.name}`, treeSelectionState(children.map((item) => item.id), selectedOutfits), (checked) => toggleOutfits(children.map((item) => item.id), checked), locked || !children.length), !children.length ? node("small", {class: "muted", text: "선택 가능한 활성 의상이 없습니다."}) : null, characterOpen ? node("div", {class: "creation-tree-outfits"}, children.map((outfit) => {
      const referenceStatus = state.referenceStatuses?.[outfit.id] ?? null;
      const referenceOk = referenceStatus === "valid";
      return node("div", {class: "creation-tree-outfit"}, [check(`의상 · ${outfit.name}`, treeSelectionState([outfit.id], selectedOutfits), (checked) => toggleOutfits([outfit.id], checked), locked || !referenceOk),
        referenceStatus ? node("span", {class: "badge", text: referenceStatusLabel(referenceStatus)}) : null,
        !referenceOk ? node("span", {class: "row"}, [node("small", {class: "muted", text: "참조 세트가 필요합니다."}), button("의상 관리에서 만들기", () => { state.navigate?.("production"); notify?.(`캐릭터 관리에서 "${outfit.name}" 의상을 선택해 참조 세트를 만드세요.`); }, {secondary: true})]) : null]);
    })) : null]); })) : null]);
  })]);
  const fragments = (state.creationFragments || []).filter((item) => !item.archived);
  const categories = new Set(state.fragmentCategories.map((item) => item.id));
  const categoryBranch = (name, items, common = false) => { const id = `${common ? "common:" : "variant:"}category:${name}`; const open = state.creationExpanded[id] !== false; const selected = common ? selectedCommonFragments : selectedFragments; return node("div", {class: "creation-tree-category"}, [treeToggle(name, open, () => toggleExpanded(id)), check(`카테고리 · ${name}`, treeSelectionState(items.map(fragmentKey), selected), (checked) => toggleFragments(items, checked, common), locked), open ? node("div", {class: "creation-tree-fragments"}, items.map((item) => node("div", {class: "creation-tree-fragment"}, [check(common ? item.name : fragmentLabel(item), treeSelectionState([fragmentKey(item)], selected), (checked) => toggleFragments([item], checked, common), locked), common ? null : node("small", {class: "muted creation-fragment-include", text: fragmentIncludeSummary(item.include)})]))) : null]); };
  const branches = (items, common) => {
    const values = [
      ...state.fragmentCategories.map((category) => [category.name, sortByName(items.filter((item) => item.category_id === category.id))]),
      ["미분류", sortByName(items.filter((item) => !item.category_id))],
      ["보관된 카테고리", sortByName(items.filter((item) => item.category_id && !categories.has(item.category_id)))],
    ];
    const visible = values.filter(([, entries]) => entries.length);
    return visible.length ? visible.map(([name, entries]) => categoryBranch(name, entries, common)) : [node("p", {class: "muted", text: common ? "등록한 공통 적용 프롬프트가 없습니다." : "등록한 이미지별 조각이 없습니다."})];
  };
  const fragmentTree = node("section", {class: "panel creation-fragment-tree"}, [node("h2", {text: "이미지별 조각"}), ...branches(fragments.filter((item) => !item.common), false), node("h2", {text: "공통 적용 프롬프트"}), node("p", {class: "muted", text: "모든 예정 이미지에 본문만 적용합니다."}), ...branches(fragments.filter((item) => item.common), true)]);
  const selectedFragmentRecords = fragments.filter((item) => selectedFragments.has(fragmentKey(item)));
  const preview = creationPreviewPage(state.selectedOutfitIds, selectedFragmentRecords, state.creationPreviewOffset);
  const freeze = async () => {
    if (!state.selectedOutfitIds.length || !selectedFragmentRecords.length) { state.error = "의상과 조각을 각각 하나 이상 선택하세요."; rerender(); return; }
    const signature = JSON.stringify({outfits: [...state.selectedOutfitIds].sort(), fragments: [...selectedFragments].sort(), common: [...selectedCommonFragments].sort()});
    if (state.creationFrozen?.signature === signature) { notify("이미 같은 선택을 고정했습니다. 기존 계획 키를 계속 사용합니다."); return; }
    try {
      // Validate every required generation and validation setting before writing
      // any new frozen group. The placeholder group id is never sent.
      buildProductionPlanBody({...state, selection: {...state.selection, groupId: "pending-group"}}, 1);
      state.creationPending = true; rerender();
      const groups = [];
      for (const outfitId of state.selectedOutfitIds) groups.push(await api.post("/v1/groups", {outfit_id: outfitId}));
      state.selection.groupIds = groups.map((group) => group.id);
      state.draft.multiPlanRequests = {}; freezeMultiProductionPlanRequests(state);
      state.creationFrozen = {signature, outfitIds: [...state.selectedOutfitIds], fragments: state.draft.fragmentSelections.map(fragmentKey), commonFragments: (state.draft.commonFragmentSelections || []).map(fragmentKey), groups};
      notify("선택한 의상과 조각의 고정 계획을 준비했습니다. Prompt를 확인한 뒤 시작하세요.");
    } catch (error) { state.error = requestError(error); }
    finally { state.creationPending = false; rerender(); }
  };
  const createPlans = async () => {
    try { state.creationPending = true; rerender(); const requests = freezeMultiProductionPlanRequests(state); let failed = 0; for (const groupId of Object.keys(requests)) { const entry = state.draft.multiPlanRequests[groupId]; if (!entry.plan) { try { entry.plan = await submitProductionPlan(api, entry.request, entry.key); entry.error = null; } catch (error) { entry.error = requestError(error); failed += 1; } } } notify(failed ? `${failed}개 계획 접수에 실패했습니다. 같은 고정 키로 다시 시도할 수 있습니다.` : "고정 제작 계획을 만들었습니다. 아직 실행을 시작하지 않았습니다.", Boolean(failed)); }
    catch (error) { state.error = requestError(error); } finally { state.creationPending = false; rerender(); }
  };
  const previewPrompt = async (outfitId, fragment) => {
    try { const group = state.creationFrozen?.groups.find((item) => item.outfit_id === outfitId); if (!group) throw new Error("먼저 선택을 고정하세요."); state.creationPromptPreview = await api.post("/v1/prompts/preview", buildGenerationBody({...state, selection: {...state.selection, groupId: group.id}, draft: {...state.draft, fragmentSelections: [fragment]}})); rerender(); }
    catch (error) { state.error = requestError(error); rerender(); }
  };
  const startPlans = async () => {
    try { state.creationPending = true; rerender(); for (const entry of Object.values(state.draft.multiPlanRequests)) if (entry.plan?.id) await api.post(`/v1/production-plans/${entry.plan.id}/start`, {plan_hash: entry.plan.plan_hash}); notify("고정 계획 실행을 시작했습니다."); }
    catch (error) { state.error = requestError(error); } finally { state.creationPending = false; rerender(); }
  };
  const planEntries = Object.values(state.draft.multiPlanRequests);
  const plansReady = planEntries.length > 0 && planEntries.every((entry) => entry.plan?.id);
  const resetFrozen = () => { state.creationCompletedPlans ||= []; state.creationCompletedPlans.push(...planEntries.filter((entry) => entry.plan?.id)); state.creationFrozen = null; state.creationPromptPreview = null; state.draft.multiPlanRequests = {}; rerender(); };
  const validationText = state.draft.validationMode === "generation" ? "검사 없이 생성합니다. 결과는 통과가 아니라 미검사 상태로 남습니다." : state.draft.validationMode === "single" ? "모든 예정 항목에 Single 검사를 고정합니다." : "모든 예정 항목에 Single 검사와 묶음 검사를 함께 고정합니다.";
  const planned = node("section", {class: "panel creation-preview"}, [node("h2", {text: `예정 항목 ${preview.total}개`}), node("p", {class: "muted", text: validationText}), node("ul", {class: "fragment-list"}, preview.items.map((item) => node("li", {class: "row"}, [node("span", {text: plannedItemLabel(entityById(state.entities.outfits, item.outfitId)?.name || item.outfitId, item.fragment)}), state.creationFrozen ? button("Prompt", () => previewPrompt(item.outfitId, item.fragment), {secondary: true}) : null]))), node("div", {class: "toolbar"}, [button("이전 50개", () => { state.creationPreviewOffset = Math.max(0, state.creationPreviewOffset - 50); rerender(); }, {secondary: true, disabled: preview.offset === 0}), button("다음 50개", () => { state.creationPreviewOffset += 50; rerender(); }, {secondary: true, disabled: preview.offset + 50 >= preview.total})]), button("선택 확인", freeze, {disabled: state.creationPending || !preview.total || locked}), locked ? button("새 준비", resetFrozen, {secondary: true, disabled: state.creationPending}) : null, state.creationFrozen ? button("생성 준비", createPlans, {disabled: state.creationPending}) : null, plansReady ? button("생성 시작", startPlans, {disabled: state.creationPending}) : null, planEntries.length ? node("ul", {class: "fragment-list"}, planEntries.map((entry) => { const group = state.creationFrozen?.groups.find((item) => item.id === entry.plan?.group_id || item.id === entry.request?.group_id); const outfit = entityById(state.entities.outfits, group?.outfit_id); return node("li", {class: "row"}, [node("span", {text: `${outfit?.name || "선택 의상"} · ${state.draft.fragmentSelections.length}장 · ${entry.plan?.state || entry.error || "계획 준비 중"}`}), entry.plan ? button("계획 보기", () => { state.productionPlanId = entry.plan.id; state.productionPlan = entry.plan; rerender(true); }, {secondary: true}) : null, entry.plan ? button("작업 현황", () => state.navigate?.("jobs"), {secondary: true}) : null]); })) : null, state.creationPromptPreview ? previewView(state.creationPromptPreview) : null]);
  const mobileNav = node("nav", {class: "creation-mobile-switch", "aria-label": "이미지 생성 단계"}, [
    button("의상", () => { state.creationMobilePanel = "targets"; rerender(); }, {secondary: state.creationMobilePanel !== "targets"}),
    button("조각", () => { state.creationMobilePanel = "fragments"; rerender(); }, {secondary: state.creationMobilePanel !== "fragments"}),
    button("설정·확인", () => { state.creationMobilePanel = "settings"; rerender(); }, {secondary: state.creationMobilePanel !== "settings"}),
  ]);
  return node("div", {class: `creation-layout creation-mobile-${state.creationMobilePanel}`}, [mobileNav, outfitTree, fragmentTree, node("section", {class: "creation-settings", inert: locked ? "" : null}, [generationPanel(state, api, rerender, notify)]), locked ? node("p", {class: "muted", text: "고정한 계획의 설정은 바꿀 수 없습니다. 새 준비를 선택하면 기존 계획을 보존한 채 새 선택과 설정을 만들 수 있습니다."}) : null, planned]);
}
/** Mount the production page and return a cleanup function. */
export async function mount(container, ctx) {
  const state = pageState(ctx);
  const creationMode = ctx.mode === "creation";
  // ADR-0027 P6: the default check for a new production plan is single-only;
  // single+group validation remains selectable but is no longer preselected.
  if (creationMode) { state.productionSection = "compose"; state.creationMode = true; if (!state.creationValidationInitialized) { state.draft.validationMode = "single"; state.draft.validationEnabled = true; state.creationValidationInitialized = true; } }
  state.navigate = ctx.navigate;
  state.api = ctx.api;
  state.pageSignal = ctx.signal;
  let disposed = false;
  let loading = 0;
  const notify = (message, error = false) => ctx.notify?.(message, error);
  state.notify = notify;
  const rerender = async (refresh = false) => {
    const current = ++loading;
    if (refresh) {
      try { await (creationMode ? loadCreationData(state, ctx.api, () => current === loading && !disposed && ctx.isActive?.() !== false) : loadProductionData(state, ctx.api, () => current === loading && !disposed && ctx.isActive?.() !== false)); }
      catch (error) { state.error = requestError(error); }
    }
    if (disposed || current !== loading) return;
    const navigation = null;
    const preparePanel = state.mobilePreparationPanel;
    const preparation = node("section", {class: `production-preparation production-mobile-panels ${preparePanel === "editor" ? "editor-open" : "classification-open"}`}, [
      node("nav", {class: "production-mobile-panel-switch", "aria-label": "준비 화면"}, [
        button("분류", () => { state.mobilePreparationPanel = "classification"; rerender(); }, {secondary: preparePanel !== "classification"}),
        button("편집", () => { state.mobilePreparationPanel = "editor"; rerender(); }, {secondary: preparePanel !== "editor"}),
      ]),
      node("div", {class: "production-mobile-panel production-classification"}, [treePanel(state, rerender)]),
      node("div", {class: "production-mobile-panel production-editor"}, [
        entityEditor(state, ctx.api, rerender, notify),
        button("분류로 돌아가기", () => { state.mobilePreparationPanel = "classification"; rerender(); }, {secondary: true}),
      ]),
    ]);
    const hasOutfit = Boolean(entityById(state.entities.outfits, state.selection.outfitId));
    const composition = node("section", {class: "production-composition production-mobile-panels"}, [
      node("div", {class: "production-mobile-panel production-confirmation"}, [groupPanel(state, ctx.api, rerender, notify)]),
      state.productionPlanId || !hasOutfit ? null : node("div", {class: "production-mobile-panel production-settings"}, [generationPanel(state, ctx.api, rerender, notify)]),
    ]);
    const main = creationMode ? (state.productionPlanId ? productionPlanPanel(state, ctx.api, rerender, notify) : creationPanel(state, ctx.api, rerender, notify)) : node("div", { class: "production-layout production-workflow" }, [preparation]);
    const confirmation = archiveConfirmationPanel(state, rerender);
    const children = state.error ? [node("p", { class: "error", role: "alert", text: state.error }), confirmation, main] : [confirmation, main];
    container.replaceChildren(...children.filter(Boolean));
    state.error = null;
  };
  const hadCachedTree = Boolean(state.loaded?.works);
  if (creationMode) state.creationLoaded = false;
  if (hadCachedTree) { state.loaded.works = false; state.loaded.characters = {}; state.loaded.outfits = {}; state.loaded.groups = {}; state.loaded.compose = false; state.loaded.fragmentPath = null; }
  await rerender(!hadCachedTree);
  if (hadCachedTree) rerender(true);
  return () => { disposed = true; state.tree?.dispose?.(); state.tree = null; state.referencePanelDispose?.(); state.referencePanelDispose = null; };
}
