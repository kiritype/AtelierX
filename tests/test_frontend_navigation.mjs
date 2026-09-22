import assert from "node:assert/strict";
import {readFile} from "node:fs/promises";
import test from "node:test";
import vm from "node:vm";

class Element {
  constructor() { this.hidden = false; this.textContent = ""; this.className = ""; this.children = []; this.dataset = {}; this.classList = {toggle() {}}; }
  addEventListener() {}
  setAttribute() {}
  replaceChildren(...children) { this.children = children; }
  focus() {}
}

async function harness(loadPage) {
  let source = await readFile(new URL("../frontend/app.js", import.meta.url), "utf8");
  source = source.replace(/^import .*?\r?\n/gm, "").replace("import(`./${page}.js`)", "globalThis.__loadPage(page)").replace(/\r?\nstart\(\);\s*$/, "\nglobalThis.__appTest={navigate,setApi:(value)=>api=value,main};");
  const elements = new Map(["#workspace", "#notice", "#page-title", "#page-description", ".skip-link", ".brand", "#connection-toggle", "#connection-panel", "#connection-form", "#core-token", "#connection-status"].map((key) => [key, new Element()]));
  const pushes = [];
  const context = {AbortController, ApiClient: class {}, __loadPage: loadPage, console,
    document: {querySelector: (selector) => elements.get(selector), querySelectorAll: () => [], createElement: () => new Element()},
    window: {scrollY: 0, confirm: () => true, scrollTo() {}, addEventListener() {}, location: {origin: "http://studio.test"}},
    history: {pushState: (...args) => pushes.push(args), replaceState() {}}, location: {hash: ""}};
  context.globalThis = context;
  vm.runInNewContext(source, context, {filename: "frontend/app.js"});
  return {...context.__appTest, pushes};
}

test("navigation skips an active route, refreshes when forced, and remounts after a detail route", async () => {
  let mounts = 0;
  let detail;
  const app = await harness(async () => ({mount: async (_host, ctx) => { mounts += 1; detail = ctx.onDetailChange; if (mounts === 1) detail("during-mount"); return () => {}; }}));
  app.setApi({});
  await app.navigate("production");
  await app.navigate("production", "during-mount", true);
  assert.equal(mounts, 1);
  await app.navigate("production");
  assert.equal(mounts, 2);
  await app.navigate("production", undefined, true, true);
  assert.equal(mounts, 3);
  detail("plan-1");
  await app.navigate("production", undefined, true);
  assert.equal(mounts, 4);
});

test("a slow mount is aborted and disposed after a faster navigation replaces its host", async () => {
  let release;
  const slow = new Promise((resolve) => { release = resolve; });
  let slowContext;
  let slowDisposed = 0;
  const app = await harness(async (page) => ({mount: async (host, ctx) => {
    if (page === "production") { slowContext = ctx; await slow; return () => { slowDisposed += 1; }; }
    host.textContent = "gallery ready";
    return () => {};
  }}));
  app.setApi({});
  const pending = app.navigate("production", "slow");
  await new Promise(setImmediate);
  const gallery = app.navigate("gallery");
  await gallery;
  assert.equal(slowContext.signal.aborted, true);
  const pushes = app.pushes.length;
  slowContext.onDetailChange("stale");
  assert.equal(app.pushes.length, pushes);
  assert.equal(app.main.children[0].textContent, "gallery ready");
  release();
  await pending;
  assert.equal(slowDisposed, 1);
  assert.equal(app.main.children[0].textContent, "gallery ready");
});
