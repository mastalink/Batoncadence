"""Plain-English error translation for the CLI.

Every error the everyday commands can hit is turned into two parts: what
happened in one plain sentence, and the exact next step. No stack traces unless
the caller asked for them with --debug (or MCO_DEBUG=1).

The table in design/redesign-v1/CLI.md is the spec; each row has a matching
branch in :func:`translate` and a test in tests/test_plain_cli.py.
"""

from __future__ import annotations

import errno
import os
import re
from dataclasses import dataclass
from typing import Optional

# Windows' WSAEADDRINUSE; errno.EADDRINUSE differs per platform.
_ADDR_IN_USE = {errno.EADDRINUSE, 98, 48, 10048}
# ERROR_SHARING_VIOLATION / ERROR_LOCK_VIOLATION
_LOCKED = {32, 33}


@dataclass(frozen=True)
class FriendlyError:
    """One plain error: what happened, and what to do next."""

    what: str
    next_step: str = ""
    kind: str = "unknown"

    def render(self) -> str:
        return f"{self.what} {self.next_step}".strip()


def debug_enabled() -> bool:
    return os.environ.get("MCO_DEBUG", "").strip().lower() in {"1", "true", "yes"}


def _chain(exc: BaseException):
    """The exception and everything it was raised from or while handling."""
    seen = set()
    while exc is not None and id(exc) not in seen:
        seen.add(id(exc))
        yield exc
        exc = exc.__cause__ or exc.__context__


def _status_and_text(exc: BaseException) -> tuple[Optional[int], str]:
    response = getattr(exc, "response", None)
    status = getattr(response, "status_code", None)
    text = ""
    if response is not None:
        try:
            text = response.text or ""
        except Exception:
            text = ""
    return status, text


def app_name_from_missing(exc: BaseException, app_hint: str = "") -> str:
    """Best-effort friendly app name for a missing config file."""
    if app_hint:
        return app_hint.capitalize()
    name = os.path.basename(getattr(exc, "filename", "") or str(exc)).lower()
    if "claude" in name:
        return "Claude"
    if "gemini" in name:
        return "Gemini"
    if "cursor" in name:
        return "Cursor"
    return "that app"


def translate(exc: BaseException, *, app_hint: str = "") -> FriendlyError:
    """Map any exception to a FriendlyError. Unknown errors keep their own text."""
    for e in _chain(exc):
        name = type(e).__name__

        # Not running: nothing is listening on the gateway port.
        if isinstance(e, ConnectionRefusedError) or name in {
            "ConnectError", "ConnectTimeout", "NetworkError"
        }:
            return FriendlyError(
                "BitCadence isn't running.",
                "Start it with: bitcadence start",
                "not_running",
            )

        status, body = _status_and_text(e)
        if status == 401:
            return FriendlyError(
                "BitCadence didn't recognise this computer's sign-in.",
                "Run: bitcadence fix",
                "unauthorized",
            )
        if status == 403:
            return FriendlyError(
                "You can't approve yet because your account isn't an approver.",
                "Run: bitcadence fix",
                "not_approver",
            )

        if isinstance(e, FileNotFoundError):
            who = app_name_from_missing(e, app_hint)
            cmd = f" bitcadence connect {who.lower()}" if who != "that app" else " bitcadence connect"
            return FriendlyError(
                f"I couldn't find {who} on this computer.",
                f"Install it, then run:{cmd}",
                "app_not_found",
            )

        if isinstance(e, OSError):
            code = getattr(e, "errno", None)
            winerr = getattr(e, "winerror", None)
            if code in _ADDR_IN_USE or winerr in _ADDR_IN_USE:
                return FriendlyError(
                    "Another program is using what BitCadence needs.",
                    "Run: bitcadence fix",
                    "port_in_use",
                )
            if winerr in _LOCKED or isinstance(e, PermissionError) and ".log" in str(e).lower():
                return FriendlyError(
                    "A helper can't save its notes because another copy has the file open.",
                    "Run: bitcadence fix",
                    "locked_log",
                )

        text = f"{e} {body}".lower()
        if "address already in use" in text or "only one usage of each socket" in text:
            return FriendlyError(
                "Another program is using what BitCadence needs.",
                "Run: bitcadence fix",
                "port_in_use",
            )
        if "invalid cron" in text or "cron expression" in text:
            return FriendlyError(
                "I didn't understand that schedule.",
                'Try "every weekday at 2 AM".',
                "bad_schedule",
            )

    return FriendlyError(_clean_message(exc), "If it keeps happening, run: bitcadence fix", "unknown")


def _clean_message(exc: BaseException) -> str:
    text = str(exc).strip() or type(exc).__name__
    text = re.sub(r"\s+", " ", text)
    if len(text) > 200:
        text = text[:197] + "..."
    return text if text.endswith((".", "!", "?")) else text + "."


def bad_schedule(phrase: str) -> FriendlyError:
    """The 'bad schedule' row, with the person's own words echoed back."""
    return FriendlyError(
        f'I didn\'t understand "{phrase}".',
        'Try "every weekday at 2 AM".',
        "bad_schedule",
    )


def no_helper_free() -> FriendlyError:
    """Approved, but nothing is online to pick the job up."""
    return FriendlyError("Approved, but no helper is free.", "Start one with: bitcadence helpers add", "no_helper")


def locked_log(helper: str) -> FriendlyError:
    return FriendlyError(
        f"{helper} can't save its notes because another copy has the file open.",
        "Run: bitcadence fix",
        "locked_log",
    )


def app_not_found(app: str) -> FriendlyError:
    return FriendlyError(
        f"I couldn't find {app.capitalize()} on this computer.",
        f"Install it, then run: bitcadence connect {app.lower()}",
        "app_not_found",
    )
