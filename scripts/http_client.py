"""
Minimal HTTP client for the NCCU Moodle MCP server (Streamable HTTP, stateless).

Because the server runs stateless with json_response, a tool call is a single
JSON-RPC POST to /mcp -- no initialize handshake, no session id. This uses plain
`requests`, so it needs no MCP SDK.

    uv run python scripts/http_client.py 112703016 'password' [sem]
"""
import json
import sys

import requests

URL = "http://127.0.0.1:3033/mcp"
HEADERS = {"Content-Type": "application/json",
           "Accept": "application/json, text/event-stream"}


def call_tool(name: str, arguments: dict, req_id: int = 1) -> dict:
    r = requests.post(URL, headers=HEADERS, json={
        "jsonrpc": "2.0", "id": req_id,
        "method": "tools/call",
        "params": {"name": name, "arguments": arguments},
    })
    r.raise_for_status()
    payload = r.json()
    if "error" in payload:
        raise RuntimeError(payload["error"])
    result = payload["result"]
    if result.get("isError"):
        raise RuntimeError(result["content"][0]["text"])
    # Tool returns its data as a JSON text content block.
    return json.loads(result["content"][0]["text"])


if __name__ == "__main__":
    username, password = sys.argv[1], sys.argv[2]
    sem = sys.argv[3] if len(sys.argv) > 3 else None
    args = {"username": username, "password": password}
    if sem:
        args["sem"] = sem
    data = call_tool("list_courses", args)
    print(f"{data['count']} course(s):")
    for c in data["courses"]:
        print(f"  [{c['id']}] {c['semester']}  {c['name']}")
