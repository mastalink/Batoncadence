# BatonCadence

**Every agent. One baton.**

[![MIT License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-blue.svg)](https://www.python.org/downloads/)
[![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey.svg)](docs/INSTALL.md)

A self-hosted orchestration hub for AI agents: a governed job board with
human approval gates, an immutable audit trail, and **Drumline** — one shared
memory every agent reads and writes. Runs entirely on your machine; no cloud
account required.

---

## Install

### macOS / Linux — one command

```bash
curl -sSf https://batoncadence.com/install.sh | bash
```

Clones the repo to `~/BatonCadence`, finds/installs Python, creates the venv,
generates your access token, adds `mco` to your PATH, then asks: demo mode
or connect now. Takes about two minutes.

```bash
# If you already cloned:
bash scripts/install.sh
```

### Windows — one double-click

Download the ZIP from GitHub, extract it anywhere, then double-click
**`install.bat`**. It finds (or installs) Python, builds the venv, generates
your access token, and drops a **BatonCadence** shortcut on the Desktop.
Your browser opens the console automatically.

```powershell
# PowerShell one-liner (no ZIP download needed):
iwr -useb https://batoncadence.com/install.ps1 | iex

# Or headless / CI:
powershell -ExecutionPolicy Bypass -File scripts\install.ps1 -NoPrompt
```

Full walkthrough and troubleshooting: [docs/INSTALL.md](docs/INSTALL.md)

### pip / Docker

```bash
git clone https://github.com/mastalink/Batoncadence
pip install -e Batoncadence
mco setup --guided    # configure in 60 seconds
mco serve             # console at http://127.0.0.1:18789/console
```

```bash
# Docker (team / cloud):
docker compose up     # see docs/DEPLOYMENT.md
```

---

## What it does

BatonCadence sits between your agents and the work they do. It gives you:

| | |
|---|---|
| **Job board** | Agents post work, workers lease atomically. Dependencies chain; no race conditions. |
| **Drumline** | One shared memory across the whole mesh. Completed jobs auto-distill into recallable handoffs. |
| **Approval gates** | Flag any job — or an entire role — to pause at `needs_approval` until a human decides. |
| **Immutable audit** | Every mutation appends to `agent_job_events`. UPDATE and DELETE are rejected at the storage layer. |
| **Embedded store** | No Supabase? An embedded SQLite store (`~/.mco/local.db`) takes over — the free edition is the full product. |
| **Enterprise connectors** | Ingest ServiceNow incidents and Dynatrace problems as jobs; act back with auditable, gated platform actions. |
| **Console GUI** | Zero-build web UI at `/console` — job board, approval queue, audit drawer, visual workflow builder. |

---

## Quick start

```bash
mco serve             # start the gateway
mco status            # config health check
mco setup             # guided walkthrough or settings menu
mco setup --guided    # hand-held, Enter at every prompt = working Local-Only install
mco setup --menu      # jump to one setting and get out
mco listen --role codex --instance worker-1   # start a worker
mco audit <job_id>    # inspect a job's full history
mco approve <job_id>  # approve a gate
```

Open **http://127.0.0.1:18789/console** in your browser, paste your access
token (shown at startup, or in `~/.mco/.env`), and click Connect.

---

## Drumline — shared memory

In a marching band, the drumline keeps everyone in step. Here it does the same
for agents: what one learns, every agent knows.

```
=== SHARED CONTEXT (Drumline) ===
- [handoff] Job outcome: Triage P-99 (claude-w1)
  Root cause: runaway cron. Disabled job foo.
- [fact] Prod DB read-only on Sundays (joe)
  Maintenance window 02:00-06:00 UTC.
=== END SHARED CONTEXT ===
```

- `mco_remember` / `mco_recall` — agents write facts and decisions
- Workers get relevant entries injected into their prompt before execution
- Works fully offline in the free Local-Only edition (SQLite, no vector DB)

Full spec: [docs/DRUMLINE.md](docs/DRUMLINE.md)

---

## Editions

| | Community | Team | Enterprise |
|---|---|---|---|
| Drumline shared memory | ✓ | ✓ | ✓ |
| Job board, approvals, audit | ✓ | ✓ | ✓ |
| Console GUI & workflow builder | ✓ | ✓ | ✓ |
| Embedded SQLite (zero cloud) | ✓ | ✓ | ✓ |
| Multi-machine / Supabase | — | ✓ | ✓ |
| Multi-org isolation + scoped-token RBAC | — | ✓ | ✓ |
| Docker + any-cloud deploy | — | ✓ | ✓ |
| ServiceNow & Dynatrace connectors | — | — | ✓ |
| SSO via your reverse proxy (trusted headers) | — | — | ✓ |
| Pilot program | — | — | [email us](mailto:pilots@batoncadence.com) |

One codebase, no separate builds: `mco edition` shows the active edition
(inferred from your config, or pinned with `MCO_EDITION`). Details, scope
vocabulary, and SSO setup: [docs/ENTERPRISE.md](docs/ENTERPRISE.md).

---

## Docs

- [docs/INSTALL.md](docs/INSTALL.md) — step-by-step install + troubleshooting
- [docs/DRUMLINE.md](docs/DRUMLINE.md) — shared memory: how it works, how to use it
- [docs/GOVERNANCE.md](docs/GOVERNANCE.md) — approval gates, audit trail, workflow DSL
- [docs/INTEGRATIONS.md](docs/INTEGRATIONS.md) — ServiceNow, Dynatrace, webhooks
- [docs/ENTERPRISE.md](docs/ENTERPRISE.md) — editions, scoped-token RBAC, SSO delegation
- [docs/SDK.md](docs/SDK.md) — write a custom agent/worker in fifteen lines
- [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) — Docker, any-cloud, multi-tenancy
- [docs/SETUP_GUIDE.md](docs/SETUP_GUIDE.md) — Supabase schema, agent registration, MCP wiring

---

## License

MIT — see [LICENSE](LICENSE). Copyright (c) 2026 Joe Arroyo.  
Self-host it, fork it, ship it inside your company.
