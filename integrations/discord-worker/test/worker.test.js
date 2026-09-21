import assert from "node:assert/strict";
import test from "node:test";
import { handleInteraction } from "../src/worker.js";

const now = 1_790_000_000;
const keyPair = await crypto.subtle.generateKey({ name: "Ed25519" }, true, ["sign", "verify"]);
const publicKeyHex = toHex(new Uint8Array(await crypto.subtle.exportKey("raw", keyPair.publicKey)));
const baseEnv = {
  DISCORD_PUBLIC_KEY: publicKeyHex,
  DISCORD_APPLICATION_ID: "123456789012345678",
  DISCORD_ALLOWED_USER_IDS: "987654321098765432,876543210987654321",
  BRIDGE_URL: "https://bridge.example/v1/discord/jobs",
  BRIDGE_TOKEN: "test-token"
};

test("valid signed PING returns PONG without bridge dispatch", async () => {
  const { request, ctx } = await signedRequest({ type: 1 });
  const response = await handleInteraction(request, baseEnv, ctx, { now: () => now, fetch: unexpectedFetch });
  assert.equal(response.status, 200);
  assert.deepEqual(await response.json(), { type: 1 });
  assert.equal(ctx.promises.length, 0);
});

test("rejects an invalid signature before parsing or dispatch", async () => {
  const request = new Request("https://worker.example", { method: "POST", headers: { "X-Signature-Timestamp": String(now), "X-Signature-Ed25519": "00".repeat(64) }, body: "{}" });
  const ctx = context();
  const response = await handleInteraction(request, baseEnv, ctx, { now: () => now, fetch: unexpectedFetch });
  assert.equal(response.status, 401);
  assert.equal(ctx.promises.length, 0);
});

test("rejects stale signature and unauthorized Discord user", async () => {
  const stale = await signedRequest(drawInteraction(), now - 301);
  const staleResponse = await handleInteraction(stale.request, baseEnv, stale.ctx, { now: () => now, fetch: unexpectedFetch });
  assert.equal(staleResponse.status, 401);
  const denied = await signedRequest(drawInteraction({ userId: "111111111111111111" }));
  const deniedResponse = await handleInteraction(denied.request, baseEnv, denied.ctx, { now: () => now, fetch: unexpectedFetch });
  assert.equal(deniedResponse.status, 403);
  const secondAllowed = await signedRequest(drawInteraction({ userId: "876543210987654321" }));
  const secondAllowedResponse = await handleInteraction(secondAllowed.request, baseEnv, secondAllowed.ctx, { now: () => now, fetch: acceptedFetch });
  assert.equal(secondAllowedResponse.status, 200);
  await Promise.all(secondAllowed.ctx.promises);
});

test("rejects invalid draw input before the deferred response", async () => {
  const invalid = drawInteraction({ prompt: "", mode: "other" });
  const { request, ctx } = await signedRequest(invalid);
  const response = await handleInteraction(request, baseEnv, ctx, { now: () => now, fetch: unexpectedFetch });
  assert.equal(response.status, 400);
  assert.equal(ctx.promises.length, 0);
});

test("rejects malformed or overlong optional negative prompts before the deferred response", async () => {
  for (const negative of [42, "x".repeat(4001)]) {
    const { request, ctx } = await signedRequest(drawInteraction({ negative }));
    const response = await handleInteraction(request, baseEnv, ctx, { now: () => now, fetch: unexpectedFetch });
    assert.equal(response.status, 400);
    assert.equal(ctx.promises.length, 0);
  }
});

test("rejects malformed or overlong optional checkpoint values before the deferred response", async () => {
  for (const checkpoint of [42, " ", "x".repeat(101)]) {
    const { request, ctx } = await signedRequest(drawInteraction({ checkpoint }));
    const response = await handleInteraction(request, baseEnv, ctx, { now: () => now, fetch: unexpectedFetch });
    assert.equal(response.status, 400);
    assert.equal(ctx.promises.length, 0);
  }
});

