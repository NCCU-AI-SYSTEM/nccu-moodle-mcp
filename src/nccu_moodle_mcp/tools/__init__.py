"""Tool modules — one per MCP tool, each owning its own `@mcp.tool` registration
plus tool-specific helpers. Importing this package imports every module, which is
what registers the tools on the shared MCPServer instance."""

from . import (  # noqa: F401 -- imported for their @mcp.tool registration side effects
    announcements,
    assignments,
    contents,
    courses,
    deadlines,
    grades,
    module,
    notifications,
    submissions,
)
