"""submit_assignment — save (繳交) an assignment's online-text answer, the way the
Moodle app's "Save changes" does.

This tool deliberately has NO power to finalize a submission: it only ever calls
mod_assign_save_submission, never mod_assign_submit_for_grading. The final
"submit for grading" step is irreversible, so we leave it to the user to do on
Moodle themselves.

- On most NCCU assignments there is no draft stage (submissiondrafts = 0), so a
  save already counts as submitted to the teacher (still editable until the due
  date). Nothing further is needed.
- On courses that DO have a draft stage, saving leaves the answer as a draft. The
  tool detects this (`needs_finalize`) and returns a note + the Moodle link so
  the agent can tell the user to finalize it themselves — because finalizing
  cannot be undone.
"""

from __future__ import annotations

from typing import Annotated

from mcp.server.mcpserver import Context
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field

from ..app import mcp, run_tool
from ..helpers import strip_html

# Human-friendly format name -> Moodle text format code.
_FORMATS = {"html": 1, "plain": 2, "markdown": 4, "moodle": 0}


def _saved_text(status: dict) -> str:
    """Plain-text of the online-text currently stored on the submission."""
    sub = (status.get("lastattempt") or {}).get("submission") or {}
    for p in sub.get("plugins", []) or []:
        if p.get("type") == "onlinetext":
            for ef in p.get("editorfields", []) or []:
                return strip_html(ef.get("text"))
    return ""


def submit_assignment(
    client,
    text: str,
    cmid: int | None = None,
    instance: int | None = None,
    text_format: str = "html",
) -> dict:
    """Save `text` as the online-text answer for an assignment, identified by
    `cmid` (the id in a /mod/assign/view.php?id= link) or `instance` (the
    assignment id from list_assignments).

    Only saves — never submits for grading. Returns {instance, cmid, status,
    needs_finalize, saved_text, warnings, view_url, note}. When `needs_finalize`
    is True the answer is a DRAFT that the user must finalize on Moodle (see
    `note` + `view_url`); when False, saving already counts as submitted."""
    if instance is None:
        if cmid is None:
            raise ToolError("Provide either `cmid` or `instance`.")
        cm = client.ws("core_course_get_course_module", cmid=cmid).get("cm") or {}
        instance = cm.get("instance")
        if instance is None:
            raise ToolError(f"Could not resolve assignment instance from cmid {cmid}.")

    fmt = _FORMATS.get(text_format.lower())
    if fmt is None:
        raise ToolError(f"Unknown text_format {text_format!r}; use one of {list(_FORMATS)}.")

    # Guard: only proceed when the submission can still be edited.
    pre = client.ws("mod_assign_get_submission_status", assignid=instance)
    if (pre.get("lastattempt") or {}) and not (pre.get("lastattempt") or {}).get("canedit", True):
        raise ToolError(
            "This assignment can no longer be edited (the window is closed or it "
            "was already submitted for grading)."
        )

    # Save the online text (the ONLY write this tool performs).
    res = client.ws(
        "mod_assign_save_submission",
        **{
            "assignmentid": instance,
            "plugindata[onlinetext_editor][text]": text,
            "plugindata[onlinetext_editor][format]": fmt,
            "plugindata[onlinetext_editor][itemid]": 0,
        },
    )
    warnings = list(res) if isinstance(res, list) else []
    if warnings:
        raise ToolError(f"Moodle rejected the save: {warnings}")

    # Detect whether a finalize step remains: `cansubmit` is True only on courses
    # with a draft stage where the draft has not been submitted for grading.
    status = client.ws("mod_assign_get_submission_status", assignid=instance)
    last = status.get("lastattempt") or {}
    needs_finalize = bool(last.get("cansubmit"))
    sub = last.get("submission") or {}
    view_url = client.url(f"/mod/assign/view.php?id={cmid}") if cmid else None

    if needs_finalize:
        note = (
            "SAVED AS A DRAFT, NOT submitted for grading. This tool never performs "
            "the irreversible finalize step. Tell the user their answer is saved "
            "but NOT yet submitted; that finalizing cannot be undone; and that they "
            f"must open the Moodle assignment page and click Submit themselves: {view_url}"
        )
    else:
        note = (
            "Saved. This course has no draft stage, so saving already counts as "
            "submitted to the teacher (still editable until the due date). Nothing "
            "further is needed."
        )

    return {
        "instance": instance,
        "cmid": cmid,
        "status": sub.get("status"),
        "needs_finalize": needs_finalize,
        "saved_text": _saved_text(status),
        "warnings": warnings,
        "view_url": view_url,
        "note": note,
    }


@mcp.tool(
    name="submit_assignment",
    title="Submit assignment text (繳交, save only)",
    description=(
        "Submit (繳交) an assignment's online-text answer. Use when the user says "
        "submit / 繳交 / turn in. Identify the assignment by `cmid` (from a "
        "/mod/assign/view.php?id= link or get_course_contents) or `instance` "
        "(from list_assignments); `text` is the answer, `text_format` defaults to "
        "'html'. Confirm the text with the user first, and relay `note` from the "
        "result.\n\n"
        "Credentials come from the MCP settings headers, not from you."
    ),
)
def _submit_assignment(
    ctx: Context,
    text: Annotated[str, Field(description="Answer text to submit (HTML by default).")],
    cmid: Annotated[
        int | None,
        Field(description="Course-module id (the id in a /mod/assign/view.php?id= link)."),
    ] = None,
    instance: Annotated[
        int | None,
        Field(description="Assignment instance id (from list_assignments `id`)."),
    ] = None,
    text_format: Annotated[
        str, Field(description="Text format: 'html' (default), 'plain', 'markdown', 'moodle'.")
    ] = "html",
) -> dict:
    return run_tool(
        ctx,
        lambda m: submit_assignment(
            m, text=text, cmid=cmid, instance=instance, text_format=text_format
        ),
    )
