from mco.orchestrator.loop_watchdog import STALL_EXIT_CODE, LoopWatchdog, from_env


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def make(tmp_path, clock, exits, *, dump_after=60, exit_after=300):
    return LoopWatchdog(dump_after=dump_after, exit_after=exit_after, dump_dir=tmp_path,
                        clock=clock, exit_fn=exits.append)


def test_healthy_loop_does_nothing(tmp_path):
    clock, exits = FakeClock(), []
    wd = make(tmp_path, clock, exits)
    for _ in range(500):
        clock.now += 1
        wd.beat()
        wd.check()
    assert wd.dumps == [] and exits == []


def test_stall_dumps_stacks_once_then_exits(tmp_path):
    clock, exits = FakeClock(), []
    wd = make(tmp_path, clock, exits)
    clock.now += 61
    wd.check()
    clock.now += 30
    wd.check()
    assert len(wd.dumps) == 1
    text = wd.dumps[0].read_text(encoding="utf-8")
    assert "event loop silent" in text and "test_stall_dumps_stacks_once_then_exits" in text
    assert exits == []
    clock.now += 300
    wd.check()
    assert exits == [STALL_EXIT_CODE]


def test_recovered_loop_is_left_alone_and_a_new_stall_dumps_again(tmp_path):
    clock, exits = FakeClock(), []
    wd = make(tmp_path, clock, exits)
    clock.now += 90
    wd.check()
    wd.beat()  # the loop came back by itself
    clock.now += 200
    wd.beat()
    wd.check()
    assert exits == [] and len(wd.dumps) == 1
    clock.now += 61
    wd.check()
    assert len(wd.dumps) == 2


def test_exit_can_be_disabled(tmp_path):
    clock, exits = FakeClock(), []
    wd = make(tmp_path, clock, exits, exit_after=0)
    clock.now += 10_000
    wd.check()
    assert exits == [] and len(wd.dumps) == 1


def test_unwritable_dump_dir_never_raises(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    clock, exits = FakeClock(), []
    wd = LoopWatchdog(dump_after=1, exit_after=0, dump_dir=blocker / "sub", clock=clock, exit_fn=exits.append)
    clock.now += 5
    wd.check()
    assert wd.dumps == []


def test_from_env(monkeypatch, tmp_path):
    monkeypatch.setenv("MCO_LOOP_STALL_DUMP_SECONDS", "0")
    assert from_env() is None
    monkeypatch.setenv("MCO_LOOP_STALL_DUMP_SECONDS", "45")
    monkeypatch.setenv("MCO_LOOP_STALL_EXIT_SECONDS", "0")
    monkeypatch.setenv("MCO_LOOP_STALL_DIR", str(tmp_path))
    wd = from_env()
    assert wd.dump_after == 45 and wd.exit_after == 0 and wd.dump_dir == tmp_path
