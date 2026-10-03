# Desktop Manager & System Tray

## Goal
Manage the local BitCadence server, background scheduler, and AI worker daemons using the native Windows Desktop Control window and system tray icon without keeping raw terminal windows open.

---

## Step-by-Step Instructions

### 1. Launch the Desktop Control Window
From the Windows Start menu or your Desktop, open the **BitCadence** shortcut, or run from terminal:
```powershell
python -m mco.desktop.app
```
or launch the system tray icon directly:
```powershell
mco tray
```

![BitCadence Desktop Control Window](img/19-desktop-control-window.png)

### 2. Start and Inspect Stack Components
1. In the top toolbar, click **Start all**. The Desktop Manager starts:
   - The Gateway API server (`mco serve`)
   - The Scheduler daemon (`mco schedule run`)
   - Configured local worker agents (`codex-worker`, `claude-worker`, etc.)
2. Check the component table to ensure all rows display status **running** with valid Process IDs (PIDs).
3. If you have legacy workers running as Windows Scheduled Tasks, click **Move workers into app** to migrate them under the desktop supervisor.

### 3. Open the Web Console
Click **Open console** in the top right. Your default browser will launch immediately to `http://127.0.0.1:18789/console`.

### 4. Filter Live Logs
Click any row in the component table (such as `gateway` or `scheduler`) to filter the bottom live log pane specifically to that service.

### 5. Minimize to System Tray
Click the **X** (close) button on the top-right of the window. 
The window disappears from the taskbar, and BitCadence continues running quietly in your Windows Notification Area (System Tray).

### 6. Restoring or Exiting from the Tray
1. Right-click the **BitCadence** icon in your system tray.
2. Select **Open BitCadence** to restore the window.
3. Select **Exit** when you want to stop all child processes, workers, and the gateway simultaneously.

---

## The CLI Equivalent

You can control all background processes and query their operational health directly from PowerShell:

```powershell
# Start gateway in background
mco start

# Check process status and diagnostics
mco status

# Stop background gateway
mco stop

# Apply worker fleet run modes
mco fleet apply

# Inspect worker fleet status
mco fleet status
```

---

## What You'll See

- **Desktop Window:** A native Windows window showing:
  - Header with overall health light (Green dot for healthy gateway).
  - Component table listing Component Name, Status (`running`, `standby`, `disabled`), PID, and Last Error.
  - Controls: `Start all`, `Stop all`, `Restart all`, `Start selected`, `Stop selected`, `Restart selected`, `Fleet settings`, `Reload settings`.
  - Dark terminal log viewer updating every 500ms with live output.
- **System Tray:** A custom BitCadence logo in the Windows notification tray with options to restore the UI or stop all processes.
- **Process Guard:** All spawned child processes are attached to a Windows Job Object (`JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`), guaranteeing that if the desktop manager terminates, no orphaned background workers are left consuming CPU or memory.

---

## If It Goes Wrong

### 1. "Pillow or pystray not found"
- **Cause:** Python environment was installed without the desktop extra dependencies.
- **Fix:** Install desktop dependencies in your environment:
  ```powershell
  pip install "bitcadence[desktop]"
  ```
  or run the helper installer:
  ```powershell
  .\scripts\install_desktop.ps1
  ```

### 2. "Gateway failed readiness probe"
- **Cause:** Another process is bound to port 18789, or an existing gateway crashed and left a lock.
- **Fix:** Select the `gateway` row in the table, click **Stop selected**, wait 2 seconds, then click **Start selected**.

### 3. "Closing window terminates server instead of hiding in tray"
- **Cause:** System tray support failed to initialize due to notification area permissions or display server isolation.
- **Fix:** Check the status label at the top. If tray initialization failed, the status displays `Tray unavailable`. Use `mco start` to run as a persistent background daemon instead.
