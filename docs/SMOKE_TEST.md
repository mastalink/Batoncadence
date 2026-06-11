# Cross-Vendor Live Smoke Test

`scripts/smoke_crossvendor.py` proves the marketed claim against **real**
platform instances — no mocks:

> Dynatrace's AI detects a problem → a BatonCadence agent investigates it
> with Drumline shared memory → a human approves the ITSM write → a real
> ServiceNow incident is created and resolved → the Dynatrace problem is
> closed → every step lands in the immutable audit trail.

Neither platform can do this alone. Dynatrace→ServiceNow event forwarding
exists, but a *governed AI agent* in the middle — with approval gates,
collective memory, and an append-only audit chain — is the part that's new.
That's the demo.

---

## 1. Free accounts (both genuinely free)

### ServiceNow Personal Developer Instance (PDI) — free forever*

1. Go to **developer.servicenow.com** → *Sign up and Start Building*.
2. Create a developer account (any email works; no credit card).
3. After verifying, click **Request Instance** and pick the latest release.
4. ~10 minutes later you get a full real instance:
   `https://devXXXXXX.service-now.com` plus an `admin` password.
5. *Keep it alive:* PDIs hibernate after ~30 min idle (wake via the
   developer portal) and are reclaimed after ~10 days of inactivity —
   log in occasionally.

Credentials to configure (use `mco setup` to put them in the encrypted
store, or `.env` for a quick test):

```
SERVICENOW_INSTANCE_URL=https://devXXXXXX.service-now.com
SERVICENOW_USERNAME=admin
SERVICENOW_PASSWORD=<the PDI admin password>
```

### Dynatrace SaaS trial — free 15 days, no credit card

1. Go to **dynatrace.com/trial** → sign up with email.
2. You get a real SaaS environment: `https://abc12345.apps.dynatrace.com`
   (the classic `https://abc12345.live.dynatrace.com` URL also works for
   the API).
3. Create an API token: **Settings (gear) → Access tokens → Generate new
   token**, with scopes **`problems.read`** and **`problems.write`**.
4. Optional but worth it: install OneAgent on any VM (one command shown in
   the UI) so Davis can detect *real* problems. Easiest real problem on
   demand: install OneAgent on a throwaway VM, then stop a monitored
   process or saturate CPU (`stress-ng --cpu 8`) — Davis opens a problem
   in a few minutes.

```
DYNATRACE_BASE_URL=https://abc12345.live.dynatrace.com
DYNATRACE_API_TOKEN=dt0c01.XXXX...
```

> **No Dynatrace yet?** The smoke test still runs: it injects a
> Dynatrace-format problem notification through the gateway's real webhook
> endpoint (clearly labeled `[SIM]` in the output). The ServiceNow half is
> live either way. Set `MCO_WEBHOOK_SECRET=<any-long-random-string>` to
> enable the webhook path.

---

## 2. Run it

```powershell
# Terminal 1 — the gateway (connectors load from your config)
.venv\Scripts\python.exe -m mco.cli serve

# Terminal 2 — the smoke test
.venv\Scripts\python.exe scripts\smoke_crossvendor.py
```

Useful switches:

| Env var | Effect |
|---|---|
| `MCO_SMOKE_MANUAL_APPROVE=1` | The script pauses at the approval gate until you click **Approve** in the console GUI — the money shot for a recording. |
| `MCO_SMOKE_REAL_AGENT=1` | Movement II investigation is done by the **real `claude` CLI** (frontier model in the loop), fed the Dynatrace problem + Drumline memory + the similar-tickets/KB findings. Falls back to a scripted root cause if the CLI is missing. |
| `MCO_SMOKE_TOKEN` | Approver token to use (defaults to `MCO_LOCAL_TOKEN` from `.env`). |
| `MCO_SMOKE_GATEWAY` | Gateway URL (default `http://127.0.0.1:18789`). |

**The story the movements tell** is the recurring-incident pain: 60–80% of
incidents are repeats, and the fixes are buried in closed tickets and KB
articles nobody re-reads (the Known Error Database nobody maintains).
Movement II digs that institutional memory up — `search_similar_incidents`
returns prior close notes, `search_kb` returns published articles, Drumline
returns what the agents themselves learned. Movement VI is the payoff: a
recurrence arrives and its ticket is **born with the known fix attached**,
matched to the incident this very run resolved, urgency already downgraded.
First incident: hours. Recurrence: seconds. The product gets more valuable
every week it runs — that's the flywheel a pilot turns into a contract.

What "passed" means: a real incident was created **and resolved** in your
PDI (the script prints the deep link and verifies `state=6` by reading it
back), and the audit chains print for every job. The resolved incident
sitting in ServiceNow *is* the evidence.

---

## 3. Record it (the launch asset)

Best setup on Windows — two layers:

**A. The terminal narrative (the script output):**
1. `winget install asciinema.asciinema` *(or in WSL: `sudo apt install asciinema`)*
2. `asciinema rec batoncadence-crossvendor.cast` → run the smoke test → `exit`.
3. Render to a sharable GIF/MP4: `agg batoncadence-crossvendor.cast demo.gif`
   (`cargo install agg` or grab the release binary). asciinema.org hosting
   also gives you an embeddable player for the website.

**B. The full screen story (for the video):** use **OBS Studio** (free)
with a single Display Capture scene, recording at 1080p:

1. Left half: the terminal running the smoke test with
   `MCO_SMOKE_MANUAL_APPROVE=1`.
2. Right half: the browser with two tabs — the BatonCadence console
   (Approvals inbox) and the ServiceNow incident list
   (`https://devXXXXXX.service-now.com/now/nav/ui/classic/params/target/incident_list.do`).
3. The recording beats: script pauses at the gate → you click **Approve**
   in the console → the incident pops into the ServiceNow list → script
   resolves it → refresh shows **Resolved** → audit chain prints.
4. Trim in Clipchamp (built into Windows 11); keep it under 2:30.

That 2-minute clip is the README hero, the Show HN comment, and the
pilot-pitch opener — one recording, three uses.

---

## 4. What this proves vs. what the unit tests prove

| Layer | Proven by |
|---|---|
| We speak the documented APIs correctly (paths, verbs, auth, parsing) | `tests/test_connectors.py` (offline, `httpx.MockTransport`) |
| A live instance accepts our writes (ACLs, state codes, required fields) | **this smoke test** |
| The governed lifecycle (gate → approve → lease → execute → audit) | both — the smoke test exercises it against the real gateway |

If the smoke test fails on your instance (e.g. a customized incident state
model rejects `state=6`), that's the test doing its job — fix the values in
`src/mco/connectors/servicenow.py` and re-run.
