#!/usr/bin/env bash
# Shim-proof CLI wrapper (macOS/Linux): runs the CLI through the project venv's
# interpreter from the repo root, so relative config paths and the entrypoint
# resolve regardless of cwd or PATH ordering.
#
#   scripts/mco.sh serve
#   scripts/mco.sh workflow configs/workflows/qa_loop.yaml --dry-run
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
py="$root/.venv/bin/python"
[ -x "$py" ] || { echo "No venv found. Create one: python -m venv .venv && .venv/bin/pip install -e .[dev]" >&2; exit 1; }
cd "$root"
exec "$py" -m mco.cli "$@"
