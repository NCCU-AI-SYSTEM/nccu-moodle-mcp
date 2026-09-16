# Connecting NCCU Moodle MCP to ChatGPT

This guide is for **end users** who want to use the NCCU Moodle MCP server inside
ChatGPT as a custom **connector** (MCP). You sign in with your own iNCCU account;
your password is never stored (see the Terms shown on the login page).

> If you run Claude Code / opencode instead of ChatGPT, you don't need this — use
> header credentials as described in the main `README.md`.

---

## What you need

1. **The server URL** from whoever runs the server (the operator), ending in
   **`/mcp`** — for example:
   ```
   https://nccu-moodle-mcp.example.com/mcp
   ```
   It must be a public **HTTPS** URL and it must end in `/mcp` (not the bare
   domain — see Troubleshooting).
2. **A ChatGPT plan that supports custom connectors / developer mode.** Custom
   MCP connectors are a Plus/Pro/Business/Enterprise feature and may be gated by
   region/rollout. The exact menu names below can differ slightly by plan and
   app version.
3. Your **iNCCU (NCCU portal) account** — student ID + the password you use at
   <https://i.nccu.edu.tw>.

---

## Step 1 — Enable Developer mode (custom connectors)

Custom MCP connectors live behind **Developer mode**.

1. Open ChatGPT (web is easiest for setup: <https://chatgpt.com>).
2. Go to **Settings** → **Connectors** (may be under **Apps & Connectors** /
   **Connectors**).
3. Open **Advanced** (or **Advanced settings**) and turn on **Developer mode**
   (sometimes labelled "Custom connectors" or "MCP").
   - On Business/Enterprise, a workspace **admin** may need to allow custom /
     developer connectors first.

You'll now see an option to add your own connector.

---

## Step 2 — Add the connector

1. In **Settings → Connectors**, click **Create** / **Add** / **New connector**
   (in Developer mode this is the custom/MCP option).
2. Fill in:
   - **Name**: anything, e.g. `NCCU Moodle`.
   - **MCP Server URL** / **URL**: the `/mcp` URL from the operator, e.g.
     `https://nccu-moodle-mcp.example.com/mcp`.
   - **Authentication**: **OAuth** (it should auto-detect this).
3. Click **Create** / **Save**.

You do **not** enter any client ID or secret — the connector registers itself
automatically (Dynamic Client Registration). If ChatGPT asks you to paste a
client ID/secret, the URL is wrong or points at something that isn't this server.

---

## Step 3 — Connect and sign in

1. Click **Connect** on the connector. ChatGPT opens an OAuth window.
2. You'll land on the **NCCU Moodle sign-in page** served by the connector:
   - Enter your **iNCCU account (student ID)** and **password**.
   - Click the **Terms & Conditions and Data-Use terms** link (or the checkbox),
     **scroll to the bottom**, and click **I Agree**. This ticks the consent box.
   - Click **Sign in**.
3. On success the window closes and the connector shows **Connected**.

What happens to your credentials (also on the login page):
- Your **password** is used once to sign in through NCCU SSO and is **never
  stored, logged, or shared** — the AI never sees it.
- The **Moodle access token** is stored only in **encrypted** form and used to
  read your Moodle data on your behalf when you ask.

---

## Step 4 — Use it in a chat

1. Start a new chat. Open the **+ / tools / connectors** menu in the composer and
   enable **NCCU Moodle** for the conversation (in Developer mode you may need to
   toggle the connector on per chat).
2. Ask things like:
   - "List my Moodle courses this semester."
   - "What assignments are due this week, and have I submitted them?"
   - "Open my latest announcement in <course> and summarize it."
   - "Show my grades in <course>."
   - "Search my courses for 物件導向."
3. ChatGPT will call the connector's tools; the first call in a while may prompt
   you to confirm/allow the connector.

---

## Managing the connector

- **Disconnect / revoke**: Settings → Connectors → the connector → **Disconnect**.
  This ends its access to your Moodle account.
- **Re-sign-in**: if it stops working (e.g. your Moodle session expired), click
  **Connect** again and sign in.

---

## Troubleshooting

| Symptom | Cause & fix |
|---|---|
| **"There was a problem connecting … 424"** after auth succeeds | The connector URL is the bare domain, not the MCP endpoint. Set the URL to end in **`/mcp`** (e.g. `https://…/mcp`), then reconnect. |
| **`invalid_client` — "The requested OAuth 2.0 Client does not exist"** | ChatGPT cached a client that the server no longer has (e.g. the operator reset the server database). **Delete the connector and add it again** — reconnecting alone reuses the dead client. |
| **Asked to enter a client ID / secret** | The URL is wrong or not this server. Use the exact `/mcp` URL; no ID/secret is needed. |
| **`invalid_scope` … `offline_access`** | The server is out of date. Ask the operator to deploy the latest version. |
| **Login page error: "You must accept the Terms & Conditions"** | You clicked Sign in without agreeing. Open the Terms (checkbox or underlined link), scroll to the bottom, click **I Agree**, then Sign in. |
| **"Incorrect username or password"** | Re-enter your iNCCU credentials. ⚠️ NCCU **locks the account for 15 minutes after 5 failed attempts** — don't keep guessing. |
| **CSRF / "request_forbidden" / a raw error page** | A server-side configuration issue — report it to the operator (it's not something you can fix from ChatGPT). |
| **Tools don't appear / connector shows connected but does nothing** | Make sure the connector is enabled **for that chat** (Developer mode is per-conversation), then send a request. |

---

## Notes & privacy

- The connector accesses your Moodle data **only when you ask** (courses,
  assignments, grades, announcements, files, submissions; and, only if you
  explicitly ask, saving assignment text).
- Results are returned to **ChatGPT** (a third party, under its own terms).
- The service is **not affiliated with NCCU or Moodle**; it's an independent tool.
- Full details are in the Terms & Conditions on the login page and in
  [`docs/oauth.md`](oauth.md).
