"""Text captures for redesign slice 5 (Helpers). No gateway, no real processes touched.

Runs the real `bitcadence helpers`, `helpers fix` and the gateway routes against a
fixture: one helper with a second copy running, one resting, one working. Output is
sanitized (no tokens, no paths) and written to design/redesign-v1/evidence-s5/.
"""
import sys
from pathlib import Path

from typer.testing import CliRunner

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import mco.cli as cli  # noqa: E402
from mco import helpers, plain  # noqa: E402

OUT = ROOT / "design/redesign-v1/evidence-s5"


def wake(pid, started):
    return helpers.Proc(pid, [sys.executable, "-m", "mco.cli", "wake", "--exec", "x", "--instance", "fixer"], started, [])


class Gateway:
    def jobs(self, **_):
        return [{"leased_by_instance_id": "scout", "status": "in_progress", "title": "Check open pull requests"}]

    def agents(self):
        mk = lambda i, s, **k: {"instance_id": i, "role": "codex", "state": s, "effective_status": "online" if s != "offline" else "offline", "last_seen_seconds": 12, **k}  # noqa: E731
        return [mk("scout", "working"), mk("fixer", "standby"), mk("tester", "offline")]


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    runner = CliRunner()
    cli._gateway_client = lambda: Gateway()
    helpers.list_processes = lambda: [wake(101, 1.0), wake(102, 2.0)]
    stopped = []
    helpers._stop = stopped.append

    out = ["$ bitcadence helpers", runner.invoke(cli.app, ["helpers"]).output]
    plain.interactive = lambda: True
    import builtins
    answers = iter(["n", "y"])
    builtins.input = lambda *_: next(answers)
    out += ["$ bitcadence helpers fix   (answer: n)", runner.invoke(cli.app, ["helpers", "fix"]).output,
            f"stopped after n: {stopped}", "",
            "$ bitcadence helpers fix   (answer: y)", runner.invoke(cli.app, ["helpers", "fix"]).output,
            f"stopped after y: {stopped}"]
    (OUT / "helpers-cli.txt").write_text("\n".join(out), encoding="utf-8")
    print("\n".join(out))


if __name__ == "__main__":
    main()
