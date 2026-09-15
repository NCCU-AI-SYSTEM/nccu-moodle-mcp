"""get_module — open a single course item (a teacher's posting) by course-module
id, dispatching by module type to return its content or the right follow-up."""

from __future__ import annotations

from typing import Annotated

from mcp.server.mcpserver import Context
from pydantic import Field

from ..app import mcp, run_tool
from ..helpers import strip_html
from .announcements import forum_discussions
from .assignments import assignment_detail


def _find_module(contents: list, cmid: int) -> dict | None:
    for section in contents:
        for mod in section.get("modules", []):
            if mod.get("id") == cmid:
                return mod
    return None


def _files(mod: dict) -> list[dict]:
    """Plain file links from a resource/folder module's `contents` (no token —
    the user opens them in their authenticated browser)."""
    return [
        {
            "filename": c.get("filename"),
            "mimetype": c.get("mimetype"),
            "size": c.get("filesize"),
            "url": c.get("fileurl"),
        }
        for c in mod.get("contents", [])
        if c.get("type") == "file"
    ]


def get_module(client, cmid: int, course_id: int | None = None) -> dict:
    """Open one course item by its course-module id (cmid) — the `id` in a
    `/mod/<type>/view.php?id=<cmid>` link — and return its content by type:

      resource/folder -> {files:[{filename, mimetype, size, url}]}  (browser links)
      url             -> {external_url}
      page            -> {html}
      label           -> {text}
      forum           -> {forum_id, intro, discussions:[tiles]}  (read one via get_announcement)
      assign          -> {description, attachments, due/opens/cutoff, grade_max,
                          status, submission{...}, feedback{...}}
      quiz            -> {metadata, attempts}
      other           -> {description}

    `course_id` is optional: if omitted it's resolved from the cmid via
    core_course_get_course_module, so a bare cmid (e.g. from a view.php link) is
    enough. Every result also carries {course_id, cmid, instance, type, name, view_url}.
    """
    if course_id is None:
        cm = client.ws("core_course_get_course_module", cmid=cmid).get("cm") or {}
        course_id = cm.get("course")
        if course_id is None:
            return {"cmid": cmid, "error": "could not resolve course from cmid"}

    mod = _find_module(client.ws("core_course_get_contents", courseid=course_id), cmid)
    if mod is None:
        return {"course_id": course_id, "cmid": cmid, "error": "module not found in course"}

    mtype = mod.get("modname")
    instance = mod.get("instance")
    out = {
        "course_id": course_id,
        "cmid": cmid,
        "instance": instance,
        "type": mtype,
        "name": mod.get("name") or strip_html(mod.get("description")),
        "view_url": mod.get("url") or client.url(f"/mod/{mtype}/view.php?id={cmid}"),
    }

    if mtype in ("resource", "folder"):
        out["files"] = _files(mod)
    elif mtype == "url":
        contents = mod.get("contents") or []
        out["external_url"] = contents[0].get("fileurl") if contents else mod.get("url")
    elif mtype == "page":
        pages = client.ws("mod_page_get_pages_by_courses", **{"courseids[0]": course_id})
        page = next((p for p in pages.get("pages", []) if p.get("coursemodule") == cmid), None)
        out["html"] = (
            strip_html(page.get("content")) if page else strip_html(mod.get("description"))
        )
    elif mtype == "label":
        out["text"] = strip_html(mod.get("description"))
    elif mtype == "forum":
        out["forum_id"] = instance
        # A teacher often posts the content in the forum's intro (esp. forums with
        # no discussion threads). That intro is the module `description` that
        # core_course_get_contents already returned — no extra request needed.
        out["intro"] = strip_html(mod.get("description"))
        out["discussions"] = forum_discussions(client, instance, course_id)
    elif mtype == "assign":
        out.update(assignment_detail(client, course_id, cmid, instance))
    elif mtype == "quiz":
        quizzes = client.ws("mod_quiz_get_quizzes_by_courses", **{"courseids[0]": course_id})
        out["metadata"] = next(
            (q for q in quizzes.get("quizzes", []) if q.get("coursemodule") == cmid), None
        )
        attempts = client.ws("mod_quiz_get_user_attempts", quizid=instance, status="all")
        out["attempts"] = attempts.get("attempts", [])
    else:
        out["description"] = strip_html(mod.get("description"))
    return out


@mcp.tool(
    name="get_module",
    title="Open a course item",
    description=(
        "Open ONE item a teacher posted and return its content, given its `cmid` "
        "(course-module id — the `id` in a /mod/<type>/view.php?id=<cmid> link, "
        "or from get_course_contents). `course_id` is OPTIONAL — omit it and it's "
        "resolved from the cmid, so a bare cmid/link is enough. It detects the "
        "item type and returns:\n"
        "  - resource/folder -> files:[{filename, mimetype, size, url}] (open the "
        "url/view_url in a browser to download; no direct download here yet)\n"
        "  - url   -> external_url\n"
        "  - page  -> html (plain text)\n"
        "  - label -> text\n"
        "  - forum -> forum_id + intro + discussions[] (read one with get_announcement)\n"
        "  - assign -> description (instructions), attachments, due/opens/cutoff, "
        "grade_max, status, submission{submitted_at,files,text}, "
        "feedback{grade,grade_display,graded_at,comment,files}\n"
        "  - quiz -> metadata + attempts  ·  otherwise -> description\n\n"
        "Always includes {course_id, cmid, instance, type, name, view_url}.\n\n"
        "Credentials come from the MCP settings headers, not from you."
    ),
)
def _get_module(
    ctx: Context,
    cmid: Annotated[int, Field(description="Course-module id (the id in a view.php?id= link).")],
    course_id: Annotated[
        int | None,
        Field(description="Moodle course id. Optional — resolved from cmid if omitted."),
    ] = None,
) -> dict:
    return run_tool(ctx, lambda m: get_module(m, cmid, course_id))
