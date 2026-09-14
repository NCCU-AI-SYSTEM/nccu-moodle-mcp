"""
NCCU Moodle MCP server.

Exposes NCCU Moodle (moodle45.nccu.edu.tw) over the Model Context Protocol.
Every tool is multi-tenant and stateless: the caller passes their NCCU portal
credentials, the server performs the full i.nccu.edu.tw SSO handoff for that one
call, uses the resulting session, and discards it when the call returns. No
credentials or session tokens are cached to disk or shared between calls, so
concurrent callers never interfere with one another.
"""
from __future__ import annotations

from typing import Annotated

from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field

from moodle_client import MoodleClient, MoodleAuthError

# Reusable, richly-described parameter types (surface as JSON Schema constraints).
Sem = Annotated[
    str | None,
    Field(description="NCCU term code, e.g. \"1142\". Omit for the latest "
                      "semester; \"all\" for every semester."),
]
CourseId = Annotated[int, Field(description="Moodle course id (from list_courses).")]

# Header names clients configure in their MCP settings (the `headers` block).
USER_HEADER = "X-Moodle-Username"
PASS_HEADER = "X-Moodle-Password"


def _resolve_credentials(ctx: Context) -> tuple[str, str]:
    """Read the caller's credentials from the request headers their MCP client
    was configured with. Credentials are never tool arguments, so the calling
    agent/model never sees or handles the user's password."""
    headers = ctx.headers or {}
    user = headers.get(USER_HEADER) or headers.get(USER_HEADER.lower())
    pw = headers.get(PASS_HEADER) or headers.get(PASS_HEADER.lower())
    if not user or not pw:
        raise ToolError(
            "Missing credentials. Configure them in your MCP client settings "
            f"`headers` block as '{USER_HEADER}' and '{PASS_HEADER}'."
        )
    return user, pw


def _run(ctx: Context, work):
    """Resolve header credentials, log in (stateless), run `work(client)`, and
    turn an auth failure into a clean tool error."""
    user, pw = _resolve_credentials(ctx)
    try:
        with MoodleClient.login(user, pw) as m:
            return work(m)
    except MoodleAuthError as e:
        raise ToolError(f"Moodle login failed: {e}") from e

mcp = MCPServer(
    name="nccu-moodle",
    title="NCCU Moodle",
    description=(
        "Access NCCU Moodle (moodle45.nccu.edu.tw) on behalf of a student. "
        "Each tool logs in through the NCCU single-sign-on portal "
        "(i.nccu.edu.tw) using the credentials passed to it, so every call is "
        "independent and stateless — nothing is stored between calls."
    ),
    instructions=(
        "Tools require the student's NCCU portal account (student ID) and "
        "password, which are the same credentials used at "
        "https://i.nccu.edu.tw. Credentials are used only to establish a login "
        "session for that single call and are never persisted. NOTE: NCCU locks "
        "an account for 15 minutes after 5 failed login attempts, so do not "
        "retry with guessed passwords."
    ),
)


@mcp.tool(
    name="list_courses",
    title="List Moodle courses",
    description=(
        "List the student's enrolled Moodle courses, filtered by semester.\n\n"
        "By default (no `sem`), returns ONLY the latest semester's courses "
        "(the current term). Pass `sem` as an NCCU term code (e.g. \"1142\") to "
        "get that semester; pass \"all\" to return every enrolled course.\n\n"
        "Each course is returned as an object with:\n"
        "  - id       (int)  Moodle course id, usable in other course tools\n"
        "  - name     (str)  full course title\n"
        "  - url      (str)  direct link to the course\n"
        "  - semester (str)  NCCU term code the course belongs to (e.g. \"1151\")\n"
        "  - current  (bool) true if it is in the current (latest) semester\n\n"
        "Authentication is automatic: the user's NCCU credentials come from the "
        "MCP client settings (headers), not from you. Just call the tool; you "
        "never need — or have — the user's password."
    ),
)
def list_courses(ctx: Context, sem: Sem = None) -> dict:
    """
    Args:
        sem: Semester to list. Omit for the latest semester only; a term code
             ("1142") or full label for one semester; "all" for every semester.

    Returns:
        {"count": int, "courses": [ {id, name, url, semester, current}, ... ]}

    Credentials are read from request headers (see the MCP settings `headers`
    block); they are not parameters of this tool.
    """
    courses = _run(ctx, lambda m: m.list_courses(sem=sem))
    return {"count": len(courses), "courses": courses}


