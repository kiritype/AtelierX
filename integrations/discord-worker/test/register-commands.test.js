import assert from "node:assert/strict";
import test from "node:test";
import { registerCommands } from "../scripts/register-commands.mjs";

const env = {
  DISCORD_APPLICATION_ID: "123456789012345678",
  DISCORD_BOT_TOKEN: "bot-token",
  DISCORD_GUILD_ID: "444444444444444444",
  ATELIERX_CORE_URL: "http://127.0.0.1:8190",
  ATELIERX_CORE_TOKEN: "core-token"
};

test("registers Core checkpoint choices with the default first", async () => {
  const calls = [];
  await registerCommands({ env, fetchImpl: async (url, init) => {
    calls.push({ url, init });
    if (url === "http://127.0.0.1:8190/v1/standalone-checkpoints") {
      assert.equal(init.headers.authorization, "Bearer core-token");
      return Response.json({ items: [{ name: "first.safetensors", value: "first.safetensors" }, { name: "default.safetensors", value: "default.safetensors" }], default: "default.safetensors" });
    }
    return new Response(null, { status: 201 });
  } });
  assert.equal(calls.length, 3);
  const draw = JSON.parse(calls[1].init.body);
  const checkpoint = draw.options.find((option) => option.name === "checkpoint");
  assert.deepEqual(checkpoint.choices, [{ name: "default.safetensors", value: "default.safetensors" }, { name: "first.safetensors", value: "first.safetensors" }]);
  assert.match(calls[1].url, /\/guilds\/444444444444444444\/commands$/);
});

test("fails registration when Core checkpoint configuration is unavailable or invalid", async () => {
  await assert.rejects(registerCommands({ env: { ...env, ATELIERX_CORE_TOKEN: "" }, fetchImpl: unexpectedFetch }), /configuration is invalid/);
  await assert.rejects(registerCommands({ env: { ...env, ATELIERX_CORE_URL: "https://core.example" }, fetchImpl: unexpectedFetch }), /configuration is invalid/);
  await assert.rejects(registerCommands({ env, fetchImpl: async () => Response.json({ items: [], default: "none.safetensors" }) }), /too many or no checkpoints/);
});

async function unexpectedFetch() { throw new Error("fetch should not run"); }
