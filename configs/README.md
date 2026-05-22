# Wiring the 3 GUIs to the MCO dropbox (MCP)

Each coding GUI talks to the MCOrchestr8 dropbox through the **`mco mcp`** stdio
server, authenticating as a registered agent. No `mco listen` daemon required —
each app uses its own scheduler to check its inbox.

## Prerequisites
1. The gateway must be running: `mco serve` (default `http://127.0.0.1:18789`).
2. Each agent must be registered (`mco register --name <instance> --role <role>`)
   and you must paste its **current** access token into the config below.
   (Re-running `register` rotates the token — use the latest.)

## Install per app
Replace `mco_tok_REPLACE_WITH_*` with each agent's real token first.

- **Claude Code** — copy `claude/.mcp.json` into your project root as `.mcp.json`
  (or run `claude mcp add mco -- C:\AI\MCOrchestr8\.venv\Scripts\mco.exe mcp`
  and set the env vars). Role `claude`, instance `coding-beast-claude`.
- **Codex** — append `codex/config.toml` to `~/.codex/config.toml`.
  Role `codex`, instance `coding-beast-codex`.
- **Antigravity** — add `antigravity/mcp_config.json`'s `mco` entry to
  Antigravity's MCP config. Role `antigravity`, instance `coding-beast-gemini`.

## Tools exposed
`mco_inbox` · `mco_lease(task_id)` · `mco_complete(task_id, output)` ·
`mco_fail(task_id, error)` · `mco_send(to_role, title, instructions, to_instance?)` ·
`mco_agents`

## Scheduler prompt (run on each app's interval)
> Call `mco_inbox`. For every job addressed to you: `mco_lease(task_id)`; if it
> succeeds, do the work in `input_payload.prompt`; then `mco_complete(task_id, <result>)`
> (or `mco_fail(task_id, <error>)`). Use `mco_send(...)` to hand work to another agent.

## Security
- Tokens are bearer credentials — keep them out of version control. The files
  here use placeholders on purpose.
- The gateway enforces the dropbox rule: anyone may send to anyone, but you can
  only lease/complete/poll mail addressed to you.
