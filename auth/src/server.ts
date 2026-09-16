/**
 * OAuth login/consent + gateway-verify service for Ory Hydra.
 *
 *   GET  /login    Hydra redirects here with ?login_challenge=; render the form.
 *   POST /login    verify Moodle via SSO, mint a WS token, accept the login.
 *   GET  /consent  Hydra redirects here with ?consent_challenge=; auto-grant and
 *                  carry only a random `link` handle in the session (the WS token
 *                  stays in the in-memory vault, never in Hydra/Postgres).
 *   GET  /verify   Caddy forward_auth target: introspect the bearer token, resolve
 *                  the Moodle token from the vault, and return X-Moodle-* headers.
 *   GET  /healthz  liveness.
 */
import express from "express";
import { loginAndMintToken, MoodleAuthError } from "./moodle.js";
import {
  acceptConsent,
  acceptLogin,
  getConsentRequest,
  getLoginRequest,
  introspect,
  rejectLogin,
} from "./hydra.js";
import { loginPage } from "./views.js";
import { evict, resolveToken, stashPending } from "./vault.js";

const app = express();
app.use(express.urlencoded({ extended: false }));

const PUBLIC_URL = (process.env.PUBLIC_URL || "").replace(/\/$/, "");
const SCOPES = ["openid", "moodle"];
const RESOURCE_META = `${PUBLIC_URL}/.well-known/oauth-protected-resource`;

app.get("/healthz", (_req, res) => res.type("text").send("ok"));

// --- Discovery documents for MCP clients (ChatGPT) to auto-register --------- //
// Hydra serves /.well-known/openid-configuration but not RFC 8414 metadata, and
// does not advertise the DCR endpoint. We publish RFC 8414 (authorization server)
// and RFC 9728 (protected resource) so a client can find /oauth2/register and
// self-register. These route through the gateway on the same public origin.
app.get("/.well-known/oauth-authorization-server", (_req, res) => {
  res.json({
    issuer: PUBLIC_URL,
    authorization_endpoint: `${PUBLIC_URL}/oauth2/auth`,
    token_endpoint: `${PUBLIC_URL}/oauth2/token`,
    registration_endpoint: `${PUBLIC_URL}/oauth2/register`,
    jwks_uri: `${PUBLIC_URL}/.well-known/jwks.json`,
    userinfo_endpoint: `${PUBLIC_URL}/userinfo`,
    scopes_supported: SCOPES,
    response_types_supported: ["code"],
    // No refresh: the WS token is encrypted under the access token, which must
    // not rotate (see vault.ts). Access tokens are re-minted by re-login.
    grant_types_supported: ["authorization_code"],
    code_challenge_methods_supported: ["S256"],
    token_endpoint_auth_methods_supported: [
      "client_secret_post",
      "client_secret_basic",
      "none",
    ],
  });
});

app.get("/.well-known/oauth-protected-resource", (_req, res) => {
  res.json({
    resource: `${PUBLIC_URL}/mcp`,
    authorization_servers: [PUBLIC_URL],
    scopes_supported: SCOPES,
    bearer_methods_supported: ["header"],
  });
});

// ---- login ---------------------------------------------------------------- //
app.get("/login", async (req, res) => {
  const challenge = String(req.query.login_challenge || "");
  if (!challenge) return res.status(400).send("Missing login_challenge.");
  try {
    // Never skip: a remembered subject would have no (fresh) Moodle token.
    await getLoginRequest(challenge);
    res.type("html").send(loginPage(challenge));
  } catch {
    res.status(502).send("Auth server error talking to Hydra.");
  }
});

app.post("/login", async (req, res) => {
  const challenge = String(req.body.challenge || "");
  const username = String(req.body.username || "").trim();
  const password = String(req.body.password || "");
  if (!challenge) return res.status(400).send("Missing challenge.");
  if (!username || !password) {
    return res.type("html").send(loginPage(challenge, "Enter your account and password."));
  }
  try {
    const { wsToken, base } = await loginAndMintToken(username, password);
    // Carry the token forward to the consent step via Hydra's `context`.
    const redirectTo = await acceptLogin(challenge, username, {
      moodle_token: wsToken,
      moodle_base: base,
    });
    res.redirect(redirectTo);
  } catch (e) {
    if (e instanceof MoodleAuthError) {
      return res.type("html").send(loginPage(challenge, e.message));
    }
    console.error("login error", e);
    res.status(502).send("Login failed due to a server error. Please try again.");
  }
});

// ---- consent (first-party: auto-grant) ------------------------------------ //
app.get("/consent", async (req, res) => {
  const challenge = String(req.query.consent_challenge || "");
  if (!challenge) return res.status(400).send("Missing consent_challenge.");
  try {
    const cr = await getConsentRequest(challenge);
    const ctx = (cr.context || {}) as Record<string, unknown>;
    // Do NOT put the WS token in the Hydra session (it would be persisted,
    // server-readable). Stash it in memory and carry only a random handle.
    const link = stashPending(String(ctx.moodle_token || ""), String(ctx.moodle_base || ""));
    const redirectTo = await acceptConsent(challenge, cr, { link });
    res.redirect(redirectTo);
  } catch (e) {
    console.error("consent error", e);
    res.status(502).send("Consent failed due to a server error.");
  }
});

// ---- gateway verify (Caddy forward_auth) ---------------------------------- //
app.all("/verify", async (req, res) => {
  const challenge = (err: string) =>
    `Bearer error="${err}", resource_metadata="${RESOURCE_META}"`;
  const auth = req.header("authorization") || "";
  const m = auth.match(/^Bearer\s+(.+)$/i);
  if (!m) {
    res.set("WWW-Authenticate", challenge("invalid_request"));
    return res.status(401).end();
  }
  try {
    const accessToken = m[1];
    const intro = await introspect(accessToken);
    if (!intro.active) {
      evict(accessToken); // token expired/revoked — drop any vault entry
      res.set("WWW-Authenticate", challenge("invalid_token"));
      return res.status(401).end();
    }
    // Decrypt the Moodle token from the vault (or bootstrap it on the first
    // request from the pending handle carried in the session `ext.link`).
    const resolved = resolveToken(accessToken, intro.ext?.link as string | undefined);
    if (!resolved || !resolved.wsToken) {
      res.set("WWW-Authenticate", challenge("invalid_token"));
      return res.status(401).end();
    }
    res.set("X-Moodle-Token", resolved.wsToken);
    if (resolved.base) res.set("X-Moodle-Base", resolved.base);
    res.status(200).end();
  } catch (e) {
    console.error("verify error", e);
    res.status(502).end();
  }
});

const PORT = Number(process.env.PORT || 3000);
app.listen(PORT, () => console.log(`auth service listening on :${PORT}`));

export default app;
