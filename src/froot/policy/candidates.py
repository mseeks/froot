"""Candidate selection: choose the patch-level target for each upgrade.

Pure business logic — the loop's notion of "the right target". Given the
versions available for each outdated dependency, pick the *highest stable patch*
of the installed version and build a :class:`PatchCandidate`. Dependencies with
no patch-level upgrade are dropped; the result is sorted by package for a
stable, reviewable order. The package-manager adapter only gathers raw facts
(:class:`AvailableUpgrade`); the decision lives here, where it is testable.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from froot.domain.candidate import AvailableUpgrade, PatchCandidate

if TYPE_CHECKING:
    from collections.abc import Iterable

    from froot.domain.version import Version


def _best_patch_target(upgrade: AvailableUpgrade) -> Version | None:
    """The highest available stable patch of the installed version, if any."""
    patches = [
        version
        for version in upgrade.available
        if version.is_patch_bump_of(upgrade.current)
    ]
    return max(patches) if patches else None


def select_patch_candidates(
    upgrades: Iterable[AvailableUpgrade],
) -> tuple[PatchCandidate, ...]:
    """Reduce available upgrades to the patch candidates worth proposing.

    Args:
        upgrades: The raw availability facts, one per outdated dependency.

    Returns:
        One :class:`PatchCandidate` per dependency that has a patch-level
        upgrade (targeting the highest available patch), sorted by package.
        Dependencies whose only upgrades cross the minor/major line — or step
        onto a prerelease — are dropped.
    """
    candidates = [
        PatchCandidate(
            package=upgrade.package,
            ecosystem=upgrade.ecosystem,
            current=upgrade.current,
            target=target,
        )
        for upgrade in upgrades
        if (target := _best_patch_target(upgrade)) is not None
    ]
    return tuple(sorted(candidates, key=lambda candidate: candidate.package))
