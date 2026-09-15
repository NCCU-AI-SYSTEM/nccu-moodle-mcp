/**
 * Thin client for the Ory Hydra Admin API (v2). Only the calls this service
 * needs: fetch/accept login + consent challenges, and introspect a token.
 *
 * The Admin API is reachable only on the internal Docker network (never exposed
 * publicly). Base URL from HYDRA_ADMIN_URL (default http://hydra:4445).
 */
import axios from "axios";

const ADMIN = (process.env.HYDRA_ADMIN_URL || "http://hydra:4445").replace(/\/$/, "");

const admin = axios.create({ baseURL: ADMIN, timeout: 10000 });

export interface LoginRequest {
  skip: boolean;
  subject: string;
  request_url: string;
}

export interface ConsentRequest {
  skip: boolean;
  subject: string;
  requested_scope: string[];
  requested_access_token_audience: string[];
  context?: Record<string, unknown>;
}

export async function getLoginRequest(challenge: string): Promise<LoginRequest> {
  const r = await admin.get("/admin/oauth2/auth/requests/login", {
    params: { login_challenge: challenge },
  });
  return r.data;
}

/** Accept a login; `context` is passed through to the consent step. */
export async function acceptLogin(
  challenge: string,
  subject: string,
  context: Record<string, unknown>,
): Promise<string> {
  const r = await admin.put(
    "/admin/oauth2/auth/requests/login/accept",
    { subject, remember: false, remember_for: 0, context },
    { params: { login_challenge: challenge } },
  );
  return r.data.redirect_to;
}

export async function rejectLogin(challenge: string, reason: string): Promise<string> {
  const r = await admin.put(
    "/admin/oauth2/auth/requests/login/reject",
    { error: "access_denied", error_description: reason },
    { params: { login_challenge: challenge } },
  );
  return r.data.redirect_to;
}

export async function getConsentRequest(challenge: string): Promise<ConsentRequest> {
  const r = await admin.get("/admin/oauth2/auth/requests/consent", {
    params: { consent_challenge: challenge },
  });
  return r.data;
}

/**
 * Accept a consent. The `session.access_token` fields surface as `ext` in token
 * introspection — that is where we stash the Moodle token + base so the gateway
 * can read them back WITHOUT the client ever seeing them.
 */
export async function acceptConsent(
  challenge: string,
  req: ConsentRequest,
  sessionExt: Record<string, unknown>,
): Promise<string> {
  const r = await admin.put(
    "/admin/oauth2/auth/requests/consent/accept",
    {
      grant_scope: req.requested_scope,
      grant_access_token_audience: req.requested_access_token_audience,
      remember: false,
      remember_for: 0,
      session: { access_token: sessionExt, id_token: {} },
    },
    { params: { consent_challenge: challenge } },
  );
  return r.data.redirect_to;
}

export interface Introspection {
  active: boolean;
  sub?: string;
  ext?: Record<string, unknown>;
}

export async function introspect(token: string): Promise<Introspection> {
  const r = await admin.post(
    "/admin/oauth2/introspect",
    new URLSearchParams({ token }).toString(),
    { headers: { "Content-Type": "application/x-www-form-urlencoded" } },
  );
  return r.data;
}
