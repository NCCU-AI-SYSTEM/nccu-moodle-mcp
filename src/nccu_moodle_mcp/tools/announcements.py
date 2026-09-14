"""Announcements — list tiles (list_announcements) then read a thread
(get_announcement), mirroring browsing the forum then opening a post."""

from __future__ import annotations

from typing import Annotated

from mcp.server.mcpserver import Context
from pydantic import Field

from ..app import mcp, run_tool
from ..helpers import fmt_time, strip_html
from .courses import list_courses


def _author_name(author) -> str:
    """Discussion-post author is an object ({fullname:...}); tiles give a string."""
    if isinstance(author, dict):
        author = author.get("fullname")
    return (author or "").strip()


def list_announcements(
    client, course_id: int | None = None, limit: int = 10, offset: int = 0
) -> list[dict]:
    """Announcement TILES (no body) from the "Announcements" (news) forum, via
    mod_forum_get_forums_by_courses + mod_forum_get_forum_discussions.

    course_id: one course; omitted -> aggregate across the latest semester.
    limit/offset: paginate the newest-first tiles.
    Each tile: {discussion_id, course_id, course, subject, author, posted,
    replies, pinned, url}.
    """
    if course_id:
        course_ids, names = [course_id], {}
    else:
        courses = list_courses(client)  # latest semester
        course_ids = [c["id"] for c in courses]
        names = {c["id"]: c["name"] for c in courses}
    if not course_ids:
        return []

    params = {f"courseids[{i}]": cid for i, cid in enumerate(course_ids)}
    forums = client.ws("mod_forum_get_forums_by_courses", **params)

    tiles = []
    for fo in forums:
        if fo.get("type") != "news":  # the Announcements forum
            continue
        cid = fo.get("course")
        disc = client.ws("mod_forum_get_forum_discussions", forumid=fo["id"])
        for d in disc.get("discussions", []):
            tiles.append(
                {
                    "discussion_id": d.get("discussion"),
                    "course_id": cid,
                    "course": names.get(cid, ""),
                    "subject": d.get("subject") or d.get("name"),
                    "author": _author_name(d.get("userfullname")),
                    "posted": fmt_time(d.get("created")),
                    "replies": d.get("numreplies"),
                    "pinned": bool(d.get("pinned")),
                    "url": client.url(f"/mod/forum/discuss.php?d={d.get('discussion')}"),
                }
            )
    tiles.sort(key=lambda t: t["posted"] or "", reverse=True)
    return tiles[offset : offset + limit]


def get_announcement(client, discussion_id: int, limit: int = 20, offset: int = 0) -> dict:
    """Open one announcement: its thread of posts (original + replies), via
    mod_forum_get_discussion_posts. Oldest-first, paginated with limit/offset.
    Returns {discussion_id, total, posts:[{post_id, parent_id, subject, author,
    posted, message}]}.
    """
    data = client.ws("mod_forum_get_discussion_posts", discussionid=discussion_id)
    posts = data.get("posts", [])
    posts.sort(key=lambda p: p.get("timecreated") or 0)  # thread order
    out = []
    for p in posts[offset : offset + limit]:
        out.append(
            {
                "post_id": p.get("id"),
                "parent_id": p.get("parentid"),
                "subject": p.get("subject"),
                "author": _author_name(p.get("author")),
                "posted": fmt_time(p.get("timecreated")),
                "message": strip_html(p.get("message")),
            }
        )
    return {"discussion_id": discussion_id, "total": len(posts), "posts": out}


@mcp.tool(
    name="list_announcements",
    title="List announcements",
    description=(
        "List announcement TILES (headers only, no message body) from a course's "
        '"Announcements" forum — like scanning the forum page. To read one, take '
        "its `discussion_id` and call get_announcement.\n\n"
        "If `course_id` is given, lists that course's announcements; otherwise "
        "aggregates across the current (latest) semester's courses. `limit`/"
        "`offset` paginate the newest-first list.\n\n"
        "Each tile: {discussion_id, course_id, course, subject, author, posted, "
        "replies, pinned, url}. `posted` is Taipei time 'YYYY-MM-DD HH:MM'.\n\n"
        "Credentials come from the MCP settings headers, not from you."
    ),
)
def _list_announcements(
    ctx: Context,
    course_id: Annotated[
        int | None,
        Field(
            description="Moodle course id (from list_courses). Omit to cover all "
            "current-semester courses."
        ),
    ] = None,
    limit: Annotated[int, Field(ge=1, le=50, description="Max tiles to return.")] = 10,
    offset: Annotated[int, Field(ge=0, description="Skip this many (for paging).")] = 0,
) -> dict:
    items = run_tool(
        ctx, lambda m: list_announcements(m, course_id=course_id, limit=limit, offset=offset)
    )
    return {"count": len(items), "offset": offset, "announcements": items}


@mcp.tool(
    name="get_announcement",
    title="Read an announcement",
    description=(
        "Open ONE announcement and read its thread — the original post plus any "
        "replies — given a `discussion_id` from list_announcements.\n\n"
        "Posts are oldest-first; `limit`/`offset` paginate long threads.\n\n"
        "Returns {discussion_id, total, posts:[{post_id, parent_id, subject, "
        "author, posted, message}]}. `posted` is Taipei time 'YYYY-MM-DD HH:MM'.\n\n"
        "Credentials come from the MCP settings headers, not from you."
    ),
)
def _get_announcement(
    ctx: Context,
    discussion_id: Annotated[int, Field(description="Discussion id from list_announcements.")],
    limit: Annotated[int, Field(ge=1, le=100, description="Max posts to return.")] = 20,
    offset: Annotated[int, Field(ge=0, description="Skip this many posts (for paging).")] = 0,
) -> dict:
    return run_tool(ctx, lambda m: get_announcement(m, discussion_id, limit=limit, offset=offset))
