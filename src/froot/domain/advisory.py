"""A security advisory and its affected version ranges — the security signal.

The raw facts the OSV adapter shapes at the boundary, kept as strings so the
*decision* (does the installed version fall in a vulnerable range, and what is
the lowest version that clears it) stays in the pure
:func:`froot.policy.candidates.select_security_candidates`, where it is tested
without the network. One :class:`Advisory` is one vulnerability affecting one
package; its :class:`VulnRange` entries are that package's affected spans.
"""

from __future__ import annotations

from pydantic import Field

from froot.domain.base import Frozen
from froot.domain.ecosystem import Ecosystem


class VulnRange(Frozen):
    """One affected span: vulnerable from ``introduced`` up to ``fixed``.

    Attributes:
        introduced: The first affected version, or ``"0"`` for "from the start"
            (OSV's convention). A raw version string, parsed by the policy.
        fixed: The version the span is fixed in (the clearing target), or
            ``None`` when this span has no published fix.
    """

    introduced: str = Field(min_length=1)
    fixed: str | None = None


class Advisory(Frozen):
    """One vulnerability affecting one package, with its affected ranges.

    Attributes:
        id: The advisory's primary id (e.g. a ``GHSA-…``).
        aliases: Other ids for the same vulnerability (``CVE-…``, ``PYSEC-…``),
            surfaced in the PR so the human can look it up.
        package: The affected dependency's name.
        ecosystem: The package manager it belongs to.
        ranges: The affected spans; the policy finds the one holding the
            installed version to read its clearing target.
    """

    id: str = Field(min_length=1)
    aliases: tuple[str, ...] = ()
    package: str = Field(min_length=1)
    ecosystem: Ecosystem
    ranges: tuple[VulnRange, ...]
