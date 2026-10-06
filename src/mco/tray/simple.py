"""The everyday tray: a status light with a word, and four menu items.

Spec: design/redesign-v1/01-first-run.html and CLI.md. The icon colour is never
the only signal: every state has a word in the tooltip and as the first
(disabled) menu line.

    green  Running            all well
    amber  Paused             on hold until you resume
    amber  Needs attention    a problem `bitcadence fix` can look at
    red    Stopped            BitCadence isn't answering

Menu: Open BitCadence, Pause/Resume, Fix problems, Quit.

It reads the same board snapshot the CLI verbs use (``plain.take_snapshot``) and
runs the same code as ``bitcadence fix`` and ``bitcadence pause``. It does not
supervise anything; the older daemon-driven tray is still ``mco tray --daemon``.
"""

from __future__ import annotations

import os
import threading
import webbrowser
from typing import Any, Callable, Optional

from mco import plain
from mco.tray.icons import ICON_AMBER, ICON_GREEN, ICON_RED, render_icon

POLL_INTERVAL_S = 5.0


def tray_state(snap: "plain.Snapshot") -> tuple[str, str]:
    """(colour, word) for a board snapshot. The single mapping the tray uses."""
    if not snap.reachable:
        return ICON_RED, "Stopped"
    if snap.paused:
        return ICON_AMBER, "Paused"
    if plain.find_problems(snap):
        return ICON_AMBER, "Needs attention"
    return ICON_GREEN, "Running"


def tooltip(word: str, waiting: Optional[int]) -> str:
    if waiting:
        noun = "approval" if waiting == 1 else "approvals"
        return f"BitCadence: {word} - {waiting} {noun} waiting"
    return f"BitCadence: {word}"


def menu_items(word: str) -> list[dict[str, Any]]:
    """Serializable menu. Used by the pystray builder and by tests."""
    paused = word == "Paused"
    return [
        {"label": f"BitCadence: {word}", "enabled": False},
        {"label": "Open BitCadence", "action": "open", "default": True},
        {"label": "Resume" if paused else "Pause", "action": "resume" if paused else "pause"},
        {"label": "Fix problems", "action": "fix"},
        {"label": "Quit", "action": "quit"},
    ]


class SimpleTray:
    def __init__(
        self,
        client_factory: Optional[Callable[[], Any]] = None,
        opener: Optional[Callable[[], Any]] = None,
        poll_interval: float = POLL_INTERVAL_S,
    ):
        self._client_factory = client_factory
        self._open = opener or self._open_signed_in
        self.poll_interval = poll_interval
        self.color, self.word = ICON_RED, "Stopped"
        self.waiting: Optional[int] = None
        self._stop = threading.Event()
        self._icon = None

    def client(self):
        if self._client_factory is not None:
            return self._client_factory()
        from mco import cli

        return cli._gateway_client()

    def refresh(self) -> tuple[str, str]:
        snap = plain.take_snapshot(self.client())
        self.color, self.word = tray_state(snap)
        self.waiting = len(snap.waiting) if snap.reachable else None
        return self.color, self.word

    # Actions (the same verbs the CLI runs)
    def _open_signed_in(self) -> None:
        from mco import quiet

        webbrowser.open(quiet.login_url(quiet.DEFAULT_HOST, quiet.DEFAULT_PORT))

    def open_app(self, *_: Any) -> None:
        self._open()

    def pause(self, *_: Any) -> None:
        plain.do_pause(self.client(), yes=True)

    def resume(self, *_: Any) -> None:
        plain.do_resume(self.client())

    def fix(self, *_: Any) -> None:
        plain.do_fix(self.client(), yes=True)

    def quit(self, icon=None, item=None) -> None:
        self._stop.set()
        target = icon if icon is not None else self._icon
        if target is not None:
            try:
                target.stop()
            except Exception:  # noqa: BLE001
                pass

    # pystray plumbing
    def _build_menu(self, pystray):
        actions = {"open": self.open_app, "pause": self.pause, "resume": self.resume,
                   "fix": self.fix, "quit": self.quit}
        items = []
        for spec in menu_items(self.word):
            if "action" not in spec:
                items.append(pystray.MenuItem(spec["label"], None, enabled=False))
            else:
                items.append(pystray.MenuItem(
                    spec["label"], actions[spec["action"]], default=spec.get("default", False)))
        return pystray.Menu(*items)

    def _paint(self, icon, pystray) -> None:
        icon.icon = render_icon(self.color, self.waiting)
        icon.title = tooltip(self.word, self.waiting)
        icon.menu = self._build_menu(pystray)
        if hasattr(icon, "update_menu"):
            icon.update_menu()

    def _poll_loop(self, icon, pystray) -> None:
        while not self._stop.wait(self.poll_interval):
            try:
                self.refresh()
                self._paint(icon, pystray)
            except Exception:  # noqa: BLE001
                continue

    def run(self) -> None:
        import pystray

        try:
            self.refresh()
        except Exception:  # noqa: BLE001
            pass
        icon = pystray.Icon("bitcadence", render_icon(self.color, self.waiting),
                            tooltip(self.word, self.waiting), menu=self._build_menu(pystray))
        self._icon = icon
        threading.Thread(target=self._poll_loop, args=(icon, pystray), daemon=True).start()
        icon.run()


def main() -> None:
    from mco import quiet

    pidfile = quiet.tray_pidfile()
    try:
        pidfile.parent.mkdir(parents=True, exist_ok=True)
        pidfile.write_text(str(os.getpid()), encoding="utf-8")
    except OSError:
        pass
    try:
        SimpleTray().run()
    finally:
        try:
            pidfile.unlink()
        except OSError:
            pass
