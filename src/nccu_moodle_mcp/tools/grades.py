"""get_grades — the student's own grade items for one course."""

from __future__ import annotations

from mcp.server.mcpserver import Context

from ..app import CourseId, mcp, run_tool
from ..helpers import strip_html


def get_grades(client, course_id: int) -> list[dict]:
    """Grade items via gradereport_user_get_grade_items. Returns {item, grade,
    percentage, range, feedback, type}. A '-' grade means not yet graded."""
    data = client.ws(
        "gradereport_user_get_grade_items", courseid=course_id, userid=client.get_userid()
    )
    usergrades = data.get("usergrades", [])
    if not usergrades:
        return []
    out = []
    for it in usergrades[0].get("gradeitems", []):
        name = it.get("itemname")
        if not name and it.get("itemtype") == "course":
            name = "Course total"
        out.append(
            {
                "item": name or it.get("itemtype"),
                "grade": it.get("gradeformatted"),
                "percentage": it.get("percentageformatted"),
                "range": it.get("rangeformatted"),
                "feedback": strip_html(it.get("feedback")),
                "type": it.get("itemtype"),
            }
        )
    return out


@mcp.tool(
    name="get_grades",
    title="Get course grades",
    description=(
        "Get the student's own grade items for one course (by Moodle course id, "
        "from list_courses).\n\n"
        "Each item: {item, grade, percentage, range, feedback, type}. A '-' grade "
        "means not yet graded.\n\n"
        "Credentials come from the MCP settings headers, not from you."
    ),
)
def _get_grades(ctx: Context, course_id: CourseId) -> dict:
    items = run_tool(ctx, lambda m: get_grades(m, course_id))
    return {"course_id": course_id, "count": len(items), "grades": items}
