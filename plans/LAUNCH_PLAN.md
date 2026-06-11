# BatonCadence — Launch & Marketing Plan

**Drafted:** 2026-06-10 · **Owner:** Joe · **Site:** `website/` → Cloudflare Pages

## Positioning

**One line:** *Every agent. One baton.* — the governed job board for the AI
agents you already have.

**The wedge:** every competitor sells a framework for *building* agents.
Nobody owns "the control plane for agents you already run" — Claude Desktop,
Codex CLI, Gemini, custom workers — with the three things the December 2025
Gartner validation said enterprises require before agents touch production:
**human approval gates, an immutable audit trail, escalation paths.**

**The moat story:** Mythos. Shared memory that makes the whole mesh smarter
with every job — original, deterministic, auditable, and fully present in the
free edition. The pitch writes itself: *"your agent fleet has amnesia."*

**Anti-positioning (say what we are not):** not a LangChain competitor, not
an agent framework, not another RAG vector store. We coordinate; we don't
replace.

## Audiences (in funnel order)

1. **Self-hosters / r/LocalLLaMA crowd** — want local-first, MIT, no cloud
   account. They generate stars, issues, and credibility. Hook: Mythos +
   one-click install + "the free edition is the full product."
2. **Dev-tool power users** — already run 3+ agent CLIs, feel the
   coordination pain daily. Hook: the dropbox model + MCP tools inside
   Claude Desktop.
3. **IT ops / platform engineers (the buyers)** — ServiceNow/Dynatrace
   shops. Hook: approval gates, audit trail, kill switch, escalation bridge.
   These become the pilot pipeline (Phase C of ROADMAP.md).

## Launch sequence

### Phase 0 — Pre-flight (this week)
- [x] **LICENSE file** — done 2026-06-10: MIT, copyright Joe Arroyo
- [ ] Register domain (`batoncadence.dev` or `.com`) + set up
      `pilots@` forwarding (the site's enterprise CTA already points there)
- [ ] Deploy site to Cloudflare Pages, connect repo for auto-deploy
- [ ] Make the GitHub repo public, add topics
      (`agents`, `orchestration`, `mcp`, `self-hosted`, `ai-governance`)
- [ ] README hero section with a GIF of the console + the hero terminal
- [ ] 2–3 min demo video: install.bat → console → approve a gated job →
      audit trail → Mythos recall (screen capture, no narration needed)

### Phase 1 — Community launch (week 2)
- **Show HN:** "Show HN: BatonCadence — a governed job board for AI agents,
  with shared memory (MIT, local-first)". Post early Tuesday–Thursday ET.
  First comment: the honest architecture story (PostgREST-dialect embedded
  store, why no embeddings in Mythos, the dad-installer test).
- **r/LocalLLaMA + r/selfhosted:** angle = "the free edition is the whole
  product, runs from one double-click, no cloud." These communities punish
  hidden paywalls — our editions story is genuinely clean, lead with it.
- **MCP ecosystem:** submit the MCP server to the MCP servers directory and
  awesome-mcp lists; agents-coordinating-agents via Claude Desktop is a
  native demo of MCP's value.
- **X/LinkedIn thread:** the hero terminal narrative as a 60-sec screen
  recording. LinkedIn version targets the ITSM angle for ops folks.

### Phase 2 — Content engine (weeks 3–8, one piece/week)
1. "Your agent fleet has amnesia" — the Mythos design essay (why
   deterministic scoring beat embeddings; auditability as a feature)
2. "The dropbox model" — why agents-as-mail beats agents-as-functions
3. "An audit trail your auditors will believe" — append-only enforcement
   at the storage layer, local and cloud
4. "We made our installer pass the Dad test" — the install.bat story
   (genuinely differentiated dev-tool content; people share this)
5. "Gating ServiceNow writes behind a human" — the enterprise teaser
6. Comparison page: BatonCadence vs CrewAI vs AutoGen vs n8n (honest:
   "use them *inside* a BatonCadence job")

### Phase 3 — Pilot conversion (weeks 4–12)
- Re-engage the Gartner conference contacts (per ROADMAP Phase C) with the
  one-pager + demo video; offer white-glove pilots: we run the install call
- Target 3–5 design partners from ServiceNow/Dynatrace shops in inbound
- Pilot feedback defines the 1.0 paywall line (likely: multi-tenancy,
  SSO/RBAC, connectors stay source-available; core + Mythos stay MIT)

## Pricing hypothesis (validate in pilots, don't publish yet)

- **Local:** free forever, MIT. The funnel and the community moat.
- **Team:** free, BYO Postgres. Converts to hosted later if demand appears.
- **Enterprise:** $1.5k–3k/mo per org pilot pricing — anchored to ITSM
  connector + governance value, not per-seat (agents aren't seats).

## Metrics that matter

- Week 1: GitHub stars (>200 = HN front page worked), installer downloads
- Month 1: weekly-active gateways (add an opt-in, documented, anonymous
  ping — be loud about privacy or skip it), Discord/Discussions activity
- Month 3: 3 active pilots, 1 reference customer for the site

## Risks / honesty checks

- ~~The repo's author field still says "DeepMind team" in pyproject.toml~~
  fixed 2026-06-10.
- ~~No LICENSE file~~ fixed 2026-06-10 (MIT, Joe Arroyo).
- `pilots@batoncadence.dev` must exist before the site ships, or swap the
  mailto for a GitHub Discussions link.
- Demo video must show real software, no mockups — this crowd checks.
