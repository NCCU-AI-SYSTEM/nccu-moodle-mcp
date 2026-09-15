"""
MoodleClient - a per-user, self-contained NCCU Moodle session.

Designed for a multi-tenant MCP server: no shared/global cookie cache. Each
MCP call authenticates its own user via SSO and gets back an isolated
MoodleClient whose `.session` (a requests.Session with that user's cookies) is
passed down to whatever functions do the work.

Typical MCP handler:

    with MoodleClient.login(username, password) as m:
        courses = m.get_json("/lib/ajax/service.php", ...)   # uses m.session
        return courses

One login == the full SSO handoff (~5 requests). If you find yourself calling
several tools inside one MCP invocation, build ONE client and reuse it for all
of them rather than logging in per function.
"""

from __future__ import annotations

import concurrent.futures
import os
from dataclasses import dataclass, field
from urllib.parse import parse_qs, unquote, urljoin, urlsplit

import requests
from bs4 import BeautifulSoup

# Stable entry host. It 303-redirects to the current backend instance
# (moodle45 today, maybe a different number later) — we never hardcode that.
MOODLE = "https://moodle.nccu.edu.tw"

# Site-wide config discovered once and cached in memory (NOT user data): the NCCU
# SSO login URL (which encodes the MoodleSSOxx.aspx path) and the resolved Moodle
# backend base. Discovered from Moodle's own login page so nothing is hardcoded.
_SSO_LOGIN_URL: str | None = None
_MOODLE_BASE: str | None = None

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/152.0.0.0 Safari/537.36"
)

# The mobile Web Services token launch is only served to a mobile browser, and
# Moodle binds the session to the User-Agent — so the WHOLE token flow (SSO login
# + launch.php) must run under this UA. Used only for token requests; the default
# session UA stays desktop (UA above).
IPHONE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
)


class MoodleAuthError(RuntimeError):
    """Raised when SSO authentication fails (bad credentials, layout change)."""


def _inputs(scope) -> dict[str, str]:
    return {i.get("name"): i.get("value", "") for i in scope.find_all("input") if i.get("name")}


def _discover_site(session: requests.Session) -> tuple[str, str]:
    """Return (sso_login_url, moodle_base), discovering them once and caching in
    memory. On first call it fetches Moodle's English login page and reads the
    "NCCU faculty and students" button (a.inccu-button pointing at i.nccu.edu.tw)
    for the SSO login URL, and the page's final URL for the backend base — so the
    MoodleSSOxx.aspx version and the moodleNN host are never hardcoded.

    MOODLE_SSO_URL overrides the SSO login URL (and skips the discovery fetch for
    it). This is site-wide config, not per-user state.
    """
    global _SSO_LOGIN_URL, _MOODLE_BASE
    env = os.environ.get("MOODLE_SSO_URL", "").strip()
    if env:
        _SSO_LOGIN_URL = env
    if _SSO_LOGIN_URL and _MOODLE_BASE:
        return _SSO_LOGIN_URL, _MOODLE_BASE

    r = session.get(MOODLE + "/?lang=en", allow_redirects=True, timeout=15)
    p = urlsplit(r.url)
    if p.scheme and p.netloc:
        _MOODLE_BASE = f"{p.scheme}://{p.netloc}"
    if not _SSO_LOGIN_URL:
        soup = BeautifulSoup(r.text, "html.parser")
        for a in soup.select("a.inccu-button, a.btn-login"):
            href = a.get("href", "")
            if "Login.aspx" in href and "i.nccu.edu.tw" in href:
                _SSO_LOGIN_URL = href
                break
    if not _SSO_LOGIN_URL:
        raise MoodleAuthError(
            "Could not find the NCCU SSO login link on Moodle's login page; "
            "set MOODLE_SSO_URL to the i.nccu.edu.tw Login.aspx URL."
        )
    return _SSO_LOGIN_URL, (_MOODLE_BASE or MOODLE)


