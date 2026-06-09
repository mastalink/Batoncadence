"""Data contracts and schemas for the standalone job board."""

from enum import Enum

class JobStatus(str, Enum):
    """Execution state of a Job Board task."""
    WAITING = "waiting"                 # Blocked by dependencies
    NEEDS_APPROVAL = "needs_approval"   # Paused at a human-in-the-loop approval gate
    PENDING = "pending"                 # Ready to be leased/executed
    LEASED = "leased"                   # Claimed by an agent instance
    IN_PROGRESS = "in_progress"         # Being executed by an agent instance
    COMPLETED = "completed"             # Execution completed successfully
    FAILED = "failed"                   # Execution failed (may retry/escalate)
    REJECTED = "rejected"               # Terminal: a human rejected the approval gate
