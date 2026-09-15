/** Minimal server-rendered login page. No client JS, no external assets. */

function esc(s: string): string {
  return s.replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]!,
  );
}

export function loginPage(challenge: string, error?: string): string {
  const err = error
    ? `<p role="alert" style="color:#b00020;margin:0 0 12px">${esc(error)}</p>`
    : "";
  return `<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>NCCU Moodle — Sign in</title>
<style>
  :root { color-scheme: light dark; }
  body { font-family: system-ui, sans-serif; margin:0; display:flex; min-height:100vh;
         align-items:center; justify-content:center; background:#f5f5f7; }
  .card { width:min(92vw,360px); background:#fff; border-radius:12px; padding:28px;
          box-shadow:0 6px 24px rgba(0,0,0,.08); }
  @media (prefers-color-scheme: dark){ body{background:#111} .card{background:#1c1c1e;color:#eee} }
  h1 { font-size:18px; margin:0 0 4px; } p.sub{ color:#888; font-size:13px; margin:0 0 20px; }
  label { display:block; font-size:13px; margin:14px 0 4px; }
  input { width:100%; box-sizing:border-box; padding:10px 12px; font-size:15px;
          border:1px solid #ccc; border-radius:8px; background:transparent; color:inherit; }
  button { width:100%; margin-top:20px; padding:11px; font-size:15px; border:0;
           border-radius:8px; background:#0a66c2; color:#fff; cursor:pointer; }
  .note { margin-top:16px; font-size:12px; color:#999; line-height:1.4; }
</style></head>
<body>
  <form class="card" method="post" action="/login">
    <h1>NCCU Moodle</h1>
    <p class="sub">Sign in with your NCCU portal account to connect.</p>
    ${err}
    <input type="hidden" name="challenge" value="${esc(challenge)}">
    <label for="u">Student ID / Account</label>
    <input id="u" name="username" autocomplete="username" autofocus required>
    <label for="p">Password</label>
    <input id="p" name="password" type="password" autocomplete="current-password" required>
    <button type="submit">Sign in</button>
    <p class="note">Your password is used only to establish this connection and is
      never stored. NCCU locks an account for 15 minutes after 5 failed attempts.</p>
  </form>
</body></html>`;
}
