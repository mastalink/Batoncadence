# BitCadence redesign v1 (Phase 1: mockups)

Open `index.html` in a browser. Static pages, no backend, nothing is built yet. Phase 2 (the real build) waits for owner approval of these mockups.

## What's here

| File | What |
|---|---|
| `index.html` | Browsable index: phone or desktop preview, light or dark |
| `01-first-run.html` | Install, "You're all set", quiet tray service (friction #1, #2) |
| `02-connect-ai.html` | One tap per AI app, app writes the connection (#3) |
| `03-home.html` | "What needs you" first, then "What's running" |
| `04-score-live.html` | Live Score view, auto-drawn and read-only |
| `05-ask.html` | Plain-language request, drawn plan, one Approve (#6, #9). Both drag-and-drop builders are removed. |
| `06-helpers.html` | Friendly names, Add a helper, health light, locked-log and duplicate detection (#4, #5) |
| `07-schedules.html` | "Every weekday at 2 AM" pickers (#8) |
| `08-approvals.html` | No 403s, plain fixes (#7) |
| `09-settings.html` | Advanced things behind plain labels |
| `CLI.md` | CLI redesign spec, 15 before/after |
| `STEP-COUNT.md` | Every friction task, current vs. redesigned steps |

## Design rules applied

- Two people drive every choice: someone who didn't grow up with computers, and a teen who only uses an iPhone.
- No jargon, terminal, JSON or YAML, tokens or ports on screen. No "Run as administrator" in normal use.
- Cards say what an agent is doing in plain words. A job id shows only after a tap.
- Colour is never the only signal: every state also has a word.
- Large tap targets (48 px or more), visible focus, reduced-motion respected.

## Decisions to confirm

1. Live view stages are columns on desktop and swipe sideways on phone.
2. "Ask for something" allows only light tweaks (remove a step, always ask me, make it repeat). Bigger changes mean editing the request.
3. Stalls are flagged after 10 minutes with no sign of life. The number is a placeholder.
4. The lock-down option (service account, firewall) is optional and stays behind one consent prompt.

## Not covered

- The real app, installer, tray service, or any backend. The mockups only show intent.
- Screen reader testing and real-device phone testing. Both come in Phase 2.
