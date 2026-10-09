"""Text captures for redesign slice 6 (Schedules, Approvals, Settings).

Runs the real `bitcadence schedule`, `approve` and `settings` commands against
fixtures only: a temporary schedules file, a fake gateway that refuses approval
until "fixed", and a stubbed grant. Nothing touches ~/.mco or a real registry.
Output is written to design/redesign-v1/evidence-s6/.
"""
import builtins
import sys
import tempfile
from pathlib import Path

from typer.testing import CliRunner

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import httpx  # noqa: E402

import mco.cli as cli  # noqa: E402
from mco import approver, plain, scheduler  # noqa: E402
from mco import schedules_plain as sp  # noqa: E402

OUT = ROOT / "design/redesign-v1/evidence-s6"
FILE = """launchers:
  nightly-audit:
    role: reviewer
    title: Nightly dependency audit
schedules:
  nightly-audit:
    launcher: nightly-audit
    cron: "0 3 * * *"
    timezone: America/New_York
"""


class Gateway:
    def __init__(self):
        self.fixed = False

    def jobs(self, **_):
        return [{"id": "aaaa1111", "title": "Publish release notes", "status": "needs_approval",
                 "target_agent_role": "codex"}]

    def agents(self):
        return [{"instance_id": "codex-1", "role": "codex", "effective_status": "online", "state": "standby"}]

    def settings(self):
        return {"groups": {"safety": [{"key": "MCO_KILL_SWITCH", "value": ""}],
                           "notifications": [{"key": "NTFY_TOPIC", "type": "secret", "value": True}]}}

    def approve(self, job_id):
        if not self.fixed:
            req = httpx.Request("POST", "http://x/approve")
            raise httpx.HTTPStatusError("403", request=req, response=httpx.Response(403, request=req))
        return {"job": {"id": job_id, "title": "Publish release notes"}}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    runner = CliRunner()
    tmp = Path(tempfile.mkdtemp())
    path = tmp / "schedules.yaml"
    path.write_text(FILE, encoding="utf-8")
    scheduler.SCHEDULES_CONFIG_PATH = path
    sp.detect_timezone = lambda: "America/New_York"
    import mco.launcher as launcher

    launcher._state_path = lambda p=None: tmp / "state.json"
    gw = Gateway()
    cli._gateway_client = lambda: gw
    approver.own_account = lambda: None
    approver.grant = lambda account=None: setattr(gw, "fixed", True) or "Done. You can approve now."

    def run(label, args, answers=()):
        replies = iter(answers)
        builtins.input = lambda prompt="": (print(f"{prompt}{(r := next(replies))}"), r)[1]
        plain.interactive = lambda: bool(answers)
        out = runner.invoke(cli.app, args).output
        return [f"$ {label}", out.rstrip(), ""]

    lines = []
    lines += run("bitcadence schedule", ["schedule"])
    lines += run('bitcadence schedule add --what "Nightly dependency audit" --when "every weekday at 2 AM" --yes',
                 ["schedule", "add", "--what", "Nightly dependency audit", "--when", "every weekday at 2 AM", "--yes"])
    lines += run('bitcadence schedule add --when "every second tuesday"',
                 ["schedule", "add", "--what", "nightly-audit", "--when", "every second tuesday", "--yes"])
    lines += run("bitcadence schedule", ["schedule"])
    (OUT / "schedules-cli.txt").write_text("\n".join(lines), encoding="utf-8")

    lines = run("bitcadence approve Publish   (answer: Y)", ["approve", "Publish"], ["y"])
    (OUT / "approve-fix-cli.txt").write_text("\n".join(lines), encoding="utf-8")

    lines = run("bitcadence settings", ["settings"])
    (OUT / "settings-cli.txt").write_text("\n".join(lines), encoding="utf-8")
    print((OUT / "schedules-cli.txt").read_text(encoding="utf-8"))
    print((OUT / "approve-fix-cli.txt").read_text(encoding="utf-8"))
    print((OUT / "settings-cli.txt").read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
