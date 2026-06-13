# Changelog

All notable changes. Format: [Keep a Changelog](https://keepachangelog.com); versioning: semver.

## [0.2.0] - 2026-06-12

The enterprise-suite release: RBAC, SSO delegation, editions, the Context
Exchange, a full web Control Panel, and an SDK.

### Added
- **Scoped-token RBAC**: every endpoint declares scopes; `mco register
  --scope` issues least-privilege tokens; role-derived defaults keep
  pre-RBAC installs behaving identically.
- **Trusted-header SSO delegation** (enterprise): authenticate humans via
  the reverse proxy you already run (oauth2-proxy, Cloudflare Access,
  Authelia) - off by default, optional constant-time proxy secret.
- **Edition model**: community / team / enterprise in one codebase,
  inferred from config or pinned with `MCO_EDITION`; `mco edition` prints
  the feature matrix.
- **Context Exchange**: structured handoffs ({summary, decisions, files,
  gotchas, follow_ups}) stored verbatim and weighted above mined context;
  workflow runs stamp every step, and workers inject the whole predecessor
  thread deterministically - cross-vendor continuity.
- **Web Control Panel** at `/dashboard`: lock screen, agent
  register/rotate/edit/delete with tokens shown exactly once, workflow
  YAML submission, server-driven settings (governance, Drumline, presence,
  tenancy, edition, security, notifications), connector health/sync,
  retry on failed jobs, MCP/worker connect instructions per token.
- **Agent presence health checks**: polling is the heartbeat; agents
  silent past `MCO_AGENT_OFFLINE_AFTER` (default 300 s) report offline with
  "seen Xm ago" in both the dashboard and `mco agents`.
- **Org allowlist** (`MCO_ORGS`): tenants are minted deliberately in
  Settings, never implicitly by a typo at registration.
- **Agent SDK** (`mco.sdk.BatonAgent`): a worker in fifteen lines with
  atomic leasing, thread-aware prompts, structured handoffs, and
  governance-correct failure reporting.
- **Air-gapped install**: `make-offline-bundle` scripts produce a
  repo+wheels archive; installers auto-detect `offline/wheels` and install
  with `--no-index`.
- **Lifecycle commands**: `mco start` (detached background gateway with
  health-checked startup), `mco restart`, `mco doctor` (end-to-end install
  diagnosis), `mco --version`.
- One-command installers (`curl | bash`, `iwr | iex`) with existing-install
  detection; Hermes-style install UX on the website and README.
- SECURITY.md, CodeQL, dependabot, release pipeline (PyPI + GHCR).

### Fixed
- Setup can no longer orphan the secret store (key is persisted before the
  store is created); locked-store warnings are single and actionable.
- `mco stop` no longer crashes (psutil was missing from dependencies).
- WebSocket honors `MCO_LOCAL_TOKEN` parity with HTTP auth; the worker's
  raw shell executor is opt-in (`MCO_ENABLE_SHELL_EXECUTOR`).
- Web agent list shows all orgs to the host operator (parity with
  `mco agents`).

### Changed
- Distribution renamed `mco` -> `batoncadence` (the CLI is still `mco`).
- Config home is global (`~/.mco/.env`): `mco` behaves the same from any
  directory.

## [0.1.0] - 2026-06-10

Initial MVP: job board with atomic leasing, multi-vendor executors
(claude/codex/gemini), approval gates, immutable audit trail, escalation,
DAG workflows, Drumline shared context, MCP server, ServiceNow/Dynatrace
connectors, embedded LocalStore, dashboard, 151-test suite.
