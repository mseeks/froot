"""Semantic versions and the patch-bump relation.

:class:`Version` is the value object the whole loop turns on: the deterministic
signal is "a higher patch of a dependency exists", and *patch* is a precise
relation between two versions, encoded in :meth:`Version.is_patch_bump_of`.
Because :class:`~froot.domain.candidate` enforces that relation at construction,
a candidate that is *not* a patch bump is unrepresentable.

Parsing untrusted version strings is a boundary concern, so
:meth:`Version.parse` returns a :class:`~froot.result.Result`, not an exception.
"""

from __future__ import annotations

import re
from functools import total_ordering

from froot.domain.base import Frozen
from froot.result import Err, Ok, Result

# major.minor.patch with an optional -prerelease and an ignored +build segment.
_SEMVER = re.compile(
    r"""
    ^\s*v?                         # tolerate a leading 'v'
    (?P<major>0|[1-9]\d*)\.
    (?P<minor>0|[1-9]\d*)\.
    (?P<patch>0|[1-9]\d*)
    (?:-(?P<prerelease>[0-9A-Za-z.-]+))?
    (?:\+[0-9A-Za-z.-]+)?           # build metadata: parsed away, not compared
    \s*$
    """,
    re.VERBOSE,
)


@total_ordering
class Version(Frozen):
    """A semantic version, ordered and comparable.

    Attributes:
        major: The major component (breaking changes).
        minor: The minor component (backward-compatible features).
        patch: The patch component (backward-compatible fixes).
        prerelease: The prerelease tag (e.g. ``rc.1``), or ``None`` for a
            stable release. A prerelease sorts below its stable release.
    """

    major: int
    minor: int
    patch: int
    prerelease: str | None = None

    @classmethod
    def parse(cls, text: str) -> Result[Version, str]:
        """Parse a semantic-version string at the untrusted boundary.

        Args:
            text: A version string such as ``"1.4.2"`` or ``"2.0.0-rc.1"``.
                A leading ``v`` and ``+build`` metadata are tolerated.

        Returns:
            ``Ok(Version)`` on success, or ``Err(message)`` if the string is
            not a recognizable semantic version.
        """
        match = _SEMVER.match(text)
        if match is None:
            return Err(f"not a semantic version: {text!r}")
        return Ok(
            cls(
                major=int(match["major"]),
                minor=int(match["minor"]),
                patch=int(match["patch"]),
                prerelease=match["prerelease"],
            )
        )

    @property
    def is_stable(self) -> bool:
        """True when this is a stable release (no prerelease tag)."""
        return self.prerelease is None

    @property
    def _sort_key(self) -> tuple[int, int, int, int, str]:
        # A stable release outranks its prereleases: (…, 1, "") > (…, 0, tag).
        # Prerelease-vs-prerelease compares the tag lexically, NOT by SemVer §11
        # numeric-identifier rules (so "rc.2" sorts after "rc.10"). That is
        # deliberate: the patch loop only ever compares stable versions
        # (is_patch_bump_of requires both ends stable), so this path is unused.
        rank = 1 if self.prerelease is None else 0
        return (self.major, self.minor, self.patch, rank, self.prerelease or "")

    def is_patch_bump_of(self, other: Version) -> bool:
        """Whether this version is a clean patch-level upgrade of ``other``.

        A patch bump keeps the major and minor fixed, raises the patch, and is
        stable on both ends. Prereleases are never clean patch bumps: a loop
        that proposed ``1.4.2 -> 1.4.3-rc.1`` would be proposing instability.

        Args:
            other: The currently installed version.

        Returns:
            True iff ``self`` is the same ``major.minor`` as ``other`` with a
            strictly higher, stable patch.
        """
        return (
            self.is_stable
            and other.is_stable
            and self.major == other.major
            and self.minor == other.minor
            and self.patch > other.patch
        )

    def __lt__(self, other: object) -> bool:
        """Order by ``major.minor.patch`` then prerelease rank."""
        if not isinstance(other, Version):
            return NotImplemented
        return self._sort_key < other._sort_key

    def __str__(self) -> str:
        """Render as ``major.minor.patch[-prerelease]``."""
        base = f"{self.major}.{self.minor}.{self.patch}"
        return f"{base}-{self.prerelease}" if self.prerelease else base
