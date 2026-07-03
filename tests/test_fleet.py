from pathlib import Path

import pytest

from mco import fleet


def _write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def test_load_fleet_parses_waker_poll_and_off_modes(tmp_path):
    config = _write(
        tmp_path / "fleet.toml",
        """
[workers.opencode-beast]
role = "opencode"
instance = "opencode-beast"
mode = "waker"
exec = "C:/Users/masta/.mco/bin/opencode-beast-run.cmd"
min_interval = 10

[workers.codex-beast]
role = "codex"
instance = "codex-beast"
mode = "poll"
exec = "C:/Users/masta/.mco/bin/codex-beast-run.cmd"
poll_interval = 1800

[workers.disabled]
role = "codex"
instance = "codex-disabled"
mode = "off"
""",
    )

    workers = fleet.load_fleet(config)

    assert workers["opencode-beast"].mode == "waker"
    assert workers["opencode-beast"].min_interval == 10
    assert workers["codex-beast"].mode == "poll"
    assert workers["codex-beast"].poll_interval == 1800
    assert workers["disabled"].active_service_name is None


def test_load_fleet_missing_file_is_clear(tmp_path):
    with pytest.raises(fleet.FleetConfigMissing):
        fleet.load_fleet(tmp_path / "missing.toml")


def test_load_fleet_rejects_bad_mode(tmp_path):
    config = _write(
        tmp_path / "fleet.toml",
        """
[workers.bad]
role = "codex"
instance = "codex-bad"
mode = "daemon"
exec = "run.cmd"
""",
    )

    with pytest.raises(fleet.FleetConfigError, match="mode must be one of"):
        fleet.load_fleet(config)


def test_apply_dispatches_by_mode_and_reconciles_removed_workers(monkeypatch, tmp_path):
    config = _write(
        tmp_path / "fleet.toml",
        """
[workers.opencode-beast]
role = "opencode"
instance = "opencode-beast"
mode = "waker"
exec = "opencode-run.cmd"
min_interval = 7

[workers.codex-beast]
role = "codex"
instance = "codex-beast"
mode = "poll"
exec = "codex-run.cmd"
poll_interval = 900

[workers.disabled]
role = "codex"
instance = "codex-disabled"
mode = "off"
""",
    )
    calls = []
    installed = {
        "BatonCadence-poll-opencode-opencode-beast",
        "BatonCadence-wake-codex-beast",
        "BatonCadence-poll-codex-disabled",
        "BatonCadence-wake-old-old",
    }

    monkeypatch.setattr(
        fleet.service,
        "list_status",
        lambda: [{"name": name, "installed": True, "running": False} for name in sorted(installed)],
    )

    def fake_uninstall(name):
        calls.append(("uninstall", name))
        installed.discard(name)
        return True, f"removed {name}"

    monkeypatch.setattr(fleet.service, "uninstall", fake_uninstall)
    monkeypatch.setattr(
        fleet.service,
        "install_waker",
        lambda role, exec_command, instance=None, min_interval=10.0: (
            calls.append(("waker", role, exec_command, instance, min_interval)) or (True, "waker installed")
        ),
    )
    monkeypatch.setattr(
        fleet.service,
        "install_poll",
        lambda role, exec_command, instance=None, poll_interval=1800.0: (
            calls.append(("poll", role, exec_command, instance, poll_interval)) or (True, "poll installed")
        ),
    )

    summaries = fleet.apply_fleet(config)

    assert ("uninstall", "BatonCadence-poll-opencode-opencode-beast") in calls
    assert ("waker", "opencode", "opencode-run.cmd", "opencode-beast", 7.0) in calls
    assert ("uninstall", "BatonCadence-wake-codex-beast") in calls
    assert ("poll", "codex", "codex-run.cmd", "codex-beast", 900.0) in calls
    assert ("uninstall", "BatonCadence-poll-codex-disabled") in calls
    assert ("uninstall", "BatonCadence-wake-old-old") in calls
    assert any("opencode-beast: waker OK" in line for line in summaries)
    assert any("codex-beast: poll OK" in line for line in summaries)


def test_fleet_status_lists_configured_workers(monkeypatch, tmp_path):
    config = _write(
        tmp_path / "fleet.toml",
        """
[workers.codex-beast]
role = "codex"
instance = "codex-beast"
mode = "poll"
exec = "codex-run.cmd"
poll_interval = 900
""",
    )

    monkeypatch.setattr(
        fleet.service,
        "status",
        lambda name: {"name": name, "installed": True, "running": True, "last_exit": "0"},
    )

    assert fleet.fleet_status(config) == [{
        "worker": "codex-beast",
        "role": "codex",
        "instance": "codex-beast",
        "mode": "poll",
        "service": "BatonCadence-poll-codex-codex-beast",
        "installed": True,
        "running": True,
        "last_exit": "0",
    }]


def test_set_worker_value_updates_toml_and_requires_apply(tmp_path):
    config = _write(
        tmp_path / "fleet.toml",
        """
[workers.codex-beast]
role = "codex"
instance = "codex-beast"
mode = "poll"
exec = "codex-run.cmd"
poll_interval = 900
""",
    )

    message = fleet.set_worker_value("codex-beast", "mode=waker", config)

    assert "mco fleet apply" in message
    workers = fleet.load_fleet(config)
    assert workers["codex-beast"].mode == "waker"
