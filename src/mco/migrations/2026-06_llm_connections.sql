-- ============================================================================
-- LLM Provider Connections (June 2026)
-- ============================================================================
-- Named connections to LLM providers (Anthropic, OpenAI, Gemini, or a custom
-- OpenAI-compatible endpoint), managed from the Control Panel ("Settings ->
-- Model Connections"). Metadata only - the API key itself is never stored in
-- this table. It lives in the same place every other secret in BatonCadence
-- lives (the operator's config home / encrypted secret store), keyed by this
-- row's id, and is never echoed back over the API.
--
-- LocalStore (the embedded SQLite backend) needs no migration: rows are JSON
-- documents and this table is created automatically on first use.
-- ============================================================================

create table if not exists llm_connections (
  id          uuid not null default gen_random_uuid() primary key,
  name        text not null,
  provider    text not null,           -- anthropic | openai | gemini | custom
  base_url    text,                    -- only meaningful for provider=custom
  model       text,
  org_id      text,
  created_at  timestamptz not null default now()
);

create index if not exists idx_llm_connections_org
  on llm_connections (org_id);
