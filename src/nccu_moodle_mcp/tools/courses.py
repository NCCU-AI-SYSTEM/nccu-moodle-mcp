"""list_courses — the student's enrolled courses, filtered by semester."""

from __future__ import annotations

from ..helpers import select_by_sem, term_code


def list_courses(client, sem: str | None = None) -> list[dict]:
    """Enrolled courses via core_enrol_get_users_courses, semester derived from
    the leading term code in each course's shortname (e.g. "1151_..." -> "1151").

    sem: None/'latest' -> latest term only; a term code -> that term; 'all' -> every course.
    Returns {id, name, url, semester, current}, newest term first.
    """
    raw = client.ws("core_enrol_get_users_courses", userid=client.get_userid())
    if not isinstance(raw, list):
        return []

    courses = [
        {
            "id": c.get("id"),
            "name": c.get("fullname") or c.get("shortname") or "",
            "url": client.url(f"/course/view.php?id={c.get('id')}"),
            "semester": term_code(c.get("shortname") or c.get("fullname")),
        }
        for c in raw
    ]

    terms = [c["semester"] for c in courses if c["semester"]]
    latest = max(terms) if terms else ""
    for c in courses:
        c["current"] = c["semester"] == latest

    courses = select_by_sem(courses, sem)
    courses.sort(key=lambda c: c["semester"], reverse=True)
    return courses
