/**
 * Production pilot page.  It only composes Core REST requests; Core remains
 * responsible for prompt composition, frozen groups, and task orchestration.
 */

const EMPTY_COMPONENTS = Object.freeze({ appearance: "", upper: "", lower: "" });
const DEFAULT_GENERATION = Object.freeze({
  diffusion_model: "", text_encoder: "", vae: "", width: 1024, height: 1024,
  seed: 123456789, steps: 24, cfg: 4.5, sampler: "euler_ancestral", scheduler: "normal",
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

function makeKey() {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
  return `production-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

function requestError(error) {
  return error?.message || "요청을 완료하지 못했습니다.";
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
    compositionMode: "fragment", fragmentSelections: [],
    framing: "custom", framingPrompt: "upper body", expression: "", action: "", situation: "",
    include: { appearance: true, upper: true, lower: false },
    generation: deepCopy(DEFAULT_GENERATION), loras: [],
    generationPreset: "", postprocessPreset: "", postprocessMode: "default",
    upscaleModel: "4x-UltraSharp.safetensors", upscaleScale: 1.5, webpEnabled: true, webpQuality: 90,
    validationEnabled: false, validationProfile: "", validationProvider: "",
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
  state.fragmentLimit ||= 50;
  state.fragmentTotal ||= 0;
  state.draft ||= initialDraft();
  state.draft.include ||= { appearance: true, upper: true, lower: false };
  state.draft.fragmentSelections ||= [];
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
  for (const name of ["appearance", "upper", "lower"]) state.draft.include[name] = Boolean(state.draft.include[name]);
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
  return state;
}

function entityById(items, id) {
  return items.find((item) => item.id === id) || null;
}

function query(path, parameters) {
  const values = Object.entries(parameters || {}).filter(([, value]) => value !== null && value !== undefined && value !== "");
  return values.length ? `${path}?${new URLSearchParams(values)}` : path;
}

function entityEditor(state, api, rerender, notify) {
  const selection = state.selection;
  const work = entityById(state.entities.works, selection.workId);
  const character = entityById(state.entities.characters, selection.characterId);
  const outfit = entityById(state.entities.outfits, selection.outfitId);
  const existing = outfit || character || work;
  const kind = existing?.kind || state.editor?.kind;
  if (!kind) return node("section", { class: "panel" }, [node("h2", { text: "저장할 Prompt" }), node("p", { class: "muted", text: "왼쪽에서 작품, 캐릭터 또는 의상을 선택하세요." })]);

  const fresh = existing ? { ...existing, components: { ...EMPTY_COMPONENTS, ...existing.components } } : state.editor;
  state.editor ||= fresh;
  const draft = state.editor;
  const edit = (apply) => (value) => { apply(value); state.dirty = true; };
  const controls = [field("이름", textInput(draft.name, edit((value) => { draft.name = value; })), "분류 이름은 생성 Prompt에 자동으로 들어가지 않습니다.")];
  if (kind === "characters") controls.push(field("캐릭터 Negative", textArea(draft.negative_prompt || "", edit((value) => { draft.negative_prompt = value; })), "이 캐릭터에만 적용되는 제외 조건입니다."));
  if (kind === "outfits") {
    controls.push(field("외형", textArea(draft.components.appearance, edit((value) => { draft.components.appearance = value; })), "머리·눈·신체 특징"));
    controls.push(field("상의", textArea(draft.components.upper, edit((value) => { draft.components.upper = value; })), "상의와 액세서리"));
    controls.push(field("하의", textArea(draft.components.lower, edit((value) => { draft.components.lower = value; })), "하의와 풋웨어"));
  }
  const save = async () => {
    try {
      let result;
      if (existing) {
        const body = { revision: existing.revision, name: draft.name };
        if (kind === "characters") body.negative_prompt = draft.negative_prompt || "";
        if (kind === "outfits") body.components = { ...draft.components };
        result = await api.patch(`/v1/${kind}/${existing.id}`, body);
      } else {
        const body = { name: draft.name };
        if (kind !== "works") body.parent_id = draft.parent_id;
        if (kind === "characters") body.negative_prompt = draft.negative_prompt || "";
        if (kind === "outfits") body.components = { ...draft.components };
        result = await api.post(`/v1/${kind}`, body);
      }
      state.editor = null;
      state.dirty = false;
      if (result.kind === "works") selection.workId = result.id;
      if (result.kind === "characters") selection.characterId = result.id;
      if (result.kind === "outfits") selection.outfitId = result.id;
      notify("원본을 저장했습니다.");
      await rerender(true);
    } catch (error) { state.error = requestError(error); rerender(); }
  };
  return node("section", { class: "panel" }, [node("h2", { text: existing ? "저장할 Prompt" : "새 분류" }),
    state.dirty ? node("p", { class: "error", text: "원본에 저장하지 않은 변경이 있습니다." }) : null,
    node("div", { class: "grid" }, controls), node("div", { class: "row" }, [button("저장", save),
      button("취소", () => { state.editor = null; state.dirty = false; rerender(); }, { secondary: true })]),
    existing?.kind === "outfits" ? node("p", { class: "muted", text: "저장해도 기존 그룹과 과거 Task의 고정 구성은 바뀌지 않습니다." }) : null]);
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
      appearance: Boolean(draft.include.appearance),
      upper: Boolean(draft.include.upper),
      lower: Boolean(draft.include.lower),
    };
    for (const name of ["expression", "action", "situation"]) {
      if (typeof draft[name] === "string" && draft[name].trim()) body[name] = draft[name].trim();
    }
  }
  if (draft.generationPreset) {
    body.presets = { generation: presetReference(draft.generationPreset) };
  } else {
    const input = draft.generation;
    const seed = finiteNumber(input.seed, "Seed", { integer: true });
    if (!Number.isSafeInteger(seed) || seed < 0) throw new Error("Seed는 0 이상의 안전 정수여야 합니다.");
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
  if (draft.validationEnabled) {
    if (!draft.validationProfile || !draft.validationProvider) throw new Error("검사 Profile과 Provider를 모두 선택하세요.");
    body.validation = { profile_id: draft.validationProfile, provider_id: draft.validationProvider };
  }
  return body;
}

export function buildProductionPlanBody(state, minimumFragments = 2) {
  const draft = state.draft;
  if (draft.compositionMode !== "fragment" || !Array.isArray(draft.fragmentSelections) || draft.fragmentSelections.length < minimumFragments) {
    throw new Error(`제작 계획에는 전역 조각을 ${minimumFragments === 2 ? "두 개" : "한 개"} 이상 선택하세요.`);
  }
  if (!draft.validationEnabled || !draft.validationProfile || !draft.validationProvider) {
    throw new Error("제작 계획에는 각 이미지의 Single 검사 Profile과 Provider가 필요합니다.");
  }
  if (!draft.groupValidationProfile || !draft.groupValidationProvider) {
    throw new Error("제작 계획에는 묶음 검사 Profile과 Provider가 필요합니다.");
  }
  // Reuse the exact common generation/postprocess/validation contract from a
  // one-fragment preview, then replace only the composition selection.
  const previewBody = buildGenerationBody({ ...state, draft: { ...draft, fragmentSelections: [draft.fragmentSelections[0]] } });
  delete previewBody.fragment;
  previewBody.fragments = draft.fragmentSelections.map(presetReference);
  previewBody.group_validation = { profile_id: draft.groupValidationProfile, provider_id: draft.groupValidationProvider };
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
  const [id, revision] = value.split("@");
  return { id, revision: Number(revision) };
}

function selectChoice(value, options, onChange) {
  return node("select", { onchange: (event) => onChange(event.target.value) }, options.map((option) => selectedOption(option, option, value === option)));
}

function seedField(value, onChange, pickRandom) {
  const input = textInput(value, onChange, { type: "number", min: 0, step: 1 });
  const id = `production-seed-${++fieldSequence}`;
  input.id = id;
  return node("div", { class: "field" }, [node("label", { for: id, text: "Seed" }),
    node("div", { class: "row" }, [input, button("랜덤 뽑기", pickRandom, { secondary: true })]),
    node("small", { class: "muted", text: "안전 정수 범위에서 난수를 만들고 미리보기를 무효화합니다." })]);
}

function generationPanel(state, api, rerender, notify) {
  const draft = state.draft;
  const change = (callback) => (value) => { callback(value); invalidatePreview(draft, true); };
  const generationControls = draft.generationPreset ? [node("p", { class: "muted", text: "Generation preset을 선택했으므로 직접 모델 설정은 요청에 함께 보내지 않습니다." })] : [
    field("Diffusion model", textInput(draft.generation.diffusion_model, change((value) => { draft.generation.diffusion_model = value; }), { placeholder: "등록된 diffusion model 파일명" }), "모델 목록 API가 아직 없으므로 등록 파일명을 직접 입력합니다."),
    field("Text encoder", textInput(draft.generation.text_encoder, change((value) => { draft.generation.text_encoder = value; }), { placeholder: "등록된 text encoder 파일명" })),
    field("VAE", textInput(draft.generation.vae, change((value) => { draft.generation.vae = value; }), { placeholder: "등록된 VAE 파일명" })),
    field("너비", textInput(draft.generation.width, change((value) => { draft.generation.width = value; }), { type: "number", min: 256, max: 1920, step: 16 })),
    field("높이", textInput(draft.generation.height, change((value) => { draft.generation.height = value; }), { type: "number", min: 256, max: 1920, step: 16 })),
    seedField(draft.generation.seed, change((value) => { draft.generation.seed = value; }), () => {
      draft.generation.seed = randomSafeSeed(); invalidatePreview(draft, true); rerender();
    }),
    field("Steps", textInput(draft.generation.steps, change((value) => { draft.generation.steps = value; }), { type: "number", min: 1, max: 100, step: 1 })),
    field("CFG", textInput(draft.generation.cfg, change((value) => { draft.generation.cfg = value; }), { type: "number", min: 0, max: 20, step: 0.1 })),
    field("Sampler", selectChoice(draft.generation.sampler, SAMPLER_OPTIONS, change((value) => { draft.generation.sampler = value; }))),
    field("Scheduler", selectChoice(draft.generation.scheduler, SCHEDULER_OPTIONS, change((value) => { draft.generation.scheduler = value; }))),
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
      selectedOption("default", "기본 사용: 1024 → 1536, WebP", draft.postprocessMode === "default" && !draft.postprocessPreset),
      selectedOption("none", "후처리 없음: {}", draft.postprocessMode === "none"),
      selectedOption("direct", "직접 Upscale/Encode 설정", draft.postprocessMode === "direct"),
    ]), "기본은 요청에서 postprocess를 생략합니다."),
    field("후처리 Preset", node("select", { onchange: (event) => { draft.postprocessPreset = event.target.value; invalidatePreview(draft); rerender(); } }, [selectedOption("", "선택 안 함", !draft.postprocessPreset),
      ...state.presets.postprocess.map((item) => selectedOption(`${item.id}@${item.revision}`, `${item.name} (r${item.revision})`, draft.postprocessPreset === `${item.id}@${item.revision}`))])),
    draft.postprocessMode === "direct" && !draft.postprocessPreset ? field("Upscale model", textInput(draft.upscaleModel, change((value) => { draft.upscaleModel = value; }))) : null,
    draft.postprocessMode === "direct" && !draft.postprocessPreset ? field("최종 배율", textInput(draft.upscaleScale, change((value) => { draft.upscaleScale = value; }), { type: "number", min: 0.01, step: 0.1 })) : null,
    draft.postprocessMode === "direct" && !draft.postprocessPreset ? field("WebP 출력", node("input", { type: "checkbox", checked: draft.webpEnabled, onchange: (event) => { draft.webpEnabled = event.target.checked; invalidatePreview(draft); } })) : null,
    draft.postprocessMode === "direct" && !draft.postprocessPreset ? field("WebP 품질", textInput(draft.webpQuality, change((value) => { draft.webpQuality = value; }), { type: "number", min: 1, max: 100, step: 1 })) : null,
  ]);
  const validation = node("div", { class: "grid" }, [
    field("생성 후 검사", node("input", { type: "checkbox", checked: draft.validationEnabled, onchange: (event) => { draft.validationEnabled = event.target.checked; invalidatePreview(draft); rerender(); } })),
    draft.validationEnabled ? field("Single Profile", choice(draft.validationProfile, state.presets.profiles, (value) => { draft.validationProfile = value; invalidatePreview(draft); }), "등록된 설정만 선택합니다.") : null,
    draft.validationEnabled ? field("Provider", choice(draft.validationProvider, state.presets.providers, (value) => { draft.validationProvider = value; invalidatePreview(draft); })) : null,
  ]);
  return node("section", { class: "panel" }, [node("h2", { text: "생성 설정" }), field("Generation Preset", presetSelect), node("div", { class: "grid" }, generationControls),
    node("h3", { text: "LoRA" }), node("p", { class: "muted", text: "행 순서대로 적용합니다. 설치 확인된 Anima LoRA를 제안하며, 다른 등록 파일명도 직접 입력할 수 있습니다." }),
    node("datalist", { id: "production-known-anima-loras" }, KNOWN_ANIMA_LORAS.map((name) => node("option", { value: name }))), ...loraRows,
    button("+ LoRA", () => { draft.loras.push({ name: "", strength: 1 }); invalidatePreview(draft); rerender(); }, { secondary: true }),
    node("h3", { text: "후처리" }), postprocess, node("h3", { text: "검사" }), validation]);
}

function choice(value, items, onChange) {
  return node("select", { onchange: (event) => onChange(event.target.value) }, [selectedOption("", "선택", !value),
    ...items.map((item) => selectedOption(item.profile_id || item.provider_id || item.id, `${item.name || item.profile_id || item.provider_id} (r${item.revision})`, value === (item.profile_id || item.provider_id || item.id)))]);
}

function fragmentReference(item) {
  return `${item.id}@${item.revision}`;
}

function directCompositionFields(draft, update) {
  return node("div", { class: "grid" }, [
    field("구도 Prompt", textArea(draft.framingPrompt, update("framingPrompt"), "예: full body, white background\n또는 upper body, cowboy shot"), "쉼표나 줄바꿈으로 한 이미지의 구도를 조합합니다. 줄마다 별도 Task를 만들지 않습니다."),
    field("표정", textArea(draft.expression, update("expression"), "예: gentle smile")),
    field("자세·동작", textArea(draft.action, update("action"), "예: standing, one hand raised")),
    field("상황", textArea(draft.situation, update("situation"), "예: studio portrait")),
    field("외형 포함", node("input", { type: "checkbox", checked: draft.include.appearance, onchange: (event) => { draft.include.appearance = event.target.checked; invalidatePreview(draft); } })),
    field("상의 포함", node("input", { type: "checkbox", checked: draft.include.upper, onchange: (event) => { draft.include.upper = event.target.checked; invalidatePreview(draft); } })),
    field("하의 포함", node("input", { type: "checkbox", checked: draft.include.lower, onchange: (event) => { draft.include.lower = event.target.checked; invalidatePreview(draft); } }), "상반신 구도에서 하의를 켜면 Core가 구도와의 충돌을 검사합니다. 전신으로 바꾸면 하의를 명시적으로 켜세요."),
  ]);
}

function fragmentLibrary(state, api, rerender, notify) {
  const draft = state.draft;
  const selections = new Set(draft.fragmentSelections);
  const editor = state.fragmentEditor;
  const setMode = (mode) => { draft.compositionMode = mode; invalidatePreview(draft, true); rerender(); };
  const toggle = (item, checked) => {
    const ref = fragmentReference(item);
    if (checked) selections.add(ref); else selections.delete(ref);
    draft.fragmentSelections = [...selections];
    invalidatePreview(draft, true); rerender();
  };
  const openEditor = (item = null) => {
    state.fragmentEditor = item ? { id: item.id, revision: item.revision, name: item.name, body: item.body,
      include: { upper: Boolean(item.include?.upper), lower: Boolean(item.include?.lower) } } :
      { name: "", body: "", include: { upper: true, lower: false } };
    rerender();
  };
  const save = async () => {
    const value = state.fragmentEditor;
    try {
      const body = { name: value.name, body: value.body, include: { upper: Boolean(value.include.upper), lower: Boolean(value.include.lower) } };
      const previousRef = value.id ? `${value.id}@${value.revision}` : null;
      const result = value.id ? await api.patch(`/v1/prompt-fragments/${value.id}`, { revision: value.revision, ...body }) : await api.post("/v1/prompt-fragments", body);
      if (previousRef && selections.delete(previousRef)) selections.add(fragmentReference(result));
      if (!previousRef) selections.add(fragmentReference(result));
      draft.fragmentSelections = [...selections]; state.fragmentEditor = null;
      invalidatePreview(draft, true); notify("전역 조각을 저장했습니다."); await rerender(true);
    } catch (error) { state.error = requestError(error); rerender(); }
  };
  const archive = async (item) => {
    try {
      await api.patch(`/v1/prompt-fragments/${item.id}`, { revision: item.revision, archived: true });
      selections.delete(fragmentReference(item)); draft.fragmentSelections = [...selections];
      invalidatePreview(draft, true); notify("전역 조각을 보관했습니다."); await rerender(true);
    } catch (error) { state.error = requestError(error); rerender(); }
  };
  const selectedCount = draft.fragmentSelections.length;
  const mode = node("select", { onchange: (event) => setMode(event.target.value) }, [
    selectedOption("fragment", "전역 조각 라이브러리", draft.compositionMode === "fragment"),
    selectedOption("direct", "고급 단일 직접 입력", draft.compositionMode === "direct"),
  ]);
  if (draft.compositionMode === "direct") return node("div", { class: "grid" }, [field("구성 방식", mode), directCompositionFields(draft, (name) => (value) => { draft[name] = value; invalidatePreview(draft, true); })]);
  const rows = state.fragments.map((item) => {
    const ref = fragmentReference(item);
    return node("li", { class: "row" }, [
      node("input", { type: "checkbox", checked: selections.has(ref), "aria-label": `${item.name} 조각 선택`, onchange: (event) => toggle(item, event.target.checked) }),
      node("span", { text: `${item.name} (r${item.revision})` }), button("수정", () => openEditor(item), { secondary: true }), button("보관", () => archive(item), { secondary: true }),
    ]);
  });
  const editorPanel = editor ? node("div", { class: "grid" }, [
    field("조각 이름", textInput(editor.name, (value) => { editor.name = value; })),
    field("조각 본문", textArea(editor.body, (value) => { editor.body = value; }, "구도·표정·동작·배경을 자유롭게 작성")),
    field("상의 포함", node("input", { type: "checkbox", checked: editor.include.upper, onchange: (event) => { editor.include.upper = event.target.checked; } })),
    field("하의 포함", node("input", { type: "checkbox", checked: editor.include.lower, onchange: (event) => { editor.include.lower = event.target.checked; } })),
    node("p", { class: "muted", text: "외형은 모든 전역 조각에 항상 포함됩니다." }),
    node("div", { class: "toolbar" }, [button("조각 저장", save), button("취소", () => { state.fragmentEditor = null; rerender(); }, { secondary: true })]),
  ]) : null;
  return node("div", { class: "grid" }, [field("구성 방식", mode),
    node("p", { class: "muted", text: "전역 조각은 작품·캐릭터에 속하지 않습니다. 조각 본문에는 구도, 표정, 동작, 배경을 함께 작성할 수 있습니다." }),
    editorPanel || node("div", {}, [node("ul", { class: "fragment-list" }, rows),
      node("div", { class: "toolbar" }, [button("이전", () => { state.fragmentOffset = Math.max(0, state.fragmentOffset - state.fragmentLimit); rerender(true); }, { secondary: true, disabled: state.fragmentOffset === 0 }),
        button("다음", () => { state.fragmentOffset += state.fragmentLimit; rerender(true); }, { secondary: true, disabled: state.fragmentOffset + state.fragmentLimit >= state.fragmentTotal }),
        button("+ 전역 조각", () => openEditor(), { secondary: true })]),
      node("p", { class: "muted", text: `조각 ${state.fragmentTotal ? state.fragmentOffset + 1 : 0}–${Math.min(state.fragmentOffset + state.fragmentLimit, state.fragmentTotal)} / ${state.fragmentTotal}` })]),
    node("p", { class: selectedCount === 1 ? "muted" : "error", text: selectedCount === 1 ? "단일 미리보기에 조각 1개가 선택되었습니다." : `선택 조각: ${selectedCount}개. 단일 미리보기에는 정확히 1개를 선택하세요.` }),
    selectedCount > 1 ? node("p", { class: "muted", text: "복수 선택은 아래 제작 계획에서 고정 미리보기로 만들고, 페이지별 Prompt를 확인한 뒤 명시적으로 시작합니다." }) : null,
  ]);
}

async function refreshProductionPlan(state, api) {
  if (!state.productionPlanId) return;
  const plan = await api.get(`/v1/production-plans/${state.productionPlanId}`);
  const [items, comparisons] = await Promise.all([
    api.get(query(`/v1/production-plans/${plan.id}/items`, { limit: 20, offset: state.planItemsOffset })),
    api.get(`/v1/production-plans/${plan.id}/comparisons`),
  ]);
  state.productionPlan = plan;
  const pendingEntry = state.draft.multiPlanRequests?.[plan.group_id];
  if (pendingEntry?.plan?.id === plan.id) pendingEntry.plan = plan;
  if (state.multiProductionPlans?.[plan.group_id]?.id === plan.id) state.multiProductionPlans[plan.group_id] = plan;
  state.productionPlanGroup = plan.state === "awaiting_reference_confirmation" ? await api.get(`/v1/groups/${plan.group_id}`) : null;
  state.productionPlanItems = collection(items);
  state.productionPlanItemsTotal = Number.isInteger(items?.total) ? items.total : state.productionPlanItems.length;
  state.productionPlanComparisons = collection(comparisons);
}

function planSetupPanel(state, api, rerender, notify) {
  const draft = state.draft;
  if (draft.fragmentSelections.length < 2) return null;
  const create = async () => {
    try {
      draft.planRequest ||= buildProductionPlanBody(state);
      draft.planKey ||= makeKey();
      draft.planPending = true; rerender();
      const plan = await api.post("/v1/production-plans", draft.planRequest, draft.planKey);
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
  return `${names.length ? names.join(" / ") : "이름을 불러오는 중"} · r${group.outfit_revision} · ${group.id.slice(0, 8)}`;
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
          const plan = await api.post("/v1/production-plans", entry.request, entry.key);
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
  return node("section", { class: "panel" }, [node("h3", { text: "여러 캐릭터·의상 제작" }),
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
  const items = (state.productionPlanItems || []).map((item) => node("li", {}, [node("details", {}, [
    node("summary", { text: `#${item.index + 1} · ${item.state}` }),
    node("p", { class: "prompt-preview-text", text: `Positive: ${item.snapshot?.generation_inputs?.positive_prompt || ""}` }),
    node("p", { class: "prompt-preview-text", text: `Negative: ${item.snapshot?.generation_inputs?.negative_prompt || ""}` }),
    node("pre", { text: JSON.stringify({ fragment: item.fragment, inclusion: item.snapshot?.inclusion, error: item.error }, null, 2) }),
  ])]));
  const terminal = ["completed", "failed", "cancelled", "insufficient_images"].includes(plan.state);
  return node("section", { class: "panel" }, [node("h2", { text: "고정 제작 계획" }),
    node("p", { class: "badge", text: plan.state }), node("p", { text: `계획 ${plan.id} · ${plan.total}개 · 결과: ${plan.outcome || "아직 없음"}` }),
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
  if (!outfit) return node("section", { class: "panel" }, [node("h2", { text: "이번 생성" }),
    node("p", { class: "muted", text: "단일 생성은 의상을 선택한 뒤 고정 그룹을 만듭니다. 여러 기존 그룹은 아래에서 바로 선택할 수 있습니다." }),
    fragmentLibrary(state, api, rerender, notify), multiPlanSetupPanel(state, api, rerender, notify)]);
  const createGroup = async () => {
    try {
      const group = await api.post("/v1/groups", { outfit_id: outfit.id });
      state.selection.groupId = group.id;
      state.catalogLoaded = false;
      notify("새 고정 그룹을 만들었습니다.");
      await rerender(true);
    } catch (error) { state.error = requestError(error); rerender(); }
  };
  const groups = state.entities.groups;
  const groupList = node("select", { onchange: (event) => { state.selection.groupId = event.target.value || null; invalidatePreview(state.draft); rerender(); } }, [selectedOption("", "그룹 선택", !state.selection.groupId),
    ...groups.map((item) => selectedOption(item.id, `r${item.outfit_revision} · ${item.id.slice(0, 8)}`, state.selection.groupId === item.id))]);
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
  return node("section", { class: "panel" }, [node("h2", { text: "이번 생성" }), node("div", { class: "row" }, [field("고정 그룹", groupList), button("현재 의상으로 새 그룹", createGroup, { secondary: true })]),
    stale ? node("p", { class: "error", text: "선택 그룹은 현재 의상과 다른 revision입니다. 과거 구성을 사용하거나 새 그룹을 만드세요." }) : null,
    fragmentLibrary(state, api, rerender, notify),
    planSetupPanel(state, api, rerender, notify),
    multiPlanSetupPanel(state, api, rerender, notify),
    node("div", { class: "toolbar" }, [button("미리보기 갱신", preview, { disabled: draft.previewing }), button("명시적으로 Task 접수", submit, { disabled: draft.pending || !draft.preview?.preview_hash }),
      draft.pendingKey ? button("응답 유실 복구", recover, { secondary: true }) : null]),
    previewView(draft.preview), draft.pendingKey ? node("p", { class: "muted", text: `복구 키를 보관 중입니다: ${draft.pendingKey}` }) : null,
    draft.task ? node("div", { class: "row" }, [node("span", { class: "badge", text: draft.task.state || "accepted" }), button("작업 현황 열기", () => ctxNavigate(state, "jobs", draft.task.id), { secondary: true })]) : null]);
}

function ctxNavigate(state, tab, id) {
  state.navigate?.(tab, id);
}

function previewView(preview) {
  if (!preview) return node("p", { class: "muted", text: "미리보기를 갱신하면 Core가 합성한 Prompt와 포함 사유를 표시합니다." });
  const generation = preview.snapshot?.generation_inputs || {};
  return node("details", { open: "" }, [node("summary", { text: "Core 미리보기" }),
    node("p", { class: "prompt-preview-text", text: `Positive: ${generation.positive_prompt || ""}` }), node("p", { class: "prompt-preview-text", text: `Negative: ${generation.negative_prompt || ""}` }),
    node("pre", { text: JSON.stringify(preview.snapshot?.inclusion || {}, null, 2) })]);
}

function treePanel(state, rerender) {
  const selection = state.selection;
  const expanded = state.expanded;
  const select = (kind, item) => {
    if (state.dirty) { state.error = "미저장 원본을 먼저 저장하거나 취소하세요."; rerender(); return; }
    if (kind === "works") {
      selection.workId = item.id; selection.characterId = null; selection.outfitId = null; selection.groupId = null;
      expanded.works[item.id] = true;
    }
    if (kind === "characters") {
      selection.workId = item.parent_id; selection.characterId = item.id; selection.outfitId = null; selection.groupId = null;
      expanded.works[item.parent_id] = true; expanded.characters[item.id] = true;
    }
    if (kind === "outfits") {
      const character = entityById(state.entities.characters, item.parent_id);
      selection.characterId = item.parent_id; selection.workId = character?.parent_id || selection.workId;
      selection.outfitId = item.id; selection.groupId = null;
      if (selection.workId) expanded.works[selection.workId] = true;
      expanded.characters[item.parent_id] = true;
    }
    state.editor = { ...item, components: { ...EMPTY_COMPONENTS, ...item.components } };
    rerender(true);
  };
  const toggle = (kind, id) => {
    expanded[kind][id] = !expanded[kind][id];
    rerender(true);
  };
  const create = (kind, parentId = null) => {
    if (state.dirty) { state.error = "미저장 원본을 먼저 저장하거나 취소하세요."; rerender(); return; }
    state.editor = { kind, name: "", parent_id: parentId, negative_prompt: "", components: { ...EMPTY_COMPONENTS } };
    rerender();
  };
  const selectButton = (label, selected, action) => node("button", {
    type: "button", class: selected ? "tree-select selected" : "tree-select", "aria-current": selected ? "true" : null,
    onclick: action, text: label,
  });
  const toggleButton = (kind, id, isOpen, label) => node("button", {
    type: "button", class: "tree-toggle", "aria-expanded": isOpen ? "true" : "false",
    "aria-label": `${label} ${isOpen ? "접기" : "펼치기"}`, onclick: () => toggle(kind, id), text: isOpen ? "˅" : ">",
  });
  const works = state.entities.works.map((work) => {
    const workOpen = Boolean(expanded.works[work.id]);
    const characters = state.entities.characters.filter((character) => character.parent_id === work.id).map((character) => {
      const characterOpen = Boolean(expanded.characters[character.id]);
      const outfits = state.entities.outfits.filter((outfit) => outfit.parent_id === character.id).map((outfit) =>
        node("li", { role: "treeitem", class: "tree-row" }, [selectButton(outfit.name, selection.outfitId === outfit.id, () => select("outfits", outfit))]));
      return node("li", { role: "treeitem", "aria-expanded": characterOpen ? "true" : "false" }, [
        node("div", { class: "tree-row" }, [toggleButton("characters", character.id, characterOpen, character.name), selectButton(character.name, selection.characterId === character.id && !selection.outfitId, () => select("characters", character))]),
        characterOpen ? node("ul", { class: "tree-children", role: "group" }, outfits) : null,
      ]);
    });
    return node("li", { role: "treeitem", "aria-expanded": workOpen ? "true" : "false" }, [
      node("div", { class: "tree-row" }, [toggleButton("works", work.id, workOpen, work.name), selectButton(work.name, selection.workId === work.id && !selection.characterId, () => select("works", work))]),
      workOpen ? node("ul", { class: "tree-children", role: "group" }, characters) : null,
    ]);
  });
  return node("section", { class: "panel" }, [node("h2", { text: "분류" }), node("ul", { class: "classification-tree", role: "tree", "aria-label": "작품, 캐릭터, 의상" }, works),
    node("div", { class: "toolbar" }, [button("+ 작품", () => create("works"), { secondary: true }), button("+ 캐릭터", () => {
      if (selection.workId) create("characters", selection.workId); else { state.error = "먼저 작품을 선택하세요."; rerender(); }
    }, { secondary: true }), button("+ 의상", () => {
      if (selection.characterId) create("outfits", selection.characterId); else { state.error = "먼저 캐릭터를 선택하세요."; rerender(); }
    }, { secondary: true })])]);
}
async function load(state, api) {
  const [works, generation, postprocess, profiles, providers, fragments, groupProfiles] = await Promise.all([
    api.get("/v1/works?limit=200&offset=0"), api.get("/v1/presets/generation?archived=false"), api.get("/v1/presets/postprocess?archived=false"),
    api.get("/v1/validation-settings/single-profiles"), api.get("/v1/validation-settings/providers"),
    api.get(query("/v1/prompt-fragments", { archived: false, limit: state.fragmentLimit, offset: state.fragmentOffset })),
    api.get("/v1/validation-settings/group-profiles"),
  ]);
  state.entities.works = collection(works);
  state.presets.generation = collection(generation); state.presets.postprocess = collection(postprocess);
  state.presets.profiles = collection(profiles); state.presets.providers = collection(providers);
  state.presets.groupProfiles = collection(groupProfiles);
  state.fragments = collection(fragments);
  state.fragmentTotal = Number.isInteger(fragments?.total) ? fragments.total : state.fragments.length;
  const workIds = [...new Set([state.selection.workId, ...Object.entries(state.expanded.works).filter(([, open]) => open).map(([id]) => id)].filter(Boolean))];
  const characterLists = await Promise.all(workIds.map((parentId) => api.get(query("/v1/characters", { parent_id: parentId, limit: 200, offset: 0 }))));
  state.entities.characters = characterLists.flatMap(collection);
  const characterIds = [...new Set([state.selection.characterId, ...Object.entries(state.expanded.characters).filter(([, open]) => open).map(([id]) => id)].filter(Boolean))];
  const outfitLists = await Promise.all(characterIds.map((parentId) => api.get(query("/v1/outfits", { parent_id: parentId, limit: 200, offset: 0 }))));
  state.entities.outfits = outfitLists.flatMap(collection);
  if (state.selection.outfitId) state.entities.groups = collection(await api.get(query("/v1/groups", { outfit_id: state.selection.outfitId, limit: 200, offset: 0 })));
  else state.entities.groups = [];
  if (!state.catalogLoaded) {
    const page = async (path, parameters = {}) => {
      const all = [];
      for (let offset = 0; ; offset += 200) {
        const result = await api.get(query(path, { ...parameters, limit: 200, offset }));
        const values = collection(result); all.push(...values);
        if (values.length < 200 || (Number.isInteger(result?.total) && all.length >= result.total)) return all;
      }
    };
    const catalogWorks = await page("/v1/works");
    const catalogCharacters = (await Promise.all(catalogWorks.map((work) => page("/v1/characters", { parent_id: work.id })))).flat();
    const catalogOutfits = (await Promise.all(catalogCharacters.map((character) => page("/v1/outfits", { parent_id: character.id })))).flat();
    state.catalog = { works: catalogWorks, characters: catalogCharacters, outfits: catalogOutfits, groups: await page("/v1/groups") };
    state.catalogLoaded = true;
  }
  if (state.productionPlanId) await refreshProductionPlan(state, api);
}
/** Mount the production page and return a cleanup function. */
export async function mount(container, ctx) {
  const state = pageState(ctx);
  state.navigate = ctx.navigate;
  let disposed = false;
  let loading = 0;
  const notify = (message, error = false) => ctx.notify?.(message, error);
  const rerender = async (refresh = false) => {
    const current = ++loading;
    if (refresh) {
      try { await load(state, ctx.api); }
      catch (error) { state.error = requestError(error); }
    }
    if (disposed || current !== loading) return;
    const main = node("div", { class: "production-layout" }, [treePanel(state, rerender),
      node("div", { class: "grid" }, [entityEditor(state, ctx.api, rerender, notify), groupPanel(state, ctx.api, rerender, notify)]),
      generationPanel(state, ctx.api, rerender, notify)]);
    const children = state.error ? [node("p", { class: "error", role: "alert", text: state.error }), main] : [main];
    container.replaceChildren(...children);
    state.error = null;
  };
  await rerender(true);
  return () => { disposed = true; };
}
