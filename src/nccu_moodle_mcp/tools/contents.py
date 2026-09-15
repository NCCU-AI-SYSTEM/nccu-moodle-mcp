"""get_course_contents — everything the teacher posted in a course, by week/section."""

from __future__ import annotations

from typing import Annotated

from mcp.server.mcpserver import Context
from pydantic import Field

from ..app import CourseId, mcp, run_tool
from ..helpers import strip_html


def get_course_contents(client, course_id: int, include_empty: bool = False) -> list[dict]:
    """The course outline via core_course_get_contents — the teacher's postings
    grouped by section (NCCU names sections by week). One dict per section:
    {section, summary, modules:[{name, type, url}]}, where `type` is the Moodle
    module (assign, resource, url, forum, quiz, page, folder, label, …).

    include_empty: by default, a section is dropped only when it has NO items
    AND NO summary text — so weeks where the teacher wrote only a summary (e.g.
    the week's readings/plan, common at NCCU) are kept. Set True for the full
    week-by-week skeleton including truly empty weeks.
    """
    data = client.ws("core_course_get_contents", courseid=course_id)
    sections = []
    for s in data:
        modules = [
            {
                "id": mod.get("id"),  # course-module id (cmid) — view.php?id=, other tools
                "instance": mod.get("instance"),  # activity instance id (module-specific WS)
                "name": mod.get("name") or strip_html(mod.get("description")),
                "type": mod.get("modname"),
                "url": mod.get("url"),
            }
            for mod in s.get("modules", [])
        ]
        summary = strip_html(s.get("summary"))
        if not modules and not summary and not include_empty:
            continue
        sections.append(
            {
                "section_id": s.get("id"),
                "section": s.get("name"),
                "summary": summary,
                "modules": modules,
            }
        )
    return sections


@mcp.tool(
    name="get_course_contents",
    title="Get course contents",
    description=(
        "Get everything the teacher posted in one course (by Moodle course id, "
        "from list_courses), grouped by section — NCCU names sections by week, so "
        "this is the week-by-week list of materials, links, forums and "
        "assignments.\n\n"
        "The `summary` is the teacher's text for that section/week (readings, "
        "plan, notes) — many NCCU weeks have only a summary and no attached items. "
        "By default a section is shown if it has items OR a summary; only truly "
        "blank sections are dropped. Set `include_empty` true for the full week "
        "skeleton including blank weeks.\n\n"
        "Each section: {section_id, section, summary, modules:[{id, instance, "
        "name, type, url}]}. `type` is the Moodle module (assign, resource, url, "
        "forum, quiz, page, folder, label, …); `id` is the course-module id (cmid) "
        "and `instance` the activity id — use them to open an item with other "
        "tools (e.g. an assign `instance` is the `course_id`-independent assignment "
        "id, a forum `instance` feeds get_announcement's forum).\n\n"
        "Credentials come from the MCP settings headers, not from you."
    ),
)
def _get_course_contents(
    ctx: Context,
    course_id: CourseId,
    include_empty: Annotated[
        bool, Field(description="Include truly blank sections (no items and no summary).")
    ] = False,
) -> dict:
    sections = run_tool(
        ctx, lambda m: get_course_contents(m, course_id, include_empty=include_empty)
    )
    return {"course_id": course_id, "count": len(sections), "sections": sections}
