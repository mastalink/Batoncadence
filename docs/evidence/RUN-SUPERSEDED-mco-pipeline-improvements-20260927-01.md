# Run superseded: mco-pipeline-improvements-20260927-01

**Status:** superseded, 2026-09-29 (Chief decision on job 4172a8ab / 581afb81-1da2-4a9a-bd81-d0fe1bd3e86f)

## What happened

This Score run got stuck: the EVIDENCE-repair1 task (commit `15e0239f`) passed an
independent review as technically CLEAN, but the reviewer correctly refused to
force-accept the verdict inside the Score, since that would have overridden the
conductor. Known lesson from prior runs: a blocked Score run does not recover on
its own — the fix is to start a fresh `run_id`, not to keep nudging this one.

## Disposition

- The reviewed pagination fixes (commits `3eafe45` and `15e0239f` — removal of the
  hardcoded `.limit(100)` / `.limit(500)` caps on job/event pagination) were
  cherry-picked out of this branch and landed as a normal PR against public
  BitCadence: https://github.com/mastalink/BitCadence/pull/124. That PR carries
  its own tests and its own review; it is not gated on this run's stuck
  conductor state.
- No acceptance is being forged for this run. It is being marked superseded, not
  completed.
- The remaining work on this branch — the capacity scheduler (`09ebb4f`,
  "Enforce provider availability separately from online sockets") and the
  review-artifact sync — is intentionally left behind. It waits for Score Cloud
  v2's git-native evidence path rather than being force-landed through this
  blocked run.

## Follow-up

Re-run the capacity scheduler and review-artifact sync work under a fresh
run_id once Score Cloud v2's git-native evidence is available.
