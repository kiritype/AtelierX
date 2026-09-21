import assert from "node:assert/strict";
import { createServer } from "node:http";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { Miniflare, convertV4MiniflareOptions } from "miniflare";

test("workerd dispatches a signed draw to the bridge with manual redirect handling", async () => {
  const keyPair = await crypto.subtle.generateKey({ name: "Ed25519" }, true, ["sign", "verify"]);
  const publicKey = hex(new Uint8Array(await crypto.subtle.exportKey("raw", keyPair.publicKey)));
  let receiveBridgeRequest;
  const received = new Promise((resolve) => { receiveBridgeRequest = resolve; });
  const bridge = createServer(async (request, response) => {
    const chunks = [];
    for await (const chunk of request) chunks.push(chunk);
    const payload = JSON.parse(Buffer.concat(chunks).toString("utf8"));
    receiveBridgeRequest({ method: request.method, path: request.url, payload });
    response.writeHead(202, { "content-type": "application/json" });
    response.end(JSON.stringify({ interaction_id: payload.interaction_id, state: "accepted" }));
  });
  await new Promise((resolve) => bridge.listen(0, "127.0.0.1", resolve));
  const port = bridge.address().port;
  const source = await readFile(new URL("../src/worker.js", import.meta.url), "utf8");
  const mf = new Miniflare(convertV4MiniflareOptions({
    modules: true,
    script: source,
    compatibilityDate: "2026-09-21",
    bindings: {
      DISCORD_PUBLIC_KEY: publicKey,
      DISCORD_APPLICATION_ID: "123456789012345678",
      DISCORD_ALLOWED_USER_IDS: "987654321098765432",
      BRIDGE_URL: `http://127.0.0.1:${port}/v1/discord/jobs`,
      BRIDGE_TOKEN: "test-token",
      ALLOW_INSECURE_LOCAL_BRIDGE: "true"
    }
  }));
  try {
    const interaction = { id: "111111111111111111", application_id: "123456789012345678", type: 2, token: "test-token", user: { id: "987654321098765432" }, data: { name: "draw", options: [{ name: "prompt", value: "workerd regression" }] } };
    const raw = JSON.stringify(interaction);
    const timestamp = String(Math.floor(Date.now() / 1000));
    const signature = hex(new Uint8Array(await crypto.subtle.sign("Ed25519", keyPair.privateKey, new TextEncoder().encode(timestamp + raw))));
    const response = await mf.dispatchFetch("http://worker.test/", { method: "POST", headers: { "content-type": "application/json", "X-Signature-Timestamp": timestamp, "X-Signature-Ed25519": signature }, body: raw });
    assert.equal(response.status, 200);
    assert.deepEqual(await response.json(), { type: 5, data: { flags: 64 } });
    const bridgeRequest = await withTimeout(received, 2_000);
    assert.equal(bridgeRequest.method, "POST");
    assert.equal(bridgeRequest.path, "/v1/discord/jobs");
    assert.equal(bridgeRequest.payload.interaction_id, interaction.id);
    assert.equal(bridgeRequest.payload.mode, "natural");
  } finally {
    await mf.dispose();
    await new Promise((resolve, reject) => bridge.close((error) => error ? reject(error) : resolve()));
  }
});

function hex(bytes) { return Array.from(bytes, (value) => value.toString(16).padStart(2, "0")).join(""); }
async function withTimeout(promise, milliseconds) {
  let timer;
  try {
    return await Promise.race([promise, new Promise((_, reject) => { timer = setTimeout(() => reject(new Error("mock bridge did not receive a request")), milliseconds); })]);
  } finally { clearTimeout(timer); }
}