test("guild public draw is visible, while status remains ephemeral", async () => {
  const guildEnv = { ...baseEnv, DISCORD_ACCESS_MODE: "guild", DISCORD_PUBLIC_RESULTS: "true", DISCORD_ALLOWED_GUILD_IDS: "444444444444444444", DISCORD_ALLOWED_CHANNEL_IDS: "555555555555555555" };
  const dm = await signedRequest(drawInteraction({ userId: "111111111111111111" }));
  const dmResponse = await handleInteraction(dm.request, guildEnv, dm.ctx, { now: () => now, fetch: unexpectedFetch });
  assert.equal(dmResponse.status, 403);
  const wrongGuild = await signedRequest(guildDrawInteraction({ guildId: "666666666666666666" }));
  const wrongGuildResponse = await handleInteraction(wrongGuild.request, guildEnv, wrongGuild.ctx, { now: () => now, fetch: unexpectedFetch });
  assert.equal(wrongGuildResponse.status, 403);
  const wrongChannel = await signedRequest(guildDrawInteraction({ channelId: "666666666666666666" }));
  const wrongChannelResponse = await handleInteraction(wrongChannel.request, guildEnv, wrongChannel.ctx, { now: () => now, fetch: unexpectedFetch });
  assert.equal(wrongChannelResponse.status, 403);
  const validNonOwner = await signedRequest(guildDrawInteraction({ userId: "111111111111111111" }));
  const calls = [];
  const validResponse = await handleInteraction(validNonOwner.request, guildEnv, validNonOwner.ctx, { now: () => now, fetch: async (url, init) => {
    calls.push({ url, init });
    return Response.json({ interaction_id: "111111111111111111", state: "accepted" }, { status: 202 });
  } });
  assert.equal(validResponse.status, 200);
  assert.deepEqual(await validResponse.json(), { type: 5, data: { flags: 0 } });
  await Promise.all(validNonOwner.ctx.promises);
  const payload = JSON.parse(calls[0].init.body);
  assert.equal(payload.user_id, "111111111111111111");
  assert.equal(payload.guild_id, "444444444444444444");
  assert.equal(payload.channel_id, "555555555555555555");
  const status = await signedRequest(guildStatusInteraction());
  const statusResponse = await handleInteraction(status.request, guildEnv, status.ctx, { now: () => now, fetch: acceptedFetch });
  assert.deepEqual(await statusResponse.json(), { type: 5, data: { flags: 64 } });
  await Promise.all(status.ctx.promises);
});

test("guild mode fails closed for malformed configured identifiers", async () => {
  const guildEnv = { ...baseEnv, DISCORD_ACCESS_MODE: "guild", DISCORD_ALLOWED_GUILD_IDS: "444444444444444444,not-an-id" };
  const interaction = await signedRequest(guildDrawInteraction());
  const response = await handleInteraction(interaction.request, guildEnv, interaction.ctx, { now: () => now, fetch: unexpectedFetch });
  assert.equal(response.status, 500);
});

test("public results fail closed outside guild mode", async () => {
  const interaction = await signedRequest(drawInteraction());
  const response = await handleInteraction(interaction.request, { ...baseEnv, DISCORD_PUBLIC_RESULTS: "true" }, interaction.ctx, { now: () => now, fetch: unexpectedFetch });
  assert.equal(response.status, 500);
});

test("defers an ephemeral draw and sends the exact normalized job once", async () => {
  const { request, ctx } = await signedRequest(drawInteraction({ prompt: "draw a fox", negative: "no text", checkpoint: "anima.safetensors", mode: " NATURAL " }));
  const calls = [];
  const response = await handleInteraction(request, baseEnv, ctx, { now: () => now, fetch: async (url, init) => {
    calls.push({ url, init });
    return Response.json({ interaction_id: "111111111111111111", state: "accepted" }, { status: 202 });
  } });
  assert.deepEqual(await response.json(), { type: 5, data: { flags: 64 } });
  assert.equal(ctx.promises.length, 1);
  await Promise.all(ctx.promises);
  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, "https://bridge.example/v1/discord/jobs");
  assert.equal(calls[0].init.redirect, "manual");
  assert.deepEqual(JSON.parse(calls[0].init.body), {
    interaction_id: "111111111111111111", application_id: baseEnv.DISCORD_APPLICATION_ID, interaction_token: "interaction-token", user_id: "987654321098765432",
    attachment_size_limit: 10485760, received_at: now, prompt: "draw a fox", mode: "natural", negative_prompt: "no text", checkpoint: "anima.safetensors"
  });
});

test("uses direct mode by default and omits an absent negative prompt", async () => {
  const { request, ctx } = await signedRequest(drawInteraction({ omitMode: true }));
  const calls = [];
  const response = await handleInteraction(request, baseEnv, ctx, { now: () => now, fetch: async (url, init) => {
    calls.push({ url, init });
    return Response.json({ interaction_id: "111111111111111111", state: "accepted" }, { status: 202 });
  } });
  assert.equal(response.status, 200);
  await Promise.all(ctx.promises);
  const payload = JSON.parse(calls[0].init.body);
  assert.equal(payload.mode, "direct");
  assert.equal(Object.hasOwn(payload, "negative_prompt"), false);
});

test("forwards an explicitly empty negative prompt unchanged", async () => {
  const { request, ctx } = await signedRequest(drawInteraction({ negative: "", omitMode: true }));
  const calls = [];
  const response = await handleInteraction(request, baseEnv, ctx, { now: () => now, fetch: async (url, init) => {
    calls.push({ url, init });
    return Response.json({ interaction_id: "111111111111111111", state: "accepted" }, { status: 202 });
  } });
  assert.equal(response.status, 200);
  await Promise.all(ctx.promises);
  assert.equal(JSON.parse(calls[0].init.body).negative_prompt, "");
});

