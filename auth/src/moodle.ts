/**
 * Independent reimplementation of the NCCU SSO -> Moodle handoff and the mobile
 * Web Services token fetch. Ported from the Python MoodleClient; this service
 * shares NO code with the Python MCP.
 *
 * The only thing we relay onward is the resulting WS token + the backend host
 * that issued it. The password is used here, in memory, then discarded.
 */
import axios, { AxiosInstance, AxiosResponse } from "axios";
import { wrapper } from "axios-cookiejar-support";
import { CookieJar } from "tough-cookie";
import * as cheerio from "cheerio";

const MOODLE = "https://moodle.nccu.edu.tw";

const UA =
  "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 " +
  "(KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36";

// Moodle serves the mobile token launch only to a mobile browser and binds the
// session to the UA, so the launch request uses this UA.
const IPHONE_UA =
  "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) " +
  "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1";

// Site-wide config, discovered once and cached in memory (not user data).
let ssoLoginUrl: string | null = process.env.MOODLE_SSO_URL?.trim() || null;
let moodleBase: string | null = null;

export class MoodleAuthError extends Error {}

export interface MoodleToken {
  username: string;
  wsToken: string;
  base: string;
}

function newClient(jar: CookieJar): AxiosInstance {
  return wrapper(
    axios.create({
      jar,
      withCredentials: true,
      maxRedirects: 10,
      timeout: 20000,
      // Inspect any status ourselves (the SSO flow reads 3xx/4xx too).
      validateStatus: () => true,
      headers: { "User-Agent": UA, "Accept-Language": "en-US,en;q=0.9" },
    }),
  );
}

/** Final URL after redirects (Node attaches it to the underlying response). */
function finalUrl(r: AxiosResponse, fallback: string): string {
  return (r.request?.res?.responseUrl as string) || fallback;
}

/** All input[name] -> value pairs within a cheerio-selected form. */
function formInputs($: cheerio.CheerioAPI, form: cheerio.Cheerio<any>): Record<string, string> {
  const out: Record<string, string> = {};
  form.find("input").each((_, el) => {
    const name = $(el).attr("name");
    if (name) out[name] = $(el).attr("value") ?? "";
  });
  return out;
}

function hasCookie(jar: CookieJar, name: string): boolean {
  return jar.serializeSync()?.cookies.some((c) => c.key === name) ?? false;
}

async function discoverSite(client: AxiosInstance): Promise<[string, string]> {
  if (ssoLoginUrl && moodleBase) return [ssoLoginUrl, moodleBase];

  const r = await client.get(`${MOODLE}/?lang=en`);
  const url = new URL(finalUrl(r, MOODLE));
  moodleBase = `${url.protocol}//${url.host}`;

  if (!ssoLoginUrl) {
    const $ = cheerio.load(r.data);
    $("a.inccu-button, a.btn-login").each((_, a) => {
      const href = $(a).attr("href") ?? "";
      if (!ssoLoginUrl && href.includes("Login.aspx") && href.includes("i.nccu.edu.tw")) {
        ssoLoginUrl = href;
      }
    });
  }
  if (!ssoLoginUrl) {
    throw new MoodleAuthError(
      "Could not find the NCCU SSO login link on Moodle's login page; " +
        "set MOODLE_SSO_URL to the i.nccu.edu.tw Login.aspx URL.",
    );
  }
  return [ssoLoginUrl, moodleBase || MOODLE];
}

const form = (data: Record<string, string>) => new URLSearchParams(data).toString();

/**
 * Authenticate one user through NCCU SSO and return a mobile WS token + the
 * backend host that issued it. Throws MoodleAuthError on bad credentials.
 */
