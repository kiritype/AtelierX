const MAX_BODY_BYTES = 64 * 1024;
const MAX_PROMPT_CODE_POINTS = 4000;
const MAX_REQUEST_ID_CODE_POINTS = 200;
const DEFAULT_ATTACHMENT_SIZE_LIMIT = 10 * 1024 * 1024;
const SIGNATURE_MAX_AGE_SECONDS = 5 * 60;
const BRIDGE_TIMEOUT_MS = 8_000;
const DISCORD_TIMEOUT_MS = 5_000;
const DISCORD_API_BASE = "https://discord.com/api/v10";

export default {
  async fetch(request, env, ctx) {
    try {
      return await handleInteraction(request, env, ctx);
    } catch {
      console.error(JSON.stringify({ event: "discord_interaction_unhandled" }));
      return jsonResponse({ error: "internal_error" }, 500);
    }
  },
};

export async function handleInteraction(request, env, ctx, dependencies = {}) {
  const now = dependencies.now ?? (() => Math.floor(Date.now() / 1000));
  const fetchImpl = dependencies.fetch ?? fetch;
  if (request.method !== "POST") return jsonResponse({ error: "method_not_allowed" }, 405);

  const config = getConfig(env);
  if (!config.ok) return jsonResponse({ error: "misconfigured" }, 500);

  const raw = await readLimitedBody(request, MAX_BODY_BYTES);
  if (!raw.ok) return jsonResponse({ error: raw.error }, raw.status);
  const timestamp = request.headers.get("X-Signature-Timestamp");
  const signature = request.headers.get("X-Signature-Ed25519");
  if (!isFreshTimestamp(timestamp, now())) return jsonResponse({ error: "invalid_signature" }, 401);
  if (!await verifyDiscordSignature(config.publicKey, signature, timestamp, raw.text)) {
    return jsonResponse({ error: "invalid_signature" }, 401);
  }

  const interaction = parseJson(raw.text);
  if (!interaction) return jsonResponse({ error: "invalid_interaction" }, 400);
  if (interaction.type === 1) {
    if (isNonEmptyString(interaction.application_id) && interaction.application_id !== config.applicationId) return jsonResponse({ error: "invalid_application" }, 401);
    return jsonResponse({ type: 1 }, 200);
  }
  if (!config.ready) return jsonResponse({ error: "misconfigured" }, 500);
  if (interaction.application_id !== config.applicationId) return jsonResponse({ error: "invalid_application" }, 401);

  const access = authorizeInteraction(interaction, config);
  if (!access.authorized) {
    return jsonResponse({ error: "forbidden" }, 403);
  }

  const command = normalizeCommand(interaction, now(), access);
  if (!command.ok) return jsonResponse({ error: command.error }, 400);
  ctx.waitUntil(dispatchAndReport(command, config, fetchImpl));
  return jsonResponse({ type: 5, data: { flags: 64 } }, 200);
}

function getConfig(env) {
  const publicKey = env.DISCORD_PUBLIC_KEY;
  const applicationId = env.DISCORD_APPLICATION_ID;
  const accessMode = env.DISCORD_ACCESS_MODE ?? "users";
  const allowedUserIds = parseSnowflakeList(env.DISCORD_ALLOWED_USER_IDS ?? env.DISCORD_ALLOWED_USER_ID);
  const allowedGuildIds = parseSnowflakeList(env.DISCORD_ALLOWED_GUILD_IDS);
  const allowedChannelIds = env.DISCORD_ALLOWED_CHANNEL_IDS === undefined ? [] : parseSnowflakeList(env.DISCORD_ALLOWED_CHANNEL_IDS);
  const bridgeUrl = validateBridgeUrl(env.BRIDGE_URL, env.ALLOW_INSECURE_LOCAL_BRIDGE);
  if (!isHex(publicKey, 64)) return { ok: false };
  const validAccessConfig = (accessMode === "users" && allowedUserIds !== null)
    || (accessMode === "guild" && allowedGuildIds !== null && allowedChannelIds !== null);
  return {
    ok: true,
    ready: isSnowflake(applicationId) && validAccessConfig && Boolean(bridgeUrl) && isNonEmptyString(env.BRIDGE_TOKEN) && hasCompleteAccessToken(env),
    publicKey, applicationId, accessMode, allowedUserIds, allowedGuildIds, allowedChannelIds, bridgeUrl, bridgeToken: env.BRIDGE_TOKEN, accessClientId: env.CF_ACCESS_CLIENT_ID, accessClientSecret: env.CF_ACCESS_CLIENT_SECRET
  };
}

function authorizeInteraction(interaction, config) {
  if (config.accessMode === "users") {
    const userId = interaction.member?.user?.id ?? interaction.user?.id;
    return isSnowflake(userId) && config.allowedUserIds.includes(userId) ? { authorized: true, userId, mode: "users" } : { authorized: false };
  }
  const userId = interaction.member?.user?.id;
  const guildId = interaction.guild_id;
  const channelId = interaction.channel_id;
  const channelAllowed = config.allowedChannelIds.length === 0 || config.allowedChannelIds.includes(channelId);
  return isSnowflake(userId) && isSnowflake(guildId) && isSnowflake(channelId) && config.allowedGuildIds.includes(guildId) && channelAllowed
    ? { authorized: true, userId, guildId, channelId, mode: "guild" }
    : { authorized: false };
}

