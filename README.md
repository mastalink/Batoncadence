# MCOrchestr8 (Multi-Client Orchestrator)

MCOrchestr8 is a highly secure, modular, and completely standalone agent orchestration and job board system. It acts as a lightweight coordination hub enabling multiple diverse agents on different platforms or machines to register, lease, and atomically execute tasks.

---

## Features

- **Decoupled Architecture**: 100% independent from any core platform or framework.
- **Secure Secret Storage**: Military-grade `AES-256-GCM` encryption for local configuration parameters and API credentials, with automated passwordless unlock via Windows Credential Manager integration.
- **Dynamic Profiles**: Flexible environment profiles (Local-Only, Cloud-Heavy, Hybrid) tailoring how the system behaves.
- **Robust Job Board**: High-performance, concurrent WebSocket and REST-based multi-client job dispatch, leasing, execution tracking, and downstream task dependency resolution.
- **Gateway Security**: REST API endpoints secured using dynamic Bearer-token authentication and dedicated Dropbox authorization scopes.
- **Role Executors**: Native execution templates for diverse roles (`codex`, `claude`, `gemini`) so leased jobs automatically process through correct interfaces.
- **Supabase Performance Optimization**: Memoized, pre-warmed Supabase clients preventing polling delays or query timeouts.
- **`ntfy.sh` centralized hooks**: Integrated central configuration manager notifier wiring process snapshot leak detections, case-insensitive role filtering, and dynamic job lease notifications.
- **Dropbox MCP Server**: Custom MCP server integrating the dropbox schema and specialized GUI configuration maps (Claude, Codex, Antigravity).
- **Immutable Audit Trail**: Every job mutation (create, lease, status change, approval decision, retry, escalation) is appended to a tamper-evident `agent_job_events` table protected by a database trigger that rejects UPDATE/DELETE. Inspect with `mco audit <job_id>` or `GET /api/jobs/{id}/events`.
- **Human-in-the-Loop Approval Gates**: Jobs flagged `requires_approval` pause at `needs_approval` until an approver role (configurable via `MCO_APPROVER_ROLES`, default `human,admin,operator`) approves or rejects them — via REST, CLI (`mco approve` / `mco reject`), MCP tools, or the dashboard.
- **Escalation Paths**: Failed jobs retry up to `max_retries`, then auto-create an escalation job for `escalate_to_role` instead of dying silently — with ntfy alerts at every step.
- **Declarative Workflow DSL**: YAML-defined DAGs of multi-agent steps (`mco workflow pipeline.yaml`), with per-step approval gates, retry budgets, and escalation roles. See `configs/workflows/example_release.yaml`.
- **Control-Plane Dashboard**: Zero-build web UI at `http://host:port/dashboard` — job board, approval queue with approve/reject buttons, agent fleet presence, and per-job audit viewer.
- **Windows Console Stability**: Pure ASCII console notation (`->`) replacing unicode symbols to avoid legacy terminal encoding crashes on Windows.
- **CLI-First**: Ergonomic, rich CLI commands `setup`, `serve`, `listen`, `status`, `workflow`, `audit`, `approve`, and `reject`.

---

## Installation

MCOrchestr8 is designed to be installed as a local editable python package.

### Prerequisites
- Python 3.9 or higher
- (Recommended) `uv` or `pip`

```bash
# Clone or navigate to the repository
cd C:/AI/MCOrchestr8

# Set up virtual environment
python -m venv .venv
source .venv/Scripts/activate # On Windows: .venv\Scripts\activate

# Install dependencies in editable mode
pip install -e .[dev]
```

---

## Usage & CLI Commands

Once installed, the CLI is available via the `mco` command (or executing `python mco.py`).

### 1. Interactive Onboarding & Setup
Initialize the configuration, environment profiles, and AES-256-GCM secure storage using the interactive setup wizard:
```bash
mco setup
```
This wizard will prompt you to:
- Choose your **Environment Profile** (Local-Only, Cloud-Heavy, Hybrid).
- Set up **Supabase database** connection strings to persist the orchestration `agent_jobs` table (required for Cloud-Heavy and Hybrid profiles).
- Protect credentials using **AES-256-GCM encryption** (with the option to automatically store the master unlock key in Windows Credential Manager for passwordless reboots).

