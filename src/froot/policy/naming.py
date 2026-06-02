"""Deterministic names — the loop's idempotency keys.

A bump's head branch and its per-bump Temporal workflow id are pure functions of
the bump identity (repo + package + target version). Re-running the loop reuses
the same names, so a duplicate PR or a duplicate in-flight workflow is
impossible: the loop is idempotent by construction (SPEC: one PR per bump). The
scan loop's id is a per-repo singleton for the same reason.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from froot.domain.pull_request import BranchName

if TYPE_CHECKING:
    from froot.domain.candidate import PatchCandidate
    from froot.domain.repo import TargetRepo

_BRANCH_PREFIX = "froot/dependency-patch"
# Anything outside the safe set collapses to a single hyphen.
_UNSAFE = re.compile(r"[^a-z0-9._-]+")


def _slug(text: str) -> str:
    """Lowercase and reduce ref/id-unsafe runs to single hyphens."""
    return _UNSAFE.sub("-", text.lower()).strip("-")


def branch_name(candidate: PatchCandidate) -> BranchName:
    """The deterministic head branch for a bump (also the PR dedup key)."""
    return BranchName(
        value=f"{_BRANCH_PREFIX}/{_slug(candidate.package)}-{candidate.target}"
    )


def bump_workflow_id(repo: TargetRepo, candidate: PatchCandidate) -> str:
    """The deterministic per-bump workflow id (the dispatch dedup key)."""
    return "-".join(
        (
            "froot-bump",
            _slug(repo.repo.owner),
            _slug(repo.repo.name),
            _slug(candidate.package),
            _slug(str(candidate.target)),
        )
    )


def scan_workflow_id(repo: TargetRepo) -> str:
    """The deterministic per-repo scan-loop workflow id (a singleton)."""
    return "-".join(
        ("froot-scan", _slug(repo.repo.owner), _slug(repo.repo.name))
    )
