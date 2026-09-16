# How the Moodle token is stored & refreshed

This explains, end to end, how the OAuth stack (`oauth` branch) obtains, stores,
uses, and refreshes your **Moodle Web Services token** — and why it stays
encrypted at rest. It's written to be readable without prior context.

## The four tokens (who issues what)

| Token | What it is | Issued by | Held by / used for |
|-------|-----------|-----------|--------------------|
| **WS** — Moodle Web Services token | The credential that acts as *you* to read Moodle data | **Moodle** (after NCCU SSO login) | Our server calls Moodle with it. **This is the secret we protect and use continuously.** |
| **code** — authorization code | A one-time, short-lived code | **Hydra** (our self-hosted OAuth server) | Handed to the client (ChatGPT) to *exchange* for the tokens below |
| **AT** — access token | The "pass" sent on every API call | **Hydra** | ChatGPT sends it on every `/mcp` call; short-lived (~8h) |
| **RT** — refresh token | The "renewal ticket" used when the AT expires | **Hydra** | ChatGPT keeps it; exchanges it for a fresh AT (+RT) |

Key point: **AT and RT are OAuth tokens Hydra issues to the client (ChatGPT); they
have nothing to do with Moodle.** They only prove "this client may use our
service." On an MCP call ChatGPT sends **only the AT**.

The core idea of the design: **use the client's AT/RT as the key to encrypt the
Moodle WS token.** The AT/RT themselves are never stored — only a hash of them,
plus ciphertext.

## Where the WS token lives

- **`pending`** — in the auth service's memory only. A short-lived (~15 min),
  single-use plaintext stash used *only* between login and the token exchange.
- **`token_vault`** — a table in the existing Postgres. Durable, and **always
  ciphertext**. Each row is:
  - **key** = `sha256(token)` — a one-way hash, for lookup only.
  - **value** = `{ ct, iv, tag, base }` — `ct` is the WS token encrypted with
    **AES-256-GCM**; `base` is the (non-secret) Moodle backend host.
  - plus an `expires_at`.
  The encryption key, `HKDF-SHA256(token)`, is derived per request and **never
  stored**.

Two rows exist per session — the **same** WS token, encrypted under two different
keys — because `/mcp` only ever presents the AT, while a refresh only presents the
RT:
- `sha256(access_token)` → sealed WS (read on every `/mcp` call)
- `sha256(refresh_token)` → sealed WS (read during a refresh)

## How the tokens are obtained (OAuth authorization-code flow)

1. ChatGPT sends your browser to Hydra's `/oauth2/auth`; Hydra redirects to **our
   login page**.
2. You enter your iNCCU credentials; we complete NCCU SSO and receive the **WS**
   token (issued by Moodle).
3. Hydra issues a one-time **`code`** and redirects the browser back to ChatGPT.
4. ChatGPT exchanges that `code` at Hydra's `/oauth2/token` (a back-channel,
   server-to-server call) — and **only now does Hydra issue the AT + RT**.

So at login time (step 2) the AT/RT don't exist yet; they appear at step 4. That
is why we need the temporary `pending` stash.

## Storage & refresh lifecycle

```
1. LOGIN (step 2)          WS obtained; AT/RT don't exist yet
   → pending[link] = { WS, base }        (RAM, single-use, ~15 min)
   → Hydra session stores only the random `link` (never the WS)

2. CODE EXCHANGE (step 4)  Hydra issues AT1 + RT1  (proxied by tokenproxy.ts)
   → look up WS via `link` from pending (then delete it)
   → WRITE two encrypted rows to token_vault (same WS, two keys):
       sha256(AT1) → AES-GCM(WS, key = HKDF(AT1))
       sha256(RT1) → AES-GCM(WS, key = HKDF(RT1))

3. EVERY /mcp CALL         (read; server.ts /verify)
   → ChatGPT sends AT → read token_vault[sha256(AT)]
   → decrypt with HKDF(AT) → WS → inject as X-Moodle-Token to the MCP backend

4. REFRESH (AT expired)    ChatGPT sends old RT to /oauth2/token (tokenproxy.ts)
   → read token_vault[sha256(oldRT)] → decrypt → recover the SAME WS
   → Hydra issues AT2 + RT2
   → WRITE two new rows: sha256(AT2), sha256(RT2)   (re-encrypt the same WS)
   → DELETE the old RT row (the old AT row expires by TTL)
   → subsequent /mcp calls use AT2 → back to step 3
```

The WS token "hops forward" — `(AT1,RT1) → (AT2,RT2) → (AT3,RT3) → …` — carried by
the refresh token, always stored only as ciphertext.

## Key properties

1. **The WS value never changes on refresh.** A refresh only re-encrypts the same
   WS under the new tokens (new rows + drop the old RT row). It's a re-wrap, not a
   value change.
2. **AT/RT are never stored** — only `sha256(token)` (a hash, for the lookup key)
   and the AES-GCM ciphertext. The decryption key is derived from the live token
   on each request. So a **stolen database is useless**: without a live AT/RT you
   can neither locate a row (need the token to compute the hash) nor decrypt it
   (need the token to derive the key). Verified: the plaintext WS token appears in
   zero `token_vault` rows.
3. **The WS token is re-issued (a genuinely new value) only when** you log in
   again, or Moodle expires/revokes it — in which case an `/mcp` call returns
   `invalidtoken` and the user is asked to reconnect.
4. **Persistence:** because the vault is in Postgres, an auth-service restart does
   **not** force a re-login (as long as the client's AT is still valid). Only the
   brief in-memory `pending` stash is lost on restart.
5. **Honest limit:** this protects data *at rest* (a stolen DB/volume/backup). It
   does **not** protect a compromised *running* service, which necessarily
   decrypts the WS token in memory to call Moodle.

## Where this lives in the code

- `auth/src/vault.ts` — sealing/unsealing (`sealForTokens`, `unsealByAccess`,
  `unsealByRefresh`, `evictRefresh`), the `pending` map, HKDF + AES-GCM helpers.
- `auth/src/store.ts` — the Postgres-backed `token_vault` (get/put/del/sweep),
  with an in-memory fallback if `DATABASE_URL` is unset.
- `auth/src/tokenproxy.ts` — proxies `/oauth2/token`; re-wraps the WS token on
  code exchange and on refresh (the only place both new tokens are visible).
- `auth/src/server.ts` — `/verify` (reads the vault on each `/mcp` call) and the
  login/consent handlers.

See also [`oauth.md`](oauth.md) for the overall stack.
