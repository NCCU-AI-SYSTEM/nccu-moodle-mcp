/**
 * At-rest protection for the Moodle WS token.
 *
 * The token is never stored in a form the server can read on its own. It is
 * encrypted with a key DERIVED FROM the client's OAuth access token — a secret
 * only the client holds and presents on each request (Hydra stores only a hash
 * of it). So the server can decrypt only DURING a live request; a stolen
 * vault/DB dump yields nothing without a live access token.
 *
 * Two in-memory stores (nothing sensitive on disk):
 *   - `pending`: link handle -> {wsToken, base}, single-use, short TTL. Bridges
 *     the gap between consent (no access token yet) and the first request.
 *   - `vault`:   sha256(access_token) -> sealed {wsToken} + base. Populated on
 *     the first request; read on every later request.
 *
 * NOTE: in-memory means an auth-service restart forces users to re-login (the
 * "token-only, re-login on expiry" model). Swap these Maps for Redis to persist.
 */
import {
  createCipheriv,
  createDecipheriv,
  createHash,
  hkdfSync,
  randomBytes,
  randomUUID,
} from "node:crypto";

const PENDING_TTL_MS = 15 * 60 * 1000; // consent -> first request
const VAULT_TTL_MS = 8 * 60 * 60 * 1000; // ~ access-token lifetime (housekeeping)

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
const vault = new Map<string, Sealed>();

export function sha256(s: string): string {
  return createHash("sha256").update(s).digest("hex");
}

/** Store the WS token under a fresh single-use handle; returns the handle. */
export function stashPending(wsToken: string, base: string): string {
  const link = randomUUID();
  pending.set(link, { wsToken, base, expires: Date.now() + PENDING_TTL_MS });
  return link;
}

function takePending(link: string): Pending | undefined {
  const p = pending.get(link);
  pending.delete(link); // single-use
  if (!p || p.expires < Date.now()) return undefined;
  return p;
}

function key(accessToken: string, salt: Buffer): Buffer {
  // HKDF-SHA256(IKM = access_token, salt, info) -> 32-byte AES key.
  return Buffer.from(hkdfSync("sha256", accessToken, salt, "moodle-ws-token", 32));
}

function seal(accessToken: string, wsToken: string, base: string): Sealed {
  const salt = randomBytes(16);
  const iv = randomBytes(12);
  const c = createCipheriv("aes-256-gcm", key(accessToken, salt), iv);
  const ciphertext = Buffer.concat([c.update(wsToken, "utf8"), c.final()]);
  return { salt, iv, tag: c.getAuthTag(), ciphertext, base, expires: Date.now() + VAULT_TTL_MS };
}

function unseal(accessToken: string, e: Sealed): string {
  const d = createDecipheriv("aes-256-gcm", key(accessToken, e.salt), e.iv);
  d.setAuthTag(e.tag);
  return Buffer.concat([d.update(e.ciphertext), d.final()]).toString("utf8");
}

/**
 * Resolve the Moodle token for a request that presents `accessToken`.
 *   - vault hit  -> decrypt and return.
 *   - vault miss -> bootstrap from `pending[link]` (first request after login),
 *                   seal into the vault, and return.
 *   - neither    -> null (link expired/unknown; caller should force re-login).
 */
export function resolveToken(
  accessToken: string,
  link: string | undefined,
): { wsToken: string; base: string } | null {
  const k = sha256(accessToken);
  const hit = vault.get(k);
  if (hit && hit.expires >= Date.now()) {
    return { wsToken: unseal(accessToken, hit), base: hit.base };
  }
  vault.delete(k);
  if (!link) return null;
  const p = takePending(link);
  if (!p) return null;
  vault.set(k, seal(accessToken, p.wsToken, p.base));
  return { wsToken: p.wsToken, base: p.base };
}

/** Drop a vault entry (e.g. when introspection reports the token inactive). */
export function evict(accessToken: string): void {
  vault.delete(sha256(accessToken));
}

// Periodic sweep of expired entries so memory doesn't grow unbounded.
setInterval(() => {
  const now = Date.now();
  for (const [k, v] of pending) if (v.expires < now) pending.delete(k);
  for (const [k, v] of vault) if (v.expires < now) vault.delete(k);
}, 60 * 1000).unref();
