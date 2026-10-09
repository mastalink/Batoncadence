"""Approver rights, in plain words.

A missing right used to surface as ``403 Forbidden: missing scope jobs:approve``.
Now `bitcadence approve` and `bitcadence fix` notice it, say it in one sentence
and offer the one-key "Fix it? [Y/n]" repair (CLI.md, approver-rights row).

The repair edits the registry on THIS computer's own database, from a terminal
the person is sitting at, and only for the account this terminal signs in as. It
is never exposed through the gateway API: a token that cannot approve must not be
able to promote itself over the network.
"""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger("mco.approver")

APPROVE = "jobs:approve"


class CannotRepair(Exception):
    """The repair is not possible here; the message says what to do instead."""


def _token() -> str:
    from mco.config import get_config

    config = get_config()
    return (config.get("MCO_AGENT_TOKEN") or config.get("MCO_LOCAL_TOKEN") or "").strip()


def _db():
    from mco.orchestrator.routes import get_db_client

    return get_db_client()


def own_account() -> Optional[dict]:
    """This terminal's registry row, or None when it cannot be told (no local
    database, or a sign-in that is not a registered account)."""
    from mco.orchestrator.auth import verify_token

    token, db = _token(), _db()
    if not token or db is None:
        return None
    try:
        return verify_token(db, token)
    except Exception:  # noqa: BLE001 - a check must never break the verb that asked
        return None


def is_missing(account: Optional[dict] = None) -> bool:
    """True only when we can see the account and it truly lacks the approve right."""
    from mco.orchestrator.auth import has_scope

    account = account if account is not None else own_account()
    return bool(account) and not has_scope(account, APPROVE)


def grant(account: Optional[dict] = None) -> str:
    """Give this computer's account the approve right. The caller has already asked."""
    from mco.localstore import LocalStore
    from mco.orchestrator.auth import resolve_scopes

    db = _db()
    if not isinstance(db, LocalStore):
        raise CannotRepair("This account is managed somewhere else, so I can't change it from here. "
                           "Ask the person who runs BitCadence to make you an approver.")
    account = account if account is not None else own_account()
    if not account or not account.get("instance_id"):
        raise CannotRepair("I couldn't tell which account this is, so I left it alone.")
    scopes = sorted(set(resolve_scopes(account)) | {APPROVE})
    (db.table("agent_registry").update({"scopes": scopes})
       .eq("instance_id", account["instance_id"]).execute())
    logger.warning("approver right granted to %s from the local terminal", account["instance_id"])
    return "Done. You can approve now."
