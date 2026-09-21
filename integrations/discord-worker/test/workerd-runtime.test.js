import assert from "node:assert/strict";
import { createServer } from "node:http";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { Miniflare, convertV4MiniflareOptions } from "miniflare";

test("workerd makes guild draw public while status remains ephemeral", async () => {
  const keyPair = await crypto.subtle.generateKey({ name: "Ed25519" }, true, ["sign", "verify"]);
  const publicKey = hex(new Uint8Array(await crypto.subtle.exportKey("raw", keyPair.publicKey)));
  const bridgeRequests = [];
  let receiveBridgeRequests;
  const received = new Promise((resolve) => { receiveBridgeRequests = resolve; });
  const bridge = createServer(async (request, response) => {
    const chunks = [];
    for await (const chunk of request) chunks.push(chunk);
    const payload = JSON.parse(Buffer.concat(chunks).toString("utf8"));
    bridgeRequests.push({ method: request.method, path: request.url, payload });
    if (bridgeRequests.length === 2) receiveBridgeRequests(bridgeRequests);
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
      DISCORD_ACCESS_MODE: "guild",
      DISCORD_PUBLIC_RESULTS: "true",
      DISCORD_ALLOWED_GUILD_IDS: "444444444444444444",
      DISCORD_ALLOWED_CHANNEL_IDS: "555555555555555555",
      BRIDGE_URL: `http://127.0.0.1:${port}/v1/discord/jobs`,
      BRIDGE_TOKEN: "test-token",
      ALLOW_INSECURE_LOCAL_BRIDGE: "true"
    }
  }));
  try {
    const draw = { id: "111111111111111111", application_id: "123456789012345678", type: 2, token: "test-token", guild_id: "444444444444444444", channel_id: "555555555555555555", member: { user: { id: "987654321098765432" } }, data: { name: "draw", options: [{ name: "prompt", value: "workerd regression" }, { name: "negative", value: "no watermark" }, { name: "mode", value: " DIRECT " }] } };
    const status = { id: "222222222222222222", application_id: "123456789012345678", type: 2, token: "status-token", guild_id: "444444444444444444", channel_id: "555555555555555555", member: { user: { id: "987654321098765432" } }, data: { name: "status", options: [{ name: "request_id", value: "333333333333333333" }] } };
    const drawResponse = await dispatchSigned(mf, keyPair, draw);
    const statusResponse = await dispatchSigned(mf, keyPair, status);
    assert.deepEqual(await drawResponse.json(), { type: 5, data: { flags: 0 } });
    assert.deepEqual(await statusResponse.json(), { type: 5, data: { flags: 64 } });
    const requests = await withTimeout(received, 2_000);
    assert.equal(requests[0].method, "POST");
    assert.equal(requests[0].path, "/v1/discord/jobs");
    assert.equal(requests[1].path, "/v1/discord/status");
    assert.equal(requests[0].payload.interaction_id, draw.id);
    assert.equal(requests[0].payload.mode, "direct");
    assert.equal(requests[0].payload.negative_prompt, "no watermark");
    assert.equal(requests[0].payload.guild_id, draw.guild_id);
    assert.equal(requests[1].payload.channel_id, status.channel_id);
  } finally {
    await mf.dispose();
    await new Promise((resolve, reject) => bridge.close((error) => error ? reject(error) : resolve()));
  }
});

async function dispatchSigned(mf, keyPair, interaction) {
  const raw = JSON.stringify(interaction);
  const timestamp = String(Math.floor(Date.now() / 1000));
  const signature = hex(new Uint8Array(await crypto.subtle.sign("Ed25519", keyPair.privateKey, new TextEncoder().encode(timestamp + raw))));
  return mf.dispatchFetch("http://worker.test/", { method: "POST", headers: { "content-type": "application/json", "X-Signature-Timestamp": timestamp, "X-Signature-Ed25519": signature }, body: raw });
}

function hex(bytes) { return Array.from(bytes, (value) => value.toString(16).padStart(2, "0")).join(""); }
async function withTimeout(promise, milliseconds) {
  let timer;
  try {
    return await Promise.race([promise, new Promise((_, reject) => { timer = setTimeout(() => reject(new Error("mock bridge did not receive a request")), milliseconds); })]);
  } finally { clearTimeout(timer); }
}
