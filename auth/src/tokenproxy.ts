/**
 * Transparent proxy for Hydra's token endpoint (POST /oauth2/token).
 *
 * It forwards the request to Hydra UNCHANGED and returns Hydra's response bytes
 * UNCHANGED — so PKCE, client auth, errors, etc. are untouched. Its only extra
 * job is to peek at successful responses and re-wrap the Moodle WS token under
 * the freshly issued tokens (the only place both the new access token and new
 * refresh token are visible together):
 *
 *   - authorization_code grant: recover WS from `pending` (introspect the new AT
 *     -> ext.link -> pending[link]) and seal it under the new AT + RT.
 *   - refresh_token grant: recover WS from the OLD refresh token's vault entry
 *     and re-seal it under the new AT + RT.
 *
 * The WS token value is never changed here — only re-encrypted. Sealing failures
 * never affect the passthrough (a later /mcp miss just forces a re-login).
 */
import type { Request, Response } from "express";
import axios from "axios";
import { introspect } from "./hydra.js";
import { evictRefresh, sealForTokens, takePending, unsealByRefresh } from "./vault.js";

const HYDRA_TOKEN_URL =
  (process.env.HYDRA_PUBLIC_URL || "http://hydra:4444").replace(/\/$/, "") + "/oauth2/token";

export async function tokenProxy(req: Request, res: Response): Promise<void> {
  const rawBody: Buffer = Buffer.isBuffer(req.body) ? req.body : Buffer.from("");

  // Forward to Hydra verbatim (content-type + client auth preserved).
  const fwdHeaders: Record<string, string> = {
    "content-type": req.header("content-type") || "application/x-www-form-urlencoded",
  };
  const auth = req.header("authorization");
  if (auth) fwdHeaders["authorization"] = auth;

  let hydraStatus = 502;
  let hydraCT = "application/json";
  let hydraBody: Buffer = Buffer.from("");
  try {
    const r = await axios.post(HYDRA_TOKEN_URL, rawBody, {
      headers: fwdHeaders,
      responseType: "arraybuffer",
      validateStatus: () => true,
      timeout: 15000,
    });
    hydraStatus = r.status;
    hydraCT = (r.headers["content-type"] as string) || "application/json";
    hydraBody = Buffer.from(r.data);
  } catch (e) {
    console.error("token proxy: forwarding to Hydra failed", e);
    res.status(502).type("application/json").send('{"error":"server_error"}');
    return;
  }

  // Re-wrap the WS token on success. Never let this break the passthrough.
  if (hydraStatus >= 200 && hydraStatus < 300) {
    try {
      const tok = JSON.parse(hydraBody.toString("utf8"));
      const accessToken: string | undefined = tok.access_token;
      const refreshToken: string | undefined = tok.refresh_token;
      if (accessToken) {
        const params = new URLSearchParams(rawBody.toString("utf8"));
        const grant = params.get("grant_type");
        if (grant === "authorization_code") {
          const intro = await introspect(accessToken);
          const link = intro.ext?.link as string | undefined;
          const ws = link ? takePending(link) : undefined;
          if (ws) await sealForTokens(ws.wsToken, ws.base, accessToken, refreshToken);
        } else if (grant === "refresh_token") {
          const oldRt = params.get("refresh_token") || "";
          const ws = await unsealByRefresh(oldRt);
          if (ws) {
            await sealForTokens(ws.wsToken, ws.base, accessToken, refreshToken);
            await evictRefresh(oldRt); // drop the now-rotated RT's stale entry
          }
        }
      }
    } catch (e) {
      console.error("token proxy: re-wrap skipped", e);
    }
  }

  res.status(hydraStatus).type(hydraCT).send(hydraBody);
}
