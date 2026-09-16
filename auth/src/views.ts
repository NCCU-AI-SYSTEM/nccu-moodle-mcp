/** Server-rendered login page with a click-through Terms consent modal. */

function esc(s: string): string {
  return s.replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]!,
  );
}

// Static Terms & Conditions / data-use text. Plain, self-contained.
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
  [
    "9. Acceptance",
    "By entering your credentials and signing in, you acknowledge that you have read and " +
      "agree to these Terms & Conditions and Data-Use terms. You understand that your " +
      "password is used only to sign in and is never stored, and that your Moodle token " +
      "is stored only in encrypted form.",
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
  :root { color-scheme: light dark; --bd:#ccc; --muted:#888; }
  @media (prefers-color-scheme: dark){ :root{ --bd:#3a3a3c; --muted:#9a9a9e; } }
  body { font-family: system-ui, sans-serif; margin:0; display:flex; min-height:100vh;
         align-items:center; justify-content:center; background:#f5f5f7; padding:24px 0; }
  .card { width:min(92vw,400px); background:#fff; border-radius:12px; padding:28px;
          box-shadow:0 6px 24px rgba(0,0,0,.08); }
  @media (prefers-color-scheme: dark){ body{background:#111} .card{background:#1c1c1e;color:#eee} }
  h1 { font-size:18px; margin:0 0 4px; } p.sub{ color:var(--muted); font-size:13px; margin:0 0 20px; }
  label.fld { display:block; font-size:13px; margin:14px 0 4px; }
  input[type=text], input[type=password] {
          width:100%; box-sizing:border-box; padding:10px 12px; font-size:15px;
          border:1px solid var(--bd); border-radius:8px; background:transparent; color:inherit; }
  button.primary { width:100%; margin-top:20px; padding:11px; font-size:15px; border:0;
           border-radius:8px; background:#0a66c2; color:#fff; cursor:pointer; }
  button.primary:disabled { opacity:.5; cursor:not-allowed; }
  .agree { display:flex; gap:8px; align-items:flex-start; margin-top:18px; font-size:12.5px;
           color:var(--muted); line-height:1.45; }
  .agree input { margin-top:2px; flex:0 0 auto; }
  a.tc-link { color:inherit; text-decoration:underline; cursor:pointer; font-weight:600; }

  .overlay { position:fixed; inset:0; background:rgba(0,0,0,.5); display:flex;
             align-items:center; justify-content:center; padding:16px; z-index:10; }
  .overlay[hidden] { display:none; }   /* explicit display above overrides the
                                          hidden attribute, so restore it here */
  .modal { width:min(94vw,520px); max-height:86vh; display:flex; flex-direction:column;
           background:#fff; color:#222; border-radius:12px; overflow:hidden; }
  @media (prefers-color-scheme: dark){ .modal{ background:#1c1c1e; color:#eee; } }
  .modal-head { display:flex; align-items:center; justify-content:space-between;
                padding:14px 16px; border-bottom:1px solid var(--bd); }
  .modal-head strong { font-size:15px; }
  .modal-head button { background:none; border:0; font-size:22px; line-height:1; cursor:pointer;
                       color:inherit; }
  .modal-body { overflow-y:auto; padding:4px 18px 14px; font-size:12.5px; line-height:1.55;
                color:var(--muted); }
  .modal-body h4 { font-size:13px; margin:14px 0 2px; color:inherit; }
  .modal-body p { margin:0 0 6px; }
  .tc-end { text-align:center; font-weight:600; margin-top:14px !important; }
  .modal-foot { display:flex; gap:10px; padding:12px 16px; border-top:1px solid var(--bd); }
  .modal-foot button { flex:1; padding:10px; font-size:14px; border-radius:8px; cursor:pointer; }
  .modal-foot .disagree { background:transparent; border:1px solid var(--bd); color:inherit; }
  .modal-foot .agreebtn { background:#0a66c2; color:#fff; border:0; }
  .modal-foot .agreebtn:disabled { opacity:.5; cursor:not-allowed; }
</style></head>
<body>
  <form class="card" method="post" action="/login" id="form">
    <h1>NCCU Moodle</h1>
    <p class="sub">Sign in with your <strong>iNCCU</strong> (NCCU portal) account to connect.</p>
    ${err}
    <input type="hidden" name="challenge" value="${esc(challenge)}">
    <label class="fld" for="u">iNCCU Account (Student ID)</label>
    <input id="u" name="username" type="text" autocomplete="username" autofocus required>
    <label class="fld" for="p">Password</label>
    <input id="p" name="password" type="password" autocomplete="current-password" required>

    <div class="agree">
      <input type="checkbox" name="agree" value="yes" id="agree" required>
      <span>I have read and agree to the
        <a class="tc-link" id="tc-link" role="button" tabindex="0">Terms &amp; Conditions and Data-Use terms</a>.</span>
    </div>

    <button type="submit" class="primary" id="submit" disabled>Sign in</button>
  </form>

  <div class="overlay" id="tc-overlay" hidden>
    <div class="modal" role="dialog" aria-modal="true" aria-labelledby="tc-title">
      <div class="modal-head">
        <strong id="tc-title">Terms &amp; Conditions and Data Use</strong>
        <button type="button" id="tc-close" aria-label="Close">&times;</button>
      </div>
      <div class="modal-body" id="tc-body">
        ${terms}
        <p class="tc-end">— End of Terms — scroll reached, you may now agree —</p>
      </div>
      <div class="modal-foot">
        <button type="button" class="disagree" id="tc-disagree">Disagree</button>
        <button type="button" class="agreebtn" id="tc-agree" disabled>Scroll to the bottom to agree</button>
      </div>
    </div>
  </div>

<script>
(function () {
  var overlay = document.getElementById('tc-overlay');
  var body = document.getElementById('tc-body');
  var agreeBtn = document.getElementById('tc-agree');
  var cb = document.getElementById('agree');
  var submit = document.getElementById('submit');
  var link = document.getElementById('tc-link');

  var agreed = false;
  function setAgreed(v) { agreed = v; cb.checked = v; submit.disabled = !v; }

  function atBottom() {
    return body.scrollTop + body.clientHeight >= body.scrollHeight - 4;
  }
  function refreshAgree() {
    var ok = atBottom();
    agreeBtn.disabled = !ok;
    agreeBtn.textContent = ok ? 'I Agree' : 'Scroll to the bottom to agree';
  }
  function open() {
    overlay.hidden = false;
    document.body.style.overflow = 'hidden';
    body.scrollTop = 0;
    // allow layout to settle before measuring
    setTimeout(refreshAgree, 0);
  }
  function close() {
    overlay.hidden = true;
    document.body.style.overflow = '';
  }

  // The checkbox can never toggle on its own: always prevent the default toggle
  // (the browser pre-toggles cb.checked inside the click handler, so we track our
  // own agreed flag instead of reading cb.checked here). If not yet agreed, open
  // the modal; if already agreed, a click un-agrees.
  function boxToggle(e) {
    e.preventDefault();
    if (agreed) setAgreed(false);
    else open();
  }
  cb.addEventListener('click', boxToggle);
  cb.addEventListener('keydown', function (e) {
    if (e.key === ' ' || e.key === 'Enter') boxToggle(e);
  });

  function openFromLink(e) { e.preventDefault(); open(); }
  link.addEventListener('click', openFromLink);
  link.addEventListener('keydown', function (e) {
    if (e.key === 'Enter' || e.key === ' ') openFromLink(e);
  });

  body.addEventListener('scroll', refreshAgree);
  window.addEventListener('resize', function () { if (!overlay.hidden) refreshAgree(); });

  agreeBtn.addEventListener('click', function () {
    if (agreeBtn.disabled) return;
    setAgreed(true);
    close();
  });
  document.getElementById('tc-close').addEventListener('click', close);   // X: leave unchecked
  document.getElementById('tc-disagree').addEventListener('click', function () {
    setAgreed(false); close();
  });
  overlay.addEventListener('click', function (e) { if (e.target === overlay) close(); });
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape' && !overlay.hidden) close();
  });

  setAgreed(false); // start not agreed; Sign in disabled
})();
</script>
</body></html>`;
}
