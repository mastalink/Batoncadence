-- ═══════════════════════════════════════════════════════════════════════
-- MCOrchestr8 Multi-Tenancy Migration (June 2026)
-- Org scoping for the hosted-SaaS control plane: every agent, job, audit
-- event, and context entry belongs to an org. Existing rows backfill to the
-- 'default' org, so single-tenant/self-host deployments are unaffected.
-- Idempotent: safe to run more than once.
-- ═══════════════════════════════════════════════════════════════════════

alter table agent_registry   add column if not exists org_id text not null default 'default';
alter table agent_jobs       add column if not exists org_id text not null default 'default';
alter table agent_job_events add column if not exists org_id text not null default 'default';
alter table agent_context    add column if not exists org_id text not null default 'default';

create index if not exists idx_agent_jobs_org       on agent_jobs (org_id, status);
create index if not exists idx_agent_registry_org   on agent_registry (org_id);
create index if not exists idx_agent_job_events_org on agent_job_events (org_id, job_id);
create index if not exists idx_agent_context_org    on agent_context (org_id, created_at desc);
