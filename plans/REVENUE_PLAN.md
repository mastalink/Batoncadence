# BatonCadence — First-Revenue Plan (solo founder)

**Drafted:** 2026-06-12 · Companion to [LAUNCH_PLAN.md](LAUNCH_PLAN.md) (channels/sequence)
and [docs/DEMO.md](../docs/DEMO.md) (the pitch in motion).

## The macro tailwind (use it in every pitch)

- **Gartner (May 2026):** uniform governance across AI agents fails; 40% of
  enterprise apps will embed agents by end of 2026; 40%+ of agentic projects
  risk cancellation by 2027 **without governance, observability, and ROI
  clarity**. We are the governance+observability layer.
- **EU AI Act, enforceable August 2026:** multi-agent orchestration in
  high-impact sectors is "high-risk" → requires **human-in-the-loop
  oversight, immutable audit trails, persistent identity**. That is
  literally `requires_approval`, `agent_job_events`, and the agent
  registry. *"Compliance-shaped software, two months before the deadline"*
  is the cold-email subject line for any EU prospect.
- Deloitte: only 1 in 5 companies has a mature agent-governance model.

## Revenue ladder (start at the bottom this week)

| Rung | What | Price | Effort | When |
|---|---|---|---|---|
| 1 | **Paid design-partner pilots** — white-glove install + 90 days of support + roadmap influence | $1.5k–3k/mo (per LAUNCH_PLAN hypothesis), 3-month minimum | Calls + the demo | **Now** — this is the business |
| 2 | **White-glove setup engagements** — one-off "we wire your fleet + ServiceNow in a week" | $2.5k–7.5k fixed | A few days each | Now, from the same calls |
| 3 | **GitHub Sponsors / support tiers** — community goodwill + enterprise-friendly $500–2k/mo tiers (the React Query playbook) | $0→low 4 figures/mo over months | Setup once | At repo-public day |
| 4 | **Enterprise license + support contract** — SLA, priority fixes, the connectors/SSO surface | $15k–30k/yr | Needs 1–2 reference pilots first | Month 3–6 |
| 5 | Hosted/managed gateway | TBD | High | Only if pilots demand it |

Solo-dev reality check from the research: most OSS maintainers who reach
meaningful revenue **combine 2+ streams**, and services contribute the
largest early jumps ($2k–8k/mo from consulting is well-documented). Rungs
1–2 are services anchored to your product — highest conversion, zero
infra.

## The 14-day sprint (everything here is unblocked today)

**Days 1–2 — close the credibility gaps** (see Gaps below):
demo video (screen-capture docs/DEMO.md Acts 1–4, no narration needed),
attach batoncadence.com to Cloudflare Pages, repo public + topics,
README hero GIF.

**Days 3–4 — the pilot kit:** one-pager PDF (the three pitches below +
the editions table + the EU AI Act paragraph), Calendly link,
`pilots@batoncadence.com` already live.

**Day 5 — warm outreach:** the Gartner-conference contacts (ROADMAP Phase
C names this), plus every ops/platform person you know in
ServiceNow/Dynatrace shops. Ask for 25 minutes, run DEMO.md live, end
with: *"I'm taking three design partners at pilot pricing — you get
white-glove install and the roadmap pen."*

**Week 2 — public launch** (LAUNCH_PLAN Phase 1): Show HN + r/LocalLLaMA +
r/selfhosted + MCP directory submissions, honest-first-comment ready.
Public launch feeds rungs 3+ and refills the pilot funnel.

**Rule for a solo founder:** product time only on what blocks a pilot
dollar. Everything else waits.

## The three pitches (memorize)

**One-liner:** *Every agent. One baton.* The governed job board for the AI
agents you already have.

**Elevator (30s):** "Companies are deploying Claude, Codex, Gemini, and
custom agents — and they have no shared control plane. BatonCadence is a
self-hosted job board those agents work from: every task is leased
atomically, can pause for human approval, lands in an append-only audit
trail, and feeds a shared memory so the fleet stops having amnesia. MIT
core, runs from one double-click, and the enterprise tier speaks
ServiceNow. We coordinate the agents you already have; we replace nothing."

**Per audience:**
- **Self-hosters:** "The free edition is the whole product. One
  double-click, no cloud account, and your agents share one memory."
- **Power users:** "Your Claude session can drop a job that your Codex
  worker executes overnight — with the research context attached
  automatically. It's MCP-native."
- **Ops buyers (the money):** "Nothing an agent does in production is
  un-audited, un-approved, or un-escalated. Incidents flow in from
  ServiceNow; closures flow back gated behind a human. The EU AI Act
  enforcement date is August — this is the checklist, self-hosted."

**Anti-positioning (verbatim, builds trust):** not an agent framework, not
a LangChain/CrewAI competitor — run those *inside* a BatonCadence job.

## Pilot qualification (say no fast)

Good pilot: runs ServiceNow or Dynatrace; already pays for 2+ agent
vendors; has a compliance or platform owner; EU exposure is a bonus.
Bad pilot: wants you to build their agents (that's a services rabbit
hole), wants hosted-only, wants a custom framework.

## Metrics

Week 2: 3 demo calls booked, 1 pilot verbally agreed.
Month 1: first pilot invoice sent. Month 3: 3 paying pilots, 1 public
reference, sponsors live. If month 3 shows zero pilot interest from 20+
qualified calls, the price point or the wedge is wrong — revisit, don't
push harder on the same door.
