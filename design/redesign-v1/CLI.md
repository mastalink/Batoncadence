# CLI redesign spec

Goal: a person who has never used a terminal can still get by with five plain words. Everyone else keeps working, because every old `mco` command stays as an alias.

## Principles

1. **Plain verbs.** `start`, `status`, `ask`, `approve`, `fix`, plus `helpers`, `schedule`, `connect`, `pause`.
2. **Ask, don't make me remember flags.** If something is missing, the command asks. Flags still work for scripts, and `--yes` skips questions.
3. **Errors say what to do next.** Every error has two parts: what happened in one plain sentence, and the exact next command or "run `bitcadence fix`". No stack traces unless `--debug`.
4. **No secrets on screen.** No tokens, ports or addresses in normal output. They appear only under `bitcadence settings --show-advanced`.
5. **Old commands are aliases.** `mco <anything>` keeps working and prints nothing extra. A hint to the new verb appears once per day at most.
6. **Pick from a list.** Where a job id is needed, show a numbered list of plain titles. The id is accepted but never required.

## The five core verbs

```
bitcadence start                 Start in the background (no window). Opens the app.
bitcadence status                Plain summary: what needs you, what's running, any problems.
bitcadence ask "..."             Draft a plan from plain words, show it, ask "Start this? [Y/n]".
bitcadence approve               Show what's waiting, one at a time. Y = approve, N = not yet.
bitcadence fix                   Find what's wrong and offer to repair it. Y/n per fix.
```

Also: `bitcadence helpers`, `bitcadence schedule`, `bitcadence connect`, `bitcadence pause` / `resume`, `bitcadence remember "..."`, `bitcadence stop`.

### Sample session

```
$ bitcadence status
Good morning.
  Needs you (2)
    1. Publish release notes?            (Weekly release)
    2. Tester is stuck                   (10 minutes)
  Running (2)
    Weekly release   step 3 of 5   Reviewer is checking the changes
    Tidy the docs    step 1 of 3   Writer is rewriting the install page
Run `bitcadence approve` or `bitcadence fix`.

$ bitcadence fix
Found 1 problem.
  Tester stopped answering 10 minutes ago because a second copy is running.
  Stop the extra copy and restart Tester? [Y/n] y
Done. Tester is working again.
```

## Plain-English errors

| Situation | Today | Redesigned |
|---|---|---|
| Not running | `ConnectionRefusedError: [Errno 111] ... 127.0.0.1:18789` | `BitCadence isn't running. Start it with: bitcadence start` |
| Missing approver rights | `403 Forbidden: missing scope jobs:approve` | `You can't approve yet because your account isn't an approver. Fix it? [Y/n]` |
| Nobody to do the job | job sits in `pending` forever | `Approved, but no helper is free. Start one? [Y/n]` |
| Locked log | silent, status shows online | `Fixer can't save its notes because another copy has the file open. Run: bitcadence fix` |
| Bad schedule | `invalid cron expression` | `I didn't understand "every second tuesday". Try "every weekday at 2 AM".` |
| Port in use | traceback | `Another program is using what BitCadence needs. Run: bitcadence fix` |
| App not found when connecting | `FileNotFoundError: claude_desktop_config.json` | `I couldn't find Gemini on this computer. Install it, then run: bitcadence connect gemini` |

## Before and after: the 15 most-used commands

"Before" is the reference at `docs/wiki/mco-cli-reference.md`. Old forms keep working as aliases.

| # | Before | After | Notes |
|:-:|---|---|---|
| 1 | `mco serve --host 127.0.0.1 --port 18789` (foreground, black window) | `bitcadence start` | Background, no window, opens the app. Alias: `mco start`. |
| 2 | `mco status` (database path, profile, diagnostics) | `bitcadence status` | Plain summary of what needs you and what's running. Old output under `--details`. |
| 3 | `mco doctor` | `bitcadence fix` | Finds problems and offers fixes. `doctor` stays as a report-only alias. |
| 4 | `mco setup` (menu of profiles, tokens, vault) | `bitcadence start` (first run only) | No setup menu for normal use. Advanced pieces live in `bitcadence settings`. |
| 5 | `mco send "Title" --role codex --instructions "..." --approval --retries 2` | `bitcadence ask "..."` | Roles, approval and retries are chosen for you. Asks before starting. |
| 6 | `mco workflow plan.yaml` | `bitcadence ask "..."` | No YAML. The plan is drawn and approved. A file can still be loaded with `--file`. |
| 7 | `mco approve <job-id>` | `bitcadence approve` | Walks through what's waiting. Id optional. |
| 8 | `mco reject <job-id> --reason "..."` | `bitcadence approve` then answer **n** | Asks "What should change?" in a sentence. |
| 9 | `mco retry <job-id>` / `mco reassign <job-id>` | `bitcadence fix` | Offers "try again" or "try a different helper". |
| 10 | `mco register --name x --role codex --scope jobs:read,jobs:write` | `bitcadence helpers add` | Asks name and what it's good at. Saves credentials itself. |
| 11 | `mco listen --role codex --instance x` (leaves a window open) | `bitcadence helpers add` | Starts quietly in the background. |
| 12 | `mco agents` | `bitcadence helpers` | Names, jobs, and a health light each. |
| 13 | Hand-edit `claude_desktop_config.json`, then `mco mcp` | `bitcadence connect claude` | Finds the app and writes its settings. `connect` alone shows a pick list. |
| 14 | Edit `~/.mco/schedules.yaml`, then `mco schedule enable <name>` | `bitcadence schedule` | Asks what, how often, what time. Prints "Every weekday at 2:00 AM". |
| 15 | `mco service install-waker` (needs admin) / `mco fleet apply` | `bitcadence helpers add` / `bitcadence helpers pause` | One consent prompt at most, once. Service files written for you. |

Other old commands (`remember`, `recall`, `audit`, `exchange`, `score`, `platform`, `connectors`, `reset-token`, `deregister`) stay as they are under `bitcadence advanced <old command>` and as the original `mco` forms. They are not part of the everyday set.

## Interactive prompt rules

- One question per screen, a default in brackets, Enter accepts it.
- Lists are numbered. Type a number or part of a name.
- Never ask for a value we can find ourselves.
- Always say what will happen before doing anything that changes things.
- Anything that spends money, publishes or deletes asks first, even with `--yes`, unless the person set that policy in Settings.

## Compatibility

- The `mco` binary remains installed and points at the same code. Scripts are not broken.
- `bitcadence` and `mco` accept the same flags.
- Output for scripts: `--json` on every read command, unchanged from today.
- Exit codes stay the same.

## Open questions

1. Binary name on package managers (`bitcadence` vs a short alias).
2. Whether `bitcadence ask` should work with no network by queuing the request.