export async function loginAndMintToken(username: string, password: string): Promise<MoodleToken> {
  const jar = new CookieJar();
  const client = newClient(jar);

  // 0. Discover the SSO login URL + Moodle backend base.
  const [loginUrl, base] = await discoverSite(client);
  const p = new URL(loginUrl);
  const portal = `${p.protocol}//${p.host}`; // https://i.nccu.edu.tw
  const returnPath = decodeURIComponent(p.searchParams.get("ReturnUrl") ?? "");
  const ssoAppUrl = returnPath.startsWith("/") ? portal + returnPath : loginUrl;
  const allowSubmitUrl = `${portal}/SSOService.asmx/AllowSubmit`;

  // 1. GET login form -> ASP.NET hidden state.
  let r = await client.get(loginUrl);
  let $ = cheerio.load(r.data);
  if ($("#captcha_Login1_UserName").length === 0) {
    throw new MoodleAuthError("Login page layout changed; aborting before a failed attempt.");
  }
  const payload = formInputs($, $("form").first());

  // 2. POST credentials via the LinkButton postback (__EVENTTARGET).
  payload["captcha$Login1$UserName"] = username;
  payload["captcha$Login1$Password"] = password;
  payload["__EVENTTARGET"] = "captcha$Login1$LoginButton";
  payload["__EVENTARGUMENT"] = "";
  r = await client.post(loginUrl, form(payload), {
    headers: {
      Origin: portal,
      Referer: loginUrl,
      "Content-Type": "application/x-www-form-urlencoded",
    },
  });

  // The .LDAPAUTH ticket is issued only on success.
  if (!hasCookie(jar, ".LDAPAUTH")) {
    throw new MoodleAuthError("Incorrect username or password.");
  }

  // 3. Land on the SSO app page and parse its handoff form.
  let landedUrl = finalUrl(r, loginUrl);
  const appBasename = ssoAppUrl.split("/").pop()!.split("?")[0];
  if (!landedUrl.includes(appBasename)) {
    r = await client.get(ssoAppUrl, { headers: { Referer: loginUrl } });
    landedUrl = finalUrl(r, ssoAppUrl);
  }
  $ = cheerio.load(r.data);
  const handoff = $("form").first();
  if (handoff.length === 0) {
    throw new MoodleAuthError("SSO page returned no form; login likely rejected.");
  }
  const fields = formInputs($, handoff);
  let action = new URL(handoff.attr("action") || "", landedUrl).toString();

  // 4. Clear the anti double-submit guard (best-effort).
  try {
    await client.post(
      allowSubmitUrl,
      JSON.stringify({}),
      {
        headers: {
          "X-Requested-With": "XMLHttpRequest",
          "Content-Type": "application/json; charset=UTF-8",
          Origin: portal,
          Referer: ssoAppUrl,
        },
      },
    );
  } catch {
    // non-fatal; the handoff below is what matters
  }

  // 5. Hand off to Moodle. If the form posts to itself, target <base>/login.php.
  const sameTarget = action.split("?")[0].replace(/\/$/, "") === landedUrl.split("?")[0].replace(/\/$/, "");
  if (!action || sameTarget) action = `${base}/login.php`;
  r = await client.post(action, form(fields), {
    headers: {
      Origin: portal,
      Referer: ssoAppUrl,
      "Content-Type": "application/x-www-form-urlencoded",
    },
  });
  if (!hasCookie(jar, "MoodleSession")) {
    throw new MoodleAuthError("SSO handoff failed: no MoodleSession cookie issued.");
  }

  // 6. Fetch the mobile WS token the way the app does (iPhone UA, no redirect).
  const passport = Math.random() * 1000;
  const launch = await client.get(
    `${base}/admin/tool/mobile/launch.php?service=moodle_mobile_app` +
      `&passport=${passport}&urlscheme=moodlemobile`,
    { headers: { "User-Agent": IPHONE_UA }, maxRedirects: 0 },
  );
  const source = `${launch.headers["location"] ?? ""} ${typeof launch.data === "string" ? launch.data : ""}`;
  const m = source.match(/moodlemobile:\/\/token=([A-Za-z0-9+/=]+)/);
  if (!m) {
    throw new MoodleAuthError(
      "Could not obtain a Web Services token (session not authenticated, " +
        "or the mobile service is disabled).",
    );
  }
  // base64 -> "signature:::wstoken:::privatetoken"
  const decoded = Buffer.from(m[1], "base64").toString("utf8");
  const wsToken = decoded.split(":::")[1];
  if (!wsToken) throw new MoodleAuthError("Malformed token payload from launch.php.");

  return { username, wsToken, base };
}
