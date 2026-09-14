# NCCU Moodle MCP

An MCP server that accesses **NCCU Moodle** (`moodle45.nccu.edu.tw`) on behalf of a
student. It logs in through the NCCU single-sign-on portal (`i.nccu.edu.tw`) and
exposes Moodle data as MCP tools.

It runs as a **hosted HTTP server**: you (the operator) run one instance, and
everyone else just adds its URL to their MCP client config — no install on their
side.

- **Multi-tenant & stateless** — each call authenticates with the credentials
  passed to it, uses that session for the one call, and discards it. Nothing is
  cached to disk or shared between calls, so concurrent users never interfere.

### Tools
| Tool | Description |
|------|-------------|
| `list_courses` | List a student's courses grouped by semester. No `sem` → latest semester only; `sem="1142"` or a full label → that semester; `sem="all"` → every semester. |

---

## Part A — For users (setup guide)

You do **not** clone or install anything. You just add one block to your MCP
client's config: the central server's address plus **your own** NCCU credentials
as headers. The server reads those headers on each request, so every user
connects as themselves.

**Before you start, get these three things:**

1. The **server address** from the operator — e.g. `http://140.119.x.x:8000/mcp`
   or `https://moodle-mcp.example.com/mcp`.
2. Your **NCCU student ID** (e.g. `112703016`).
3. Your **NCCU portal password** (the one you use at <https://i.nccu.edu.tw>).

In every snippet below, replace `SERVER_ADDRESS`, `YOUR_STUDENT_ID`, and
`YOUR_PASSWORD`.

---

### Claude Code

**Option 1 — CLI (easiest).** Run this once; the flag `-s user` makes it
available in every project:

```bash
claude mcp add -s user --transport http nccu-moodle SERVER_ADDRESS \
  -H "X-Moodle-Username: YOUR_STUDENT_ID" \
  -H "X-Moodle-Password: YOUR_PASSWORD"
```

**Option 2 — edit the config file** directly. Create/edit `.mcp.json` in your
project folder (or add this `mcpServers` block to your existing config):

```json
{
  "mcpServers": {
    "nccu-moodle": {
      "type": "http",
      "url": "SERVER_ADDRESS",
      "headers": {
        "X-Moodle-Username": "YOUR_STUDENT_ID",
        "X-Moodle-Password": "YOUR_PASSWORD"
      }
    }
  }
}
```

**Verify:**

```bash
claude mcp list                 # nccu-moodle should be listed
```

Then start Claude Code and run `/mcp` — you should see `nccu-moodle` connected
with the `list_courses` tool.

---

### opencode

opencode is configured by a JSON file (there's no add command for MCP). Edit
one of:

- **Global** (recommended, works everywhere): `~/.config/opencode/opencode.json`
- **Per project**: `opencode.json` in the project root

Add the `mcp` block (merge into the file if it already exists):

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "nccu-moodle": {
      "type": "remote",
      "url": "SERVER_ADDRESS",
      "enabled": true,
      "headers": {
        "X-Moodle-Username": "YOUR_STUDENT_ID",
        "X-Moodle-Password": "YOUR_PASSWORD"
      }
    }
  }
}
```

**Verify:** restart opencode; the `list_courses` tool from `nccu-moodle` should
be available to the assistant.

---

### Try it

Ask the assistant, for example:

> *List my Moodle courses this semester.*
> *List all my Moodle courses.*  (→ every semester)
> *What courses did I take in 1142?*

It calls `list_courses` and reads your credentials from the headers you set — so
you never type your password into the chat, and **the assistant never sees or
handles your password** (the tool has no username/password parameters).

---

### Notes & safety

> ⚠️ **Lockout:** NCCU suspends an account for **15 minutes after 5 failed login
> attempts**. Make sure the password in your config is correct.
>
> 🔒 Your password is stored in a local config file and sent to the server on
> each call. Keep that file private, and don't commit a personal `.mcp.json` /
> `opencode.json` containing your password to a shared repository. The operator
> should serve the endpoint over **HTTPS** (see Part B).

**Troubleshooting:**

| Symptom | Fix |
|---------|-----|
| Tool errors with *"Missing credentials…"* | The `headers` block is missing or misspelled. Header names must be exactly `X-Moodle-Username` and `X-Moodle-Password`. |
| *"Moodle login failed…"* | Wrong student ID or password. Fix it in the config (mind the 5-attempt lockout). |
| `list_courses` not showing up | Config not loaded — re-check the file location, valid JSON, and restart the client. For Claude Code, confirm with `claude mcp list`. |
| Connection/timeout errors | Server address wrong or server not reachable. Confirm `SERVER_ADDRESS` with the operator. |

---

## Part B — For the operator (run the server)

This project uses **[uv](https://docs.astral.sh/uv/)** to manage Python and
dependencies.

### 1. Install

```bash
cd /path/to/moodle_mcp
uv sync          # creates .venv and installs from uv.lock
```

(Install uv first if needed: `curl -LsSf https://astral.sh/uv/install.sh | sh`.)

### 2. Run as an HTTP server

```bash
MCP_HOST=0.0.0.0 \
MCP_PORT=8000 \
MCP_ALLOWED_HOSTS="moodle-mcp.example.com" \
uv run nccu-moodle-mcp http
```

Endpoint: `http://<host>:8000/mcp` (Streamable HTTP, stateless, JSON responses).

Environment variables:

| Var | Default | Purpose |
|-----|---------|---------|
| `MCP_HOST` | `127.0.0.1` | Bind address. Set `0.0.0.0` to accept remote connections. |
| `MCP_PORT` | `8000` | Port. |
| `MCP_ALLOWED_HOSTS` | *(localhost only)* | Comma-separated hostnames allowed in the `Host` header (DNS-rebinding protection). Set to your public domain. Use `*` to disable the check **only** behind a trusted reverse proxy. |

> DNS-rebinding protection is on by default. If `MCP_ALLOWED_HOSTS` doesn't
> include the host clients use, requests are rejected with **HTTP 421**.

### 3. Put it behind HTTPS (recommended)

Terminate TLS with a reverse proxy and forward to the app on localhost. Example
Caddy config:

```
moodle-mcp.example.com {
    reverse_proxy 127.0.0.1:8000
}
```

Run the app bound to localhost with the public host allowed:

```bash
MCP_ALLOWED_HOSTS="moodle-mcp.example.com" uv run nccu-moodle-mcp http
```

(With nginx/other proxies you can instead set `MCP_ALLOWED_HOSTS="*"` since the
proxy is the only client the app sees — but only if the app port is not otherwise
reachable.)

### 4. Keep it running

Run under a process manager (systemd, pm2, Docker, …). Minimal systemd unit:

```ini
[Unit]
Description=NCCU Moodle MCP
After=network.target

[Service]
WorkingDirectory=/path/to/moodle_mcp
Environment=MCP_HOST=127.0.0.1
Environment=MCP_ALLOWED_HOSTS=moodle-mcp.example.com
ExecStart=/path/to/uv run nccu-moodle-mcp http
Restart=always

[Install]
WantedBy=multi-user.target
```

### Smoke test

```bash
curl -s https://moodle-mcp.example.com/mcp -X POST \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

---

## Files

| File | Purpose |
|------|---------|
| `server.py` | MCP server (stdio + HTTP), tool definitions |
| `moodle_client.py` | `MoodleClient`: stateless SSO login + `list_courses` |
| `client.py` | Minimal HTTP client for testing (plain `requests`) |
| `pyproject.toml` | Project metadata, dependencies, `nccu-moodle-mcp` entry point |
| `uv.lock` | Pinned dependency lockfile (committed) |
