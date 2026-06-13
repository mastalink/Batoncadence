-- ============================================================================
-- Scoped-token RBAC (June 2026)
-- ============================================================================
-- Adds the optional `scopes` column to the agent registry. Rows without
-- explicit scopes keep role-derived defaults (approver roles -> admin;
-- worker roles -> jobs/context read+write), so applying this migration
-- changes nothing until you register a token with --scope.
--
-- LocalStore (the embedded SQLite backend) needs no migration: rows are
-- JSON documents and pick up the field automatically.
-- ============================================================================

alter table agent_registry
    add column if not exists scopes jsonb;

comment on column agent_registry.scopes is
    'Explicit token scopes (e.g. ["jobs:read","context:read"]). NULL = role-derived defaults. "admin" = all scopes.';
