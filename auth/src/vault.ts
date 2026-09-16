/**
 * At-rest protection for the Moodle WS token.
 *
 * Hard invariant: we NEVER store the access token or refresh token — plaintext OR
 * encrypted. A token appears only transiently in memory during the one request
 * that carries it; we use it to (a) compute a lookup hash and (b) derive an HKDF
 * encryption key, then discard it. Never log tokens.
 *
 * The Moodle WS token's VALUE never changes on an OAuth refresh — it is only
 * re-encrypted ("re-wrapped") under the new tokens. It changes only on re-login
 * or a Moodle-side expiry.
 *
 * Persistence: the sealed entries live in `store.ts` (Postgres by default) so the
 * vault survives an auth-service restart. What is stored is only:
 *   key   = sha256(token)                     — irreversible hash, for lookup
 *   value = AES-256-GCM ciphertext of the WS  — plus {salt, iv, tag, base}
 * The encryption key HKDF(token, salt) is derived per request and never stored,
 * so a database dump is useless without a live token.
 *
 *   - vaultAt (key sha256(access_token))  -> read by /verify
 *   - vaultRt (key sha256(refresh_token)) -> read on refresh to recover WS
 * The single-use `pending` map bridges consent (no tokens yet) -> code exchange
 * and holds the WS token only briefly, in memory (never persisted).
 */
import { createCipheriv, createDecipheriv, createHash, hkdfSync, randomBytes, randomUUID } from "node:crypto";
import { del, get, put, sweep, type VaultRow } from "./store.js";

const PENDING_TTL_MS = 15 * 60 * 1000; // consent -> code exchange
const AT_TTL_MS = 8 * 60 * 60 * 1000; // ~ access-token lifetime
const RT_TTL_MS = 45 * 24 * 60 * 60 * 1000; // >= refresh-token lifetime

interface Pending {
  wsToken: string;
  base: string;
  expires: number;
}
const pending = new Map<string, Pending>();

export function sha256(s: string): string {
  return createHash("sha256").update(s).digest("hex");
}

/** Store the WS token under a fresh single-use handle; returns the handle. */
export function stashPending(wsToken: string, base: string): string {
  const link = randomUUID();
  pending.set(link, { wsToken, base, expires: Date.now() + PENDING_TTL_MS });
  return link;
}

/** Consume the pending WS token for `link` (single-use). */
export function takePending(link: string): { wsToken: string; base: string } | undefined {
  const p = pending.get(link);
  pending.delete(link);
  if (!p || p.expires < Date.now()) return undefined;
  return { wsToken: p.wsToken, base: p.base };
}

// HKDF-SHA256(IKM = token, salt, info) -> 32-byte AES key. The token is never
// stored; only this derived key (transiently) and sha256(token) (as the store key).
function deriveKey(token: string, salt: Buffer): Buffer {
  return Buffer.from(hkdfSync("sha256", token, salt, "moodle-ws-token", 32));
}

function seal(token: string, wsToken: string, base: string): VaultRow {
  const salt = randomBytes(16);
  const iv = randomBytes(12);
  const c = createCipheriv("aes-256-gcm", deriveKey(token, salt), iv);
  const ct = Buffer.concat([c.update(wsToken, "utf8"), c.final()]);
  return {
    salt: salt.toString("base64"),
    iv: iv.toString("base64"),
    tag: c.getAuthTag().toString("base64"),
    ct: ct.toString("base64"),
    base,
  };
}

function unseal(token: string, row: VaultRow): { wsToken: string; base: string } {
  const salt = Buffer.from(row.salt, "base64");
  const d = createDecipheriv("aes-256-gcm", deriveKey(token, salt), Buffer.from(row.iv, "base64"));
  d.setAuthTag(Buffer.from(row.tag, "base64"));
  const ws = Buffer.concat([d.update(Buffer.from(row.ct, "base64")), d.final()]).toString("utf8");
  return { wsToken: ws, base: row.base };
}

/**
 * Seal the SAME WS token under both the access token and the refresh token
 * (re-wrap on rotation). Call at the token endpoint, where both new tokens are
 * visible. `refreshToken` may be absent.
 */
export async function sealForTokens(
  wsToken: string,
  base: string,
  accessToken: string,
  refreshToken?: string,
): Promise<void> {
  await put(sha256(accessToken), seal(accessToken, wsToken, base), Date.now() + AT_TTL_MS);
  if (refreshToken) {
    await put(sha256(refreshToken), seal(refreshToken, wsToken, base), Date.now() + RT_TTL_MS);
  }
}

/** Recover the WS token for a request presenting `accessToken` (used by /verify). */
export async function unsealByAccess(
  accessToken: string,
): Promise<{ wsToken: string; base: string } | null> {
  const row = await get(sha256(accessToken));
  if (!row) return null;
  try {
    return unseal(accessToken, row);
  } catch {
    return null;
  }
}

/** Recover the WS token for a refresh presenting the old `refreshToken`. */
export async function unsealByRefresh(
  refreshToken: string,
): Promise<{ wsToken: string; base: string } | null> {
  const row = await get(sha256(refreshToken));
  if (!row) return null;
  try {
    return unseal(refreshToken, row);
  } catch {
    return null;
  }
}

/** Drop an access-token vault entry (e.g. when introspection says inactive). */
export async function evict(accessToken: string): Promise<void> {
  await del(sha256(accessToken));
}

/** Drop a refresh-token vault entry (the old RT, once rotated). */
export async function evictRefresh(refreshToken: string): Promise<void> {
  await del(sha256(refreshToken));
}

// Periodic sweep so expired entries don't accumulate (store rows + pending).
setInterval(() => {
  const now = Date.now();
  for (const [k, v] of pending) if (v.expires < now) pending.delete(k);
  void sweep();
}, 60 * 1000).unref();
