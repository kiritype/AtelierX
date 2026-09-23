"use strict";

const STATE_LABELS = { running: "실행 중", external: "외부 실행", stopped: "중지", starting: "준비 중", stopping: "종료 중", error: "오류" };
const DEP_LABELS = { ok: "정상", warning: "주의", missing: "없음", unknown: "확인 불가" };
const OPTION_LABELS = { generation: "Generation", validation: "Validation", discord_bridge: "Discord Bridge" };
const WORK_LABELS = {
  core_tasks: "Core Task", standalone: "독립 생성", plans: "제작 계획", postprocess: "후처리", validation_runs: "검증",
  group_runs: "묶음 검증", batches: "배치", gpu_active: "GPU 사용·대기", generation: "Generation Job",
  validation: "Validation Job", discord_delivery: "Discord 미전달", remote_generation: "원격 Generation", remote_validation: "원격 Validation",
};
const cards = new Map();

async function api(path, options = {}) {
  const method = options.method || "GET";
  const headers = { Accept: "application/json" };
  if (method !== "GET") headers["X-AtelierX-Control"] = "1";
  if (options.body !== undefined) headers["Content-Type"] = "application/json";
  const response = await fetch(path, { method, headers, body: options.body === undefined ? undefined : JSON.stringify(options.body), cache: "no-store" });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
  return data;
}

function el(tag, attributes = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attributes)) {
    if (key === "class") node.className = value;
    else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else node.setAttribute(key, value);
  }
  for (const child of children) node.append(child);
  return node;
}

function formatTime(value) {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString("ko-KR");
}

function workSummary(work) {
  if (!work) return "";
  return Object.entries(work).filter(([, value]) => value).map(([key, value]) => `${WORK_LABELS[key] || key} ${value === true ? "" : value}`.trim()).join(", ");
}

function buildCard(item) {
  const refs = {};
  refs.badge = el("span", { class: "badge" });
  refs.pid = el("dd"); refs.started = el("dd"); refs.ports = el("dd"); refs.managed = el("dd");
  refs.start = el("button", { type: "button", class: "primary", onclick: () => act(item.id, "start") }, "시작");
  refs.stop = el("button", { type: "button", onclick: () => act(item.id, "stop") }, "종료");
  refs.restart = el("button", { type: "button", onclick: () => act(item.id, "restart") }, "재시작");
  refs.log = el("button", { type: "button", onclick: () => showLog(item.id) }, "로그 보기");
  refs.autostart = el("input", { type: "checkbox", onchange: (event) => saveSettings({ autostart: { [item.id]: event.target.checked } }) });
  refs.message = el("p", { class: "msg", hidden: "" });
  refs.error = el("p", { class: "msg bad", hidden: "" });
  const card = el("article", { class: "card", "aria-labelledby": `title-${item.id}` },
    el("header", {}, el("h3", { id: `title-${item.id}` }, item.label), refs.badge),
    el("dl", {}, el("dt", {}, "관리"), refs.managed, el("dt", {}, "PID"), refs.pid, el("dt", {}, "시작 시각"), refs.started, el("dt", {}, "포트"), refs.ports),
    el("div", { class: "actions" }, refs.start, refs.stop, refs.restart, refs.log),
    el("label", { class: "autostart" }, refs.autostart, "시작 시 자동 켜기"));
  if (item.id === "services") {
    refs.options = {};
    const box = el("div", { class: "options" }, el("span", { class: "small muted" }, "시작 옵션 (재시작 시 적용)"));
    for (const key of Object.keys(OPTION_LABELS)) {
      refs.options[key] = el("input", { type: "checkbox", onchange: (event) => saveSettings({ services: { [key]: event.target.checked } }) });
      box.append(el("label", {}, refs.options[key], OPTION_LABELS[key]));
    }
    refs.pending = el("p", { class: "msg warn", hidden: "" }, "변경한 옵션은 서비스를 재시작해야 적용됩니다.");
    box.append(refs.pending);
    card.append(box);
  }
  card.append(refs.message, refs.error);
  cards.set(item.id, refs);
  return card;
}

function updateCard(item) {
  const refs = cards.get(item.id);
  refs.badge.className = `badge badge-${item.state}`;
  refs.badge.textContent = STATE_LABELS[item.state] || item.state;
  refs.managed.textContent = item.managed ? "제어판 관리" : (item.state === "external" ? "외부 실행 (종료 불가)" : "—");
  refs.pid.textContent = item.pid ?? "—";
  refs.started.textContent = formatTime(item.started_at);
  refs.ports.textContent = item.ports.length ? item.ports.join(", ") : "—";
  const busy = item.busy || item.state === "starting" || item.state === "stopping";
  refs.start.disabled = busy || item.state === "running" || item.state === "external";
  refs.stop.disabled = busy || !item.managed;
  refs.restart.disabled = busy || !item.managed;
  refs.log.disabled = !item.has_log;
  if (document.activeElement !== refs.autostart) refs.autostart.checked = item.autostart;
  if (refs.options) {
    for (const [key, box] of Object.entries(refs.options)) if (document.activeElement !== box) box.checked = Boolean(item.pending_options?.[key]);
    const differs = item.managed && Object.keys(OPTION_LABELS).some((key) => Boolean(item.options?.[key]) !== Boolean(item.pending_options?.[key]));
    refs.pending.hidden = !differs;
  }
  const work = workSummary(item.active_work);
  refs.error.hidden = !item.last_error;
  refs.error.textContent = item.last_error ? item.last_error + (work ? `\n활성 작업: ${work}` : "") : "";
  refs.message.hidden = Boolean(item.last_error) || !item.last_result;
  refs.message.className = "msg ok";
  refs.message.textContent = item.last_result || "";
}

