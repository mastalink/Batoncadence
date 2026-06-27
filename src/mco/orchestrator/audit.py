"""
Tamper-evident, append-only audit trail for the Job Board.

Every job mutation (create, lease, status change, approval decision, retry,
escalation) is recorded as an append-only row in `agent_job_events`. The table
is protected by a database trigger that rejects UPDATE/DELETE (see
docs/migrations/) and, on the embedded LocalStore, by APPEND_ONLY_TABLES - so
the trail can only ever grow.

On top of append-only storage, every row is hash-chained:

    prev_hash = hash of the immediately preceding event for the same job
                ("" for the first event)
    hash      = sha256( prev_hash + "\n" + canonical(content) )

where `content` is a deterministic JSON serialization of the row's meaningful
fields (job_id, event, actor_id, actor_role, detail, created_at). Because each
hash folds in the previous one, removing, reordering, or editing any event
breaks every link after it - even an operator with direct database access
cannot rewrite history without detection.

Optionally, when an audit HMAC key is configured in the encrypted secret store
(secret name ``MCO_AUDIT_HMAC_KEY``), each row also carries an HMAC-SHA256
``signature`` over its ``hash``. The signature proves the chain was produced by
a holder of the key, defending against an attacker who recomputes a consistent
chain from scratch.

Audit writes must never break the orchestration path - failures are logged and
swallowed.
"""

import hashlib
import hmac
import json
import logging
from typing import Any, Optional

logger = logging.getLogger("mco.orchestrator.audit")

EVENTS_TABLE = "agent_job_events"

# Secret name under which an optional audit-signing key lives in the secret store.
HMAC_SECRET_NAME = "MCO_AUDIT_HMAC_KEY"

# Process-level cache for the resolved HMAC key. The key is immutable for the
# life of the process, and resolving it can trigger a vault auto_unlock attempt
# (with its own warning logs) - so we resolve at most once. Sentinel means
# "not yet resolved"; None means "resolved, no key configured".
_HMAC_KEY_UNRESOLVED = object()
_hmac_key_cache: Any = _HMAC_KEY_UNRESOLVED

# Fields that make up a row's signed/hashed content. Storage-only columns
# (id, prev_hash, hash, signature, org_id) are deliberately excluded so the
# hash is stable across backends that assign ids/tenants differently.
_CONTENT_FIELDS = ("job_id", "event", "actor_id", "actor_role", "detail", "created_at")

GENESIS_HASH = ""  # prev_hash of the very first event in a chain


def _canonical(content: dict) -> str:
    """Deterministic JSON serialization used as hash input.

    sort_keys + compact separators make the encoding stable regardless of dict
    insertion order or backend formatting, so the same logical row always hashes
    to the same value on LocalStore and Supabase alike.
    """
    return json.dumps(content, sort_keys=True, separators=(",", ":"), default=str)


def _content_of(row: dict) -> dict:
    """Project a stored row down to the fields the hash is computed over."""
    return {f: row.get(f) for f in _CONTENT_FIELDS}


def compute_hash(prev_hash: str, content: dict) -> str:
    """Hash one event: sha256(prev_hash + '\\n' + canonical(content))."""
    material = f"{prev_hash or ''}\n{_canonical(content)}".encode("utf-8")
    return hashlib.sha256(material).hexdigest()


def _resolve_audit_hmac_key() -> Optional[bytes]:
    """Look up the audit HMAC key in the secret store, or None if unavailable.

    Never raises: any failure to reach/unlock the store means "no signing",
    which keeps hash-chaining working on installs without a configured vault.
    """
    try:
        from mco.security import get_secret_store

        store = get_secret_store()
        if not store.is_initialized():
            return None
        if not store.is_unlocked and not store.auto_unlock():
            return None
        raw = store.get(HMAC_SECRET_NAME)
        if not raw:
            return None
        return raw.encode("utf-8")
    except Exception as e:  # pragma: no cover - defensive
        logger.debug(f"Audit HMAC key unavailable: {type(e).__name__}")
        return None


def _audit_hmac_key() -> Optional[bytes]:
    """Return the (process-cached) audit HMAC key, resolving it at most once."""
    global _hmac_key_cache
    if _hmac_key_cache is _HMAC_KEY_UNRESOLVED:
        _hmac_key_cache = _resolve_audit_hmac_key()
    return _hmac_key_cache


def _sign(row_hash: str, key: Optional[bytes]) -> Optional[str]:
    """HMAC-SHA256 over the row hash, or None when no key is configured."""
    if not key:
        return None
    return hmac.new(key, row_hash.encode("utf-8"), hashlib.sha256).hexdigest()


