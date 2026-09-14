"""list_assignments — assignments with due dates, by semester or explicit courses."""

from __future__ import annotations

from typing import Annotated

from mcp.server.mcpserver import Context
from pydantic import Field

from ..app import Sem, mcp, run_tool
from ..helpers import fmt_time, select_by_sem, term_code


def list_assignments(
    client, sem: str | None = None, course_ids: list[int] | None = None
) -> list[dict]:
    """Assignments via mod_assign_get_assignments. When `course_ids` is given they
    scope the fetch (and `sem` is ignored); otherwise all enrolled courses are
    fetched and filtered by `sem` (default: latest). Returns {id, course_id,
    course, name, due, opens, cutoff, url}, sorted by due date.
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

    selected = courses if course_ids else select_by_sem(courses, sem)
    out = []
    for co in selected:
        for a in co["assignments"]:
            out.append(
                {
                    "id": a.get("id"),
                    "course_id": co["id"],
                    "course": co["name"],
                    "name": a.get("name"),
                    "due": fmt_time(a.get("duedate")),
                    "opens": fmt_time(a.get("allowsubmissionsfromdate")),
                    "cutoff": fmt_time(a.get("cutoffdate")),
                    "url": client.url(f"/mod/assign/view.php?id={a.get('cmid')}"),
                }
            )
    out.sort(key=lambda x: x["due"] or "9999")
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
        "Each assignment: {id, course_id, course, name, due, opens, cutoff, url}. "
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
) -> dict:
    items = run_tool(ctx, lambda m: list_assignments(m, sem=sem, course_ids=course_ids))
    return {"count": len(items), "assignments": items}
