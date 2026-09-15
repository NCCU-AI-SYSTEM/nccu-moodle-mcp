"""upcoming_deadlines — action events (due dates, quizzes) across courses."""

from __future__ import annotations

import time
from typing import Annotated

from mcp.server.mcpserver import Context
from pydantic import Field

from ..app import mcp, run_tool
from ..helpers import fmt_time
from .courses import _enrolled_self_params, _roles_from


def upcoming_deadlines(client, days: int = 14, include_all_role: bool = False) -> list[dict]:
    """Upcoming action events within the next `days`, via
    core_calendar_get_action_events_by_timesort. Returns {name, course_id, course,
    role, due, overdue, module, url}, soonest first.

    include_all_role: by default (False) only events from courses where the user
    is a 'student' are kept (site/personal events with no real course are always
    kept). Set True to include courses where you are a teacher/TA.
    """
    now = int(time.time())
    data = client.ws(
        "core_calendar_get_action_events_by_timesort",
        timesortfrom=now,
        timesortto=now + days * 86400,
        limitnum=50,
    )
    events = []
    for e in data.get("events", []):
        co = e.get("course") or {}
        events.append(
            {
                "name": e.get("name"),
                "course_id": co.get("id"),
                "course": co.get("fullname", ""),
                "due": fmt_time(e.get("timesort")),
                "overdue": bool(e.get("overdue")),
                "module": e.get("modulename"),
                "url": e.get("url") or e.get("viewurl"),
            }
        )

    # Resolve the user's role per real course (id > 1; 0/1 = site/personal), <=5
    # in parallel, and attach it. Then optionally keep only student courses.
    uid = client.get_userid()
    seen = list(dict.fromkeys(ev["course_id"] for ev in events if (ev["course_id"] or 0) > 1))
    role_map = {}
    if seen:
        results = client.ws_parallel(
            "core_enrol_get_enrolled_users",
            [_enrolled_self_params(cid, uid) for cid in seen],
            max_workers=5,
        )
        for cid, eu in zip(seen, results, strict=True):
            got = _roles_from(eu, uid)
            role_map[cid] = got[0] if got else None
    for ev in events:
        ev["role"] = role_map.get(ev["course_id"])
    if not include_all_role:
        events = [ev for ev in events if (ev["course_id"] or 0) <= 1 or ev["role"] == "student"]
    return events


@mcp.tool(
    name="upcoming_deadlines",
    title="Upcoming deadlines",
    description=(
        "List the student's upcoming action events (assignment due dates, quiz "
        "closings, etc.) across courses within the next `days` (default 14). "
        "This is the best 'what's due soon' overview.\n\n"
        "By default only events from courses where you are a STUDENT are included; "
        "set `include_all_role` true to also include courses where you are a "
        "teacher/TA. (Personal/site events are always kept.)\n\n"
        "Each event: {name, course_id, course, role, due, overdue, module, url}. "
        "`due` is Taipei time 'YYYY-MM-DD HH:MM'. Sorted soonest first.\n\n"
        "Credentials come from the MCP settings headers, not from you."
    ),
)
def _upcoming_deadlines(
    ctx: Context,
    days: Annotated[
        int, Field(ge=1, le=365, description="How many days ahead to look (1-365).")
    ] = 14,
    include_all_role: Annotated[
        bool,
        Field(
            description="Include courses where you are not a student (teacher/TA). "
            "Default false = only your student courses."
        ),
    ] = False,
) -> dict:
    items = run_tool(
        ctx, lambda m: upcoming_deadlines(m, days=days, include_all_role=include_all_role)
    )
    return {"count": len(items), "days": days, "events": items}
