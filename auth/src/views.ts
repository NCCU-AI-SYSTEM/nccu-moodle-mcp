/** Server-rendered login page with a click-through Terms consent modal. */

function esc(s: string): string {
  return s.replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]!,
  );
}

// Static Terms & Conditions / data-use text. Plain, self-contained. Not legal
// advice; the operator is encouraged to have counsel review before wide use.
const TERMS: [string, string][] = [
  [
    "1. Acceptance of Terms",
    "These Terms & Conditions and Data-Use terms (the “Terms”) form a binding " +
      "agreement between you (the “User”) and the operator of this service (the " +
      "“Operator”, “we”, “us”). By entering your credentials, " +
      "ticking the consent box, and signing in, you confirm that you have read, understood, " +
      "and agree to be bound by these Terms. If you do not agree, do not sign in or use the " +
      "Service.",
  ],
  [
    "2. Definitions",
    "“Service” means this authentication/login gateway together with the NCCU " +
      "Moodle MCP server it connects to. “Connected Application” means the " +
      "third-party application you authorise to use the Service on your behalf (for example, " +
      "ChatGPT). “Moodle” means NCCU’s Moodle learning platform. " +
      "“Credentials” means your iNCCU (NCCU portal) account ID and password.",
  ],
  [
    "3. The Service",
    "The Service lets a Connected Application access your NCCU Moodle account on your behalf, " +
      "via NCCU single sign-on (i.nccu.edu.tw) and the Moodle web-services API. It is an " +
      "independent, self-hosted, non-commercial tool provided free of charge.",
  ],
  [
    "4. Eligibility & authority",
    "You may use the Service only if you hold a valid NCCU account and are authorised to " +
      "access the Moodle data you request. You represent that your use complies with all NCCU " +
      "rules and applicable law, and that you will use only your own account and credentials.",
  ],
  [
    "5. Your credentials — password is never stored",
    "Your Credentials are submitted on this page and used one time, in server memory, solely " +
      "to complete NCCU single sign-on and obtain a Moodle access token. Your password is " +
      "NEVER written to disk, NEVER logged, and NEVER shared, and is discarded immediately " +
      "after authentication. The Connected Application and its AI model never receive your " +
      "password. You are responsible for keeping your Credentials confidential.",
  ],
  [
    "6. Moodle access token — stored encrypted",
    "After sign-in the Service holds a Moodle web-services token that authorises access to " +
      "your Moodle data. This token is encrypted (AES-256-GCM) with a key derived from your " +
      "session’s OAuth tokens, kept only in server memory, and never written to disk in " +
      "readable form. It cannot be decrypted without a live request from your Connected " +
      "Application, and it is discarded when your session ends or expires, or when the server " +
      "restarts.",
  ],
  [
    "7. Data we access and process",
    "Using your token, the Service reads only the Moodle data needed to fulfil requests you " +
      "make through the Connected Application — such as your courses, assignments, grades, " +
      "announcements, files and submissions — and, only where you explicitly ask, may " +
      "save assignment text on your behalf. It accesses your data only in response to your " +
      "requests and does not build a persistent profile of you.",
  ],
  [
    "8. Third-party services & data sharing",
    "The results of your requests are returned to the Connected Application, which is operated " +
      "by a third party under its own terms and privacy policy and is outside our control. The " +
      "Service also relies on third parties such as NCCU, network/tunnel and hosting providers. " +
      "We do not sell your data or share it with any other third party. All traffic is carried " +
      "over encrypted (HTTPS) connections. We are not responsible for the acts, omissions, " +
      "terms, or privacy practices of any third party.",
  ],
  [
    "9. Acceptable use",
    "You agree not to: use the Service in violation of any law or NCCU policy; access, or " +
      "attempt to access, any account or data that is not your own; interfere with, overload, " +
      "probe, or disrupt the Service or the systems it connects to; circumvent authentication or " +
      "rate limits; or use the Service for any unlawful, harmful, or abusive purpose. We may " +
      "throttle, suspend, or block use that we believe violates this section.",
  ],
  [
    "10. Academic integrity — your responsibility",
    "You are solely responsible for complying with NCCU’s academic-integrity, examination, " +
      "and coursework rules. The Service and any AI output are aids only; using them does not " +
      "authorise plagiarism, unauthorised assistance, contract cheating, or misrepresentation of " +
      "your work. Any assignment save or submission made through the Service is your own act and " +
      "responsibility. The Operator is not responsible or liable for any academic penalty, " +
      "disciplinary action, or other consequence arising from your use.",
  ],
  [
    "11. AI output & accuracy disclaimer",
    "Content produced with the help of the Connected Application’s AI may be inaccurate, " +
      "incomplete, outdated, or misleading, and may not reflect the true state of your Moodle " +
      "account. Do not rely on it for grades, deadlines, submission status, or any official " +
      "information; always verify against Moodle and official NCCU channels. The Service does " +
      "not guarantee the accuracy, completeness, or timeliness of any data, result, or action.",
  ],
  [
    "12. No affiliation; trademarks",
    "The Service is not affiliated with, authorised by, endorsed by, sponsored by, or operated " +
      "by National Chengchi University (NCCU), Moodle, or the operator of any Connected " +
      "Application. All names and trademarks (including “NCCU” and “Moodle”) " +
      "belong to their respective owners and are used only nominatively to identify the systems " +
      "accessed.",
  ],
  [
    "13. Intellectual property",
    "Your data remains yours. The Service’s software and design remain the property of the " +
      "Operator and its licensors. These Terms grant you only a limited, revocable, " +
      "non-exclusive, non-transferable permission to use the Service as intended; no other rights " +
      "are granted.",
  ],
  [
    "14. Availability, changes & sessions",
    "The Service is provided on a best-effort basis and may be modified, suspended, degraded, or " +
      "discontinued at any time, with or without notice. Access tokens and sessions expire, and " +
      "you may be required to sign in again. We do not guarantee any level of uptime, " +
      "performance, or data retention.",
  ],
  [
    "15. Disclaimer of warranties",
    "THE SERVICE IS PROVIDED “AS IS” AND “AS AVAILABLE”, WITHOUT WARRANTIES " +
      "OF ANY KIND, WHETHER EXPRESS, IMPLIED, OR STATUTORY, INCLUDING WITHOUT LIMITATION IMPLIED " +
      "WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE, TITLE, NON-INFRINGEMENT, " +
      "ACCURACY, SECURITY, OR UNINTERRUPTED OR ERROR-FREE OPERATION. YOU USE THE SERVICE AT YOUR " +
      "OWN RISK.",
  ],
  [
    "16. Limitation of liability",
    "TO THE MAXIMUM EXTENT PERMITTED BY LAW, THE OPERATOR SHALL NOT BE LIABLE FOR ANY INDIRECT, " +
      "INCIDENTAL, SPECIAL, CONSEQUENTIAL, EXEMPLARY, OR PUNITIVE DAMAGES, OR FOR ANY LOSS OF " +
      "DATA, GRADES, ACADEMIC STANDING, OPPORTUNITIES, OR GOODWILL, ARISING FROM OR RELATED TO " +
      "YOUR USE OF OR INABILITY TO USE THE SERVICE, EVEN IF ADVISED OF THE POSSIBILITY. TO THE " +
      "EXTENT LIABILITY CANNOT BE FULLY EXCLUDED, THE OPERATOR’S TOTAL AGGREGATE LIABILITY " +
      "SHALL NOT EXCEED NEW TAIWAN DOLLARS ZERO (NT$0), AS THE SERVICE IS PROVIDED FREE OF CHARGE.",
  ],
  [
    "17. Indemnification",
    "You agree to indemnify, defend, and hold harmless the Operator from and against any claims, " +
      "liabilities, damages, losses, and expenses (including reasonable legal fees) arising from " +
      "or related to your use of the Service, your violation of these Terms, or your violation of " +
      "any law or the rights of any third party.",
  ],
  [
    "18. Assumption of risk",
    "You acknowledge and accept the risks of using an automated, unofficial tool with your NCCU " +
      "account — including that automated access may interact unexpectedly with Moodle, that " +
      "data shown may be wrong, and that repeated failed sign-ins can trigger an NCCU account " +
      "lockout (NCCU locks an account for 15 minutes after 5 failed attempts). You assume these " +
      "risks voluntarily.",
  ],
  [
    "19. Suspension & termination",
    "The Operator may suspend or terminate the Service, or your access to it, at any time and " +
      "for any reason, without notice or liability. You may stop using the Service and revoke " +
      "its access at any time through the Connected Application. Sections that by their nature " +
      "should survive termination (including 5–17, 20–22) survive.",
  ],
  [
    "20. Changes to these Terms",
    "The Operator may update these Terms at any time. Changes take effect when posted on this " +
      "sign-in page, and your continued use of the Service after changes constitutes acceptance " +
      "of the updated Terms. If you do not agree to a change, stop using the Service.",
  ],
  [
    "21. Governing law & jurisdiction",
    "These Terms are governed by the laws of the Republic of China (Taiwan), without regard to " +
      "its conflict-of-laws rules. You agree to the exclusive jurisdiction of the competent " +
      "courts located in Taiwan for any dispute arising out of or relating to the Service or " +
      "these Terms, to the extent permitted by mandatory law.",
  ],
  [
    "22. Severability; waiver; entire agreement",
    "If any provision of these Terms is held invalid or unenforceable, the remaining provisions " +
      "remain in full force and effect. Failure to enforce any provision is not a waiver of it. " +
      "These Terms are the entire agreement between you and the Operator regarding the Service " +
      "and supersede all prior discussions. The Service does not provide legal, academic, " +
      "financial, or other professional advice.",
  ],
  [
    "23. Consent",
    "By entering your credentials and signing in, you acknowledge that you have read and agree " +
      "to these Terms & Conditions and Data-Use terms, and specifically that your password is " +
      "used only to sign in and is never stored, and that your Moodle token is stored only in " +
      "encrypted form.",
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
  .modal { width:min(94vw,540px); max-height:86vh; display:flex; flex-direction:column;
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
        <p class="tc-end">— End of Terms — you may now agree —</p>
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
