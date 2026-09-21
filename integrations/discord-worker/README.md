# AtelierX personal Discord Worker

This Worker accepts only signed Discord interaction webhooks using configured user or guild/channel access rules. It has no database, queue, GPU access, Core access, or generation logic. It forwards accepted commands to the authenticated local bridge reachable through a HTTPS Cloudflare Tunnel.

`/draw prompt:<text> mode:<natural|direct>` defers ephemerally and sends exactly one request to `BRIDGE_URL` (`/v1/discord/jobs`). `natural` is the default; the bridge asks Core to convert the request using the local LLM. `direct` preserves the supplied prompt. The request is bounded to 64 KiB, while `prompt` is bounded to 4,000 Unicode code points.

`/status request_id:<Discord interaction ID>` also defers ephemerally, then sends a fresh interaction token to `/v1/discord/status`. The local bridge uses that token only to return a saved result to its original owner; it must never start generation again. This gives the user a way to retrieve a result after Discord's original interaction-token window expires.

Every normalized bridge body contains only the documented request fields, including `interaction_token`, and is never logged. The Worker validates the raw signed body with Discord's Ed25519 public key, requires a timestamp no older or newer than five minutes, checks the configured application and access policy, and accepts no other callers. `DISCORD_ALLOWED_USER_ID` is also accepted for one older local setup. The Worker uses only the fixed Discord API base URL when it needs to update the deferred ephemeral message, and blocks HTTP redirects so credentials never follow an untrusted location. Bridge transport ambiguity, including 5xx, triggers one update saying acceptance is unknown and never causes automatic resubmission. A 4xx bridge reply is reported as a rejection.

## Local setup and checks

Copy `.dev.vars.example` to `.dev.vars`, add actual secrets locally, then run (Node 22 or later):

```powershell
npm test
```

`npm run register-commands` POSTs only the two command definitions to Discord, preserving unrelated application commands. It is intentionally not run automatically. It requires `DISCORD_APPLICATION_ID` and `DISCORD_BOT_TOKEN` in the process environment; set `DISCORD_GUILD_ID` to register into one personal test server instead of globally. Deploying the Worker and setting Discord's interactions endpoint are separate, manual operations.

`BRIDGE_URL` must be HTTPS and exactly end in `/v1/discord/jobs`. HTTP is accepted only for `localhost`, `127.0.0.1`, or `[::1]` when `ALLOW_INSECURE_LOCAL_BRIDGE=true` is explicitly set for local development. `BRIDGE_TOKEN` and optional Cloudflare Access service-token credentials belong in Worker secrets, never in `wrangler.jsonc`.

Install the pinned toolchain with `npm ci`. Check packaging with `npx wrangler deploy --dry-run`, confirm the intended account using `npx wrangler whoami`, then deploy using `npx wrangler deploy`. Local `.dev.vars` is not uploaded as remote secrets; use `npx wrangler secret put NAME` for each required value. The setup inputs are `DISCORD_PUBLIC_KEY`, `DISCORD_APPLICATION_ID`, `DISCORD_ALLOWED_USER_IDS`, `BRIDGE_URL`, and `BRIDGE_TOKEN`. Do not pass the Bot Token to the Worker.

Current deployment and end-to-end verification status are maintained in [the personal bot report](../../docs/development/discord-personal-bot.md).


Access modes: `DISCORD_ACCESS_MODE=users` (default) uses the existing explicit user allowlist. `guild` requires nonempty `DISCORD_ALLOWED_GUILD_IDS` and a signed guild member identity; optional `DISCORD_ALLOWED_CHANNEL_IDS` narrows access to exact channels. Guild mode forwards `guild_id` and `channel_id` to the Bridge, which must use the matching policy. DM and other guilds are rejected, including for the owner. Empty or malformed required scope does not grant public access. Bot installation restrictions are separate: disable Public Bot in the Discord Developer Portal to restrict server installation to the application owner.
