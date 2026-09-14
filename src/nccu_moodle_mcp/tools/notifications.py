"""get_notifications — the student's notification bell."""

from __future__ import annotations

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
