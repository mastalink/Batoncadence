"""The default `bitcadence` / `mco` menu (no arguments, real terminal only).

Items run the same functions as the matching verbs in :mod:`mco.plain`. The
chooser is injectable so tests drive the menu with a fake gateway and no
terminal; the real chooser uses prompt_toolkit for arrow keys and falls back to
a plain numbered prompt anywhere it can't run.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Callable, List, Optional

from mco import plain


@dataclass(frozen=True)
class MenuItem:
    key: str  # maps to a verb in VERBS
    label: str


def build_items(snap: plain.Snapshot) -> List[MenuItem]:
    """Menu entries with live counts. Counts are omitted when the gateway is down."""
    items: List[MenuItem] = []
    if not snap.reachable:
        items.append(MenuItem("start", "Start BitCadence"))
    waiting = len(snap.waiting)
    problems = len(plain.find_problems(snap)) if snap.reachable else 0
    items += [
        MenuItem("status", "Status"),
        MenuItem("ask", "Ask for something"),
        MenuItem("approve", f"Approvals ({waiting} waiting)" if snap.reachable else "Approvals"),
        MenuItem("fix", f"Fix problems ({problems})" if snap.reachable else "Fix problems"),
        MenuItem("helpers", "Helpers"),
        MenuItem("schedule", "Schedules"),
        MenuItem("connect", "Connect an AI"),
        MenuItem("resume" if snap.paused else "pause", "Resume everything" if snap.paused else "Pause everything"),
        MenuItem("settings", "Settings"),
        MenuItem("help", "Help"),
        MenuItem("quit", "Quit"),
    ]
    return items


def _verbs(client, help_text: Callable[[], str]) -> dict:
    """key -> zero-arg callable, each the same code the CLI verb runs."""
    from mco import quiet

    return {
        "start": lambda: quiet.run_start(),
        "status": lambda: plain.do_status(client),
        "ask": lambda: plain.do_ask(client, ""),
        "approve": lambda: plain.do_approve(client),
        "fix": lambda: plain.do_fix(client),
        "helpers": lambda: plain.do_helpers(client),
        "schedule": lambda: plain.do_schedules(),
        "connect": lambda: plain.do_connect(""),
        "pause": lambda: plain.do_pause(client),
        "resume": lambda: plain.do_resume(client),
        "settings": lambda: plain.do_settings(client),
        "help": lambda: plain.say(help_text()),
    }


Chooser = Callable[[str, List[str]], Optional[int]]


def numbered_choose(title: str, labels: List[str]) -> Optional[int]:
    """Plain fallback: works on any terminal, no arrow keys needed."""
    plain.say(title)
    for i, label in enumerate(labels, 1):
        plain.say(f"  {i}. {label}")
    while True:
        try:
            raw = input("Type a number (q to go back): ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            plain.say()
            return None
        if raw in {"q", "quit", "exit"}:
            return None
        if raw.isdigit() and 1 <= int(raw) <= len(labels):
            return int(raw) - 1
        plain.say(f"Please type a number from 1 to {len(labels)}, or q.")


def arrow_choose(title: str, labels: List[str]) -> Optional[int]:
    """Arrow keys / j,k / digits 1-9 / Enter. Esc or q goes back. Reverse video
    for the selection, so it stays readable with no colour (NO_COLOR)."""
    from prompt_toolkit.application import Application
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.layout import FormattedTextControl, Layout, Window

    index = [0]

    def render():
        parts = [("bold", title + "\n")]
        for i, label in enumerate(labels):
            selected = i == index[0]
            parts.append(("reverse" if selected else "", f"{'>' if selected else ' '} {i + 1}. {label}\n"))
        parts.append(("", "\nUp/Down or a number, Enter to choose, Esc or q to go back\n"))
        return parts

    kb = KeyBindings()

    @kb.add("up")
    @kb.add("k")
    def _up(event):
        index[0] = (index[0] - 1) % len(labels)

    @kb.add("down")
    @kb.add("j")
    def _down(event):
        index[0] = (index[0] + 1) % len(labels)

    @kb.add("enter")
    def _enter(event):
        event.app.exit(result=index[0])

    @kb.add("escape", eager=True)
    @kb.add("q")
    def _back(event):
        event.app.exit(result=None)

    @kb.add("c-c")
    def _interrupt(event):
        event.app.exit(result=None)

    for n in range(1, 10):
        @kb.add(str(n))
        def _digit(event, n=n):
            if n <= len(labels):
                event.app.exit(result=n - 1)

    app = Application(
        layout=Layout(Window(FormattedTextControl(render, show_cursor=False))),
        key_bindings=kb,
        full_screen=False,
    )
    return app.run()


def default_chooser(title: str, labels: List[str]) -> Optional[int]:
    if os.environ.get("MCO_MENU_PLAIN"):
        return numbered_choose(title, labels)
    try:
        return arrow_choose(title, labels)
    except Exception:  # noqa: BLE001 - no usable terminal for arrows: use numbers
        return numbered_choose(title, labels)


def run_menu(
    client,
    help_text: Callable[[], str],
    chooser: Chooser = default_chooser,
    pause: Optional[Callable[[], None]] = None,
) -> int:
    """Show the menu until the person quits. Esc/q at the top level quits."""
    verbs = _verbs(client, help_text)
    if pause is None:
        def pause() -> None:
            try:
                input("\nPress Enter to go back to the menu. ")
            except (EOFError, KeyboardInterrupt):
                pass
    while True:
        snap = plain.take_snapshot(client)
        items = build_items(snap)
        picked = chooser("BitCadence - what would you like to do?", [i.label for i in items])
        if picked is None or items[picked].key == "quit":
            return 0
        action = verbs[items[picked].key]
        try:
            action()
        except SystemExit:
            pass
        except KeyboardInterrupt:
            plain.say()
        except Exception as exc:  # noqa: BLE001 - a failed item must not close the menu
            from mco import friendly

            plain.say(friendly.translate(exc).render())
        pause()


def should_show_menu(args: List[str]) -> bool:
    """Menu only for a bare invocation on a real terminal; never for pipes/CI."""
    if args or "--no-menu" in args:
        return False
    if os.environ.get("MCO_NO_MENU") or os.environ.get("CI"):
        return False
    return plain.interactive()