@mcp.tool(
    name="list_assignments",
    title="List assignments",
    description=(
        "List assignments (with due dates) for the student's courses.\n\n"
        "Scope, in priority order:\n"
        "  - `course_ids`: if given, list assignments for exactly those Moodle "
        "course ids (from list_courses); `sem` is ignored.\n"
        "  - `sem`: otherwise filter all enrolled courses by NCCU term code. "
        "Default (neither given) = latest semester; \"1142\" = that term; "
        "\"all\" = every course.\n\n"
        "Each assignment: {id, course_id, course, name, due, opens, cutoff, url}. "
        "Times are Taipei time 'YYYY-MM-DD HH:MM'; null means unset. Sorted by "
        "due date.\n\n"
        "Credentials come from the MCP settings headers, not from you."
    ),
)
def list_assignments(
    ctx: Context,
    sem: Sem = None,
    course_ids: Annotated[
        list[int] | None,
        Field(description="Specific Moodle course ids (from list_courses). "
                          "When given, overrides `sem`."),
    ] = None,
) -> dict:
    """List assignments. `course_ids`: specific courses (overrides `sem`).
    `sem`: omit=latest, a term code, or "all"."""
    items = _run(ctx, lambda m: m.list_assignments(sem=sem, course_ids=course_ids))
    return {"count": len(items), "assignments": items}


@mcp.tool(
    name="upcoming_deadlines",
    title="Upcoming deadlines",
    description=(
        "List the student's upcoming action events (assignment due dates, quiz "
        "closings, etc.) across ALL courses within the next `days` (default 14). "
        "This is the best 'what's due soon' overview.\n\n"
        "Each event: {name, course, due, overdue, module, url}. `due` is Taipei "
        "time 'YYYY-MM-DD HH:MM'. Sorted soonest first.\n\n"
        "Credentials come from the MCP settings headers, not from you."
    ),
)
def upcoming_deadlines(
    ctx: Context,
    days: Annotated[int, Field(ge=1, le=365,
        description="How many days ahead to look (1-365).")] = 14,
) -> dict:
    """Upcoming deadlines across all courses within `days` (default 14)."""
    items = _run(ctx, lambda m: m.upcoming_deadlines(days=days))
    return {"count": len(items), "days": days, "events": items}


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
def get_grades(ctx: Context, course_id: CourseId) -> dict:
    """Grade items for one course. `course_id` from list_courses."""
    items = _run(ctx, lambda m: m.get_grades(course_id))
    return {"course_id": course_id, "count": len(items), "grades": items}


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
def get_course_contents(ctx: Context, course_id: CourseId) -> dict:
    """Sections and activities of one course. `course_id` from list_courses."""
    sections = _run(ctx, lambda m: m.get_course_contents(course_id))
    return {"course_id": course_id, "count": len(sections), "sections": sections}


def main() -> None:
    """Console entry point. `nccu-moodle-mcp [http]` or `uv run nccu-moodle-mcp`.

      (no arg)  -> stdio  (for Claude Desktop / Code as a local server)
      http      -> Streamable HTTP on 127.0.0.1:8000/mcp
    Env overrides: MCP_TRANSPORT, MCP_HOST, MCP_PORT, MCP_ALLOWED_HOSTS
    """
    import os
    import sys

    transport = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("MCP_TRANSPORT", "stdio")

    if transport in ("http", "streamable-http"):
        from mcp.server.transport_security import TransportSecuritySettings

        # When the server is reached through a domain / another host, Streamable
        # HTTP's DNS-rebinding protection rejects the request unless the Host is
        # allowed. Configure via MCP_ALLOWED_HOSTS:
        #   unset            -> localhost only (default, safe for local use)
        #   "example.com"    -> allow that host (comma-separate for several)
        #   "*"              -> disable the check (use only behind a trusted proxy)
        allowed = os.environ.get("MCP_ALLOWED_HOSTS", "").strip()
        security = None
        if allowed == "*":
            security = TransportSecuritySettings(enable_dns_rebinding_protection=False)
        elif allowed:
            hosts = [h.strip() for h in allowed.split(",") if h.strip()]
            security = TransportSecuritySettings(
                allowed_hosts=hosts,
                allowed_origins=["*"],
            )

        mcp.run(
            transport="streamable-http",
            host=os.environ.get("MCP_HOST", "127.0.0.1"),  # set 0.0.0.0 to expose
            port=int(os.environ.get("MCP_PORT", "8000")),
            streamable_http_path="/mcp",
            json_response=True,     # plain JSON responses (easy to curl), not SSE
            stateless_http=True,    # each request independent -> no session handshake
            transport_security=security,
        )
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
