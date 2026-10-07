# Step-count table

Every task from `docs/wiki/_review/FRICTION.md` Part 2. "Now" is the step count in the audit (UI steps, or CLI steps where the task has no UI). "Redesigned" counts taps or clicks the person makes, including any single OS permission prompt. Rule: any task over 2 steps gets redesigned.

| # | Task | Now | Redesigned | How it gets there | Mockup |
|:-:|---|:-:|:-:|---|---|
| 1 | Install and first run | 5 (CLI) / 2 (UI) | 1 (+1 OS prompt) | One installer. Quiet tray service starts itself. Browser opens already signed in. | 01 |
| 2 | Connect the web console | 4 | 0 | No token or address to copy. The app signs itself in. | 01 |
| 3 | Create a gated task | 5 | 2 | Type what you want, tap Approve. Roles are picked for you. | 05 |
| 4 | Decide an approval | 3 | 1 | Approve button on Home, the card, and the phone notification. If a helper is missing, the page offers "Start a helper". | 03, 08 |
| 5 | Author a workflow (console builder) | 6 | 2 | Builder removed. Describe it, review the drawing, Approve. | 05 |
| 6 | Author a workflow (flow design mode) | 8 | 2 | Design mode removed. Same as above. | 05 |
| 7 | Register an agent | 4 | 1 | "Add a helper" with a name. Credentials are made and stored by the app. Nothing to copy. | 06 |
| 8 | Connect Claude, Codex or Gemini | 7 | 1 | "Connect" per app. The app finds the app and writes the connection itself. | 02 |
| 9 | Run a background worker | 4 | 1 | "Add a helper" starts it quietly. No terminal. | 06 |
| 10 | Schedule a recurring loop | 6 | 3 | Pick what, how often, what time. Shows "Every weekday at 2:00 AM". No cron, no YAML. | 07 |
| 11 | Save a memory | 4 | 1 | "Remember this" in plain words. Type (fact, lesson) is worked out automatically. | 09 |
| 12 | Use the emergency stop | 3 | 1 | One "Pause everything" button in Settings and the tray menu. Says what keeps running. | 09 |
| 13 | Configure AI provider keys | 5 | 1 | "Sign in" with an account login where the provider allows it. Key paste only under Advanced. | 09 |
| 14 | Reassign a failed job | 4 | 1 | "Fix it" on the stuck card. Tries again, with a different helper if needed. | 04, 06 |
| 15 | Author a Score contract | 10 | 2 | Generated from the request. Not user-edited. | 05 |
| 16 | Install the desktop app and dependencies | 3 (CLI) | 1 | Same single installer as #1. No PowerShell, no Python path. | 01 |
| 17 | Autostart at sign-in | 3 (CLI) | 1 | "Start with my computer" toggle, on by default. | 09 |
| 18 | Declarative fleet orchestration (`fleet.toml`) | 4 (CLI) | 1 | Helpers page: add, pause or remove with buttons. The file is written for you. | 06 |
| 19 | Background sidecars (S4U logon) | 3 (CLI, admin) | 1 | Installer registers per-user background service. At most one consent prompt, once. No "Run as administrator" after that. | 01, 06 |
| 20 | Admin pack (service account, ACLs, firewall) | 4 (CLI, admin) | 1 (+1 OS prompt) | Optional "Lock this computer down" switch in Settings, behind one consent prompt. Never needed for normal use. | 09 |
| 21 | Wire the `claude-cio` sidecar policy | 5 (CLI) | 2 | Plain controls: "Ask me before spending over $X". Policy is generated. | 06, 09 |
| 22 | Diagnose a locked-log "online" helper | 6 (CLI) | 1 | Health light turns red with a reason. One "Fix it". | 04, 06 |
| 23 | Detect and resolve duplicate wakers | 5 (CLI) | 0-1 | Detected automatically. Extra copy stopped, one-line note shown. "Fix it" if user action is needed. | 06 |
| 24 | Migrate scheduled tasks to the desktop app | 3 (CLI) / 2 (UI) | 0 | Happens in the installer or first launch. Nothing to choose. | 01 |

## Totals

- Tasks audited: 24.
- Redesigned maximum: 3 steps (#10 schedules: what, how often, what time). Every other task is 2 or fewer. #10 stays at 3 because each step is a plain choice, like setting a phone alarm.
- Tasks that needed a terminal today (the CLI-only rows #16-#24, plus the CLI paths in #1, #8 and #9): none after the redesign.
- Tasks that needed "Run as administrator" today (#19, #20): none for normal use. The optional lock-down in #20 shows one consent prompt.
