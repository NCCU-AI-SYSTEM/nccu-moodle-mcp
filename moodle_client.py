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

import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, unquote, urljoin, urlsplit

import requests
from bs4 import BeautifulSoup

# NCCU is UTC+8; Moodle returns unix timestamps.
TAIPEI = timezone(timedelta(hours=8))


def _ts(epoch) -> str | None:
    """Unix timestamp -> 'YYYY-MM-DD HH:MM' in Taipei time, or None if unset (0)."""
    if not epoch:
        return None
    return datetime.fromtimestamp(int(epoch), TAIPEI).strftime("%Y-%m-%d %H:%M")


def _text(html: str | None) -> str:
    """Strip HTML to plain text (for summaries / feedback)."""
    if not html:
        return ""
    return BeautifulSoup(html, "html.parser").get_text(" ", strip=True)


def _term_code(text: str | None) -> str:
    """NCCU term code = the leading 4 digits of a course short/full name (e.g. '1151')."""
    import re
    m = re.match(r"\s*(\d{4})", text or "")
    return m.group(1) if m else ""


def _select_by_sem(items: list[dict], sem: str | None, term_key: str = "semester") -> list[dict]:
    """Filter items (each carrying a term code under `term_key`) by `sem`:
    None/''/'latest' -> only the highest (latest) term; 'all' -> everything;
    otherwise -> exact term-code match."""
    want = (sem or "").strip().lower()
    terms = [it[term_key] for it in items if it.get(term_key)]
    latest = max(terms) if terms else ""
    if want in ("", "latest"):
        return [it for it in items if it.get(term_key) == latest]
    if want == "all":
        return list(items)
    return [it for it in items if (it.get(term_key) or "").lower() == want]

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

        # 0. Discover (once, cached) the SSO login URL and the Moodle backend base
        #    from Moodle's login page, so neither the MoodleSSOxx.aspx version nor
        #    the moodleNN host is hardcoded.
        login_url, base = _discover_site(s)
        p = urlsplit(login_url)
        portal = f"{p.scheme}://{p.netloc}"                       # https://i.nccu.edu.tw
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
        r = s.post(login_url, data=payload,
                   headers={"Origin": portal, "Referer": login_url}, allow_redirects=True)
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
            s.post(allow_submit_url, json={},
                   headers={"X-Requested-With": "XMLHttpRequest",
                            "Content-Type": "application/json; charset=UTF-8",
                            "Origin": portal, "Referer": sso_app_url})
        except requests.RequestException:
            pass  # non-fatal; handoff below is what matters

        # 5. Hand off to Moodle. The SSO form posts to itself, so the real target
        #    is <base>/login.php carrying the SSO token. `base` is the resolved
        #    backend (from discovery), so this POST goes there directly and a
        #    cross-host 303 can't turn it into a GET and strip the token.
        if not action or action.split("?")[0].rstrip("/") == r.url.split("?")[0].rstrip("/"):
            action = f"{base}/login.php"
        r = s.post(action, data=fields,
                   headers={"Origin": portal, "Referer": sso_app_url}, allow_redirects=True)
        msid = s.cookies.get("MoodleSession")
        if not msid:
            raise MoodleAuthError("SSO handoff failed: no MoodleSession cookie issued.")

        client = cls(username=username, session=s, moodle_session_id=msid, base_url=base)
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
        raw = self.ws("core_enrol_get_users_courses", userid=self._get_userid())
        if not isinstance(raw, list):
            return []

        courses = [{
            "id": c.get("id"),
            "name": c.get("fullname") or c.get("shortname") or "",
            "url": self.url(f"/course/view.php?id={c.get('id')}"),
            "semester": _term_code(c.get("shortname") or c.get("fullname")),
        } for c in raw]

        terms = [c["semester"] for c in courses if c["semester"]]
        latest = max(terms) if terms else ""
        for c in courses:
            c["current"] = c["semester"] == latest

        courses = _select_by_sem(courses, sem)
        # Newest term first, preserving API order within a term.
        courses.sort(key=lambda c: c["semester"], reverse=True)
        return courses

    def list_assignments(self, sem: str | None = None,
                          course_ids: list[int] | None = None) -> list[dict]:
        """List assignments via mod_assign_get_assignments. One dict per assignment:
        {id, course_id, course, name, due, opens, cutoff, url}. Sorted by due date.

        course_ids : restrict to these Moodle course ids (passed to Moodle as
                     `courseids`). When given, `sem` is ignored.
        sem        : when course_ids is not given, filter all enrolled courses by
                     semester term code (default: latest). See list_courses.
        """
        if course_ids:
            params = {f"courseids[{i}]": cid for i, cid in enumerate(course_ids)}
            data = self.ws("mod_assign_get_assignments", **params)
        else:
            data = self.ws("mod_assign_get_assignments")   # all enrolled courses

        courses = [{
            "id": co.get("id"),
            "name": co.get("fullname") or co.get("shortname") or "",
            "semester": _term_code(co.get("shortname") or co.get("fullname")),
            "assignments": co.get("assignments", []),
        } for co in data.get("courses", [])]

        # Explicit course_ids already scoped the fetch; otherwise filter by sem.
        selected = courses if course_ids else _select_by_sem(courses, sem)
        out = []
        for co in selected:
            for a in co["assignments"]:
                out.append({
                    "id": a.get("id"),
                    "course_id": co["id"],
                    "course": co["name"],
                    "name": a.get("name"),
                    "due": _ts(a.get("duedate")),
                    "opens": _ts(a.get("allowsubmissionsfromdate")),
                    "cutoff": _ts(a.get("cutoffdate")),
                    "url": self.url(f"/mod/assign/view.php?id={a.get('cmid')}"),
                })
        out.sort(key=lambda x: x["due"] or "9999")
        return out

    def upcoming_deadlines(self, days: int = 14) -> list[dict]:
        """Upcoming action events (assignment due dates, quizzes, etc.) across all
        courses in the next `days`, via core_calendar_get_action_events_by_timesort.
        One dict per event: {name, course, due, overdue, module, url}."""
        now = int(time.time())
        data = self.ws(
            "core_calendar_get_action_events_by_timesort",
            timesortfrom=now, timesortto=now + days * 86400, limitnum=50,
        )
        out = []
        for e in data.get("events", []):
            out.append({
                "name": e.get("name"),
                "course": (e.get("course") or {}).get("fullname", ""),
                "due": _ts(e.get("timesort")),
                "overdue": bool(e.get("overdue")),
                "module": e.get("modulename"),
                "url": e.get("url") or e.get("viewurl"),
            })
        return out

    def get_grades(self, course_id: int) -> list[dict]:
        """Your grade items for one course, via gradereport_user_get_grade_items.
        One dict per item: {item, grade, percentage, range, feedback, type}."""
        data = self.ws("gradereport_user_get_grade_items",
                       courseid=course_id, userid=self._get_userid())
        usergrades = data.get("usergrades", [])
        if not usergrades:
            return []
        out = []
        for it in usergrades[0].get("gradeitems", []):
            name = it.get("itemname")
            if not name and it.get("itemtype") == "course":
                name = "Course total"
            out.append({
                "item": name or it.get("itemtype"),
                "grade": it.get("gradeformatted"),
                "percentage": it.get("percentageformatted"),
                "range": it.get("rangeformatted"),
                "feedback": _text(it.get("feedback")),
                "type": it.get("itemtype"),
            })
        return out

    def get_course_contents(self, course_id: int) -> list[dict]:
        """Sections and activities/resources of a course, via core_course_get_contents.
        One dict per section: {section, summary, modules:[{name, type, url}]}."""
        data = self.ws("core_course_get_contents", courseid=course_id)
        sections = []
        for s in data:
            modules = [{
                "name": mod.get("name"),
                "type": mod.get("modname"),
                "url": mod.get("url"),
            } for mod in s.get("modules", [])]
            sections.append({
                "section": s.get("name"),
                "summary": _text(s.get("summary")),
                "modules": modules,
            })
        return sections

    def get_announcements(self, course_id: int | None = None, limit: int = 10) -> list[dict]:
        """Course announcements — posts in the "Announcements" (news) forum — via
        mod_forum_get_forums_by_courses + mod_forum_get_forum_discussions.

        course_id : one course; if omitted, aggregates across the latest
                    semester's courses.
        Returns newest-first: {course_id, course, subject, author, posted,
        message, replies, url}, capped at `limit`.
        """
        if course_id:
            course_ids, names = [course_id], {}
        else:
            courses = self.list_courses()          # latest semester
            course_ids = [c["id"] for c in courses]
            names = {c["id"]: c["name"] for c in courses}
        if not course_ids:
            return []

        params = {f"courseids[{i}]": cid for i, cid in enumerate(course_ids)}
        forums = self.ws("mod_forum_get_forums_by_courses", **params)

        out = []
        for fo in forums:
            if fo.get("type") != "news":           # the Announcements forum
                continue
            cid = fo.get("course")
            disc = self.ws("mod_forum_get_forum_discussions", forumid=fo["id"])
            for d in disc.get("discussions", []):
                out.append({
                    "course_id": cid,
                    "course": names.get(cid, ""),
                    "subject": d.get("subject") or d.get("name"),
                    "author": (d.get("userfullname") or "").strip(),
                    "posted": _ts(d.get("created")),
                    "message": _text(d.get("message")),
                    "replies": d.get("numreplies"),
                    "url": self.url(f"/mod/forum/discuss.php?d={d.get('discussion')}"),
                })
        out.sort(key=lambda x: x["posted"] or "", reverse=True)
        return out[:limit]

    def get_notifications(self, limit: int = 10) -> list[dict]:
        """The user's notifications (the app's notification bell), via
        message_popup_get_popup_notifications. Newest first:
        {subject, message, posted, read, url}."""
        data = self.ws("message_popup_get_popup_notifications",
                       useridto=self._get_userid(), limit=limit, offset=0)
        out = []
        for n in data.get("notifications", []):
            out.append({
                "subject": n.get("subject"),
                "message": _text(n.get("smallmessage") or n.get("fullmessagehtml")
                                 or n.get("fullmessage")),
                "posted": _ts(n.get("timecreated")),
                "read": bool(n.get("read")),
                "url": n.get("contexturl"),
            })
        return out

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
