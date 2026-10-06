"""One-time local sign-in for the web console.

Today a person copies a long secret and confirms a web address. Instead the CLI
asks the running gateway for a one-time code, and the browser opens a link that
carries only that code. The gateway swaps the code for the console's saved
connection exactly once, and only for a request that really came from this
computer.

Safety properties (each has a test in tests/test_local_login.py):

* loopback only: both the minting call and the redeeming page refuse any peer
  that is not 127.0.0.1 / ::1, and any Host header that is not a loopback name
  (so a DNS-rebinding page cannot redeem a code);
* short-lived: a code expires after ``CODE_TTL_SECONDS``;
* single-use: redeeming removes it, so a copied or logged link is worthless;
* the long-lived token never appears in a URL, only in the one response body.
"""

from __future__ import annotations

import json
import secrets
import threading
import time
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse

from mco.orchestrator.auth import extract_bearer, require_agent

CODE_TTL_SECONDS = 60
MAX_PENDING = 8
# Pages a sign-in may land on. A fixed list, never a caller-supplied address.
LANDING_PAGES = {"console": "/console", "welcome": "/welcome"}

_LOOPBACK_PEERS = {"127.0.0.1", "::1"}
_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}

_lock = threading.Lock()
_codes: dict[str, tuple[str, float, str]] = {}  # code -> (token, expires_at, landing)

local_login_router = APIRouter()


def _is_loopback(request: Request) -> bool:
    peer = request.client.host if request.client else ""
    host = (request.headers.get("host") or "").strip().lower()
    if host.startswith("["):  # [::1]:18789
        host = host[1:host.index("]")] if "]" in host else host
    elif host.count(":") == 1:
        host = host.rsplit(":", 1)[0]
    return peer in _LOOPBACK_PEERS and host in _LOOPBACK_HOSTS


def mint(token: str, landing: str = "console", now: Optional[float] = None) -> str:
    """Create a one-time code that redeems to ``token``."""
    if landing not in LANDING_PAGES:
        raise ValueError(f"unknown landing page: {landing}")
    now = time.monotonic() if now is None else now
    with _lock:
        for code in [c for c, (_, exp, _l) in _codes.items() if exp <= now]:
            del _codes[code]
        if len(_codes) >= MAX_PENDING:
            oldest = min(_codes, key=lambda c: _codes[c][1])
            del _codes[oldest]
        code = secrets.token_urlsafe(24)
        _codes[code] = (token, now + CODE_TTL_SECONDS, landing)
    return code


def redeem(code: str, now: Optional[float] = None) -> Optional[tuple[str, str]]:
    """Return (token, landing path) once, or None for an unknown/used/expired code."""
    now = time.monotonic() if now is None else now
    with _lock:
        entry = _codes.pop(code, None)
    if entry is None or entry[1] <= now:
        return None
    return entry[0], LANDING_PAGES[entry[2]]


def reset() -> None:
    with _lock:
        _codes.clear()


_NO_STORE = {
    "Cache-Control": "no-store",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
}


@local_login_router.post("/api/local-login", include_in_schema=False)
def create_local_login(
    request: Request,
    landing: str = "console",
    principal: dict = Depends(require_agent),
):
    """Mint a one-time sign-in link. Needs the caller's own token, from this computer."""
    if not _is_loopback(request):
        raise HTTPException(status_code=403, detail="Local sign-in only works from this computer.")
    if landing not in LANDING_PAGES:
        raise HTTPException(status_code=400, detail="Unknown page.")
    token = extract_bearer(request.headers.get("authorization", ""))
    if not token:
        raise HTTPException(status_code=400, detail="Local sign-in needs a bearer token.")
    code = mint(token, landing)
    return {"path": f"/local-login?code={code}", "expires_in": CODE_TTL_SECONDS}


_EXPIRED = """<!doctype html><meta charset="utf-8"><title>BitCadence</title>
<body style="font-family:system-ui,sans-serif;max-width:32rem;margin:4rem auto;padding:0 1rem">
<h1>That link has expired</h1>
<p>Nothing is wrong. Open BitCadence again from the icon near your clock,
or run <code>bitcadence start</code>.</p></body>"""


def _signin_page(token: str, landing: str) -> str:
    # json.dumps, then neutralise "</" so the token can never close the script tag.
    conn = json.dumps({"url": "", "token": token}).replace("</", "<\\/")
    return (
        '<!doctype html><meta charset="utf-8"><title>BitCadence</title>'
        '<body style="font-family:system-ui,sans-serif;padding:2rem">Signing you in...'
        "<script>"
        f"var c={conn};c.url=location.origin;"
        "try{localStorage.setItem('bitcadence_conn',JSON.stringify(c));}catch(e){}"
        f"location.replace({json.dumps(landing)});"
        "</script></body>"
    )


@local_login_router.get("/local-login", response_class=HTMLResponse, include_in_schema=False)
def redeem_local_login(request: Request, code: str = ""):
    if not _is_loopback(request):
        raise HTTPException(status_code=403, detail="Local sign-in only works from this computer.")
    redeemed = redeem(code) if code else None
    if redeemed is None:
        return HTMLResponse(_EXPIRED, status_code=410, headers=_NO_STORE)
    token, landing = redeemed
    return HTMLResponse(_signin_page(token, landing), headers=_NO_STORE)


# "You're all set" (design/redesign-v1/01-first-run.html)
WELCOME_HTML = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>You're all set - BitCadence</title>
<style>
body{font-family:system-ui,"Segoe UI",sans-serif;background:#f7f7f8;color:#17171c;margin:0}
main{max-width:34rem;margin:5rem auto;background:#fff;border:1px solid #e4e4e9;border-radius:14px;padding:2.5rem;text-align:center}
h1{margin:.5rem 0}p{color:#5e5e6b;line-height:1.5}
.ok{font-size:3rem;color:#1a7a3e}.chips{display:flex;gap:.5rem;justify-content:center;margin:1.5rem 0;flex-wrap:wrap}
.chip{background:#e5f4ea;color:#1a7a3e;border-radius:999px;padding:.3rem .9rem;font-size:.9rem}
a.btn{display:inline-block;background:#5b5bd6;color:#fff;text-decoration:none;border-radius:8px;padding:.7rem 1.4rem;font-weight:600}
a.skip{display:block;margin-top:1rem;color:#5e5e6b}
</style></head><body><main>
<div class="ok" aria-hidden="true">&#10003;</div>
<h1>You're all set</h1>
<p>BitCadence now runs quietly in the background. Look for the small icon near your clock.
It starts by itself when you sign in.</p>
<div class="chips"><span class="chip">&#10003; Running quietly</span><span class="chip">&#10003; No window to keep open</span></div>
<a class="btn" href="/console">Next: connect your AI</a>
<a class="skip" href="/console">Skip for now, take me home</a>
</main></body></html>"""


@local_login_router.get("/welcome", response_class=HTMLResponse, include_in_schema=False)
def welcome() -> str:
    return WELCOME_HTML


def welcome_text() -> str:
    """The same screen for a terminal."""
    return (
        "You're all set.\n"
        "  BitCadence now runs quietly in the background.\n"
        "  Look for the small icon near your clock. It starts by itself when you sign in.\n"
        "  [x] Running quietly   [x] No window to keep open\n"
        "Next: connect your AI with `bitcadence connect`."
    )
