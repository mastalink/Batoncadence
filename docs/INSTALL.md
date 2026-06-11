# Installing BatonCadence — Dad's Guide

This guide assumes zero technical background. Follow it top to bottom, and you
will be looking at the BatonCadence console in your browser.

---

## What you need

- A Windows 10 or 11 computer
- The BatonCadence folder anywhere on your computer (e.g. `C:\BatonCadence`)
- An internet connection during installation only

You do **not** need a cloud account, API keys, or Python pre-installed.

---

## Step 1 — Install (one double-click)

1. Open the BatonCadence folder.
2. Double-click **`install.bat`**.

A window opens and runs through six steps automatically:

```
[OK] Python 3.x found
[OK] Virtual environment created
[OK] BatonCadence installed
[OK] Created Local-Only configuration (.env) with access token
[OK] CLI self-check passed
[OK] Shortcut 'BatonCadence' added to the Desktop
```

When it asks *"Would you like to start BatonCadence now?"* press **Enter**.

> If Python is not found it will offer to install it automatically — press
> Enter again and wait about two minutes.

---

## Step 2 — Start (every time after that)

Double-click the **BatonCadence** icon on your Desktop.

A black server window appears and shows something like this:

```
============================================================
  Starting BatonCadence...
============================================================

  Your access token (already copied to clipboard):

    mco_tok_a1b2c3d4e5f6...

  In 5 seconds your browser will open the console.
  Paste the token into the "Agent token" box and click Connect.

  Keep this window open while BatonCadence is running.
  Close it to stop BatonCadence.
============================================================
```

Your browser opens automatically in about 5 seconds.

> The token is already in your clipboard — you do not need to type it.

---

## Step 3 — Connect the console (first time only)

The console opens showing **"Demo mode — simulated data"**. Here is how
to connect it to your live server in three clicks:

1. Click the **Settings** icon (or look for the Settings panel — it is
   usually open already).

2. You will see two fields:

   | Field | What to type |
   |---|---|
   | **Gateway URL** | `http://127.0.0.1:18789` — this is already filled in |
   | **Agent token** | Paste here (`Ctrl+V`) — the token is already in your clipboard |

3. Click **Connect**.

The page changes from *"Demo mode"* to live data. You are done — the console
remembers these settings and connects automatically next time.

Everything you do now is saved on your computer (in `~/.mco/local.db`):
jobs, the audit history, and the shared agent memory (Mythos) all work
without any cloud account.

> **Token forgotten?** Look at the black server window — it always shows the
> token at startup. Or open `.env` in the BatonCadence folder in Notepad and
> look for the line that starts with `MCO_LOCAL_TOKEN=`.

---

## Day-to-day use

- **Start:** double-click the **BatonCadence** icon on the Desktop.
- **Stop:** close the black server window.
- If you double-click while it is already running, it just reopens the
  console (it won't start a second copy).

---

## What the installer creates

| Item | Where | Purpose |
|---|---|---|
| `.venv\` | BatonCadence folder | Private Python environment |
| `.env` | BatonCadence folder | Configuration + access token |
| `BatonCadence.lnk` | Desktop | Shortcut that starts everything |

To uninstall: delete the BatonCadence folder and the Desktop shortcut.
Nothing else is changed on the computer (except Python itself, if it was
installed automatically).

---

## Troubleshooting

**The setup window flashes and disappears**

Open a terminal and run the installer from there so you can read the error:
```
powershell -ExecutionPolicy Bypass -File scripts\install.ps1
```

**"Python was installed but is not yet visible"**

Close the window and double-click `install.bat` again — Windows needs a
fresh session to pick up the new PATH.

**The browser opens but says "can't connect"**

The server needed a few extra seconds to start. Wait 10 seconds and
refresh the page.

**The console shows "Demo mode" even after pasting the token**

- Make sure you pasted the whole token (it starts with `mco_tok_`)
- Check the Gateway URL is exactly `http://127.0.0.1:18789`
- The server window must still be open — if you closed it, double-click
  the Desktop icon to restart

**Port 18789 is already in use**

Run the server on a different port from a terminal:
```
.venv\Scripts\python.exe -m mco.cli serve --port 18790
```
Then use `http://127.0.0.1:18790` as the Gateway URL in the console.

**Where is my token?**

Open the `.env` file in the BatonCadence folder in Notepad.
Find the line that starts with `MCO_LOCAL_TOKEN=` — everything after the
`=` is your token.

---

## For developers / power users

```powershell
# Check configuration health
.venv\Scripts\python.exe -m mco.cli status

# Interactive setup wizard (change profile, add Supabase, encryption)
.venv\Scripts\python.exe -m mco.cli setup

# Run the gateway in a visible window
.venv\Scripts\python.exe -m mco.cli serve

# Register a database-backed agent (requires Supabase)
.venv\Scripts\python.exe -m mco.cli register --name my-agent --role admin
```

Unattended install (CI / scripted):
```powershell
powershell -ExecutionPolicy Bypass -File scripts\install.ps1 -NoPrompt
```
