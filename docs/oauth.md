# Self-hosted OAuth for the NCCU Moodle MCP

Goal: let an MCP client that speaks **OAuth** (e.g. ChatGPT connectors) reach this
server, using a **fully open-source, self-hosted** auth stack — no third-party
auth SaaS (Auth0/Clerk/Firebase/…). Everything runs in Docker on our own host.

## Decisions (locked)

- **Multi-user.** Many people use it, each acting as their **own** Moodle account.
- **Issuer: [Ory Hydra](https://www.ory.sh/hydra/)** — open-source, standards-certified
  OAuth2/OIDC server. Issues **opaque** access tokens by default, so the client
  (ChatGPT) never holds anything but a random string.
- **Token-only relay, no secret stored.** We never persist a Moodle password.
  The login step exchanges the password for a Moodle **Web Services (WS) token**
  and keeps only that (server-side, in the Hydra token session).
- **Re-login on expiry.** When the WS token expires or is revoked, tools return a
  clear "reconnect" error and the user re-runs the OAuth login. We do **not**
  silently re-mint (that would require storing the password, since NCCU login is
  SSO — see below).

## Why a token relay (and not password relay)

`MoodleClient.login(user, pass)` runs the full NCCU SSO → Moodle handoff and then
`fetch_ws_token()` reads the mobile WS token. **WS calls authenticate with the
token alone** — no session cookie — so once we have the token, the password is no
longer needed. The login/consent app uses the password exactly once, in memory,
then discards it.

Verified facts (probe, 2026-09-15):
- A WS token works **token-only** (fresh session, no cookies) against the
  **discovered backend host** (e.g. `https://moodle45.nccu.edu.tw`).
- The same token does **not** work against the canonical `https://moodle.nccu.edu.tw`
  (returns a redirect/landing page, not JSON).
- ⇒ the relay must carry **both** the token and its **base host**. The base host
  is not a secret.

## Architecture

```
[ChatGPT] ──OAuth (opaque token)──► [Gateway]  introspects token at Hydra,
                                        │        reads WS token + base from session,
                                        │        injects headers
                                        ▼
                                   [MCP backend]  X-Moodle-Token + X-Moodle-Base
                                                  → token-only MoodleClient

  OAuth login (once, or after expiry):
  [ChatGPT] ─► Hydra /oauth2/auth ─► [Login/Consent app]
                                        user types Moodle user/pass on OUR page
                                        → MoodleClient.login → fetch_ws_token
                                        → store {ws_token, base} in Hydra session
                                        → accept login/consent
```

Components (all open-source, Docker):
1. **Ory Hydra** — the OAuth2/OIDC issuer. ChatGPT's Authorization/Token URLs
   point here. Opaque tokens; custom session data carries `{ws_token, base}`.
2. **Login/Consent app** (small, ours) — the UI Hydra delegates to. Renders a
   Moodle login form, runs `MoodleClient.login`+`fetch_ws_token`, and on success
   accepts the Hydra login/consent request with the WS token + base as session
   data. Password never leaves this request.
3. **Gateway** — validates/introspects the opaque token at Hydra's admin API,
   maps the session's `{ws_token, base}` to `X-Moodle-Token` / `X-Moodle-Base`,
   and reverse-proxies to the MCP backend. (oauth2-proxy + a small introspection
   shim, or Caddy `forward_auth` — TBD in the compose step.)
4. **MCP backend** — this repo. Accepts the relayed headers (done, below).

> Note: `oauth2-proxy` is a **relying party**, not an issuer — it cannot mint
> tokens for ChatGPT on its own. Hydra is the issuer; oauth2-proxy (if used) sits
> on the resource-server side.

## Backend support (implemented on this branch)

- `MoodleClient.from_token(ws_token, base_url=...)` — build a token-only client,
  no login. WS/ws_parallel/url work; session-cookie helpers do not (tools don't
  need them).
- `app.run_tool` — prefers `X-Moodle-Token` (+ `X-Moodle-Base`, default canonical
  host) over `X-Moodle-Username`/`X-Moodle-Password`. On `invalidtoken` it raises
  a "reconnect (sign in again)" tool error instead of a raw WS error.
- Direct user/pass headers still work unchanged (Claude Code / opencode configs).

## TODO (next steps)

- [ ] `docker-compose.oauth.yml`: Hydra + Hydra migrate + login/consent app + gateway + MCP backend.
- [ ] Login/consent app: Moodle login form → `MoodleClient.login`/`fetch_ws_token` → Hydra accept with `{ws_token, base}` session data.
- [ ] Gateway: introspect opaque token, inject `X-Moodle-Token`/`X-Moodle-Base`.
- [ ] Register an OAuth client for ChatGPT; document its Authorization/Token URLs.
- [ ] End-to-end: ChatGPT → OAuth login (Moodle creds) → tool call succeeds; expired token → reconnect.
