# OS Services & Fleet Configuration

## Goal
Configure BitCadence processes (gateway, scheduler, wakers) as boot-persistent operating system services, and declare worker fleet topologies in `fleet.toml`.

---

## Step-by-Step Instructions

### 1. Declarative Fleet Configuration (`fleet.toml`)
BitCadence defines worker deployment topologies in `~/.mco/fleet.toml`:

```toml
[defaults]
gateway_url = "http://127.0.0.1:18789"

[workers.codex-builder]
role = "codex"
mode = "listen"                 # "listen" (daemon), "wake" (on demand), or "off"
command = "python workers/codex.py"
instances = 2

[workers.claude-researcher]
role = "claude"
mode = "wake"
command = "python workers/claude.py"

[workers.gemini-qa]
role = "gemini"
mode = "listen"
instances = 1
```

### 2. Applying Fleet Run Modes
Apply the configuration to spawn and align worker processes:

```powershell
# Apply declarative fleet settings
mco fleet apply

# Inspect current fleet status
mco fleet status

# Change an individual worker mode
mco fleet set codex-builder mode off
```

### 3. Installing OS Services
To survive system restarts and user logouts, install BitCadence components as native OS services:

**On Windows:**
Installs via Windows Task Scheduler or Windows Service Control Manager:
```powershell
# Install the gateway service
mco service install

# Install the background scheduler service
mco service install-scheduler

# Install the event waker service
mco service install-waker
```

**On Linux:**
Creates and enables `systemd` user units (`~/.config/systemd/user/bitcadence.service`):
```bash
mco service install
systemctl --user daemon-reload
systemctl --user enable --now bitcadence
```

### 4. Service Diagnostics and Lifecycle
```powershell
# Check service execution status
mco service status

# Restart services after code updates
mco service restart

# View unified service logs
mco service logs
```

---

## What You'll See

- **Self-Healing Supervision:** If a worker crashes, the supervisor restarts it with exponential backoff (up to 5 crashes in 5 minutes before pausing to avoid rapid crash loops).
- **Background Execution:** Services run without open terminal windows or user session dependencies.

---

## If It Goes Wrong

### 1. "Access is denied when installing service"
- **Cause:** Installing system-wide services requires administrative privileges.
- **Fix:** Open PowerShell as Administrator, or use user-level task installation.

### 2. "Workers crash repeatedly on startup"
- **Cause:** Missing environment variables or Python dependencies in the service execution context.
- **Fix:** Inspect logs with `mco service logs` to view standard error traces.
