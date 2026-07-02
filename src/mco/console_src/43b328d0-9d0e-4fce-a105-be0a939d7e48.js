// Baton — Overview (mission control) + Approvals inbox.
const { useState: useStateH, useMemo: useMemoH } = React;

// ----- Overview -----
function StatCard({ label, value, sub, kind, onClick }) {
  return (
    <button onClick={onClick} style={{
      textAlign: "left", background: "var(--surface)", border: "1px solid var(--border)",
      borderRadius: "var(--radius-l)", boxShadow: "var(--shadow-s)", padding: "var(--card-pad)",
      cursor: onClick ? "pointer" : "default", display: "block", width: "100%",
      transition: "border-color .12s, box-shadow .12s",
    }}
      onMouseEnter={(e) => { if (onClick) e.currentTarget.style.boxShadow = "var(--shadow-m)"; }}
      onMouseLeave={(e) => e.currentTarget.style.boxShadow = "var(--shadow-s)"}>
      <div style={{ fontSize: 12.5, fontWeight: 600, color: "var(--text-3)", display: "flex", alignItems: "center", gap: 7 }}>
        {kind ? <span style={{ width: 8, height: 8, borderRadius: 99, background: `var(--st-${kind}-dot)` }}></span> : null}
        {label}
      </div>
      <div style={{ fontSize: 30, fontWeight: 650, letterSpacing: "-0.02em", margin: "6px 0 2px", fontVariantNumeric: "tabular-nums" }}>{value}</div>
      <div style={{ fontSize: 12.5, color: "var(--text-3)" }}>{sub}</div>
    </button>
  );
}

function WorkflowStrip({ jobs, tone, onOpen }) {
  // Group jobs by workflow, show each as a stepper
  const groups = useMemoH(() => {
    const g = {};
    jobs.forEach((j) => { if (j.workflow) (g[j.workflow] = g[j.workflow] || []).push(j); });
    return Object.entries(g).map(([name, list]) => {
      // order by dependency depth: roots first, then their dependents
      const depth = {};
      const d = (id, seen) => {
        if (depth[id] != null) return depth[id];
        if (seen.has(id)) return 0;
        seen.add(id);
        const job = list.find((x) => x.id === id);
        if (!job) return 0;
        const deps = (job.depends_on || []).filter((x) => list.some((y) => y.id === x));
        depth[id] = deps.length ? 1 + Math.max(...deps.map((x) => d(x, seen))) : 0;
        return depth[id];
      };
      list.forEach((j) => d(j.id, new Set()));
      const sorted = list.slice().sort((a, b) => (depth[a.id] || 0) - (depth[b.id] || 0));
      return { name, steps: sorted };
    });
  }, [jobs]);
  if (!groups.length) return null;

  return groups.map((g) => (
    <Card key={g.name} style={{ marginBottom: 14 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 14 }}>
        <div style={{ fontWeight: 650, fontSize: 14.5 }}>{g.name}</div>
        <span style={{ fontSize: 12, color: "var(--text-3)" }}>{g.steps.filter((s) => s.status === "completed").length} of {g.steps.length} steps done</span>
      </div>
      <div style={{ display: "flex", alignItems: "stretch", gap: 0, overflowX: "auto", paddingBottom: 2 }}>
        {g.steps.map((s, i) => (
          <React.Fragment key={s.id}>
            {i > 0 ? <div style={{ alignSelf: "center", width: 26, flex: "none", height: 2, background: s.status === "waiting" ? "var(--border)" : "var(--st-done-dot)", opacity: s.status === "waiting" ? 1 : 0.5 }}></div> : null}
            <button onClick={() => onOpen(s.id)} style={{
              flex: "1 0 150px", minWidth: 150, textAlign: "left", cursor: "pointer",
              background: s.status === "in_progress" ? "var(--accent-soft)" : "var(--surface-2)",
              border: s.status === "in_progress" ? "1.5px solid var(--accent)" : "1px solid var(--border)",
              borderRadius: "var(--radius-m)", padding: "10px 12px",
            }}>
              <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 6 }}>
                <RoleChip role={s.target_agent_role} size={18} />
                <StatusBadge status={s.status} tone={tone} />
              </div>
              <div style={{ fontSize: 12.5, fontWeight: 600, lineHeight: 1.3 }}>{s.title}</div>
              {s.requires_approval && (s.status === "waiting" || s.status === "needs_approval") ? (
                <div style={{ fontSize: 11, color: "var(--st-approval-fg)", marginTop: 4 }}>⚠ needs a human OK</div>
              ) : null}
            </button>
          </React.Fragment>
        ))}
      </div>
    </Card>
  ));
}

