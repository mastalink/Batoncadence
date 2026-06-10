# Goal: Hermes-style one-click install — "Dad can install it and see the GUI"

**Status:** Windows path shipped 2026-06-10. Linux/macOS parity open.

## The goal

A non-technical person (the canonical user: Dad) can take the BatonCadence
folder, double-click one thing, answer at most one Enter-key question, and end
up looking at the console GUI in their browser. Modeled on how the hermes
agent does it (`setup-hermes.sh`): one entry script that detects the platform,
provisions Python, creates the venv, installs deps, seeds config from a
template, puts the command somewhere reachable, and offers to launch.

## Acceptance criteria

- [x] Single double-clickable entry point (`install.bat` → `scripts/install.ps1`)
- [x] No prerequisites: installer finds Python 3.9+ or installs it via winget
- [x] Safe default config written automatically (Local-Only profile, no cloud,
      no API keys, no secret-store password prompts)
- [x] Post-install self-check (`mco.cli --help` smoke test)
- [x] Desktop shortcut that starts the gateway and opens
      `http://127.0.0.1:18789/console` (demo mode until connected — GUI is
      visible immediately)
- [x] Re-running the launcher while the server is up just reopens the console
      (no second-instance port crash)
- [x] Idempotent installer (re-run safely; never clobbers an existing `.env`)
- [x] Unattended mode for CI (`install.ps1 -NoPrompt`)
- [x] Non-technical documentation with troubleshooting (`docs/INSTALL.md`)

## Hermes parity map

| hermes `setup-hermes.sh` step | BatonCadence equivalent |
|---|---|
| Detect platform (desktop vs Termux) | `install.bat` (Windows); Linux/macOS TBD |
| Install/locate uv + Python 3.11 | Locate `python`/`py` 3.9+, winget fallback |
| Create venv | `.venv` via stdlib venv |
| Install deps (lockfile or editable) | `pip install -e .` |
| `.env` from `.env.example` | Generated Local-Only `.env` |
| Symlink `hermes` into `~/.local/bin` | Desktop shortcut → `Start BatonCadence.bat` |
| Offer to run setup wizard | Offer to start server + open console |

## Remaining work

- [ ] `install.sh` for Linux/macOS mirroring `install.ps1` (the repo's
      existing `scripts/mco.sh` covers invocation but not provisioning)
- [ ] Optional: `.env.example` checked into the repo so the manual path also
      has a template (hermes pattern)
- [ ] Optional: Start Menu entry + custom icon for the shortcut
- [ ] Optional: GitHub Release ZIP so Dad downloads one archive instead of
      cloning
