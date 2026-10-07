import importlib.util
from pathlib import Path


def test_report_ranks_named_mac_callers_by_count_and_time():
    spec = importlib.util.spec_from_file_location("gateway_slow_report", Path(__file__).parents[1] / "scripts/gateway_slow_report.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    records = [
        {"timestamp": 100, "instance_id": "claude-mac", "total_ms": 3000, "lock_wait_ms": 500},
        {"timestamp": 100, "instance_id": "codex-mac", "total_ms": 1200, "lock_wait_ms": 100},
        {"timestamp": 101, "instance_id": "codex-mac", "total_ms": 1300, "lock_wait_ms": 200},
        {"timestamp": 1, "instance_id": "expired", "total_ms": 9000, "lock_wait_ms": 9000},
    ]
    report = module.summarize(records, since=90)
    assert report["by_count"][0]["instance_id"] == "codex-mac"
    assert report["by_count"][0]["count"] == 2
    assert report["by_count"][0]["lock_wait_ms"] == 300
    assert report["by_time"][0]["instance_id"] == "claude-mac"
    assert len(report["by_time"]) == 2
