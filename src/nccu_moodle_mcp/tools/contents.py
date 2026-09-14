"""get_course_contents — sections and activities/resources of a course."""

from __future__ import annotations

from ..helpers import strip_html


def get_course_contents(client, course_id: int) -> list[dict]:
    """Course outline via core_course_get_contents. One dict per section:
    {section, summary, modules:[{name, type, url}]}."""
    data = client.ws("core_course_get_contents", courseid=course_id)
    sections = []
    for s in data:
        modules = [
            {
                "name": mod.get("name"),
                "type": mod.get("modname"),
                "url": mod.get("url"),
            }
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
