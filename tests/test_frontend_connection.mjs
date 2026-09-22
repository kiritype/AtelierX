import assert from "node:assert/strict";
import {readFile} from "node:fs/promises";

const source = await readFile(new URL("../frontend/connection.js", import.meta.url), "utf8");
const {autoConnection, connectionMessage} = await import(`data:text/javascript,${encodeURIComponent(source)}`);
const settingsSource = await readFile(new URL("../frontend/settings.js", import.meta.url), "utf8");
const {connectionProblem, connectionDisplay} = await import(`data:text/javascript,${encodeURIComponent(settingsSource)}`);

const run = async (responses) => {
  const calls = [];
  class FakeApi {
    constructor(options = {}) { calls.push({kind: "constructor", options}); }
    async get(path) {
      calls.push({kind: "get", path});
      const response = responses.shift();
      if (response instanceof Error) throw response;
      if (response?.error) throw response.error;
      return response;
    }
  }
  return {result: await autoConnection(FakeApi), calls};
};

let outcome = await run([{ok: true}]);
assert.equal(outcome.result.kind, "connected");
assert.deepEqual(outcome.calls, [{kind: "constructor", options: {}}, {kind: "get", path: "/health"}]);

outcome = await run([{error: {status: 401}}, {configured: true, connected: false, auth_mode: "cloudflare_access", token_configured: true, public_origin: "https://studio.example"}]);
assert.equal(outcome.result.kind, "connection_settings");
assert.deepEqual(outcome.calls.map(({kind, path}) => ({kind, path})), [{kind: "constructor", path: undefined}, {kind: "get", path: "/health"}, {kind: "get", path: "/v1/frontend-connection"}]);

outcome = await run([{error: {status: 401}}, {error: {status: 404}}]);
assert.equal(outcome.result.kind, "manual");
assert.ok(outcome.result.api, "manual connection keeps an API client for the Settings page");

outcome = await run([{error: {status: 401}}, {error: {status: 403}}]);
assert.equal(outcome.result.kind, "auth_required");
assert.match(connectionMessage(outcome.result, "https://studio.example"), /Cloudflare Access/);

outcome = await run([{error: {status: 503}}]);
assert.equal(outcome.result.kind, "unreachable");
assert.ok(outcome.result.api, "unreachable connection still opens Settings");
assert.match(connectionMessage(outcome.result, "https://studio.example"), /네트워크/);

assert.match(connectionProblem({status: 401}).detail, /Cloudflare Access/);
assert.match(connectionProblem({status: 503}).title, /연결할 수 없습니다/);
assert.deepEqual(connectionDisplay({auth_mode: "bearer", configured: false, connected: false, public_origin: null}), {
  auth: "Bearer", browserMemory: true, canSave: false
});
assert.deepEqual(connectionDisplay({auth_mode: "cloudflare_access", configured: true, connected: true}), {
  auth: "Cloudflare Access", browserMemory: false, canSave: true
});
