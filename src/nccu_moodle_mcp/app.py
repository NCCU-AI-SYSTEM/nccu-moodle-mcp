"""Shared MCP application objects.

Holds the single MCPServer instance, credential resolution, the tool runner, and
the reusable parameter types. Each tool module imports from here to register its
own `@mcp.tool`; `server.py` imports the tools (to trigger registration) and runs
the server. Kept separate from both to avoid an import cycle.
"""

from __future__ import annotations

from typing import Annotated

from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field

from nccu_moodle_mcp.moodle_client import MoodleAuthError, MoodleClient

# Reusable, richly-described parameter types (surface as JSON Schema constraints).
Sem = Annotated[
    str | None,
    Field(
        description='NCCU term code, e.g. "1142". Omit for the latest '
        'semester; "all" for every semester.'
    ),
]
CourseId = Annotated[int, Field(description="Moodle course id (from list_courses).")]

# Header names clients configure in their MCP settings (the `headers` block).
USER_HEADER = "X-Moodle-Username"
PASS_HEADER = "X-Moodle-Password"

mcp = MCPServer(
    name="nccu-moodle",
    title="NCCU Moodle",
    description=(
        "Access NCCU Moodle (moodle.nccu.edu.tw) on behalf of a student. "
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


def run_tool(ctx: Context, work):
    """Resolve header credentials, log in (stateless), run `work(client)`, and
    turn an auth failure into a clean tool error."""
    user, pw = _resolve_credentials(ctx)
    try:
        with MoodleClient.login(user, pw) as m:
            return work(m)
    except MoodleAuthError as e:
        raise ToolError(f"Moodle login failed: {e}") from e
