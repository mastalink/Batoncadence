# MCOrchestr8 (Multi-Client Orchestrator)

MCOrchestr8 is a highly secure, modular, and completely standalone agent orchestration and job board system. It acts as a lightweight coordination hub enabling multiple diverse agents on different platforms or machines to register, lease, and atomically execute tasks.

## Features

- **Decoupled Architecture**: 100% independent from any core platform or framework.
- **Secure Secret Storage**: Military-grade `AES-256-GCM` encryption for local configuration parameters and API credentials, with automated passwordless unlock via Windows Credential Manager integration.
- **Dynamic Profiles**: Flexible environment profiles (Local-Only, Cloud-Heavy, Hybrid) tailoring how the system behaves.
- **Robust Job Board**: High-performance, concurrent WebSocket and REST-based multi-client job dispatch, leasing, execution tracking, and downstream task dependency resolution.
- **CLI-First**: Ergonomic, rich CLI commands `setup`, `serve`, `listen`, and `status`.

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