def _last_event(db_client: Any, job_id: str) -> Optional[dict]:
    """Most recent event for a job (by created_at), or None for a fresh chain."""
    try:
        res = (
            db_client.table(EVENTS_TABLE)
            .select("*")
            .eq("job_id", str(job_id))
            .order("created_at", desc=False)
            .execute()
        )
        rows = res.data or []
        return rows[-1] if rows else None
    except Exception as e:
        logger.warning(f"Could not read prior audit event for job {job_id}: {type(e).__name__}")
        return None


def record_event(
    db_client: Any,
    job_id: str,
    event: str,
    actor_id: Optional[str] = None,
    actor_role: Optional[str] = None,
    detail: Optional[dict] = None,
) -> bool:
    """Append one hash-chained event to the audit trail. Never raises."""
    if db_client is None or not job_id:
        return False
    try:
        prev = _last_event(db_client, str(job_id))
        prev_hash = (prev or {}).get("hash") or GENESIS_HASH

        # The row content is finalized BEFORE hashing so the stored hash covers
        # exactly what is persisted. created_at is stamped here for the same
        # reason - a server-assigned timestamp could not be folded into the hash.
        from mco.localstore import _now_iso  # local import avoids a cycle at import time

        content = {
            "job_id": str(job_id),
            "event": event,
            "actor_id": actor_id,
            "actor_role": actor_role,
            "detail": detail or {},
            "created_at": _now_iso(),
        }
        row_hash = compute_hash(prev_hash, content)
        signature = _sign(row_hash, _audit_hmac_key())

        record = dict(content)
        record["prev_hash"] = prev_hash
        record["hash"] = row_hash
        if signature is not None:
            record["signature"] = signature

        db_client.table(EVENTS_TABLE).insert(record).execute()
        return True
    except Exception as e:
        logger.warning(f"Audit write skipped for job {job_id} ({event}): {type(e).__name__}")
        return False


def get_events(db_client: Any, job_id: str) -> list:
    """Return the full audit trail for a job, oldest first."""
    if db_client is None:
        return []
    try:
        res = (
            db_client.table(EVENTS_TABLE)
            .select("*")
            .eq("job_id", str(job_id))
            .order("created_at", desc=False)
            .execute()
        )
        return res.data or []
    except Exception as e:
        logger.error(f"Error fetching audit events for job {job_id}: {type(e).__name__}")
        return []


def verify_chain(db_client: Any, job_id: str) -> dict:
    """Walk a job's hash chain and report integrity.

    Returns a dict::

        {
          "job_id": <id>,
          "ok": bool,
          "count": <events checked>,
          "broken_at": <1-based index of first bad link> | None,
          "reason": <human-readable description> | None,
          "signed": bool,     # whether a signing key was available for checks
        }

    A chain with no events is trivially OK. The first row whose stored hash,
    prev_hash linkage, or HMAC signature does not match is reported as the
    broken link; verification stops there.
    """
    events = get_events(db_client, str(job_id))
    key = _audit_hmac_key()
    result = {
        "job_id": str(job_id),
        "ok": True,
        "count": len(events),
        "broken_at": None,
        "reason": None,
        "signed": key is not None,
    }

    expected_prev = GENESIS_HASH
    for idx, row in enumerate(events, start=1):
        stored_prev = row.get("prev_hash") or GENESIS_HASH
        if stored_prev != expected_prev:
            result.update(ok=False, broken_at=idx,
                          reason=f"prev_hash mismatch at event {idx} "
                                 f"(expected {expected_prev or '<genesis>'}, "
                                 f"got {stored_prev or '<genesis>'})")
            return result

        recomputed = compute_hash(stored_prev, _content_of(row))
        stored_hash = row.get("hash") or ""
        if not hmac.compare_digest(recomputed, stored_hash):
            result.update(ok=False, broken_at=idx,
                          reason=f"content hash mismatch at event {idx} "
                                 f"(row '{row.get('event')}' was altered or "
                                 f"hash is missing)")
            return result

        # Signature check only when both a key is configured AND the row carries
        # one. A row signed under a different/absent key fails closed.
        sig = row.get("signature")
        if key is not None:
            expected_sig = _sign(stored_hash, key)
            if not sig or not hmac.compare_digest(sig, expected_sig or ""):
                result.update(ok=False, broken_at=idx,
                              reason=f"signature mismatch at event {idx} "
                                     f"(HMAC does not verify under the configured key)")
                return result

        expected_prev = stored_hash

    return result
