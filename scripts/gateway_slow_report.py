"""Summarize the last ten minutes of authenticated gateway slow callers.

Run after deploying the middleware: python scripts/gateway_slow_report.py
Reads the current log and its three rotated files; never reads agent tokens.
"""

import argparse
from collections import defaultdict
import json
from pathlib import Path
import time


def summarize(records, *, since):
    callers = defaultdict(lambda: {"count": 0, "total_ms": 0.0, "lock_wait_ms": 0.0, "max_ms": 0.0})
    for row in records:
        if row["timestamp"] < since:
            continue
        entry = callers[row.get("instance_id") or "unauthenticated"]
        entry["count"] += 1
        entry["total_ms"] += row["total_ms"]
        entry["lock_wait_ms"] += row["lock_wait_ms"]
        entry["max_ms"] = max(entry["max_ms"], row["total_ms"])
    rows = [{"instance_id": name, **{k: round(v, 3) for k, v in stats.items()}}
            for name, stats in callers.items()]
    return {
        "by_count": sorted(rows, key=lambda row: (-row["count"], -row["total_ms"])),
        "by_time": sorted(rows, key=lambda row: -row["total_ms"]),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--log", type=Path, default=Path.home() / ".mco/logs/gateway-slow.log")
    parser.add_argument("--minutes", type=float, default=10)
    args = parser.parse_args()
    if not args.log.exists():
        parser.error(f"Slow-request log not found: {args.log}. Deploy the middleware and observe live traffic first.")
    records = []
    malformed = 0
    for path in [args.log, *[Path(str(args.log) + f".{index}") for index in range(1, 4)]]:
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                try:
                    row = json.loads(line)
                    if not all(isinstance(row.get(key), (int, float))
                               for key in ("timestamp", "total_ms", "lock_wait_ms")):
                        raise ValueError("invalid timing record")
                    records.append(row)
                except (ValueError, TypeError):
                    malformed += 1
    now = time.time()
    print(json.dumps({"window_minutes": args.minutes, "generated_at": now,
                      "malformed_lines": malformed,
                      **summarize(records, since=now - args.minutes * 60)}, indent=2))


if __name__ == "__main__":
    main()
