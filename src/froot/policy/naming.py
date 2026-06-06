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

from froot.domain.loop import Loop
from froot.domain.pull_request import BranchName

if TYPE_CHECKING:
    from froot.domain.candidate import Candidate
    from froot.domain.repo import TargetRepo

# Anything outside the safe set collapses to a single hyphen.
_UNSAFE = re.compile(r"[^a-z0-9._-]+")


def _slug(text: str) -> str:
    """Lowercase and reduce ref/id-unsafe runs to single hyphens."""
    return _UNSAFE.sub("-", text.lower()).strip("-")


def _loop_id_segment(loop: Loop) -> tuple[str, ...]:
    """The workflow-id segment that namespaces a loop.

    Empty for ``dependency-patch`` so its ids stay byte-for-byte what they were
    before a second loop existed — the running cluster loop is not orphaned on
    deploy. Every other loop carries its name as a segment.
    """
    return () if loop is Loop.DEPENDENCY_PATCH else (loop.value,)


def branch_name(
    candidate: Candidate, loop: Loop = Loop.DEPENDENCY_PATCH
) -> BranchName:
    """The deterministic head branch for a bump (also the PR dedup key).

    Namespaced by loop (``froot/<loop>/…``) so two loops never push the same
    branch even when they target the same package and version.
    """
    return BranchName(
        value=f"froot/{loop.value}/{_slug(candidate.package)}-{candidate.target}"
    )


def branch_package_prefix(
    package: str, loop: Loop = Loop.DEPENDENCY_PATCH
) -> str:
    """The branch prefix shared by all of this loop's bumps of ``package``.

    ``branch_name`` appends ``-<target>`` to this, so an open PR belongs to this
    loop's ``package`` iff its branch starts with this prefix *and* the rest
    parses as a version (reconcile relies on that version-parse to tell apart
    packages whose slugs prefix one another — ``foo`` vs ``foo-bar``). The loop
    in the prefix scopes reconcile to its own PRs.
    """
    return f"froot/{loop.value}/{_slug(package)}-"


def bump_workflow_id(
    repo: TargetRepo, candidate: Candidate, loop: Loop = Loop.DEPENDENCY_PATCH
) -> str:
    """The deterministic per-bump workflow id (the dispatch dedup key)."""
    return "-".join(
        (
            "froot-bump",
            *_loop_id_segment(loop),
            _slug(repo.repo.owner),
            _slug(repo.repo.name),
            _slug(candidate.package),
            _slug(str(candidate.target)),
        )
    )


def scan_workflow_id(
    repo: TargetRepo, loop: Loop = Loop.DEPENDENCY_PATCH
) -> str:
    """The deterministic per-repo scan-loop workflow id (a singleton)."""
    return "-".join(
        (
            "froot-scan",
            *_loop_id_segment(loop),
            _slug(repo.repo.owner),
            _slug(repo.repo.name),
        )
    )


def review_workflow_id(repo: TargetRepo) -> str:
    """The deterministic per-repo determinism-review loop id (a singleton)."""
    return "-".join(
        ("froot-review", _slug(repo.repo.owner), _slug(repo.repo.name))
    )


def pr_review_workflow_id(
    repo: TargetRepo, pr_number: int, head_sha: str
) -> str:
    """The deterministic per-(PR, head SHA) review id (the dispatch dedup key).

    Keyed on the head SHA so a new commit triggers a fresh review, and
    re-dispatch of the same commit is a no-op (REJECT_DUPLICATE).
    """
    return "-".join(
        (
            "froot-pr-review",
            _slug(repo.repo.owner),
            _slug(repo.repo.name),
            _slug(str(pr_number)),
            _slug(head_sha[:12]),
        )
    )
