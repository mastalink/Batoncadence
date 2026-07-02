// Baton — Agent Fleet + Settings screens.
const { useState: useStateO, useEffect: useEffectO } = React;

// ----- Register agent panel -----
function RegisterAgentPanel({ tone, advanced, onDone, onCancel }) {
  const store = window.BatonStore;
  const [instanceId, setInstanceId] = useStateO("");
  const [role, setRole] = useStateO("");
  const [org, setOrg] = useStateO("");
  const [busy, setBusy] = useStateO(false);
  const [err, setErr] = useStateO(null);
  const [result, setResult] = useStateO(null); // { agent, token }
  const [copied, setCopied] = useStateO(false);
  const inputStyle = { border: "1px solid var(--border-strong)", borderRadius: 8, padding: "7px 12px", fontSize: 13, fontFamily: "var(--font-mono)", width: 240, background: "var(--surface)", color: "var(--text)" };

  async function submit() {
    setBusy(true); setErr(null);
    try {
      const payload = { instance_id: instanceId.trim(), role: role.trim() };
      if (advanced && org.trim()) payload.org = org.trim();
      const res = await store.registerAgent(payload);
      setResult(res);
      if (onDone) onDone();
    } catch (e) { setErr(e.message); }
    setBusy(false);
  }

  function copyToken() {
    if (!result || !result.token) return;
    navigator.clipboard.writeText(result.token).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1600);
    });
  }

  return (
    <Card style={{ marginBottom: 16 }}>
      <SectionTitle>{tone === "plain" ? "Add a new agent" : "Register agent"}</SectionTitle>
      {result ? (
        <div>
          <p style={{ fontSize: 12.5, color: "var(--text-2)", margin: "0 0 10px" }}>
            {tone === "plain"
              ? `"${result.agent.instance_id}" is registered.`
              : `Agent "${result.agent.instance_id}" registered with role "${result.agent.role}".`}
          </p>
          <div style={{
            display: "flex", alignItems: "center", gap: 10, padding: "10px 12px",
            background: "var(--surface-2)", border: "1px solid var(--st-approval-dot)", borderRadius: 8,
          }}>
            <Mono style={{ fontSize: 12.5, color: "var(--text)", flex: 1, wordBreak: "break-all" }}>{result.token}</Mono>
            <Btn small onClick={copyToken}>{copied ? "Copied" : "Copy"}</Btn>
          </div>
          <p style={{ fontSize: 12, color: "var(--st-failed-fg)", fontWeight: 600, margin: "8px 0 0" }}>
            {tone === "plain" ? "Copy this now — you won't see it again." : "This token is shown once — store it now."}
          </p>
          <div style={{ paddingTop: 14 }}>
            <Btn onClick={onCancel}>{tone === "plain" ? "Done" : "Close"}</Btn>
          </div>
        </div>
      ) : (
        <div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 12, alignItems: "flex-end" }}>
            <div>
              <div style={{ fontSize: 11.5, color: "var(--text-3)", marginBottom: 4 }}>Instance ID</div>
              <input value={instanceId} onChange={(e) => setInstanceId(e.target.value)} placeholder="e.g. claude-worker-3" style={inputStyle} />
            </div>
            <div>
              <div style={{ fontSize: 11.5, color: "var(--text-3)", marginBottom: 4 }}>Role</div>
              <input value={role} onChange={(e) => setRole(e.target.value)} placeholder="e.g. claude" style={inputStyle} />
            </div>
            {advanced ? (
              <div>
                <div style={{ fontSize: 11.5, color: "var(--text-3)", marginBottom: 4 }}>Org (optional)</div>
                <input value={org} onChange={(e) => setOrg(e.target.value)} placeholder="default" style={inputStyle} />
              </div>
            ) : null}
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 12, paddingTop: 14 }}>
            <Btn kind="primary" disabled={busy || !instanceId.trim() || !role.trim()} onClick={submit}>
              {busy ? (tone === "plain" ? "Adding…" : "Registering…") : (tone === "plain" ? "Add agent" : "Register")}
            </Btn>
            <Btn onClick={onCancel}>Cancel</Btn>
            {err ? <span style={{ fontSize: 12.5, color: "var(--st-failed-fg)" }}>{err}</span> : null}
          </div>
        </div>
      )}
    </Card>
  );
}

