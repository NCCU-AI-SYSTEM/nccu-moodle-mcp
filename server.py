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

from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from moodle_client import MoodleClient, MoodleAuthError

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
        "List the student's Moodle courses shown on the Moodle home page, "
        "grouped by semester.\n\n"
        "By default (no `sem`), returns ONLY the latest semester's courses — "
        "the first/top block on the page, i.e. the current term. Pass `sem` to "
        "select a specific semester by its term code (e.g. \"1142\") or by its "
        "full label (e.g. \"1142-2026 Spring Semester\"); pass \"all\" to return "
        "courses from every semester.\n\n"
        "Each course is returned as an object with:\n"
        "  - id       (int)  Moodle course id, usable in other course tools\n"
        "  - name     (str)  full course title\n"
        "  - url      (str)  direct link to the course\n"
        "  - semester (str)  the semester label the course belongs to\n"
        "  - current  (bool) true if it is in the current (latest) semester\n\n"
        "Authentication is automatic: the user's NCCU credentials come from the "
        "MCP client settings (headers), not from you. Just call the tool; you "
        "never need — or have — the user's password."
    ),
)
def list_courses(ctx: Context, sem: str | None = None) -> dict:
    """
    Args:
        sem: Semester to list. Omit for the latest semester only; a term code
             ("1142") or full label for one semester; "all" for every semester.

    Returns:
        {"count": int, "courses": [ {id, name, url, semester, current}, ... ]}

    Credentials are read from request headers (see the MCP settings `headers`
    block); they are not parameters of this tool.
    """
    user, pw = _resolve_credentials(ctx)
    try:
        with MoodleClient.login(user, pw) as m:
            courses = m.list_courses(sem=sem)
            return {"count": len(courses), "courses": courses}
    except MoodleAuthError as e:
        # Anticipated failure: return is_error with a readable message for the
        # model, rather than a generic "unexpected tool error" crash.
        raise ToolError(f"Moodle login failed: {e}") from e


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
