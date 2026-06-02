"""A patch candidate: a dependency with a clean patch-level upgrade available.

This is the loop's bounded unit of work. Its single, load-bearing invariant —
the target *is* a patch bump of the current version — is enforced at
construction, so the rest of the system can treat any :class:`PatchCandidate` it
holds as already-validated. A candidate that changes the major or minor, goes
backward, or steps onto a prerelease simply cannot be built.
"""

from __future__ import annotations

from typing import Self

from pydantic import Field, model_validator

from froot.domain.base import Frozen
from froot.domain.ecosystem import Ecosystem
from froot.domain.version import Version


class PatchCandidate(Frozen):
    """A proposed patch-level upgrade of a single dependency.

    Attributes:
        package: The dependency's name (e.g. ``"left-pad"`` or a scoped
            ``"@scope/pkg"``).
        ecosystem: The package manager the dependency belongs to.
        current: The installed version.
        target: The proposed version — guaranteed a clean patch bump of
            ``current`` (see :meth:`Version.is_patch_bump_of`).
    """

    package: str = Field(min_length=1)
    ecosystem: Ecosystem
    current: Version
    target: Version

    @model_validator(mode="after")
    def _require_patch_bump(self) -> Self:
        """Reject any candidate whose target is not a clean patch bump."""
        if not self.target.is_patch_bump_of(self.current):
            raise ValueError(
                f"{self.target} is not a clean patch bump of {self.current} "
                f"for {self.package!r}"
            )
        return self

    def __str__(self) -> str:
        """Render as ``package current -> target``."""
        return f"{self.package} {self.current} -> {self.target}"


class AvailableUpgrade(Frozen):
    """An installed dependency and the published versions it could move to.

    The raw material the package-manager adapter reports (e.g. from ``npm
    outdated`` + the published version list). It is deliberately *not* yet a
    :class:`PatchCandidate`: choosing which available version is the right
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
