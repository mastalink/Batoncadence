# MCOrchestr8 — Full Setup Guide (Backend + Agents)

This is a complete, share-with-a-friend walkthrough. It takes you from an empty
machine to three AI coding agents (Claude, Codex, Antigravity/Gemini) passing
work to each other through a shared job board.

**What you are building:**

```
              ┌──────────────────────────┐
              │   Supabase (Postgres)    │   <- backend: 2 tables + 1 function
              │  agent_jobs · agent_registry │
              └────────────▲─────────────┘
                           │ REST
              ┌────────────┴─────────────┐
              │   mco serve (gateway)    │   <- FastAPI on 127.0.0.1:18789
              │   REST + WebSocket        │
              └────────────▲─────────────┘
                           │ stdio MCP (mco mcp)
        ┌──────────────────┼───────────────────┐
        │                  │                   │
   ┌────┴────┐        ┌────┴────┐         ┌────┴────┐
   │ Claude  │        │  Codex  │         │Antigravity│
   │ planner │ ─send→ │ builder │ ─send→  │ reviewer │
   └─────────┘        └─────────┘         └────┬────┘
        ▲                                       │
        └───────────── send (fix loop) ─────────┘
```

Each agent runs a small recurring prompt (`/loop`, cron, or scheduled task) that
checks its inbox, leases jobs addressed to it, does the work, and hands off to
the next agent with `mco_send`.

---

## Part 0 — Prerequisites

- **Python 3.9+** (3.11+ recommended)
- A **Supabase** account (free tier is fine) — this is the backend database
- At least one of: Claude Code, Codex CLI, or Antigravity (you can also test with
  just the built-in `mco listen` daemon — no AI app required)
- **Windows** users get passwordless secret unlock via Credential Manager;
  macOS/Linux fall back to an env var or interactive prompt.

---

## Part 1 — Install the package

```bash
# Clone, then:
cd C:/AI/MCOrchestr8      # adjust to wherever you cloned it

python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

pip install -e ".[dev]"
```

Verify the CLI is live:

```bash
mco --help
```

You should see the commands: `setup`, `serve`, `mcp`, `listen`, `status`,
`register`, `agents`.

---

## Part 2 — Backend: create the Supabase database

### 2.1 Create a project
1. Go to https://supabase.com → **New project**.
2. Note your **Project URL** (`https://xxxx.supabase.co`) and the
   **service_role key** (Settings → API). The service_role key is required
   because the gateway writes to tables and calls a SQL function.

### 2.2 Create the schema
Open the Supabase **SQL Editor** and run this. It creates the two tables and the
atomic lease function the gateway depends on.

```sql
-- ── Table: agent_registry ──────────────────────────────────────────────
-- One row per agent instance. The token is stored only as a SHA-256 hash.
create table if not exists agent_registry (
  instance_id     text primary key,
  role            text not null,
  status          text not null default 'offline',
  last_seen_at    timestamptz default now(),
  auth_token_hash text not null
);

-- ── Table: agent_jobs ──────────────────────────────────────────────────
-- The job board / dropbox. Every message between agents is a row here.
create table if not exists agent_jobs (
  id                    uuid primary key default gen_random_uuid(),
  title                 text not null,
  description           text,
  source_agent_id       text,
  source_agent_role     text,
  target_agent_role     text not null,
  target_agent_id       text,            -- null = addressed to whole role
  status                text not null default 'pending',
  leased_by_instance_id text,
  depends_on            text[] default '{}',
  input_payload         jsonb default '{}'::jsonb,   -- {"prompt": "..."} lives here
  output_payload        jsonb default '{}'::jsonb,   -- {"result": "..."} on complete
  created_at            timestamptz default now(),
  started_at            timestamptz,
  completed_at          timestamptz,
  error_message         text
);

create index if not exists idx_agent_jobs_target
  on agent_jobs (target_agent_role, status);

-- ── Function: lease_task ───────────────────────────────────────────────
-- Atomic claim. Returns true only if THIS caller won the race for the job.
-- Prevents two agents from running the same task.
create or replace function lease_task(p_agent_instance_id text, p_task_id text)
returns boolean
language plpgsql
as $$
declare
  rows_affected int;
begin
  update agent_jobs
     set status = 'leased',
         leased_by_instance_id = p_agent_instance_id,
         started_at = now()
   where id = p_task_id::uuid
     and status = 'pending'
     and leased_by_instance_id is null;
  get diagnostics rows_affected = row_count;
  return rows_affected > 0;
end;
$$;
```

