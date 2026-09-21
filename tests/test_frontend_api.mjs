import assert from "node:assert/strict";
import {readFile} from "node:fs/promises";

globalThis.window = {location: {origin: "http://127.0.0.1:8190"}};
const source = await readFile(new URL("../frontend/api.js", import.meta.url), "utf8");
const {ApiClient, ApiClientError} = await import(`data:text/javascript,${encodeURIComponent(source)}`);

const calls = [];
globalThis.fetch = async (path, options) => {
  calls.push({path, options});
  return {ok: true, status: 200, json: async () => ({ok: true})};
};

const client = new ApiClient({token: "memory-token"});
assert.deepEqual(await client.post("/v1/tasks", {group_id: "group"}, "caller-key"), {ok: true});
assert.equal(calls.length, 1);
assert.equal(calls[0].path, "/v1/tasks");
assert.equal(calls[0].options.headers.Authorization, "Bearer memory-token");
assert.equal(calls[0].options.headers["Idempotency-Key"], "caller-key");
assert.equal(calls[0].options.redirect, "error");
assert.ok(calls[0].options.signal instanceof AbortSignal);
assert.equal(calls[0].options.body, '{"group_id":"group"}');

calls.length = 0;
const tokenless = new ApiClient();
await tokenless.get("/health");
assert.equal(calls[0].options.headers.Authorization, undefined);

await assert.rejects(client.get("https://external.invalid/v1/tasks"), (error) =>
  error instanceof ApiClientError && error.code === "CLIENT_INVALID_PATH");
await assert.rejects(client.get("/v1/../health"), (error) =>
  error instanceof ApiClientError && error.code === "CLIENT_INVALID_PATH");
await assert.rejects(client.get("/v1/settings#fragment"), (error) =>
  error instanceof ApiClientError && error.code === "CLIENT_INVALID_PATH");

globalThis.fetch = async () => ({
  ok: false, status: 409,
  json: async () => ({error: {code: "CORE_REVISION_CONFLICT", message: "Revision changed"}}),
});
await assert.rejects(client.get("/v1/settings"), (error) =>
  error instanceof ApiClientError && error.code === "CORE_REVISION_CONFLICT" && error.status === 409);

let transportCalls = 0;
globalThis.fetch = async () => { transportCalls += 1; throw new TypeError("offline"); };
await assert.rejects(client.post("/v1/tasks", {group_id: "group"}, "offline-key"), (error) =>
  error instanceof ApiClientError && error.code === "CLIENT_TRANSPORT_ERROR" && error.status === 503);
assert.equal(transportCalls, 1);

globalThis.fetch = async () => ({ok: false, status: 401, json: async () => ({error: {code: "CORE_UNAUTHORIZED", message: "Bearer token required"}})});
await assert.rejects(client.get("/health"), (error) =>
  error instanceof ApiClientError && error.code === "CORE_UNAUTHORIZED" && error.status === 401);

globalThis.fetch = async () => ({ok: true, status: 200, json: async () => { throw new SyntaxError("bad json"); }});
await assert.rejects(client.get("/v1/settings"), (error) =>
  error instanceof ApiClientError && error.code === "CLIENT_PROTOCOL_ERROR" && error.status === 502);

const circular = {}; circular.self = circular;
const beforeCircular = transportCalls;
await assert.rejects(client.post("/v1/tasks", circular, "circular-key"), (error) =>
  error instanceof ApiClientError && error.code === "CLIENT_INVALID_BODY" && error.status === 400);
assert.equal(transportCalls, beforeCircular);

globalThis.fetch = async (_path, options) => new Promise((_resolve, reject) => {
  options.signal.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")));
});
await assert.rejects(new ApiClient({token: "memory-token", timeoutMs: 1}).get("/v1/settings"), (error) =>
  error instanceof ApiClientError && error.code === "CLIENT_TIMEOUT" && error.status === 504);

globalThis.fetch = async (_path, options) => ({ok: true, status: 200, json: () => new Promise((_resolve, reject) => {
  options.signal.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")));
})});
await assert.rejects(new ApiClient({token: "memory-token", timeoutMs: 1}).get("/v1/settings"), (error) =>
  error instanceof ApiClientError && error.code === "CLIENT_TIMEOUT" && error.status === 504);

globalThis.fetch = async (_path, options) => ({ok: true, status: 200, blob: () => new Promise((_resolve, reject) => {
  options.signal.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")));
})});
await assert.rejects(new ApiClient({token: "memory-token", timeoutMs: 1}).imageBlob("/v1/images/image/content"), (error) =>
  error instanceof ApiClientError && error.code === "CLIENT_TIMEOUT" && error.status === 504);

globalThis.fetch = async () => ({ok: false, status: 401, json: async () => ({error: {code: "CORE_UNAUTHORIZED", message: "Bearer token required"}})});
await assert.rejects(client.imageBlob("/v1/images/image/content"), (error) =>
  error instanceof ApiClientError && error.code === "CORE_UNAUTHORIZED" && error.status === 401);
assert.throws(() => new ApiClient({timeoutMs: 0}), TypeError);
