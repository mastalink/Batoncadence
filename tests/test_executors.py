"""Functional tests for the role executor layer.

These exercise the real subprocess path (using the test's own Python interpreter)
rather than only mocks, so we know leased jobs will actually run.
"""

import sys

import pytest

import mco.orchestrator.executors as ex
import mco.orchestrator.listener as listener_mod
from mco.orchestrator.executors import (
    make_cli_executor,
    register_default_executors,
    resolve_argv,
    run_argv,
)


@pytest.mark.asyncio
async def test_run_argv_success_captures_stdout():
    out, err = await run_argv([sys.executable, "-c", "print('hello-mco')"])
    assert err is None
    assert out == "hello-mco"


@pytest.mark.asyncio
async def test_run_argv_nonzero_exit_is_error():
    out, err = await run_argv(
        [sys.executable, "-c", "import sys; sys.stderr.write('boom'); sys.exit(3)"]
    )
    assert out is None
    assert "exit 3" in err and "boom" in err


@pytest.mark.asyncio
async def test_run_argv_timeout_kills_process():
    out, err = await run_argv(
        [sys.executable, "-c", "import time; time.sleep(5)"], timeout=0.5
    )
    assert out is None
    assert "timed out" in err


@pytest.mark.asyncio
async def test_run_argv_missing_binary_is_error():
    out, err = await run_argv(["this-binary-does-not-exist-xyz", "arg"])
    assert out is None
    assert "Failed to launch" in err


def test_resolve_argv_missing_returns_none(monkeypatch):
    monkeypatch.setattr(ex.shutil, "which", lambda b: None)
    assert resolve_argv(["nope", "{prompt}"], "x") is None


def test_resolve_argv_substitutes_prompt(monkeypatch):
    monkeypatch.setattr(ex.shutil, "which", lambda b: "/usr/bin/codex")
    monkeypatch.setattr(ex.os, "name", "posix")
    argv = resolve_argv(["codex", "exec", "{prompt}"], "do the thing")
    assert argv == ["/usr/bin/codex", "exec", "do the thing"]


def test_resolve_argv_windows_cmd_is_wrapped(monkeypatch):
    monkeypatch.setattr(ex.shutil, "which", lambda b: "C:\\fake\\codex.cmd")
    monkeypatch.setattr(ex.os, "name", "nt")
    monkeypatch.setenv("COMSPEC", "C:\\Windows\\System32\\cmd.exe")
    argv = resolve_argv(["codex", "exec", "{prompt}"], "do it")
    assert argv == ["C:\\Windows\\System32\\cmd.exe", "/c", "C:\\fake\\codex.cmd", "exec", "do it"]


@pytest.mark.asyncio
async def test_cli_executor_runs_end_to_end_via_override(monkeypatch):
    # Point the codex role at this interpreter; the job "prompt" is python to run.
    monkeypatch.setenv("MCO_EXEC_CODEX", f"{sys.executable} -c {{prompt}}")
    executor = make_cli_executor("codex")
    out, err = await executor({}, "print('hi-from-codex')")
    assert err is None
    assert out == "hi-from-codex"


def test_register_default_executors_populates_registry():
    listener_mod._executor_registry.clear()
    roles = register_default_executors(["codex", "claude"])
    assert roles == ["codex", "claude"]
    assert "codex" in listener_mod._executor_registry
    assert "claude" in listener_mod._executor_registry
