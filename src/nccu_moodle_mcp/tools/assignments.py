"""list_assignments — assignments with due dates, by semester or explicit courses."""

from __future__ import annotations

from ..helpers import fmt_time, select_by_sem, term_code


def list_assignments(
    client, sem: str | None = None, course_ids: list[int] | None = None
) -> list[dict]:
    """Assignments via mod_assign_get_assignments. When `course_ids` is given they
    scope the fetch (and `sem` is ignored); otherwise all enrolled courses are
    fetched and filtered by `sem` (default: latest). Returns {id, course_id,
    course, name, due, opens, cutoff, url}, sorted by due date.
    """
    if course_ids:
        params = {f"courseids[{i}]": cid for i, cid in enumerate(course_ids)}
        data = client.ws("mod_assign_get_assignments", **params)
    else:
        data = client.ws("mod_assign_get_assignments")  # all enrolled courses

    courses = [
        {
            "id": co.get("id"),
            "name": co.get("fullname") or co.get("shortname") or "",
            "semester": term_code(co.get("shortname") or co.get("fullname")),
            "assignments": co.get("assignments", []),
        }
        for co in data.get("courses", [])
    ]

    selected = courses if course_ids else select_by_sem(courses, sem)
    out = []
    for co in selected:
        for a in co["assignments"]:
            out.append(
                {
                    "id": a.get("id"),
                    "course_id": co["id"],
                    "course": co["name"],
                    "name": a.get("name"),
                    "due": fmt_time(a.get("duedate")),
                    "opens": fmt_time(a.get("allowsubmissionsfromdate")),
                    "cutoff": fmt_time(a.get("cutoffdate")),
                    "url": client.url(f"/mod/assign/view.php?id={a.get('cmid')}"),
                }
            )
    out.sort(key=lambda x: x["due"] or "9999")
    return out
