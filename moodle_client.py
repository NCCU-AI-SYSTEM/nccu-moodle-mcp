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


class MoodleAuthError(RuntimeError):
    """Raised when SSO authentication fails (bad credentials, lockout, layout change)."""


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

    # ---- construction ---------------------------------------------------- #
    @classmethod
    def login(cls, username: str, password: str) -> "MoodleClient":
        """Run the full NCCU SSO -> Moodle handoff and return a ready client."""
        s = requests.Session()
        s.headers.update({"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"})

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
        if not any(c.name == ".LDAPAUTH" for c in s.cookies):
            raise MoodleAuthError("Authentication failed: wrong credentials or account locked.")

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

    # ---- tools ----------------------------------------------------------- #
    def list_courses(self, sem: str | None = None) -> list[dict]:
        """List the user's courses from the semester accordion on the Moodle
        home page (the `card-header` sections under #SemesterGroup).

        sem : which semester to return.
              - None (default): only the latest semester (the first block).
              - a term code or label, e.g. "1142" or "1142-2026 Spring Semester":
                that semester (matched against the header code/label).
              - "all": every semester.

        Returns one dict per course: {id, name, url, semester, current}
        `current` is True for the currently-open (expanded) semester.
        """
        soup = BeautifulSoup(self.get("/").text, "html.parser")
        group = soup.select_one("#SemesterGroup")
        if group is None:
            return []

        cards = group.select(".card")
        want = (sem or "").strip().lower()

        def matches(idx: int, code: str, label: str) -> bool:
            if want == "" or want == "latest":
                return idx == 0                      # default -> first block only
            if want == "all":
                return True
            return want == code.lower() or want in label.lower()

        courses: list[dict] = []
        for idx, card in enumerate(cards):
            header = card.select_one(".card-header")
            if header is None:
                continue
            code = header.get("id", "")               # e.g. "1151"
            btn = header.select_one("h5 button, button, h5")
            label = btn.get_text(strip=True) if btn else header.get_text(strip=True)
            if not matches(idx, code, label):
                continue

            collapse = card.select_one(".collapse")
            is_current = bool(collapse and "show" in (collapse.get("class") or []))
            body = card.select_one(".card-body")
            if body is None:
                continue
            for a in body.select('a[href*="course/view.php?id="]'):
                href = a.get("href", "")
                cid = href.split("id=")[-1].split("&")[0]
                # The link text carries the full course name (the title attr is
                # sometimes truncated to just the course code); icon has no text.
                name = a.get_text(" ", strip=True) or a.get("title", "")
                courses.append({
                    "id": int(cid) if cid.isdigit() else cid,
                    "name": name.strip(),
                    "url": href if href.startswith("http") else self.url(href),
                    "semester": label,
                    "current": is_current,
                })
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