// ----- Per-agent row admin actions (live only) -----
function AgentRowActions({ agent, tone }) {
  const store = window.BatonStore;
  const [busy, setBusy] = useStateO(false);
  const [reset, setReset] = useStateO(null); // { token } | { error }
  const [err, setErr] = useStateO(null);

  async function doReset() {
    const msg = tone === "plain"
      ? `Give "${agent.instance_id}" a brand new token? The old one stops working right away.`
      : `Reset token for "${agent.instance_id}"? The current token is invalidated immediately.`;
    if (!window.confirm(msg)) return;
    setBusy(true); setErr(null);
    try {
      const res = await store.resetToken(agent.instance_id);
      setReset(res);
    } catch (e) { setErr(e.message); }
    setBusy(false);
  }

  async function doDelete() {
    if (!window.confirm(`This agent's token stops working immediately. Remove ${agent.instance_id}?`)) return;
    setBusy(true); setErr(null);
    try { await store.deleteAgent(agent.instance_id); }
    catch (e) { setErr(e.message); setBusy(false); }
  }

  return (
    <div>
      <div style={{ display: "flex", alignItems: "center", gap: 6, marginTop: 4, paddingLeft: 16 }}>
        <Btn small kind="ghost" disabled={busy} onClick={doReset} style={{ fontSize: 11.5, padding: "3px 8px", color: "var(--text-3)" }}>
          {tone === "plain" ? "New token" : "Reset token"}
        </Btn>
        <Btn small kind="ghost" disabled={busy} onClick={doDelete} style={{ fontSize: 11.5, padding: "3px 8px", color: "var(--text-3)" }}>
          {tone === "plain" ? "Remove" : "Remove"}
        </Btn>
      </div>
      {err ? <div style={{ fontSize: 11.5, color: "var(--st-failed-fg)", paddingLeft: 16, marginTop: 4 }}>{err}</div> : null}
      {reset && reset.token ? (
        <div style={{
          display: "flex", alignItems: "center", gap: 8, margin: "6px 0 0 16px", padding: "8px 10px",
          background: "var(--surface-2)", border: "1px solid var(--st-approval-dot)", borderRadius: 8,
        }}>
          <Mono style={{ fontSize: 11.5, color: "var(--text)", flex: 1, wordBreak: "break-all" }}>{reset.token}</Mono>
          <Btn small onClick={() => navigator.clipboard.writeText(reset.token)}>Copy</Btn>
          <span style={{ fontSize: 11, color: "var(--st-failed-fg)", fontWeight: 600, whiteSpace: "nowrap" }}>
            {tone === "plain" ? "Won't show again" : "Shown once"}
          </span>
        </div>
      ) : null}
    </div>
  );
}

