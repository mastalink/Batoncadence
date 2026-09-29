# Packet C2 (offline) — Shadow GitHub evidence verifier

**Status:** fixture-backed shadow verifier. No live App tokens, no merge, no
status writes.

## Artifact claim shape

```json
{
  "repo": "mastalink/via",
  "number": 41,
  "head_sha": "<40-hex>",
  "base_ref": "codex/via-foundation",
  "expected_base_sha": "<40-hex optional>",
  "required_checks": ["Verify Via"],
  "author_login": "copilot-swe-agent[bot]",
  "reviewer_login": "claude-reviewer"
}
```

Fixtures under `tests/fixtures/github_evidence/` use stems `pr-N`, `checks-N`,
`review-N`.

## Shadow report

`ShadowVerifyReport` fields: `repo`, `number`, `head_sha`, `accepted`,
`would_refuse`, `checked`, `notes`. Always `mode=shadow`, `mutates_github=false`.

## Fail-closed rules (v0)

- Missing check run for a required name → `missing_ci` / `missing_check:…`
- Unallowlisted check app → ignored; check still missing
- Fork head → `fork_head_ignored`
- Wrong head SHA on check or review → refuse
- Author == reviewer or same vendor family → refuse

## Acceptance (this PR)

- [x] Replays fixture stand-ins for Via PRs #41–#46; missing CI refuses.
- [x] No live GitHub API / App tokens.
