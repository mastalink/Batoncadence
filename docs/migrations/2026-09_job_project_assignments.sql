-- Human-reviewed project labels for the Projects console view.
-- Kept separate from agent_jobs so organizing work never mutates execution input.

create table if not exists job_project_assignments (
  job_id           text primary key,
  org_id           text not null default 'default',
  project_id       text not null check (char_length(project_id) between 1 and 80),
  project_name     text not null check (char_length(project_name) between 1 and 80),
  assigned_by      text not null,
  assigned_by_role text,
  updated_at       timestamptz not null default now()
);

create index if not exists idx_job_project_assignments_org_project
  on job_project_assignments (org_id, project_id);

-- Gateway access uses the service role after application-layer org checks.
-- Direct PostgREST clients receive no policy and cannot read/write this table.
alter table job_project_assignments enable row level security;