function AgentFleet({ agents, jobs, tone, advanced }) {
  const store = window.BatonStore;
  const live = (store.mode ? store.mode() : "demo") === "live";
  const [showRegister, setShowRegister] = useStateO(false);
  const byRole = {};
  agents.forEach((a) => { (byRole[a.role] = byRole[a.role] || []).push(a); });

  const workingOn = (a) => jobs.find((j) => j.leased_by_instance_id === a.instance_id && ["leased", "in_progress"].includes(j.status));
  const doneBy = (a) => jobs.filter((j) => j.leased_by_instance_id === a.instance_id && j.status === "completed").length;

  return (
    <div>
      <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 16, marginBottom: 16 }}>
        <p style={{ margin: 0, color: "var(--text-2)", fontSize: 13.5, maxWidth: 560 }}>
          {tone === "plain"
            ? "Every machine or program signed up to do work shows up here, grouped by what it can do."
            : "Registered agent instances from agent_registry, grouped by role, with live presence heartbeats."}
        </p>
        {live ? (
          <Btn kind="primary" small onClick={() => setShowRegister((v) => !v)}>
            {showRegister ? "Cancel" : (tone === "plain" ? "Add agent" : "Register agent")}
          </Btn>
        ) : null}
      </div>

      {live && showRegister ? (
        <RegisterAgentPanel tone={tone} advanced={advanced}
          onDone={() => { /* keep panel open to show the token */ }}
          onCancel={() => setShowRegister(false)} />
      ) : null}

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(310px, 1fr))", gap: 16 }}>
        {Object.entries(byRole).map(([role, list]) => (
          <Card key={role} pad={false}>
            <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "14px 16px", borderBottom: "1px solid var(--border)", background: "var(--surface-2)" }}>
              <RoleChip role={role} size={26} />
              <div style={{ flex: 1 }}>
                <div style={{ fontWeight: 650, fontSize: 14 }}>{role}</div>
                <div style={{ fontSize: 11.5, color: "var(--text-3)" }}>{list.filter((a) => a.status === "online").length} of {list.length} online</div>
              </div>
            </div>
            {list.map((a, i) => {
              const job = workingOn(a);
              return (
                <div key={a.instance_id} style={{ padding: "11px 16px", borderBottom: i < list.length - 1 ? "1px solid var(--border)" : "none" }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                    <span style={{
                      width: 8, height: 8, borderRadius: 99, flex: "none",
                      background: a.status === "online" ? "var(--st-done-dot)" : "var(--st-rejected-dot)",
                      animation: a.status === "online" ? "baton-pulse 2.2s ease-in-out infinite" : "none",
                    }}></span>
                    <Mono style={{ fontWeight: 600, color: "var(--text)", fontSize: 13 }}>{a.instance_id}</Mono>
                    <span style={{ flex: 1 }}></span>
                    <span style={{ fontSize: 11.5, color: "var(--text-3)" }}>{a.status === "online" ? "seen " + timeAgo(a.last_seen_at) : "last seen " + timeAgo(a.last_seen_at)}</span>
                  </div>
                  <div style={{ fontSize: 12.5, color: "var(--text-2)", marginTop: 4, paddingLeft: 16 }}>
                    {job
                      ? <span>{tone === "plain" ? "Working on: " : "Executing: "}<b>{job.title}</b></span>
                      : a.status === "online"
                        ? <span style={{ color: "var(--text-3)" }}>{tone === "plain" ? "Idle — waiting for work" : "Idle — polling job board"}</span>
                        : <span style={{ color: "var(--text-3)" }}>{tone === "plain" ? "Not connected" : "No heartbeat"}</span>}
                    {advanced ? <span style={{ color: "var(--text-3)" }}> · {doneBy(a)} completed</span> : null}
                  </div>
                  {live ? <AgentRowActions agent={a} tone={tone} /> : null}
                </div>
              );
            })}
          </Card>
        ))}
      </div>
    </div>
  );
}

// ----- Settings -----
function SettingRow({ title, body, control }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 16, padding: "14px 0", borderBottom: "1px solid var(--border)" }}>
      <div style={{ flex: 1 }}>
        <div style={{ fontWeight: 600, fontSize: 13.5 }}>{title}</div>
        <div style={{ fontSize: 12.5, color: "var(--text-2)", marginTop: 2, maxWidth: 480 }}>{body}</div>
      </div>
      <div style={{ flex: "none" }}>{control}</div>
    </div>
  );
}

function Toggle({ on, onChange }) {
  return (
    <button onClick={() => onChange(!on)} aria-pressed={on} style={{
      width: 38, height: 22, borderRadius: 99, border: "none", cursor: "pointer", position: "relative",
      background: on ? "var(--accent)" : "var(--border-strong)", transition: "background .15s",
    }}>
      <span style={{
        position: "absolute", top: 2, left: on ? 18 : 2, width: 18, height: 18, borderRadius: 99,
        background: "#fff", boxShadow: "0 1px 3px rgba(0,0,0,.25)", transition: "left .15s",
      }}></span>
    </button>
  );
}

