# BitCadence Bug & Usability Anomaly Inventory

Five observations from the hands-on review. Each lists the evidence type: **source** means confirmed by reading the cited code on `main` at the time of writing; **UI** means observed in the running console but not re-verified in a test. An earlier draft listed two more items (a persistent invisible backdrop after backdrop-click, and an invalid `"\B"` escape warning). Neither could be reproduced or located in source, so both were removed.

---

### Bug 1: New Job modal does not close on Escape

- **Severity:** Low
- **Evidence:** source
- **Surface:** Web Console, Job Board
- **Component:** `src/mco/console_src/5adac14f-6645-4e02-866b-22c4e571989b.js` (`NewJobForm`, opened by the **+ New job** button)
- **Finding:** Clicking the backdrop or the `×` button closes the drawer. No `keydown` / `Escape` handler exists anywhere in `src/mco/console_src`, so pressing Escape does nothing.
- **Reproduce:** Open `/console`, Job Board, **+ New job**, press `Escape`. The form stays open.
- **Expected:** Escape dismisses the modal, as most users assume.

---

### Bug 2: "Register agent" button is hidden in Demo Mode

- **Severity:** Medium
- **Evidence:** source
- **Surface:** Web Console, Agent Fleet
- **Component:** `src/mco/console_src/2ed3f6b1-e1c6-43fc-8b29-31917195cbd5.js:215`
- **Code:**
  ```javascript
  {live ? (
    <Btn kind="primary" small onClick={() => setShowRegister((v) => !v)}>
      {showRegister ? "Cancel" : (tone === "plain" ? "Add agent" : "Register agent")}
    </Btn>
  ) : null}
  ```
- **Reproduce:** Open `/console` without connecting a live token, go to **Agent Fleet**.
- **Finding:** With `live` false the button renders nothing, so a first-time user sees no graphical way to register an agent and no hint that connecting is required.
- **Expected:** A disabled button or a short note explaining that registration needs a live connection.

---

### Bug 3: `Start BitCadence.bat` opens the browser even if the server failed to start

- **Severity:** Medium
- **Evidence:** source
- **Surface:** `Start BitCadence.bat:77-79`
- **Code:**
  ```bat
  start "" /b cmd /c "timeout /t 5 /nobreak >nul & start http://127.0.0.1:18789/console"
  ".venv\Scripts\python.exe" -m mco.cli serve
  ```
- **Reproduce:** Make `mco serve` exit immediately (for example, occupy port 18789 first), then run the script.
- **Finding:** The browser launch is an unconditional five-second timer. If the server has already exited, the browser opens onto a connection-refused page.
- **Expected:** Probe the port (or `/readyz`) before launching the browser.

---

### Bug 4: Desktop Manager creates its Tk root without a guard

- **Severity:** Medium
- **Evidence:** source (crash not exercised in a headless session)
- **Surface:** `src/mco/desktop/app.py`, `DesktopApp.__init__`
- **Finding:** `self.root = tk.Tk()` is called with no `try/except`. On a host with no display, `tk.Tk()` raises `TclError`, which would surface as an unhandled traceback rather than a message pointing at `mco status`.
- **Reproduce:** Run `python -m mco.desktop.app` from an SSH session or other host with no desktop display.
- **Expected:** Catch the error, print a one-line explanation, and exit non-zero.

---

### Bug 5: Two flow builders do not share a draft

- **Severity:** Medium
- **Evidence:** source and UI
- **Surface:** `/console` Workflows tab versus `/flow` Design mode
- **Finding:** `/flow` is a standalone page (`src/mco/static/flow.html`) and the console builder is part of the console bundle. A search of both for draft persistence found no shared storage; the only `localStorage` key used by `flow.html` is the access token. A workflow drawn in one builder does not appear in the other, except through YAML export and import.
- **Reproduce:** Build a three-step workflow in the console Workflows tab, then open `/flow` and choose **Design workflow**. The canvas is empty.
- **Expected:** One shared draft, or a single builder.