> **Status lifecycle:** `waiting` (blocked by `depends_on`) → `pending` (ready) →
> `leased` → `in_progress` → `completed` / `failed`.

---

## Part 3 — Configure the gateway

Run the interactive wizard. It stores your Supabase URL/key in an encrypted
secret store (`~/.mco/secrets.enc`, AES-256-GCM) — **not** in plaintext.

```bash
mco setup
```

Choose:
- **Profile**: pick **Hybrid** (or Cloud-Heavy) so it asks for Supabase.
- Paste your **Project URL** and **service_role key**.
- Opt in to **encrypt credentials** and (Windows) **Credential Manager** so the
  gateway can auto-unlock on reboot with no password.

Confirm everything resolved:

```bash
mco status
```

You should see `SUPABASE_URL` and `SUPABASE_KEY` as `[ENCRYPTED]` and the secret
store as unlocked.

---

## Part 4 — Start the gateway

```bash
mco serve
```

This serves the REST + WebSocket API at **http://127.0.0.1:18789**. Leave it
running in its own terminal. Quick smoke test from another terminal:

```bash
curl http://127.0.0.1:18789/api/agents
# -> [] (empty list until you register agents) — a 200 means the backend works
```

---

## Part 5 — Register each agent (get tokens)

Every agent authenticates with a bearer token. Registering creates the
`agent_registry` row and prints the token **once**. Re-running rotates it.

```bash
mco register --name coding-beast-claude   --role claude
mco register --name coding-beast-codex    --role codex
mco register --name coding-beast-gemini   --role antigravity
```

Copy each `mco_tok_...` somewhere safe. List what's registered any time:

```bash
mco agents
```

> The `role` is how jobs are addressed (`mco_send(to_role="codex", ...)`); the
> `instance` (`--name`) is the specific worker. A job to a role with no
> `target_agent_id` can be leased by any instance of that role.

---

## Part 6 — Wire each AI app to the dropbox (MCP)

Each app talks to the gateway through the bundled **`mco mcp`** stdio server. It
exposes six tools: `mco_inbox`, `mco_lease`, `mco_complete`, `mco_fail`,
`mco_send`, `mco_agents`.

Replace `mco_tok_REPLACE_ME` with the real token from Part 5 in each file.
Adjust the path to `mco.exe` (Windows) / `mco` (Unix) to your `.venv`.

### Claude Code
Create `.mcp.json` in your project root:

```json
{
  "mcpServers": {
    "mco": {
      "command": "C:/AI/MCOrchestr8/.venv/Scripts/mco.exe",
      "args": ["mcp"],
      "env": {
        "MCO_GATEWAY_URL": "http://127.0.0.1:18789",
        "MCO_AGENT_TOKEN": "mco_tok_REPLACE_ME",
        "AGENT_ROLE": "claude",
        "AGENT_INSTANCE_ID": "coding-beast-claude"
      }
    }
  }
}
```

Or: `claude mcp add mco -- C:/AI/MCOrchestr8/.venv/Scripts/mco.exe mcp` then set
the four env vars.

### Codex
Append to `~/.codex/config.toml`:

```toml
[mcp_servers.mco]
command = "C:/AI/MCOrchestr8/.venv/Scripts/mco.exe"
args = ["mcp"]
env = { MCO_GATEWAY_URL = "http://127.0.0.1:18789", MCO_AGENT_TOKEN = "mco_tok_REPLACE_ME", AGENT_ROLE = "codex", AGENT_INSTANCE_ID = "coding-beast-codex" }
```

### Antigravity (Gemini)
Add the `mco` entry to Antigravity's MCP config:

```json
{
  "mcpServers": {
    "mco": {
      "command": "C:/AI/MCOrchestr8/.venv/Scripts/mco.exe",
      "args": ["mcp"],
      "env": {
        "MCO_GATEWAY_URL": "http://127.0.0.1:18789",
        "MCO_AGENT_TOKEN": "mco_tok_REPLACE_ME",
        "AGENT_ROLE": "antigravity",
        "AGENT_INSTANCE_ID": "coding-beast-gemini"
      }
    }
  }
}
```

Restart each app so it picks up the MCP server.

