# Self-hosted OAuth for the NCCU Moodle MCP

Goal: let an MCP client that speaks **OAuth** (e.g. ChatGPT connectors) reach this
server, using a **fully open-source, self-hosted** auth stack — no third-party
auth SaaS (Auth0/Clerk/Firebase/…). Everything runs in Docker on our own host.

## Decisions (locked)

- **Multi-user.** Many people use it, each acting as their **own** Moodle account.
- **Issuer: [Ory Hydra](https://www.ory.sh/hydra/)** — open-source, standards-certified
  OAuth2/OIDC server. Issues **opaque** access tokens by default, so the client
  (ChatGPT) never holds anything but a random string.
- **Token-only relay, no password stored.** We never persist a Moodle password.
  The login step exchanges the password (used once, in memory) for a Moodle
  **Web Services (WS) token** and keeps only that.
- **WS token unreadable at rest.** The WS token is NOT stored in the Hydra session
  (which Hydra persists, decryptable with the app's system secret). It is kept in
  memory, encrypted under the client's tokens — see "Token storage" below.
- **Refresh supported; WS token re-wrapped on rotation.** `offline_access` is
  enabled (ChatGPT requires it). Because a refresh rotates the access token, the
  WS token is sealed under BOTH the access token and the refresh token, and
  re-sealed on every refresh (at the proxied token endpoint). The WS token's value
  never changes on refresh — only its encryption wrapper. It changes only on
  re-login or a Moodle-side expiry (which surfaces as a `/mcp` "reconnect" error).

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

## Token storage (at-rest protection)

The server must not be able to read a stored WS token on its own — only during a
live request, when the client presents a token. **We never store the access or
refresh token** (plaintext or encrypted); each appears only transiently in the
request that carries it, used to derive a key and a lookup hash, then discarded.
Hydra likewise stores only hashes of them. What we store (`auth/src/vault.ts`):

- **key** = `sha256(token)` — an irreversible hash (the map key).
- **value** = AES-256-GCM **ciphertext of the WS token** + `{salt, iv, tag, base}`.
  The key `HKDF-SHA256(token, salt)` is derived per request, never persisted.

Two entries hold the SAME sealed WS token under different tokens, because `/mcp`
only ever presents the access token and a refresh only presents the refresh token:
- `sha256(access_token)` → sealed WS  (read by `/verify`)
- `sha256(refresh_token)` → sealed WS  (read on refresh)

These are persisted in the existing **Postgres** (reused, own `token_vault` table;
`auth/src/store.ts`) so the vault survives an auth-service restart — the Moodle
token is used continuously, and we don't want to force a re-login on every
deploy. Persisting is safe because the rows are ciphertext keyed by token hashes
and the key is never stored. (`pending` stays in memory only.)

Flow:
- **Consent:** WS goes into an in-memory single-use `pending[link]`; only the
  random `link` handle is placed in the Hydra session.
- **Code exchange (proxied token endpoint):** recover WS from `pending` (introspect
  the new AT → `ext.link`), seal under the new AT + RT.
- **Refresh (proxied token endpoint):** recover WS from the old RT's entry, re-seal
  under the new AT + RT (writing two fresh rows), and drop the old RT row. The WS
  value is unchanged — only re-wrapped. (The old AT row expires by TTL.)
- **`/mcp`:** introspect the AT (validity/revocation), `unsealByAccess(AT)`, inject
  headers.

**Honest guarantee:** unreadable *at rest* (a DB dump is `{hash → ciphertext}`,
useless without a live token to both locate and decrypt an entry), not *never*
readable — during a request the server decrypts to call Moodle. Protects a stolen
DB/volume/config; does **not** protect a compromised *running* service. Verified:
the plaintext WS token appears in zero `token_vault` rows.

## Architecture

```
[ChatGPT] ──OAuth (opaque token)──► [Caddy]  forward_auth → auth /verify:
                                        │       introspect + decrypt WS token
                                        │       from the vault, inject headers
                                        ▼
                                   [MCP backend]  X-Moodle-Token + X-Moodle-Base
                                                  → token-only MoodleClient

  OAuth login (once, or after expiry):
  [ChatGPT] ─► Hydra /oauth2/auth ─► [Login/Consent app]
                                        user types Moodle user/pass on OUR page
                                        → SSO → WS token → pending[link]
                                        → accept login/consent (session carries
                                          only the random `link` handle)
```

Components (all open-source, Docker) — **three services**:
1. **Ory Hydra** — the OAuth2/OIDC issuer. ChatGPT's Authorization/Token URLs
   point here. Opaque tokens; DCR enabled. Uses **SQLite** with migrations run
   inline on start (no separate database or migrate service).
2. **Auth service** (`auth/`, ours) — login/consent UI + the `/verify`
   gateway-check + the discovery docs + the token **vault** (`vault.ts`). Renders
   the Moodle login, reimplements SSO to mint the WS token, and holds it encrypted
   under the access token. Password never leaves the login request.
3. **Caddy gateway** — routes issuer/login/metadata traffic, and `forward_auth`s
   `/mcp` requests through the auth service's `/verify` (which injects
   `X-Moodle-Token` / `X-Moodle-Base`) before reverse-proxying to the MCP backend.

The MCP backend is this repo's existing server, reached behind Caddy; it accepts
the relayed headers (see "Backend support").

## Backend support (implemented on this branch)

- `MoodleClient.from_token(ws_token, base_url=...)` — build a token-only client,
  no login. WS/ws_parallel/url work; session-cookie helpers do not (tools don't
  need them).
- `app.run_tool` — prefers `X-Moodle-Token` (+ `X-Moodle-Base`, default canonical
  host) over `X-Moodle-Username`/`X-Moodle-Password`. On `invalidtoken` it raises
  a "reconnect (sign in again)" tool error instead of a raw WS error.
- Direct user/pass headers still work unchanged (Claude Code / opencode configs).

## The independent auth service (`auth/`)

A standalone **Node/TypeScript** service — it shares no code with the Python MCP
and **reimplements the NCCU SSO flow itself** (`auth/src/moodle.ts`, ported from
`MoodleClient`). It provides:

- `GET/POST /login` — the Moodle login page; on submit it runs SSO, mints a WS
  token, and accepts the Hydra login with `{moodle_token, moodle_base}` as
  `context`. Consent (auto-granted, first-party) stashes the token in `pending`
  and puts only a random `link` handle into the session `ext` (see "Token storage").
- `POST /oauth2/token` — transparent proxy to Hydra that re-wraps the WS token
  under the freshly issued access/refresh tokens (`auth/src/tokenproxy.ts`).
- `GET /verify` — Caddy `forward_auth` target: introspects the bearer token,
  `unsealByAccess` from the vault, and returns `X-Moodle-Token` / `X-Moodle-Base`.
  A missing/expired token → 401 with `WWW-Authenticate: … resource_metadata=…`.
- The discovery documents (below).

## Dynamic Client Registration + discovery

So an MCP client (ChatGPT) can **register itself** when the connector is added by
URL — no manual client setup:

- Hydra DCR is enabled (`OIDC_DYNAMIC_CLIENT_REGISTRATION_ENABLED=true`), exposing
  `POST /oauth2/register` (RFC 7591). Default scopes: `openid offline_access moodle`.
- Hydra serves `/.well-known/openid-configuration` but **not** RFC 8414 metadata
  and does **not** advertise the DCR endpoint. So the auth service publishes:
  - `/.well-known/oauth-authorization-server` (RFC 8414) — includes
    `registration_endpoint` and `code_challenge_methods_supported: ["S256"]`.
  - `/.well-known/oauth-protected-resource` (RFC 9728) — points at the AS.
  The gateway routes these two paths to the auth service (before Hydra's
  `/.well-known/*` catch-all); everything else OAuth goes to Hydra.

## Deploy (Docker)

```
cp .env.oauth.example .env         # set PUBLIC_URL (your tunnel https URL) + secrets
docker compose -f docker-compose.oauth.yml up -d --build
```

No client-registration step: MCP clients self-register via DCR. Point your tunnel
(e.g. Cloudflare) at the Caddy gateway port (`GATEWAY_PORT`, default 8971). In
ChatGPT, add the connector with the MCP URL `${PUBLIC_URL}/mcp`; it discovers the
AS, self-registers, and runs auth-code + PKCE.

Four services: **hydra-postgres** (Postgres 18), **hydra** (issuer; migrations run
inline on start), **auth** (login/consent + verify + vault), **caddy** (gateway).

**Dual auth on `/mcp`:** the gateway accepts either an OAuth bearer token (ChatGPT)
or `X-Moodle-Username` / `X-Moodle-Password` headers. A request carrying the
credential header is passed straight through to the MCP server (which does its own
SSO login), skipping OAuth — so header-based clients (Claude Code / opencode) can
use the same `${PUBLIC_URL}/mcp` URL. Bearer requests take the OAuth path.

## Status — verified end-to-end (local)

The full chain was exercised against the running stack with a real NCCU account:
discovery → **DCR** (self-registered client) → **auth code + PKCE** → Moodle SSO
login → opaque token → `/mcp` `tools/call` — the gateway relayed the token and
`search_courses` ran as the logged-in user (correct courses + roles). A
garbage/expired token surfaces the "reconnect" error.

Not yet done: run against the real public tunnel domain + the actual ChatGPT
connector (needs `PUBLIC_URL`); optional login/consent styling.