// Set up enterprise connectors and verify them — the GUI counterpart to the
// terminal `mco setup` wizard. Reads/writes the same whitelisted settings API,
// and the Test button runs the connector's real health() probe server-side.
const CONNECTORS = [
  { name: "servicenow", label: "ServiceNow", fields: ["SERVICENOW_INSTANCE_URL", "SERVICENOW_USERNAME", "SERVICENOW_PASSWORD"] },
  { name: "dynatrace", label: "Dynatrace", fields: ["DYNATRACE_BASE_URL", "DYNATRACE_API_TOKEN"] },
];

function ConnectorsCard({ tone }) {
  const store = window.BatonStore;
  const live = (store.mode ? store.mode() : "demo") === "live";
  const [meta, setMeta] = useStateO(null);   // key -> setting metadata (incl. set/unset)
  const [form, setForm] = useStateO({});       // editable field values
  const [saving, setSaving] = useStateO(false);
  const [saveMsg, setSaveMsg] = useStateO(null);
  const [test, setTest] = useStateO({});       // name -> { busy, ok, detail }
  const [loadErr, setLoadErr] = useStateO(null);
  const [health, setHealth] = useStateO(null);  // name -> { ok, detail } | null on error
  const [sync, setSync] = useStateO({});        // name -> { busy, ok, summary }
  const inputStyle = { border: "1px solid var(--border-strong)", borderRadius: 8, padding: "7px 12px", fontSize: 13, fontFamily: "var(--font-mono)", width: 320, background: "var(--surface)", color: "var(--text)" };

  // Secrets come back as set/unset (never the value), so we keep their inputs
  // blank and only send them when retyped — blank means "leave unchanged".
  const hydrate = (data) => {
    const conn = (data.groups && data.groups.connectors) || [];
    const m = {}, f = {};
    conn.forEach((s) => { m[s.key] = s; f[s.key] = s.type === "secret" ? "" : (s.value || ""); });
    setMeta(m); setForm(f);
  };

  useEffectO(() => {
    if (!live) { setMeta(null); return; }
    let alive = true;
    setLoadErr(null);
    store.getSettings().then((d) => { if (alive) hydrate(d); }).catch((e) => { if (alive) setLoadErr(e.message); });
    return () => { alive = false; };
  }, [live]);

  useEffectO(() => {
    if (!live) { setHealth(null); return; }
    let alive = true;
    store.getIntegrations()
      .then((list) => {
        if (!alive) return;
        const h = {};
        (list || []).forEach((c) => { h[c.name] = c.health || {}; });
        setHealth(h);
      })
      .catch(() => { if (alive) setHealth(null); }); // integrations may need a different scope — hide dots
    return () => { alive = false; };
  }, [live]);

  if (!live) {
    return (
      <Card style={{ marginBottom: 18 }}>
        <SectionTitle>Connectors</SectionTitle>
        <p style={{ fontSize: 12.5, color: "var(--text-2)", margin: "10px 0 0", maxWidth: 520 }}>
          {tone === "plain"
            ? "Connect to your orchestrator above, then set up ServiceNow or Dynatrace and test them right here — no terminal needed."
            : "Connect a live gateway above to configure SERVICENOW_*/DYNATRACE_* and run each connector's health() probe."}
        </p>
      </Card>
    );
  }

  const set = (k, v) => setForm((f) => Object.assign({}, f, { [k]: v }));

  async function save() {
    setSaving(true); setSaveMsg(null);
    const payload = {};
    Object.keys(meta || {}).forEach((k) => {
      const v = form[k] || "";
      if (meta[k].type === "secret") { if (v) payload[k] = v; }  // blank keeps existing
      else payload[k] = v;
    });
    try {
      await store.saveSettings(payload);
      hydrate(await store.getSettings());
      setSaveMsg({ ok: true, text: "Saved." });
    } catch (e) { setSaveMsg({ ok: false, text: e.message }); }
    setSaving(false);
  }

  async function runTest(name) {
    setTest((t) => Object.assign({}, t, { [name]: { busy: true } }));
    try {
      const r = await store.testConnector(name);
      setTest((t) => Object.assign({}, t, { [name]: { busy: false, ok: !!r.ok, detail: r.detail || "" } }));
    } catch (e) {
      setTest((t) => Object.assign({}, t, { [name]: { busy: false, ok: false, detail: e.message } }));
    }
  }

  function summarize(r) {
    if (r && typeof r === "object") {
      if (r.created != null || r.updated != null || r.count != null) {
        const parts = [];
        if (r.created != null) parts.push((Array.isArray(r.created) ? r.created.length : r.created) + " created");
        if (r.updated != null) parts.push((Array.isArray(r.updated) ? r.updated.length : r.updated) + " updated");
        if (r.skipped != null) parts.push((Array.isArray(r.skipped) ? r.skipped.length : r.skipped) + " skipped");
        if (r.count != null && !parts.length) parts.push(r.count + " items");
        if (parts.length) return parts.join(", ");
      }
    }
    const s = JSON.stringify(r);
    return s && s.length > 80 ? s.slice(0, 80) + "…" : (s || "done");
  }

  async function runSync(name) {
    setSync((s) => Object.assign({}, s, { [name]: { busy: true } }));
    try {
      const r = await store.syncConnector(name);
      setSync((s) => Object.assign({}, s, { [name]: { busy: false, ok: true, summary: summarize(r) } }));
    } catch (e) {
      setSync((s) => Object.assign({}, s, { [name]: { busy: false, ok: false, summary: e.message } }));
    }
  }

  return (
    <Card style={{ marginBottom: 18 }}>
      <SectionTitle>Connectors</SectionTitle>
      {!meta && !loadErr ? <p style={{ fontSize: 12.5, color: "var(--text-3)", margin: "10px 0 0" }}>Loading…</p> : null}
      {CONNECTORS.map((c) => (
        <div key={c.name} style={{ padding: "14px 0", borderBottom: "1px solid var(--border)" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 7, flex: 1 }}>
              <div style={{ fontWeight: 650, fontSize: 13.5 }}>{c.label}</div>
              {health && health[c.name] ? (
                <span title={health[c.name].detail || ""} style={{ display: "inline-flex", alignItems: "center", gap: 5 }}>
                  <span style={{
                    width: 7, height: 7, borderRadius: 99, flex: "none",
                    background: health[c.name].ok ? "var(--st-done-dot)" : "var(--st-failed-dot)",
                  }}></span>
                  <span style={{ fontSize: 11.5, color: "var(--text-3)" }}>{health[c.name].detail || (health[c.name].ok ? "ok" : "unreachable")}</span>
                </span>
              ) : null}
            </div>
            <Btn small disabled={test[c.name] && test[c.name].busy} onClick={() => runTest(c.name)}>
              {test[c.name] && test[c.name].busy ? "Testing…" : "Test connection"}
            </Btn>
            {live && test[c.name] && test[c.name].ok ? (
              <Btn small disabled={sync[c.name] && sync[c.name].busy} onClick={() => runSync(c.name)}>
                {sync[c.name] && sync[c.name].busy ? "Syncing…" : "Sync now"}
              </Btn>
            ) : null}
          </div>
          {c.fields.map((k) => (meta && meta[k]) ? (
            <div key={k} style={{ display: "flex", alignItems: "center", gap: 12, marginTop: 8 }}>
              <label style={{ flex: 1, fontSize: 12.5, color: "var(--text-2)" }}>{meta[k].label}</label>
              <input value={form[k] || ""} onChange={(e) => set(k, e.target.value)}
                type={meta[k].type === "secret" ? "password" : "text"}
                placeholder={meta[k].type === "secret" ? (meta[k].value ? "•••• set — blank keeps it" : "not set") : (meta[k].placeholder || "")}
                style={inputStyle} />
            </div>
          ) : null)}
          {test[c.name] && !test[c.name].busy ? (
            <div style={{ marginTop: 8, fontSize: 12.5, fontWeight: 600, color: test[c.name].ok ? "var(--st-done-fg)" : "var(--st-failed-fg)" }}>
              {(test[c.name].ok ? "✓ " : "✗ ") + (test[c.name].detail || (test[c.name].ok ? "Connected." : "Not reachable."))}
            </div>
          ) : null}
          {sync[c.name] && !sync[c.name].busy ? (
            <div style={{ marginTop: 6, fontSize: 12, color: sync[c.name].ok ? "var(--st-done-fg)" : "var(--st-failed-fg)" }}>
              {sync[c.name].ok ? "✓ Synced — " + sync[c.name].summary : "✗ " + sync[c.name].summary}
            </div>
          ) : null}
        </div>
      ))}
      <div style={{ display: "flex", alignItems: "center", gap: 12, paddingTop: 14 }}>
        <Btn kind="primary" disabled={saving || !meta} onClick={save}>{saving ? "Saving…" : "Save connectors"}</Btn>
        {saveMsg ? <span style={{ fontSize: 12.5, color: saveMsg.ok ? "var(--st-done-fg)" : "var(--st-failed-fg)" }}>{saveMsg.text}</span> : null}
        {loadErr ? <span style={{ fontSize: 12.5, color: "var(--st-failed-fg)" }}>{loadErr}</span> : null}
      </div>
    </Card>
  );
}

