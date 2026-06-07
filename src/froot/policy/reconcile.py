"""Decide which of a loop's own open PRs no longer deserve to stay open.

Branch names are per *version*, so a package whose target moves on (a new patch
for dependency-patch, a newer advisory's fix for security-patch) ends up with a
*second* open PR — the stale one is never closed by the propose path. This pure
policy is the cleanup: given the repo's open PRs and the loop's current
candidates (re-derived from the repo this tick), it returns the PRs to close,
each with its note.

A PR is closed when it is **superseded** — the loop's current candidate for that
package targets a newer version than the PR does, so the PR's bump is stale.
(That also subsumes "the base already caught up": any candidate's ``current`` is
below its ``target``, so a PR at or below ``current`` is below ``target`` too.)
Matching is loop-scoped and fail-safe: a PR is attributed to a package only when
its branch carries that loop's prefix *and* the remaining tail parses as a
version — so the two loops never reconcile each other's PRs, slug collisions
(``foo`` vs ``foo-bar``) resolve correctly, and a PR that matches nothing is
deliberately left open. froot stores nothing; the set is re-derived each tick.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from froot.domain.base import Frozen
from froot.domain.candidate import Candidate
from froot.domain.loop import Loop
from froot.domain.pull_request import PullRequestRef
from froot.domain.version import Version
from froot.policy.compose import CLOSE_MARKER
from froot.policy.naming import branch_package_prefix
from froot.result import Ok

if TYPE_CHECKING:
    from froot.domain.work import WorkItem


class ReconcileClosure(Frozen):
    """A PR reconcile decided to close, plus the note to leave on it.

    Attributes:
        pr: The open PR to close (its branch is deleted with it).
        comment: The human-facing reason, carrying :data:`CLOSE_MARKER` so the
            close posts through the idempotent comment path.
    """

    pr: PullRequestRef
    comment: str


def reconciliations(
    open_prs: tuple[PullRequestRef, ...],
    candidates: tuple[WorkItem, ...],
    loop: Loop = Loop.DEPENDENCY_PATCH,
) -> tuple[ReconcileClosure, ...]:
    """The loop's PRs to close this tick, derived from its current candidates.

    Args:
        open_prs: Every open PR on the repo (other loops' and humans' branches
            simply never match this loop's prefix).
        candidates: This loop's current work items. Only *bumps* supersede (they
            carry a version); removals carry none, so they are ignored here — a
            removal loop's stale-PR cleanup is a separate concern.
        loop: Which loop is reconciling — scopes the branch matching to its own
            namespace.

    Returns:
        One :class:`ReconcileClosure` per of this loop's PRs that targets a
        version below the loop's current candidate for that package, in
        PR-number order.
    """
    bumps = tuple(c for c in candidates if isinstance(c, Candidate))
    by_package = {candidate.package: candidate for candidate in bumps}
    closures: list[ReconcileClosure] = []
    for pr in sorted(open_prs, key=lambda p: p.number):
        matched = _match_pr(pr, bumps, loop)
        if matched is None:
            continue
        package, pr_target = matched
        candidate = by_package[package]
        if pr_target < candidate.target:
            closures.append(
                ReconcileClosure(
                    pr=pr, comment=_superseded_comment(candidate.target)
                )
            )
    return tuple(closures)


def _match_pr(
    pr: PullRequestRef, candidates: tuple[Candidate, ...], loop: Loop
) -> tuple[str, Version] | None:
    """The ``(package, target)`` a PR's branch is for, within this loop.

    Matches the PR's branch against each candidate's loop prefix and parses the
    remainder as a version — so a branch maps to a package only when the
    tail is a real version, which disambiguates packages whose slugs prefix one
    another (``foo`` vs ``foo-bar``). The longest matching prefix wins, so a
    pathological exact collision still resolves deterministically.
    """
    best: tuple[str, Version, int] | None = None
    for candidate in candidates:
        prefix = branch_package_prefix(candidate.package, loop)
        if not pr.branch.value.startswith(prefix):
            continue
        match Version.parse(pr.branch.value[len(prefix) :]):
            case Ok(version):
                if best is None or len(prefix) > best[2]:
                    best = (candidate.package, version, len(prefix))
            case _:
                continue
    return (best[0], best[1]) if best is not None else None


def _superseded_comment(superseding: Version) -> str:
    """The note for a PR a newer target has overtaken."""
    return "\n".join(
        (
            CLOSE_MARKER,
            f"froot closed this PR: a newer target ({superseding}) supersedes "
            "it. The newer bump is being proposed in its place.",
        )
    )
