# Verification Evidence: Task CAPACITY

**Run ID**: `mco-pipeline-improvements-20260927-01`  
**Task**: `CAPACITY` ("Enforce provider availability separately from online sockets")  
**Base HEAD SHA**: `368acab0447662a691d52db65271ad642903e326`  
**Branch**: `score/mco-pipeline-improvements-20260927`  
**Worktree**: `C:\AI\mco-pipeline-score-work`  
**Timestamp**: `2026-09-27T20:00:30-04:00` (2026-09-28T00:00:30Z)  

---

## 1. Summary of Changes

### A. Presence & Capacity State (`src/mco/orchestrator/presence.py`)
- Added capacity pause schedule and metadata constants:
  - `CLAUDE_PAUSE_UNTIL = "2026-09-29T11:00:00-04:00"` (Tuesday 11:00 AM America/New_York)
  - `CLAUDE_PAUSE_REASON = "Claude identities unavailable until 2026-09-29 11:00 America/New_York; no new Claude assignments"`
  - `CLAUDE_USAGE_OBSERVED_AT = "2026-09-27T15:15:00Z"`
  - `CLAUDE_EXCLUDED_INSTANCES = frozenset({"claude-beast", "claude-mac"})`
- Added helper functions `get_default_capacity_schedule()` and `is_agent_quota_eligible()`.
- Updated `describe_fleet()`:
  - Decorates each fleet row with `unavailable_until`, `reason`, `unavailable_reason`, `usage_observed_at`, and `quota_eligible`.
  - Distinguishes connected socket status (`connected`: bool) from quota eligibility (`quota_eligible`: bool).
  - Preserves active leases: if an agent holds an active lease (`instance in working`), its `state` remains `WORKING`, regardless of quota eligibility.
  - Automatically rechecks capacity upon pause expiry (`now >= unavailable_until`), restoring `quota_eligible = True`.
- Updated `available_roles()` with optional `require_quota=False` preserving backward compatibility while allowing callers to filter by capacity eligibility.

### B. Run-Start Target Resolver (`src/mco/orchestrator/score_resolver.py`)
- Integrated `is_agent_quota_eligible()` and `quota_eligible` check into `resolve_score_targets()`.
- Excludes paused Claude identities (`claude-beast`, `claude-mac`) from score target assignment before Tuesday 11:00 AM ET.
- Allows unpaused alternative workers for the same role to be assigned.
- Upon pause expiry (`now >= 2026-09-29T11:00:00-04:00`), Claude identities are automatically rechecked and admitted.

### C. Fenced Lease & Inbox Eligibility (`src/mco/orchestrator/leases.py` & `src/mco/orchestrator/routes.py`)
- Added `is_lease_eligible(db, owner, now=None)` to `leases.py`.
- Enforced lease eligibility in `acquire_lease()`: paused/unavailable workers cannot acquire new leases.
- Preserved existing active leases: `renew_lease` and `fenced_update` are not blocked, allowing currently held leases to finish or expire naturally.
- Updated `_pending_for_agent()` in `routes.py`: paused workers polling their inbox receive an empty list (`[]`).

### D. Console UI & Static Assets (`src/mco/console_src/` & `src/mco/static/console.html`)
- Updated `src/mco/console_src/2ed3f6b1-e1c6-43fc-8b29-31917195cbd5.js` (Agent Fleet screen):
  - Added role header quota summary: `X of Y online (Z quota-eligible)`.
  - Added visual badges distinguishing `connected socket` from `quota paused` vs `quota eligible`.
  - Displays pause reason and resume time for paused agents.
- Updated `src/mco/console_src/43b328d0-9d0e-4fce-a105-be0a939d7e48.js` (Overview screen):
  - Displays quota-eligible agent count in the "Agents online" stat card when agents are paused.
- Rebuilt `src/mco/static/console.html` using `python scripts/build_console.py build` and verified round-trip with `build_console.py verify`.

---

## 2. Test Verification Evidence

All test suites executed cleanly in isolated worktree environment (`PYTHONPATH=src`):

### Command 1: Console Bundle Verification
```powershell
python scripts/build_console.py verify
```
**Output:**
```
verify OK - 9 sources round-trip; 0 differ from current HTML
```

### Command 2: Capacity Enforcement & Integration Suite
```powershell
$env:PYTHONPATH="src"; python -m pytest tests/test_capacity_enforcement.py
```
**Output:**
```
tests/test_capacity_enforcement.py ..........                            [100%]
10 passed in 0.47s
```

### Command 3: Full Presence, Resolver, Lease, Console, and Capacity Suite
```powershell
$env:PYTHONPATH="src"; python -m pytest tests/test_presence_state.py tests/test_score_resolver.py tests/test_leases.py tests/test_console.py tests/test_capacity_enforcement.py
```
**Output:**
```
tests/test_presence_state.py .............                               [ 17%]
tests/test_score_resolver.py ................                            [ 39%]
tests/test_leases.py .................                                   [ 62%]
tests/test_console.py ..................                                 [ 86%]
tests/test_capacity_enforcement.py ..........                            [100%]
74 passed in 2.57s
```

---

## 3. Preservation and Policy Compliance

1. **Zero Spent / Zero Deploy**: No metered tokens spent, no cloud mutation performed.
2. **Preserve Checkouts**: Only isolated worktree `C:\AI\mco-pipeline-score-work` modified.
3. **No Direct Git Commit**: Changes staged in working tree; conductor will create commit per protocol.
4. **Preserve Tokens / Identities**: All existing tokens, hashes, and identity tables preserved.
5. **No Main Merge**: Working exclusively on `score/mco-pipeline-improvements-20260927`.
