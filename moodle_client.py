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

from dataclasses import dataclass, field
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

PORTAL = "https://i.nccu.edu.tw"
LOGIN_URL = f"{PORTAL}/Login.aspx?ReturnUrl=%2fsso_app%2fMoodleSSO45.aspx"
SSO_APP_URL = f"{PORTAL}/sso_app/MoodleSSO45.aspx"
ALLOW_SUBMIT_URL = f"{PORTAL}/SSOService.asmx/AllowSubmit"
MOODLE = "https://moodle45.nccu.edu.tw"

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


@dataclass
class MoodleClient:
    """Holds one authenticated user's Moodle session."""

    username: str
    session: requests.Session
    moodle_session_id: str
    fullname: str = ""
    base_url: str = MOODLE
    sesskey: str = field(default="", repr=False)
    ws_token: str = field(default="", repr=False)   # mobile Web Services token
    userid: int | None = None

    # ---- construction ---------------------------------------------------- #
    @classmethod
    def login(cls, username: str, password: str, *, user_agent: str = UA) -> "MoodleClient":
        """Run the full NCCU SSO -> Moodle handoff and return a ready client.

        user_agent: the User-Agent used for the ENTIRE flow. Moodle binds the
        session to it, so it must stay constant across login and later requests
        (e.g. the mobile token launch)."""
        s = requests.Session()
        s.headers.update({"User-Agent": user_agent, "Accept-Language": "en-US,en;q=0.9"})

        # 1. GET login form -> ASP.NET hidden state.
        r = s.get(LOGIN_URL)
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
        r = s.post(LOGIN_URL, data=payload,
                   headers={"Origin": PORTAL, "Referer": LOGIN_URL}, allow_redirects=True)
        # The auth ticket (.LDAPAUTH) is issued only on success. If it's absent,
        # the login was rejected — fail here, immediately, before the token/WS steps.
        if not any(c.name == ".LDAPAUTH" for c in s.cookies):
            raise MoodleAuthError("Incorrect username or password.")

        # 3. Land on the SSO app page and parse its handoff form (one-time token).
        if "MoodleSSO45.aspx" not in r.url:
            r = s.get(SSO_APP_URL, headers={"Referer": LOGIN_URL})
        soup = BeautifulSoup(r.text, "html.parser")
        form = soup.find("form")
        if form is None:
            raise MoodleAuthError("SSO page returned no form; login likely rejected.")
        fields = _inputs(form)
        action = urljoin(r.url, form.get("action") or "")

        # 4. Clear the anti double-submit guard the page's JS waits on.
        try:
            s.post(ALLOW_SUBMIT_URL, json={},
                   headers={"X-Requested-With": "XMLHttpRequest",
                            "Content-Type": "application/json; charset=UTF-8",
                            "Origin": PORTAL, "Referer": SSO_APP_URL})
        except requests.RequestException:
            pass  # non-fatal; handoff below is what matters

        # 5. Hand off to Moodle. The SSO form posts to itself, so the real
        #    target is moodle45/login.php carrying the SSO token.
        if not action or action.split("?")[0].rstrip("/") == r.url.split("?")[0].rstrip("/"):
            action = f"{MOODLE}/login.php"
        r = s.post(action, data=fields,
                   headers={"Origin": PORTAL, "Referer": SSO_APP_URL}, allow_redirects=True)
        msid = s.cookies.get("MoodleSession")
        if not msid:
            raise MoodleAuthError("SSO handoff failed: no MoodleSession cookie issued.")

        client = cls(username=username, session=s, moodle_session_id=msid)
        client._hydrate(r.text)  # pick up fullname + sesskey from the landing page
        return client

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

    def _get_userid(self) -> int:
        if self.userid is None:
            info = self.ws("core_webservice_get_site_info")
            self.userid = info["userid"]
            self.fullname = self.fullname or info.get("fullname", "")
        return self.userid

    # ---- tools ----------------------------------------------------------- #
    def list_courses(self, sem: str | None = None) -> list[dict]:
        """List the user's courses via the Moodle mobile Web Services API
        (core_enrol_get_users_courses), grouped/filtered by semester.

        Semester is derived from the leading term code in each course's
        shortname (e.g. "1151_..." -> "1151"); NCCU encodes it there.

        sem : which semester to return.
              - None (default): only the latest semester (highest term code).
              - a term code, e.g. "1142": that semester.
              - "all": every course, every semester.

        Returns one dict per course: {id, name, url, semester, current}
        `current` is True for courses in the latest term code.
        """
        import re

        raw = self.ws("core_enrol_get_users_courses", userid=self._get_userid())
        if not isinstance(raw, list):
            return []

        def term_of(course: dict) -> str:
            # NCCU term code is the leading 4 digits of the shortname/fullname.
            text = course.get("shortname") or course.get("fullname") or ""
            mm = re.match(r"\s*(\d{4})", text)
            return mm.group(1) if mm else ""

        courses = []
        for c in raw:
            courses.append({
                "id": c.get("id"),
                "name": c.get("fullname") or c.get("shortname") or "",
                "url": self.url(f"/course/view.php?id={c.get('id')}"),
                "semester": term_of(c),
            })

        terms = [c["semester"] for c in courses if c["semester"]]
        latest = max(terms) if terms else ""
        for c in courses:
            c["current"] = c["semester"] == latest

        want = (sem or "").strip().lower()
        if want in ("", "latest"):
            courses = [c for c in courses if c["current"]]
        elif want != "all":
            courses = [c for c in courses if c["semester"].lower() == want]

        # Newest term first, preserving API order within a term.
        courses.sort(key=lambda c: c["semester"], reverse=True)
        return courses

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
            mm = re.search(r'"sesskey":"([^"]+)"', h) or re.search(r'[?&]sesskey=([A-Za-z0-9]+)', h)
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

    def __enter__(self) -> "MoodleClient":
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
