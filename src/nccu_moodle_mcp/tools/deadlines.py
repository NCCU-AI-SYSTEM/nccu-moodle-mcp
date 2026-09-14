"""upcoming_deadlines — action events (due dates, quizzes) across all courses."""

from __future__ import annotations

import time

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