test("a bridge 5xx is acceptance-unknown and never retries dispatch", async () => {
  const { request, ctx } = await signedRequest(drawInteraction());
  const calls = [];
  const response = await handleInteraction(request, baseEnv, ctx, { now: () => now, fetch: async (url, init) => {
    calls.push({ url, init });
    if (url === baseEnv.BRIDGE_URL) return new Response(null, { status: 503 });
    return new Response(null, { status: 200 });
  } });
  assert.equal(response.status, 200);
  await Promise.all(ctx.promises);
  assert.equal(calls.filter((call) => call.url === baseEnv.BRIDGE_URL).length, 1);
  const edit = calls.find((call) => call.init.method === "PATCH");
  assert.match(edit.url, /^https:\/\/discord\.com\/api\/v10\/webhooks\//);
  assert.match(JSON.parse(edit.init.body).content, /acceptance is unknown/);
});

test("a bridge redirect is not followed and is reported as acceptance-unknown", async () => {
  const { request, ctx } = await signedRequest(drawInteraction());
  const calls = [];
  await handleInteraction(request, baseEnv, ctx, { now: () => now, fetch: async (url, init) => {
    calls.push({ url, init });
    if (url === baseEnv.BRIDGE_URL) return new Response(null, { status: 302, headers: { location: "https://untrusted.example/" } });
    return new Response(null, { status: 200 });
  } });
  await Promise.all(ctx.promises);
  assert.equal(calls.filter((call) => call.url === baseEnv.BRIDGE_URL).length, 1);
  assert.equal(calls[0].init.redirect, "manual");
  assert.equal(calls.some((call) => call.url === "https://untrusted.example/"), false);
  assert.equal(calls.find((call) => call.init.method === "PATCH").init.redirect, "manual");
});

test("status uses its status bridge path and a fresh interaction token", async () => {
  const { request, ctx } = await signedRequest(statusInteraction());
  const calls = [];
  await handleInteraction(request, baseEnv, ctx, { now: () => now, fetch: async (url, init) => {
    calls.push({ url, init });
    return Response.json({ interaction_id: "222222222222222222", state: "complete" }, { status: 200 });
  } });
  await Promise.all(ctx.promises);
  assert.equal(calls[0].url, "https://bridge.example/v1/discord/status");
  assert.deepEqual(JSON.parse(calls[0].init.body), {
    interaction_id: "222222222222222222", application_id: baseEnv.DISCORD_APPLICATION_ID, interaction_token: "new-status-token", user_id: "987654321098765432",
    attachment_size_limit: 10485760, received_at: now, request_id: "333333333333333333"
  });
});

function drawInteraction({ prompt = "a watercolor fox", negative, checkpoint, mode = "direct", omitMode = false, userId = "987654321098765432" } = {}) {
  const options = [{ name: "prompt", value: prompt }];
  if (negative !== undefined) options.push({ name: "negative", value: negative });
  if (checkpoint !== undefined) options.push({ name: "checkpoint", value: checkpoint });
  if (!omitMode) options.push({ name: "mode", value: mode });
  return { id: "111111111111111111", application_id: baseEnv.DISCORD_APPLICATION_ID, type: 2, token: "interaction-token", attachment_size_limit: 10485760, member: { user: { id: userId } }, data: { name: "draw", options } };
}
function guildDrawInteraction({ userId = "111111111111111111", guildId = "444444444444444444", channelId = "555555555555555555" } = {}) {
  return { id: "111111111111111111", application_id: baseEnv.DISCORD_APPLICATION_ID, type: 2, token: "interaction-token", attachment_size_limit: 10485760, guild_id: guildId, channel_id: channelId, member: { user: { id: userId } }, data: { name: "draw", options: [{ name: "prompt", value: "guild request" }] } };
}
function guildStatusInteraction() {
  return { id: "222222222222222222", application_id: baseEnv.DISCORD_APPLICATION_ID, type: 2, token: "status-token", attachment_size_limit: 10485760, guild_id: "444444444444444444", channel_id: "555555555555555555", member: { user: { id: "111111111111111111" } }, data: { name: "status", options: [{ name: "request_id", value: "333333333333333333" }] } };
}
function statusInteraction() { return { id: "222222222222222222", application_id: baseEnv.DISCORD_APPLICATION_ID, type: 2, token: "new-status-token", attachment_size_limit: 10485760, user: { id: "987654321098765432" }, data: { name: "status", options: [{ name: "request_id", value: "333333333333333333" }] } }; }
async function signedRequest(body, timestamp = now) {
  const raw = JSON.stringify(body);
  const signature = new Uint8Array(await crypto.subtle.sign("Ed25519", keyPair.privateKey, new TextEncoder().encode(String(timestamp) + raw)));
  return { request: new Request("https://worker.example", { method: "POST", headers: { "content-type": "application/json", "X-Signature-Timestamp": String(timestamp), "X-Signature-Ed25519": toHex(signature) }, body: raw }), ctx: context() };
}
function context() { return { promises: [], waitUntil(promise) { this.promises.push(promise); } }; }
function toHex(bytes) { return Array.from(bytes, (value) => value.toString(16).padStart(2, "0")).join(""); }
async function unexpectedFetch() { throw new Error("fetch should not run"); }
async function acceptedFetch(url, init) { return Response.json({ interaction_id: JSON.parse(init.body).interaction_id, state: "accepted" }, { status: 202 }); }
