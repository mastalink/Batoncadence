"""Executor edge-case hardening: process teardown, large I/O, env overrides."""

import asyncio
import sys

import pytest

import mco.orchestrator.executors as ex
from mco.orchestrator.executors import make_cli_executor, resolve_argv, run_argv


@pytest.mark.asyncio
async def test_timed_out_process_is_reaped_cleanly():
    """After timeout the killed process is fully reaped — no zombie or dangling transport."""
    out, err = await run_argv(
        [sys.executable, "-c", "import time; time.sleep(30)"], timeout=0.3
    )
    assert out is None
    assert "timed out" in err
    # Yield to the event loop; if teardown left a pending callback it would warn here.
    await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_new_subprocess_succeeds_after_prior_timeout():
    """Running a new process after a timeout leaves the event loop undamaged."""
    await run_argv([sys.executable, "-c", "import time; time.sleep(10)"], timeout=0.2)
    out, err = await run_argv([sys.executable, "-c", "print('recovered')"])
    assert out == "recovered"
    assert err is None


@pytest.mark.asyncio
async def test_large_stdout_returned_intact():
    """Large stdout (>4 KB) is captured in full without truncation."""
    out, err = await run_argv([sys.executable, "-c", "print('x' * 10_000)"])
    assert err is None
    assert out == "x" * 10_000


@pytest.mark.asyncio
async def test_large_stderr_truncated_at_2000_chars():
    """Error strings from nonzero exits truncate stderr at 2000 characters."""
    out, err = await run_argv(
        [sys.executable, "-c", "import sys; sys.stderr.write('e' * 5000); sys.exit(1)"]
    )
    assert out is None
    assert err is not None
    # run_argv formats: f"exit {code}: {(err or out)[:2000]}"
    assert len(err) <= len("exit 1: ") + 2000


@pytest.mark.asyncio
async def test_both_stdout_and_stderr_on_nonzero_exit():
    """When stdout is present but exit is nonzero, stderr is preferred in the error."""
    script = "import sys; print('out'); sys.stderr.write('err'); sys.exit(2)"
    out, err = await run_argv([sys.executable, "-c", script])
    assert out is None
    assert "exit 2" in err
    assert "err" in err


def test_resolve_argv_comspec_absent_falls_back_to_cmd_exe(monkeypatch):
    """When COMSPEC is absent and the resolved binary is a .cmd, fall back to cmd.exe."""
    monkeypatch.setattr(ex.shutil, "which", lambda b: "C:\\tools\\mco.cmd")
    monkeypatch.setattr(ex.os, "name", "nt")
    monkeypatch.delenv("COMSPEC", raising=False)
    argv = resolve_argv(["mco", "{prompt}"], "hello")
    assert argv is not None
    assert argv[0] == "cmd.exe"
    assert argv[1] == "/c"
    assert "C:\\tools\\mco.cmd" in argv


def test_resolve_argv_bat_extension_also_wrapped_on_windows(monkeypatch):
    """Both .cmd and .bat shims are wrapped through the command interpreter."""
    monkeypatch.setattr(ex.shutil, "which", lambda b: "C:\\npm\\tool.bat")
    monkeypatch.setattr(ex.os, "name", "nt")
    monkeypatch.setenv("COMSPEC", "C:\\Windows\\System32\\cmd.exe")
    argv = resolve_argv(["tool", "{prompt}"], "run")
    assert argv[0] == "C:\\Windows\\System32\\cmd.exe"
    assert argv[1] == "/c"


def test_resolve_argv_posix_binary_not_wrapped(monkeypatch):
    """On POSIX, even a .cmd-named binary is NOT wrapped through a shell."""
    monkeypatch.setattr(ex.shutil, "which", lambda b: "/usr/local/bin/mco.cmd")
    monkeypatch.setattr(ex.os, "name", "posix")
    argv = resolve_argv(["mco", "{prompt}"], "hello")
    assert argv[0] == "/usr/local/bin/mco.cmd"
    assert len(argv) == 2  # binary + substituted prompt only


@pytest.mark.asyncio
async def test_cli_executor_uses_env_override_for_role(monkeypatch):
    """MCO_EXEC_<ROLE> env var overrides the default command template."""
    monkeypatch.setenv("MCO_EXEC_CODEX", f"{sys.executable} -c {{prompt}}")
    executor = make_cli_executor("codex")
    out, err = await executor({}, "print('env-override-works')")
    assert err is None
    assert out == "env-override-works"


def test_make_cli_executor_unknown_role_with_no_env_errors(monkeypatch):
    """An executor for a role with no template and no env var returns an error."""
    monkeypatch.delenv("MCO_EXEC_UNKNOWNROLE", raising=False)

    async def _run():
        executor = make_cli_executor("unknownrole")
        return await executor({}, "some prompt")

    out, err = asyncio.run(_run())
    assert out is None
    assert "No executor command configured" in err
