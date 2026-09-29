# Score Cloud v2 — offline packet notes (Stealth E–H)

These files document offline implementations that land **without** editing
`docs/SCORE-CLOUD-V2.md` or `docs/SCORE-CLOUD-V2-PACKETS.md`, so merge order with
draft PRs #119 / #120 stays clean.

| Packet | Note | Code | Tests |
|---|---|---|---|
| C1 | `C1-fake-score-store.md` | `mco.orchestrator.score_cloud.store` | `tests/test_score_cloud_eh_c1_fake_store.py` |
| C2 | `C2-shadow-evidence-verifier.md` | `mco.orchestrator.score_cloud.github_evidence` | `tests/test_score_cloud_eh_c2_shadow_verifier.py` |
| C8 | `C8-cost-reservation-mocks.md` | `mco.orchestrator.score_cloud.cost_reservation` | `tests/test_score_cloud_eh_c8_cost_reservation.py` |
| G (hygiene) | — | — | `tests/test_examples_scores_hygiene.py` |
