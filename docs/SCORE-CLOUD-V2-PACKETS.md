# Score Cloud v2 — coding packets checklist

Companion to [`SCORE-CLOUD-V2.md`](./SCORE-CLOUD-V2.md). This document turns the
C0–C9 build order into coding packets with acceptance criteria and **offline
stub tests**. Nothing here deploys, creates cloud resources, handles credentials,
pushes, merges, or calls a paid provider.

Status: **packet checklist + stub tests only.** Implementing a packet is a
separate governed Score. Stub tests under `tests/test_score_cloud_c*_*.py` stay
skipped until the packet lands; they keep CI green and pin the intended
interface names.

Source design base: `main` at `ff4374d` (see SCORE-CLOUD-V2.md).

---

## Packet index

| Packet | Focus | Stub test |
|---|---|---|
| C0 | Human: Via CI billing + Postgres host choice | `tests/test_score_cloud_c0_human.py` |
| C1 | Store interface + Postgres Score store + parity | `tests/test_score_cloud_c1_store.py` |
| C2 | GitHub evidence verifier (shadow mode) | `tests/test_score_cloud_c2_github_evidence.py` |
| C3 | Scoped task credentials + bearer_guard | `tests/test_score_cloud_c3_scoped_credentials.py` |
| C4 | Issue-dispatch lane + one vendor canary | `tests/test_score_cloud_c4_issue_dispatch.py` |
| C5 | Conductor-owned merge + required status | `tests/test_score_cloud_c5_conductor_merge.py` |
| C6 | Cloud deploy of gateway + conductor + gate UI | `tests/test_score_cloud_c6_cloud_deploy.py` |
| C7 | Beast site agent (outbound only) | `tests/test_score_cloud_c7_site_agent.py` |
| C8 | API lane + cost reservations | `tests/test_score_cloud_c8_api_lane.py` |
| C9 | Cross-lane canary | `tests/test_score_cloud_c9_cross_lane.py` |

---

## C0 — Human prerequisites

**Delivers:** GitHub Actions billing fixed on `mastalink/via`; Postgres host chosen.

**Acceptance (no cloud deploy from agents):**
- [ ] A `Verify Via` workflow run exists on `codex/via-foundation` after billing fix.
- [ ] Written choice of Postgres host (existing Team-edition path / Supabase / RDS) recorded in the packet handoff — not applied here.

**Stub:** asserts the design doc names C0 and that this checklist exists.

---

## C1 — Postgres Score store behind one interface

**Delivers:** Store interface used by `score_bridge`, `score_conductor`, `score_sweep`; SQLite remains default; Postgres implementation + migration; parity suite.

**Acceptance:**
- [ ] One store interface; SQLite behavior unchanged for Appliance.
- [ ] Parity test: canary + repository-slice fixtures produce identical event sequences on both stores.
- [ ] Postgres cases gated to postgres-acceptance CI; no cloud deploy in this packet.
- [ ] Transaction boundaries preserved (plan+outbox, state transition+event).

**Stub interface placeholders:** `ScoreStore`, `SqliteScoreStore`, `PostgresScoreStore`, `score_store_parity_events`.

---

## C2 — GitHub evidence verifier (shadow mode)

**Delivers:** Verifier for `pull_request`, `check_runs`, `review` evidence; shadow mode only (report would-refuse; no merge).

**Acceptance:**
- [ ] Replays Via PRs #41–#46 and reports refusals for missing CI runs.
- [ ] Fork / unallowlisted app / wrong head SHA ignored; missing check fails closed.
- [ ] No merge, no status write in shadow mode.

**Stub interface placeholders:** `GitHubEvidenceVerifier`, `ShadowVerifyReport`, `verify_pull_request_evidence`.

---

## C3 — Scoped task credentials

**Delivers:** Task-scoped expiring credentials; `bearer_guard` verifier.

**Acceptance:**
- [ ] Expired, replayed, and cross-task tokens rejected.
- [ ] Appliance static bearer unchanged when scoped credentials are disabled.
- [ ] No long-lived master token in examples or tests.

**Stub interface placeholders:** `mint_task_credential`, `verify_task_credential`, `TaskCredentialClaims`.

---

## C4 — Issue-dispatch lane adapter

**Delivers:** Thin issue→PR dispatch adapter + one vendor canary (dark).

**Acceptance:**
- [ ] One packet dispatched as an issue, returned as a draft PR, verified offline with fixtures.
- [ ] Vendor trigger behind explicit config; dark by default.
- [ ] No live vendor API calls in unit tests.

**Stub interface placeholders:** `IssueDispatchAdapter`, `DispatchReceipt`, `vendor_canary_fixture`.

---

## C5 — Conductor-owned merge

**Delivers:** Required `bitcadence/score` status; conductor merge effect behind a grant.

**Acceptance:**
- [ ] PR without acceptance cannot merge under the protection rules described in the design.
- [ ] Force-push after review voids acceptance.
- [ ] Workers never gain merge capability; tests use fakes only.

**Stub interface placeholders:** `ConductorMergeEffect`, `required_score_status`, `void_acceptance_on_new_head`.

---

## C6 — Cloud deploy (dark checklist only here)

**Delivers:** Gateway + conductor + gate UI on always-on host.

**Acceptance (this repo packet is checklist-only):**
- [ ] `/readyz` green with Beast powered off — proven in a later governed deploy Score, not in these stubs.
- [ ] Stub test only checks that deploy is out of scope for offline CI (skip).

**Stub:** permanently skipped offline; documents the live probe name `readyz_with_beast_off`.

---

## C7 — Beast site agent

**Delivers:** Outbound-only site agent; local lane lease/resume.

**Acceptance:**
- [ ] Local lane leases, loses network, resumes without duplicate effects (fake clock/network in tests).
- [ ] No inbound ports required on Beast for the control plane.

**Stub interface placeholders:** `SiteAgentSession`, `resume_without_duplicate_effects`.

---

## C8 — API lane + cost reservations

**Delivers:** API lane worker + atomic cost reservations.

**Acceptance:**
- [ ] Reservation atomic under concurrency.
- [ ] Unknown outcome keeps its reservation.
- [ ] budget_cents enforcement path covered with fakes; no paid calls.

**Stub interface placeholders:** `ApiLaneWorker`, `reserve_cost_cents`, `CostReservation`.

---

## C9 — Cross-lane canary

**Delivers:** One run: cloud-session builds, local reviews, API triages; Beast off mid-run; complete evidence trail.

**Acceptance:**
- [ ] Fixture-driven canary with fake lanes produces a complete evidence trail.
- [ ] Beast-off mid-run does not duplicate effects or false-accept.
- [ ] Dark by default; no cloud:change.

**Stub interface placeholders:** `CrossLaneCanary`, `complete_evidence_trail`.

---

## Global rules for every packet

1. Dark by default; SQLite Appliance behavior unchanged until explicitly configured.
2. No cloud resources, terraform apply, credentials, push, merge, or deploy in stub/CI tests.
3. No real vendor or model API calls in tests — deterministic fakes and recorded fixtures only.
4. Builder and reviewer are different identities (and different vendor families when lanes apply).
5. New Stealth examples and fixtures use abstract resources only — never `C:/AI/...` Beast paths.

When a packet is implemented, flip its stub from `skip` to real assertions in the same file and cite the Score run that built it.
