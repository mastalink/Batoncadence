-- ═══════════════════════════════════════════════════════════════════════
-- MCOrchestr8 Drumline Migration (June 2026)
-- Shared context substrate: one collective memory all agents read/write.
-- Entries come from explicit agent writes (mco_remember) and automatic
-- distillation of completed jobs (prompt -> outcome handoffs).
-- Idempotent: safe to run more than once.
-- ═══════════════════════════════════════════════════════════════════════

create table if not exists agent_context (
  id            uuid primary key default gen_random_uuid(),
  scope         text not null default 'global',   -- global | role | job
  role          text,                             -- role affinity (boosts recall for that role)
  kind          text not null default 'fact',     -- fact | decision | lesson | handoff | artifact
  title         text not null,
  content       text not null,
  tags          text[] default '{}',
  source_job_id text,                             -- set for distilled job outcomes
  created_by    text,                             -- instance_id or 'system'
  weight        real not null default 1.0,        -- recall multiplier (0.1 - 5.0)
  created_at    timestamptz not null default now()
);

create index if not exists idx_agent_context_recent
  on agent_context (created_at desc);
create index if not exists idx_agent_context_role
  on agent_context (role);
create index if not exists idx_agent_context_source_job
  on agent_context (source_job_id);
