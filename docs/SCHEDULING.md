# Scheduling — Launchers, Schedules, and Loops

Cron can start a process. It cannot tell you six weeks later *who authorized the
thing that ran at 3am*, stop after the tenth iteration because a human said so,
or pause a run behind an approval gate.

BatonCadence's scheduler creates **jobs on the governed board**, so recurring
work inherits everything a hand-submitted job gets: approval gates, retry
budgets, role/instance isolation, and an audit trail that records which schedule
created it.

Two config files, two different questions:

| File | Question it answers |
|---|---|
| `~/.mco/fleet.toml` | Which **workers** run, and how they wake |
| `~/.mco/schedules.yaml` | What **work** gets created, and when |

---

## Quick start

```bash
mco schedule init      # write a starter ~/.mco/schedules.yaml
mco schedule list      # see every schedule and its next fire time
mco launch <name>      # fire one by hand, right now
mco schedule tick --dry-run   # show what would fire, create nothing
mco schedule run       # run the scheduler in the foreground
```

---

## The three concepts

### Launcher — *what* to run

A named, reusable launch target. Either a single job or a whole workflow file.

```yaml
launchers:
  nightly-audit:
    role: reviewer                 # which role's dropbox
    title: Nightly dependency audit
    instructions: |
      Audit dependencies for new CVEs. Open a PR if any are found.
    requires_approval: false       # optional governance
    max_retries: 2
    escalate_to_role: human

  release:
    workflow: workflows/release-pipeline.yaml   # a whole DAG instead
```

`mco launch nightly-audit` fires it immediately. This is **the same code path** a
scheduled fire uses — so testing a launcher by hand proves the 3am run too.

### Schedule — *when* to run it

Binds a launcher to a trigger. Fires indefinitely until disabled.

```yaml
schedules:
  nightly-audit:
    launcher: nightly-audit
    cron: "0 3 * * *"              # 5-field cron, or @daily/@hourly/@weekly
    timezone: America/New_York     # optional; UTC when omitted

  health-check:
    launcher: nightly-audit
    every: 30m                     # 30s / 15m / 2h / 1d / 1w
    overlap: skip                  # skip (default) | allow
    enabled: true
    requires_approval: true        # force a gate on everything this fires
```

`overlap: skip` means a schedule won't fire again while its previous run is still
in flight — the default, because the common failure mode for agent work is a
pile-up of duplicate jobs racing each other on the same repo.

### Loop — a schedule that stops

Same machinery, **mandatory bound**. A loop must declare `max_iterations`,
`until`, or both.

```yaml
loops:
  triage-backlog:
    launcher: nightly-audit
    every: 30m
    max_iterations: 10
    until: "2026-12-31T00:00:00Z"
```

An unbounded self-repeating agent task is how fleets burn budget and drift, so
the parser **refuses to build one**:

```
loops.forever: a loop must declare 'max_iterations' and/or 'until'.
An unbounded loop is just a schedule - define it under 'schedules:' if that's what you meant.
```

The bound is enforced at runtime too, not just documented — once a loop hits its
limit it stops firing and `mco schedule list` shows *why*.

---

## Cron syntax

Standard 5-field: `minute hour day-of-month month day-of-week`

| Form | Meaning |
|---|---|
| `*` | every value |
| `5` | exactly 5 |
| `1-10` | range |
| `*/15` | every 15th |
| `8-18/4` | every 4th within a range |
| `1,3,5` | list |

Shortcuts: `@hourly` `@daily` `@midnight` `@weekly` `@monthly` `@yearly`

Day-of-week is `0`–`7` with both `0` and `7` meaning Sunday. When **both**
day-of-month and day-of-week are restricted they are OR'd, not AND'd — the
standard cron quirk (`0 0 1 * 5` = the 1st of the month *or* any Friday).

> **Windows:** timezone names need the IANA database, which Windows doesn't ship.
> It's installed automatically as a dependency (`tzdata`); if you see
> *"this machine has no IANA timezone database"*, run `pip install tzdata`.

---

## Running the scheduler

Two ways, pick one:

**Foreground daemon** — ticks on an interval until interrupted:
```bash
mco schedule run --interval 30
```

**Single pass** — drive it from an existing cron / Task Scheduler entry instead:
```bash
mco schedule tick
```

A bad config or an unreachable gateway won't kill the daemon; it logs and keeps
ticking. The failure operators actually suffer is a scheduler that quietly died
three weeks ago.

---

## Where state lives

`~/.mco/schedule-state.json` — iteration counts, last fire times, and the job ids
each fire created. Written atomically, and deliberately separate from
`schedules.yaml`: the config is yours to edit and version-control, the state is
the runtime's to own. If it's ever corrupted the scheduler starts fresh rather
than refusing to run.

---

## Auditing a scheduled run

Every job a launcher creates is stamped with its origin:

```json
{
  "origin": {
    "launcher": "nightly-audit",
    "schedule": "nightly-audit",
    "trigger": "schedule",
    "iteration": 7,
    "launched_at": "2026-07-28T07:00:00+00:00"
  }
}
```

So `mco audit <job-id>` answers "what created this, and was it the 7th of a
bounded loop or a human pressing the button?" — the question plain cron
structurally cannot.
