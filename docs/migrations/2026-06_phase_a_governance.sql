-- ═══════════════════════════════════════════════════════════════════════
-- MCOrchestr8 Phase A Governance Migration (June 2026)
-- Adds: human-in-the-loop approval gates, retry/escalation paths, and the
-- immutable agent_job_events audit trail.
-- Idempotent: safe to run more than once.
-- ═══════════════════════════════════════════════════════════════════════

-- ── agent_jobs: governance columns ──────────────────────────────────────
alter table agent_jobs add column if not exists requires_approval boolean not null default false;
alter table agent_jobs add column if not exists approved_by       text;
alter table agent_jobs add column if not exists max_retries       int not null default 0;
alter table agent_jobs add column if not exists retry_count       int not null default 0;
alter table agent_jobs add column if not exists escalate_to_role  text;

-- ── Table: agent_job_events ─────────────────────────────────────────────
-- Append-only audit trail. One row per job mutation (create, lease, status
-- change, approval decision, retry, escalation). Never updated or deleted.
create table if not exists agent_job_events (
  id          bigint generated always as identity primary key,
  job_id      text not null,
  event       text not null,            -- created | leased | status:<x> | approved | rejected | retried | escalated
  actor_id    text,                     -- instance_id, or 'system'
  actor_role  text,
  detail      jsonb default '{}'::jsonb,
  created_at  timestamptz not null default now()
);

create index if not exists idx_agent_job_events_job
  on agent_job_events (job_id, created_at);

-- ── Immutability enforcement ────────────────────────────────────────────
-- The audit trail is tamper-evident: UPDATE and DELETE are rejected at the
-- database level, so even a service_role key cannot quietly rewrite history.
create or replace function mco_audit_block_mutation()
returns trigger
language plpgsql
as $$
begin
  raise exception 'agent_job_events is append-only: % is not allowed', tg_op;
end;
$$;

drop trigger if exists trg_agent_job_events_immutable on agent_job_events;
create trigger trg_agent_job_events_immutable
  before update or delete on agent_job_events
  for each row execute function mco_audit_block_mutation();