function render(status) {
  const container = document.getElementById("items");
  for (const item of status.items) {
    if (!cards.has(item.id)) container.append(buildCard(item));
    updateCard(item);
  }
  const auto = status.autostart || {};
  const notice = document.getElementById("autostart");
  notice.hidden = !auto.state || auto.state === "idle";
  notice.className = auto.state === "failed" ? "notice bad" : "notice";
  notice.textContent = auto.state === "running" ? "자동 켜기 진행 중: ComfyUI·LM Studio → 서비스 → Tunnel 순서로 준비를 확인합니다."
    : auto.state === "failed" ? auto.error : auto.state === "completed" ? "자동 켜기를 마쳤습니다." : "";
  document.getElementById("updated").textContent = "갱신 " + new Date(status.generated_at).toLocaleTimeString("ko-KR");
}

async function poll() {
  try {
    render(await api("/api/status"));
    document.getElementById("conn").hidden = true;
  } catch {
    document.getElementById("conn").hidden = false;
  }
}

async function act(id, action) {
  const refs = cards.get(id);
  try {
    await api(`/api/items/${id}/${action}`, { method: "POST" });
    refs.error.hidden = true;
  } catch (error) {
    refs.error.hidden = false;
    refs.error.textContent = error.message;
  }
  poll();
}

async function saveSettings(change) {
  try { await api("/api/settings", { method: "PUT", body: change }); } catch (error) { alert("설정 저장 실패: " + error.message); }
  poll();
}

async function loadLog() {
  const item = document.getElementById("log-item").value;
  const output = document.getElementById("log");
  try {
    const data = await api(`/api/logs/${item}?lines=200`);
    const atBottom = output.scrollHeight - output.scrollTop - output.clientHeight < 24;
    document.getElementById("log-file").textContent = data.file ? `파일: ${data.file}` : "기록된 로그가 없습니다.";
    output.textContent = data.lines.length ? data.lines.join("\n") : "(비어 있음)";
    if (atBottom) output.scrollTop = output.scrollHeight;
  } catch (error) {
    output.textContent = "로그를 읽지 못했습니다: " + error.message;
  }
}

function showLog(id) {
  document.getElementById("log-item").value = id;
  loadLog();
  document.getElementById("log").scrollIntoView({ behavior: "smooth", block: "nearest" });
}

async function loadDeps(refresh = false) {
  const list = document.getElementById("deps");
  const button = document.getElementById("deps-refresh");
  button.disabled = true;
  try {
    const data = await api(refresh ? "/api/dependencies/refresh" : "/api/dependencies", refresh ? { method: "POST" } : {});
    list.replaceChildren(...data.dependencies.map((check) => el("li", {},
      el("span", { class: `badge badge-${check.status}` }, DEP_LABELS[check.status] || check.status),
      el("span", {}, el("strong", {}, check.label), " ", el("span", { class: "detail" }, check.detail)))));
  } catch (error) {
    list.replaceChildren(el("li", { class: "muted" }, "점검 실패: " + error.message));
  } finally {
    button.disabled = false;
  }
}

async function loadShortcut(method) {
  const state = document.getElementById("shortcut-state");
  const button = document.getElementById("shortcut-toggle");
  button.disabled = true;
  try {
    const data = await api("/api/startup-shortcut", method ? { method } : {});
    state.textContent = data.exists ? "바로가기가 있습니다. Windows 로그인 시 제어판이 실행됩니다." : "바로가기가 없습니다.";
    button.textContent = data.exists ? "바로가기 삭제" : "바로가기 만들기";
    button.dataset.exists = data.exists ? "1" : "";
  } catch (error) {
    state.textContent = "처리 실패: " + error.message;
  } finally {
    button.disabled = false;
  }
}

document.getElementById("deps-refresh").addEventListener("click", () => loadDeps(true));
document.getElementById("log-item").addEventListener("change", loadLog);
document.getElementById("shortcut-toggle").addEventListener("click", (event) => loadShortcut(event.target.dataset.exists ? "DELETE" : "POST"));
poll();
loadDeps();
loadShortcut();
loadLog();
setInterval(poll, 3000);
setInterval(() => { if (document.getElementById("log-follow").checked) loadLog(); }, 3000);
