"""Decide which of froot's own open bump PRs no longer deserve to stay open.

Branch names are per *version* (``froot/dependency-patch/<pkg>-<target>``), so a
package that gets a newer patch (``1.2.3`` then ``1.2.4``) ends up with a
*second* open PR — the stale one is never closed by the propose path. This pure
policy is the cleanup: given the repo's open PRs and the same upgrade facts the
scan tick gathered, it returns the froot PRs to close, each with its note.

Two reasons, both read off ground truth (the live ``AvailableUpgrade`` set), so
the policy only closes on a *positive* match and otherwise leaves a PR alone:

* **superseded** — a newer patch target for that package is being proposed now,
  so the older PR's version is below the current best.
* **satisfied** — the base already caught up to (or past) the PR's target, so
  merging it would be a no-op.

Like the rest of froot this stores nothing: the close set is re-derived from the
repo each tick. A PR that can't be matched to a live upgrade (its package is no
longer outdated at all, or its branch doesn't parse) is deliberately left open —
reconcile fails safe, never guessing a close.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from froot.domain.base import Frozen
from froot.domain.pull_request import PullRequestRef
from froot.domain.version import Version
from froot.policy.candidates import select_patch_candidates
from froot.policy.compose import CLOSE_MARKER
from froot.policy.naming import branch_package_prefix
from froot.result import Ok

if TYPE_CHECKING:
    from froot.domain.candidate import AvailableUpgrade


class ReconcileClosure(Frozen):
    """A froot PR reconcile decided to close, plus the note to leave on it.

    Attributes:
        pr: The open PR to close (its branch is deleted with it).
        comment: The human-facing reason, carrying :data:`CLOSE_MARKER` so the
            close posts through the idempotent comment path.
    """

    pr: PullRequestRef
    comment: str


def reconciliations(
    open_prs: tuple[PullRequestRef, ...],
    upgrades: tuple[AvailableUpgrade, ...],
) -> tuple[ReconcileClosure, ...]:
    """The froot PRs to close this tick, derived from the live upgrade facts.

    Args:
        open_prs: Every open PR on the repo (froot's and not — non-froot
            branches simply never match a bump prefix).
        upgrades: The outdated dependencies and their available versions, as
            the scan gathered them. Both the current candidates and the
            installed versions are derived from these.

    Returns:
        One :class:`ReconcileClosure` per froot PR that is superseded by a newer
        target or already satisfied by the base, in PR-number order.
    """
    candidates = {c.package: c for c in select_patch_candidates(upgrades)}
    installed = {u.package: u.current for u in upgrades}
    closures: list[ReconcileClosure] = []
    for pr in sorted(open_prs, key=lambda p: p.number):
        matched = _match_pr(pr, upgrades)
        if matched is None:
            continue
        package, pr_target = matched
        candidate = candidates.get(package)
        if candidate is not None and pr_target < candidate.target:
            closures.append(
                ReconcileClosure(
                    pr=pr, comment=_superseded_comment(candidate.target)
                )
            )
        elif pr_target <= installed[package]:
            closures.append(
                ReconcileClosure(
                    pr=pr, comment=_satisfied_comment(installed[package])
                )
            )
    return tuple(closures)


def _match_pr(
    pr: PullRequestRef, upgrades: tuple[AvailableUpgrade, ...]
) -> tuple[str, Version] | None:
    """The ``(package, target)`` a froot bump PR is for, or ``None``.

    Matches the PR's branch against each upgrade's bump prefix and parses the
    remainder as a version — so a branch is attributed to a package only when
    the tail is a real version, which disambiguates packages whose slugs prefix
    one another (``foo`` vs ``foo-bar``). The longest matching prefix wins, so a
    pathological exact collision still resolves deterministically.
    """
    best: tuple[str, Version, int] | None = None
    for upgrade in upgrades:
        prefix = branch_package_prefix(upgrade.package)
        if not pr.branch.value.startswith(prefix):
            continue
        match Version.parse(pr.branch.value[len(prefix) :]):
            case Ok(version):
                if best is None or len(prefix) > best[2]:
                    best = (upgrade.package, version, len(prefix))
            case _:
                continue
    return (best[0], best[1]) if best is not None else None


def _superseded_comment(superseding: Version) -> str:
    """The note for a PR a newer patch target has overtaken."""
    return "\n".join(
        (
            CLOSE_MARKER,
            f"froot closed this PR: a newer patch ({superseding}) supersedes "
            "it. The newer bump is being proposed in its place.",
        )
    )


def _satisfied_comment(installed: Version) -> str:
    """The note for a PR the base has already caught up to."""
    return "\n".join(
        (
            CLOSE_MARKER,
            f"froot closed this PR: the base already has {installed}, so this "
            "bump is moot.",
        )
    )
