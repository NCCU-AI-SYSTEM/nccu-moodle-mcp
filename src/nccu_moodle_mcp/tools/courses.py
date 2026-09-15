"""Courses — list the student's enrolled courses (with role) and look up the
role in a single course."""

from __future__ import annotations

from mcp.server.mcpserver import Context

from ..app import CourseId, Sem, mcp, run_tool
from ..helpers import select_by_sem, term_code


def _roles_from(enrolled_users, userid: int) -> list[str]:
    """Role shortnames of `userid` in a core_enrol_get_enrolled_users result."""
    if not isinstance(enrolled_users, list):
        return []
    me = next((u for u in enrolled_users if u.get("id") == userid), None)
    return [r.get("shortname") for r in (me or {}).get("roles", []) if r.get("shortname")]


def _enrolled_self_params(course_id: int, userid: int) -> dict:
    """core_enrol_get_enrolled_users params filtered to just `userid`."""
    return {
        "courseid": course_id,
        "options[0][name]": "userids",
        "options[0][value]": str(userid),
    }


def list_courses(client, sem: str | None = None, include_role: bool = False) -> list[dict]:
    """Enrolled courses via core_enrol_get_users_courses, semester derived from
    the leading term code in each course's shortname (e.g. "1151_..." -> "1151").

    sem: None/'latest' -> latest term only; a term code -> that term; 'all' -> every course.
    include_role: also add `role` (e.g. 'student' / 'teacher' / 'editingteacher')
        per course — one core_enrol_get_enrolled_users call each, run ≤5 in
        parallel. Off by default so internal callers stay cheap.

    Returns {id, name, url, semester, current[, role]}, newest term first.
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

    if include_role and courses:
        uid = client.get_userid()
        results = client.ws_parallel(
            "core_enrol_get_enrolled_users",
            [_enrolled_self_params(c["id"], uid) for c in courses],
            max_workers=5,
        )
        for c, eu in zip(courses, results, strict=True):
            roles = _roles_from(eu, uid)
            c["role"] = roles[0] if roles else None
    return courses


def get_course_role(client, course_id: int) -> dict:
    """The student's role(s) in one course via core_enrol_get_enrolled_users.
    Returns {course_id, role, roles} where `role` is the primary shortname
    (e.g. 'student', 'teacher', 'editingteacher', 'teachingassistant')."""
    uid = client.get_userid()
    eu = client.ws("core_enrol_get_enrolled_users", **_enrolled_self_params(course_id, uid))
    roles = _roles_from(eu, uid)
    return {"course_id": course_id, "role": roles[0] if roles else None, "roles": roles}


@mcp.tool(
    name="list_courses",
    title="List Moodle courses",
    description=(
        "List the student's enrolled Moodle courses (with the user's role in "
        "each), filtered by semester.\n\n"
        "By default (no `sem`), returns ONLY the latest semester's courses "
        '(the current term). Pass `sem` as an NCCU term code (e.g. "1142") to '
        'get that semester; pass "all" to return every enrolled course.\n\n'
        "Each course is returned as an object with:\n"
        "  - id       (int)  Moodle course id, usable in other course tools\n"
        "  - name     (str)  full course title\n"
        "  - url      (str)  direct link to the course\n"
        '  - semester (str)  NCCU term code the course belongs to (e.g. "1151")\n'
        "  - current  (bool) true if it is in the current (latest) semester\n"
        "  - role     (str)  the user's role: 'student', 'teacher', "
        "'editingteacher', 'teachingassistant', … (null if unknown)\n\n"
        "Credentials come from the MCP settings headers, not from you."
    ),
)
def _list_courses(ctx: Context, sem: Sem = None) -> dict:
    items = run_tool(ctx, lambda m: list_courses(m, sem=sem, include_role=True))
    return {"count": len(items), "courses": items}


@mcp.tool(
    name="get_course_role",
    title="Get my role in a course",
    description=(
        "Get the user's role in one course (by Moodle course id, from "
        "list_courses): 'student', 'teacher' (often the TA/助教), "
        "'editingteacher' (instructor), 'teachingassistant', 'manager', etc.\n\n"
        "Returns {course_id, role, roles}: `role` is the primary role shortname, "
        "`roles` all of them (a user can hold more than one).\n\n"
        "Credentials come from the MCP settings headers, not from you."
    ),
)
def _get_course_role(ctx: Context, course_id: CourseId) -> dict:
    return run_tool(ctx, lambda m: get_course_role(m, course_id))
