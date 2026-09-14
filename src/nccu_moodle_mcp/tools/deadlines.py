"""upcoming_deadlines — action events (due dates, quizzes) across all courses."""

from __future__ import annotations

import time
from typing import Annotated

from mcp.server.mcpserver import Context
from pydantic import Field

from ..app import mcp, run_tool
from ..helpers import fmt_time


def upcoming_deadlines(client, days: int = 14) -> list[dict]:
    """Upcoming action events within the next `days`, via
    core_calendar_get_action_events_by_timesort. Returns {name, course, due,
    overdue, module, url}."""
    now = int(time.time())
    data = client.ws(
        "core_calendar_get_action_events_by_timesort",
        timesortfrom=now,
        timesortto=now + days * 86400,
        limitnum=50,
    )
    out = []
    for e in data.get("events", []):
        out.append(
            {
                "name": e.get("name"),
                "course": (e.get("course") or {}).get("fullname", ""),
                "due": fmt_time(e.get("timesort")),
                "overdue": bool(e.get("overdue")),
                "module": e.get("modulename"),
                "url": e.get("url") or e.get("viewurl"),
            }
        )
    return out


@mcp.tool(
    name="upcoming_deadlines",
    title="Upcoming deadlines",
    description=(
        "List the student's upcoming action events (assignment due dates, quiz "
        "closings, etc.) across ALL courses within the next `days` (default 14). "
        "This is the best 'what's due soon' overview.\n\n"
        "Each event: {name, course, due, overdue, module, url}. `due` is Taipei "
        "time 'YYYY-MM-DD HH:MM'. Sorted soonest first.\n\n"
        "Credentials come from the MCP settings headers, not from you."
    ),
)
def _upcoming_deadlines(
    ctx: Context,
    days: Annotated[
        int, Field(ge=1, le=365, description="How many days ahead to look (1-365).")
    ] = 14,
) -> dict:
    items = run_tool(ctx, lambda m: upcoming_deadlines(m, days=days))
    return {"count": len(items), "days": days, "events": items}
