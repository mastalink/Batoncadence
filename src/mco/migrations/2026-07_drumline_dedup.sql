-- ═══════════════════════════════════════════════════════════════════════
-- MCOrchestr8 Drumline Dedup Migration (July 2026)
-- Adds content_hash to agent_context so remember() can skip inserting
-- entries whose title|content|role already exist (audit finding M-08).
-- Idempotent: safe to run more than once.
-- ═══════════════════════════════════════════════════════════════════════

alter table agent_context
  add column if not exists content_hash text;

create index if not exists idx_agent_context_content_hash
  on agent_context (content_hash);
