# Verification Evidence: Task EVIDENCE (including EVIDENCE-repair1)

**Run ID**: `mco-pipeline-improvements-20260927-01`  
**Task**: `EVIDENCE-repair1` ("Bind completion claims to real artifacts")  
**Base HEAD SHA**: `3eafe4596241d1ca016f6c94b443bc5ea7203e08`  
**Branch**: `score/mco-pipeline-improvements-20260927`  
**Worktree**: `C:\AI\mco-pipeline-score-work`  
**Timestamp**: `2026-09-27T20:31:00-04:00` (2026-09-28T00:31:00Z)  

---

## 1. Summary of Changes & Repairs

### A. Repair of Full-Board Read Across Remaining Capped Paths (EVIDENCE-repair1)
- **`src/mco/orchestrator/routes.py` (`get_recent_events`)**:
  - Removed `.limit(500)` on the `agent_jobs` query driving event enrichment and tenant filtering.
  - Event enrichment now accesses the entire board history (631+ jobs in local.db) without dropping audit events for jobs older than the top 500 rows.
- **`src/mco/orchestrator/admin_routes.py` (`export_evidence_pack`)**:
  - Removed `.limit(500)` on the `agent_jobs` query in `export_evidence_pack`.
  - Evidence packs generated for compliance now ingest and map all jobs on the board, ensuring zero truncation of job metadata across the full board.
- **Regression Unit Tests in `tests/test_evidence_binding_integrity.py`**:
  - Added `test_get_recent_events_reads_all_jobs_without_500_limit`: asserts that 600 jobs are queried without a limit and that events for job index 550 are enriched and retained.
  - Added `test_export_evidence_pack_reads_all_jobs_without_500_limit`: asserts that 600 jobs are queried without a limit and that evidence pack includes job metadata for job index 550.

### B. Evidence Verification & Artifact Binding (`src/mco/orchestrator/score_bridge.py`)
- **Stale-Head Rejection**:
  - Rejects worker completion payloads claiming an `expected_before_sha` that mismatches the actual expected before-SHA from the contract/worktree HEAD.
- **Strict Evidence Label Binding (No Fabricated Commit SHAs)**:
  - Eliminated the permissive fallback (`else: evidence[req] = new_sha`) that allowed arbitrary required evidence keys (such as `report` or `test_report`) to be silently populated with a git commit hash.
  - For `repository:write` tasks, `commit_sha` and `commit` continue to be bound to the verified git commit output from the live adapter.
  - Any additional evidence requirements (e.g. `report`, `test_report`) MUST be explicitly provided by the worker in `artifacts` with relative path and SHA-256 digest.
- **Path Traversal & Boundaries Protection**:
  - Rejects artifact paths containing traversal sequences (`..` in path components) or absolute paths.
  - Enforces that referenced artifact files reside strictly within permitted roots: either the Score `artifact_root` or the worktree path (specifically `docs/verification/` or within worktree bounds).
  - Rejects oversized artifact files (> 16MB).
  - Verifies that file content SHA-256 matches the claimed digest (case-insensitive comparison).
- **Read-Only Audit Artifact Traversal Hardening**:
  - In `ScoreBridge.artifacts()`, added path traversal checks (`..` rejection and `path.relative_to(self.root)`) alongside case-insensitive digest validation.

### C. Lineage Normalization Across Repairs (`src/mco/orchestrator/score_bridge.py` & `src/mco/orchestrator/score_conductor.py`)
- **Bridge Dependency Planning (`_lineage_satisfied`)**:
  - Evaluates the full repair chain via `self._lineage_info`. If any task in the lineage was accepted, the requirement is satisfied.
- **Conductor Launch Readiness (`Conductor.status`)**:
  - Evaluates `launch_requires` using lineage normalization (`_task_satisfied`), ensuring an accepted repair task satisfies the original launch requirement.

### D. Job Board Full Read Without 100-Row Loss (`src/mco/orchestrator/routes.py`, `client.py`, `mcp_server.py`)
- **Full-Board Retrieval in `GET /api/jobs`**:
  - Removed the hardcoded `.limit(100)` in `get_jobs()`. Added optional query parameter `limit: Optional[int] = None`.
  - When `limit` is omitted, all jobs on the board are returned without 100-row truncation loss.
- **Client & MCP Server Parameter Propagation**:
  - Updated `MCOClient.jobs(include_archived=..., limit=...)` in `client.py`.
  - Updated MCP tool `mco_jobs(include_archived=..., limit=...)` in `mcp_server.py`.
- **Duplicates Search Without 500-Row Truncation**:
  - Removed `.limit(500)` in `get_job_duplicates()` in `routes.py` to ensure duplicate checks search the full job history.

### E. Superseding Receipts Reconciliation Without Deleting History
- **MyMeals PR #3 Stale Review Job Reconciliation**:
  - Identified stale failed review job `baac2546-2732-4a02-bac5-514916348757` ("Review MyMeals PR #3: product and UI impact", failed due to muse access restriction).
  - Reconciled with superseding completed review job `51e999df-b66f-45c4-8281-ba82beac6f1d` ("UI/product review of MyMeals PR #3 (replaces blocked muse job baac2546)").
  - Bidirectional reassignment linkage:
    - `baac2546.reassigned_to_job_id = "51e999df-b66f-45c4-8281-ba82beac6f1d"`
    - `51e999df.reassigned_from_job_id = "baac2546-2732-4a02-bac5-514916348757"`
  - Safely archived `baac2546` via standard `mco_archive` tool, removing it from default board clutter while keeping its complete history and audit trail intact.

---

## 2. Test Verification Evidence & Raw Transcripts

All test suites executed in isolated worktree environment (`PYTHONPATH=src`):

### Full Test Suite Execution Command
```powershell
python -m pytest -o pythonpath=src -v tests/test_evidence_binding_integrity.py tests/test_score_evidence.py tests/test_score_bridge.py tests/test_routes.py tests/test_governance.py --junitxml=docs/verification/junit_evidence_repair1.xml
```

### Verified Raw Output
- **Total Tests**: 124 passing tests (0 failures, 0 errors)
- **Suite Breakdown**:
  - `tests/test_evidence_binding_integrity.py`: 9 passed
  - `tests/test_score_evidence.py`: 11 passed
  - `tests/test_score_bridge.py`: 35 passed
  - `tests/test_routes.py`: 29 passed
  - `tests/test_governance.py`: 40 passed
- **Duration**: 13.45s

### Verifiable Artifacts
1. **Raw Pytest Output Transcript**:
   - `docs/verification/pytest_evidence_repair1.txt`
   - Replicated to `C:\Users\masta\.mco\score-artifacts\score-runs\mco-pipeline-improvements-20260927-01\pytest_evidence_repair1.txt`
2. **JUnit XML Report**:
   - `docs/verification/junit_evidence_repair1.xml`
   - Replicated to `C:\Users\masta\.mco\score-artifacts\score-runs\mco-pipeline-improvements-20260927-01\junit_evidence_repair1.xml`

---

## 3. Policy & Constraint Compliance

1. **Zero Spent / Zero Deploy**: No metered tokens spent, no AWS operations, no cloud infrastructure mutations.
2. **Preserve Checkouts**: Only isolated worktree `C:\AI\mco-pipeline-score-work` modified.
3. **No Direct Git Commit**: Working tree modified as instructed; conductor commits allowed paths.
4. **No Protected Score Document Edits**: Score definitions and runtime database configurations untouched.
5. **Claude Exclusion**: Claude exclusion until Tuesday 11:00 AM preserved.
6. **No Main Merge**: Exclusively working on branch `score/mco-pipeline-improvements-20260927`.
