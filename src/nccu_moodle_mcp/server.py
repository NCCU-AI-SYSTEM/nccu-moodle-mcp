"""NCCU Moodle MCP server — entry point.

The MCPServer instance and shared tool infrastructure live in `app.py`; each tool
is defined in `tools/*.py` and self-registers on import. This module wires those
together and runs the chosen transport.

Every tool is multi-tenant and stateless: the caller passes their NCCU portal
credentials (via request headers), the server performs the full i.nccu.edu.tw SSO
handoff for that one call, uses the resulting session, and discards it. No
credentials or session tokens are cached to disk or shared between calls.
"""

from __future__ import annotations

from nccu_moodle_mcp import tools  # noqa: F401 -- import registers every @mcp.tool
from nccu_moodle_mcp.app import mcp
from nccu_moodle_mcp.moodle_client import prewarm


def main() -> None:
    """Console entry point. `nccu-moodle-mcp [http]` or `python -m nccu_moodle_mcp`.

      (no arg)  -> stdio  (for Claude Desktop / Code as a local server)
      http      -> Streamable HTTP on 127.0.0.1:3033/mcp
    Env overrides: MCP_TRANSPORT, MCP_HOST, MCP_PORT, MCP_ALLOWED_HOSTS
    """
    import os
    import sys

    transport = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("MCP_TRANSPORT", "stdio")

    if transport in ("http", "streamable-http"):
        from mcp.server.transport_security import TransportSecuritySettings

        # Streamable HTTP's DNS-rebinding protection rejects requests whose Host
        # header isn't allowed. Configure via MCP_ALLOWED_HOSTS:
        #   unset / "*"      -> allow ANY host (default; disables the check)
        #   "example.com"    -> allow that host only (comma-separate for several)
        allowed = (os.environ.get("MCP_ALLOWED_HOSTS") or "*").strip()
        security = None
        if allowed == "*":
            security = TransportSecuritySettings(enable_dns_rebinding_protection=False)
        elif allowed:
            hosts = [h.strip() for h in allowed.split(",") if h.strip()]
            security = TransportSecuritySettings(allowed_hosts=hosts, allowed_origins=["*"])

        # Eagerly discover + cache the SSO login URL and Moodle backend base now,
        # so the first user request doesn't pay the discovery latency (best-effort;
        # falls back to lazy discovery on first login if it fails).
        warmed = prewarm()
        status = f"ok {warmed[1]}" if warmed else "deferred (will retry on first login)"
        print(f"[startup] site discovery: {status}", file=sys.stderr)

        mcp.run(
            transport="streamable-http",
            host=os.environ.get("MCP_HOST", "127.0.0.1"),  # set 0.0.0.0 to expose
            port=int(os.environ.get("MCP_PORT", "3033")),
            streamable_http_path="/mcp",
            json_response=True,  # plain JSON responses (easy to curl), not SSE
            stateless_http=True,  # each request independent -> no session handshake
            transport_security=security,
        )
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
