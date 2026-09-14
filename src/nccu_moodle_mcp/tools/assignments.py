"""list_assignments — assignments with due dates, status, and a date-range filter."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from mcp.server.mcpserver import Context
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field

from ..app import Sem, mcp, run_tool
from ..helpers import TAIPEI, fmt_time, select_by_sem, term_code


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


def list_assignments(
    client,
    sem: str | None = None,
    course_ids: list[int] | None = None,
    due_from: str | None = None,
    due_to: str | None = None,
) -> list[dict]:
    """Assignments via mod_assign_get_assignments. When `course_ids` is given they
    scope the fetch (and `sem` is ignored); otherwise all enrolled courses are
    fetched and filtered by `sem` (default: latest). Returns {id, course_id,
    course, name, due, opens, cutoff, status, url}, sorted by due date.

    due_from / due_to: keep only assignments whose due date is within this range.
    ISO dates in Taipei time, e.g. "2026-09-08" or "2026-09-08 23:59"; either or
    both may be given. Assignments with no due date are dropped when filtering.

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

    lo = _to_epoch(due_from)
    hi = _to_epoch(due_to, end_of_day=True)
    windowed = lo is not None or hi is not None

    selected = courses if course_ids else select_by_sem(courses, sem)
    out = []
    for co in selected:
        for a in co["assignments"]:
            due = a.get("duedate") or 0
            if windowed and (
                not due or (lo is not None and due < lo) or (hi is not None and due > hi)
            ):
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
        "Filter by due date with `due_from` / `due_to` (ISO dates in Taipei time, "
        'e.g. "2026-09-08"). Compute the range from today for questions like '
        "'due this week' or 'due last week'. This is the best way to answer "
        "'what's due (in some period)', since it also carries submission status.\n\n"
        "Each assignment: {id, course_id, course, name, due, opens, cutoff, "
        "status, url}, where `status` is 'graded' / 'submitted' / 'not submitted'. "
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
) -> dict:
    items = run_tool(
        ctx,
        lambda m: list_assignments(
            m, sem=sem, course_ids=course_ids, due_from=due_from, due_to=due_to
        ),
    )
    return {"count": len(items), "assignments": items}
