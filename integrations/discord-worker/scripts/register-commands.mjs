const applicationId = process.env.DISCORD_APPLICATION_ID;
const botToken = process.env.DISCORD_BOT_TOKEN;
const guildId = process.env.DISCORD_GUILD_ID;
if (!isSnowflake(applicationId) || !isNonEmptyString(botToken) || (guildId && !isSnowflake(guildId))) throw new Error("Discord registration configuration is invalid");

const commands = [
  { name: "draw", description: "Create an AtelierX image", type: 1, options: [
    { name: "prompt", description: "What to create", type: 3, required: true, max_length: 4000 },
    { name: "negative", description: "Optional negative prompt", type: 3, required: false, max_length: 4000 },
    { name: "mode", description: "Use prompt directly by default, or interpret it", type: 3, required: false, choices: [
      { name: "Direct", value: "direct" }, { name: "Natural", value: "natural" }
    ] }
  ] },
  { name: "status", description: "Get the saved result for an AtelierX request", type: 1, options: [
    { name: "request_id", description: "The request ID from /draw", type: 3, required: true, max_length: 200 }
  ] }
];

const commandBase = guildId
  ? `https://discord.com/api/v10/applications/${encodeURIComponent(applicationId)}/guilds/${encodeURIComponent(guildId)}/commands`
  : `https://discord.com/api/v10/applications/${encodeURIComponent(applicationId)}/commands`;
for (const command of commands) {
  const response = await fetchWithTimeout(commandBase, { method: "POST", headers: { authorization: `Bot ${botToken}`, "content-type": "application/json" }, body: JSON.stringify(command) }, 8_000);
  if (!response.ok) throw new Error("Discord command registration failed");
}
console.log("Discord draw and status commands registered without replacing unrelated commands.");

async function fetchWithTimeout(url, init, timeoutMs) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try { return await fetch(url, { ...init, redirect: "error", signal: controller.signal }); } finally { clearTimeout(timer); }
}
function isSnowflake(value) { return typeof value === "string" && /^\d{17,20}$/.test(value); }
function isNonEmptyString(value) { return typeof value === "string" && value.length > 0; }
