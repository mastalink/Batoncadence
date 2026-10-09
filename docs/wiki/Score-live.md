# Live Score

From Home, tap a running Score card. **Back to Home** returns to the overview.
This drawing is read-only: it cannot edit the plan, approve work, retry a job,
pause a run, or create jobs.

Stages come from the stored run definition, including tasks that have not yet
been dispatched. Work and review cards come from that run's dispatch records.
Rejection paths appear as **Repeats with … if changes are needed**, and each
card labels its work/review round. Worker progress stays visible. **See more**
reveals the job identifier. Columns scroll sideways on a phone.

The console reads `/api/score/autonomy/runs/{run_id}` every ten seconds while
this view is open. This authenticated `jobs:read` endpoint is on the existing
Score status router. It checks the caller's organization and uses a read-only
SQLite connection, returning only drawing fields. It reads at most 200 matching
job rows from the gateway board. Larger runs still show all planned stages and
show a notice that some job details are outside the view. If a job row is not
available, the card uses its dispatch state rather than inventing progress.

The endpoint is a synchronous FastAPI handler so database work runs in the
worker pool. Reading it does not open a writable conductor or tick the run.
Missing runs and runs in another organization return the same unavailable
response. Connection/read failures show a plain error; a stale plan is not
silently presented as current.

Home and this drawing share the ten-minute silence setting described in
[Home](Console-home.md). A recent heartbeat counts as a sign of life even while a long
operation has not produced a new progress sentence. A stall changes only the
display label, not the actual job state.
