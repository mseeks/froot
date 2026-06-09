"""A removal: a single piece of dead weight a loop wants to delete.

The dead-code loop's bounded unit of work — the other work-item *kind* beside a
:class:`~froot.domain.candidate.Candidate` bump. v1 carries one shape: an
*unused dependency* a static analyzer (knip / deptry) flagged, which the loop
removes from the manifest and relocks, with CI as the oracle. The action is a
deletion, not a version move, so a removal has no ``target`` and never touches
the forward-stable invariant a candidate must satisfy — which is exactly why the
work item had to widen past :class:`Candidate`.

``justification`` carries the signal's "why" (e.g. the analyzer's finding) to
the PR body and the safe-to-remove judge, the same role it plays on a candidate.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from froot.domain.base import Frozen
from froot.domain.ecosystem import Ecosystem


class Removal(Frozen):
    """A proposed removal of a single unused dependency.

    Attributes:
        kind: The work-item discriminator — always ``"removal"``.
        package: The dependency to remove.
        ecosystem: The package manager it belongs to.
        dev: Whether it is a development dependency (so the manifest edit
            and the PR framing name the right section).
        justification: A short "why" — the analyzer's finding (e.g.
            ``"unused (knip)"``); carried to the PR body and the judge.
    """

    kind: Literal["removal"] = "removal"
    package: str = Field(min_length=1)
    ecosystem: Ecosystem
    dev: bool = False
    justification: str | None = None

    @property
    def subject(self) -> str:
        """The work item's human-readable identifier (its package)."""
        return self.package

    def __str__(self) -> str:
        """Render as ``remove package (unused)``."""
        return f"remove {self.package} (unused)"
