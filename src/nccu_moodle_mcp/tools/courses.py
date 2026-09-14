"""list_courses — the student's enrolled courses, filtered by semester."""

from __future__ import annotations

from mcp.server.mcpserver import Context

from ..app import Sem, mcp, run_tool
from ..helpers import select_by_sem, term_code


def list_courses(client, sem: str | None = None) -> list[dict]:
    """Enrolled courses via core_enrol_get_users_courses, semester derived from
    the leading term code in each course's shortname (e.g. "1151_..." -> "1151").

    sem: None/'latest' -> latest term only; a term code -> that term; 'all' -> every course.
    Returns {id, name, url, semester, current}, newest term first.
    """
    raw = client.ws("core_enrol_get_users_courses", userid=client.get_userid())
    if not isinstance(raw, list):
        return []

    courses = [
        {
            "id": c.get("id"),
            "name": c.get("fullname") or c.get("shortname") or "",
            "url": client.url(f"/course/view.php?id={c.get('id')}"),
            "semester": term_code(c.get("shortname") or c.get("fullname")),
        }
        for c in raw
    ]

    terms = [c["semester"] for c in courses if c["semester"]]
    latest = max(terms) if terms else ""
    for c in courses:
        c["current"] = c["semester"] == latest

    courses = select_by_sem(courses, sem)
    courses.sort(key=lambda c: c["semester"], reverse=True)
    return courses


@mcp.tool(
    name="list_courses",
    title="List Moodle courses",
    description=(
        "List the student's enrolled Moodle courses, filtered by semester.\n\n"
        "By default (no `sem`), returns ONLY the latest semester's courses "
        '(the current term). Pass `sem` as an NCCU term code (e.g. "1142") to '
        'get that semester; pass "all" to return every enrolled course.\n\n'
        "Each course is returned as an object with:\n"
        "  - id       (int)  Moodle course id, usable in other course tools\n"
        "  - name     (str)  full course title\n"
        "  - url      (str)  direct link to the course\n"
        '  - semester (str)  NCCU term code the course belongs to (e.g. "1151")\n'
        "  - current  (bool) true if it is in the current (latest) semester\n\n"
        "Authentication is automatic: the user's NCCU credentials come from the "
        "MCP client settings (headers), not from you. Just call the tool; you "
        "never need — or have — the user's password."
    ),
)
def _list_courses(ctx: Context, sem: Sem = None) -> dict:
    items = run_tool(ctx, lambda m: list_courses(m, sem=sem))
    return {"count": len(items), "courses": items}
