"""Text captures for redesign slice 7 (Connect an AI).

Runs the real `bitcadence connect` against a fake computer in a temp folder:
Claude (json) and Codex (toml) are installed, Gemini is not. Nothing touches a
real app's settings. Output goes to design/redesign-v1/evidence-s7/.
"""
import json
import sys
import tempfile
from pathlib import Path

from typer.testing import CliRunner

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import mco.cli as cli  # noqa: E402
from mco import connect_ai  # noqa: E402

OUT = ROOT / "design/redesign-v1/evidence-s7"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    runner = CliRunner()
    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp)
        claude = home / "claude_desktop_config.json"
        claude.write_text(json.dumps({"mcpServers": {"other": {"command": "x"}}}), encoding="utf-8")
        codex = home / "config.toml"
        codex.write_text('model = "gpt"\n', encoding="utf-8")
        table = {"claude": [claude], "codex": [codex], "gemini": [home / "missing.json"]}
        connect_ai.targets = lambda: table  # fixtures only
        steps = [("connect-claude", ["connect", "claude", "--yes"]), ("connect-codex", ["connect", "codex", "--yes"]),
                 ("test-claude", ["connect", "claude", "--test"]), ("gemini-missing", ["connect", "gemini", "--yes"]),
                 ("disconnect-claude", ["connect", "claude", "--disconnect", "--yes"])]
        for name, args in steps:
            out = runner.invoke(cli.app, ["connect", *args[1:]]).output.replace(str(home), "<home>")
            (OUT / f"{name}.txt").write_text(f"$ bitcadence {' '.join(args)}\n{out}", encoding="utf-8")
        (OUT / "backups.txt").write_text("\n".join(sorted(p.name for p in home.iterdir())) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
