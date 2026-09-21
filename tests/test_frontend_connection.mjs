import assert from "node:assert/strict";
import {readFile} from "node:fs/promises";

const source = await readFile(new URL("../frontend/connection.js", import.meta.url), "utf8");
const {autoConnection, connectionMessage} = await import(`data:text/javascript,${encodeURIComponent(source)}`);

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

outcome = await run([{error: {status: 401}}, {error: {status: 403}}]);
assert.equal(outcome.result.kind, "auth_required");
assert.match(connectionMessage(outcome.result, "https://studio.example"), /Cloudflare Access/);

outcome = await run([{error: {status: 503}}]);
assert.equal(outcome.result.kind, "unreachable");
assert.match(connectionMessage(outcome.result, "https://studio.example"), /네트워크/);
