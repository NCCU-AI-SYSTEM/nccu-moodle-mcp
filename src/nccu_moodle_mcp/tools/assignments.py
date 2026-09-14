"""list_assignments — assignments with due dates, by semester or explicit courses."""

from __future__ import annotations

import time
from typing import Annotated

from mcp.server.mcpserver import Context
from pydantic import Field

from ..app import Sem, mcp, run_tool
from ..helpers import fmt_time, select_by_sem, term_code


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


def list_assignments(
    client,
    sem: str | None = None,
    course_ids: list[int] | None = None,
    due_within_days: int | None = None,
) -> list[dict]:
    """Assignments via mod_assign_get_assignments. When `course_ids` is given they
    scope the fetch (and `sem` is ignored); otherwise all enrolled courses are
    fetched and filtered by `sem` (default: latest). Returns {id, course_id,
    course, name, due, opens, cutoff, status, url}, sorted by due date.

    due_within_days: if set, keep only assignments whose due date falls between
    now and now + that many days (e.g. 7 for "due this week"); assignments with
    no due date are dropped.

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

    now = int(time.time())
    window_end = now + due_within_days * 86400 if due_within_days is not None else None

    selected = courses if course_ids else select_by_sem(courses, sem)
    out = []
    for co in selected:
        for a in co["assignments"]:
            due = a.get("duedate") or 0
            if window_end is not None and not (now <= due <= window_end):
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
        "List assignments (with due dates) for the student's courses.\n\n"
        "Scope, in priority order:\n"
        "  - `course_ids`: if given, list assignments for exactly those Moodle "
        "course ids (from list_courses); `sem` is ignored.\n"
        "  - `sem`: otherwise filter all enrolled courses by NCCU term code. "
        'Default (neither given) = latest semester; "1142" = that term; '
        '"all" = every course.\n\n'
        "Set `due_within_days` to only return assignments due within that many "
        "days from now (e.g. 7 for 'due this week') — the best way to answer "
        "'what's due soon', since it also carries submission status.\n\n"
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
    due_within_days: Annotated[
        int | None,
        Field(ge=1, le=365, description="Only assignments due within this many days from now."),
    ] = None,
) -> dict:
    items = run_tool(
        ctx,
        lambda m: list_assignments(
            m, sem=sem, course_ids=course_ids, due_within_days=due_within_days
        ),
    )
    return {"count": len(items), "assignments": items}