function ActivityFeed({ jobs, tone, onOpen }) {
  const evts = window.BatonStore.getAllEvents(9);
  const titleOf = (jobId) => { const j = jobs.find((x) => x.id === jobId); return j ? j.title : shortId(jobId); };
  return (
    <Card pad={false}>
      <div style={{ padding: "0 4px" }}>
        {evts.map((e, i) => (
          <button key={e.id} onClick={() => onOpen(e.job_id)} style={{
            display: "flex", width: "100%", textAlign: "left", gap: 10, alignItems: "center",
            padding: "9px 14px", background: "transparent", border: "none", cursor: "pointer",
            borderBottom: i < evts.length - 1 ? "1px solid var(--border)" : "none", fontSize: 13,
          }}
            onMouseEnter={(ev) => ev.currentTarget.style.background = "var(--surface-2)"}
            onMouseLeave={(ev) => ev.currentTarget.style.background = "transparent"}>
            <span style={{ width: 8, height: 8, flex: "none", borderRadius: 99, background: `var(--st-${eventKindH(e.event)}-dot)` }}></span>
            <span style={{ flex: 1, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
              <b>{eventLabel(e.event, tone)}</b>
              <span style={{ color: "var(--text-2)" }}> · {titleOf(e.job_id)}</span>
            </span>
            <span style={{ color: "var(--text-3)", fontSize: 11.5, flex: "none" }}>{timeAgo(e.created_at)}</span>
          </button>
        ))}
        {!evts.length ? <EmptyState icon="≡" title="Quiet so far" body="Activity will appear as agents pick up work." /> : null}
      </div>
    </Card>
  );
}
function eventKindH(ev) {
  if (ev === "created") return "pending";
  if (ev === "leased" || ev === "status:in_progress") return "active";
  if (ev === "approved" || ev === "status:completed") return "done";
  if (ev === "rejected" || ev.indexOf("failed") >= 0) return "failed";
  return "waiting";
}

function Overview({ jobs, agents, tone, advanced, onNav, onOpen }) {
  const active = jobs.filter((j) => ["pending", "leased", "in_progress"].includes(j.status)).length;
  const gates = jobs.filter((j) => j.status === "needs_approval").length;
  const doneToday = jobs.filter((j) => j.status === "completed").length;
  const problems = jobs.filter((j) => ["failed"].includes(j.status)).length;
  const online = agents.filter((a) => a.status === "online").length;

  return (
    <div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 14, marginBottom: 22 }}>
        <StatCard label={tone === "plain" ? "Working now" : "Active jobs"} value={active} sub={tone === "plain" ? "jobs moving through the pipeline" : "pending · leased · in progress"} kind="active" onClick={() => onNav("jobs")} />
        <StatCard label={tone === "plain" ? "Needs your OK" : "Approval gates"} value={gates} sub={gates ? (tone === "plain" ? "paused until you decide" : "paused at needs_approval") : "all clear"} kind="approval" onClick={() => onNav("approvals")} />
        <StatCard label={tone === "plain" ? "Finished" : "Completed"} value={doneToday} sub="in the last 24 hours" kind="done" onClick={() => onNav("jobs")} />
        <StatCard label="Agents online" value={online + " / " + agents.length} sub={problems ? problems + (tone === "plain" ? " job needs attention" : " failed job") : "fleet healthy"} kind={problems ? "failed" : "done"} onClick={() => onNav("agents")} />
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1.7fr) minmax(0, 1fr)", gap: 22, alignItems: "start" }}>
        <div>
          <SectionTitle action={<Btn small kind="ghost" onClick={() => onNav("workflows")}>Open builder →</Btn>}>{tone === "plain" ? "Running flows" : "Workflows in flight"}</SectionTitle>
          <WorkflowStrip jobs={jobs} tone={tone} onOpen={onOpen} />
          {gates > 0 ? (
            <div style={{ marginTop: 8 }}>
              <SectionTitle action={<Btn small kind="ghost" onClick={() => onNav("approvals")}>Review all →</Btn>}>{tone === "plain" ? "Waiting on you" : "Approval queue"}</SectionTitle>
              {jobs.filter((j) => j.status === "needs_approval").slice(0, 2).map((j) => (
                <Card key={j.id} style={{ marginBottom: 10, padding: 14 }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                    <RoleChip role={j.target_agent_role} />
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ fontWeight: 600, fontSize: 13.5 }}>{j.title}</div>
                      <div style={{ fontSize: 12, color: "var(--text-3)" }}>from {j.source_agent_id} · {timeAgo(j.created_at)}</div>
                    </div>
                    <Btn kind="ok" small onClick={() => window.BatonStore.approve(j.id, "joe-laptop")}>✓ Approve</Btn>
                    <Btn small onClick={() => onOpen(j.id)}>Review</Btn>
                  </div>
                </Card>
              ))}
            </div>
          ) : null}
        </div>
        <div>
          <SectionTitle>{tone === "plain" ? "What just happened" : "Live activity"}</SectionTitle>
          <ActivityFeed jobs={jobs} tone={tone} onOpen={onOpen} />
        </div>
      </div>
    </div>
  );
}

