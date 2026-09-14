"""get_course_contents — sections and activities/resources of a course."""

from __future__ import annotations

from mcp.server.mcpserver import Context

from ..app import CourseId, mcp, run_tool
from ..helpers import strip_html


def get_course_contents(client, course_id: int) -> list[dict]:
    """Course outline via core_course_get_contents. One dict per section:
    {section, summary, modules:[{name, type, url}]}."""
    data = client.ws("core_course_get_contents", courseid=course_id)
    sections = []
    for s in data:
        modules = [
            {"name": mod.get("name"), "type": mod.get("modname"), "url": mod.get("url")}
            for mod in s.get("modules", [])
        ]
        sections.append(
            {
                "section": s.get("name"),
                "summary": strip_html(s.get("summary")),
                "modules": modules,
            }
        )
    return sections


@mcp.tool(
    name="get_course_contents",
    title="Get course contents",
    description=(
        "Get the sections and activities/resources of one course (by Moodle "
        "course id, from list_courses) — the course outline.\n\n"
        "Each section: {section, summary, modules:[{name, type, url}]}, where "
        "`type` is the Moodle module (assign, resource, url, forum, quiz, page, "
        "folder, label, …).\n\n"
        "Credentials come from the MCP settings headers, not from you."
    ),
)
def _get_course_contents(ctx: Context, course_id: CourseId) -> dict:
    sections = run_tool(ctx, lambda m: get_course_contents(m, course_id))
    return {"course_id": course_id, "count": len(sections), "sections": sections}
