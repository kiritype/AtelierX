import { fileURLToPath } from "node:url";
import { resolve } from "node:path";

const MAX_CHECKPOINT_CHOICES = 25;
const MAX_CHECKPOINT_CODE_POINTS = 100;
const REQUEST_TIMEOUT_MS = 8_000;

export async function registerCommands({ env = process.env, fetchImpl = fetch } = {}) {
  const applicationId = env.DISCORD_APPLICATION_ID;
  const botToken = env.DISCORD_BOT_TOKEN;
  const guildId = env.DISCORD_GUILD_ID;
  const coreUrl = validateLoopbackCoreUrl(env.ATELIERX_CORE_URL);
  const coreToken = env.ATELIERX_CORE_TOKEN;
  if (!isSnowflake(applicationId) || !isNonEmptyString(botToken) || (guildId && !isSnowflake(guildId)) || !coreUrl || !isNonEmptyString(coreToken)) {
    throw new Error("Discord registration configuration is invalid");
  }

  const checkpoints = await fetchCheckpoints(fetchImpl, coreUrl, coreToken);
  const commands = buildCommands(checkpoints);
  const commandBase = guildId
    ? `https://discord.com/api/v10/applications/${encodeURIComponent(applicationId)}/guilds/${encodeURIComponent(guildId)}/commands`
    : `https://discord.com/api/v10/applications/${encodeURIComponent(applicationId)}/commands`;
  for (const command of commands) {
    const response = await fetchWithTimeout(fetchImpl, commandBase, { method: "POST", headers: { authorization: `Bot ${botToken}`, "content-type": "application/json" }, body: JSON.stringify(command) }, REQUEST_TIMEOUT_MS);
    if (!response.ok) throw new Error("Discord command registration failed");
  }
}

export function buildCommands(checkpoints) {
  return [
    { name: "draw", description: "Create an AtelierX image", type: 1, options: [
      { name: "prompt", description: "What to create", type: 3, required: true, max_length: 4000 },
      { name: "negative", description: "Optional negative prompt", type: 3, required: false, max_length: 4000 },
      { name: "checkpoint", description: "Optional registered checkpoint", type: 3, required: false, choices: checkpoints },
      { name: "mode", description: "Use prompt directly by default, or interpret it", type: 3, required: false, choices: [
        { name: "Direct", value: "direct" }, { name: "Natural", value: "natural" }
      ] }
    ] },
    { name: "status", description: "Get the saved result for an AtelierX request", type: 1, options: [
      { name: "request_id", description: "The request ID from /draw", type: 3, required: true, max_length: 200 }
    ] }
  ];
}

async function fetchCheckpoints(fetchImpl, coreUrl, coreToken) {
  const url = new URL("/v1/standalone-checkpoints", coreUrl).toString();
  const response = await fetchWithTimeout(fetchImpl, url, { headers: { authorization: `Bearer ${coreToken}` } }, REQUEST_TIMEOUT_MS);
  if (!response.ok) throw new Error("Core checkpoint lookup failed");
  let payload;
  try { payload = await response.json(); } catch { throw new Error("Core checkpoint lookup returned invalid JSON"); }
  if (!Array.isArray(payload?.items) || !isCheckpoint(payload.default)) throw new Error("Core checkpoint lookup returned an invalid schema");
  if (payload.items.length === 0 || payload.items.length > MAX_CHECKPOINT_CHOICES) throw new Error("Core checkpoint lookup returned too many or no checkpoints");
  const choices = payload.items.map((item) => ({ name: item?.name, value: item?.value }));
  if (!choices.every((item) => isCheckpoint(item.name) && item.name === item.value)) throw new Error("Core checkpoint lookup returned an invalid checkpoint");
  if (new Set(choices.map((item) => item.value)).size !== choices.length || !choices.some((item) => item.value === payload.default)) throw new Error("Core checkpoint lookup returned inconsistent checkpoints");
  return [choices.find((item) => item.value === payload.default), ...choices.filter((item) => item.value !== payload.default)];
}

function validateLoopbackCoreUrl(value) {
  try {
    const url = new URL(value);
    const hostname = url.hostname.toLowerCase();
    if ((url.protocol !== "http:" && url.protocol !== "https:") || !["localhost", "127.0.0.1", "[::1]", "::1"].includes(hostname) || url.username || url.password || url.search || url.hash) return null;
    return url.toString();
  } catch { return null; }
}

function isCheckpoint(value) { return typeof value === "string" && value.trim().length > 0 && Array.from(value).length <= MAX_CHECKPOINT_CODE_POINTS; }
async function fetchWithTimeout(fetchImpl, url, init, timeoutMs) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try { return await fetchImpl(url, { ...init, redirect: "error", signal: controller.signal }); } finally { clearTimeout(timer); }
}
function isSnowflake(value) { return typeof value === "string" && /^\d{17,20}$/.test(value); }
function isNonEmptyString(value) { return typeof value === "string" && value.length > 0; }

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  await registerCommands();
  console.log("Discord draw and status commands registered without replacing unrelated commands.");
}
