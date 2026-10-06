# Console Home

Open `/console` and choose **Home**. **What needs you** comes first: approval
requests, unsuccessful work, and active jobs with no sign of life. **Approve**
uses the existing authenticated approval action; **Look first** opens the job
details. Job identifiers are absent from Home cards.

**What's running** groups Score jobs by their run, so two runs of the same plan
remain separate. Cards show a state word and a sentence from worker progress,
with a plain fallback when no progress sentence is available. Structured output
and recognizable credential text are not used as progress sentences.
Step counts come from the actual Score plan, not a count of recently fetched
jobs; repeat rounds are labelled. Home refreshes at most twenty visible plans
every thirty seconds. If a plan cannot be read, its card omits the step count.

Tap a Score card to watch its read-only live drawing. Other cards open job
details. Home polls `/api/jobs?limit=200` and `/api/agents`; it never requests an
unbounded job board. A notice appears at the 200-job limit because older work
may be outside this view. This is a recent-work view, not a complete history.

The named `HOME_STALL_MINUTES` setting in the console source is **10**. For
leased or working jobs, the newest valid start, update, progress timestamp or
worker heartbeat starts the silence clock. Waiting and approval jobs are not
flagged merely because they are old. Missing timestamps do not prove a stall.
The **Stuck** label is a display flag; viewing it never changes the job or
restarts a helper. Check the job details before choosing a repair.

Cards use words as well as color, visible keyboard focus, and controls at least
48 pixels high. The view follows light/dark preferences and reduced motion.

See [Live Score](Score-live.md) for the automatic drawing and its limits.
