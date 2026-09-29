"""C2 — Shadow-mode GitHub evidence verifier (fixtures only).

Verifies pull_request / check_runs / review claims against fake GitHub JSON.
Never talks to the live API and never holds App tokens. Missing CI fails closed
(would_refuse). Shadow mode reports only — no merge, no status write.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence


@dataclass(frozen=True)
class ShadowVerifyReport:
    """Outcome of a shadow verification. Never mutates GitHub."""

    repo: str
    number: int
    head_sha: str
    accepted: bool
    would_refuse: tuple[str, ...]
    checked: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "repo": self.repo,
            "number": self.number,
            "head_sha": self.head_sha,
            "accepted": self.accepted,
            "would_refuse": list(self.would_refuse),
            "checked": list(self.checked),
            "notes": list(self.notes),
            "mode": "shadow",
            "mutates_github": False,
        }


@dataclass
class GitHubEvidenceVerifier:
    """Fixture-backed verifier. `fixtures` maps logical names to parsed JSON."""

    fixtures: Mapping[str, Mapping[str, Any]]
    allowed_check_apps: Sequence[str] = ("github-actions",)
    allowed_base_refs: Sequence[str] | None = None
    require_checks: Sequence[str] = ("Verify Via",)

    def verify_pull_request_evidence(
        self,
        *,
        claim: Mapping[str, Any],
        pull_request_key: str = "pull_request",
        check_runs_key: str = "check_runs",
        review_key: str = "review",
    ) -> ShadowVerifyReport:
        return verify_pull_request_evidence(
            claim,
            fixtures=self.fixtures,
            allowed_check_apps=self.allowed_check_apps,
            allowed_base_refs=self.allowed_base_refs,
            require_checks=self.require_checks,
            pull_request_key=pull_request_key,
            check_runs_key=check_runs_key,
            review_key=review_key,
        )


def load_github_fixtures(directory: str | Path) -> dict[str, dict[str, Any]]:
    """Load `*.json` fixtures from a directory into a name→payload map."""
    root = Path(directory)
    out: dict[str, dict[str, Any]] = {}
    for path in sorted(root.glob("*.json")):
        out[path.stem] = json.loads(path.read_text(encoding="utf-8"))
    return out


def verify_pull_request_evidence(
    claim: Mapping[str, Any],
    *,
    fixtures: Mapping[str, Mapping[str, Any]],
    allowed_check_apps: Sequence[str] = ("github-actions",),
    allowed_base_refs: Sequence[str] | None = None,
    require_checks: Sequence[str] = ("Verify Via",),
    pull_request_key: str = "pull_request",
    check_runs_key: str = "check_runs",
    review_key: str = "review",
) -> ShadowVerifyReport:
    """Shadow-verify PR / check_runs / review evidence against fixtures.

    Artifact claim shape (documented for packet C2):
      {
        "repo": "owner/name",
        "number": 41,
        "head_sha": "<40-hex>",
        "base_ref": "codex/via-foundation",
        "expected_base_sha": "<40-hex optional>",
        "required_checks": ["Verify Via"],   # optional override
        "author_login": "copilot-swe-agent", # optional
        "reviewer_login": "codex-bot"        # optional; must differ from author
      }

    Fixture keys referenced relative to claim.number / claim.repo:
      pull_request → fixtures[pull_request_key] or fixtures[f"pr-{number}"]
      check_runs   → fixtures[check_runs_key] or fixtures[f"checks-{number}"]
      review       → fixtures[review_key] or fixtures[f"review-{number}"]
    """
    refuses: list[str] = []
    checked: list[str] = []
    notes: list[str] = []

    repo = str(claim.get("repo") or "")
    number = int(claim.get("number") or 0)
    head_sha = str(claim.get("head_sha") or "").lower()
    base_ref = str(claim.get("base_ref") or "")
    expected_base = str(claim.get("expected_base_sha") or "").lower() or None
    required = tuple(claim.get("required_checks") or require_checks)

    pr = _pick_fixture(fixtures, pull_request_key, f"pr-{number}")
    if pr is None:
        refuses.append("pull_request_fixture_missing")
        return ShadowVerifyReport(repo, number, head_sha, False, tuple(refuses), tuple(checked), tuple(notes))

    checked.append("pull_request")
    if pr.get("head", {}).get("sha", "").lower() != head_sha:
        refuses.append("head_sha_mismatch")
    if pr.get("base", {}).get("ref") != base_ref and base_ref:
        refuses.append("base_ref_mismatch")
    if allowed_base_refs is not None and base_ref and base_ref not in allowed_base_refs:
        refuses.append("base_ref_not_allowed")
    if expected_base and pr.get("base", {}).get("sha", "").lower() != expected_base:
        # Descendant policy deferred; exact match only in shadow v0.
        refuses.append("base_sha_mismatch")
    if pr.get("head", {}).get("repo", {}).get("fork") is True:
        refuses.append("fork_head_ignored")
        notes.append("fork PRs are ignored in shadow v0")

    author = str(claim.get("author_login") or pr.get("user", {}).get("login") or "")
    checks_doc = _pick_fixture(fixtures, check_runs_key, f"checks-{number}")
    if checks_doc is None:
        refuses.append("check_runs_fixture_missing")
        refuses.append("missing_ci")
    else:
        checked.append("check_runs")
        runs = list(checks_doc.get("check_runs") or [])
        by_name = {str(r.get("name")): r for r in runs}
        for name in required:
            run = by_name.get(name)
            if run is None:
                refuses.append(f"missing_check:{name}")
                refuses.append("missing_ci")
                continue
            app_slug = str((run.get("app") or {}).get("slug") or run.get("app_slug") or "")
            if app_slug and app_slug not in allowed_check_apps:
                refuses.append(f"unallowlisted_app:{name}:{app_slug}")
                notes.append(f"ignored unallowlisted app for {name}")
                # Unallowlisted apps do not satisfy the check.
                refuses.append(f"missing_check:{name}")
                continue
            if str(run.get("head_sha") or "").lower() != head_sha:
                refuses.append(f"check_wrong_head:{name}")
                continue
            conclusion = str(run.get("conclusion") or "").lower()
            status = str(run.get("status") or "").lower()
            if status != "completed" or conclusion != "success":
                refuses.append(f"check_not_green:{name}:{status}:{conclusion or 'none'}")

    review_doc = _pick_fixture(fixtures, review_key, f"review-{number}")
    if review_doc is None:
        refuses.append("review_fixture_missing")
    else:
        checked.append("review")
        state = str(review_doc.get("state") or "").lower()
        reviewer = str(
            claim.get("reviewer_login")
            or (review_doc.get("user") or {}).get("login")
            or ""
        )
        review_commit = str(review_doc.get("commit_id") or review_doc.get("head_sha") or "").lower()
        if state not in {"approved", "mco_approved"}:
            refuses.append(f"review_not_approved:{state or 'none'}")
        if review_commit and review_commit != head_sha:
            refuses.append("review_wrong_head")
        if author and reviewer and author == reviewer:
            refuses.append("reviewer_same_as_author")
        if author and reviewer and _vendor_family(author) == _vendor_family(reviewer):
            # Soft note in shadow; hard refuse when families collide and both known.
            if _vendor_family(author) != "unknown":
                refuses.append("reviewer_same_vendor_family")

    # Dedupe while preserving order.
    seen: set[str] = set()
    ordered: list[str] = []
    for reason in refuses:
        if reason not in seen:
            seen.add(reason)
            ordered.append(reason)

    accepted = not ordered
    return ShadowVerifyReport(
        repo=repo,
        number=number,
        head_sha=head_sha,
        accepted=accepted,
        would_refuse=tuple(ordered),
        checked=tuple(checked),
        notes=tuple(notes),
    )


def _pick_fixture(
    fixtures: Mapping[str, Mapping[str, Any]],
    primary: str,
    fallback: str,
) -> Mapping[str, Any] | None:
    if primary in fixtures:
        return fixtures[primary]
    if fallback in fixtures:
        return fixtures[fallback]
    return None


def _vendor_family(login: str) -> str:
    lowered = login.lower()
    if "copilot" in lowered:
        return "copilot"
    if "codex" in lowered or "openai" in lowered:
        return "codex"
    if "claude" in lowered or "anthropic" in lowered:
        return "claude"
    if "jules" in lowered:
        return "jules"
    return "unknown"
