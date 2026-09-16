/** Minimal server-rendered login page. No client JS, no external assets. */

function esc(s: string): string {
  return s.replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]!,
  );
}

// Static Terms & Conditions / data-use text shown on the login page. Plain,
// self-contained; describes exactly how credentials and the Moodle token are
// handled by this service.
const TERMS: [string, string][] = [
  [
    "1. The Service",
    "This service (the “Service”) lets an application you have connected " +
      "(for example, an AI assistant such as ChatGPT) access your NCCU Moodle account " +
      "on your behalf, via NCCU single sign-on (i.nccu.edu.tw) and the Moodle " +
      "web-services API. It is an independent, self-hosted tool.",
  ],
  [
    "2. Your credentials — password is never stored",
    "Your iNCCU (NCCU portal) account ID and password are submitted on this page and " +
      "used one time, in server memory, solely to complete NCCU single sign-on and " +
      "obtain a Moodle access token. Your password is NEVER written to disk, NEVER " +
      "logged, and NEVER shared, and is discarded immediately after authentication. " +
      "The connected application and its AI model never receive your password.",
  ],
  [
    "3. Moodle access token — stored encrypted",
    "After sign-in the Service holds a Moodle web-services token that authorizes access " +
      "to your Moodle data. This token is encrypted (AES-256-GCM) with a key derived " +
      "from your session’s OAuth tokens, kept only in server memory, and never " +
      "written to disk in readable form. It cannot be decrypted without a live request " +
      "from your connected application, and it is discarded when your session ends or " +
      "expires, or when the server restarts.",
  ],
  [
    "4. Data accessed",
    "Using your token, the Service reads only the Moodle data needed to fulfil requests " +
      "you make through the connected application — such as your courses, " +
      "assignments, grades, announcements, files and submissions — and, only where " +
      "you explicitly ask, may save assignment text on your behalf. It accesses your " +
      "data only in response to your requests.",
  ],
  [
    "5. Data sharing",
    "The results of your requests are returned to the application you connected, which is " +
      "operated by a third party under its own terms and privacy policy. The Service does " +
      "not sell your data or share it with any other third party. All traffic is carried " +
      "over encrypted (HTTPS) connections.",
  ],
  [
    "6. No affiliation",
    "The Service is not affiliated with, authorised by, endorsed by, or operated by " +
      "National Chengchi University (NCCU) or Moodle. “NCCU” and “Moodle” " +
      "are used only to identify the systems being accessed.",
  ],
  [
    "7. Your responsibilities",
    "You may use the Service only with your own account and in compliance with NCCU’s " +
      "acceptable-use and IT policies and all applicable rules. Note: NCCU locks an account " +
      "for 15 minutes after 5 failed sign-in attempts.",
  ],
  [
    "8. Revocation & no warranty",
    "You may disconnect the application or stop using the Service at any time, which ends " +
      "its access; tokens also expire automatically. The Service is provided “as is” " +
      "and “as available”, without warranties of any kind. To the maximum extent " +
      "permitted by law, the operator is not liable for any damages arising from your use " +
      "of the Service, including any loss of data or academic consequences. You use the " +
      "Service at your own risk.",
  ],
];

export function loginPage(challenge: string, error?: string): string {
  const err = error
    ? `<p role="alert" style="color:#b00020;margin:0 0 12px">${esc(error)}</p>`
    : "";
  const terms = TERMS.map(([h, b]) => `<h4>${h}</h4><p>${b}</p>`).join("");
  return `<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>NCCU Moodle MCP — Sign in</title>
<style>
  :root { color-scheme: light dark; }
  body { font-family: system-ui, sans-serif; margin:0; display:flex; min-height:100vh;
         align-items:center; justify-content:center; background:#f5f5f7; padding:24px 0; }
  .card { width:min(92vw,400px); background:#fff; border-radius:12px; padding:28px;
          box-shadow:0 6px 24px rgba(0,0,0,.08); }
  @media (prefers-color-scheme: dark){ body{background:#111} .card{background:#1c1c1e;color:#eee} }
  h1 { font-size:18px; margin:0 0 4px; } p.sub{ color:#888; font-size:13px; margin:0 0 20px; }
  label { display:block; font-size:13px; margin:14px 0 4px; }
  input[type=text], input[type=password] {
          width:100%; box-sizing:border-box; padding:10px 12px; font-size:15px;
          border:1px solid #ccc; border-radius:8px; background:transparent; color:inherit; }
  button { width:100%; margin-top:20px; padding:11px; font-size:15px; border:0;
           border-radius:8px; background:#0a66c2; color:#fff; cursor:pointer; }
  button:disabled { opacity:.5; cursor:not-allowed; }
  details.terms { margin-top:18px; border:1px solid #ddd; border-radius:8px; }
  @media (prefers-color-scheme: dark){ details.terms{border-color:#3a3a3c} input[type=text],input[type=password]{border-color:#3a3a3c} }
  details.terms summary { cursor:pointer; padding:10px 12px; font-size:13px; font-weight:600; }
  .terms-body { max-height:220px; overflow-y:auto; padding:0 12px 8px; font-size:12px;
                line-height:1.5; color:#666; }
  @media (prefers-color-scheme: dark){ .terms-body{color:#aaa} }
  .terms-body h4 { font-size:12.5px; margin:12px 0 2px; color:inherit; }
  .terms-body p { margin:0 0 4px; }
  .agree { display:flex; gap:8px; align-items:flex-start; margin-top:16px; font-size:12.5px;
           color:#555; line-height:1.4; }
  @media (prefers-color-scheme: dark){ .agree{color:#bbb} }
  .agree input { margin-top:2px; }
</style></head>
<body>
  <form class="card" method="post" action="/login">
    <h1>NCCU Moodle</h1>
    <p class="sub">Sign in with your <strong>iNCCU</strong> (NCCU portal) account to connect.</p>
    ${err}
    <input type="hidden" name="challenge" value="${esc(challenge)}">
    <label for="u">iNCCU Account (Student ID)</label>
    <input id="u" name="username" type="text" autocomplete="username" autofocus required>
    <label for="p">Password</label>
    <input id="p" name="password" type="password" autocomplete="current-password" required>

    <details class="terms">
      <summary>Terms &amp; Conditions and Data Use — please read</summary>
      <div class="terms-body">
        ${terms}
      </div>
    </details>

    <label class="agree">
      <input type="checkbox" name="agree" value="yes" required>
      <span>I have read and agree to the Terms &amp; Conditions and Data-Use terms above.
        I understand my password is used only to sign in and is never stored, and that my
        Moodle token is stored only in encrypted form. By signing in, I accept these terms.</span>
    </label>

    <button type="submit">Sign in</button>
  </form>
</body></html>`;
}