function normalizeCommand(interaction, receivedAt, access) {
  if (interaction.type !== 2 || !isNonEmptyString(interaction.id) || !isNonEmptyString(interaction.token)) return { ok: false, error: "unsupported_interaction" };
  const options = Array.isArray(interaction.data?.options) ? interaction.data.options : [];
  const option = (name) => options.find((candidate) => candidate?.name === name)?.value;
  const base = { interaction_id: interaction.id, application_id: interaction.application_id, interaction_token: interaction.token, user_id: access.userId, attachment_size_limit: normalizeAttachmentLimit(interaction.attachment_size_limit), received_at: receivedAt, ...(access.mode === "guild" ? { guild_id: access.guildId, channel_id: access.channelId } : {}) };
  if (interaction.data?.name === "draw") {
    const prompt = option("prompt");
    const requestedMode = option("mode");
    const mode = requestedMode === undefined ? "natural" : requestedMode;
    if (!isBoundedString(prompt, MAX_PROMPT_CODE_POINTS) || (mode !== "natural" && mode !== "direct")) return { ok: false, error: "invalid_draw" };
    return { ok: true, payload: { ...base, prompt, mode }, bridgePath: "/v1/discord/jobs", kind: "draw" };
  }
  if (interaction.data?.name === "status") {
    const requestId = option("request_id");
    if (!isBoundedString(requestId, MAX_REQUEST_ID_CODE_POINTS) || !isSnowflake(requestId)) return { ok: false, error: "invalid_status" };
    return { ok: true, payload: { ...base, request_id: requestId }, bridgePath: "/v1/discord/status", kind: "status" };
  }
  return { ok: false, error: "unsupported_command" };
}

async function dispatchAndReport(command, config, fetchImpl) {
  const bridgeUrl = new URL(config.bridgeUrl);
  bridgeUrl.pathname = command.bridgePath;
  const result = await postJson(fetchImpl, bridgeUrl.toString(), command.payload, bridgeHeaders(config), BRIDGE_TIMEOUT_MS);
  if (result.accepted) {
    console.log(JSON.stringify({ event: "bridge_accepted", command: command.kind, interaction_id: command.payload.interaction_id, state: result.state }));
    return;
  }
  const message = result.definiteFailure
    ? `The local bridge rejected this request (request ${command.payload.interaction_id}).`
    : `Request ${command.payload.interaction_id} may have reached the local bridge, but acceptance is unknown. It was not sent again automatically.`;
  console.error(JSON.stringify({ event: "bridge_dispatch_failed", command: command.kind, interaction_id: command.payload.interaction_id, outcome: result.definiteFailure ? "rejected" : "unknown", reason: result.reason, bridge_status: result.status ?? null }));
  await editOriginalResponse(fetchImpl, command.payload, message);
}

async function postJson(fetchImpl, url, body, headers, timeoutMs) {
  try {
    const { response, text } = await fetchJsonWithDeadline(fetchImpl, url, { method: "POST", headers: { ...headers, "content-type": "application/json" }, body: JSON.stringify(body) }, timeoutMs);
    if (response.status >= 400 && response.status < 500) return { accepted: false, definiteFailure: true, reason: "bridge_http_4xx", status: response.status };
    if (response.status >= 500) return { accepted: false, definiteFailure: false, reason: "bridge_http_5xx", status: response.status };
    if (response.status !== 200 && response.status !== 202) return { accepted: false, definiteFailure: false, reason: "bridge_http_unexpected", status: response.status };
    const payload = parseJson(text);
    if (payload?.interaction_id === body.interaction_id && isNonEmptyString(payload.state)) return { accepted: true, state: payload.state };
    return { accepted: false, definiteFailure: false, reason: "bridge_response_invalid", status: response.status };
  } catch (error) {
    return { accepted: false, definiteFailure: false, reason: error?.name === "AbortError" ? "bridge_timeout" : "bridge_transport_error" };
  }
}

function bridgeHeaders(config) {
  const headers = { authorization: `Bearer ${config.bridgeToken}` };
  if (isNonEmptyString(config.accessClientId) && isNonEmptyString(config.accessClientSecret)) {
    headers["CF-Access-Client-Id"] = config.accessClientId;
    headers["CF-Access-Client-Secret"] = config.accessClientSecret;
  }
  return headers;
}