// ----- Approvals inbox -----
function Approvals({ jobs, tone, advanced, onOpen }) {
  const queue = jobs.filter((j) => j.status === "needs_approval");
  const decided = jobs.filter((j) => j.approved_by && j.status !== "needs_approval").slice(0, 6);
  const [sel, setSel] = useStateH(null);
  const [reason, setReason] = useStateH("");
  const selected = queue.find((j) => j.id === sel) || queue[0];

  return (
    <div>
      <p style={{ margin: "0 0 16px", color: "var(--text-2)", fontSize: 13.5, maxWidth: 560 }}>
        {tone === "plain"
          ? "These jobs are paused and waiting for a person to say go. Nothing runs until you decide."
          : "Jobs flagged requires_approval pause at needs_approval until an approver role decides. Decisions are recorded in the immutable audit trail."}
      </p>
      {queue.length === 0 ? (
        <Card><EmptyState icon="✓" title={tone === "plain" ? "Nothing needs your OK" : "Approval queue is empty"} body="New approval requests will appear here and notify you." /></Card>
      ) : (
        <div style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) minmax(0, 1.4fr)", gap: 18, alignItems: "start" }}>
          <Card pad={false}>
            {queue.map((j) => {
              const isSel = selected && selected.id === j.id;
              return (
                <button key={j.id} onClick={() => { setSel(j.id); setReason(""); }} style={{
                  display: "flex", width: "100%", textAlign: "left", gap: 10, alignItems: "center",
                  padding: "12px 14px", cursor: "pointer", borderLeft: isSel ? "3px solid var(--accent)" : "3px solid transparent",
                  background: isSel ? "var(--accent-soft)" : "transparent", border: "none",
                  borderBottom: "1px solid var(--border)",
                  borderLeftStyle: "solid", borderLeftWidth: 3, borderLeftColor: isSel ? "var(--accent)" : "transparent",
                }}>
                  <RoleChip role={j.target_agent_role} />
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontWeight: 600, fontSize: 13.5, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{j.title}</div>
                    <div style={{ fontSize: 12, color: "var(--text-3)" }}>from {j.source_agent_id} · {timeAgo(j.created_at)}</div>
                  </div>
                </button>
              );
            })}
          </Card>
          {selected ? (
            <Card>
              <div style={{ display: "flex", gap: 8, marginBottom: 10 }}>
                <StatusBadge status="needs_approval" tone={tone} />
                {selected.workflow ? <span style={{ fontSize: 12, color: "var(--text-3)", alignSelf: "center" }}>part of {selected.workflow}</span> : null}
              </div>
              <h2 style={{ margin: "0 0 6px", fontSize: 18, fontWeight: 650, letterSpacing: "-0.01em" }}>{selected.title}</h2>
              <p style={{ margin: "0 0 14px", color: "var(--text-2)", fontSize: 13.5 }}>{selected.description || "No further instructions were attached."}</p>
              <div style={{ display: "flex", gap: 20, fontSize: 13, color: "var(--text-2)", borderTop: "1px solid var(--border)", borderBottom: "1px solid var(--border)", padding: "10px 0", marginBottom: 16 }}>
                <span>Will run on: <b style={{ color: "var(--text)" }}>{selected.target_agent_role}</b></span>
                <span>Requested by: <Mono>{selected.source_agent_id}</Mono></span>
                {advanced ? <span>ID: <Mono>{shortId(selected.id)}</Mono></span> : null}
              </div>
              <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
                <Btn kind="primary" onClick={() => window.BatonStore.approve(selected.id, "joe-laptop")}>✓ Approve &amp; run</Btn>
                <input value={reason} onChange={(e) => setReason(e.target.value)} placeholder={tone === "plain" ? "Reason for saying no…" : "Rejection reason (audited)…"} style={{ flex: 1, minWidth: 160, border: "1px solid var(--border-strong)", borderRadius: 8, padding: "8px 12px", fontSize: 13 }} />
                <Btn kind="danger" onClick={() => window.BatonStore.reject(selected.id, "joe-laptop", reason)}>Reject</Btn>
                <Btn kind="ghost" onClick={() => onOpen(selected.id)}>Full details →</Btn>
              </div>
            </Card>
          ) : null}
        </div>
      )}

      {decided.length ? (
        <div style={{ marginTop: 24 }}>
          <SectionTitle>Recent decisions</SectionTitle>
          <Card pad={false}>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13.5 }}>
              <THead cols={["Job", "Decision", "Decided by", "When"]} />
              <tbody>
                {decided.map((j) => (
                  <tr key={j.id} onClick={() => onOpen(j.id)} style={{ cursor: "pointer" }}
                    onMouseEnter={(e) => e.currentTarget.style.background = "var(--surface-2)"}
                    onMouseLeave={(e) => e.currentTarget.style.background = "transparent"}>
                    <Td><span style={{ fontWeight: 600 }}>{j.title}</span></Td>
                    <Td><StatusBadge status={j.status === "rejected" ? "rejected" : "completed"} tone={tone} /></Td>
                    <Td><Mono>{j.approved_by}</Mono></Td>
                    <Td><span style={{ color: "var(--text-3)", fontSize: 12.5 }}>{timeAgo(j.updated_at)}</span></Td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
        </div>
      ) : null}
    </div>
  );
}

Object.assign(window, { Overview, Approvals, StatCard });
