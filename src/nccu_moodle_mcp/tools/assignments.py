"""list_assignments — assignments with due dates, status, and a date-range filter."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from mcp.server.mcpserver import Context
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field

from ..app import Sem, mcp, run_tool
from ..helpers import TAIPEI, fmt_time, select_by_sem, term_code
from .courses import _enrolled_self_params, _roles_from


def _status_from(data: dict) -> str:
    """Parse a mod_assign_get_submission_status response into one word:
    'graded', 'submitted', or 'not submitted'."""
    last = data.get("lastattempt") or {}
    sub = last.get("submission") or {}
    if last.get("gradingstatus") == "graded":
        return "graded"
    if sub.get("status") == "submitted":
        return "submitted"
    return "not submitted"


def _to_epoch(value: str | None, *, end_of_day: bool = False) -> int | None:
    """Parse an ISO date/datetime (Taipei time if no offset) to a unix timestamp.
    A date-only `due_to` is treated as the end of that day so the bound is
    inclusive."""
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.strip())
    except ValueError as e:
        raise ToolError(f"Invalid date {value!r}; use YYYY-MM-DD or YYYY-MM-DD HH:MM.") from e
    if end_of_day and len(value.strip()) == 10:  # date only
        dt = dt.replace(hour=23, minute=59, second=59)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TAIPEI)
    return int(dt.timestamp())


def _in_window(ts: int, lo: int | None, hi: int | None) -> bool:
    """Is timestamp `ts` inside [lo, hi]? No bounds -> always True (no filter);
    with a bound, a missing timestamp (0) is excluded."""
    if lo is None and hi is None:
        return True
    if not ts:
        return False
    return (lo is None or ts >= lo) and (hi is None or ts <= hi)


def list_assignments(
    client,
    sem: str | None = None,
    course_ids: list[int] | None = None,
    due_from: str | None = None,
    due_to: str | None = None,
    opens_from: str | None = None,
    opens_to: str | None = None,
    include_all_role: bool = False,
) -> list[dict]:
    """Assignments via mod_assign_get_assignments. When `course_ids` is given they
    scope the fetch (and `sem` is ignored); otherwise all enrolled courses are
    fetched and filtered by `sem` (default: latest). Returns {id, course_id,
    course, role, name, due, opens, cutoff, status, url}, sorted by due date
    (`role` is the user's role in that course).

    include_all_role: by default (False) only courses where the user is a
    'student' are kept — your own homework. Set True to include courses where
    you are a teacher/TA/etc.

    due_from / due_to: keep only assignments whose DUE date is within this range.
    opens_from / opens_to: same, but on the OPEN (submissions-from) date.
    All are ISO dates in Taipei time, e.g. "2026-09-08" or "2026-09-08 23:59";
    give any subset. Assignments missing the filtered date are dropped.

    `status` ('graded' / 'submitted' / 'not submitted') is always included — one
    extra request per assignment, so scope the list rather than fetching every
    semester at once.
    """
    if course_ids:
        params = {f"courseids[{i}]": cid for i, cid in enumerate(course_ids)}
        data = client.ws("mod_assign_get_assignments", **params)
    else:
        data = client.ws("mod_assign_get_assignments")  # all enrolled courses

    courses = [
        {
            "id": co.get("id"),
            "name": co.get("fullname") or co.get("shortname") or "",
            "semester": term_code(co.get("shortname") or co.get("fullname")),
            "assignments": co.get("assignments", []),
        }
        for co in data.get("courses", [])
    ]

    due_lo, due_hi = _to_epoch(due_from), _to_epoch(due_to, end_of_day=True)
    open_lo, open_hi = _to_epoch(opens_from), _to_epoch(opens_to, end_of_day=True)

    selected = courses if course_ids else select_by_sem(courses, sem)
    out = []
    for co in selected:
        for a in co["assignments"]:
            due = a.get("duedate") or 0
            opens = a.get("allowsubmissionsfromdate") or 0
            if not _in_window(due, due_lo, due_hi) or not _in_window(opens, open_lo, open_hi):
                continue
            out.append(
                {
                    "id": a.get("id"),
                    "course_id": co["id"],
                    "course": co["name"],
                    "name": a.get("name"),
                    "due": fmt_time(due),
                    "opens": fmt_time(a.get("allowsubmissionsfromdate")),
                    "cutoff": fmt_time(a.get("cutoffdate")),
                    "url": client.url(f"/mod/assign/view.php?id={a.get('cmid')}"),
                }
            )
    out.sort(key=lambda x: x["due"] or "9999")

    # Resolve the user's role per course first (once per distinct course, <=5 in
    # parallel), so we can drop non-student courses before the costlier status
    # calls unless include_all_role is set.
    uid = client.get_userid()
    seen = list(dict.fromkeys(a["course_id"] for a in out))
    role_results = client.ws_parallel(
        "core_enrol_get_enrolled_users",
        [_enrolled_self_params(cid, uid) for cid in seen],
        max_workers=5,
    )
    roles = {}
    for cid, eu in zip(seen, role_results, strict=True):
        got = _roles_from(eu, uid)
        roles[cid] = got[0] if got else None
    for a in out:
        a["role"] = roles.get(a["course_id"])
    if not include_all_role:
        out = [a for a in out if a["role"] == "student"]

    # Submission status needs one call per assignment (Moodle has no student bulk
    # call) — run them concurrently, capped at 5 in flight.
    results = client.ws_parallel(
        "mod_assign_get_submission_status",
        [{"assignid": a["id"]} for a in out],
        max_workers=5,
    )
    for a, data in zip(out, results, strict=True):
        a["status"] = _status_from(data)
    return out


@mcp.tool(
    name="list_assignments",
    title="List assignments",
    description=(
        "List assignments (with due dates and submission status) for the "
        "student's courses.\n\n"
        "Scope, in priority order:\n"
        "  - `course_ids`: if given, list assignments for exactly those Moodle "
        "course ids (from list_courses); `sem` is ignored.\n"
        "  - `sem`: otherwise filter all enrolled courses by NCCU term code. "
        'Default (neither given) = latest semester; "1142" = that term; '
        '"all" = every course.\n\n'
        'Filter by date (ISO dates in Taipei time, e.g. "2026-09-08"): '
        "`due_from`/`due_to` bound the DUE date, `opens_from`/`opens_to` bound the "
        "OPEN (submissions-from) date. Give any subset; compute ranges from today "
        "for 'due this week', 'opened last week', etc. This is the best way to "
        "answer 'what's due/opened in some period', since it also carries "
        "submission status.\n\n"
        "By default only courses where you are a STUDENT are included (your own "
        "homework); set `include_all_role` true to also include courses where you "
        "are a teacher/TA.\n\n"
        "Each assignment: {id, course_id, course, role, name, due, opens, cutoff, "
        "status, url}, where `role` is the user's role in that course "
        "(student/teacher/…) and `status` is 'graded' / 'submitted' / 'not "
        "submitted'. "
        "Times are Taipei time 'YYYY-MM-DD HH:MM'; null means unset. Sorted by "
        "due date.\n\n"
        "Credentials come from the MCP settings headers, not from you."
    ),
)
def _list_assignments(
    ctx: Context,
    sem: Sem = None,
    course_ids: Annotated[
        list[int] | None,
        Field(
            description="Specific Moodle course ids (from list_courses). "
            "When given, overrides `sem`."
        ),
    ] = None,
    due_from: Annotated[
        str | None,
        Field(description="Only assignments due on/after this ISO date (Taipei tz)."),
    ] = None,
    due_to: Annotated[
        str | None,
        Field(description="Only assignments due on/before this ISO date (Taipei tz)."),
    ] = None,
    opens_from: Annotated[
        str | None,
        Field(description="Only assignments opening on/after this ISO date (Taipei tz)."),
    ] = None,
    opens_to: Annotated[
        str | None,
        Field(description="Only assignments opening on/before this ISO date (Taipei tz)."),
    ] = None,
    include_all_role: Annotated[
        bool,
        Field(
            description="Include courses where you are not a student (teacher/TA). "
            "Default false = only your student courses."
        ),
    ] = False,
) -> dict:
    items = run_tool(
        ctx,
        lambda m: list_assignments(
            m,
            sem=sem,
            course_ids=course_ids,
            due_from=due_from,
            due_to=due_to,
            opens_from=opens_from,
            opens_to=opens_to,
            include_all_role=include_all_role,
        ),
    )
    return {"count": len(items), "assignments": items}