def prewarm() -> tuple[str, str] | None:
    """Eagerly discover and cache the SSO login URL + Moodle base, so the first
    real login doesn't pay the discovery cost. Best-effort: on failure the cache
    stays empty and discovery falls back to lazy (on first login). Safe to call
    at server startup."""
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"})
    try:
        return _discover_site(s)
    except Exception:
        return None
    finally:
        s.close()


@dataclass
class MoodleClient:
    """Holds one authenticated user's Moodle session."""

    username: str
    session: requests.Session
    moodle_session_id: str
    fullname: str = ""
    base_url: str = MOODLE
    sesskey: str = field(default="", repr=False)
    ws_token: str = field(default="", repr=False)  # mobile Web Services token
    userid: int | None = None

    # ---- construction ---------------------------------------------------- #
    @classmethod
    def login(cls, username: str, password: str, *, user_agent: str = UA) -> MoodleClient:
        """Run the full NCCU SSO -> Moodle handoff and return a ready client.

        user_agent: the User-Agent used for the ENTIRE flow. Moodle binds the
        session to it, so it must stay constant across login and later requests
        (e.g. the mobile token launch)."""
        s = requests.Session()
        s.headers.update({"User-Agent": user_agent, "Accept-Language": "en-US,en;q=0.9"})

        # 0. Discover (once, cached) the SSO login URL and the Moodle backend base
        #    from Moodle's login page, so neither the MoodleSSOxx.aspx version nor
        #    the moodleNN host is hardcoded.
        login_url, base = _discover_site(s)
        p = urlsplit(login_url)
        portal = f"{p.scheme}://{p.netloc}"  # https://i.nccu.edu.tw
        return_path = unquote((parse_qs(p.query).get("ReturnUrl") or [""])[0])
        sso_app_url = portal + return_path if return_path.startswith("/") else login_url
        allow_submit_url = f"{portal}/SSOService.asmx/AllowSubmit"

        # 1. GET login form -> ASP.NET hidden state.
        r = s.get(login_url)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        if not soup.select_one("#captcha_Login1_UserName"):
            raise MoodleAuthError("Login page layout changed; aborting before a failed attempt.")
        payload = _inputs(soup.find("form"))

        # 2. POST credentials. The login control is a LinkButton, so the
        #    postback is driven by __EVENTTARGET, not a submit-button value.
        payload["captcha$Login1$UserName"] = username
        payload["captcha$Login1$Password"] = password
        payload["__EVENTTARGET"] = "captcha$Login1$LoginButton"
        payload["__EVENTARGUMENT"] = ""
        r = s.post(
            login_url,
            data=payload,
            headers={"Origin": portal, "Referer": login_url},
            allow_redirects=True,
        )
        # The auth ticket (.LDAPAUTH) is issued only on success. If it's absent,
        # the login was rejected — fail here, immediately, before the token/WS steps.
        if not any(c.name == ".LDAPAUTH" for c in s.cookies):
            raise MoodleAuthError("Incorrect username or password.")

        # 3. Land on the SSO app page and parse its handoff form (one-time token).
        if sso_app_url.rsplit("/", 1)[-1].split("?")[0] not in r.url:
            r = s.get(sso_app_url, headers={"Referer": login_url})
        soup = BeautifulSoup(r.text, "html.parser")
        form = soup.find("form")
        if form is None:
            raise MoodleAuthError("SSO page returned no form; login likely rejected.")
        fields = _inputs(form)
        action = urljoin(r.url, form.get("action") or "")

        # 4. Clear the anti double-submit guard the page's JS waits on.
        try:
            s.post(
                allow_submit_url,
                json={},
                headers={
                    "X-Requested-With": "XMLHttpRequest",
                    "Content-Type": "application/json; charset=UTF-8",
                    "Origin": portal,
                    "Referer": sso_app_url,
                },
            )
        except requests.RequestException:
            pass  # non-fatal; handoff below is what matters

        # 5. Hand off to Moodle. The SSO form posts to itself, so the real target
        #    is <base>/login.php carrying the SSO token. `base` is the resolved
        #    backend (from discovery), so this POST goes there directly and a
        #    cross-host 303 can't turn it into a GET and strip the token.
        if not action or action.split("?")[0].rstrip("/") == r.url.split("?")[0].rstrip("/"):
            action = f"{base}/login.php"
        r = s.post(
            action,
            data=fields,
            headers={"Origin": portal, "Referer": sso_app_url},
            allow_redirects=True,
        )
        msid = s.cookies.get("MoodleSession")
        if not msid:
            raise MoodleAuthError("SSO handoff failed: no MoodleSession cookie issued.")

        client = cls(username=username, session=s, moodle_session_id=msid, base_url=base)
        client._hydrate(r.text)  # pick up fullname + sesskey from the landing page
        return client

    @classmethod
    def from_token(
        cls,
        ws_token: str,
        *,
        base_url: str = MOODLE,
        username: str = "",
        user_agent: str = UA,
    ) -> MoodleClient:
        """Build a client from an existing Web Services token — no login.

        The mobile WS token authenticates every WS call on its own (no session
        cookie), so a token + its backend host is all that's needed to run the
        WS-based tools. `base_url` must be the host that ISSUED the token (the
        discovered backend, e.g. https://moodle45.nccu.edu.tw); the token is not
        accepted against the canonical moodle.nccu.edu.tw host.

        Session-cookie helpers (get/post/is_valid/_hydrate) are unavailable on a
        token-only client, but the tools use only `ws`/`ws_parallel`/`url`."""
        s = requests.Session()
        s.headers.update({"User-Agent": user_agent, "Accept-Language": "en-US,en;q=0.9"})
        return cls(
            username=username,
            session=s,
            moodle_session_id="",
            base_url=base_url,
            ws_token=ws_token,
        )

    # ---- session-scoped helpers (pass `self` down to your functions) ----- #
    def url(self, path: str) -> str:
        return path if path.startswith("http") else urljoin(self.base_url + "/", path.lstrip("/"))

    def get(self, path: str, **kw) -> requests.Response:
        return self.session.get(self.url(path), **kw)

    def post(self, path: str, **kw) -> requests.Response:
        return self.session.post(self.url(path), **kw)

    def get_json(self, path: str, **kw) -> object:
        r = self.get(path, **kw)
        r.raise_for_status()
        return r.json()

    def is_valid(self) -> bool:
        """Cheap liveness check: are we still authenticated to Moodle?"""
        r = self.get("/my/", allow_redirects=True)
        return "/login/" not in r.url

    # ---- Web Services (mobile app style) --------------------------------- #
    def fetch_ws_token(self) -> str:
        """Obtain a Moodle mobile Web Services token the way the mobile app does:
        hit admin/tool/mobile/launch.php on the authenticated web session and read
        the `moodlemobile://token=<base64>` it returns. The token is cached on this
        client (`self.ws_token`) and returned.

        Only this request uses the mobile User-Agent (Moodle serves the launch to a
        mobile browser); the rest of the session stays on its default UA.
        """
        import base64
        import random
        import re

        passport = random.uniform(0, 1000)
        r = self.get(
            "/admin/tool/mobile/launch.php?service=moodle_mobile_app"
            f"&passport={passport}&urlscheme=moodlemobile",
            allow_redirects=False,
            headers={"User-Agent": IPHONE_UA},
        )
        # The token comes back either as a Location redirect (desktop) or embedded
        # in a 200 launch page (mobile). Search both.
        source = r.headers.get("Location", "") + " " + r.text
        m = re.search(r"moodlemobile://token=([A-Za-z0-9+/=]+)", source)
        if not m:
            raise MoodleAuthError(
                "Could not obtain a Web Services token (session not authenticated, "
                "or the mobile service is disabled)."
            )
        # base64 -> "signature:::wstoken:::privatetoken"
        decoded = base64.b64decode(m.group(1)).decode()
        self.ws_token = decoded.split(":::")[1]
        return self.ws_token

    def ws(self, wsfunction: str, **params) -> object:
        """Call a Moodle Web Services REST function and return parsed JSON.
        Requires a token (fetched lazily via fetch_ws_token)."""
        if not self.ws_token:
            self.fetch_ws_token()
        payload = {
            "wstoken": self.ws_token,
            "wsfunction": wsfunction,
            "moodlewsrestformat": "json",
            **params,
        }
        r = self.session.post(self.url("/webservice/rest/server.php"), data=payload)
        r.raise_for_status()
        data = r.json()
        if isinstance(data, dict) and data.get("errorcode"):
            raise MoodleAuthError(f"WS error [{data['errorcode']}]: {data.get('message')}")
        return data

    def ws_parallel(self, wsfunction: str, param_list: list[dict], *, max_workers: int = 5) -> list:
        """Call `wsfunction` once per params dict in `param_list`, concurrently
        (up to `max_workers`), returning results in input order.

        Thread-safe: the Moodle WS token authenticates each request on its own
        (no cookie/session state), so each worker issues an independent request
        rather than sharing this client's Session (which isn't thread-safe).
        """
        if not param_list:
            return []
        if not self.ws_token:
            self.fetch_ws_token()
        url = self.url("/webservice/rest/server.php")
        ua = self.session.headers.get("User-Agent")

        def one(params: dict):
            payload = {
                "wstoken": self.ws_token,
                "wsfunction": wsfunction,
                "moodlewsrestformat": "json",
                **params,
            }
            r = requests.post(url, data=payload, headers={"User-Agent": ua})
            r.raise_for_status()
            data = r.json()
            if isinstance(data, dict) and data.get("errorcode"):
                raise MoodleAuthError(f"WS error [{data['errorcode']}]: {data.get('message')}")
            return data

        workers = max(1, min(max_workers, len(param_list)))
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
            return list(ex.map(one, param_list))

    def get_userid(self) -> int:
        """The logged-in user's Moodle id (fetched once via site info)."""
        if self.userid is None:
            info = self.ws("core_webservice_get_site_info")
            self.userid = info["userid"]
            self.fullname = self.fullname or info.get("fullname", "")
        return self.userid

    def _hydrate(self, html: str) -> None:
        """Pull the logged-in user's name + sesskey. Falls back to /my/ if the
        landing page doesn't carry them."""
        import re

        def name_from(h: str) -> str:
            el = BeautifulSoup(h, "html.parser").select_one("span.usertext, .usertext")
            return el.get_text(strip=True) if el else ""

        def sesskey_from(h: str) -> str:
            # The navbar user name is authoritative; the first JSON "fullname"
            # is a *course* title, so never use that for the user.
            mm = re.search(r'"sesskey":"([^"]+)"', h) or re.search(r"[?&]sesskey=([A-Za-z0-9]+)", h)
            return mm.group(1) if mm else ""

        self.fullname = name_from(html)
        self.sesskey = sesskey_from(html)
        if not (self.fullname and self.sesskey):
            my = self.get("/my/").text
            self.fullname = self.fullname or name_from(my)
            self.sesskey = self.sesskey or sesskey_from(my)

    # ---- lifecycle ------------------------------------------------------- #
    def close(self) -> None:
        self.session.close()

    def __enter__(self) -> MoodleClient:
        return self

    def __exit__(self, *exc) -> None:
        self.close()


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser(description="Authenticate one NCCU Moodle user.")
    p.add_argument("username")
    p.add_argument("password")
    args = p.parse_args()

    with MoodleClient.login(args.username, args.password) as m:
        print("username:  ", m.username)
        print("fullname:  ", m.fullname or "(not found)")
        print("session id:", m.moodle_session_id)
        print("sesskey:   ", m.sesskey or "(not found)")
        print("valid:     ", m.is_valid())
