# Installing BatonCadence (One-Click Windows Install)

This guide covers the simple, non-technical install path. It is written so
that anyone — no programming experience needed — can get BatonCadence running
and see the console GUI in their browser.

For the developer-oriented setup (profiles, encryption, Supabase, agents),
see [SETUP_GUIDE.md](SETUP_GUIDE.md).

---

## What you need

- A Windows 10 or 11 computer
- An internet connection (only for the install itself)
- The BatonCadence folder on your computer (downloaded as a ZIP from GitHub
  and extracted, or copied from a USB stick — anywhere is fine, e.g.
  `C:\BatonCadence`)

You do **not** need Python pre-installed, an account with any cloud service,
or any API keys. The installer handles everything and configures a safe
**Local-Only** profile that runs entirely on your computer.

---

## Install (one double-click)

1. Open the BatonCadence folder.
2. Double-click **`install.bat`**.
3. A blue-and-green setup window appears and walks through six steps:
   1. Finds Python (and offers to install it automatically if missing)
   2. Creates a private virtual environment (`.venv`)
   3. Installs BatonCadence and its dependencies
   4. Writes a safe Local-Only configuration (`.env`)
   5. Verifies the install with a self-check
   6. Puts a **BatonCadence** shortcut on your Desktop
4. When asked *"Would you like to start BatonCadence now?"* press **Enter**.

That's it. Your browser opens the BatonCadence Console at
`http://127.0.0.1:18789/console`.

---

## Day-to-day use

- **Start:** double-click the **BatonCadence** icon on the Desktop. A black
  server window opens, and a few seconds later your browser shows the console.
- **Stop:** close the black server window.
- If you double-click the icon while BatonCadence is already running, it
  simply opens the console again — it won't start a second copy.

The console starts in a safe **demo mode** until it is connected to a live
database — perfect for exploring the GUI. To connect it, open
*Settings → Connection* inside the console and paste an agent token
(see [GOVERNANCE.md](GOVERNANCE.md)).

---

## What the installer creates

| Item | Where | Purpose |
|---|---|---|
| `.venv\` | BatonCadence folder | Private Python environment (doesn't touch the rest of the PC) |
| `.env` | BatonCadence folder | Local-Only configuration (no cloud, no secrets) |
| `BatonCadence.lnk` | Desktop | Shortcut to `Start BatonCadence.bat` |

Nothing is installed system-wide except Python itself (and only if it wasn't
already there). To uninstall, delete the BatonCadence folder and the Desktop
shortcut.

---

## Unattended / scripted install

For CI or remote provisioning, run the installer without prompts:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install.ps1 -NoPrompt
```

In `-NoPrompt` mode the script never asks questions: it fails fast if Python
3.9+ is missing instead of offering a winget install, and it does not
auto-start the server at the end.

---

## Troubleshooting

**The setup window flashes and disappears**
Run it from a terminal instead so you can read the error:
`powershell -ExecutionPolicy Bypass -File scripts\install.ps1`

**"Python was installed but is not yet visible"**
Windows needs a fresh session to pick up the new PATH. Close the window and
double-click `install.bat` once more.

**The browser opens but shows "can't connect"**
The server needed longer than 4 seconds to start (first launch is slowest).
Wait a few seconds and refresh the page.

**Port 18789 is in use by something else**
Start the server on another port from a terminal in the BatonCadence folder:
`.venv\Scripts\python.exe -m mco.cli serve --port 18790`
then browse to `http://127.0.0.1:18790/console`.

**Deeper diagnostics**
`.venv\Scripts\python.exe -m mco.cli status` prints a full configuration
health check.
