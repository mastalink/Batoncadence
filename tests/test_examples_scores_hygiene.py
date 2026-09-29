"""G — examples/scores CI hygiene: schema load + Beast-path allowlist."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from mco.orchestrator.scores import ScoreError, load_score

ROOT = Path(__file__).parents[1]
SCORES_DIR = ROOT / "examples" / "scores"

# Grandfathered intentional Beast / absolute host paths on scores that already
# shipped on main. New files MUST NOT appear here and must stay path-clean.
BEAST_PATH_ALLOWLIST = {
    "drumline-agent-exchange.score.json",
    "jev-integration-preflight.score.json",
    "usage-capacity-u01.score.json",
    "via-cloud-repository-continuation.score.json",
    "via-cloud-repository-slice.score.json",
}

BEAST_PATH_RE = re.compile(
    r"(C:/AI/|C:\\\\AI\\\\|/Users/|/home/[A-Za-z0-9_.-]+/AI/)",
    re.IGNORECASE,
)


def _score_files() -> list[Path]:
    return sorted(SCORES_DIR.glob("*.score.json"))


@pytest.mark.parametrize("path", _score_files(), ids=lambda p: p.name)
def test_every_example_score_loads(path: Path):
    """Fail CI when any examples/scores/*.score.json is schema-invalid."""
    try:
        value = load_score(path.read_text(encoding="utf-8"))
    except ScoreError as exc:
        pytest.fail(f"{path.name} failed schema/load: {exc}")
    assert value["score_version"] == 1
    assert value["id"]
    assert value["tasks"]


@pytest.mark.parametrize("path", _score_files(), ids=lambda p: p.name)
def test_beast_paths_grandfathered_or_absent(path: Path):
    text = path.read_text(encoding="utf-8")
    has_beast = bool(BEAST_PATH_RE.search(text))
    if path.name in BEAST_PATH_ALLOWLIST:
        # Allowlisted files may keep historical Beast paths; flag presence for skim.
        assert has_beast, f"{path.name} is allowlisted but has no Beast path — trim allowlist"
        return
    assert not has_beast, (
        f"{path.name} introduces Beast/absolute host paths; "
        "new scores must use abstract resources only"
    )


def test_allowlist_only_references_existing_files():
    names = {p.name for p in _score_files()}
    missing = sorted(BEAST_PATH_ALLOWLIST - names)
    assert missing == [], f"allowlist entries missing from examples/scores: {missing}"


def test_inventory_documents_grandfathered_beast_scores():
    """Documented warning inventory: every allowlisted score still has C:/AI/..."""
    flagged = []
    for name in sorted(BEAST_PATH_ALLOWLIST):
        text = (SCORES_DIR / name).read_text(encoding="utf-8")
        hits = sorted(set(BEAST_PATH_RE.findall(text)))
        assert hits, name
        flagged.append((name, hits))
    assert len(flagged) == len(BEAST_PATH_ALLOWLIST)
