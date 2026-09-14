"""get_notifications — the student's notification bell."""

from __future__ import annotations

from typing import Annotated

from mcp.server.mcpserver import Context
from pydantic import Field

from ..app import mcp, run_tool
from ..helpers import fmt_time, strip_html


def get_notifications(client, limit: int = 10) -> list[dict]:
    """Notifications via message_popup_get_popup_notifications. Newest first:
    {subject, message, posted, read, url}."""
    data = client.ws(
        "message_popup_get_popup_notifications", useridto=client.get_userid(), limit=limit, offset=0
    )
    out = []
    for n in data.get("notifications", []):
        out.append(
            {
                "subject": n.get("subject"),
                "message": strip_html(
                    n.get("smallmessage") or n.get("fullmessagehtml") or n.get("fullmessage")
                ),
                "posted": fmt_time(n.get("timecreated")),
                "read": bool(n.get("read")),
                "url": n.get("contexturl"),
            }
        )
    return out


@mcp.tool(
    name="get_notifications",
    title="Get notifications",
    description=(
        "Get the student's Moodle notifications (the notification bell): "
        "assignment due reminders, grading, forum posts, etc.\n\n"
        "Each notification: {subject, message, posted, read, url}, newest first. "
        "`limit` caps the count. The result also reports how many are unread.\n\n"
        "Credentials come from the MCP settings headers, not from you."
    ),
)
def _get_notifications(
    ctx: Context,
    limit: Annotated[int, Field(ge=1, le=50, description="Max notifications to return.")] = 10,
) -> dict:
    items = run_tool(ctx, lambda m: get_notifications(m, limit=limit))
    unread = sum(1 for n in items if not n["read"])
    return {"count": len(items), "unread": unread, "notifications": items}
