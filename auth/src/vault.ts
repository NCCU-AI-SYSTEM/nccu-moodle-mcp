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
 * Stored state (in-memory maps, nothing sensitive on disk):
 *   - key   = sha256(token)  — an irreversible hash, used only for lookup.
 *   - value = AES-256-GCM ciphertext of the WS token + {salt, iv, tag, base}.
 *             The encryption key HKDF(token, salt) is derived per request.
 * A dump yields {hash -> ciphertext+salt+iv+tag+base} — useless without a live
 * token to both locate (hash) and decrypt (HKDF) an entry.
 *
 *   - pending: link handle -> {wsToken, base}, single-use, short TTL. Bridges
 *     consent (no tokens yet) -> the code-exchange, where we first seal.
 *   - vaultAt: sha256(access_token)  -> sealed WS   (read by /verify)
 *   - vaultRt: sha256(refresh_token) -> sealed WS   (read on refresh to recover WS)
 *
 * In-memory means an auth-service restart forces users to re-login. The values
 * are ciphertext keyed by token hashes, so they could be persisted (e.g. Redis)
 * without weakening the guarantee — deferred.
 */
import { createCipheriv, createDecipheriv, createHash, hkdfSync, randomBytes, randomUUID } from "node:crypto";

const PENDING_TTL_MS = 15 * 60 * 1000; // consent -> code exchange
const AT_TTL_MS = 8 * 60 * 60 * 1000; // ~ access-token lifetime
const RT_TTL_MS = 45 * 24 * 60 * 60 * 1000; // >= refresh-token lifetime

interface Pending {
  wsToken: string;
  base: string;
  expires: number;
}
interface Sealed {
  salt: Buffer;
  iv: Buffer;
  tag: Buffer;
  ciphertext: Buffer;
  base: string;
  expires: number;
}

const pending = new Map<string, Pending>();
const vaultAt = new Map<string, Sealed>();
const vaultRt = new Map<string, Sealed>();

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
// stored; only this derived key (transiently) and sha256(token) (as the map key).
function deriveKey(token: string, salt: Buffer): Buffer {
  return Buffer.from(hkdfSync("sha256", token, salt, "moodle-ws-token", 32));
}

function seal(token: string, wsToken: string, base: string, ttlMs: number): Sealed {
  const salt = randomBytes(16);
  const iv = randomBytes(12);
  const c = createCipheriv("aes-256-gcm", deriveKey(token, salt), iv);
  const ciphertext = Buffer.concat([c.update(wsToken, "utf8"), c.final()]);
  return { salt, iv, tag: c.getAuthTag(), ciphertext, base, expires: Date.now() + ttlMs };
}

function unseal(token: string, e: Sealed): { wsToken: string; base: string } {
  const d = createDecipheriv("aes-256-gcm", deriveKey(token, e.salt), e.iv);
  d.setAuthTag(e.tag);
  const wsToken = Buffer.concat([d.update(e.ciphertext), d.final()]).toString("utf8");
  return { wsToken, base: e.base };
}

/**
 * Seal the SAME WS token under both the access token and the refresh token
 * (re-wrap on rotation). Call at the token endpoint, where both new tokens are
 * visible. `refreshToken` may be absent (e.g. a client without offline_access).
 */
export function sealForTokens(
  wsToken: string,
  base: string,
  accessToken: string,
  refreshToken?: string,
): void {
  vaultAt.set(sha256(accessToken), seal(accessToken, wsToken, base, AT_TTL_MS));
  if (refreshToken) {
    vaultRt.set(sha256(refreshToken), seal(refreshToken, wsToken, base, RT_TTL_MS));
  }
}

/** Recover the WS token for a request presenting `accessToken` (used by /verify). */
export function unsealByAccess(accessToken: string): { wsToken: string; base: string } | null {
  const k = sha256(accessToken);
  const e = vaultAt.get(k);
  if (!e || e.expires < Date.now()) {
    vaultAt.delete(k);
    return null;
  }
  try {
    return unseal(accessToken, e);
  } catch {
    return null;
  }
}

/** Recover the WS token for a refresh presenting the old `refreshToken`. */
export function unsealByRefresh(refreshToken: string): { wsToken: string; base: string } | null {
  const e = vaultRt.get(sha256(refreshToken));
  if (!e || e.expires < Date.now()) return null;
  try {
    return unseal(refreshToken, e);
  } catch {
    return null;
  }
}

/** Drop an access-token vault entry (e.g. when introspection says inactive). */
export function evict(accessToken: string): void {
  vaultAt.delete(sha256(accessToken));
}

// Periodic sweep so expired entries don't accumulate.
setInterval(() => {
  const now = Date.now();
  for (const m of [pending, vaultAt, vaultRt]) {
    for (const [k, v] of m as Map<string, { expires: number }>) if (v.expires < now) m.delete(k);
  }
}, 60 * 1000).unref();
