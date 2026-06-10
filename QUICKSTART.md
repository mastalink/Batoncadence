# BatonCadence Quickstart Guide

This quickstart guide gets a local, secure instance of BatonCadence up and running in under 2 minutes.

---

## 1. Setup Your Virtual Environment

First, open your terminal (PowerShell, Command Prompt, or Bash) and navigate to the project directory:

```bash
cd C:/AI/BatonCadence

# Create and activate virtual environment
python -m venv .venv
# On Windows:
.venv\Scripts\activate
# On Linux/macOS:
source .venv/bin/activate

# Install the package in editable mode with development tools
pip install -e .[dev]
```

---

## 2. Initialize Secure Configuration

Run the interactive wizard to set up your environment profiles and AES-256-GCM credentials store:

```bash
mco setup
```

**Quick Selections:**
- Choose **[1] Local-Only** for testing without cloud dependencies, or **[3] Hybrid** to configure the Supabase database.
- Opt-in to **Encrypt sensitive credentials** and **Windows Credential Manager** to enable passwordless background launches.

Verify configuration health:
```bash
mco status
```

---

## 3. Run the Coordination Gateway (Server)

Start the combined REST/WebSocket gateway:

```bash
mco serve
```
This runs the coordination engine locally at `http://127.0.0.1:18789`.

---

## 4. Run the Background Executor (Daemon)

In a new terminal window (with `.venv` active), launch a background agent listener:

```bash
mco listen --role codex --instance local-worker-1
```
The listener will register itself, poll for jobs, and execute them safely.

---

## 5. Programmatic Quickstart Example (`quickstart.py`)

A simple python script to interact with BatonCadence programmatically is located in the root of the workspace. Run it to verify direct API access:

```bash
python quickstart.py
```
This script initializes the config manager, demonstrates the AES-256-GCM secure credentials loading, and prints current credentials health status.
