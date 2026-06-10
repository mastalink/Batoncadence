"""
Minimal control-plane dashboard served by the gateway at /dashboard.

Single static HTML page, no build step. It talks to the existing REST API with
a bearer token the operator pastes once (kept in browser localStorage): job
board with status colors, approval queue with approve/reject buttons, agent
fleet presence, and a per-job audit trail viewer.
"""

DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>BatonCadence Control Plane</title>
<style>
  :root { color-scheme: dark; }
  body { font-family: -apple-system, "Segoe UI", Roboto, sans-serif; background: #0d1117; color: #e6edf3; margin: 0; padding: 1.5rem; }
  h1 { font-size: 1.3rem; } h2 { font-size: 1rem; margin: 1.5rem 0 .5rem; color: #8b949e; text-transform: uppercase; letter-spacing: .05em; }
  table { width: 100%; border-collapse: collapse; font-size: .85rem; }
  th, td { text-align: left; padding: .4rem .6rem; border-bottom: 1px solid #21262d; vertical-align: top; }
  th { color: #8b949e; font-weight: 600; }
  .badge { padding: .1rem .5rem; border-radius: 999px; font-size: .75rem; font-weight: 600; white-space: nowrap; }
  .s-pending { background:#1f3d2b; color:#3fb950; } .s-waiting { background:#2d2a1f; color:#d29922; }
  .s-needs_approval { background:#3d2d1f; color:#f0883e; } .s-leased,.s-in_progress { background:#1f2d3d; color:#58a6ff; }
  .s-completed { background:#1f3d2b; color:#3fb950; } .s-failed,.s-rejected { background:#3d1f1f; color:#f85149; }
  .s-online { background:#1f3d2b; color:#3fb950; } .s-offline { background:#3d1f1f; color:#f85149; }
  button { background:#21262d; color:#e6edf3; border:1px solid #30363d; border-radius:6px; padding:.25rem .7rem; cursor:pointer; font-size:.8rem; }
  button:hover { background:#30363d; }
  button.ok { border-color:#238636; color:#3fb950; } button.no { border-color:#da3633; color:#f85149; }
  input { background:#0d1117; border:1px solid #30363d; border-radius:6px; color:#e6edf3; padding:.35rem .6rem; width:24rem; }
  #token-bar { display:flex; gap:.5rem; align-items:center; margin-bottom:1rem; }
  #audit-panel { background:#161b22; border:1px solid #30363d; border-radius:8px; padding:1rem; margin-top:1rem; display:none; }
  .muted { color:#8b949e; } pre { white-space:pre-wrap; margin:0; font-size:.78rem; }
  .err { color:#f85149; }
</style>
</head>
<body>
<h1>BatonCadence Control Plane</h1>
<div id="token-bar">
  <input id="token" type="password" placeholder="Paste agent bearer token (approver role for approvals)">
  <button onclick="saveToken()">Connect</button>
  <span id="conn" class="muted"></span>
</div>

<h2>Approval Queue</h2>
<table><thead><tr><th>Job</th><th>Title</th><th>Target</th><th>From</th><th>Decide</th></tr></thead>
<tbody id="approvals"><tr><td colspan="5" class="muted">-</td></tr></tbody></table>

<h2>Job Board</h2>
<table><thead><tr><th>Job</th><th>Title</th><th>Status</th><th>Target</th><th>Leased By</th><th>Created</th><th>Audit</th></tr></thead>
<tbody id="jobs"><tr><td colspan="7" class="muted">-</td></tr></tbody></table>

<h2>Agent Fleet</h2>
<table><thead><tr><th>Instance</th><th>Role</th><th>Status</th><th>Last Seen</th></tr></thead>
<tbody id="agents"><tr><td colspan="4" class="muted">-</td></tr></tbody></table>

<div id="audit-panel">
  <h2 style="margin-top:0">Audit Trail: <span id="audit-job"></span></h2>
  <pre id="audit-body"></pre>
</div>

<script>
const $ = id => document.getElementById(id);
let token = localStorage.getItem("mco_token") || "";
$("token").value = token;

function saveToken() {
  token = $("token").value.trim();
  localStorage.setItem("mco_token", token);
  refresh();
}

async function api(path, opts = {}) {
  const res = await fetch(path, {
    ...opts,
    headers: { "Authorization": "Bearer " + token, "Content-Type": "application/json", ...(opts.headers || {}) },
  });
  if (!res.ok) throw new Error(res.status + " " + (await res.text()));
  return res.json();
}

function badge(status) {
  return `<span class="badge s-${status}">${status}</span>`;
}
function esc(s) {
  return String(s ?? "").replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;","\\"":"&quot;"}[c]));
}
function short(id) { return String(id ?? "").slice(0, 8); }

async function refresh() {
  if (!token) { $("conn").textContent = "no token"; return; }
  try {
    const [jobs, agents] = await Promise.all([api("/api/jobs"), api("/api/agents")]);
    $("conn").textContent = "connected - " + new Date().toLocaleTimeString();
    $("conn").className = "muted";

    const approvals = jobs.filter(j => j.status === "needs_approval");
    $("approvals").innerHTML = approvals.length ? approvals.map(j => `
      <tr><td>${short(j.id)}</td><td>${esc(j.title)}</td><td>${esc(j.target_agent_role)}</td>
      <td>${esc(j.source_agent_id)}</td>
      <td><button class="ok" onclick="decide('${j.id}','approve')">Approve</button>
          <button class="no" onclick="decide('${j.id}','reject')">Reject</button></td></tr>`).join("")
      : '<tr><td colspan="5" class="muted">Nothing awaiting approval.</td></tr>';

    $("jobs").innerHTML = jobs.length ? jobs.map(j => `
      <tr><td>${short(j.id)}</td><td>${esc(j.title)}</td><td>${badge(j.status)}</td>
      <td>${esc(j.target_agent_role)}${j.target_agent_id ? " / " + esc(j.target_agent_id) : ""}</td>
      <td>${esc(j.leased_by_instance_id || "-")}</td><td>${esc((j.created_at || "").slice(0, 19))}</td>
      <td><button onclick="showAudit('${j.id}')">View</button></td></tr>`).join("")
      : '<tr><td colspan="7" class="muted">No jobs.</td></tr>';

    $("agents").innerHTML = agents.length ? agents.map(a => `
      <tr><td>${esc(a.instance_id)}</td><td>${esc(a.role)}</td><td>${badge(a.status)}</td>
      <td>${esc((a.last_seen_at || "").slice(0, 19))}</td></tr>`).join("")
      : '<tr><td colspan="4" class="muted">No agents registered.</td></tr>';
  } catch (e) {
    $("conn").textContent = "error: " + e.message;
    $("conn").className = "err";
  }
}

async function decide(jobId, action) {
  let body = {};
  if (action === "reject") body.reason = prompt("Reason for rejection?") || "";
  try {
    await api(`/api/jobs/${jobId}/${action}`, { method: "POST", body: JSON.stringify(body) });
    refresh();
  } catch (e) { alert(action + " failed: " + e.message); }
}

async function showAudit(jobId) {
  try {
    const events = await api(`/api/jobs/${jobId}/events`);
    $("audit-job").textContent = jobId;
    $("audit-body").textContent = events.length
      ? events.map(ev => `${ev.created_at}  ${ev.event}  by ${ev.actor_id || "-"} (${ev.actor_role || "-"})  ${JSON.stringify(ev.detail || {})}`).join("\\n")
      : "No audit events.";
    $("audit-panel").style.display = "block";
  } catch (e) { alert("audit fetch failed: " + e.message); }
}

refresh();
setInterval(refresh, 5000);
</script>
</body>
</html>
"""