function Settings({ tone, advanced, setAdvanced }) {
  const store = window.BatonStore;
  const conn = store.config ? store.config() : { url: "http://127.0.0.1:18789", token: "" };
  const mode = store.mode ? store.mode() : "demo";
  const [ntfy, setNtfy] = useStateO(true);
  const [approvers, setApprovers] = useStateO("human, admin, operator");
  const [url, setUrl] = useStateO(conn.url || "http://127.0.0.1:18789");
  const [token, setToken] = useStateO(conn.token || "");
  const [busy, setBusy] = useStateO(false);
  const err = store.lastError ? store.lastError() : null;
  const inputStyle = { border: "1px solid var(--border-strong)", borderRadius: 8, padding: "7px 12px", fontSize: 13, fontFamily: "var(--font-mono)", width: 260, background: "var(--surface)", color: "var(--text)" };

  return (
    <div style={{ maxWidth: 720 }}>
      <Card style={{ marginBottom: 18 }}>
        <SectionTitle>Connection</SectionTitle>
        <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "12px 0", borderBottom: "1px solid var(--border)" }}>
          <span style={{
            width: 9, height: 9, borderRadius: 99, flex: "none",
            background: mode === "live" ? "var(--st-done-dot)" : mode === "connecting" ? "var(--st-waiting-dot)" : "var(--st-approval-dot)",
            animation: mode !== "demo" ? "baton-pulse 1.6s infinite" : "none",
          }}></span>
          <div style={{ flex: 1 }}>
            <div style={{ fontWeight: 600, fontSize: 13.5 }}>
              {mode === "live" ? "Live — connected to your orchestrator" : mode === "connecting" ? "Connecting…" : "Demo mode — simulated data"}
            </div>
            <div style={{ fontSize: 12.5, color: "var(--text-2)", marginTop: 2 }}>
              {mode === "live"
                ? (tone === "plain" ? "Everything you see is real, updating live. Actions affect real jobs." : "Live events via /ws/broadcast, with /api polling as fallback, using your bearer token.")
                : (tone === "plain" ? "Connect to your running server to see real jobs and agents." : "Point this console at a running `mco serve` gateway to go live.")}
            </div>
          </div>
          {mode === "live" ? <Btn small kind="danger" onClick={() => store.disconnect()}>Disconnect</Btn> : null}
        </div>
        <SettingRow
          title="Gateway URL"
          body={tone === "plain" ? "Where your orchestrator server is running." : "The mco serve REST endpoint (default http://127.0.0.1:18789)."}
          control={<input value={url} onChange={(e) => setUrl(e.target.value)} disabled={mode === "live"} style={inputStyle} />} />
        <SettingRow
          title="Agent token"
          body={tone === "plain" ? "Proves it's you. Use an approver token to decide approval gates." : "Bearer token from `mco register`. Approver role (human/admin/operator) required for approve/reject."}
          control={<input value={token} onChange={(e) => setToken(e.target.value)} disabled={mode === "live"} type="password" placeholder="paste token…" style={inputStyle} />} />
        {mode !== "live" ? (
          <div style={{ display: "flex", alignItems: "center", gap: 12, paddingTop: 14 }}>
            <Btn kind="primary" disabled={busy || !url.trim() || !token.trim()} onClick={async () => {
              setBusy(true);
              await store.connect(url, token);
              setBusy(false);
            }}>{busy ? "Connecting…" : "Connect"}</Btn>
            {err ? <span style={{ fontSize: 12.5, color: "var(--st-failed-fg)" }}>{err}</span>
              : <span style={{ fontSize: 12.5, color: "var(--text-3)" }}>{tone === "plain" ? "Nothing breaks if it fails — you stay in demo mode." : "Connection is verified against GET /api/agents before switching."}</span>}
          </div>
        ) : err ? <div style={{ paddingTop: 12, fontSize: 12.5, color: "var(--st-failed-fg)" }}>Last poll error: {err}</div> : null}
      </Card>

      <Card style={{ marginBottom: 18 }}>
        <SectionTitle>Experience</SectionTitle>
        <SettingRow
          title="Advanced mode"
          body={tone === "plain" ? "Show the technical layer: raw IDs, payloads, retry budgets, and YAML." : "Expose payload JSON, full UUIDs, retry/escalation config, and workflow YAML."}
          control={<Toggle on={advanced} onChange={setAdvanced} />} />
        <SettingRow
          title="Desktop notifications (ntfy)"
          body="Push alerts when a job needs approval, completes, or fails. Uses your configured ntfy.sh topic."
          control={<Toggle on={ntfy} onChange={setNtfy} />} />
      </Card>

      <Card style={{ marginBottom: 18 }}>
        <SectionTitle>Access</SectionTitle>
        <SettingRow
          title="Approver roles"
          body={tone === "plain" ? "Which kinds of users are allowed to approve paused jobs." : "MCO_APPROVER_ROLES — comma-separated, case-insensitive."}
          control={<input value={approvers} onChange={(e) => setApprovers(e.target.value)} style={inputStyle} />} />
      </Card>

      <ConnectorsCard tone={tone} />

      {advanced ? (
        <Card>
          <SectionTitle>Environment</SectionTitle>
          <SettingRow title="Profile" body="Environment profile chosen during `mco setup`." control={<Mono style={{ fontSize: 12.5 }}>Hybrid</Mono>} />
          <SettingRow title="Secret store" body="AES-256-GCM envelope at ~/.mco/secrets.enc, unlocked via Windows Credential Manager."
            control={<span style={{ fontSize: 12, fontWeight: 600, color: "var(--st-done-fg)", background: "var(--st-done-bg)", padding: "3px 10px", borderRadius: 999 }}>Unlocked</span>} />
        </Card>
      ) : (
        <p style={{ fontSize: 12.5, color: "var(--text-3)" }}>Turn on Advanced mode to see environment details.</p>
      )}
    </div>
  );
}

Object.assign(window, { AgentFleet, Settings, Toggle, SettingRow, ConnectorsCard });
