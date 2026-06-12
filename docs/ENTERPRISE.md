# Enterprise Guide: Editions, RBAC & SSO

BatonCadence is open core in a single MIT-licensed codebase. Every edition
runs the same code; the edition decides which surfaces are active. Drumline
(shared context) is first-class in **every** edition — collective memory is
the product, not an upsell.

## Editions

| Capability | community | team | enterprise |
|---|:---:|:---:|:---:|
| Job board, governance (audit / approvals / escalation) | ✅ | ✅ | ✅ |
| DAG workflows (`mco workflow`) | ✅ | ✅ | ✅ |
| **Drumline shared context** (embedded LocalStore) | ✅ | ✅ | ✅ |
| Dashboard + MCP server | ✅ | ✅ | ✅ |
| Shared gateway (cloud database) | — | ✅ | ✅ |
| Multi-org tenancy | — | ✅ | ✅ |
| Scoped-token RBAC management | — | ✅ | ✅ |
| Enterprise connectors (ServiceNow, Dynatrace, webhooks) | — | — | ✅ |
| Trusted-header SSO delegation | — | — | ✅ |
| Audit export | — | — | ✅ |

**Resolution:** set `MCO_EDITION=community|team|enterprise` to pin a posture
explicitly. When unset, the edition is **inferred from configuration** so
existing installs never hit a surprise 403: a configured connector or
trusted-header auth implies `enterprise`; a cloud database implies `team`;
otherwise `community`. Check with:

```bash
mco edition
```

Gating is honor-system by design (the code is MIT). Pinning matters because
it is *deterministic*: `MCO_EDITION=community` reliably disables every
enterprise surface, which is also how you verify a locked-down posture.

## Scoped-token RBAC

Every API endpoint declares the scopes it requires. A token's scopes come
from its `agent_registry` row; rows without explicit scopes get
**role-derived defaults** that match pre-RBAC behavior exactly:

- Approver roles (`MCO_APPROVER_ROLES`, default `human,admin,operator`) → `admin` (all scopes)
- Every other role → the worker default set:
  `jobs:read`, `jobs:write`, `context:read`, `context:write`, `agents:read`, `integrations:read`

### Scope vocabulary

| Scope | Grants |
|---|---|
| `jobs:read` | List jobs, poll pending, read audit trails |
| `jobs:write` | Create, lease, and update jobs |
| `jobs:approve` | Approve / reject / retry jobs at the human gate |
| `context:read` | Recall Drumline shared context |
| `context:write` | Write Drumline entries (`remember`) |
| `agents:read` | List registered agents and presence |
| `integrations:read` | List connector health; trigger sync (with `jobs:write`) |
| `integrations:manage` | Run connector control actions directly |
| `admin` | Wildcard — satisfies every check |

### Issuing scoped tokens

```bash
# A read-only observer for a wallboard or reporting job:
mco register --name wallboard --role viewer --scope jobs:read --scope agents:read

# A worker that may execute jobs but never write memory:
mco register --name ci-bot --role codex --scope jobs:read --scope jobs:write

# Full access:
mco register --name ops-admin --role admin --scope admin
```

Scope checks are *additive* to the existing dropbox rules (you can only
lease/update jobs addressed to you) and approver-role gates — defense in
depth, not a replacement.

Cloud databases need one migration (the embedded LocalStore needs nothing):

```sql
-- docs/migrations/2026-06_scoped_tokens.sql
alter table agent_registry add column if not exists scopes jsonb;
```

## Trusted-header SSO delegation

BatonCadence does not implement SAML or OIDC. Instead it **delegates identity
to the SSO reverse proxy you already run** — Cloudflare Access, oauth2-proxy,
Authelia, Pomerium, Tailscale Serve — which handles your IdP, MFA, and SCIM,
and asserts the authenticated user via headers. ~200 lines of code instead of
a quarter of protocol work, and the proxy is the battle-tested part.

### Configuration

```bash
MCO_EDITION=enterprise
MCO_TRUSTED_HEADER_AUTH=true            # default off; never enable without a proxy in front
MCO_TRUSTED_HEADER_SECRET=<random>      # strongly recommended, see below
MCO_TRUSTED_HEADER_USER=X-Forwarded-User       # header carrying the identity
MCO_TRUSTED_HEADER_ROLE=X-Forwarded-Role       # optional role header
MCO_TRUSTED_HEADER_DEFAULT_ROLE=human          # role when no role header present
MCO_TRUSTED_HEADER_ORG=default                 # org the SSO users belong to
```

Examples per proxy:

| Proxy | `MCO_TRUSTED_HEADER_USER` |
|---|---|
| oauth2-proxy | `X-Forwarded-User` (default) |
| Cloudflare Access | `Cf-Access-Authenticated-User-Email` |
| Authelia | `Remote-User` |
| Pomerium | `X-Pomerium-Claim-Email` |

### Security requirements — read before enabling

1. **The gateway must not be directly reachable.** Bind it to localhost or a
   private network; only the proxy may connect. If a client can reach the
   gateway directly, identity headers are attacker-controllable.
2. **The proxy must strip/overwrite inbound identity headers.** Every proxy
   above does this by default — verify yours does.
3. **Set `MCO_TRUSTED_HEADER_SECRET`.** The proxy must add the header
   `X-MCO-Proxy-Secret: <value>` to upstream requests. BatonCadence compares
   it in constant time and silently ignores identity headers when it is
   missing or wrong — proving the request actually traversed the proxy even
   if requirement 1 is ever misconfigured.

Agents and workers keep using bearer tokens unchanged; trusted headers are
evaluated first and only for requests that carry them. SSO users authenticate
as `sso:<user>` with role `human` by default (an approver), so the dashboard
works for your whole team with zero token handling.

## Verifying a posture

```bash
MCO_EDITION=community mco serve   # enterprise surfaces deterministically 403
mco edition                       # print the active edition + feature matrix
pytest tests/test_rbac.py         # the RBAC/SSO/edition test matrix
```
