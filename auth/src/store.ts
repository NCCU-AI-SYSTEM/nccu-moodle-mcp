/**
 * Durable store for the sealed-token vault, so it survives an auth-service
 * restart (the Moodle token is used continuously; we don't want to force a
 * re-login on every deploy/restart).
 *
 * Backed by the existing Postgres (reused, own table). What we persist is only
 * ciphertext keyed by sha256(token) with the crypto parameters — NEVER a token
 * itself and never the derived key. A database dump therefore stays useless
 * without a live access/refresh token (see vault.ts).
 *
 * Falls back to a pure in-memory map if DATABASE_URL is unset (e.g. quick local
 * runs) so the service still works, just without persistence.
 */
import pg from "pg";

export interface VaultRow {
  salt: string; // base64
  iv: string; // base64
  tag: string; // base64
  ct: string; // base64 ciphertext of the WS token
  base: string;
}

const DSN = process.env.DATABASE_URL || "";
const mem = new Map<string, { data: VaultRow; expires: number }>();
let pool: pg.Pool | null = null;
let ready: Promise<void> | null = null;

async function init(): Promise<void> {
  if (!DSN) return; // in-memory fallback
  pool = new pg.Pool({ connectionString: DSN, max: 4 });
  await pool.query(
    `CREATE TABLE IF NOT EXISTS token_vault (
       k          text   PRIMARY KEY,
       data       jsonb  NOT NULL,
       expires_at bigint NOT NULL
     )`,
  );
}
function ensureReady(): Promise<void> {
  if (!ready) ready = init().catch((e) => {
    console.error("store: init failed, using in-memory fallback", e);
    pool = null;
  });
  return ready;
}

export async function put(k: string, data: VaultRow, expires: number): Promise<void> {
  await ensureReady();
  if (!pool) {
    mem.set(k, { data, expires });
    return;
  }
  await pool.query(
    `INSERT INTO token_vault (k, data, expires_at) VALUES ($1, $2, $3)
     ON CONFLICT (k) DO UPDATE SET data = EXCLUDED.data, expires_at = EXCLUDED.expires_at`,
    [k, JSON.stringify(data), expires],
  );
}

export async function get(k: string): Promise<VaultRow | null> {
  await ensureReady();
  if (!pool) {
    const e = mem.get(k);
    if (!e || e.expires < Date.now()) {
      mem.delete(k);
      return null;
    }
    return e.data;
  }
  const r = await pool.query("SELECT data, expires_at FROM token_vault WHERE k = $1", [k]);
  if (!r.rows.length) return null;
  if (Number(r.rows[0].expires_at) < Date.now()) {
    await del(k);
    return null;
  }
  return r.rows[0].data as VaultRow;
}

export async function del(k: string): Promise<void> {
  await ensureReady();
  if (!pool) {
    mem.delete(k);
    return;
  }
  await pool.query("DELETE FROM token_vault WHERE k = $1", [k]);
}

/** Delete expired rows so the table doesn't grow unbounded. */
export async function sweep(): Promise<void> {
  await ensureReady();
  if (!pool) {
    const now = Date.now();
    for (const [k, v] of mem) if (v.expires < now) mem.delete(k);
    return;
  }
  await pool.query("DELETE FROM token_vault WHERE expires_at < $1", [Date.now()]);
}
