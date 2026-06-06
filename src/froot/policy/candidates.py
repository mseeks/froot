"""Candidate selection: each loop's notion of "the right target", pure.

Given the raw facts an adapter gathered, decide the version to propose and build
a :class:`Candidate`. dependency-patch picks the *highest stable patch* of the
installed version; security-patch picks the *lowest version that clears every
advisory* affecting it (often a minor or major bump). The adapters gather facts
(:class:`AvailableUpgrade`, :class:`Advisory`); the decisions live here, where
they are tested without the network, and both end sorted by package.
"""

from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING

from froot.domain.candidate import AvailableUpgrade, Candidate
from froot.domain.version import Version
from froot.result import Ok

if TYPE_CHECKING:
    from collections.abc import Iterable

    from froot.domain.advisory import Advisory
    from froot.domain.candidate import InstalledPackage


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
) -> tuple[Candidate, ...]:
    """Reduce available upgrades to the patch candidates worth proposing.

    Args:
        upgrades: The raw availability facts, one per outdated dependency.

    Returns:
        One :class:`Candidate` per dependency that has a patch-level
        upgrade (targeting the highest available patch), sorted by package.
        Dependencies whose only upgrades cross the minor/major line — or step
        onto a prerelease — are dropped.
    """
    candidates = [
        Candidate(
            package=upgrade.package,
            ecosystem=upgrade.ecosystem,
            current=upgrade.current,
            target=target,
        )
        for upgrade in upgrades
        if (target := _best_patch_target(upgrade)) is not None
    ]
    return tuple(sorted(candidates, key=lambda candidate: candidate.package))


def _introduced_reached(version: Version, introduced: str) -> bool:
    """Whether ``version`` is at or past an advisory range's lower bound."""
    if introduced == "0":  # OSV's "from the start"
        return True
    match Version.parse(introduced):
        case Ok(bound):
            return version >= bound
        case _:
            return False  # unparseable bound — conservatively not in range


def _clearing_version(version: Version, advisory: Advisory) -> Version | None:
    """The lowest version that clears ``advisory`` for ``version``, or ``None``.

    Finds the advisory's affected range that holds ``version`` and returns its
    fixed version. ``None`` when the holding range has no published fix, or its
    fix doesn't parse as a stable semver (conservative: froot won't propose a
    bump it can't reason about).
    """
    for span in advisory.ranges:
        if not _introduced_reached(version, span.introduced):
            continue
        if span.fixed is None:
            continue
        match Version.parse(span.fixed):
            case Ok(fixed) if version < fixed:
                return fixed
            case _:
                continue
    return None


def _justification(cleared: list[Advisory], others_remain: bool) -> str:
    """The PR-body "why": the advisories this bump clears, honestly.

    Names only the advisories the target actually clears, never implying it
    clears more. If the package has *other* advisories with no usable fix, it
    says so plainly rather than letting the reviewer assume the bump is a full
    fix — froot only bumps direct deps, so the rest are out of its reach.
    """
    names = [", ".join((a.id, *a.aliases)) for a in cleared]
    body = "Clears " + "; ".join(names) + "."
    if others_remain:
        body += (
            " Note: this package has further advisories with no usable fix; "
            "this bump does not clear those."
        )
    return body


def select_security_candidates(
    installed: tuple[InstalledPackage, ...],
    advisories: tuple[Advisory, ...],
) -> tuple[Candidate, ...]:
    """Reduce installed packages + advisories to the security bumps to propose.

    Args:
        installed: The direct dependencies and their locked versions.
        advisories: The advisories affecting them (one per vulnerability).

    Returns:
        One :class:`Candidate` per package with at least one clearable advisory,
        targeting the *lowest version that clears those* (the max of the
        per-advisory fixes), justified by the advisory ids. When a package also
        has advisories with no usable fix, the bump is still proposed (it cuts
        the surface) and the justification says the rest are not cleared. A
        package with no clearable advisory at all is dropped. Sorted by package.
    """
    by_package: dict[tuple[str, object], list[Advisory]] = defaultdict(list)
    for advisory in advisories:
        by_package[(advisory.package, advisory.ecosystem)].append(advisory)

    candidates: list[Candidate] = []
    for package in installed:
        package_advisories = by_package.get(
            (package.package, package.ecosystem), []
        )
        cleared: list[Advisory] = []
        target: Version | None = None
        for advisory in package_advisories:
            fix = _clearing_version(package.version, advisory)
            if fix is None:
                continue
            cleared.append(advisory)
            target = fix if target is None else max(target, fix)
        if target is None or not target > package.version:
            continue
        candidates.append(
            Candidate(
                package=package.package,
                ecosystem=package.ecosystem,
                current=package.version,
                target=target,
                justification=_justification(
                    cleared,
                    others_remain=len(cleared) < len(package_advisories),
                ),
            )
        )
    return tuple(sorted(candidates, key=lambda candidate: candidate.package))