async function editOriginalResponse(fetchImpl, payload, content) {
  const url = `${DISCORD_API_BASE}/webhooks/${encodeURIComponent(payload.application_id)}/${encodeURIComponent(payload.interaction_token)}/messages/@original`;
  try {
    const response = await fetchWithTimeout(fetchImpl, url, { method: "PATCH", headers: { "content-type": "application/json" }, body: JSON.stringify({ content }) }, DISCORD_TIMEOUT_MS);
    if (!response.ok) console.error(JSON.stringify({ event: "discord_original_response_edit_failed", interaction_id: payload.interaction_id, reason: "discord_http_error", discord_status: response.status }));
  } catch (error) {
    console.error(JSON.stringify({ event: "discord_original_response_edit_failed", interaction_id: payload.interaction_id, reason: error?.name === "AbortError" ? "discord_timeout" : "discord_transport_error" }));
  }
}

async function fetchWithTimeout(fetchImpl, url, init, timeoutMs) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  // workerd supports manual redirects, while redirect:"error" is rejected at this compatibility date.
  // Manual mode preserves the response status and never forwards bridge credentials to another URL.
  try { return await fetchImpl(url, { ...init, redirect: "manual", signal: controller.signal }); } finally { clearTimeout(timer); }
}

async function fetchJsonWithDeadline(fetchImpl, url, init, timeoutMs) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetchImpl(url, { ...init, redirect: "manual", signal: controller.signal });
    // A non-acceptance status is enough to classify the outcome. Do not require
    // an error response body, which is commonly absent on tunnel and gateway 5xx.
    if (response.status !== 200 && response.status !== 202) return { response, text: null };
    const result = await readLimitedStream(response.body, MAX_BODY_BYTES);
    if (!result.ok) throw new Error(result.error);
    return { response, text: result.text };
  } finally { clearTimeout(timer); }
}

async function readLimitedBody(request, limit) {
  const length = request.headers.get("content-length");
  if (length !== null && (!/^\d+$/.test(length) || Number(length) > limit)) return { ok: false, status: 413, error: "body_too_large" };
  return readLimitedStream(request.body, limit);
}

async function readLimitedStream(stream, limit) {
  const reader = stream?.getReader();
  if (!reader) return { ok: false, status: 400, error: "invalid_body" };
  const chunks = []; let size = 0;
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    size += value.byteLength;
    if (size > limit) { await reader.cancel(); return { ok: false, status: 413, error: "body_too_large" }; }
    chunks.push(value);
  }
  const bytes = new Uint8Array(size); let offset = 0;
  for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength; }
  try { return { ok: true, text: new TextDecoder("utf-8", { fatal: true }).decode(bytes) }; } catch { return { ok: false, status: 400, error: "invalid_body" }; }
}

async function verifyDiscordSignature(publicKeyHex, signatureHex, timestamp, rawBody) {
  if (!isHex(signatureHex, 128)) return false;
  try {
    const publicKey = await crypto.subtle.importKey("raw", hexBytes(publicKeyHex), { name: "Ed25519" }, false, ["verify"]);
    return await crypto.subtle.verify("Ed25519", publicKey, hexBytes(signatureHex), new TextEncoder().encode(timestamp + rawBody));
  } catch { return false; }
}

function validateBridgeUrl(value, allowInsecureLocal) {
  try {
    const url = new URL(value);
    const localHttp = allowInsecureLocal === "true" && url.protocol === "http:" && (url.hostname === "localhost" || url.hostname === "127.0.0.1" || url.hostname === "[::1]");
    return (url.pathname === "/v1/discord/jobs" && (url.protocol === "https:" || localHttp) && !url.username && !url.password && !url.search && !url.hash) ? url.toString() : null;
  } catch { return null; }
}

function isFreshTimestamp(timestamp, now) { return typeof timestamp === "string" && /^\d{10}$/.test(timestamp) && Math.abs(now - Number(timestamp)) <= SIGNATURE_MAX_AGE_SECONDS; }
function normalizeAttachmentLimit(value) { return Number.isSafeInteger(value) && value >= 0 ? value : DEFAULT_ATTACHMENT_SIZE_LIMIT; }
function isBoundedString(value, max) { return typeof value === "string" && value.trim().length > 0 && Array.from(value).length <= max; }
function isNonEmptyString(value) { return typeof value === "string" && value.length > 0; }
function isSnowflake(value) { return typeof value === "string" && /^\d{17,20}$/.test(value); }
function parseSnowflakeList(value) {
  if (typeof value !== "string") return null;
  const values = value.split(",").map((item) => item.trim());
  return values.length > 0 && values.every(isSnowflake) ? [...new Set(values)] : null;
}
function hasCompleteAccessToken(env) { return Boolean(env.CF_ACCESS_CLIENT_ID) === Boolean(env.CF_ACCESS_CLIENT_SECRET); }
function isHex(value, length) { return typeof value === "string" && value.length === length && /^[0-9a-f]+$/i.test(value); }
function hexBytes(value) { const out = new Uint8Array(value.length / 2); for (let i = 0; i < out.length; i += 1) out[i] = Number.parseInt(value.slice(i * 2, i * 2 + 2), 16); return out; }
function parseJson(value) { try { const parsed = JSON.parse(value); return parsed && typeof parsed === "object" ? parsed : null; } catch { return null; } }
function jsonResponse(value, status) { return new Response(JSON.stringify(value), { status, headers: { "content-type": "application/json; charset=utf-8" } }); }
