# Verification Evidence: Task EVIDENCE

**Run ID**: `mco-pipeline-improvements-20260927-01`  
**Task**: `EVIDENCE` ("Bind completion claims to real artifacts")  
**Base HEAD SHA**: `09ebb4f4c373b159747335ce67dddd12360f9e0e`  
**Branch**: `score/mco-pipeline-improvements-20260927`  
**Worktree**: `C:\AI\mco-pipeline-score-work`  
**Timestamp**: `2026-09-27T20:18:00-04:00` (2026-09-28T00:18:00Z)  

---

## 1. Summary of Changes

### A. Evidence Verification & Artifact Binding (`src/mco/orchestrator/score_bridge.py`)
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

### B. Lineage Normalization Across Repairs (`src/mco/orchestrator/score_bridge.py` & `src/mco/orchestrator/score_conductor.py`)
- **Bridge Dependency Planning (`_lineage_satisfied`)**:
  - Updated `_lineage_satisfied(dep_id)` to evaluate the full repair chain via `self._lineage_info`. If any task in the lineage was accepted, the requirement is satisfied.
- **Conductor Launch Readiness (`Conductor.status`)**:
  - Updated `status()` in `score_conductor.py` to evaluate `launch_requires` using lineage normalization (`_task_satisfied`), ensuring an accepted repair task satisfies the original launch requirement.

### C. Job Board Full Read Without 100-Row Loss (`src/mco/orchestrator/routes.py`, `client.py`, `mcp_server.py`)
- **Full-Board Retrieval in `GET /api/jobs`**:
  - Removed the hardcoded `.limit(100)` in `get_jobs()`. Added optional query parameter `limit: Optional[int] = None`.
  - When `limit` is omitted, all jobs on the board (619+ rows) are returned without 100-row truncation loss.
- **Client & MCP Server Parameter Propagation**:
  - Updated `MCOClient.jobs(include_archived=..., limit=...)` in `client.py`.
  - Updated MCP tool `mco_jobs(include_archived=..., limit=...)` in `mcp_server.py`.
- **Duplicates Search Without 500-Row Truncation**:
  - Removed `.limit(500)` in `get_job_duplicates()` in `routes.py` to ensure duplicate checks search the full job history.

### D. Superseding Receipts Reconciliation Without Deleting History
- **MyMeals PR #3 Stale Review Job Reconciliation**:
  - Identified stale failed review job `baac2546-2732-4a02-bac5-514916348757` ("Review MyMeals PR #3: product and UI impact", failed due to muse access restriction).
  - Reconciled with superseding completed review job `51e999df-b66f-45c4-8281-ba82beac6f1d` ("UI/product review of MyMeals PR #3 (replaces blocked muse job baac2546)").
  - Established bidirectional reassignment linkage:
    - `baac2546.reassigned_to_job_id = "51e999df-b66f-45c4-8281-ba82beac6f1d"`
    - `51e999df.reassigned_from_job_id = "baac2546-2732-4a02-bac5-514916348757"`
  - Safely archived `baac2546` via standard `mco_archive` tool, removing it from default board clutter while keeping its complete history and audit trail intact.

---

## 2. Test Verification Evidence

All test suites executed cleanly in isolated worktree environment (`PYTHONPATH=src`):

### Suite 1: Evidence Binding Integrity, Stale-Head, Path Traversal, and Full-Read
```powershell
python -m pytest -o pythonpath=src tests/test_evidence_binding_integrity.py
```
**Results:**
```
tests/test_evidence_binding_integrity.py .......                         [100%]
7 passed, 45 warnings in 4.21s
```
Covering:
- `test_stale_head_in_worker_output_rejected`: Rejection of stale `expected_before_sha` claims.
- `test_missing_evidence_label_rejected_without_fabricating_commit_sha`: Rejection of missing required evidence without substituting commit SHA.
- `test_path_traversal_in_artifact_path_rejected`: Rejection of `..` path traversal in artifact claims.
- `test_digest_mismatch_in_artifact_rejected`: Rejection of artifact digest mismatches.
- `test_real_artifact_in_verification_dir_successfully_bound`: Successful binding of real verification reports in `docs/verification/`.
- `test_lineage_normalization_in_conductor_launch_requires`: Successful launch requirement satisfaction via accepted repair task.
- `test_get_jobs_reads_all_rows_without_100_row_loss`: Successful retrieval of 150/150 jobs without 100-row loss, and respect for explicit `limit` parameter.

### Suite 2: Core Regression Test Suites
```powershell
python -m pytest -o pythonpath=src tests/test_score_evidence.py tests/test_score_bridge.py tests/test_routes.py tests/test_governance.py
```
**Results:**
```
115 passed in 10.38s
```

Total: 122 passing tests.

---

## 3. Policy & Constraint Compliance

1. **Zero Spent / Zero Deploy**: No metered tokens spent, no AWS operations, no cloud infrastructure mutations.
2. **Preserve Checkouts**: Only isolated worktree `C:\AI\mco-pipeline-score-work` modified.
3. **No Direct Git Commit**: Working tree modified as instructed; conductor commits allowed paths.
4. **No Protected Score Document Edits**: Score definitions and runtime database configurations untouched.
5. **Claude Exclusion**: Claude exclusion until Tuesday 11:00 AM preserved.
6. **No Main Merge**: Exclusively working on branch `score/mco-pipeline-improvements-20260927`.
