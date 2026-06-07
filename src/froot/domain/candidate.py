"""A candidate: a single dependency bump a loop wants to propose.

The loop's bounded unit of work, shared by every loop. The type enforces only
what is true for *any* loop — the target is a stable release strictly newer than
the installed version, so a candidate can never go backward or step onto a
prerelease. *How much* of a bump is allowed (patch-only for dependency-patch, or
whatever clears an advisory for security-patch) is the selecting policy's call,
not the type's — see :mod:`froot.policy.candidates`. The optional
``justification`` carries a loop's "why" (e.g. the advisories a security bump
clears) to the PR body and the judge, without any other loop having to care.
"""

from __future__ import annotations

from typing import Literal, Self

from pydantic import Field, model_validator

from froot.domain.base import Frozen
from froot.domain.ecosystem import Ecosystem
from froot.domain.version import Version


class Candidate(Frozen):
    """A proposed upgrade of a single dependency.

    One of the loop's work-item *kinds* (the other is
    :class:`~froot.domain.removal.Removal`); ``kind`` is the discriminator the
    chassis uses to route a work item to the right signal/judge/action without a
    loop having to special-case the spine.

    Attributes:
        kind: The work-item discriminator — always ``"bump"`` for a candidate.
        package: The dependency's name (e.g. ``"left-pad"`` or a scoped
            ``"@scope/pkg"``).
        ecosystem: The package manager the dependency belongs to.
        current: The installed version.
        target: The proposed version — a stable release strictly newer than
            ``current`` (the loop's policy decides how far it may reach).
        justification: An optional short "why" for loops that need one (e.g.
            ``"clears GHSA-… (CVE-…)"``); ``None`` when the bump speaks for
            itself, as a patch does.
    """

    kind: Literal["bump"] = "bump"
    package: str = Field(min_length=1)
    ecosystem: Ecosystem
    current: Version
    target: Version
    justification: str | None = None

    @model_validator(mode="after")
    def _require_forward_stable(self) -> Self:
        """Reject a target that is not a stable release newer than current."""
        if not self.target.is_stable:
            raise ValueError(
                f"{self.target} is a prerelease; not a candidate target "
                f"for {self.package!r}"
            )
        if not self.target > self.current:
            raise ValueError(
                f"{self.target} is not newer than {self.current} "
                f"for {self.package!r}"
            )
        return self

    def __str__(self) -> str:
        """Render as ``package current -> target``."""
        return f"{self.package} {self.current} -> {self.target}"


class InstalledPackage(Frozen):
    """A direct dependency and the version currently locked for it.

    The raw material the security-patch signal works from: froot can only bump a
    *direct* dependency (a transitive vuln needs its parent moved), so this is
    the set the package-manager adapter reads from the lockfile, and what OSV is
    asked about. Versions that don't parse as a :class:`Version` are dropped by
    the adapter before they get here (conservative, same as the patch loop).

    Attributes:
        package: The dependency's name.
        ecosystem: The package manager it belongs to.
        version: The installed (locked) version.
    """

    package: str = Field(min_length=1)
    ecosystem: Ecosystem
    version: Version


class AvailableUpgrade(Frozen):
    """An installed dependency and the published versions it could move to.

    The raw material the package-manager adapter reports (e.g. from ``npm
    outdated`` + the published version list). It is deliberately *not* yet a
    :class:`Candidate`: choosing which available version is the right
    patch-level target is business logic, and it lives in the pure
    :func:`froot.policy.candidates.select_patch_candidates`, not in the adapter.

    Attributes:
        package: The dependency's name.
        ecosystem: The package manager it belongs to.
        current: The installed version.
        available: The published versions that could be upgraded to (any
            order; the policy selects among them).
    """

    package: str = Field(min_length=1)
    ecosystem: Ecosystem
    current: Version
    available: tuple[Version, ...]