### 2. Check System Diagnostics
Confirm the state of the configuration, active API keys, and secret store lock status:
```bash
mco status
```

### 3. Start the Orchestrator Server
Spawn the FastAPI server hosting REST jobs endpoints and WebSocket broadcasts:
```bash
mco serve
```

### 4. Spawn Background Executor Daemon
Run the background agent client listener to poll the job board, claim/lease tasks, and execute them:
```bash
mco listen --role codex --instance local-worker-1
```

### 5. Governance Commands
```bash
# Submit a multi-step, multi-agent workflow (validate first with --dry-run)
mco workflow configs/workflows/example_release.yaml

# Inspect a job's immutable audit trail
mco audit <job_id>

# Decide a human-in-the-loop approval gate (requires an approver-role token)
mco approve <job_id>
mco reject <job_id> --reason "too risky"
```
Or open the control-plane dashboard at `http://127.0.0.1:18789/dashboard` and
paste an agent token to manage the approval queue visually.

Full usage documentation for approval gates, the audit trail, retries/escalation,
the workflow DSL, and the dashboard lives in [docs/GOVERNANCE.md](docs/GOVERNANCE.md).

---

## Advanced Integrations

### ntfy Notification Setup
MCOrchestr8 supports instant task push alerts over `ntfy.sh` (or any custom ntfy server). Hook up notifications by configuring the following variables in your secure vault:
*   `NTFY_URL`: The URL to your target ntfy topic (e.g. `https://ntfy.sh/moses_leases`).
*   `NTFY_TOKEN`: Optional bearer authorization token for secured ntfy topics.

### Dropbox MCP Server configuration
The custom MCP server can map database schemas and client variables to GUI frontends (like Claude Desktop or Cursor). Add it with the following stdio parameters:
```json
{
  "mco-dropbox": {
    "command": "python",
    "args": ["-m", "mco.mcp.dropbox_server"],
    "env": {
      "SUPABASE_URL": "${SUPABASE_URL}",
      "SUPABASE_KEY": "${SUPABASE_KEY}"
    }
  }
}
```

---

## Technical Security Design (AES-256-GCM)

All sensitive API keys and connection tokens are kept safely out of raw `.env` files. Instead, MCOrchestr8 uses a secure envelope format stored at `~/.mco/secrets.enc`:

```json
{
  "version": 1,
  "kdf": "pbkdf2-hmac-sha256",
  "iterations": 600000,
  "salt": "base64...",
  "nonce": "base64...",
  "tag": "base64...",
  "ciphertext": "base64..."
}
```

The master key can be safely auto-loaded upon reboot from:
1. Windows Credential Manager under the target name `MCO_SECRET_STORE`.
2. The `MCO_MASTER_PASSWORD` environment variable.
3. Fallback interactive prompt if running a terminal session.

---

## Verification & Testing

Execute the comprehensive Pytest suite to verify route handlers, secure vault configurations, executors, and database connectors:
```bash
pytest tests/
```
All 52 unit and E2E test cases must pass cleanly.

---

## Project Background & Roadmap

- [docs/GOVERNANCE.md](docs/GOVERNANCE.md) - usage guide for the governance layer: approval gates, audit trail, retries/escalation, workflow DSL, and the dashboard.
- [docs/SETUP_GUIDE.md](docs/SETUP_GUIDE.md) - end-to-end setup: Supabase schema, gateway config, agent registration, and GUI/MCP wiring.
- [docs/VALIDATION_SUMMARY.md](docs/VALIDATION_SUMMARY.md) - the December 2025 market validation (Gartner IT Infrastructure Conference) that launched this project under the "AgentMesh" codename.
- [docs/ROADMAP.md](docs/ROADMAP.md) - current state vs. the original plan, gap analysis, and the close-out roadmap (audit trail, human-in-the-loop approval gates, escalation paths).