---

## Part 7 — Run the loop (the part that makes it autonomous)

Each agent runs a recurring prompt that does **one inbox sweep** and ends. The
**scheduler** (not the prompt) owns recurrence.

> ⚠️ **Never** put control-flow words ("stop", "do not loop", "one pass") inside a
> looped prompt — a looping agent will read "stop" and cancel its own loop.

### Claude — `/loop` (sub-hour)
In an open Claude session:

```
/loop 10m Check your MCO inbox: call mco_inbox. For each job addressed to you (up to 3), call mco_lease(task_id); if the lease succeeds, carry out its input_payload.prompt using your tools, then mco_complete(task_id, <concise result>) — or mco_fail(task_id, <error>). If the inbox is empty, there is nothing to do this run.
```

### Codex — cron `*/5 * * * *`

```
Check your MCO inbox: call mco_inbox. For each job (up to 3): mco_lease(task_id); if the lease succeeds, implement what its input_payload.prompt asks in the workspace, then mco_complete(task_id, <summary of files changed>) — or mco_fail(task_id, <error>) — and hand off: mco_send(to_role="antigravity", title="Review & test: <feature>", instructions="<what to verify / how to run tests>"). If the inbox is empty, there is nothing to do.
```

### Antigravity — cron `*/5 * * * *`

```
Check your MCO inbox: call mco_inbox. For each job (up to 3): mco_lease(task_id); if the lease succeeds, review/test what the job points to (run the tests). If it passes: mco_complete(task_id, <verdict>). If it needs fixes: mco_complete(task_id, <findings>) and mco_send(to_role="codex", title="Fix: <issue>", instructions="<what to fix>"). If the inbox is empty, there is nothing to do.
```

### No AI app? Use the built-in daemon
You can drive a role with the bundled worker instead of an AI app:

```bash
mco listen --role codex --instance coding-beast-codex
```

---

## Part 8 — Kick off a job

From any agent (or via the API), drop the first task. In an agent that has the
MCP wired, just ask it to:

```
mco_send(to_role="codex", title="Hello world", instructions="Create hello.py that prints 'hello from the swarm'")
```

Codex's next loop tick leases it, writes the file, completes it, and sends a
review job to Antigravity. Watch it flow with `mco agents` and the Supabase
table editor.

---

## Topology (rewire as you like)

- **claude** (planner): turns a goal into a plan → `mco_send` → codex
- **codex** (builder): writes code → `mco_send` → antigravity
- **antigravity** (reviewer): tests; on failure → `mco_send` → codex (fix loop); else done

Change the `mco_send` targets in the loop prompts to rewire the pipeline, or drop
them entirely for a flat peer model where each agent only does what it is sent.

---

## Security notes

- **Tokens are bearer credentials.** Keep them out of git. `.env` and
  `configs/_filled/` are gitignored for this reason — never commit real tokens.
- The gateway enforces the **dropbox rule**: anyone may send to anyone, but an
  agent can only lease / complete / poll mail **addressed to it** (its role or
  its instance). Cross-agent reads return `403`.
- Secrets live encrypted at `~/.mco/secrets.enc` (AES-256-GCM, PBKDF2 600k
  iterations). The master key auto-loads from Windows Credential Manager
  (`MCO_SECRET_STORE`), the `MCO_MASTER_PASSWORD` env var, or an interactive
  prompt — in that order.
- Use the Supabase **service_role** key only on the trusted machine running
  `mco serve`. Do not ship it to the agent apps — they authenticate with their
  own per-agent `mco_tok_...` tokens, not the database key.

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `mco status` shows DB not configured | Re-run `mco setup`, choose Hybrid/Cloud-Heavy, paste Supabase URL + service_role key. |
| `curl /api/agents` returns 503 | Gateway can't reach Supabase — check the URL/key and that the secret store unlocked. |
| Agent tools return 401 | Token is wrong/rotated. Re-`mco register` and update the app's `MCO_AGENT_TOKEN`. |
| Agent tools return 403 | The job isn't addressed to that agent's role/instance. Check `target_agent_role`. |
| `lease` always returns false | Job isn't `pending` (already leased/completed) or `lease_task` function wasn't created — re-run the SQL in Part 2.2. |
| Looping agent stops itself | A control-flow word ("stop") leaked into the loop prompt. Remove it. |
