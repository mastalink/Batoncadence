// BatonCadence — live gateway adapter.
// Wraps the demo store (data.js) in a facade. When connected, all reads/writes
// go to the real MCOrchestr8 REST API:
//   GET  /api/jobs            GET /api/agents       GET /api/jobs/{id}/events
//   POST /api/jobs            POST /api/jobs/{id}/approve|reject
//   PUT  /api/jobs/{id}
// Polls every 4s (same cadence as the built-in /dashboard) and synthesizes
// toasts + an activity feed from status diffs.
(function () {
  const demo = window.BatonStore; // set by data.js (must load first)
  const listeners = new Set();
  const toastFns = new Set();
  let cfg = null;
  try { cfg = JSON.parse(localStorage.getItem("baton_conn") || "null"); } catch (e) { cfg = null; }
  let connState = "demo"; // demo | connecting | live
  let lastError = null;
  let pollTimer = null;

  let jobs = [];
  let agents = [];
  let eventsCache = {};
  let prevStatus = {};
  let liveActivity = []; // synthesized feed: {id, job_id, event, created_at, actor_id, actor_role}

  const isLive = () => connState === "live";
  const emit = () => listeners.forEach((fn) => fn());
  const rid = () => Math.random().toString(36).slice(2);
  const toast = (kind, title, body) => toastFns.forEach((fn) => fn({ id: rid(), kind, title, body }));

  // Re-emit demo store changes while in demo mode
  demo.subscribe(() => { if (!isLive()) emit(); });
  demo.onToast((t) => { if (!isLive()) toastFns.forEach((fn) => fn(t)); });

  async function api(path, opts = {}) {
    const base = (cfg && cfg.url ? cfg.url : "").replace(/\/+$/, "");
    const res = await fetch(base + path, Object.assign({}, opts, {
      headers: Object.assign({
        "Authorization": "Bearer " + ((cfg && cfg.token) || ""),
        "Content-Type": "application/json",
      }, opts.headers || {}),
    }));
    if (!res.ok) {
      let detail = "";
      try { detail = (await res.json()).detail || ""; } catch (e) { /* ignore */ }
      throw new Error("HTTP " + res.status + (detail ? " — " + detail : ""));
    }
    return res.json();
  }

  const TOAST_FOR = {
    completed: ["ok", "Completed"],
    failed: ["err", "Failed"],
    needs_approval: ["approval", "Approval needed"],
    in_progress: ["info", "Started"],
    rejected: ["err", "Rejected"],
  };

  async function poll() {
    try {
      const [j, a] = await Promise.all([api("/api/jobs"), api("/api/agents")]);
      const seenBefore = Object.keys(prevStatus).length > 0;
      (j || []).forEach((job) => {
        const old = prevStatus[job.id];
        if (seenBefore && old !== job.status) {
          liveActivity.unshift({
            id: rid(), job_id: job.id,
            event: old ? "status:" + job.status : "created",
            actor_id: job.leased_by_instance_id || job.source_agent_id, actor_role: job.target_agent_role,
            created_at: new Date().toISOString(),
          });
          const t = old ? TOAST_FOR[job.status] : ["info", "New job"];
          if (t) toast(t[0], t[1], job.title);
          delete eventsCache[job.id]; // refresh audit on next open
        }
        prevStatus[job.id] = job.status;
      });
      liveActivity = liveActivity.slice(0, 50);
      jobs = j || []; agents = a || [];
      if (lastError) { lastError = null; }
      emit();
    } catch (e) {
      lastError = e.message;
      emit();
    }
  }

  function startPolling() {
    if (pollTimer) clearInterval(pollTimer);
    pollTimer = setInterval(poll, 4000);
  }
  function stopPolling() {
    if (pollTimer) clearInterval(pollTimer);
    pollTimer = null;
  }

  const facade = {
    // ---- connection management ----
    mode: () => connState,
    lastError: () => lastError,
    config: () => cfg || { url: (/^https?:$/.test(location.protocol) ? location.origin : "http://127.0.0.1:18789"), token: "" },
    async connect(url, token) {
      cfg = { url: url.trim(), token: token.trim() };
      connState = "connecting"; lastError = null; emit();
      try {
        await api("/api/agents"); // auth + reachability check
        localStorage.setItem("baton_conn", JSON.stringify(cfg));
        demo.stopSim();
        connState = "live";
        jobs = []; agents = []; eventsCache = {}; prevStatus = {}; liveActivity = [];
        await poll();
        startPolling();
        toast("ok", "Live", "Connected to " + cfg.url);
        emit();
        return true;
      } catch (e) {
        connState = "demo"; lastError = e.message;
        toast("err", "Connection failed", e.message);
        emit();
        return false;
      }
    },
    disconnect() {
      stopPolling();
      connState = "demo"; lastError = null;
      localStorage.removeItem("baton_conn");
      toast("info", "Demo mode", "Showing simulated data again.");
      emit();
    },

    // ---- reads ----
    getJobs: () => isLive() ? jobs.slice() : demo.getJobs(),
    getAgents: () => isLive() ? agents.slice() : demo.getAgents(),
    getEvents(jobId) {
      if (!isLive()) return demo.getEvents(jobId);
      if (!eventsCache[jobId]) {
        eventsCache[jobId] = [];
        api("/api/jobs/" + jobId + "/events")
          .then((ev) => { eventsCache[jobId] = ev || []; emit(); })
          .catch(() => { /* leave empty; drawer shows none */ });
      }
      return eventsCache[jobId];
    },
    getAllEvents: (n) => isLive() ? liveActivity.slice(0, n || 12) : demo.getAllEvents(n),

    // ---- writes ----
    async approve(jobId, actor) {
      if (!isLive()) return demo.approve(jobId, actor);
      try { await api("/api/jobs/" + jobId + "/approve", { method: "POST" }); await poll(); }
      catch (e) { toast("err", "Approve failed", e.message); }
    },
    async reject(jobId, actor, reason) {
      if (!isLive()) return demo.reject(jobId, actor, reason);
      try { await api("/api/jobs/" + jobId + "/reject", { method: "POST", body: JSON.stringify({ reason: reason || "" }) }); await poll(); }
      catch (e) { toast("err", "Reject failed", e.message); }
    },
    async retryNow(jobId) {
      if (!isLive()) return demo.retryNow(jobId);
      try { await api("/api/jobs/" + jobId, { method: "PUT", body: JSON.stringify({ status: "pending" }) }); await poll(); toast("ok", "Re-queued", "Job sent back to the board."); }
      catch (e) { toast("err", "Retry failed", e.message + " (the gateway only lets the target role update a job)"); }
    },
    async createJob(payload) {
      if (!isLive()) return demo.createJob(payload);
      try {
        const res = await api("/api/jobs", { method: "POST", body: JSON.stringify(payload) });
        await poll();
        toast(payload.requires_approval ? "approval" : "ok", "Job created", payload.title);
        return res.job;
      } catch (e) { toast("err", "Create failed", e.message); }
    },
    async submitWorkflow(name, steps) {
      if (!isLive()) return demo.submitWorkflow(name, steps);
      // topo order: place steps whose deps are all already submitted
      const remaining = steps.slice();
      const idMap = {};
      try {
        let guard = 0;
        while (remaining.length && guard++ < steps.length + 2) {
          for (let i = remaining.length - 1; i >= 0; i--) {
            const s = remaining[i];
            const deps = (s.depends_on || []);
            if (deps.every((d) => idMap[d])) {
              const res = await api("/api/jobs", {
                method: "POST",
                body: JSON.stringify({
                  title: s.title, description: s.instructions || "", target_agent_role: s.role,
                  depends_on: deps.map((d) => idMap[d]),
                  requires_approval: !!s.requires_approval,
                  max_retries: s.max_retries || 0,
                  escalate_to_role: s.escalate_to_role || null,
                }),
              });
              idMap[s.tmpId] = res.job.id;
              remaining.splice(i, 1);
            }
          }
        }
        await poll();
        toast("ok", "Workflow submitted", name + " — " + steps.length + " steps queued.");
        return idMap;
      } catch (e) { toast("err", "Workflow failed", e.message); return idMap; }
    },

    // ---- settings & connectors (live only) ----
    async getSettings() {
      if (!isLive()) throw new Error("Connect to your orchestrator first.");
      return api("/api/settings");
    },
    async saveSettings(values) {
      if (!isLive()) throw new Error("Connect to your orchestrator first.");
      return api("/api/settings", { method: "PUT", body: JSON.stringify(values) });
    },
    async testConnector(name) {
      if (!isLive()) throw new Error("Connect to your orchestrator first.");
      return api("/api/settings/test-connector", { method: "POST", body: JSON.stringify({ name }) });
    },

    // ---- demo sim controls (no-ops while live) ----
    startSim() { if (!isLive()) demo.startSim(); },
    stopSim() { demo.stopSim(); },

    // ---- pub/sub ----
    subscribe(fn) { listeners.add(fn); return () => listeners.delete(fn); },
    onToast(fn) { toastFns.add(fn); return () => toastFns.delete(fn); },
  };

  window.BatonStore = facade;

  // Auto-reconnect if a saved connection exists
  if (cfg && cfg.url && cfg.token) {
    facade.connect(cfg.url, cfg.token);
  }
})();
